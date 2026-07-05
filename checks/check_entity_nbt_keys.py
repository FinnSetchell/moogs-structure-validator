from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext

_KEYS_FILE = Path(__file__).parent.parent / "registries" / "entity_nbt_keys.json"


def _load_key_table() -> dict[str, dict[str, dict]]:
    with _KEYS_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _dv_name(version_map: dict[str, int], dv: int) -> str:
    return next((k for k, v in version_map.items() if v == dv), str(dv))


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")
    if not structures_dir.exists():
        return True, "no structures directory"

    key_table = _load_key_table()

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

    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        files_checked += 1
        rel = str(nbt_path.relative_to(structures_dir))

        info = nbt_ranges.get(nbt_path)
        file_min = info.min_version if info else global_min_version
        file_max = info.max_version if info else global_max_version
        file_min_dv = version_map.get(file_min)
        file_max_dv = version_map.get(file_max)
        if file_min_dv is None or file_max_dv is None:
            continue

        for entity_nbt, entity_path in iter_entities(nbt):
            id_tag = entity_nbt.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)

            mob_rules = key_table.get(entity_id)
            if not mob_rules:
                continue

            entities_checked += 1

            for key, constraints in mob_rules.items():
                if key not in entity_nbt:
                    continue
                min_dv = constraints.get("min_dv")
                max_dv = constraints.get("max_dv")
                note = constraints.get("note", "")

                # Key valid DV window is [min_dv or -inf, max_dv or +inf].
                # File range must fit entirely inside that window.
                if min_dv is not None and file_min_dv < min_dv:
                    if file_max_dv < min_dv:
                        # entire range too old
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which requires DV >= {min_dv} but wired range"
                            f" {file_min}..{file_max} is entirely older."
                            + (f" {note}" if note else "")
                        )
                    else:
                        # range spans the min boundary
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which requires DV >= {min_dv} ({_dv_name(version_map, min_dv)})"
                            f" but wired range {file_min}..{file_max} spans that boundary."
                            + (f" {note}" if note else "")
                        )
                elif max_dv is not None and file_max_dv > max_dv:
                    if file_min_dv > max_dv:
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which is only valid through DV {max_dv} but wired range"
                            f" {file_min}..{file_max} is entirely newer."
                            + (f" {note}" if note else "")
                        )
                    else:
                        errors.append(
                            f"[ERROR] {rel}: {entity_path} ({entity_id!r}) has key {key!r}"
                            f" which is only valid through DV {max_dv} ({_dv_name(version_map, max_dv)})"
                            f" but wired range {file_min}..{file_max} spans that boundary."
                            + (f" {note}" if note else "")
                        )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity/entities checked -- all valid")

    if errors:
        return False, f"{len(errors)} nbt key error(s)"
    return True, f"{files_checked} files, {entities_checked} entities with key rules checked"
