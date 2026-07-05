"""Validates MSL's msl_pieces_spawn_counts and msl_pieces_spawn_counts_additions
datapack files: per-piece spawn count caps keyed by structure id.

Format (from MSL's StructurePieceCountsManager):
  data/<ns>/msl_pieces_spawn_counts/<structure_path>.json
  {
    "pieces_spawn_counts": [
      {
        "nbt_piece_name": "<ns>:<template path>",
        "always_spawn_this_many": 2,
        "never_spawn_more_than_this_many": 5,
        "minimum_distance_from_center_piece": 0,
        "condition": "<mod config condition>"
      }
    ]
  }
The file id is the structure the counts apply to. Additions files merge in
extra entries and use the same shape. MSL errors at load when
always_spawn_this_many exceeds never_spawn_more_than_this_many.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from utils.paths import all_data_dirs

if TYPE_CHECKING:
    from validator import ValidatorContext

_DIRS = ("msl_pieces_spawn_counts", "msl_pieces_spawn_counts_additions")

_INT_FIELDS = (
    "always_spawn_this_many",
    "never_spawn_more_than_this_many",
    "minimum_distance_from_center_piece",
)

_KNOWN_FIELDS = set(_INT_FIELDS) | {"nbt_piece_name", "condition"}


def _check_entry(ctx: ValidatorContext, where: str, entry: object,
                 namespace_root: Path, bad: list[str]) -> None:
    if not isinstance(entry, dict):
        bad.append(f"{where}: entry is not an object")
        return

    piece = entry.get("nbt_piece_name")
    if not isinstance(piece, str) or not piece:
        bad.append(f"{where}: missing nbt_piece_name")
    else:
        namespace, _, path = (piece if ":" in piece else f"minecraft:{piece}").partition(":")
        if namespace == ctx.namespace:
            structure_dirs = all_data_dirs(namespace_root, "structure")
            if not any((d / f"{path}.nbt").exists() for d in structure_dirs):
                bad.append(f"{where}: nbt_piece_name {piece!r} has no template NBT in this project")

    for key in _INT_FIELDS:
        value = entry.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            bad.append(f"{where}: {key} must be a non-negative integer, got {value!r}")

    condition = entry.get("condition")
    if condition is not None and not isinstance(condition, str):
        bad.append(f"{where}: condition must be a string, got {condition!r}")

    always = entry.get("always_spawn_this_many")
    never = entry.get("never_spawn_more_than_this_many")
    if isinstance(always, int) and isinstance(never, int) and always > never:
        bad.append(
            f"{where}: always_spawn_this_many {always} greater than "
            f"never_spawn_more_than_this_many {never}"
        )

    unknown = sorted(set(entry) - _KNOWN_FIELDS)
    if unknown:
        bad.append(f"{where}: unknown field(s) {', '.join(unknown)}")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace

    bad: list[str] = []
    file_count = 0

    for dir_name in _DIRS:
        counts_dir = namespace_root / dir_name
        if not counts_dir.exists():
            continue

        for json_path in sorted(counts_dir.rglob("*.json")):
            rel = json_path.relative_to(counts_dir)
            file_count += 1

            try:
                with json_path.open(encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception as e:
                bad.append(f"{dir_name}/{rel}: invalid JSON: {e}")
                continue

            entries = data.get("pieces_spawn_counts") if isinstance(data, dict) else None
            if not isinstance(entries, list):
                bad.append(f"{dir_name}/{rel}: missing pieces_spawn_counts list")
                continue

            # the file id names the structure these counts apply to
            structure_path = rel.with_suffix("").as_posix()
            structure_file = namespace_root / "worldgen" / "structure" / f"{structure_path}.json"
            if not structure_file.exists():
                bad.append(
                    f"{dir_name}/{rel}: no structure "
                    f"{ctx.namespace}:{structure_path} in this project"
                )

            for i, entry in enumerate(entries):
                _check_entry(ctx, f"{dir_name}/{rel} [{i}]", entry, namespace_root, bad)

    if file_count == 0:
        return True, "no spawn count files"

    for msg in bad:
        print(f"  [WARN] spawn counts: {msg}")
    if not bad:
        print(f"  {file_count} spawn count file(s), all valid")

    summary = (
        f"{file_count} file(s), {len(bad)} problem(s)"
        if bad
        else f"{file_count} file(s), all valid"
    )
    return not bad, summary
