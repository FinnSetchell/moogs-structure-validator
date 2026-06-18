from __future__ import annotations

from typing import TYPE_CHECKING

from utils.nbt_cache import load_nbt
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext

# Pool refs in these namespaces are always valid without a local file check
_EXTERNAL_OK = {"minecraft"}


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structure_dir = data_dir(namespace_root, "structure")
    template_pool_dir = namespace_root / "worldgen" / "template_pool"

    if not structure_dir.exists():
        return True, "no structures directory"

    known_pools: set[str] = set()
    if template_pool_dir.exists():
        for json_path in template_pool_dir.rglob("*.json"):
            rel = json_path.relative_to(template_pool_dir)
            pool_name = str(rel.with_suffix("")).replace("\\", "/")
            known_pools.add(f"{ctx.namespace}:{pool_name}")

    warnings: list[str] = []
    jigsaw_count = 0

    for nbt_path in sorted(structure_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue

        palette = nbt.get("palette")
        blocks = nbt.get("blocks")
        if palette is None or blocks is None:
            continue

        rel = str(nbt_path.relative_to(structure_dir))

        jigsaw_indices: set[int] = set()
        for i, state in enumerate(palette):
            if str(state.get("Name", "")) == "minecraft:jigsaw":
                jigsaw_indices.add(i)

        if not jigsaw_indices:
            continue

        for block in blocks:
            state_idx = int(block.get("state", -1))
            if state_idx not in jigsaw_indices:
                continue

            block_nbt = block.get("nbt")
            if block_nbt is None:
                continue
            pool_tag = block_nbt.get("pool")
            if pool_tag is None:
                continue

            pool = str(pool_tag)
            jigsaw_count += 1

            if ":" not in pool:
                continue
            ns = pool.split(":", 1)[0]
            if ns in _EXTERNAL_OK:
                continue
            if ns == ctx.namespace and pool in known_pools:
                continue

            pos_tag = block.get("pos")
            pos = f"({', '.join(str(int(x)) for x in pos_tag)})" if pos_tag is not None else "(?)"
            reason = "pool not found" if ns == ctx.namespace else "unknown namespace"
            warnings.append(f"{rel} @ {pos} -> {pool!r} ({reason})")

    for msg in warnings:
        print(f"  [WARN] jigsaw pool: {msg}")

    if jigsaw_count == 0:
        print("  no jigsaw blocks found")
    elif not warnings:
        print(f"  {jigsaw_count} jigsaw block(s), all pools valid")

    summary = (
        f"{jigsaw_count} jigsaw block(s), {len(warnings)} pool warning(s)"
        if warnings
        else f"{jigsaw_count} jigsaw block(s), all valid"
    )
    return True, summary
