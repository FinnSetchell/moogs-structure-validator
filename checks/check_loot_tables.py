from __future__ import annotations

import collections
from typing import TYPE_CHECKING

import nbtlib
from pathlib import Path

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


def _collect_loot_tables(node, out: set) -> None:
    if isinstance(node, nbtlib.Compound):
        for key, val in node.items():
            if key == "LootTable" and isinstance(val, nbtlib.String):
                out.add(str(val))
            else:
                _collect_loot_tables(val, out)
    elif isinstance(node, nbtlib.List):
        for item in node:
            _collect_loot_tables(item, out)


def _loc_to_loot_path(location: str, namespace: str, loot_table_dir: Path) -> Path | None:
    if ":" not in location:
        return None
    ns, path = location.split(":", 1)
    if ns != namespace:
        return None
    return loot_table_dir / (path + ".json")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structure_dir = data_dir(namespace_root, "structure")
    loot_table_dir = data_dir(namespace_root, "loot_table")

    if not structure_dir.exists():
        print(f"  structure directory not found: {structure_dir}")
        return False, "structure directory missing"
    if not loot_table_dir.exists():
        print(f"  loot table directory not found: {loot_table_dir}")
        return False, "loot table directory missing"

    structure_tables: dict[str, set[str]] = {}

    for nbt_path in sorted(structure_dir.rglob("*.nbt")):
        rel = str(nbt_path.relative_to(structure_dir).with_suffix("")).replace("\\", "/")
        try:
            nbtfile = nbtlib.load(str(nbt_path))
        except Exception as e:
            print(f"  [ERROR] {rel}.nbt — {e}")
            continue
        tables: set[str] = set()
        _collect_loot_tables(nbtfile, tables)
        structure_tables[rel] = tables

    all_refs: set[str] = set()
    for tables in structure_tables.values():
        all_refs |= tables

    missing: dict[str, list[str]] = collections.defaultdict(list)
    minecraft_refs: dict[str, list[str]] = collections.defaultdict(list)
    other_refs: dict[str, list[str]] = collections.defaultdict(list)

    for ref in sorted(all_refs):
        if ":" not in ref:
            other_refs[ref] = []
            continue
        namespace, _ = ref.split(":", 1)
        if namespace == "minecraft":
            for struct, tables in structure_tables.items():
                if ref in tables:
                    minecraft_refs[ref].append(struct)
        elif namespace == ctx.namespace:
            path = _loc_to_loot_path(ref, ctx.namespace, loot_table_dir)
            if path and not path.exists():
                for struct, tables in structure_tables.items():
                    if ref in tables:
                        missing[ref].append(struct)
        else:
            for struct, tables in structure_tables.items():
                if ref in tables:
                    other_refs[ref].append(struct)

    total = len(structure_tables)
    with_loot = sum(1 for t in structure_tables.values() if t)
    print(f"  {total} structures scanned: {with_loot} with loot tables, {total - with_loot} without")

    if missing:
        print(f"  {len(missing)} missing loot table(s):")
        for ref, structs in sorted(missing.items()):
            expected = _loc_to_loot_path(ref, ctx.namespace, loot_table_dir)
            expected_rel = expected.relative_to(loot_table_dir) if expected else ref
            print(f"    {ref}")
            print(f"      expected file: {expected_rel}")
            for s in sorted(structs):
                print(f"      used by: {s}")
    else:
        print(f"  no missing {ctx.namespace}: loot tables")

    if minecraft_refs:
        print(f"  {len(minecraft_refs)} vanilla (minecraft:) loot table(s) referenced")

    if other_refs:
        print(f"  {len(other_refs)} loot table(s) with unrecognised namespace:")
        for ref in sorted(other_refs):
            print(f"    {ref}")

    if missing:
        summary = f"{with_loot} / {total} structures, {len(missing)} missing loot table(s)"
    else:
        summary = f"{with_loot} / {total} structures have loot tables"

    return not missing, summary
