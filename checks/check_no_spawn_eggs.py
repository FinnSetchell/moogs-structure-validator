"""No spawn eggs in containers, item frames, container entities or loot tables.

Any ``minecraft:*_spawn_egg`` in a container block's ``Items``, a chest or
hopper minecart's ``Items``, an item frame's ``Item``, or a loot table's
``minecraft:item`` entries is an error.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from checks.check_containers import SHULKER_BOXES, format_pos
from core.context import services
from core.loot import is_spawn_egg, iter_spawn_egg_loot_entries

if TYPE_CHECKING:
    from core.context import ValidatorContext

_CONTAINER_BLOCKS = {
    "minecraft:chest",
    "minecraft:trapped_chest",
    "minecraft:barrel",
    "minecraft:hopper",
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:decorated_pot",
    *SHULKER_BOXES,
}

_CONTAINER_ENTITY_IDS = {"minecraft:chest_minecart", "minecraft:hopper_minecart"}
_ITEM_FRAME_IDS = {"minecraft:item_frame", "minecraft:glow_item_frame"}


def _check_items_list(items: list, rel: str, context: str, errors: list[str]) -> None:
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        if is_spawn_egg(item_id):
            errors.append(f"  [ERROR] {rel}: {context}[{i}] = {item_id}")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project, store = svc.project, svc.structures
    loot_table_dir = project.loot_table_dir

    errors: list[str] = []

    if store.dir.exists():
        for nbt_path in store.checked_files():
            structure = store.try_load(nbt_path)
            if structure is None:
                continue
            rel = store.rel(nbt_path)

            if structure.palette is not None:
                names = structure.palette_names()
                container_indices = {i: name for i, name in enumerate(names) if name in _CONTAINER_BLOCKS}
                for _, state, pos, block_nbt in structure.blocks_in_states(container_indices):
                    if block_nbt is None:
                        continue
                    items = block_nbt.get("Items")
                    if not items:
                        continue
                    _check_items_list(items, rel, f"{container_indices[state]} @ {format_pos(pos)} > Items", errors)

            for entity_entry in structure.entities:
                entity_nbt = entity_entry.get("nbt") if isinstance(entity_entry, dict) else None
                if not isinstance(entity_nbt, dict):
                    continue
                entity_id = str(entity_nbt.get("id", ""))

                if entity_id in _CONTAINER_ENTITY_IDS:
                    items = entity_nbt.get("Items")
                    if items:
                        _check_items_list(items, rel, f"{entity_id} > Items", errors)

                if entity_id in _ITEM_FRAME_IDS:
                    item = entity_nbt.get("Item")
                    if isinstance(item, dict):
                        item_id = str(item.get("id", ""))
                        if is_spawn_egg(item_id):
                            errors.append(f"  [ERROR] {rel}: {entity_id} > Item = {item_id}")

    if loot_table_dir.exists():
        for json_path in project.json_files(loot_table_dir):
            rel = str(json_path.relative_to(loot_table_dir))
            for entry_path, item_id in iter_spawn_egg_loot_entries(json_path, project.try_json(json_path)):
                errors.append(f"  [ERROR] loot_table/{rel}: {entry_path} = {item_id}")

    for msg in errors:
        print(msg)

    if not errors:
        print("  no spawn eggs found in containers or loot tables")
        return True, "no spawn eggs in containers or loot tables"
    return False, f"{len(errors)} spawn egg(s) found"
