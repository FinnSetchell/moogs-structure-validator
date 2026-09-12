"""A block entity must not carry a ``components`` key before 1.20.5.

The key arrived at 1.20.5, so a file whose minimum covered version is below that
cannot carry one on any block entity.

The inverse -- "at 1.20.5+ every block entity must carry the key" -- is
deliberately NOT checked, because vanilla does not work that way. Across the
1108 shipped structure files that contain block entities, 4832 of 4848 block
entities carry no ``components`` key at all, both at DataVersion 4325 (1.21.5)
and at 4556 (1.21.10). The only carriers are the eight in each of
``pillager_outpost/watchtower.nbt`` and ``watchtower_overgrown.nbt``, and those
same two files also hold block entities without it. Absence is the ordinary
shape and the game loads it fine; requiring the key would flag correct data.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.context import services
from core.mcversions import DV_1_20_5

if TYPE_CHECKING:
    from core.context import ValidatorContext

_MAX_LISTED_IDS = 6


def _listed(block_ids: list[str]) -> str:
    unique = sorted(set(block_ids))
    shown = ", ".join(unique[:_MAX_LISTED_IDS])
    if len(unique) > _MAX_LISTED_IDS:
        shown += f", (+ {len(unique) - _MAX_LISTED_IDS} more)"
    return shown


def _noun(count: int) -> str:
    return "block entity" if count == 1 else "block entities"


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store = svc.structures
    if not store.dir.exists():
        return True, "no structures directory"

    version_map = svc.versions
    if not version_map:
        return True, "skipped (no version map)"

    errors: list[str] = []
    files_with_errors: set[Path] = set()
    files_checked = 0
    block_entities_checked = 0

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        rel = store.rel(nbt_path)
        file_min_version = svc.file_min_version(nbt_path)
        file_min_dv = version_map.get(file_min_version)
        if file_min_dv is None:
            continue
        predates_components = file_min_dv < DV_1_20_5

        files_checked += 1
        names = structure.palette_names()
        offenders: list[str] = []
        for be in structure.block_entities:
            block_entities_checked += 1
            if predates_components and "components" in be.nbt:
                offenders.append(names[be.state] if 0 <= be.state < len(names) else "?")

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
