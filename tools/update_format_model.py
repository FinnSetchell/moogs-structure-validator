"""Fetch the vanilla-mcdoc model, prove it against vanilla data, and pin it.

    py -3.13 tools/update_format_model.py
    py -3.13 tools/update_format_model.py --symbols path/to/symbols.json --from 1.20

What it does:

1. Takes the compiled vanilla-mcdoc symbol table (Spyglass publishes it at
   https://api.spyglassmc.com/vanilla-mcdoc/symbols), minus the documentation
   strings.
2. For every stable release from ``--from`` to the newest one mcmeta knows,
   downloads that version's vanilla data (misode/mcmeta ``<version>-data-json``,
   cached under ``cache/vanilla/``) and reads every data file and every tag with
   the model *as that version*. Vanilla data is correct for its own version by
   definition, so anything reported there is a hole in the model (or, rarely, a
   bug in vanilla's own data).
3. Reads each release's vanilla data again as the *next* release, and lists keys
   that vanilla stopped writing but the model still accepts. That is how a
   rename the model has not caught up with would show: the old key vanishes
   from vanilla while the model keeps it. It is advisory; vanilla also stops
   using optional keys for content reasons.
4. Writes ``data/format_model/symbols.json`` and ``model.json`` (the mcdoc
   commit, every version proven clean, the known gaps) and
   ``data/format_model/VERIFICATION.md`` (what was read and what was found).

A version with an unexplained finding is left out of ``verified``, and
``check_data_formats`` then refuses to judge it. Known gaps live in
``model.json`` under ``gaps``, each with a reason; ``scope: "model"`` gaps are
also applied by the check, ``scope: "vanilla"`` ones (vanilla's own bugs) only
here.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import mcmeta  # noqa: E402
from core.formats import (MODEL_DIR, FormatModel, apply_patches, classify, neighbour_lists,  # noqa: E402
                          read_tag, version_reader)
from core.mcversions import VersionIndex  # noqa: E402

SYMBOLS_URL = "https://api.spyglassmc.com/vanilla-mcdoc/symbols"
DATA_URL = "https://github.com/misode/mcmeta/archive/refs/tags/{version}-data-json.zip"
VANILLA_CACHE = REPO / "cache" / "vanilla"


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "moogs-structure-validator"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def strip_docs(node):
    if isinstance(node, dict):
        return {k: strip_docs(v) for k, v in node.items() if k != "desc"}
    if isinstance(node, list):
        return [strip_docs(v) for v in node]
    return node


def write_symbols(symbols: dict, path: Path) -> None:
    """One symbol per line, sorted, so a model bump diffs type by type."""
    lines = ["{", f'"ref": {json.dumps(symbols.get("ref"))},']
    for section in ("mcdoc", "mcdoc/dispatcher"):
        lines.append(f"{json.dumps(section)}: {{")
        items = sorted(symbols[section].items())
        for i, (k, v) in enumerate(items):
            sep = "," if i < len(items) - 1 else ""
            lines.append(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True, separators=(',', ':'))}{sep}")
        lines.append("}," if section == "mcdoc" else "}")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def vanilla_zip(version: str) -> zipfile.ZipFile:
    VANILLA_CACHE.mkdir(parents=True, exist_ok=True)
    path = VANILLA_CACHE / f"{version}-data-json.zip"
    if not path.exists():
        print(f"  downloading vanilla data {version}...")
        path.write_bytes(_http(DATA_URL.format(version=version)))
    return zipfile.ZipFile(path)


def vanilla_files(z: zipfile.ZipFile):
    """``(data-relative path, parsed JSON)`` for every vanilla file under data/minecraft."""
    for name in sorted(z.namelist()):
        parts = name.split("/", 1)
        if len(parts) < 2 or not parts[1].startswith("data/minecraft/") or not name.endswith(".json"):
            continue
        rel = parts[1][len("data/"):]
        if rel.startswith("minecraft/datapacks/"):
            continue  # the built-in feature packs, read on their own
        yield rel, json.loads(z.read(name))


ORDER: list[str] = []


def _registry_summary(version: str) -> dict:
    return mcmeta.fetch_registry_data(version, mcmeta.CACHE_DIR, False)


def read_all(model: FormatModel, read_as: str, files, registry_data: dict, usage: dict | None = None):
    """Read vanilla files as ``read_as``. Returns (counts per kind, findings)."""
    reader = version_reader(model, read_as, registry_data, set(),
                            neighbour_lists(read_as, ORDER, _registry_summary) if ORDER else None)
    if usage is not None:
        reader.usage = usage
        reader.usage_windows = usage.setdefault("__windows__", {})
        reader.usage_paths = usage.setdefault("__paths__", {})
    kinds = set(model.symbols["mcdoc/dispatcher"].get("minecraft:resource", {}))
    registries = {k for k in registry_data if not k.startswith("tag/")}
    v = tuple(int(x) for x in read_as.split("."))
    per_kind = collections.Counter()
    findings = []
    for rel, data in files:
        res = classify(rel, kinds, registries)
        if res is None or not res.loaded_on(v):
            continue
        if res.tag_registry is not None:
            fs = read_tag(data, res.tag_registry, reader)
        else:
            t = reader.resource_type(res.kind)
            if t is None:
                continue
            reader.usage_prefix = res.kind + ":"
            fs = reader.read(data, t)
        per_kind[res.kind] += 1
        for f in fs:
            findings.append((res.kind, rel, f))
    return per_kind, findings


def explained(model: FormatModel, kind: str, version: str, f) -> dict | None:
    for g in model.gaps:
        if g.get("kind") != kind or g.get("code") != f.code:
            continue
        if g.get("key") is not None and g.get("key") != f.key:
            continue
        if g.get("versions") and version not in g["versions"]:
            continue
        if g.get("path_suffix") and not f.path.endswith(g["path_suffix"]):
            continue
        if g.get("detail_contains") and g["detail_contains"] not in f.detail:
            continue
        return g
    return None


def struct_names(symbols: dict) -> dict[int, str]:
    """``id(struct node)`` -> a readable name, for census lines."""
    names: dict[int, str] = {}

    def walk(node, name):
        if isinstance(node, dict):
            if node.get("kind") == "struct" and id(node) not in names:
                names[id(node)] = name
            for k, v in node.items():
                walk(v, name)
        elif isinstance(node, list):
            for v in node:
                walk(v, name)

    for name, node in symbols["mcdoc"].items():
        walk(node, name.split("::")[-1] if "<anonymous" not in name else name.split("::", 3)[-1])
    for reg, table in symbols["mcdoc/dispatcher"].items():
        for key, node in table.items():
            walk(node, f"{reg}[{key}]")
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=Path, help="a symbols.json on disk instead of fetching")
    ap.add_argument("--from", dest="low", default="1.20", help="oldest release to prove (default 1.20)")
    ap.add_argument("--to", dest="high", default=None, help="newest release to prove (default: newest stable)")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    if args.symbols:
        raw = json.loads(args.symbols.read_text(encoding="utf-8"))
    else:
        print(f"fetching {SYMBOLS_URL}...")
        raw = json.loads(_http(SYMBOLS_URL).decode("utf-8"))
    symbols = strip_docs(raw)

    old_meta = {}
    if (MODEL_DIR / "model.json").exists():
        old_meta = json.loads((MODEL_DIR / "model.json").read_text(encoding="utf-8"))
    patched = strip_docs(raw)
    unmatched = apply_patches(patched, old_meta.get("patches", []))
    for u in unmatched:
        print(f"  [WARN] patch {u} matches nothing in this model: remove it or move it")
    model = FormatModel(patched, {"gaps": old_meta.get("gaps", [])})

    index = VersionIndex(mcmeta.fetch_version_entries(mcmeta.CACHE_DIR, True))
    high = args.high or index.stable_ascending[-1]
    versions = index.stable_between(args.low, high)
    ORDER[:] = index.stable_ascending
    print(f"proving mcdoc {symbols.get('ref')} against {len(versions)} releases: {versions[0]} .. {versions[-1]}")

    verified: dict[str, dict] = {}
    report = ["# Format model verification", "",
              f"vanilla-mcdoc `{symbols.get('ref')}`, checked {datetime.date.today().isoformat()} "
              f"by `tools/update_format_model.py`.", "",
              "Each release's own vanilla data (misode/mcmeta `<version>-data-json`), read as that release.", "",
              "| Release | Files | Kinds | Unexplained | Known gaps hit |", "|---|---|---|---|---|"]
    details: list[str] = []
    gap_hits: collections.Counter = collections.Counter()
    loaded: dict[str, list] = {}
    usage: dict[str, dict] = {}
    regdata: dict[str, dict] = {}
    for v in versions:
        files = list(vanilla_files(vanilla_zip(v)))
        loaded[v] = files
        regdata[v] = mcmeta.fetch_registry_data(v, mcmeta.CACHE_DIR, False)
        usage[v] = {}
        per_kind, findings = read_all(model, v, files, regdata[v], usage[v])
        bad = []
        hits = 0
        for kind, rel, f in findings:
            g = explained(model, kind, v, f)
            if g is not None:
                hits += 1
                gap_hits[g.get("reason", "?")] += 1
            else:
                bad.append((kind, rel, f))
        n = sum(per_kind.values())
        report.append(f"| {v} | {n} | {len(per_kind)} | {len(bad)} | {hits} |")
        print(f"  {v}: {n} files in {len(per_kind)} kinds, {len(bad)} unexplained, {hits} known gaps")
        if not bad:
            verified[v] = {"files": n, "kinds": len(per_kind)}
        else:
            details.append(f"### {v}")
            for kind, rel, f in bad[:40]:
                line = f"- `{rel}` @ `{f.path}`: {f.code} {f.key or ''} {f.detail}".rstrip()
                details.append(line)
                print("     " + line)
            if len(bad) > 40:
                details.append(f"- ... {len(bad) - 40} more")

    # The vanish census: fields vanilla stopped writing that the model still
    # says the next release reads. A rename the model has not caught up with
    # looks exactly like this.
    from core.mcdoc import At, _vt
    names = struct_names(patched)
    census: list[str] = []
    for prev, cur in zip(versions, versions[1:]):
        before, after = usage[prev], usage[cur]
        windows = before.get("__windows__", {})
        paths = before.get("__paths__", {})
        # Everything the model reports when the older data is read as the newer release.
        _, cross = read_all(model, cur, loaded[prev], regdata[cur])
        reported = {f"{kind}:" + re.sub(r"\[\d+\]", "[]", f.path) for kind, _rel, f in cross}
        cur_paths = set().union(*after.get("__paths__", {}).values()) if after.get("__paths__") else set()

        def caught(p: str) -> bool:
            # the field itself, or anything enclosing it, is reported
            while True:
                if p in reported:
                    return True
                cut = max(p.rfind("."), p.rfind("["))
                if cut <= p.find(":"):
                    return p.split(":", 1)[0] + ":" in reported
                p = p[:cut]

        for uk, count in sorted(before.items(), key=lambda kv: (names.get(kv[0][0], "") if isinstance(kv[0], tuple) else "", str(kv[0]))):
            if not isinstance(uk, tuple) or count < 3 or after.get(uk, 0):
                continue
            if not At(_vt(cur)).ok(windows.get(uk, (None, None))):
                continue  # the model retires it here: reported, not missed
            # Each place it was used is either reported when read as the newer
            # release (retired through a union member or an enclosing field), or
            # still written there, read through a different model type.
            if paths.get(uk) and all(caught(p) or p in cur_paths for p in paths[uk]):
                continue
            census.append(f"- {prev} -> {cur}: `{names.get(uk[0], '?')}.{uk[1]}` "
                          f"({count} uses before, none after; the model still reads it)")

    # The appear census: fields vanilla starts writing that the model says the
    # previous release already read. A field the model dates too early looks
    # like this (enchant_randomly's `options` is a 1.21 field the model allowed
    # on 1.20).
    appear: list[str] = []
    for prev, cur in zip(versions, versions[1:]):
        before, after = usage[prev], usage[cur]
        windows = after.get("__windows__", {})
        paths = after.get("__paths__", {})
        _, cross = read_all(model, prev, loaded[cur], regdata[prev])
        reported = {f"{kind}:" + re.sub(r"\[\d+\]", "[]", f.path) for kind, _rel, f in cross}
        prev_paths = set().union(*before.get("__paths__", {}).values()) if before.get("__paths__") else set()

        def caught_back(p: str) -> bool:
            while True:
                if p in reported:
                    return True
                cut = max(p.rfind("."), p.rfind("["))
                if cut <= p.find(":"):
                    return p.split(":", 1)[0] + ":" in reported
                p = p[:cut]

        # Only types vanilla already wrote in the earlier release: a type that is
        # new as a whole (a new registry, a new function) dates itself.
        used_before = {k[0] for k, n in before.items() if isinstance(k, tuple) and n}
        for uk, count in sorted(after.items(), key=lambda kv: (names.get(kv[0][0], "") if isinstance(kv[0], tuple) else "", str(kv[0]))):
            if not isinstance(uk, tuple) or count < 3 or before.get(uk, 0) or uk[0] not in used_before:
                continue
            if not At(_vt(prev)).ok(windows.get(uk, (None, None))):
                continue  # the model dates it to this release: reported, not missed
            if paths.get(uk) and all(caught_back(p) or p in prev_paths for p in paths[uk]):
                continue
            appear.append(f"- {prev} -> {cur}: `{names.get(uk[0], '?')}.{uk[1]}` "
                          f"(none before, {count} uses after; the model says {prev} already read it)")

    report += ["", "Known gaps (model.json `gaps`) explained these findings:", ""]
    report += [f"- {reason}: {n}" for reason, n in sorted(gap_hits.items())] or ["- none"]
    if details:
        report += ["", "## Unexplained findings", ""] + details
    report += ["", "## Fields vanilla stopped writing that the model still reads", "",
               "Advisory. Each line is a field vanilla used at least three times in one release and not at all "
               "in the next, while the model says the next release still reads it. Most are content changes "
               "(vanilla stopped needing an optional field); a rename the model missed would show up here.", ""]
    report += census or ["- none"]
    report += ["", "## Fields vanilla started writing that the model says the release before already read", "",
               "Advisory, the mirror of the list above. Each line is a field vanilla first used in one release "
               "that the model says the previous release already read. Most are new content using an old field; "
               "a field the model dates too early would show up here. Confirmed ones go in model.json `patches`.", ""]
    report += appear or ["- none"]

    print(f"verified: {len(verified)} of {len(versions)}; census: {len(census)} vanished, {len(appear)} appeared")
    if args.dry_run:
        print("\n".join(census + ["--- appeared"] + appear))
        return 0 if len(verified) == len(versions) else 1

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    write_symbols(symbols, MODEL_DIR / "symbols.json")
    meta = {
        "source": SYMBOLS_URL,
        "mcdoc_ref": symbols.get("ref"),
        "checked": datetime.date.today().isoformat(),
        "verified": verified,
        "gaps": old_meta.get("gaps", []),
        "patches": old_meta.get("patches", []),
    }
    (MODEL_DIR / "model.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (MODEL_DIR / "VERIFICATION.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"wrote {MODEL_DIR}")
    return 0 if len(verified) == len(versions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
