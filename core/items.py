"""Where item stacks live inside entity and block-entity NBT.

Each check names the slots it cares about; these helpers do the walking. Paths
follow the file's own layout (``entities[3].HandItems[0]``,
``blocks[42].nbt.Items[5]``) so a message points at exactly one compound.
"""
from __future__ import annotations

from typing import Iterator

from core.mcversions import DV_1_21_5
from core.nbt import BlockEntity

# The full slot set: every list and compound slot that has ever held an item on
# an entity. `equipment` (1.21.5+) is walked when the caller asks for it.
LIST_SLOTS_ALL = ("HandItems", "ArmorItems", "Inventory", "Items")
COMPOUND_SLOTS_ALL = ("body_armor_item", "SaddleItem", "ArmorItem", "DecorItem", "Item")

# The equipment-only view most content checks use.
LIST_SLOTS_EQUIPMENT = ("HandItems", "ArmorItems")
COMPOUND_SLOTS_EQUIPMENT = ("body_armor_item", "SaddleItem", "Item")


def entity_items(
    entity: dict,
    prefix: str,
    list_slots: tuple[str, ...] = LIST_SLOTS_EQUIPMENT,
    compound_slots: tuple[str, ...] = COMPOUND_SLOTS_EQUIPMENT,
    equipment: bool = True,
) -> Iterator[tuple[str, dict]]:
    """``(path, item)`` for every item compound in the named slots of ``entity``.
    ``prefix`` is the entity's path (or ``""`` for slot-relative paths)."""
    dot = f"{prefix}." if prefix else ""
    for field in list_slots:
        items = entity.get(field)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, dict):
                    yield f"{dot}{field}[{i}]", item
    for field in compound_slots:
        item = entity.get(field)
        if isinstance(item, dict):
            yield f"{dot}{field}", item
    if equipment:
        equip = entity.get("equipment")
        if isinstance(equip, dict):
            for slot, item in equip.items():
                if isinstance(item, dict):
                    yield f"{dot}equipment.{slot}", item


def entity_items_for_dv(entity: dict, prefix: str, file_dv: int) -> Iterator[tuple[str, dict]]:
    """Every slot, with ``equipment`` only once the file can carry it (1.21.5+)."""
    return entity_items(entity, prefix, LIST_SLOTS_ALL, COMPOUND_SLOTS_ALL, file_dv >= DV_1_21_5)


def block_entity_items(
    block_entities: list[BlockEntity],
    compound_slots: tuple[str, ...] = ("Book", "item"),
) -> Iterator[tuple[str, dict]]:
    """``(path, item)`` for container ``Items`` plus the named single-item slots
    (a lectern's ``Book``, a decorated pot's ``item``) of every block entity."""
    for be in block_entities:
        base = f"blocks[{be.index}].nbt"
        items = be.nbt.get("Items")
        if isinstance(items, list):
            for j, item in enumerate(items):
                if isinstance(item, dict):
                    yield f"{base}.Items[{j}]", item
        for field in compound_slots:
            item = be.nbt.get(field)
            if isinstance(item, dict):
                yield f"{base}.{field}", item


def item_id(item: dict) -> str:
    return str(item.get("id", ""))
