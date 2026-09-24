"""Every jigsaw block's ``pool`` names a real template pool (warn-only).

A pool in our namespace must have a matching JSON under
``worldgen/template_pool``. A ``minecraft:`` pool must exist in vanilla on at
least one targeted version, per misode/mcmeta's ``worldgen/template_pool``
registry (when that registry cannot be fetched, vanilla pools are taken as
valid, as they always were). Any other namespace warns: it cannot be verified
from this pack.

In an overlay pack (``"overlay": true``) a pool in our namespace that the pack
does not ship is the parent mod's to provide, which is the normal shape for a
jigsaw that hands back to the parent's pieces. Those are counted in one line
rather than warned about one by one.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from checks.check_containers import format_pos
from core.context import Services, services

if TYPE_CHECKING:
    from core.context import ValidatorContext


def _vanilla_pools(svc: Services) -> set[str] | None:
    """Every vanilla template pool id on any targeted version; None when the
    registry is unavailable (then vanilla refs are not checked)."""
    try:
        pools = svc.mcmeta.union("worldgen/template_pool")
    except Exception:
        return None
    return pools or None


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project, store = svc.project, svc.structures
    if not store.dir.exists():
        return True, "no structures directory"

    pool_dir = project.template_pool_dir
    known_pools = {
        f"{ctx.namespace}:{str(p.relative_to(pool_dir).with_suffix('')).replace(chr(92), '/')}"
        for p in project.json_files(pool_dir)
    }

    vanilla_pools = _vanilla_pools(svc)
    warnings: list[str] = []
    from_parent: set[str] = set()
    jigsaw_count = 0

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception:
            continue
        if structure.palette is None:
            continue

        rel = store.rel(nbt_path)
        jigsaw_indices = {i for i, name in enumerate(structure.palette_names()) if name == "minecraft:jigsaw"}
        if not jigsaw_indices:
            continue

        for _, _, pos, block_nbt in structure.blocks_in_states(jigsaw_indices):
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
            if ns == ctx.namespace:
                if pool in known_pools:
                    continue
                if project.overlay:
                    from_parent.add(pool)
                    continue
                reason = "pool not found"
            elif ns == "minecraft":
                if vanilla_pools is None or pool in vanilla_pools:
                    continue
                reason = "vanilla pool not found"
            else:
                reason = "unknown namespace"
            warnings.append(f"{rel} @ {format_pos(pos)} -> {pool!r} ({reason})")

    for msg in warnings:
        print(f"  [WARN] jigsaw pool: {msg}")
    if from_parent:
        print(f"  {len(from_parent)} pool(s) not in this pack (expected from the parent mod)")

    if jigsaw_count == 0:
        print("  no jigsaw blocks found")
    elif not warnings:
        print(f"  {jigsaw_count} jigsaw block(s), all pools valid")

    summary = (
        f"{jigsaw_count} jigsaw block(s), {len(warnings)} pool warning(s)"
        if warnings
        else f"{jigsaw_count} jigsaw block(s), all valid"
    )
    if from_parent:
        summary += f" ({len(from_parent)} pool(s) from the parent mod)"
    return True, summary
