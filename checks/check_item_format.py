"""Item stacks use the right custom-data key and enchantment shape for the
file's target range.

Custom data: ``tag`` before 1.20.5, ``components`` from it. Items with neither
are fine. Enchantments live in three shapes: ``tag.Enchantments`` (a list of
``{id, lvl}``) before 1.20.5, ``components.minecraft:enchantments.levels`` from
1.20.5, and the same component without the ``levels`` wrapper from 1.21.5.
Enchantment ids are checked against the registry at the file's minimum version.

Walks every item slot on every entity (riders and spawner-nested entities
included) and every container, lectern and decorated pot.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.items import block_entity_items, entity_items_for_dv
from core.mcversions import DV_1_20_5, DV_1_21_5, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext


def check_item_era(item: dict, file_dv: int, slot_desc: str, entity_id: str,
                   rel: str, file_version: str) -> str | None:
    """An ``[ERROR]`` line if the item's custom-data key is the wrong era, else None."""
    if "id" not in item:
        return None
    has_tag = "tag" in item
    has_components = "components" in item
    if not has_tag and not has_components:
        return None
    if file_dv < DV_1_20_5 and has_components:
        return (
            f"[ERROR] {rel}: {slot_desc} ({entity_id!r}) has `components` on item"
            f" (min target {file_version} is pre-1.20.5; use `tag` not `components`)"
        )
    if file_dv >= DV_1_20_5 and has_tag:
        return (
            f"[ERROR] {rel}: {slot_desc} ({entity_id!r}) has legacy `tag` on item"
            f" (min target {file_version} is 1.20.5+; use `components` not `tag`)"
        )
    return None


def _check_enchantments(item: dict, path: str, rel: str, min_v: str, max_v: str,
                        min_dv: int, max_dv: int, valid_enchants: set[str] | None) -> list[str]:
    errors: list[str] = []
    fmt_side = side_of(min_dv, max_dv, DV_1_20_5)
    wrap_side = side_of(min_dv, max_dv, DV_1_21_5)

    tag = item.get("tag")
    comps = item.get("components")

    if isinstance(tag, dict):
        ench_list = tag.get("Enchantments")
        if isinstance(ench_list, list) and ench_list:
            if fmt_side == BoundarySide.NEW:
                errors.append(
                    f"[ERROR] {rel}: {path}.tag.Enchantments used on min>=1.20.5 target"
                    f" ({min_v}); enchantments must live under components at 1.20.5+"
                )
            elif valid_enchants is not None:
                for i, e in enumerate(ench_list):
                    if not isinstance(e, dict):
                        continue
                    id_tag = e.get("id")
                    if id_tag is None:
                        continue
                    id_str = str(id_tag)
                    if id_str.startswith("minecraft:") and id_str not in valid_enchants:
                        errors.append(
                            f"[ERROR] {rel}: {path}.tag.Enchantments[{i}]: unknown enchantment"
                            f" '{id_str}' (min target {min_v})"
                        )

    if isinstance(comps, dict):
        ench = comps.get("minecraft:enchantments")
        if isinstance(ench, dict):
            key = "minecraft:enchantments"
            has_levels = "levels" in ench
            if wrap_side == BoundarySide.NEW and has_levels:
                errors.append(
                    f"[ERROR] {rel}: {path}.components.{key}: `levels` wrapper on min>=1.21.5"
                    f" target ({min_v}); at 1.21.5+ enchantments are inlined ({{id: lvl, ...}})"
                )
            elif wrap_side == BoundarySide.OLD and not has_levels:
                errors.append(
                    f"[ERROR] {rel}: {path}.components.{key}: missing `levels` wrapper on"
                    f" max<1.21.5 target ({max_v}); pre-1.21.5 uses {{levels: {{id: lvl}}}}"
                )
            elif wrap_side == BoundarySide.SPANS:
                errors.append(
                    f"[ERROR] {rel}: {path}.components.{key}: enchantments across range"
                    f" {min_v}..{max_v} span 1.21.5; `levels` wrapper is incompatible on both"
                )

            id_map = ench.get("levels") if has_levels else ench
            if valid_enchants is not None and isinstance(id_map, dict):
                for id_str in id_map:
                    if id_str.startswith("minecraft:") and id_str not in valid_enchants:
                        hint = " (renamed to `sweeping_edge` at 1.20.5)" if id_str == "minecraft:sweeping" else ""
                        errors.append(
                            f"[ERROR] {rel}: {path}.components.{key}: unknown enchantment"
                            f" '{id_str}'{hint} (min target {min_v})"
                        )
    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store, reg = svc.structures, svc.mcmeta
    if not store.dir.exists():
        return True, "no structures directory"

    ench_sets: dict[str, set[str] | None] = {}

    def valid_enchants_for(version: str) -> set[str] | None:
        if version not in ench_sets:
            try:
                ench_sets[version] = reg.registry(version, "enchantment") or None
            except Exception:
                ench_sets[version] = None
        return ench_sets[version]

    errors: list[str] = []
    items_checked = 0
    files_checked = 0

    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue
        min_dv, max_dv = fr.min_dv, fr.max_dv
        file_min, file_max = fr.min_version, fr.max_version
        valid_enchants = valid_enchants_for(file_min)

        for entity, entity_path in structure.walk_entities():
            entity_id = str(entity.get("id", "?"))
            for full_path, item in entity_items_for_dv(entity, entity_path, min_dv):
                items_checked += 1
                msg = check_item_era(item, min_dv, full_path, entity_id, rel, file_min)
                if msg:
                    errors.append(msg)
                errors.extend(_check_enchantments(
                    item, full_path, rel, file_min, file_max, min_dv, max_dv, valid_enchants,
                ))

        for slot_desc, item in block_entity_items(structure.block_entities):
            items_checked += 1
            item_id = str(item.get("id", "?"))
            msg = check_item_era(item, min_dv, slot_desc, item_id, rel, file_min)
            if msg:
                errors.append(msg)
            errors.extend(_check_enchantments(
                item, slot_desc, rel, file_min, file_max, min_dv, max_dv, valid_enchants,
            ))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {items_checked} item slot(s) checked -- all valid")
        return True, f"{files_checked} files, {items_checked} item slots checked"
    return False, f"{len(errors)} item format error(s)"
