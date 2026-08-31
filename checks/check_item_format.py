from __future__ import annotations

from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import nbtlib

from registries.fetcher import fetch_registry_set
from utils.boundaries import DV_1_20_5, DV_1_21_5, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.item_format import check_item_era, iter_entity_items
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


def _iter_items_in_blocks(nbt: nbtlib.Compound) -> Iterator[tuple[str, nbtlib.Compound]]:
    for i, block_entry in enumerate(nbt.get("blocks") or []):
        block_nbt = block_entry.get("nbt")
        if not isinstance(block_nbt, nbtlib.Compound):
            continue
        base = f"blocks[{i}].nbt"
        items = block_nbt.get("Items")
        if isinstance(items, list):
            for j, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{base}.Items[{j}]", item
        for field in ("Book", "item"):
            it = block_nbt.get(field)
            if isinstance(it, nbtlib.Compound):
                yield f"{base}.{field}", it


def _check_enchantments(
    item: nbtlib.Compound, path: str, item_id: str, rel: str,
    min_v: str, max_v: str, min_dv: int, max_dv: int,
    valid_enchants: set[str] | None, extra_ids: set[str],
) -> list[str]:
    """Enchantments live in three shapes across versions.

    <1.20.5: item.tag.Enchantments = [{id, lvl}, ...]
    1.20.5-1.21.4: item.components["minecraft:enchantments"] = {levels: {id: lvl, ...}, ...}
    >=1.21.5: item.components["minecraft:enchantments"] = {id: lvl, ...} (no `levels` wrapper)
    """
    errors: list[str] = []
    fmt_side = side_of(min_dv, max_dv, DV_1_20_5)
    wrap_side = side_of(min_dv, max_dv, DV_1_21_5)

    tag = item.get("tag")
    comps = item.get("components")

    if isinstance(tag, nbtlib.Compound):
        ench_list = tag.get("Enchantments")
        if isinstance(ench_list, list) and ench_list:
            if fmt_side == BoundarySide.NEW:
                errors.append(
                    f"[ERROR] {rel}: {path}.tag.Enchantments used on min>=1.20.5 target"
                    f" ({min_v}); enchantments must live under components at 1.20.5+"
                )
            elif valid_enchants is not None:
                for i, e in enumerate(ench_list):
                    if not isinstance(e, nbtlib.Compound):
                        continue
                    id_tag = e.get("id")
                    if id_tag is None:
                        continue
                    id_str = str(id_tag)
                    if id_str.startswith("minecraft:") and id_str not in valid_enchants:
                        errors.append(
                            f"[ERROR] {rel}: {path}.tag.Enchantments[{i}]: unknown enchantment"
                            f" '{id_str}' (min target {min_v})"
                        )

    if isinstance(comps, nbtlib.Compound):
        ench = comps.get("minecraft:enchantments")
        if isinstance(ench, nbtlib.Compound):
            key = "minecraft:enchantments"
            has_levels = "levels" in ench
            if wrap_side == BoundarySide.NEW and has_levels:
                errors.append(
                    f"[ERROR] {rel}: {path}.components.{key}: `levels` wrapper on min>=1.21.5"
                    f" target ({min_v}); at 1.21.5+ enchantments are inlined ({{id: lvl, ...}})"
                )
            elif wrap_side == BoundarySide.OLD and not has_levels:
                errors.append(
                    f"[ERROR] {rel}: {path}.components.{key}: missing `levels` wrapper on"
                    f" max<1.21.5 target ({max_v}); pre-1.21.5 uses {{levels: {{id: lvl}}}}"
                )
            elif wrap_side == BoundarySide.SPANS:
                errors.append(
                    f"[ERROR] {rel}: {path}.components.{key}: enchantments across range"
                    f" {min_v}..{max_v} span 1.21.5; `levels` wrapper is incompatible on both"
                )

            # Validate ids
            id_map = ench.get("levels") if has_levels else ench
            if valid_enchants is not None and isinstance(id_map, nbtlib.Compound):
                for id_str in id_map:
                    if id_str.startswith("minecraft:") and id_str not in valid_enchants:
                        # Common gotcha: sweeping -> sweeping_edge at 1.20.5.
                        hint = ""
                        if id_str == "minecraft:sweeping":
                            hint = " (renamed to `sweeping_edge` at 1.20.5)"
                        errors.append(
                            f"[ERROR] {rel}: {path}.components.{key}: unknown enchantment"
                            f" '{id_str}'{hint} (min target {min_v})"
                        )
    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"
    version_map = load_version_map(cache_dir, ctx.refresh)

    global_min_version = min(ctx.mc_versions, key=_parse_version)
    global_max_version = max(ctx.mc_versions, key=_parse_version)

    nbt_ranges = {}
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if template_pool_dir.exists():
        nbt_ranges = _build_nbt_version_ranges(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version,
            ctx.mc_versions, global_max_version,
        )

    version_ench_cache: dict[str, set[str]] = {}

    def valid_enchants_for(version: str) -> set[str] | None:
        if version not in version_ench_cache:
            try:
                version_ench_cache[version] = fetch_registry_set(
                    version, cache_dir, ctx.refresh, "enchantment"
                )
            except Exception:
                version_ench_cache[version] = set()
        return version_ench_cache[version] or None

    errors: list[str] = []
    items_checked = 0
    files_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue

        files_checked += 1
        rel = str(nbt_path.relative_to(structures_dir))

        info = nbt_ranges.get(nbt_path)
        file_min = info.min_version if info else global_min_version
        file_max = info.max_version if info else global_max_version
        min_dv = version_map.get(file_min)
        max_dv = version_map.get(file_max)
        if min_dv is None or max_dv is None:
            continue

        valid_enchants = valid_enchants_for(file_min)

        # Entities and their items (recursed).
        for entity_nbt, entity_path in iter_entities(nbt):
            entity_id = str(entity_nbt.get("id", "?"))
            for slot_desc, item in iter_entity_items(entity_nbt, min_dv):
                items_checked += 1
                full_path = f"{entity_path}.{slot_desc}"
                msg = check_item_era(item, min_dv, full_path, entity_id, rel, file_min)
                if msg:
                    errors.append(msg)
                item_id = str(item.get("id", "?"))
                errors.extend(_check_enchantments(
                    item, full_path, item_id, rel,
                    file_min, file_max, min_dv, max_dv, valid_enchants, ctx.extra_ids,
                ))

        # Block-entity items (containers, lecterns, decorated pots, etc.)
        for slot_desc, item in _iter_items_in_blocks(nbt):
            items_checked += 1
            item_id = str(item.get("id", "?"))
            msg = check_item_era(item, min_dv, slot_desc, item_id, rel, file_min)
            if msg:
                errors.append(msg)
            errors.extend(_check_enchantments(
                item, slot_desc, item_id, rel,
                file_min, file_max, min_dv, max_dv, valid_enchants, ctx.extra_ids,
            ))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {items_checked} item slot(s) checked -- all valid")

    if errors:
        return False, f"{len(errors)} item format error(s)"
    return True, f"{files_checked} files, {items_checked} item slots checked"
