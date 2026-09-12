"""Containers carry loot (warn-only).

Chests, trapped chests, barrels, all shulker boxes, dispensers and droppers are
expected to hold a ``LootTable``. An empty container warns (barrels and hoppers
excepted: they fill from the world), and hardcoded ``Items`` without a loot
table warn (dispensers, droppers and hoppers excepted: their contents are
deliberate).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext

SHULKER_BOXES = {
    "minecraft:shulker_box",
    "minecraft:white_shulker_box",
    "minecraft:orange_shulker_box",
    "minecraft:magenta_shulker_box",
    "minecraft:light_blue_shulker_box",
    "minecraft:yellow_shulker_box",
    "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box",
    "minecraft:gray_shulker_box",
    "minecraft:light_gray_shulker_box",
    "minecraft:cyan_shulker_box",
    "minecraft:purple_shulker_box",
    "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box",
    "minecraft:green_shulker_box",
    "minecraft:red_shulker_box",
    "minecraft:black_shulker_box",
}

CONTAINER_BLOCKS = {
    "minecraft:chest",
    "minecraft:trapped_chest",
    "minecraft:barrel",
    "minecraft:hopper",
    "minecraft:dispenser",
    "minecraft:dropper",
    *SHULKER_BOXES,
}
_CONTAINER_BLOCKS = CONTAINER_BLOCKS

# Having no items is normal for these (they fill dynamically or are decorative).
_NO_EMPTY_WARN = {"minecraft:barrel", "minecraft:hopper"}

# Hardcoded items are intentional for these.
_NO_HARDCODED_WARN = {"minecraft:hopper", "minecraft:dispenser", "minecraft:dropper"}


def format_pos(pos: tuple[int, int, int] | None) -> str:
    return f"({', '.join(str(int(x)) for x in pos)})" if pos is not None else "(?)"


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    store = services(ctx).structures
    if not store.dir.exists():
        return True, "no structures directory"

    empty: list[str] = []
    hardcoded: list[str] = []

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception:
            continue
        if structure.palette is None:
            continue

        rel = store.rel(nbt_path)
        names = structure.palette_names()
        container_indices = {i: name for i, name in enumerate(names) if name in CONTAINER_BLOCKS}
        if not container_indices:
            continue

        for _, state, pos, block_nbt in structure.blocks_in_states(container_indices):
            block_name = container_indices[state]
            label = f"{rel} @ {format_pos(pos)} [{block_name}]"

            if block_nbt is None:
                if block_name not in _NO_EMPTY_WARN:
                    empty.append(label)
                continue

            has_loot = "LootTable" in block_nbt
            items_tag = block_nbt.get("Items")
            has_items = items_tag is not None and len(items_tag) > 0

            if not has_loot and not has_items and block_name not in _NO_EMPTY_WARN:
                empty.append(label)
            elif has_items and not has_loot and block_name not in _NO_HARDCODED_WARN:
                hardcoded.append(label)

    for msg in empty:
        print(f"  [WARN] empty container: {msg}")
    for msg in hardcoded:
        print(f"  [WARN] hardcoded items: {msg}")

    if not empty and not hardcoded:
        print("  all containers have loot tables")

    parts = []
    if empty:
        parts.append(f"{len(empty)} empty")
    if hardcoded:
        parts.append(f"{len(hardcoded)} hardcoded")
    return True, ", ".join(parts) if parts else "all containers valid"
