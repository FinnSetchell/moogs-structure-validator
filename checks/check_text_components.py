from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import nbtlib

from utils.boundaries import DV_1_21_5, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


ITEM_TEXT_COMPONENT_KEYS = ("minecraft:custom_name", "minecraft:item_name")
ITEM_LORE_COMPONENT = "minecraft:lore"


def _is_json_obj_or_array(s: str) -> bool:
    s = s.strip()
    if not s or s[0] not in "{[":
        return False
    try:
        parsed = _json.loads(s)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, (dict, list))


def _flag_value(
    value, path: str, rel: str,
    side: str, min_version: str, max_version: str,
) -> list[str]:
    """Flag a single text-component value if it's on the wrong side of 1.21.5.
    Bare non-JSON strings never flagged (they're valid on 1.21.5+ and ambiguous before)."""
    errors: list[str] = []
    if isinstance(value, str):
        if _is_json_obj_or_array(value):
            if side == BoundarySide.NEW:
                errors.append(
                    f"[ERROR] {rel}: {path}: JSON-string text component on a min>=1.21.5 target"
                    f" ({min_version}); at 1.21.5+ text is inline SNBT/bare string,"
                    f" JSON strings render literally"
                )
            elif side == BoundarySide.SPANS:
                errors.append(
                    f"[ERROR] {rel}: {path}: JSON-string text component but wired range"
                    f" {min_version}..{max_version} spans 1.21.5; incompatible on both sides"
                )
    elif isinstance(value, nbtlib.Compound) or isinstance(value, list):
        if side == BoundarySide.OLD:
            errors.append(
                f"[ERROR] {rel}: {path}: SNBT-compound text component on a max<1.21.5 target"
                f" ({max_version}); pre-1.21.5 expects JSON-string text components"
            )
        elif side == BoundarySide.SPANS:
            errors.append(
                f"[ERROR] {rel}: {path}: SNBT-compound text component but wired range"
                f" {min_version}..{max_version} spans 1.21.5; incompatible on both sides"
            )
    return errors


def _check_item(item: nbtlib.Compound, path: str, rel: str, side: str, min_v: str, max_v: str) -> list[str]:
    errors: list[str] = []
    comps = item.get("components")
    if isinstance(comps, nbtlib.Compound):
        for key in ITEM_TEXT_COMPONENT_KEYS:
            val = comps.get(key)
            if val is not None:
                errors.extend(_flag_value(val, f"{path}.components.{key}", rel, side, min_v, max_v))
        lore = comps.get(ITEM_LORE_COMPONENT)
        if isinstance(lore, list):
            for i, line in enumerate(lore):
                errors.extend(_flag_value(
                    line, f"{path}.components.{ITEM_LORE_COMPONENT}[{i}]", rel, side, min_v, max_v
                ))
    return errors


def _iter_items_in_entity(entity_nbt: nbtlib.Compound, entity_path: str) -> Iterator[tuple[str, nbtlib.Compound]]:
    for list_field in ("HandItems", "ArmorItems"):
        items = entity_nbt.get(list_field)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{entity_path}.{list_field}[{i}]", item
    for field in ("body_armor_item", "SaddleItem", "Item"):
        item = entity_nbt.get(field)
        if isinstance(item, nbtlib.Compound):
            yield f"{entity_path}.{field}", item
    equip = entity_nbt.get("equipment")
    if isinstance(equip, nbtlib.Compound):
        for slot, item in equip.items():
            if isinstance(item, nbtlib.Compound):
                yield f"{entity_path}.equipment.{slot}", item


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
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    nbt_ranges = {}
    if template_pool_dir.exists():
        nbt_ranges = _build_nbt_version_ranges(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version,
            ctx.mc_versions, global_max_version,
        )

    errors: list[str] = []
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

        side = side_of(min_dv, max_dv, DV_1_21_5)

        # Entities: CustomName, text_display `text`, plus items on the entity.
        for entity_nbt, entity_path in iter_entities(nbt):
            custom_name = entity_nbt.get("CustomName")
            if custom_name is not None:
                errors.extend(_flag_value(custom_name, f"{entity_path}.CustomName", rel, side, file_min, file_max))
            entity_id = str(entity_nbt.get("id", ""))
            if entity_id == "minecraft:text_display":
                text = entity_nbt.get("text")
                if text is not None:
                    errors.extend(_flag_value(text, f"{entity_path}.text", rel, side, file_min, file_max))
            for slot, item in _iter_items_in_entity(entity_nbt, entity_path):
                errors.extend(_check_item(item, slot, rel, side, file_min, file_max))

        # Block entities: signs, item stacks in containers/lecterns/pots.
        for i, block_entry in enumerate(nbt.get("blocks") or []):
            block_nbt = block_entry.get("nbt")
            if not isinstance(block_nbt, nbtlib.Compound):
                continue
            base = f"blocks[{i}].nbt"
            for face in ("front_text", "back_text"):
                face_c = block_nbt.get(face)
                if not isinstance(face_c, nbtlib.Compound):
                    continue
                messages = face_c.get("messages")
                if isinstance(messages, list):
                    for j, msg in enumerate(messages):
                        errors.extend(_flag_value(
                            msg, f"{base}.{face}.messages[{j}]", rel, side, file_min, file_max
                        ))

        for slot, item in _iter_items_in_blocks(nbt):
            errors.extend(_check_item(item, slot, rel, side, file_min, file_max))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s) checked -- all text components valid")

    if errors:
        return False, f"{len(errors)} text component error(s)"
    return True, f"{files_checked} files checked"
