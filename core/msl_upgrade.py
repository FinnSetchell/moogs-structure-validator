"""Moog's Structure Lib's on-load rewrite of pre-26.3 data, ported.

From its first 26.3 build (3.3.0) Moog's Structure Lib rewrites pre-26.3 data
pack JSON into the 26.3 shapes as each registry element is read
(``compat/LegacyDataUpgrader`` behind ``RegistryLoadTaskMixin``), for every
namespace. On 26.3 the game therefore reads a Moog mod's files *after* this
rewrite, and the check reads them the same way. This is a line-for-line port of
the 3.4.x class; keep it in step with MSL.

What MSL rewrites:

* block states ``{"Name", "Properties"}`` -> ``{"id", "properties"}`` in
  processor lists, template pools and structures, and ``minecraft:chain`` ->
  ``minecraft:iron_chain`` where the new id exists;
* structure spawn overrides ``minCount`` / ``maxCount`` -> an int provider ``count``;
* loot tables, predicates and item modifiers: ``function`` -> ``type``, a
  ``conditions`` list -> one ``condition`` (``all_of`` for several), ``condition``
  -> ``type`` inside those, and a typeless ``{"min", "max"}`` under a number
  field -> a ``minecraft:uniform``.

What it does not: ``functions`` -> ``modifier`` (so 26.3 still ignores every
loot function list), ``name`` -> ``loot_table_id`` on ``set_loot_table``, and
anything outside the registries above.
"""
from __future__ import annotations

import copy
import re

BLOCK_STATE_KINDS = frozenset({"worldgen/processor_list", "worldgen/template_pool", "worldgen/structure"})
LOOT_KINDS = frozenset({"loot_table", "predicate", "item_modifier"})
NUMBER_FIELDS = frozenset({"rolls", "bonus_rolls", "count", "levels", "damage", "amplifier",
                           "duration", "amount", "chance"})
RENAMES = {"minecraft:chain": "minecraft:iron_chain"}

# The first MSL release that has each rewrite. All arrived together in
# LegacyDataUpgrader (tag 3.3.0-26.3, commit 2b31c44) and are unchanged through
# 3.4.2. A rewrite MSL adds later goes here with its own release, so a mod is
# only credited with it once its declared minimum reaches that release.
REWRITE_SINCE = {
    "block_states": (3, 3, 0),      # Name/Properties -> id/properties
    "block_aliases": (3, 3, 0),     # chain -> iron_chain
    "spawn_overrides": (3, 3, 0),   # minCount/maxCount -> count
    "function_ids": (3, 3, 0),      # function -> type
    "conditions": (3, 3, 0),        # conditions list -> condition (all_of)
    "condition_ids": (3, 3, 0),     # condition -> type inside conditions
    "number_ranges": (3, 3, 0),     # typeless {min, max} -> uniform
}

FIRST_VERSION = (26, 3)   # MSL's 26.3 builds are the first that carry the rewrite


def _primitive(v) -> bool:
    return not isinstance(v, (dict, list)) and v is not None


def upgrade(kind: str, data, blocks: set[str] | None = None, msl: tuple[int, ...] | None = None):
    """``(rewritten copy, number of rewrites)``; the input is not touched.

    ``blocks`` is the version's block registry, for the rename that only fires
    when the new id exists. ``msl`` is the MSL release doing the rewrite: only
    the rewrites that release has run (None: all of them).
    """
    if not isinstance(data, dict):
        return data, 0
    if kind not in BLOCK_STATE_KINDS and kind not in LOOT_KINDS:
        return data, 0
    on = {name: msl is None or msl >= since for name, since in REWRITE_SINCE.items()}
    root = copy.deepcopy(data)
    changes = 0
    if kind in BLOCK_STATE_KINDS:
        changes += _rename_block_states(root, blocks, on)
        if kind == "worldgen/structure" and on["spawn_overrides"]:
            changes += _upgrade_spawn_overrides(root)
    else:
        if kind == "predicate" and on["condition_ids"]:
            changes += _upgrade_condition(root, on)
        changes += _upgrade_loot_tree(root, None, on)
    return root, changes


def _alias(id_: str, blocks: set[str] | None) -> str:
    target = RENAMES.get(id_)
    if target is not None and blocks is not None and target in blocks:
        return target
    return id_


def _rename_block_states(element, blocks, on) -> int:
    changes = 0
    if isinstance(element, dict):
        if on["block_states"] and "Name" in element and _primitive(element["Name"]) and "id" not in element:
            element["id"] = element.pop("Name")
            if "Properties" in element and "properties" not in element:
                element["properties"] = element.pop("Properties")
            changes += 1
        if on["block_aliases"] and isinstance(element.get("id"), str):
            renamed = _alias(element["id"], blocks)
            if renamed != element["id"]:
                element["id"] = renamed
                changes += 1
        for v in list(element.values()):
            changes += _rename_block_states(v, blocks, on)
    elif isinstance(element, list):
        for v in element:
            changes += _rename_block_states(v, blocks, on)
    return changes


def _upgrade_spawn_overrides(structure: dict) -> int:
    overrides = structure.get("spawn_overrides")
    if not isinstance(overrides, dict):
        return 0
    changes = 0
    for override in overrides.values():
        if not isinstance(override, dict) or not isinstance(override.get("spawns"), list):
            continue
        for spawn in override["spawns"]:
            if not isinstance(spawn, dict) or "count" in spawn:
                continue
            if "minCount" not in spawn and "maxCount" not in spawn:
                continue
            lo = int(spawn["minCount"]) if "minCount" in spawn else 1
            hi = int(spawn["maxCount"]) if "maxCount" in spawn else lo
            spawn.pop("minCount", None)
            spawn.pop("maxCount", None)
            spawn["count"] = lo if lo == hi else {"type": "minecraft:uniform", "min_inclusive": lo, "max_inclusive": hi}
            changes += 1
    return changes


def _upgrade_loot_tree(element, parent_key, on) -> int:
    changes = 0
    if isinstance(element, dict):
        if on["function_ids"] and "function" in element and _primitive(element["function"]) and "type" not in element:
            element["type"] = element.pop("function")
            changes += 1
        if on["conditions"] and isinstance(element.get("conditions"), list) and "condition" not in element:
            conditions = element.pop("conditions")
            if on["condition_ids"]:
                for term in conditions:
                    changes += _upgrade_condition(term, on)
            if len(conditions) == 1:
                element["condition"] = conditions[0]
            elif len(conditions) > 1:
                element["condition"] = {"type": "minecraft:all_of", "terms": conditions}
            changes += 1
        if (on["number_ranges"] and parent_key is not None and parent_key in NUMBER_FIELDS
                and "min" in element and "max" in element and "type" not in element):
            element["type"] = "minecraft:uniform"
            changes += 1
        for k, v in list(element.items()):
            changes += _upgrade_loot_tree(v, k, on)
    elif isinstance(element, list):
        for v in element:
            changes += _upgrade_loot_tree(v, parent_key, on)
    return changes


def _upgrade_condition(element, on) -> int:
    if not isinstance(element, dict):
        return 0
    changes = 0
    if "condition" in element and _primitive(element["condition"]) and "type" not in element:
        element["type"] = element.pop("condition")
        changes += 1
    if isinstance(element.get("terms"), list):
        for term in element["terms"]:
            changes += _upgrade_condition(term, on)
    if "term" in element:
        changes += _upgrade_condition(element["term"], on)
    return changes


# --- which MSL a mod runs with -------------------------------------------------------

def _semver(text: str) -> tuple[int, ...] | None:
    m = re.match(r"\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


# Fabric Loader's ordering (SemanticVersionImpl): numbers compared one by one, the
# missing ones as 0; a pre-release (after the first "-") sorts below the release, its
# dot-separated parts compared as numbers when both are numbers, numbers below words;
# build metadata (after "+") is ignored. MSL's 1.x and 2.x Fabric builds call
# themselves "1.1.0-1.20-1.20.4" or "2.0.2-fabric": pre-releases, below 1.1.0 and 2.0.2.

def fabric_version(text: str):
    """``(numbers, pre-release parts or None)``, or None for a version Fabric cannot
    read as semantic."""
    core = text.strip().split("+", 1)[0]
    head, dash, pre = core.partition("-")
    parts = head.split(".")
    if not parts or not all(x.isdigit() for x in parts):
        return None
    return [int(x) for x in parts], (pre.split(".") if dash else None)


def fabric_compare(a, b) -> int:
    (na, pa), (nb, pb) = a, b
    n = max(len(na), len(nb))
    na, nb = na + [0] * (n - len(na)), nb + [0] * (n - len(nb))
    if na != nb:
        return -1 if na < nb else 1
    if pa is None or pb is None:
        return 0 if pa is pb else (1 if pa is None else -1)
    for x, y in zip(pa, pb):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return -1 if int(x) < int(y) else 1
        if x.isdigit() != y.isdigit():
            return -1 if x.isdigit() else 1
        return -1 if x < y else 1
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


def fabric_accepts(spec: str, version: str) -> bool | None:
    """Whether a Fabric or Quilt version predicate accepts ``version``: space-separated
    terms all hold (``>=``, ``<=``, ``>``, ``<``, ``=``, ``^``, ``~``, ``*``, ``1.2.x``).
    None when it cannot be read."""
    v = fabric_version(version)
    if v is None:
        return None
    terms = spec.split()
    if not terms:
        return None
    for t in terms:
        if t == "*":
            continue
        op = next((o for o in (">=", "<=", ">", "<", "=", "^", "~") if t.startswith(o)), "")
        target = t[len(op):]
        if target.endswith((".x", ".X", ".*")) and not op:
            fixed = [int(x) for x in target.split(".")[:-1] if x.isdigit()]
            if v[0][:len(fixed)] != fixed:
                return False
            continue
        w = fabric_version(target)
        if w is None:
            return None
        c = fabric_compare(v, w)
        ok = {">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "=": c == 0, "": c == 0,
              "^": c >= 0 and v[0][:1] == w[0][:1],
              "~": c >= 0 and v[0][:2] == (w[0] + [0])[:2]}[op]
        if not ok:
            return False
    return True


# Forge and NeoForge compare with Maven's ComparableVersion: alpha, beta, milestone,
# rc and snapshot qualifiers sort below the release, any other qualifier (MSL's
# "1.1.0-1.20-1.20.4") above it.
_MAVEN_PRE = ("alpha", "a", "beta", "b", "milestone", "m", "rc", "cr", "snapshot")


def _maven_key(text: str):
    m = re.match(r"\s*(\d+(?:\.\d+)*)(.*)", text)
    if not m:
        return None
    nums = [int(x) for x in m.group(1).split(".")]
    nums += [0] * (3 - len(nums))
    q = m.group(2).lstrip("-.").lower()
    rank = 1 if not q else 0 if re.match(r"(%s)(\b|\d|[.-]|$)" % "|".join(_MAVEN_PRE), q) else 2
    return nums, rank


def maven_accepts(spec: str, version: str) -> bool | None:
    """Whether a Maven range (``[3.0.0,)``, ``(,2.0]``, ``[1.0]``, several joined by
    commas) accepts ``version``. A bare version is only a recommendation: anything."""
    spec = spec.strip()
    if not spec or spec == "*":
        return True
    groups = re.findall(r"([\[(])([^\])]*)([\])])", spec)
    if not groups:
        return True if _maven_key(spec) else None
    v = _maven_key(version)
    if v is None:
        return None
    for lo_b, body, hi_b in groups:
        if "," not in body:
            if _maven_key(body) == v:
                return True
            continue
        lo, hi = (x.strip() for x in body.split(",", 1))
        ok = True
        if lo:
            k = _maven_key(lo)
            ok = ok and (v > k if lo_b == "(" else v >= k)
        if hi:
            k = _maven_key(hi)
            ok = ok and (v < k if hi_b == ")" else v <= k)
        if ok:
            return True
    return False


def accepts(loader: str, spec: str, version: str) -> bool | None:
    if loader in ("fabric", "quilt"):
        return fabric_accepts(spec, version)
    return maven_accepts(spec, version)


def range_floor(spec: str) -> tuple[int, ...] | None:
    """The lowest MSL version a dependency range allows.

    Fabric/Quilt (``>=3.0.0``, ``^3.0.0``, ``~3.1``, ``*``) and Maven (``[3.0.0,)``)
    ranges. ``*`` and an open lower bound mean any version: ``(0, 0, 0)``.
    None when the range cannot be read (an unresolved placeholder).
    """
    spec = spec.strip()
    if not spec or "${" in spec:
        return None
    if spec == "*":
        return (0, 0, 0)
    if spec[0] in "[(":
        low = spec[1:].split(",", 1)[0].strip()
        return _semver(low) if low else (0, 0, 0)
    floors = []
    for part in spec.split("||"):
        part = part.strip()
        low = None
        for token in part.split():
            for prefix in (">=", "^", "~", "=", ">"):
                if token.startswith(prefix):
                    low = _semver(token[len(prefix):])
                    break
            else:
                if token[0].isdigit():
                    low = _semver(token)
            if low is not None:
                break
        floors.append(low if low is not None else (0, 0, 0))
    return min(floors) if floors else None


class Requirement(tuple):
    """The lowest MSL any loader file allows, as a version tuple, which also keeps
    each file's own predicate (``specs``: ``(loader, spec, where)``) so it can be read
    against the builds each loader can load, as the loader reads it."""
    specs: list = []


def declared_minimum(project_root) -> tuple[Requirement | None, list[str]]:
    """The lowest Moog's Structure Lib any of the mod's loader files allows,
    and where each bound was read. ``(None, [])`` when the mod does not depend
    on MSL at all."""
    import json
    from pathlib import Path
    root = Path(project_root)
    res = root / "src" / "main" / "resources"
    found: list[tuple[tuple[int, ...] | None, str]] = []
    specs: list[tuple[str, str, str]] = []

    def add(loader, spec, where):
        found.append((range_floor(spec) if isinstance(spec, str) else None, f"{where} `{spec}`"))
        if isinstance(spec, str) and "${" not in spec:
            specs.append((loader, spec, f"{where} `{spec}`"))

    try:
        meta = json.loads((res / "fabric.mod.json").read_text(encoding="utf-8-sig"))
        dep = (meta.get("depends") or {}).get("moogs_structures")
        if dep is not None:
            for spec in (dep if isinstance(dep, list) else [dep]):
                add("fabric", spec, "fabric.mod.json")
    except (OSError, ValueError):
        pass
    try:
        meta = json.loads((res / "quilt.mod.json").read_text(encoding="utf-8-sig"))
        for d in (meta.get("quilt_loader") or {}).get("depends") or []:
            if isinstance(d, dict) and d.get("id") == "moogs_structures":
                v = d.get("versions", "*")
                for spec in (v if isinstance(v, list) else [v]):
                    add("quilt", spec, "quilt.mod.json")
    except (OSError, ValueError):
        pass
    props = {}
    try:
        for line in (root / "gradle.properties").read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                props[k.strip()] = v.strip()
    except OSError:
        pass
    for toml in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
        try:
            text = (res / toml).read_text(encoding="utf-8")
        except OSError:
            continue
        loader = "neoforge" if toml.startswith("META-INF/neoforge") else "forge"
        for block in re.split(r"\[\[dependencies\.", text)[1:]:
            if not re.search(r"""modId\s*=\s*["']moogs_structures["']""", block):
                continue
            m = re.search(r"""versionRange\s*=\s*["']([^"']*)["']""", block)
            spec = m.group(1) if m else "*"
            ph = re.fullmatch(r"\$\{(\w+)\}", spec.strip())
            if ph and ph.group(1) in props:
                spec = props[ph.group(1)]
                add(loader, spec, f"{toml.split('/')[-1]} (gradle.properties {ph.group(1)})")
            else:
                add(loader, spec, toml.split("/")[-1])
    if not found:
        return None, []
    floors = [f for f, _ in found if f is not None]
    if not floors:
        return None, [w for _, w in found]
    req = Requirement(min(floors))
    req.specs = specs
    return req, [w for _, w in found]


class MslBuilds:
    """``data/msl_builds.json``: every MSL build per loader and Minecraft version (the
    version its loader compares), the oldest MSL per Minecraft version, and from which
    MSL release each of its data behaviours runs."""

    def __init__(self, path=None):
        import json
        from pathlib import Path
        path = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "msl_builds.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.oldest = {k: _semver(v) for k, v in data["oldest_build"].items()}
        self.features = data["features"]
        self.builds = data.get("builds", [])

    def oldest_build(self, version: str) -> tuple[int, ...] | None:
        if version in self.oldest:
            return self.oldest[version]
        vt = _semver(version)
        known = sorted((_semver(k), v) for k, v in self.oldest.items())
        before = [v for k, v in known if k <= vt]
        return before[-1] if before else None

    def on(self, loader: str, version: str) -> list[str]:
        """The MSL builds a loader can load on a Minecraft version (a Quilt player runs
        the Fabric build)."""
        want = "fabric" if loader == "quilt" else loader
        return [b["version"] for b in self.builds if b["loader"] == want and version in b["mc"]]

    def per_loader(self, version: str, declared) -> list[tuple[str, list[str], list[str]]]:
        """``(where, builds on this version, the ones its predicate accepts)`` for each
        loader file that has builds here."""
        out = []
        for loader, spec, where in getattr(declared, "specs", None) or []:
            avail = self.on(loader, version)
            if avail:
                out.append((where, avail, [b for b in avail if accepts(loader, spec, b)]))
        return out

    def effective(self, version: str, declared: tuple[int, ...] | None) -> tuple[int, ...] | None:
        """The oldest MSL a player can run this mod with on ``version``: of the builds
        each loader file accepts there, as that loader reads its predicate, the oldest."""
        loaders = self.per_loader(version, declared)
        if loaders:
            ok = [_semver(b) for _, _, acc in loaders for b in acc]
            return min(ok) if ok else None
        oldest = self.oldest_build(version)
        if declared is None:
            return oldest
        if oldest is None:
            return tuple(declared)
        return max(tuple(declared), oldest)

    def refused(self, version: str, declared) -> list[str]:
        """The loader files that accept no MSL build on ``version`` although there are
        some: no player on that loader can run the mod there."""
        return [where for where, _avail, acc in self.per_loader(version, declared) if not acc]

    def passed_over(self, version: str, declared) -> list[tuple[str, str]]:
        """``(where, named release)`` for a Fabric or Quilt predicate whose own named
        release is on this version only as pre-release builds it rejects (``>=1.1.0``
        against 1.1.0-1.20-1.20.4): almost always meant as ``>=1.1.0-0``."""
        out = []
        for loader, spec, where in getattr(declared, "specs", None) or []:
            if loader not in ("fabric", "quilt"):
                continue
            floor = range_floor(spec)
            named = [b for b in self.on(loader, version) if floor and _semver(b) == floor]
            if named and not any(accepts(loader, spec, b) for b in named):
                out.append((where, fmt(floor)))
        return out

    def applies(self, feature: str, version: str, declared: tuple[int, ...] | None) -> tuple[bool, bool]:
        """``(in this version's window, guaranteed by the MSL the mod allows)``."""
        f = self.features[feature]
        vt = _semver(version)
        inside = vt >= _semver(f["mc_from"]) and ("mc_until" not in f or vt < _semver(f["mc_until"]))
        if not inside:
            return False, False
        eff = self.effective(version, declared)
        return True, eff is not None and eff >= _semver(f["msl_from"])


def fmt(v: tuple[int, ...] | None) -> str:
    return "any version" if v is None or tuple(v) == (0, 0, 0) else ".".join(str(x) for x in v)


def requires_msl(resources_root) -> bool:
    """Whether the mod declares Moog's Structure Lib as a dependency."""
    from pathlib import Path
    root = Path(resources_root)
    # resources_root is src/main/resources; declared_minimum wants the project root
    return declared_minimum(root.parent.parent.parent)[1] != []
