from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


def _collect_ids(node: object, items: set[str], blocks: set[str]) -> None:
    if isinstance(node, dict):
        entry_type = node.get("type", "")
        condition = node.get("condition", "")

        # item entry: type ends in ":item", name is the item ID
        if isinstance(entry_type, str) and entry_type.endswith(":item"):
            name = node.get("name")
            if isinstance(name, str) and ":" in name:
                items.add(name)

        # block_state_property condition: block field is a block ID
        if isinstance(condition, str) and condition.endswith(":block_state_property"):
            block = node.get("block")
            if isinstance(block, str) and ":" in block:
                blocks.add(block)

        # function node with explicit name (e.g. set_item): name is an item ID
        func = node.get("function", "")
        if isinstance(func, str) and func:
            name = node.get("name")
            if isinstance(name, str) and ":" in name:
                items.add(name)

        for val in node.values():
            _collect_ids(val, items, blocks)

    elif isinstance(node, list):
        for item in node:
            _collect_ids(item, items, blocks)


def _is_valid(id_: str, valid_set: set[str], extra_ids: set[str]) -> bool:
    if id_ in valid_set:
        return True
    if id_ in extra_ids:
        return True
    ns = id_.split(":", 1)[0]
    if f"{ns}:*" in extra_ids:
        return True
    return False


def run(ctx: ValidatorContext) -> bool:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    loot_table_dir = data_dir(namespace_root, "loot_table")

    if not loot_table_dir.exists():
        print(f"[check_registries] loot table directory not found: {loot_table_dir}")
        return True

    all_items: set[str] = set()
    all_blocks: set[str] = set()

    for json_path in sorted(loot_table_dir.rglob("*.json")):
        try:
            with json_path.open() as f:
                data = json.load(f)
        except json.JSONDecodeError:
            continue
        _collect_ids(data, all_items, all_blocks)

    unknown_items = sorted(
        id_ for id_ in all_items if not _is_valid(id_, ctx.valid_items, ctx.extra_ids)
    )
    unknown_blocks = sorted(
        id_ for id_ in all_blocks if not _is_valid(id_, ctx.valid_blocks, ctx.extra_ids)
    )

    structure_dir = data_dir(namespace_root, "structure")
    unknown_palette_blocks: list[str] = []

    if structure_dir.exists():
        for nbt_path in sorted(structure_dir.rglob("*.nbt")):
            try:
                nbt = nbtlib.load(str(nbt_path))
            except Exception:
                continue
            palette = nbt.get("palette")
            if palette is None:
                continue
            for entry in palette:
                name_tag = entry.get("Name")
                if name_tag is None:
                    continue
                name = str(name_tag)
                if ":" in name and not _is_valid(name, ctx.valid_blocks, ctx.extra_ids):
                    rel = nbt_path.relative_to(structure_dir)
                    unknown_palette_blocks.append(f"{rel}: {name}")

    if unknown_items:
        print(f"[check_registries] {len(unknown_items)} unknown item ID(s) in loot tables:")
        for id_ in unknown_items:
            print(f"  {id_}")

    if unknown_blocks:
        print(f"[check_registries] {len(unknown_blocks)} unknown block ID(s) in loot tables:")
        for id_ in unknown_blocks:
            print(f"  {id_}")

    if unknown_palette_blocks:
        print(f"[check_registries] {len(unknown_palette_blocks)} unknown block ID(s) in NBT palettes:")
        for entry in unknown_palette_blocks:
            print(f"  {entry}")

    if not unknown_items and not unknown_blocks and not unknown_palette_blocks:
        print("[check_registries] all item and block IDs valid")

    return not unknown_items and not unknown_blocks and not unknown_palette_blocks
