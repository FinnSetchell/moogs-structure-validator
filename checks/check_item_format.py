from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.item_format import check_item_era, iter_entity_items
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_min_versions, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

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
    items_checked = 0
    files_checked = 0

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
            entity_id = str(entity_nbt.get("id", "?"))

            for slot_desc, item in iter_entity_items(entity_nbt, file_dv):
                items_checked += 1
                msg = check_item_era(item, file_dv, slot_desc, entity_id, rel, file_version)
                if msg:
                    errors.append(msg)

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {items_checked} item slot(s) checked — all valid")

    if errors:
        return False, f"{len(errors)} item era error(s)"
    return True, f"{files_checked} files, {items_checked} item slots checked"
