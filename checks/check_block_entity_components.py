"""A block entity's `components` key must match the era the file targets.

The key arrived at 1.20.5. Our per-version variants are produced by each era's
own game writer, so the rule is symmetric and both halves are hard errors, keyed
on the file's minimum covered version like every other boundary check here:

  - minimum below 1.20.5 -- no block entity may carry the key;
  - minimum at or above 1.20.5 -- every block entity must carry it.

Files written by older tooling do not satisfy the second half, and they are meant
to fail. The converter now guarantees both directions, so a failure here names a
project that still needs re-running -- producing that list is the point of the
check. Do not soften it, and do not add per-block exceptions for known converter
gaps: reconverted output will comply, and an exception would hide the files that
still need the pass.

`check_sign_nbt` used to enforce the first half for signs alone. It now owns only
the sign text format, which really is sign-specific.
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
        expects_components = file_min_dv >= DV_1_20_5

        files_checked += 1
        names = _palette_names(nbt)
        offenders: list[str] = []

        for block_entry in nbt.get("blocks") or []:
            block_nbt = block_entry.get("nbt")
            if not isinstance(block_nbt, nbtlib.Compound):
                continue
            block_entities_checked += 1
            if ("components" in block_nbt) != expects_components:
                offenders.append(_block_id(names, block_entry))

        if not offenders:
            continue

        if expects_components:
            detail = (f"without a `components` key (required from 1.20.5;"
                      f" min target {file_min_version})")
        else:
            detail = (f"with a `components` key (1.20.5+ format, incompatible with"
                      f" min target {file_min_version})")
        errors.append(
            f"[ERROR] {rel}: {len(offenders)} {_noun(len(offenders))} {detail}:"
            f" {_listed(offenders)}"
        )
        files_with_errors.add(nbt_path)

    for msg in errors:
        print(f"  {msg}")

    if errors:
        return False, (
            f"{len(files_with_errors)} of {files_checked} file(s) need reconversion"
        )

    print(f"  {files_checked} file(s), {block_entities_checked} block entities"
          f" checked -- all valid")
    return True, f"{files_checked} files, {block_entities_checked} block entities checked"
