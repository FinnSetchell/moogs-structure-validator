"""Every ``.nbt`` under the structures directory parses as NBT.

This is the check that pays for parsing: every file is loaded here (orphans
included) and the parsed structure is shared with every later check.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    store = services(ctx).structures

    if not store.dir.exists():
        print(f"  structure directory not found: {store.dir}")
        return False, "structure directory missing"

    ok = 0
    corrupt: list[tuple[str, str]] = []
    for nbt_path in store.files:
        try:
            store.load(nbt_path)
            ok += 1
        except Exception as e:
            corrupt.append((store.rel(nbt_path), str(e)))

    total = ok + len(corrupt)
    if corrupt:
        print(f"  {total} files scanned, {len(corrupt)} corrupt:")
        for path, err in corrupt:
            print(f"    {path}")
            print(f"      {err}")
    else:
        print(f"  {total} files scanned, 0 corrupt")

    summary = f"{total} files, {len(corrupt)} CORRUPT" if corrupt else f"{total} files, 0 corrupt"
    return len(corrupt) == 0, summary
