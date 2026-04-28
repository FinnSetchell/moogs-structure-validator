from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from checks.check_data_integrity import _loc_to_path
from registries.fetcher import _fetch_version
from registries.version_probe import find_version_added
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _build_nbt_min_versions(
    template_pool_dir: Path,
    structures_dir: Path,
    namespace: str,
    global_min_version: str,
) -> dict[Path, str]:
    result: dict[Path, tuple[int, ...]] = {}

    for json_path in sorted(template_pool_dir.rglob("*.json")):
        try:
            with json_path.open() as f:
                data = json.load(f)
        except json.JSONDecodeError:
            continue

        for entry in data.get("elements", []):
            element = entry.get("element", {})
            el_type = element.get("element_type") or element.get("type", "")
            if el_type == "moogs_structures:versioned_single_pool_element":
                for range_key, loc in element.get("locations", {}).items():
                    lower = range_key.split("-")[0]
                    nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                    if nbt_path is None:
                        continue
                    parsed = _parse_version(lower)
                    if nbt_path not in result or parsed < result[nbt_path]:
                        result[nbt_path] = parsed
            else:
                loc = element.get("location")
                if loc:
                    nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                    if nbt_path is not None and nbt_path not in result:
                        result[nbt_path] = _parse_version(global_min_version)

    return {p: ".".join(str(x) for x in v) for p, v in result.items()}


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
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    cache_dir = Path(__file__).parent.parent / "cache"
    by_block: dict[str, list[str]] = defaultdict(list)

    global_min_version = min(ctx.mc_versions, key=_parse_version)
    nbt_min_versions: dict[Path, str] = {}
    if template_pool_dir.exists():
        nbt_min_versions = _build_nbt_min_versions(
            template_pool_dir, structure_dir, ctx.namespace, global_min_version
        )

    non_minecraft_valid = {id_ for id_ in ctx.valid_blocks if not id_.startswith("minecraft:")}
    version_block_cache: dict[str, set[str]] = {}

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

            file_version = nbt_min_versions.get(nbt_path, global_min_version)
            if file_version not in version_block_cache:
                vdata = _fetch_version(file_version, cache_dir, ctx.refresh)
                version_block_cache[file_version] = (
                    {"minecraft:" + n for n in vdata.get("block", [])} | non_minecraft_valid
                )
            valid_blocks_for_file = version_block_cache[file_version]

            seen_in_file: set[str] = set()
            for entry in palette:
                name_tag = entry.get("Name")
                if name_tag is None:
                    continue
                name = str(name_tag)
                if ":" in name and name not in seen_in_file and not _is_valid(name, valid_blocks_for_file, ctx.extra_ids):
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

    annotations: dict[str, str] = {}
    for block_id in by_block:
        if block_id.startswith("minecraft:"):
            result = find_version_added(block_id, cache_dir, ctx.refresh)
            annotations[block_id] = f"added in {result}" if result else "unknown ID"

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
            note = f"  [{annotations[block_id]}]" if block_id in annotations else ""
            print(f"    {block_id:<{id_w}} {count}: {shown}{suffix}{note}")
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
