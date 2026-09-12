"""Version-gated entity NBT keys only appear in files targeting the right range.

The table in ``data/entity_nbt_keys.json`` lists, per mob, keys with a minimum
and/or maximum DataVersion. A file's wired range must sit entirely inside a
key's window; a range entirely outside it, or spanning its edge, is an error.
Only ``minecraft:`` entities are covered.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext

_KEYS_FILE = Path(__file__).parent.parent / "data" / "entity_nbt_keys.json"
_table_cache: list[dict] = []


def _load_key_table() -> dict[str, dict[str, dict]]:
    if not _table_cache:
        with _KEYS_FILE.open(encoding="utf-8") as f:
            raw = json.load(f)
        _table_cache.append({k: v for k, v in raw.items() if not k.startswith("_")})
    return _table_cache[0]


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store = svc.structures
    if not store.dir.exists():
        return True, "no structures directory"

    key_table = _load_key_table()
    version_map = svc.versions

    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue
        file_min, file_max, file_min_dv, file_max_dv = fr.min_version, fr.max_version, fr.min_dv, fr.max_dv

        for entity, entity_path in structure.walk_entities():
            id_tag = entity.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            mob_rules = key_table.get(entity_id)
            if not mob_rules:
                continue
            entities_checked += 1

            for key, constraints in mob_rules.items():
                if key not in entity:
                    continue
                min_dv = constraints.get("min_dv")
                max_dv = constraints.get("max_dv")
                note = constraints.get("note", "")
                suffix = f" {note}" if note else ""

                if min_dv is not None and file_min_dv < min_dv:
                    if file_max_dv < min_dv:
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which requires DV >= {min_dv} but wired range"
                            f" {file_min}..{file_max} is entirely older.{suffix}"
                        )
                    else:
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which requires DV >= {min_dv} ({version_map.name_of(min_dv)})"
                            f" but wired range {file_min}..{file_max} spans that boundary.{suffix}"
                        )
                elif max_dv is not None and file_max_dv > max_dv:
                    if file_min_dv > max_dv:
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which is only valid through DV {max_dv} but wired range"
                            f" {file_min}..{file_max} is entirely newer.{suffix}"
                        )
                    else:
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which is only valid through DV {max_dv} ({version_map.name_of(max_dv)})"
                            f" but wired range {file_min}..{file_max} spans that boundary.{suffix}"
                        )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity/entities checked -- all valid")
        return True, f"{files_checked} files, {entities_checked} entities with key rules checked"
    return False, f"{len(errors)} nbt key error(s)"
