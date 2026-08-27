"""Where a block entity's `components` key may and may not appear.

The key arrived at 1.20.5, alongside the item-format change. It is never written
before that: across every pre-1.20.5 structure in the portfolio, not one block
entity carries one. So a file whose minimum target is below 1.20.5 must not have
it on any block entity -- that is a hard error, and it is the rule
`check_sign_nbt` used to enforce for signs alone.

The inverse is deliberately NOT enforced. Above 1.20.5 the key turns out to be a
per-file property, not a per-block-entity one. Surveying MSS + MVS + MTR, 223
files carry it on every block entity and 145 carry it on none, with the same
block entity types and the same DataVersion appearing on both sides -- whole-file
absence tracks how a file was written (saved in-game vs produced by the downgrade
pipeline), not an authoring mistake, and the game supplies an empty component map
when the key is absent. Failing on it would flag most of the portfolio.

What is worth reporting is a file that disagrees with itself. If some block
entities in a file carry the key and others don't, the ones missing it are the
odd ones out -- usually a container rewritten by tooling after the save. That is
a WARN: it prints, but it does not fail the check.
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
    warnings: list[str] = []
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
        # are typically saved on the newest release and downgraded per-version, so
        # the source DataVersion does not describe what the file actually contains.
        file_min_version = nbt_min_versions.get(nbt_path, global_min_version)
        file_min_dv = version_map.get(file_min_version)
        if file_min_dv is None:
            continue

        files_checked += 1
        names = _palette_names(nbt)
        with_key: list[str] = []
        without_key: list[str] = []

        for block_entry in nbt.get("blocks") or []:
            block_nbt = block_entry.get("nbt")
            if not isinstance(block_nbt, nbtlib.Compound):
                continue
            block_entities_checked += 1
            target = with_key if "components" in block_nbt else without_key
            target.append(_block_id(names, block_entry))

        if file_min_dv < DV_1_20_5:
            if with_key:
                errors.append(
                    f"[ERROR] {rel}: {len(with_key)} {_noun(len(with_key))} with a"
                    f" `components` key (1.20.5+ format, incompatible with min target"
                    f" {file_min_version}): {_listed(with_key)}"
                )
            continue

        # At or above 1.20.5, only a file that disagrees with itself is reportable.
        if with_key and without_key:
            verb = "has" if len(with_key) == 1 else "have"
            warnings.append(
                f"[WARN] {rel}: {len(without_key)} {_noun(len(without_key))} without a"
                f" `components` key while {len(with_key)} in the same file {verb} one:"
                f" {_listed(without_key)}"
            )

    for msg in errors:
        print(f"  {msg}")
    for msg in warnings:
        print(f"  {msg}")

    if not errors and not warnings:
        print(f"  {files_checked} file(s), {block_entities_checked} block entities"
              f" checked -- all consistent")

    if errors:
        return False, f"{len(errors)} error(s), {len(warnings)} warning(s)"
    return True, f"{files_checked} files, {block_entities_checked} block entities, {len(warnings)} warning(s)"
