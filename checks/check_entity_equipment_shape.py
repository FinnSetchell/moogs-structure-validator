"""Entity equipment keys match the file's target range, and equipment item ids exist.

At 1.21.5 ``ArmorItems``/``HandItems`` (and the drop-chance lists, body armor
and saddle slots) were absorbed into the ``equipment`` and ``drop_chances``
compounds. A legacy key on a 1.21.5+ target is silently dropped equipment; a
new key on a pre-1.21.5 target is ignored data; a range spanning 1.21.5 cannot
be right on both sides. Only ``minecraft:`` entities are checked. Every item in
every slot must also exist in the item registry at the file's minimum version.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.ids import is_valid, non_minecraft
from core.items import entity_items
from core.mcversions import DV_1_21_5, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

# Keys absorbed into `equipment` / `drop_chances` at 1.21.5. Sorted so the
# reported key is the same on every run (set order varies per process).
_PRE_1_21_5_KEYS = (
    "ArmorDropChances",
    "ArmorItems",
    "HandDropChances",
    "HandItems",
    "Saddle",
    "SaddleItem",
    "body_armor_drop_chance",
    "body_armor_item",
)

# Keys that only exist at 1.21.5+.
_POST_1_21_5_KEYS = ("drop_chances", "equipment", "fall_distance")

_LIST_SLOTS = ("HandItems", "ArmorItems")
_COMPOUND_SLOTS = ("body_armor_item", "SaddleItem")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store, reg = svc.structures, svc.mcmeta
    if not store.dir.exists():
        return True, "no structures directory"
    if not svc.versions:
        return True, "skipped (no version map)"

    modded_items = non_minecraft(ctx.valid_items)
    item_sets: dict[str, set[str]] = {}

    def valid_items_for(version: str) -> set[str]:
        s = item_sets.get(version)
        if s is None:
            s = reg.registry(version, "item") | modded_items
            item_sets[version] = s
        return s

    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue
        min_version, max_version, min_dv, max_dv = fr.min_version, fr.max_version, fr.min_dv, fr.max_dv
        side = side_of(min_dv, max_dv, DV_1_21_5)

        for entity, path in structure.walk_entities():
            id_tag = entity.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            if not entity_id.startswith("minecraft:"):
                continue
            entities_checked += 1

            if side == BoundarySide.NEW:
                for key in _PRE_1_21_5_KEYS:
                    if key in entity:
                        errors.append(
                            f"[ERROR] {rel}: {path} (entity {entity_id!r}) has legacy key"
                            f" `{key}` on a min>=1.21.5 target ({min_version}, DV {min_dv});"
                            f" this equipment is silently dropped at 1.21.5+"
                        )
            elif side == BoundarySide.OLD:
                for key in _POST_1_21_5_KEYS:
                    if key in entity:
                        errors.append(
                            f"[ERROR] {rel}: {path} (entity {entity_id!r}) has 1.21.5+ key"
                            f" `{key}` on a max<1.21.5 target ({max_version}, DV {max_dv});"
                            f" pre-1.21.5 clients ignore this data"
                        )
            else:
                for key in _PRE_1_21_5_KEYS + _POST_1_21_5_KEYS:
                    if key in entity:
                        errors.append(
                            f"[ERROR] {rel}: {path} (entity {entity_id!r}) has boundary-sensitive"
                            f" key `{key}` but wired range {min_version}..{max_version} spans"
                            f" 1.21.5; no single file can be correct on both sides"
                        )
                        break  # one message per spanning entity is enough

            valid_items = valid_items_for(min_version)
            for slot_desc, item in entity_items(entity, "", _LIST_SLOTS, _COMPOUND_SLOTS, True):
                item_id_tag = item.get("id")
                if item_id_tag is None:
                    continue
                item_id = str(item_id_tag)
                if not is_valid(item_id, valid_items, ctx.extra_ids):
                    errors.append(
                        f"[ERROR] {rel}: {path} (entity {entity_id!r}) equipment slot"
                        f" {slot_desc} has unknown item id '{item_id}'"
                        f" (min target {min_version})"
                    )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity/entities checked -- all valid")
        return True, f"{files_checked} files, {entities_checked} entities checked"
    return False, f"{len(errors)} equipment shape error(s)"
