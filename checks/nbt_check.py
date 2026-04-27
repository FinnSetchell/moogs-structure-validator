from __future__ import annotations

from typing import TYPE_CHECKING

import nbtlib

if TYPE_CHECKING:
    from validator import ValidatorContext


def run(ctx: ValidatorContext) -> bool:
    structures_dir = (
        ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace / "structures"
    )

    if not structures_dir.exists():
        print(f"[nbt_check] structures directory not found: {structures_dir}")
        return False

    ok = 0
    corrupt: list[tuple[str, str]] = []

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        rel = nbt_path.relative_to(structures_dir)
        try:
            nbtlib.load(str(nbt_path))
            ok += 1
        except Exception as e:
            corrupt.append((str(rel), str(e)))
            print(f"  [CORRUPT] {rel}")
            print(f"            {e}")

    print(f"\n{ok} file(s) OK, {len(corrupt)} corrupt.")
    return len(corrupt) == 0
