from __future__ import annotations

from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import nbtlib

from utils.boundaries import DV_1_20_2, DV_1_20_5, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


_POTION_ITEM_IDS = {
    "minecraft:potion",
    "minecraft:splash_potion",
    "minecraft:lingering_potion",
    "minecraft:tipped_arrow",
}


def _iter_entity_items(entity_nbt: nbtlib.Compound, entity_path: str) -> Iterator[tuple[str, nbtlib.Compound]]:
    for list_field in ("HandItems", "ArmorItems"):
        items = entity_nbt.get(list_field)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{entity_path}.{list_field}[{i}]", item
    for field in ("body_armor_item", "SaddleItem", "Item"):
        item = entity_nbt.get(field)
        if isinstance(item, nbtlib.Compound):
            yield f"{entity_path}.{field}", item
    equip = entity_nbt.get("equipment")
    if isinstance(equip, nbtlib.Compound):
        for slot, item in equip.items():
            if isinstance(item, nbtlib.Compound):
                yield f"{entity_path}.equipment.{slot}", item


def _iter_block_items(nbt: nbtlib.Compound) -> Iterator[tuple[str, nbtlib.Compound]]:
    for i, block_entry in enumerate(nbt.get("blocks") or []):
        block_nbt = block_entry.get("nbt")
        if not isinstance(block_nbt, nbtlib.Compound):
            continue
        base = f"blocks[{i}].nbt"
        items = block_nbt.get("Items")
        if isinstance(items, list):
            for j, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{base}.Items[{j}]", item


def _check_potion_item(item: nbtlib.Compound, path: str, rel: str,
                       min_v: str, max_v: str, min_dv: int, max_dv: int) -> list[str]:
    item_id = str(item.get("id", ""))
    if item_id not in _POTION_ITEM_IDS:
        return []

    errors: list[str] = []
    envelope_side = side_of(min_dv, max_dv, DV_1_20_5)   # tag vs components
    rename_side = side_of(min_dv, max_dv, DV_1_20_2)     # PascalCase vs snake_case (inside tag)

    tag = item.get("tag")
    comps = item.get("components")

    tag_pascal = None
    tag_snake = None
    if isinstance(tag, nbtlib.Compound):
        tag_pascal = tag.get("CustomPotionEffects")
        tag_snake = tag.get("custom_potion_effects")

    comp_custom = None
    if isinstance(comps, nbtlib.Compound):
        pc = comps.get("minecraft:potion_contents")
        if isinstance(pc, nbtlib.Compound):
            comp_custom = pc.get("custom_effects")

    has_tag_effects = isinstance(tag_pascal, list) or isinstance(tag_snake, list)
    has_comp_effects = isinstance(comp_custom, list)

    if envelope_side == BoundarySide.NEW and has_tag_effects:
        key = "CustomPotionEffects" if isinstance(tag_pascal, list) else "custom_potion_effects"
        errors.append(
            f"[ERROR] {rel}: {path}.tag.{key}: potion effects in `tag` on a min>=1.20.5"
            f" target ({min_v}); move to `components.minecraft:potion_contents.custom_effects`"
        )
    if envelope_side == BoundarySide.OLD and has_comp_effects:
        errors.append(
            f"[ERROR] {rel}: {path}.components.minecraft:potion_contents.custom_effects on a"
            f" max<1.20.5 target ({max_v}); pre-1.20.5 uses `tag.custom_potion_effects`"
        )
    if envelope_side == BoundarySide.SPANS and (has_tag_effects or has_comp_effects):
        errors.append(
            f"[ERROR] {rel}: {path}: potion effects across range {min_v}..{max_v} spans 1.20.5;"
            f" `tag` and `components` shapes are incompatible on either side"
        )

    # Inside tag, check the PascalCase-vs-snake_case rename at 1.20.2.
    if envelope_side == BoundarySide.OLD or (envelope_side == BoundarySide.SPANS and has_tag_effects):
        if isinstance(tag_pascal, list) and rename_side == BoundarySide.NEW:
            errors.append(
                f"[ERROR] {rel}: {path}.tag.CustomPotionEffects: legacy PascalCase on a"
                f" min>=1.20.2 target ({min_v}); use `custom_potion_effects`"
            )
        if isinstance(tag_snake, list) and rename_side == BoundarySide.OLD:
            errors.append(
                f"[ERROR] {rel}: {path}.tag.custom_potion_effects: snake_case on a"
                f" max<1.20.2 target ({max_v}); pre-1.20.2 uses `CustomPotionEffects`"
            )
    return errors


def _check_area_effect_cloud(entity_nbt: nbtlib.Compound, entity_path: str, rel: str,
                             min_v: str, max_v: str, min_dv: int, max_dv: int) -> list[str]:
    errors: list[str] = []
    envelope_side = side_of(min_dv, max_dv, DV_1_20_5)
    rename_side = side_of(min_dv, max_dv, DV_1_20_2)

    legacy_pascal = entity_nbt.get("Effects")
    legacy_snake = entity_nbt.get("custom_potion_effects")
    pc = entity_nbt.get("potion_contents")

    has_new = isinstance(pc, nbtlib.Compound) and "custom_effects" in pc
    has_old = isinstance(legacy_pascal, list) or isinstance(legacy_snake, list)

    if envelope_side == BoundarySide.NEW and has_old:
        key = "Effects" if isinstance(legacy_pascal, list) else "custom_potion_effects"
        errors.append(
            f"[ERROR] {rel}: {entity_path}.{key}: legacy potion effects on a min>=1.20.5"
            f" area_effect_cloud target ({min_v}); use `potion_contents.custom_effects`"
        )
    if envelope_side == BoundarySide.OLD and has_new:
        errors.append(
            f"[ERROR] {rel}: {entity_path}.potion_contents.custom_effects on a max<1.20.5"
            f" area_effect_cloud target ({max_v}); pre-1.20.5 uses `Effects`/`custom_potion_effects`"
        )
    if envelope_side == BoundarySide.SPANS and (has_new or has_old):
        errors.append(
            f"[ERROR] {rel}: {entity_path}: area_effect_cloud effects across range"
            f" {min_v}..{max_v} spans 1.20.5"
        )
    if isinstance(legacy_pascal, list) and rename_side == BoundarySide.NEW:
        errors.append(
            f"[ERROR] {rel}: {entity_path}.Effects: legacy PascalCase on a min>=1.20.2"
            f" area_effect_cloud target ({min_v}); use `custom_potion_effects`"
        )
    if isinstance(legacy_snake, list) and rename_side == BoundarySide.OLD:
        errors.append(
            f"[ERROR] {rel}: {entity_path}.custom_potion_effects: snake_case on a max<1.20.2"
            f" area_effect_cloud target ({max_v}); pre-1.20.2 uses `Effects`"
        )
    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")
    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"
    version_map = load_version_map(cache_dir, ctx.refresh)
    if not version_map:
        return True, "skipped (no version map)"

    global_min_version = min(ctx.mc_versions, key=_parse_version)
    global_max_version = max(ctx.mc_versions, key=_parse_version)
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    nbt_ranges = {}
    if template_pool_dir.exists():
        nbt_ranges = _build_nbt_version_ranges(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version,
            ctx.mc_versions, global_max_version,
        )

    errors: list[str] = []
    files_checked = 0
    items_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue
        files_checked += 1
        rel = str(nbt_path.relative_to(structures_dir))

        info = nbt_ranges.get(nbt_path)
        file_min = info.min_version if info else global_min_version
        file_max = info.max_version if info else global_max_version
        min_dv = version_map.get(file_min)
        max_dv = version_map.get(file_max)
        if min_dv is None or max_dv is None:
            continue

        for entity_nbt, entity_path in iter_entities(nbt):
            entity_id = str(entity_nbt.get("id", ""))
            if entity_id == "minecraft:area_effect_cloud":
                errors.extend(_check_area_effect_cloud(
                    entity_nbt, entity_path, rel, file_min, file_max, min_dv, max_dv,
                ))
            for slot_path, item in _iter_entity_items(entity_nbt, entity_path):
                if str(item.get("id", "")) in _POTION_ITEM_IDS:
                    items_checked += 1
                    errors.extend(_check_potion_item(
                        item, slot_path, rel, file_min, file_max, min_dv, max_dv,
                    ))

        for slot_path, item in _iter_block_items(nbt):
            if str(item.get("id", "")) in _POTION_ITEM_IDS:
                items_checked += 1
                errors.extend(_check_potion_item(
                    item, slot_path, rel, file_min, file_max, min_dv, max_dv,
                ))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {items_checked} potion item(s) checked -- all valid")

    if errors:
        return False, f"{len(errors)} potion effect error(s)"
    return True, f"{files_checked} files, {items_checked} potion items checked"
