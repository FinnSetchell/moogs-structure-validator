from __future__ import annotations

from typing import Iterator

import nbtlib

# DV >= 3837: 1.20.5 — item storage switches from Count+tag to count+components
ITEM_FORMAT_DV = 3837
# DV >= 4325: 1.21.5 — entity equipment unified into `equipment` compound
EQUIPMENT_DV = 4325

# List-typed equipment slots on entity NBT (pre-1.21.5)
_LIST_SLOTS = ("HandItems", "ArmorItems", "Inventory", "Items")
# Single-compound equipment slots on entity NBT
_COMPOUND_SLOTS = ("body_armor_item", "SaddleItem", "ArmorItem", "DecorItem", "Item")


def iter_entity_items(
    entity_nbt: nbtlib.Compound, file_dv: int
) -> Iterator[tuple[str, nbtlib.Compound]]:
    """Yield (slot_desc, item) for every item compound in entity_nbt."""
    for field in _LIST_SLOTS:
        items_list = entity_nbt.get(field)
        if items_list is None:
            continue
        for i, item in enumerate(items_list):
            if isinstance(item, nbtlib.Compound):
                yield f"{field}[{i}]", item

    for field in _COMPOUND_SLOTS:
        item = entity_nbt.get(field)
        if isinstance(item, nbtlib.Compound):
            yield field, item

    if file_dv >= EQUIPMENT_DV:
        equip = entity_nbt.get("equipment")
        if isinstance(equip, nbtlib.Compound):
            for slot_name, item in equip.items():
                if isinstance(item, nbtlib.Compound):
                    yield f"equipment.{slot_name}", item


def check_item_era(
    item: nbtlib.Compound,
    file_dv: int,
    slot_desc: str,
    entity_id: str,
    rel: str,
    file_version: str,
) -> str | None:
    """Return an [ERROR] string if the item's custom-data key is the wrong era, else None.

    Pre-1.20.5 (DV < 3837): items must use `tag`; `components` is invalid.
    1.20.5+   (DV >= 3837): items must use `components`; `tag` is invalid.
    Items with neither key are always fine.
    """
    if "id" not in item:
        return None
    has_tag = "tag" in item
    has_components = "components" in item
    if not has_tag and not has_components:
        return None

    if file_dv < ITEM_FORMAT_DV and has_components:
        return (
            f"[ERROR] {rel}: entity {entity_id!r} has `components` on item in {slot_desc}"
            f" (min target {file_version} is pre-1.20.5; use `tag` not `components`)"
        )
    if file_dv >= ITEM_FORMAT_DV and has_tag:
        return (
            f"[ERROR] {rel}: entity {entity_id!r} has legacy `tag` on item in {slot_desc}"
            f" (min target {file_version} is 1.20.5+; use `components` not `tag`)"
        )
    return None
