"""Book items carry their pages in the right shape for the file's target range.

Pre-1.20.5 a book's pages sit under ``tag``; from 1.20.5 under
``components.minecraft:<kind>_content``. A written book's pages are text
components, and text components changed encoding at 1.21.5 (JSON string ->
SNBT), so a JSON-string page in a written book is side-specific. A writable
book's pages are plain strings on every version (``Filterable<String>``, not
``Filterable<Component>``), so nothing about them changes at 1.21.5.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.context import services
from core.items import block_entity_items, entity_items
from core.mcversions import DV_1_20_5, DV_1_21_5, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

_BOOK_IDS = {"minecraft:writable_book", "minecraft:written_book"}


def _item_id(item: dict) -> str | None:
    tag = item.get("id")
    return None if tag is None else str(tag)


def _is_json_object_string(s: str) -> bool:
    """A page 'is' a JSON string component if it parses as a JSON object/array."""
    s = s.strip()
    if not s or s[0] not in "{[":
        return False
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, (dict, list))


def _unwrap_filterable(value):
    """Books allow ``{raw:..., filtered:...}`` wrappers at page/title level; use ``raw``."""
    if isinstance(value, dict):
        raw = value.get("raw")
        if raw is not None:
            return raw
    return value


def _check_book_item(item: dict, path: str, rel: str, min_version: str, max_version: str,
                     min_dv: int, max_dv: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    item_id = _item_id(item)
    if item_id not in _BOOK_IDS:
        return errors, warnings
    kind = item_id.rsplit(":", 1)[1]

    fmt_side = side_of(min_dv, max_dv, DV_1_20_5)
    has_tag = "tag" in item
    has_components = "components" in item

    if fmt_side == BoundarySide.NEW and has_tag:
        errors.append(
            f"[ERROR] {rel}: {path} ({item_id}) uses legacy `tag` on a min>=1.20.5 target"
            f" ({min_version}); books must live in `components.minecraft:{kind}_content`"
        )
    elif fmt_side == BoundarySide.OLD and has_components:
        errors.append(
            f"[ERROR] {rel}: {path} ({item_id}) uses `components` on a max<1.20.5 target"
            f" ({max_version}); books use `tag` before 1.20.5"
        )

    pages = None
    pages_path = ""
    if fmt_side != BoundarySide.OLD and has_components:
        comps = item.get("components")
        if isinstance(comps, dict):
            comp_key = f"minecraft:{kind}_content"
            content = comps.get(comp_key)
            if isinstance(content, dict):
                pages = content.get("pages")
                pages_path = f"{path}.components.{comp_key}.pages"
    if pages is None and has_tag:
        tag = item.get("tag")
        if isinstance(tag, dict):
            pages = tag.get("pages")
            pages_path = f"{path}.tag.pages"

    if isinstance(pages, list):
        if len(pages) == 0:
            warnings.append(f"[WARN] {rel}: {pages_path or path}: empty `pages`")
        elif item_id == "minecraft:written_book":
            page_side = side_of(min_dv, max_dv, DV_1_21_5)
            for i, page in enumerate(pages):
                unwrapped = _unwrap_filterable(page)
                if not isinstance(unwrapped, str) or not _is_json_object_string(unwrapped):
                    # Plain text is a valid page on both sides of 1.21.5.
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
    svc = services(ctx)
    store = svc.structures
    if not store.dir.exists():
        return True, "no structures directory"
    if not svc.versions:
        return True, "skipped (no version map)"

    errors: list[str] = []
    warnings: list[str] = []
    files_checked = 0
    books_checked = 0

    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue

        def check(slot: str, item: dict) -> None:
            nonlocal books_checked
            if _item_id(item) in _BOOK_IDS:
                books_checked += 1
                e, w = _check_book_item(item, slot, rel, fr.min_version, fr.max_version, fr.min_dv, fr.max_dv)
                errors.extend(e)
                warnings.extend(w)

        for entity, entity_path in structure.walk_entities():
            for slot, item in entity_items(entity, entity_path):
                check(slot, item)
        for slot, item in block_entity_items(structure.block_entities):
            check(slot, item)

    for msg in warnings:
        print(f"  {msg}")
    for msg in errors:
        print(f"  {msg}")

    if not errors and not warnings:
        print(f"  {files_checked} file(s), {books_checked} book(s) checked -- all valid")

    if errors:
        return False, f"{len(errors)} book error(s), {len(warnings)} warning(s)"
    return True, f"{books_checked} books checked, {len(warnings)} warning(s)"
