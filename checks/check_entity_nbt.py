from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from registries.fetcher import _fetch_version
from utils.nbt_versions import _build_nbt_min_versions, _parse_version
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


_VERSIONS_URL = "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json"
_NEW_FORMAT_BOUNDARY_DV = 3837  # 1.20.5


def _load_version_map(cache_dir: Path, refresh: bool) -> dict[str, int]:
    cache_file = cache_dir / "versions.json"
    if cache_file.exists() and not refresh:
        with cache_file.open() as f:
            entries = json.load(f)
    else:
        try:
            with urllib.request.urlopen(_VERSIONS_URL) as resp:
                entries = json.loads(resp.read().decode())
            with cache_file.open("w") as f:
                json.dump(entries, f)
        except Exception as e:
            print(f"  [WARN] could not fetch versions.json: {e}")
            return {}

    return {e["id"]: e["data_version"] for e in entries if e.get("stable")}


def _is_valid(id_: str, valid_set: set[str], extra_ids: set[str]) -> bool:
    if id_ in valid_set:
        return True
    if id_ in extra_ids:
        return True
    ns = id_.split(":", 1)[0]
    if f"{ns}:*" in extra_ids:
        return True
    return False


def _check_item_format(item: nbtlib.Compound, slot_desc: str, entity_id: str, rel: str, expect_old: bool, min_version_name: str) -> str | None:
    if "id" not in item:
        return None
    has_old = "Count" in item
    has_new = "count" in item
    if expect_old and has_new:
        return (
            f"[ERROR] {rel}: entity {entity_id} has new-format item in {slot_desc}"
            f" (min target version is {min_version_name}, pre-1.20.5 clients will misread it)"
        )
    if not expect_old and has_old:
        return (
            f"[ERROR] {rel}: entity {entity_id} has old-format item in {slot_desc}"
            f" (min target version is {min_version_name}, expected new item format)"
        )
    return None


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"

    version_map = _load_version_map(cache_dir, ctx.refresh)

    max_allowed_dv: int | None = None
    max_version_name: str | None = None
    min_allowed_dv: int | None = None
    min_version_name: str | None = None

    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is None:
                print(f"  [WARN] version '{v}' not found in versions.json — skipping DataVersion check for it")
                continue
            if max_allowed_dv is None or dv > max_allowed_dv:
                max_allowed_dv = dv
                max_version_name = v
            if min_allowed_dv is None or dv < min_allowed_dv:
                min_allowed_dv = dv
                min_version_name = v

    if min_allowed_dv is None:
        item_check_mode: str | None = None
    elif min_allowed_dv < _NEW_FORMAT_BOUNDARY_DV:
        item_check_mode = "old"
    else:
        item_check_mode = "new"

    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    global_min_version = min(ctx.mc_versions, key=_parse_version)
    nbt_min_versions: dict[Path, str] = {}
    if template_pool_dir.exists():
        nbt_min_versions = _build_nbt_min_versions(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version
        )
    non_minecraft_valid_entities = {e for e in ctx.valid_entities if not e.startswith("minecraft:")}
    version_entity_cache: dict[str, set[str]] = {}

    warnings: list[str] = []
    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        try:
            nbt = nbtlib.load(str(nbt_path))
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        files_checked += 1
        rel = nbt_path.name

        file_version = nbt_min_versions.get(nbt_path, global_min_version)

        if file_version not in version_entity_cache:
            vdata = _fetch_version(file_version, cache_dir, ctx.refresh)
            version_entity_cache[file_version] = (
                {"minecraft:" + n for n in vdata.get("entity_type", [])}
                | non_minecraft_valid_entities
            )
        valid_entities_for_file = version_entity_cache[file_version]

        file_dv = version_map.get(file_version)
        if file_dv is not None:
            file_item_mode = "old" if file_dv < _NEW_FORMAT_BOUNDARY_DV else "new"
        else:
            file_item_mode = item_check_mode  # fallback to global if version not in map

        if max_allowed_dv is not None:
            dv_tag = nbt.get("DataVersion")
            if dv_tag is not None:
                dv = int(dv_tag)
                if dv > max_allowed_dv:
                    dv_version_name = next(
                        (k for k, v in version_map.items() if v == dv), str(dv)
                    )
                    warnings.append(
                        f"[WARN] {rel}: DataVersion {dv} ({dv_version_name}) exceeds max allowed"
                        f" {max_allowed_dv} ({max_version_name}) — structure was saved in a newer game version"
                    )

        for entity_entry in nbt.get("entities") or []:
            entity_nbt = entity_entry.get("nbt")
            if entity_nbt is None:
                continue
            id_tag = entity_nbt.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            entities_checked += 1

            if not _is_valid(entity_id, valid_entities_for_file, ctx.extra_ids):
                errors.append(f"[ERROR] {rel}: unknown entity ID '{entity_id}'")

            if file_item_mode is not None:
                expect_old = file_item_mode == "old"
                for list_field in ("HandItems", "ArmorItems"):
                    items_tag = entity_nbt.get(list_field)
                    if items_tag is None:
                        continue
                    for slot, item in enumerate(items_tag):
                        if not isinstance(item, nbtlib.Compound):
                            continue
                        msg = _check_item_format(item, f"{list_field} slot {slot}", entity_id, rel, expect_old, min_version_name)
                        if msg:
                            errors.append(msg)
                body_item = entity_nbt.get("body_armor_item")
                if isinstance(body_item, nbtlib.Compound):
                    msg = _check_item_format(body_item, "body_armor_item", entity_id, rel, expect_old, min_version_name)
                    if msg:
                        errors.append(msg)

    for msg in warnings:
        print(f"  {msg}")
    for msg in errors:
        print(f"  {msg}")

    if not warnings and not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity ID(s) checked — all valid")

    if errors:
        w = len(warnings)
        e = len(errors)
        return False, f"{w} warning(s), {e} error(s)"
    if warnings:
        return True, f"{len(warnings)} warning(s), 0 errors"
    return True, f"{files_checked} files, {entities_checked} entities checked"
