from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_min_versions, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext

_KEYS_FILE = Path(__file__).parent.parent / "registries" / "entity_nbt_keys.json"


def _load_key_table() -> dict[str, dict[str, dict]]:
    with _KEYS_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    key_table = _load_key_table()

    cache_dir = Path(__file__).parent.parent / "cache"
    version_map = load_version_map(cache_dir, ctx.refresh)

    global_min_version = min(ctx.mc_versions, key=_parse_version)

    nbt_min_versions: dict[Path, str] = {}
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if template_pool_dir.exists():
        nbt_min_versions = _build_nbt_min_versions(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version, ctx.mc_versions
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

        file_version = nbt_min_versions.get(nbt_path, global_min_version)
        file_dv = version_map.get(file_version)
        if file_dv is None:
            continue

        for entity_entry in nbt.get("entities") or []:
            entity_nbt = entity_entry.get("nbt")
            if not isinstance(entity_nbt, nbtlib.Compound):
                continue
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

                if min_dv is not None and file_dv < min_dv:
                    errors.append(
                        f"[ERROR] {rel}: entity {entity_id!r} has key {key!r} which requires"
                        f" DV >= {min_dv} but file targets {file_version} (DV {file_dv})."
                        + (f" {note}" if note else "")
                    )
                elif max_dv is not None and file_dv > max_dv:
                    errors.append(
                        f"[ERROR] {rel}: entity {entity_id!r} has key {key!r} which is only"
                        f" valid through DV {max_dv} but file targets {file_version} (DV {file_dv})."
                        + (f" {note}" if note else "")
                    )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity/entities checked — all valid")

    if errors:
        return False, f"{len(errors)} nbt key error(s)"
    return True, f"{files_checked} files, {entities_checked} entities with key rules checked"
