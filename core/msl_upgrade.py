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


def requires_msl(resources_root) -> bool:
    """Whether the mod declares Moog's Structure Lib as a dependency (it then
    always runs alongside it, and on 26.3 MSL rewrites its data)."""
    import json
    from pathlib import Path
    root = Path(resources_root)
    fabric = root / "fabric.mod.json"
    if fabric.is_file():
        try:
            meta = json.loads(fabric.read_text(encoding="utf-8-sig"))
            if "moogs_structures" in (meta.get("depends") or {}):
                return True
        except (OSError, ValueError):
            pass
    for toml in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
        p = root / toml
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if 'modId = "moogs_structures"' in text or "modId='moogs_structures'" in text \
                    or "modId = 'moogs_structures'" in text:
                return True
    return False
