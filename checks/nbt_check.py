from __future__ import annotations

from typing import TYPE_CHECKING

import nbtlib

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        print(f"  structure directory not found: {structures_dir}")
        return False, "structure directory missing"

    ok = 0
    corrupt: list[tuple[str, str]] = []

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        rel = nbt_path.relative_to(structures_dir)
        try:
            nbtlib.load(str(nbt_path))
            ok += 1
        except Exception as e:
            corrupt.append((str(rel), str(e)))

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
