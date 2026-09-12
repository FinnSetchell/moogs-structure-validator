"""Every ``LootTable`` a structure file names in our namespace exists on disk."""
from __future__ import annotations

import collections
from pathlib import Path
from typing import TYPE_CHECKING

from core.context import services
from core.project import loc_to_path

if TYPE_CHECKING:
    from core.context import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project, store = svc.project, svc.structures
    structure_dir = project.structures_dir
    loot_table_dir = project.loot_table_dir

    if not structure_dir.exists():
        print(f"  structure directory not found: {structure_dir}")
        return False, "structure directory missing"
    if not loot_table_dir.exists():
        print(f"  loot table directory not found: {loot_table_dir}")
        return False, "loot table directory missing"

    structure_tables: dict[str, set[str]] = {}
    for nbt_path in store.checked_files():
        rel = str(nbt_path.relative_to(structure_dir).with_suffix("")).replace("\\", "/")
        try:
            structure = store.load(nbt_path)
        except Exception as e:
            print(f"  [ERROR] {rel}.nbt — {e}")
            continue
        structure_tables[rel] = structure.loot_table_refs()

    all_refs: set[str] = set()
    for tables in structure_tables.values():
        all_refs |= tables

    missing: dict[str, list[str]] = collections.defaultdict(list)
    minecraft_refs: dict[str, list[str]] = collections.defaultdict(list)
    other_refs: dict[str, list[str]] = collections.defaultdict(list)

    def users(ref: str) -> list[str]:
        return [struct for struct, tables in structure_tables.items() if ref in tables]

    for ref in sorted(all_refs):
        if ":" not in ref:
            other_refs[ref] = []
            continue
        namespace, _ = ref.split(":", 1)
        if namespace == "minecraft":
            minecraft_refs[ref].extend(users(ref))
        elif namespace == ctx.namespace:
            path = loc_to_path(ref, ctx.namespace, loot_table_dir, ".json")
            if path and not path.exists():
                missing[ref].extend(users(ref))
        else:
            other_refs[ref].extend(users(ref))

    total = len(structure_tables)
    with_loot = sum(1 for t in structure_tables.values() if t)
    print(f"  {total} structures scanned: {with_loot} with loot tables, {total - with_loot} without")

    if missing:
        print(f"  {len(missing)} missing loot table(s):")
        for ref, structs in sorted(missing.items()):
            expected = loc_to_path(ref, ctx.namespace, loot_table_dir, ".json")
            expected_rel: object = expected.relative_to(loot_table_dir) if expected else ref
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
