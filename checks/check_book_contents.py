from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import nbtlib

from utils.boundaries import DV_1_20_5, DV_1_21_5, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


_BOOK_IDS = {"minecraft:writable_book", "minecraft:written_book"}


def _item_id(item: nbtlib.Compound) -> str | None:
    tag = item.get("id")
    if tag is None:
        return None
    return str(tag)


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
        book = block_nbt.get("Book")
        if isinstance(book, nbtlib.Compound):
            yield f"{base}.Book", book
        pot_item = block_nbt.get("item")
        if isinstance(pot_item, nbtlib.Compound):
            yield f"{base}.item", pot_item


def _is_json_object_string(s: str) -> bool:
    """A page 'is' a JSON string component if it parses as a JSON object/array."""
    s = s.strip()
    if not s or s[0] not in "{[":
        return False
    try:
        parsed = _json.loads(s)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, (dict, list))


def _unwrap_filterable(value):
    """Books allow {raw:..., filtered:...} wrappers at page/title level; use `raw`."""
    if isinstance(value, nbtlib.Compound):
        raw = value.get("raw")
        if raw is not None:
            return raw
    return value


def _check_book_item(
    item: nbtlib.Compound, path: str, rel: str,
    min_version: str, max_version: str, min_dv: int, max_dv: int,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for this book stack."""
    errors: list[str] = []
    warnings: list[str] = []

    item_id = _item_id(item)
    if item_id not in _BOOK_IDS:
        return errors, warnings

    fmt_side = side_of(min_dv, max_dv, DV_1_20_5)
    has_tag = "tag" in item
    has_components = "components" in item

    if fmt_side == BoundarySide.NEW and has_tag:
        errors.append(
            f"[ERROR] {rel}: {path} ({item_id}) uses legacy `tag` on a min>=1.20.5 target"
            f" ({min_version}); books must live in `components.minecraft:{item_id.rsplit(':',1)[1]}_content`"
        )
    elif fmt_side == BoundarySide.OLD and has_components:
        errors.append(
            f"[ERROR] {rel}: {path} ({item_id}) uses `components` on a max<1.20.5 target"
            f" ({max_version}); books use `tag` before 1.20.5"
        )

    # Extract pages depending on shape.
    pages = None
    pages_path = ""
    if fmt_side != BoundarySide.OLD and has_components:
        comps = item.get("components")
        if isinstance(comps, nbtlib.Compound):
            comp_key = f"minecraft:{item_id.rsplit(':',1)[1]}_content"
            content = comps.get(comp_key)
            if isinstance(content, nbtlib.Compound):
                pages = content.get("pages")
                pages_path = f"{path}.components.{comp_key}.pages"
    if pages is None and has_tag:
        tag = item.get("tag")
        if isinstance(tag, nbtlib.Compound):
            pages = tag.get("pages")
            pages_path = f"{path}.tag.pages"

    if isinstance(pages, list):
        if len(pages) == 0:
            warnings.append(f"[WARN] {rel}: {pages_path or path}: empty `pages`")
        elif item_id == "minecraft:written_book":
            # Written book pages only. The 1.21.5 boundary is about how a *text component*
            # serialises, and only `written_book_content` pages are text components. A
            # `writable_book_content` page is a plain string on every version (the game
            # models it as Filterable<String>, not Filterable<Component>), so nothing about
            # it changes at 1.21.5 and there is nothing here to get wrong.
            page_side = side_of(min_dv, max_dv, DV_1_21_5)
            for i, page in enumerate(pages):
                unwrapped = _unwrap_filterable(page)
                if not isinstance(unwrapped, str):
                    continue
                if not _is_json_object_string(unwrapped):
                    # Plain text is a valid page on both sides of 1.21.5: before it, an
                    # unquoted string is legacy-parsed as literal text; after it, a bare
                    # string is exactly what SNBT wants. Only a JSON-object string is
                    # side-specific.
                    continue
                if page_side == BoundarySide.NEW:
                    errors.append(
                        f"[ERROR] {rel}: {pages_path}[{i}]: JSON-string page on a min>=1.21.5"
                        f" target ({min_version}); at 1.21.5+ pages are SNBT compounds or bare"
                        f" strings, so this renders literally in game"
                    )
                elif page_side == BoundarySide.SPANS:
                    errors.append(
                        f"[ERROR] {rel}: {pages_path}[{i}]: JSON-string page but wired range"
                        f" {min_version}..{max_version} spans 1.21.5; JSON-string and SNBT"
                        f" pages are incompatible, no single value works on both sides"
                    )

    return errors, warnings


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
    warnings: list[str] = []
    files_checked = 0
    books_checked = 0

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

        # Entities (and their nested passengers / spawner data) + block-entity items.
        for entity_nbt, entity_path in iter_entities(nbt):
            for slot, item in _iter_items_in_entity(entity_nbt, entity_path):
                if _item_id(item) in _BOOK_IDS:
                    books_checked += 1
                    e, w = _check_book_item(item, slot, rel, file_min, file_max, min_dv, max_dv)
                    errors.extend(e); warnings.extend(w)

        for slot, item in _iter_items_in_blocks(nbt):
            if _item_id(item) in _BOOK_IDS:
                books_checked += 1
                e, w = _check_book_item(item, slot, rel, file_min, file_max, min_dv, max_dv)
                errors.extend(e); warnings.extend(w)

    for msg in warnings:
        print(f"  {msg}")
    for msg in errors:
        print(f"  {msg}")

    if not errors and not warnings:
        print(f"  {files_checked} file(s), {books_checked} book(s) checked -- all valid")

    if errors:
        return False, f"{len(errors)} book error(s), {len(warnings)} warning(s)"
    return True, f"{books_checked} books checked, {len(warnings)} warning(s)"
