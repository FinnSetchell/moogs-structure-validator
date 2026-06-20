from __future__ import annotations

import re
from typing import TYPE_CHECKING

import nbtlib

from utils.loot_tables import iter_spawn_egg_loot_entries
from utils.nbt_cache import load_nbt
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext

_SPAWN_EGG_RE = re.compile(r"^minecraft:.+_spawn_egg$")

_SHULKER_BOXES = {
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

_CONTAINER_BLOCKS = {
    "minecraft:chest",
    "minecraft:trapped_chest",
    "minecraft:barrel",
    "minecraft:hopper",
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:decorated_pot",
    *_SHULKER_BOXES,
}

_CONTAINER_ENTITY_IDS = {
    "minecraft:chest_minecart",
    "minecraft:hopper_minecart",
}

_ITEM_FRAME_IDS = {
    "minecraft:item_frame",
    "minecraft:glow_item_frame",
}


def _is_spawn_egg(item_id: str) -> bool:
    return bool(_SPAWN_EGG_RE.match(item_id))


def _check_items_list(
    items: nbtlib.List, rel: str, context: str, errors: list[str]
) -> None:
    for i, item in enumerate(items):
        if not isinstance(item, nbtlib.Compound):
            continue
        item_id = str(item.get("id", ""))
        if _is_spawn_egg(item_id):
            errors.append(f"  [ERROR] {rel}: {context}[{i}] = {item_id}")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structure_dir = data_dir(namespace_root, "structure")
    loot_table_dir = data_dir(namespace_root, "loot_table")

    errors: list[str] = []

    if structure_dir.exists():
        for nbt_path in sorted(structure_dir.rglob("*.nbt")):
            if nbt_path.resolve() in ctx.orphan_nbts:
                continue
            try:
                nbt = load_nbt(ctx, nbt_path)
            except Exception:
                continue

            rel = str(nbt_path.relative_to(structure_dir))
            palette = nbt.get("palette")
            blocks = nbt.get("blocks")

            if palette is not None and blocks is not None:
                container_indices: dict[int, str] = {}
                for i, state in enumerate(palette):
                    name = str(state.get("Name", ""))
                    if name in _CONTAINER_BLOCKS:
                        container_indices[i] = name

                for block in blocks:
                    state_idx = int(block.get("state", -1))
                    if state_idx not in container_indices:
                        continue
                    block_nbt = block.get("nbt")
                    if block_nbt is None:
                        continue
                    items = block_nbt.get("Items")
                    if not items:
                        continue
                    pos_tag = block.get("pos")
                    pos = f"({', '.join(str(int(x)) for x in pos_tag)})" if pos_tag is not None else "(?)"
                    block_name = container_indices[state_idx]
                    _check_items_list(items, rel, f"{block_name} @ {pos} > Items", errors)

            for entity_entry in nbt.get("entities") or []:
                entity_nbt = entity_entry.get("nbt")
                if not isinstance(entity_nbt, nbtlib.Compound):
                    continue
                entity_id = str(entity_nbt.get("id", ""))

                if entity_id in _CONTAINER_ENTITY_IDS:
                    items = entity_nbt.get("Items")
                    if items:
                        _check_items_list(items, rel, f"{entity_id} > Items", errors)

                if entity_id in _ITEM_FRAME_IDS:
                    item = entity_nbt.get("Item")
                    if isinstance(item, nbtlib.Compound):
                        item_id = str(item.get("id", ""))
                        if _is_spawn_egg(item_id):
                            errors.append(f"  [ERROR] {rel}: {entity_id} > Item = {item_id}")

    if loot_table_dir.exists():
        for json_path in sorted(loot_table_dir.rglob("*.json")):
            rel = str(json_path.relative_to(loot_table_dir))
            for entry_path, item_id in iter_spawn_egg_loot_entries(json_path):
                errors.append(f"  [ERROR] loot_table/{rel}: {entry_path} = {item_id}")

    for msg in errors:
        print(msg)

    if not errors:
        print("  no spawn eggs found in containers or loot tables")

    if errors:
        return False, f"{len(errors)} spawn egg(s) found"
    return True, "no spawn eggs in containers or loot tables"
