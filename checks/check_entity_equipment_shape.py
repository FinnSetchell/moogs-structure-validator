from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.item_format import EQUIPMENT_DV
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_min_versions, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext

# Keys definitely absorbed into the `equipment` compound at 1.21.5 for all mobs
# that went through the unified equipment refactor.
# SaddleItem / ArmorItem (horse armor) / DecorItem are kept separate — their
# migration at 1.21.5 is uncertain per the plan, so we do not flag them here.
_LEGACY_KEYS = frozenset({"ArmorItems", "HandItems"})


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

        post_unification = file_dv >= EQUIPMENT_DV

        for entity_entry in nbt.get("entities") or []:
            entity_nbt = entity_entry.get("nbt")
            if not isinstance(entity_nbt, nbtlib.Compound):
                continue
            id_tag = entity_nbt.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)

            if not entity_id.startswith("minecraft:"):
                continue

            entities_checked += 1

            if post_unification:
                for key in _LEGACY_KEYS:
                    if key in entity_nbt:
                        errors.append(
                            f"[ERROR] {rel}: entity {entity_id!r} has `{key}` on a"
                            f" {file_version}+ target (DV {file_dv} >= {EQUIPMENT_DV});"
                            f" use `equipment` compound instead"
                        )
            else:
                if "equipment" in entity_nbt:
                    errors.append(
                        f"[ERROR] {rel}: entity {entity_id!r} has `equipment` compound on a"
                        f" {file_version} target (DV {file_dv} < {EQUIPMENT_DV});"
                        f" use `ArmorItems`/`HandItems` for pre-1.21.5"
                    )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity/entities checked — all valid")

    if errors:
        return False, f"{len(errors)} equipment shape error(s)"
    return True, f"{files_checked} files, {entities_checked} entities checked"
