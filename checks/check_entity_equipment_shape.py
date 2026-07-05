from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from registries.fetcher import _fetch_version
from utils.boundaries import DV_1_21_5, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.item_format import EQUIPMENT_DV
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext

# Keys that were absorbed into the unified `equipment` / `drop_chances` compounds at 1.21.5.
# Presence of any of these on a min ≥ 1.21.5 target = silently-dropped equipment in-game.
_PRE_1_21_5_KEYS = frozenset({
    "ArmorItems",
    "HandItems",
    "ArmorDropChances",
    "HandDropChances",
    "body_armor_item",
    "body_armor_drop_chance",
    "SaddleItem",
    "Saddle",
})

# Keys that only exist at 1.21.5+. Presence on max < 1.21.5 = crash or ignored data.
_POST_1_21_5_KEYS = frozenset({
    "equipment",
    "drop_chances",
    "fall_distance",
})

# Equipment slots inside the unified `equipment` compound at 1.21.5+.
_EQUIPMENT_SLOTS = frozenset({
    "head", "chest", "legs", "feet", "mainhand", "offhand", "body", "saddle",
})


def _iter_equipment_items(entity_nbt: nbtlib.Compound):
    """Yield (slot_desc, item_compound) for every item slot on this entity,
    across both pre- and post-1.21.5 shapes."""
    for list_field in ("HandItems", "ArmorItems"):
        items = entity_nbt.get(list_field)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{list_field}[{i}]", item

    for field in ("body_armor_item", "SaddleItem"):
        item = entity_nbt.get(field)
        if isinstance(item, nbtlib.Compound):
            yield field, item

    equip = entity_nbt.get("equipment")
    if isinstance(equip, nbtlib.Compound):
        for slot_name, item in equip.items():
            if isinstance(item, nbtlib.Compound):
                yield f"equipment.{slot_name}", item


def _is_valid(id_: str, valid_set: set[str], extra_ids: set[str]) -> bool:
    if id_ in valid_set:
        return True
    if id_ in extra_ids:
        return True
    ns = id_.split(":", 1)[0]
    if f"{ns}:*" in extra_ids:
        return True
    return False


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"
    version_map = load_version_map(cache_dir, ctx.refresh)
    if not version_map:
        return True, "skipped (no version map)"

    global_min_version = min(ctx.mc_versions, key=_parse_version)
    global_max_version = max(ctx.mc_versions, key=_parse_version)

    nbt_version_ranges = {}
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if template_pool_dir.exists():
        nbt_version_ranges = _build_nbt_version_ranges(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version,
            ctx.mc_versions, global_max_version,
        )

    non_minecraft_items = {i for i in ctx.valid_items if not i.startswith("minecraft:")}
    version_item_cache: dict[str, set[str]] = {}

    def valid_items_for(version: str) -> set[str]:
        if version not in version_item_cache:
            vdata = _fetch_version(version, cache_dir, ctx.refresh)
            version_item_cache[version] = (
                {"minecraft:" + n for n in vdata.get("item", [])} | non_minecraft_items
            )
        return version_item_cache[version]

    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue

        files_checked += 1
        rel = str(nbt_path.relative_to(structures_dir))

        info = nbt_version_ranges.get(nbt_path)
        min_version = info.min_version if info else global_min_version
        max_version = info.max_version if info else global_max_version
        min_dv = version_map.get(min_version)
        max_dv = version_map.get(max_version)
        if min_dv is None or max_dv is None:
            continue

        side = side_of(min_dv, max_dv, DV_1_21_5)

        for entity_nbt, path in iter_entities(nbt):
            id_tag = entity_nbt.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            if not entity_id.startswith("minecraft:"):
                continue
            entities_checked += 1

            if side == BoundarySide.NEW:
                for key in _PRE_1_21_5_KEYS:
                    if key in entity_nbt:
                        errors.append(
                            f"[ERROR] {rel}: {path} (entity {entity_id!r}) has legacy key"
                            f" `{key}` on a min≥1.21.5 target ({min_version}, DV {min_dv});"
                            f" this equipment is silently dropped at 1.21.5+"
                        )
            elif side == BoundarySide.OLD:
                for key in _POST_1_21_5_KEYS:
                    if key in entity_nbt:
                        errors.append(
                            f"[ERROR] {rel}: {path} (entity {entity_id!r}) has 1.21.5+ key"
                            f" `{key}` on a max<1.21.5 target ({max_version}, DV {max_dv});"
                            f" pre-1.21.5 clients ignore this data"
                        )
            else:  # SPANS
                for key in list(_PRE_1_21_5_KEYS) + list(_POST_1_21_5_KEYS):
                    if key in entity_nbt:
                        errors.append(
                            f"[ERROR] {rel}: {path} (entity {entity_id!r}) has boundary-sensitive"
                            f" key `{key}` but wired range {min_version}..{max_version} spans"
                            f" 1.21.5; no single file can be correct on both sides"
                        )
                        break  # one message per spanning entity is enough

            # Validate item ids in every equipment slot against the target min version's registry.
            # (Any missing id is a bug -- spawning would fail on that version.)
            valid_items = valid_items_for(min_version)
            for slot_desc, item in _iter_equipment_items(entity_nbt):
                item_id_tag = item.get("id")
                if item_id_tag is None:
                    continue
                item_id = str(item_id_tag)
                if not _is_valid(item_id, valid_items, ctx.extra_ids):
                    errors.append(
                        f"[ERROR] {rel}: {path} (entity {entity_id!r}) equipment slot"
                        f" {slot_desc} has unknown item id '{item_id}'"
                        f" (min target {min_version})"
                    )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity/entities checked -- all valid")

    if errors:
        return False, f"{len(errors)} equipment shape error(s)"
    return True, f"{files_checked} files, {entities_checked} entities checked"
