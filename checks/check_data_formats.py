"""Every JSON file under ``data/``, read the way each claimed Minecraft version reads it.

The game reads a data file with the codec of its own version and skips any key
that codec does not know, without a word in the log. When Mojang renames a key,
a file written for the old name keeps loading on the new version and simply
loses what that key carried. 26.3 renamed the loot table keys (``functions`` ->
``modifier``, ``function`` -> ``type``, ``conditions`` -> ``condition``,
``condition`` -> ``type``), and every Moog mod's chests lost their stack counts,
enchantments and pool conditions there while loading cleanly.

For every version the mod claims (``core/claims.py``), this check works out
which files that version loads (folder spelling, ``pack.mcmeta`` overlays) and
reads each one with that version's format (``core/formats.py``,
``core/mcdoc.py``). It reports:

* a key that version ignores, when the object does not also carry the form that
  version reads -- the silent loss above (ERROR). The same object written in
  both forms, each version reading its own, passes.
* a key that version ignores and has no replacement for, such as a field added
  later (WARN: the version loses that feature, nothing else).
* a key no version reads -- a typo or a leftover (ERROR).
* a required field that version needs and the file lacks, a value of the wrong
  kind, or a ``minecraft:`` id or tag that version does not have -- the game
  refuses the whole file there (ERROR).
* a file in a folder spelling that version does not load (ERROR).
* a loot table, item modifier or predicate whose two forms disagree, where 1.21
  to 26.2 read one form and 26.3 the other: side by side in one file (one object,
  for item modifiers and predicates), or across a base file and a pack overlay
  that only one side loads, where the whole table must agree: every field, and
  no pool or entry missing from either copy (ERROR).

A claimed version the format model has not been proven against fails too:
the check cannot vouch for a version nobody has checked it against.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from core.claims import claimed_versions, resolve_claims
from core.context import services
from core.formats import Pack, classify, effective_files, load_model, neighbour_lists, read_tag, version_reader
from core.loot_forms import FORM_KINDS, LOOT_RENAME, Converter, disagreements
from core.mcdoc import Finding, version_points
from core.mcversions import parse_version
from core import msl_upgrade

if TYPE_CHECKING:
    from core.context import ValidatorContext

MAX_EXAMPLES = 4      # finding lines shown per file
MAX_FILES = 40        # files shown per message before summarising


def _ranges(versions: list[str], order: list[str]) -> str:
    """``["1.21", "1.21.1", "26.3"]`` -> ``"1.21-1.21.1, 26.3"`` (runs over ``order``)."""
    order = list(order) + sorted((v for v in versions if v not in order), key=parse_version)
    idx = {v: i for i, v in enumerate(order)}
    vs = sorted(set(versions), key=lambda v: idx[v])
    runs: list[list[str]] = []
    for v in vs:
        if runs and idx[v] == idx[runs[-1][-1]] + 1:
            runs[-1].append(v)
        else:
            runs.append([v])
    return ", ".join(r[0] if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in runs)


def _span(window) -> str:
    s, u = window
    fmt = lambda t: ".".join(str(x) for x in t)
    if s is not None and u is not None:
        return f"read from {fmt(s)} until {fmt(u)}"
    if s is not None:
        return f"read from {fmt(s)}"
    if u is not None:
        return f"read before {fmt(u)}"
    return "read on other versions"


def _severity(f: Finding) -> str | None:
    """ERROR, WARN, or None (a dual-form key: fine)."""
    if f.code in ("msl-upgrade", "no-such-kind"):
        return "WARN"
    if f.code == "foreign-key":
        if not f.counterparts:
            # Removed or moved before this version: what it carried is lost. A key
            # that only arrives later is a feature this version does not have yet.
            return "ERROR" if f.retired else "WARN"
        return None if f.counterpart_present else "ERROR"
    return "ERROR"


def _message(f: Finding) -> str:
    if f.code == "foreign-key":
        if not f.counterparts:
            if f.retired:
                return (f"`{f.key}` is ignored ({_span(f.known_window)}): it was removed or moved, and this "
                        f"object has nothing this version reads in its place")
            return f"`{f.key}` is ignored ({_span(f.known_window)}; nothing replaces it here)"
        reads = ", ".join(f"`{c}`" for c in f.counterparts)
        return f"`{f.key}` is ignored ({_span(f.known_window)}); this version reads {reads} instead, which is absent"
    if f.code == "unknown-key":
        return f"`{f.key}` is read by no version"
    if f.code == "missing":
        return f"{f.detail}; the file is rejected"
    if f.code == "unknown-id":
        return f"{f.detail}; the file is rejected"
    if f.code == "unknown-tag":
        return f"{f.detail}, so it matches nothing"
    if f.code == "no-such-kind":
        return f.detail
    if f.code == "shape":
        return f"{f.detail}; the file is rejected"
    if f.code == "not-loaded":
        return f.detail
    if f.code == "unreadable":
        return f"not valid JSON ({f.detail}); the game cannot load it"
    return f.detail


def _local_ids(files: dict[str, object], kinds: set[str], registries: set[str]) -> set[tuple[str, str]]:
    """``(registry, minecraft:id)`` for the ``minecraft:`` entries the pack itself adds."""
    out: set[tuple[str, str]] = set()
    for rel in files:
        if not rel.startswith("minecraft/"):
            continue
        res = classify(rel, kinds, registries)
        if res is None:
            continue
        reg = f"tags/{res.tag_registry}" if res.tag_registry else res.kind
        out.add((reg, res.id))
    return out


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    resources = project.data_root.parent
    if not project.data_root.exists():
        print("  no data directory -- skipped")
        return True, "skipped (no data directory)"

    try:
        model = load_model()
    except (OSError, ValueError) as e:
        print(f"  [ERROR] the format model cannot be read: {e}")
        return False, "format model missing"

    pack = Pack.read(resources, project.try_json)
    # The MSL this mod runs with: the lowest its loader files allow (raised on
    # each version to the oldest MSL published there; data/msl_builds.json).
    msl_min, msl_sources = msl_upgrade.declared_minimum(project.root)
    uses_msl = bool(msl_sources)
    builds = msl_upgrade.MslBuilds() if uses_msl else None
    allowed = _allowed_keys()
    msl_relied: dict[str, set] = defaultdict(set)   # feature -> versions where the mod depends on it
    msl_short: dict[str, set] = defaultdict(set)    # ... where it would, but allows an MSL without it
    raw_claims = list(getattr(ctx, "claims", []) or [])
    claims, problems, index = resolve_claims(svc.mcmeta, project.root, list(ctx.mc_versions), raw_claims, pack.meta)
    for p in problems:
        print(f"  [ERROR] {p}")
    versions = claimed_versions(claims)
    unknown = [v for v in ctx.mc_versions if v not in index.data_version]
    for v in unknown:
        print(f"  [ERROR] {v} is not a release the version index knows; it cannot be checked")
    order = list(index.stable_ascending)
    if not versions:
        print("  [ERROR] no claimed version to check")
        return False, "no versions"

    unverified = [v for v in versions if v not in model.verified]
    checkable = [v for v in versions if v in model.verified]
    print(f"  claimed: {_ranges(versions, order)}  (" + "; ".join(
        f"{c.source} {c.low}-{c.high}" for c in claims) + ")")
    print(f"  format model: vanilla-mcdoc {model.ref[:12]}, proven against vanilla data of "
          f"{_ranges(list(model.verified), order) if model.verified else 'nothing'}")
    for v in unverified:
        print(f"  [ERROR] {v}: the format model has not been proven against this version's vanilla data, "
              f"so nothing here can say what {v} does with this pack. Run tools/update_format_model.py.")
    resource_kinds = set(model.symbols["mcdoc/dispatcher"].get("minecraft:resource", {}))
    # (kind, id) -> file -> versions that load it from that file (a base file, an overlay)
    forms_loaded: dict = defaultdict(lambda: defaultdict(set))
    # findings[(display path, kind, finding identity)] -> versions, finding
    found: dict[tuple, list] = {}
    file_count: dict[str, set] = defaultdict(set)
    skipped_kinds: dict[str, int] = defaultdict(int)
    dual = 0
    seen_dual: set[tuple] = set()
    gaps_applied = 0
    allowed_hits: set[tuple] = set()

    # Versions whose answer must be identical share one reading: same model era,
    # same registries, same overlays.
    eras: dict[tuple, list[str]] = {}
    points = version_points(model.symbols)
    for v in checkable:
        vt = parse_version(v)
        fmt = index.pack_format.get(v)
        key = (tuple(p <= vt for p in points), _registry_fingerprint(svc, v),
               tuple(pack.active_overlays(fmt)), vt >= (1, 21),
               tuple(builds.applies(n, v, msl_min) for n in builds.features) if uses_msl else ())
        eras.setdefault(key, []).append(v)

    for key, group in eras.items():
        v = group[0]
        vt = parse_version(v)
        data = svc.mcmeta.data(v)
        registries = {k for k in data if not k.startswith("tag/")}
        overlays = pack.active_overlays(index.pack_format.get(v))
        files = effective_files(resources, overlays, project.json_files)
        reader = version_reader(model, v, data, _local_ids(files, resource_kinds, registries),
                                neighbour_lists(v, order, svc.mcmeta.data))
        loaded_kinds: set[str] = set()
        classified = {rel: classify(rel, resource_kinds, registries) for rel in files}
        # the ids this version loads from some file (a pack may ship both folder spellings)
        loaded_ids = {(r.kind, r.id) for r in classified.values() if r is not None and r.loaded_on(vt)}
        for rel in sorted(files):
            path = files[rel]
            shown = path.relative_to(resources).as_posix()
            res = classified[rel]
            if res is None or res.loaded_on(vt):
                err = []
                project.json_or_report(path, err.append)
                if err:
                    f = Finding("", "unreadable", detail=str(err[0]).splitlines()[0][:160])
                    found.setdefault((shown, res.kind if res else "data", _identity(f)), [[], f])[0].extend(group)
                    continue
            if res is None:
                parts = rel.split("/")
                skipped_kinds["/".join(parts[1:2])] += 1
                continue
            if not res.loaded_on(vt):
                if (res.kind, res.id) in loaded_ids:
                    continue  # this version loads the same id from its own folder spelling
                f = Finding("", "not-loaded", detail=(
                    f"this version does not load `{rel.split('/')[1]}/`; "
                    + ("it reads the singular folder names from 1.21" if res.read_until
                       else "it reads the plural folder names before 1.21")))
                found.setdefault((shown, res.kind, _identity(f)), [[], f])[0].extend(group)
                continue
            file_count[res.kind].add(shown)
            loaded_kinds.add(res.kind)
            if res.kind in FORM_KINDS:
                forms_loaded[(res.kind, res.id)][path].update(group)
            data_json = project.try_json(path)
            if data_json is None:
                continue  # unreadable JSON is reported by the checks that own the file
            if res.tag_registry is not None:
                fs = read_tag(data_json, res.tag_registry, reader)
            else:
                t = reader.resource_type(res.kind)
                if t is None and res.kind == "trial_spawner" and uses_msl:
                    inside, guaranteed = builds.applies("trial_spawner_configs", v, msl_min)
                    if inside and guaranteed:
                        # Vanilla has no trial spawner registry yet; MSL reads the file
                        # and its processor writes the config inline into the spawner.
                        t = model.symbols["mcdoc/dispatcher"]["minecraft:resource"].get("trial_spawner")
                        msl_relied["trial_spawner_configs"].update(group)
                    elif inside:
                        msl_short["trial_spawner_configs"].update(group)
                if t is None:
                    f = Finding("", "no-such-kind", detail=(
                        f"this version has no `{res.kind}` data, so nothing reads this file here"))
                    found.setdefault((shown, res.kind, _identity(f)), [[], f])[0].extend(group)
                    continue
                fs = reader.read(data_json, t)
                inside = builds.applies("legacy_data_upgrade", v, msl_min)[0] if uses_msl else False
                if inside:
                    # The game reads this file after Moog's Structure Lib's rewrite,
                    # as done by the oldest MSL the mod allows on this version.
                    blocks = reader._registry("block")
                    eff = builds.effective(v, msl_min)
                    up_eff, n_eff = msl_upgrade.upgrade(res.kind, data_json, blocks, eff)
                    up_all, n_all = msl_upgrade.upgrade(res.kind, data_json, blocks, None)
                    after_eff = reader.read(up_eff, t) if n_eff else fs
                    after_all = reader.read(up_all, t) if n_all else fs
                    kept_eff = {_identity(x) for x in after_eff}
                    kept_all = {_identity(x) for x in after_all}
                    raw_errors = [x for x in fs if _severity(x) == "ERROR" and model.gap_for(res.kind, v, x) is None]
                    rescued = [x for x in raw_errors if _identity(x) not in kept_eff]
                    # Only when the rewrite changes what this version does: rewrites
                    # inside a form this version ignores do not count.
                    if rescued:
                        first = rescued[0]
                        f = Finding("", "msl-upgrade", detail=f"{first.path or '(file)'}: {_message(first)}")
                        found.setdefault((shown, res.kind, ("msl-upgrade",)), [[], f])[0].extend(group)
                        msl_relied["legacy_data_upgrade"].update(group)
                    if any(_identity(x) not in kept_all for x in raw_errors if _identity(x) in kept_eff):
                        msl_short["legacy_data_upgrade"].update(group)   # a newer MSL would rescue more
                    fs = after_eff
            for f in fs:
                gap = model.gap_for(res.kind, v, f)
                if gap is not None and gap.get("scope") == "model":
                    gaps_applied += 1
                    continue
                if f.code == "unknown-key" and _is_allowed(allowed, res.kind, f):
                    allowed_hits.add((shown, f.path))
                    continue
                sev = _severity(f)
                if sev is None:
                    ident = (shown, f.path, f.key)
                    if ident not in seen_dual:
                        seen_dual.add(ident)
                        dual += 1
                    continue
                found.setdefault((shown, res.kind, _identity(f)), [[], f])[0].extend(group)

    # The two loot forms must say the same thing, wherever the claim spans a
    # version that reads the old form and one that reads the new: what each side
    # loads for an id is compared, one file or two (a base file and an overlay).
    old_side = [v for v in checkable if parse_version(v) < LOOT_RENAME]
    new_side = [v for v in checkable if parse_version(v) >= LOOT_RENAME]
    if old_side and new_side:
        newest = svc.mcmeta.data(new_side[-1])
        tags = {"minecraft:" + t for t in newest.get("tag/worldgen/structure", [])}
        for rel in project.json_files(project.data_root):
            r = classify(rel.relative_to(project.data_root).as_posix(), resource_kinds, set())
            if r is not None and r.tag_registry == "worldgen/structure":
                tags.add(r.id)
        conv = Converter(tags)
        for (kind, _rid), by_path in sorted(forms_loaded.items()):
            olds = {p: {v for v in vs if parse_version(v) < LOOT_RENAME} for p, vs in by_path.items()}
            news = {p: {v for v in vs if parse_version(v) >= LOOT_RENAME} for p, vs in by_path.items()}
            for po, vo in sorted(olds.items()):
                for pn, vn in sorted(news.items()):
                    if not vo or not vn:
                        continue
                    old = project.try_json(po)
                    new = old if po == pn else project.try_json(pn)
                    shown = pn.relative_to(resources).as_posix()
                    other = "" if po == pn else f" (the old form is read from {po.relative_to(resources).as_posix()})"
                    for where, code, msg in disagreements(kind, old, new, conv):
                        f = Finding(where, code, detail=msg + other)
                        found.setdefault((shown, kind, _identity(f)), [[], f])[0].extend(sorted(vo | vn))

    msl_short_warns: list[str] = []
    if uses_msl:
        print(f"  Moog's Structure Lib: this mod allows {msl_upgrade.fmt(msl_min)} "
              f"({'; '.join(msl_sources)})")
        for name, feat in builds.features.items():
            what = feat["what"].split(" (")[0]
            if msl_relied.get(name):
                ok = sorted(msl_relied[name], key=order.index)
                print(f"    on {_ranges(ok, order)} it runs with MSL "
                      f"{msl_upgrade.fmt(builds.effective(ok[0], msl_min))} or newer, which {what}")
            if msl_short.get(name):
                short = sorted(msl_short[name], key=order.index)
                print(f"  [ERROR] on {_ranges(short, order)} this mod allows MSL "
                      f"{msl_upgrade.fmt(builds.effective(short[0], msl_min))}, older than {feat['msl_from']}, "
                      f"the first that {what}, so the files are read without it there. Raise the "
                      f"moogs_structures minimum to {feat['msl_from']} to rely on it.")
                msl_short_warns.append(name)

    # Report: errors first, grouped by file, versions folded into ranges.
    by_file: dict[tuple[str, str], list] = defaultdict(list)
    msl_files: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    msl_examples: dict[str, tuple[str, str]] = {}
    for (shown, kind, _ident), (vs, f) in found.items():
        if f.code == "msl-upgrade":
            vr = _ranges(sorted(set(vs), key=order.index), order)
            msl_files[vr][kind].append(shown)
            msl_examples.setdefault(vr, (shown, f.detail))
            continue
        by_file[(shown, "ERROR" if f.code == "not-loaded" else _severity(f))].append((vs, f, kind))

    errors = warns = 0
    error_files: dict[str, set] = defaultdict(set)
    error_versions: set[str] = set()
    for sev in ("ERROR", "WARN"):
        files_sev = sorted(k for k in by_file if k[1] == sev)
        for n_file, (shown, _s) in enumerate(files_sev):
            items = sorted(by_file[(shown, sev)], key=lambda x: (x[1].path, x[1].code))
            if sev == "ERROR":
                errors += len(items)
                for vs, f, kind in items:
                    error_files[kind].add(shown)
                    error_versions.update(vs)
            else:
                warns += len(items)
            if n_file >= MAX_FILES:
                continue
            # one line per distinct (message, versions), with example paths
            groups: dict[tuple[str, str], list[str]] = defaultdict(list)
            for vs, f, kind in items:
                groups[(_message(f), _ranges(sorted(set(vs), key=order.index), order))].append(f.path or "(file)")
            print(f"  [{sev}] {shown}")
            for (msg, vr), paths in sorted(groups.items(), key=lambda g: (g[0][1], g[0][0])):
                more = f" (+{len(paths) - MAX_EXAMPLES} more)" if len(paths) > MAX_EXAMPLES else ""
                print(f"      on {vr}: {msg}")
                if paths != ["(file)"]:
                    print(f"        at {', '.join(paths[:MAX_EXAMPLES])}{more}")
        if len(files_sev) > MAX_FILES:
            print(f"  ... and {len(files_sev) - MAX_FILES} more file(s) with {sev} findings")

    for vr, kinds in sorted(msl_files.items()):
        n = sum(len(v) for v in kinds.values())
        warns += n
        listing = ", ".join(f"{k} ({len(v)})" for k, v in sorted(kinds.items()))
        print(f"  [WARN] on {vr}: {n} file(s) load only because Moog's Structure Lib rewrites their "
              f"pre-26.3 values on load (block states, conditions, function ids, typeless number ranges): "
              f"{listing}. They work with MSL's 26.3 builds; without MSL this version would refuse them.")
        sample = [p for v in kinds.values() for p in v][:MAX_EXAMPLES]
        print(f"      e.g. {', '.join(sample)}")
        if msl_examples.get(vr):
            print(f"      first in {msl_examples[vr][0]}: {msl_examples[vr][1]}")

    total_files = len({s for fs in file_count.values() for s in fs})
    print("  by kind:")
    for kind in sorted(file_count):
        bad = len(error_files.get(kind, ()))
        print(f"    {kind}: {len(file_count[kind])} file(s){f', {bad} with errors' if bad else ''}")
    if skipped_kinds:
        print("  not vanilla data (left to their own checks): "
              + ", ".join(f"{k}/ ({n})" for k, n in sorted(skipped_kinds.items())))
    if dual:
        print(f"  {dual} key(s) written in two version forms, each version reading its own: fine")
    if gaps_applied:
        print(f"  {gaps_applied} finding(s) explained by known model gaps (data/format_model/model.json)")
    if allowed_hits:
        print(f"  {len(allowed_hits)} key(s) no version reads let through as harmless (data/allowed_keys.json)")
    errors += len(msl_short_warns)
    for name in msl_short_warns:
        error_versions.update(msl_short[name])

    failed = errors > 0 or bool(unverified) or bool(problems) or bool(unknown)
    parts = [f"{total_files} files x {len(checkable)} versions"]
    if errors:
        parts.append(f"{errors} error(s) on {_ranges(sorted(error_versions, key=order.index), order)}")
    if unverified:
        parts.append(f"{len(unverified)} version(s) the model was never proven against")
    if warns:
        parts.append(f"{warns} warning(s)")
    if not errors and not unverified:
        parts.append("0 errors")
    return not failed, ", ".join(parts)


def _allowed_keys() -> list[dict]:
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "allowed_keys.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("keys", [])
    except (OSError, ValueError):
        return []


def _is_allowed(allowed: list[dict], kind: str, f: Finding) -> bool:
    return any(a.get("kind") == kind and a.get("key") == f.key and a.get("on") in (None, f.on)
               and ("value" not in a or (f.has_value and a["value"] == f.value))
               for a in allowed)


def _identity(f: Finding) -> tuple:
    return (f.path, f.code, f.key, f.detail, f.counterparts, f.counterpart_present, f.known_window)


_FINGERPRINTS: dict[tuple[int, str], str] = {}


def _registry_fingerprint(svc, version: str) -> str:
    """Identical registry summaries give identical answers."""
    import hashlib
    import json
    data = svc.mcmeta.data(version)
    key = (id(data), version)
    if key not in _FINGERPRINTS:
        _FINGERPRINTS[key] = hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return _FINGERPRINTS[key]
