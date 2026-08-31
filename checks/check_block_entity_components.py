"""A block entity must not carry a `components` key before 1.20.5.

The key arrived at 1.20.5, so a file whose minimum covered version is below that
cannot carry one on any block entity. `check_sign_nbt` used to enforce this for
signs alone; it holds for every block entity, which is what this check walks.

The inverse -- "at 1.20.5+ every block entity must carry the key" -- is
deliberately NOT checked, because vanilla does not work that way. Across the 1108
shipped structure files that contain block entities, 4832 of 4848 block entities
carry no `components` key at all, both at DataVersion 4325 (1.21.5) and at 4556
(1.21.10): 99.7% omit it. The only carriers are the eight in each of
`pillager_outpost/watchtower.nbt` and `watchtower_overgrown.nbt`, and those same
two files also hold block entities without it -- so vanilla mixes both shapes
inside one file. Absence is the ordinary shape and the game loads it fine, so
requiring the key would flag correct data. Not even a warning: at that frequency
a warning is noise.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.boundaries import DV_1_20_5
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_min_versions, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


_MAX_LISTED_IDS = 6


def _palette_names(nbt: nbtlib.Compound) -> list[str]:
    """Block ids by palette index. Handles the multi-variant `palettes` form."""
    palette = nbt.get("palette")
    if palette is None:
        palettes = nbt.get("palettes")
        if isinstance(palettes, list) and palettes:
            palette = palettes[0]
    if palette is None:
        return []
    return [str(state.get("Name", "?")) for state in palette]


def _block_id(names: list[str], block_entry: nbtlib.Compound) -> str:
    state = block_entry.get("state")
    if state is None:
        return "?"
    index = int(state)
    return names[index] if 0 <= index < len(names) else "?"


def _listed(block_ids: list[str]) -> str:
    unique = sorted(set(block_ids))
    shown = ", ".join(unique[:_MAX_LISTED_IDS])
    if len(unique) > _MAX_LISTED_IDS:
        shown += f", (+ {len(unique) - _MAX_LISTED_IDS} more)"
    return shown


def _noun(count: int) -> str:
    return "block entity" if count == 1 else "block entities"


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
    nbt_min_versions: dict[Path, str] = {}
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if template_pool_dir.exists():
        nbt_min_versions = _build_nbt_min_versions(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version, ctx.mc_versions
        )

    errors: list[str] = []
    files_with_errors: set[Path] = set()
    files_checked = 0
    block_entities_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        rel = str(nbt_path.relative_to(structures_dir))

        # Gate on the mod's wired target range, not nbt["DataVersion"]. Structures
        # are typically saved on the newest release and converted per-version, so
        # the source DataVersion does not describe what the file actually contains.
        file_min_version = nbt_min_versions.get(nbt_path, global_min_version)
        file_min_dv = version_map.get(file_min_version)
        if file_min_dv is None:
            continue
        predates_components = file_min_dv < DV_1_20_5

        files_checked += 1
        names = _palette_names(nbt)
        offenders: list[str] = []

        for block_entry in nbt.get("blocks") or []:
            block_nbt = block_entry.get("nbt")
            if not isinstance(block_nbt, nbtlib.Compound):
                continue
            block_entities_checked += 1
            if predates_components and "components" in block_nbt:
                offenders.append(_block_id(names, block_entry))

        if not offenders:
            continue

        errors.append(
            f"[ERROR] {rel}: {len(offenders)} {_noun(len(offenders))} with a"
            f" `components` key (1.20.5+ format, incompatible with min target"
            f" {file_min_version}): {_listed(offenders)}"
        )
        files_with_errors.add(nbt_path)

    for msg in errors:
        print(f"  {msg}")

    if errors:
        return False, (
            f"{len(files_with_errors)} of {files_checked} file(s) carry a"
            f" pre-1.20.5 `components` key"
        )

    print(f"  {files_checked} file(s), {block_entities_checked} block entities"
          f" checked -- all valid")
    return True, f"{files_checked} files, {block_entities_checked} block entities checked"
