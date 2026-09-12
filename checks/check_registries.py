"""Item and block ids exist in the Minecraft registries for the targeted versions.

Two independent halves: the ids a loot table names (checked against the lowest
targeted version), and every block id in every structure palette.

Each structure is checked against its *minimum* wired version only. On load the
game runs the file through DataFixerUpper keyed on the file's own DataVersion,
so a block renamed in a later version (``chain`` -> ``iron_chain``, ``grass`` ->
``short_grass``) is re-mapped upward for us. A palette valid at the file's floor
is valid at every version above it; only the floor can fail.

An unknown ``minecraft:`` block is annotated with the first release newer than
the failing version that does know it, or ``unknown ID`` when none does.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from core.context import services
from core.ids import is_valid, non_minecraft
from core.loot import collect_loot_ids as _collect_ids
from core.mcversions import parse_version

if TYPE_CHECKING:
    from core.context import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project, store, reg = svc.project, svc.structures, svc.mcmeta
    loot_table_dir = project.loot_table_dir
    structure_dir = project.structures_dir

    have_loot_tables = loot_table_dir.exists()
    if not have_loot_tables and not structure_dir.exists():
        print("  no loot table or structure directory — skipped")
        return True, "skipped (nothing to scan)"

    global_min_version = svc.global_min
    unknown_items: list[str] = []
    unknown_blocks: list[str] = []

    if have_loot_tables:
        all_items: set[str] = set()
        all_blocks: set[str] = set()
        for json_path in project.json_files(loot_table_dir):
            data = project.try_json(json_path)
            if data is None:
                continue
            _collect_ids(data, all_items, all_blocks)

        valid_items_min = reg.registry(global_min_version, "item") | non_minecraft(ctx.valid_items)
        valid_blocks_min = reg.registry(global_min_version, "block") | non_minecraft(ctx.valid_blocks)
        unknown_items = sorted(i for i in all_items if not is_valid(i, valid_items_min, ctx.extra_ids))
        unknown_blocks = sorted(b for b in all_blocks if not is_valid(b, valid_blocks_min, ctx.extra_ids))

    # Palette scan, grouped by block id.
    by_block: dict[str, list[str]] = defaultdict(list)
    lowest_failing: dict[str, str] = {}
    non_minecraft_blocks = non_minecraft(ctx.valid_blocks)
    valid_for_version: dict[str, set[str]] = {}

    if structure_dir.exists():
        for nbt_path in store.checked_files():
            try:
                structure = store.load(nbt_path)
            except Exception:
                continue
            variants = structure.palette_variants
            if not variants:
                continue
            rel = store.rel(nbt_path)

            file_version = svc.file_min_version(nbt_path)
            valid_blocks_for_file = valid_for_version.get(file_version)
            if valid_blocks_for_file is None:
                valid_blocks_for_file = reg.registry(file_version, "block") | non_minecraft_blocks
                valid_for_version[file_version] = valid_blocks_for_file

            seen_in_file: set[str] = set()
            for palette in variants:
                for entry in palette:
                    name_tag = entry.get("Name") if isinstance(entry, dict) else None
                    if name_tag is None:
                        continue
                    name = str(name_tag)
                    if ":" in name and name not in seen_in_file and not is_valid(name, valid_blocks_for_file, ctx.extra_ids):
                        by_block[name].append(rel)
                        seen_in_file.add(name)
                        prev = lowest_failing.get(name)
                        if prev is None or parse_version(file_version) < parse_version(prev):
                            lowest_failing[name] = file_version

    if not have_loot_tables:
        print("  loot tables: no loot table directory — skipped")
    elif unknown_items or unknown_blocks:
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
            added = reg.version_added("block", block_id, lowest_failing[block_id])
            annotations[block_id] = f"added in {added}" if added else "unknown ID"

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
    if parts:
        summary = ", ".join(parts)
    elif have_loot_tables:
        summary = "all IDs valid"
    else:
        summary = "all palette IDs valid (no loot tables)"
    return overall_pass, summary
