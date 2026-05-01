from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext

_CONTAINER_BLOCKS = {
    "minecraft:chest",
    "minecraft:trapped_chest",
    "minecraft:barrel",
}


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structure_dir = data_dir(namespace_root, "structure")

    if not structure_dir.exists():
        return True, "no structures directory"

    empty: list[str] = []
    hardcoded: list[str] = []

    for nbt_path in sorted(structure_dir.rglob("*.nbt")):
        try:
            nbt = nbtlib.load(str(nbt_path))
        except Exception:
            continue

        palette = nbt.get("palette")
        blocks = nbt.get("blocks")
        if palette is None or blocks is None:
            continue

        rel = str(nbt_path.relative_to(structure_dir))

        container_indices: dict[int, str] = {}
        for i, state in enumerate(palette):
            name = str(state.get("Name", ""))
            if name in _CONTAINER_BLOCKS:
                container_indices[i] = name

        if not container_indices:
            continue

        for block in blocks:
            state_idx = int(block.get("state", -1))
            if state_idx not in container_indices:
                continue

            block_name = container_indices[state_idx]
            pos_tag = block.get("pos")
            pos = f"({', '.join(str(int(x)) for x in pos_tag)})" if pos_tag is not None else "(?)"
            label = f"{rel} @ {pos} [{block_name}]"

            block_nbt = block.get("nbt")
            if block_nbt is None:
                empty.append(label)
                continue

            has_loot = "LootTable" in block_nbt
            items_tag = block_nbt.get("Items")
            has_items = items_tag is not None and len(items_tag) > 0

            if not has_loot and not has_items:
                empty.append(label)
            elif has_items and not has_loot:
                hardcoded.append(label)

    for msg in empty:
        print(f"  [WARN] empty container: {msg}")
    for msg in hardcoded:
        print(f"  [WARN] hardcoded items: {msg}")

    if not empty and not hardcoded:
        print("  all containers have loot tables")

    parts = []
    if empty:
        parts.append(f"{len(empty)} empty")
    if hardcoded:
        parts.append(f"{len(hardcoded)} hardcoded")
    summary = ", ".join(parts) if parts else "all containers valid"

    return True, summary
