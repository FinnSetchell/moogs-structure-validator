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

FIRST_VERSION = (26, 3)   # MSL's 26.3 builds are the first that carry the rewrite


def _primitive(v) -> bool:
    return not isinstance(v, (dict, list)) and v is not None


def upgrade(kind: str, data, blocks: set[str] | None = None):
    """``(rewritten copy, number of rewrites)``; the input is not touched.

    ``blocks`` is the version's block registry, for the rename that only fires
    when the new id exists.
    """
    if not isinstance(data, dict):
        return data, 0
    if kind not in BLOCK_STATE_KINDS and kind not in LOOT_KINDS:
        return data, 0
    root = copy.deepcopy(data)
    changes = 0
    if kind in BLOCK_STATE_KINDS:
        changes += _rename_block_states(root, blocks)
        if kind == "worldgen/structure":
            changes += _upgrade_spawn_overrides(root)
    else:
        if kind == "predicate":
            changes += _upgrade_condition(root)
        changes += _upgrade_loot_tree(root, None)
    return root, changes


def _alias(id_: str, blocks: set[str] | None) -> str:
    target = RENAMES.get(id_)
    if target is not None and blocks is not None and target in blocks:
        return target
    return id_


def _rename_block_states(element, blocks) -> int:
    changes = 0
    if isinstance(element, dict):
        if "Name" in element and _primitive(element["Name"]) and "id" not in element:
            element["id"] = element.pop("Name")
            if "Properties" in element and "properties" not in element:
                element["properties"] = element.pop("Properties")
            changes += 1
        if isinstance(element.get("id"), str):
            renamed = _alias(element["id"], blocks)
            if renamed != element["id"]:
                element["id"] = renamed
                changes += 1
        for v in list(element.values()):
            changes += _rename_block_states(v, blocks)
    elif isinstance(element, list):
        for v in element:
            changes += _rename_block_states(v, blocks)
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


def _upgrade_loot_tree(element, parent_key) -> int:
    changes = 0
    if isinstance(element, dict):
        if "function" in element and _primitive(element["function"]) and "type" not in element:
            element["type"] = element.pop("function")
            changes += 1
        if isinstance(element.get("conditions"), list) and "condition" not in element:
            conditions = element.pop("conditions")
            for term in conditions:
                changes += _upgrade_condition(term)
            if len(conditions) == 1:
                element["condition"] = conditions[0]
            elif len(conditions) > 1:
                element["condition"] = {"type": "minecraft:all_of", "terms": conditions}
            changes += 1
        if (parent_key is not None and parent_key in NUMBER_FIELDS
                and "min" in element and "max" in element and "type" not in element):
            element["type"] = "minecraft:uniform"
            changes += 1
        for k, v in list(element.items()):
            changes += _upgrade_loot_tree(v, k)
    elif isinstance(element, list):
        for v in element:
            changes += _upgrade_loot_tree(v, parent_key)
    return changes


def _upgrade_condition(element) -> int:
    if not isinstance(element, dict):
        return 0
    changes = 0
    if "condition" in element and _primitive(element["condition"]) and "type" not in element:
        element["type"] = element.pop("condition")
        changes += 1
    if isinstance(element.get("terms"), list):
        for term in element["terms"]:
            changes += _upgrade_condition(term)
    if "term" in element:
        changes += _upgrade_condition(element["term"])
    return changes


# --- which MSL a mod runs with -------------------------------------------------------

def _semver(text: str) -> tuple[int, ...] | None:
    m = re.match(r"\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


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


def declared_minimum(project_root) -> tuple[tuple[int, ...] | None, list[str]]:
    """The lowest Moog's Structure Lib any of the mod's loader files allows,
    and where each bound was read. ``(None, [])`` when the mod does not depend
    on MSL at all."""
    import json
    from pathlib import Path
    root = Path(project_root)
    res = root / "src" / "main" / "resources"
    found: list[tuple[tuple[int, ...] | None, str]] = []

    def add(spec, where):
        found.append((range_floor(spec) if isinstance(spec, str) else None, f"{where} `{spec}`"))

    try:
        meta = json.loads((res / "fabric.mod.json").read_text(encoding="utf-8-sig"))
        dep = (meta.get("depends") or {}).get("moogs_structures")
        if dep is not None:
            for spec in (dep if isinstance(dep, list) else [dep]):
                add(spec, "fabric.mod.json")
    except (OSError, ValueError):
        pass
    try:
        meta = json.loads((res / "quilt.mod.json").read_text(encoding="utf-8-sig"))
        for d in (meta.get("quilt_loader") or {}).get("depends") or []:
            if isinstance(d, dict) and d.get("id") == "moogs_structures":
                v = d.get("versions", "*")
                for spec in (v if isinstance(v, list) else [v]):
                    add(spec, "quilt.mod.json")
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
        for block in re.split(r"\[\[dependencies\.", text)[1:]:
            if not re.search(r"""modId\s*=\s*["']moogs_structures["']""", block):
                continue
            m = re.search(r"""versionRange\s*=\s*["']([^"']*)["']""", block)
            spec = m.group(1) if m else "*"
            ph = re.fullmatch(r"\$\{(\w+)\}", spec.strip())
            if ph and ph.group(1) in props:
                spec = props[ph.group(1)]
                add(spec, f"{toml.split('/')[-1]} (gradle.properties {ph.group(1)})")
            else:
                add(spec, toml.split("/")[-1])
    if not found:
        return None, []
    floors = [f for f, _ in found if f is not None]
    return (min(floors) if floors else None), [w for _, w in found]


class MslBuilds:
    """``data/msl_builds.json``: the oldest MSL per Minecraft version, and from
    which MSL release each of its data behaviours runs."""

    def __init__(self, path=None):
        import json
        from pathlib import Path
        path = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "msl_builds.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.oldest = {k: _semver(v) for k, v in data["oldest_build"].items()}
        self.features = data["features"]

    def oldest_build(self, version: str) -> tuple[int, ...] | None:
        if version in self.oldest:
            return self.oldest[version]
        vt = _semver(version)
        known = sorted((_semver(k), v) for k, v in self.oldest.items())
        before = [v for k, v in known if k <= vt]
        return before[-1] if before else None

    def effective(self, version: str, declared: tuple[int, ...] | None) -> tuple[int, ...] | None:
        """The oldest MSL a player can run this mod with on ``version``."""
        oldest = self.oldest_build(version)
        if declared is None:
            return oldest
        if oldest is None:
            return declared
        return max(declared, oldest)

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
    return "any version" if v in (None, (0, 0, 0)) else ".".join(str(x) for x in v)


def requires_msl(resources_root) -> bool:
    """Whether the mod declares Moog's Structure Lib as a dependency."""
    from pathlib import Path
    root = Path(resources_root)
    # resources_root is src/main/resources; declared_minimum wants the project root
    return declared_minimum(root.parent.parent.parent)[1] != []
