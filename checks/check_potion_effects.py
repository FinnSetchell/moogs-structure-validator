"""Custom potion effects use the right key and shape for the file's target range.

Two boundaries: the envelope moved from ``tag`` to ``components`` at 1.20.5
(``custom_potion_effects`` -> ``minecraft:potion_contents.custom_effects``), and
inside ``tag`` the key was renamed from ``CustomPotionEffects`` to
``custom_potion_effects`` at 1.20.2. Potions, splash and lingering potions,
tipped arrows, and ``area_effect_cloud`` entities are checked.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.items import block_entity_items, entity_items
from core.mcversions import DV_1_20_2, DV_1_20_5, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

_POTION_ITEM_IDS = {
    "minecraft:potion",
    "minecraft:splash_potion",
    "minecraft:lingering_potion",
    "minecraft:tipped_arrow",
}


def _check_potion_item(item: dict, path: str, rel: str,
                       min_v: str, max_v: str, min_dv: int, max_dv: int) -> list[str]:
    if str(item.get("id", "")) not in _POTION_ITEM_IDS:
        return []

    errors: list[str] = []
    envelope_side = side_of(min_dv, max_dv, DV_1_20_5)   # tag vs components
    rename_side = side_of(min_dv, max_dv, DV_1_20_2)     # PascalCase vs snake_case (inside tag)

    tag = item.get("tag")
    comps = item.get("components")

    tag_pascal = tag_snake = None
    if isinstance(tag, dict):
        tag_pascal = tag.get("CustomPotionEffects")
        tag_snake = tag.get("custom_potion_effects")

    comp_custom = None
    if isinstance(comps, dict):
        pc = comps.get("minecraft:potion_contents")
        if isinstance(pc, dict):
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


def _check_area_effect_cloud(entity: dict, entity_path: str, rel: str,
                             min_v: str, max_v: str, min_dv: int, max_dv: int) -> list[str]:
    errors: list[str] = []
    envelope_side = side_of(min_dv, max_dv, DV_1_20_5)
    rename_side = side_of(min_dv, max_dv, DV_1_20_2)

    legacy_pascal = entity.get("Effects")
    legacy_snake = entity.get("custom_potion_effects")
    pc = entity.get("potion_contents")

    has_new = isinstance(pc, dict) and "custom_effects" in pc
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
    svc = services(ctx)
    store = svc.structures
    if not store.dir.exists():
        return True, "no structures directory"
    if not svc.versions:
        return True, "skipped (no version map)"

    errors: list[str] = []
    files_checked = 0
    items_checked = 0

    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue
        args = (rel, fr.min_version, fr.max_version, fr.min_dv, fr.max_dv)

        for entity, entity_path in structure.walk_entities():
            if str(entity.get("id", "")) == "minecraft:area_effect_cloud":
                errors.extend(_check_area_effect_cloud(entity, entity_path, *args))
            for slot_path, item in entity_items(entity, entity_path):
                if str(item.get("id", "")) in _POTION_ITEM_IDS:
                    items_checked += 1
                    errors.extend(_check_potion_item(item, slot_path, *args))

        for slot_path, item in block_entity_items(structure.block_entities, compound_slots=()):
            if str(item.get("id", "")) in _POTION_ITEM_IDS:
                items_checked += 1
                errors.extend(_check_potion_item(item, slot_path, *args))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {items_checked} potion item(s) checked -- all valid")
        return True, f"{files_checked} files, {items_checked} potion items checked"
    return False, f"{len(errors)} potion effect error(s)"
