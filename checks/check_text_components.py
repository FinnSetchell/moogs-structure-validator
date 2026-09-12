"""Text components use the right encoding for the file's target range.

Before 1.21.5 a text component in NBT is a JSON string; from 1.21.5 it is
inline SNBT (a bare string or a compound), and a JSON string renders literally.
Checked on entity ``CustomName``, ``text_display.text``, sign messages, and item
``custom_name``/``item_name``/``lore`` on entities and in containers. Bare
non-JSON strings are never flagged: they are valid on 1.21.5+ and ambiguous
before it.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.context import services
from core.items import block_entity_items, entity_items
from core.mcversions import DV_1_21_5, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

ITEM_TEXT_COMPONENT_KEYS = ("minecraft:custom_name", "minecraft:item_name")
ITEM_LORE_COMPONENT = "minecraft:lore"


def _is_json_obj_or_array(s: str) -> bool:
    s = s.strip()
    if not s or s[0] not in "{[":
        return False
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, (dict, list))


def _flag_value(value, path: str, rel: str, side: str, min_version: str, max_version: str) -> list[str]:
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
    elif isinstance(value, (dict, list)):
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


def _check_item(item: dict, path: str, rel: str, side: str, min_v: str, max_v: str) -> list[str]:
    errors: list[str] = []
    comps = item.get("components")
    if isinstance(comps, dict):
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


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store = svc.structures
    if not store.dir.exists():
        return True, "no structures directory"
    if not svc.versions:
        return True, "skipped (no version map)"

    errors: list[str] = []
    files_checked = 0

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue
        side = side_of(fr.min_dv, fr.max_dv, DV_1_21_5)
        file_min, file_max = fr.min_version, fr.max_version

        for entity, entity_path in structure.walk_entities():
            custom_name = entity.get("CustomName")
            if custom_name is not None:
                errors.extend(_flag_value(custom_name, f"{entity_path}.CustomName", rel, side, file_min, file_max))
            if str(entity.get("id", "")) == "minecraft:text_display":
                text = entity.get("text")
                if text is not None:
                    errors.extend(_flag_value(text, f"{entity_path}.text", rel, side, file_min, file_max))
            for slot, item in entity_items(entity, entity_path):
                errors.extend(_check_item(item, slot, rel, side, file_min, file_max))

        for be in structure.block_entities:
            base = f"blocks[{be.index}].nbt"
            for face in ("front_text", "back_text"):
                face_c = be.nbt.get(face)
                if not isinstance(face_c, dict):
                    continue
                messages = face_c.get("messages")
                if isinstance(messages, list):
                    for j, msg in enumerate(messages):
                        errors.extend(_flag_value(
                            msg, f"{base}.{face}.messages[{j}]", rel, side, file_min, file_max
                        ))

        for slot, item in block_entity_items(structure.block_entities):
            errors.extend(_check_item(item, slot, rel, side, file_min, file_max))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s) checked -- all text components valid")
        return True, f"{files_checked} files checked"
    return False, f"{len(errors)} text component error(s)"
