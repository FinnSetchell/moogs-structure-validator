from __future__ import annotations

import json
from collections import defaultdict
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


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    loot_table_dir = data_dir(namespace_root, "loot_table")

    if not loot_table_dir.exists():
        print("  no loot table directory — skipped")
        return True, "skipped (no loot tables)"

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

    # NBT palette scan — grouped by block ID
    structure_dir = data_dir(namespace_root, "structure")
    by_block: dict[str, list[str]] = defaultdict(list)

    if structure_dir.exists():
        for nbt_path in sorted(structure_dir.rglob("*.nbt")):
            try:
                nbt = nbtlib.load(str(nbt_path))
            except Exception:
                continue
            palette = nbt.get("palette")
            if palette is None:
                continue
            rel = str(nbt_path.relative_to(structure_dir))
            seen_in_file: set[str] = set()
            for entry in palette:
                name_tag = entry.get("Name")
                if name_tag is None:
                    continue
                name = str(name_tag)
                if ":" in name and name not in seen_in_file and not _is_valid(name, ctx.valid_blocks, ctx.extra_ids):
                    by_block[name].append(rel)
                    seen_in_file.add(name)

    # print loot table results
    if unknown_items or unknown_blocks:
        if unknown_items:
            print(f"  loot tables: {len(unknown_items)} unknown item ID(s):")
            for id_ in unknown_items:
                print(f"    {id_}")
        if unknown_blocks:
            print(f"  loot tables: {len(unknown_blocks)} unknown block ID(s):")
            for id_ in unknown_blocks:
                print(f"    {id_}")
    else:
        print("  loot tables: all item and block IDs valid")

    # print palette results
    if by_block:
        total_files = sum(len(v) for v in by_block.values())
        print(f"  NBT palettes: {len(by_block)} unknown block type(s) across {total_files} file(s):")
        id_w = max(len(k) for k in by_block) + 2
        for block_id in sorted(by_block):
            files = by_block[block_id]
            shown = ", ".join(files[:3])
            suffix = f"  (+ {len(files) - 3} more)" if len(files) > 3 else ""
            count = f"{len(files)} file" + ("s" if len(files) != 1 else "")
            print(f"    {block_id:<{id_w}} {count}: {shown}{suffix}")
    else:
        print("  NBT palettes: all block IDs valid")

    overall_pass = not unknown_items and not unknown_blocks and not by_block

    parts = []
    if unknown_items:
        parts.append(f"{len(unknown_items)} unknown item(s)")
    if unknown_blocks:
        parts.append(f"{len(unknown_blocks)} unknown block(s) in loot tables")
    if by_block:
        parts.append(f"{len(by_block)} unknown block type(s) in palettes")
    summary = ", ".join(parts) if parts else "all IDs valid"

    return overall_pass, summary
