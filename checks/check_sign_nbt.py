"""Signs in files targeting pre-1.20.5 use the old text format.

Before 1.20.5 a sign's ``front_text``/``back_text`` messages are JSON-encoded
text components; from 1.20.5 they are bare strings. A bare string in a file
floored below 1.20.5 is an error. Skipped entirely when every targeted version
is 1.20.5 or later. (The block-entity ``components`` key is not sign-specific;
``check_block_entity_components`` owns that rule.)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext

_SIGN_FORMAT_DV = 3836  # 1.20.5 -- new sign format (bare strings, components key)


def _is_bare(msg_str: str) -> bool:
    """Pre-1.20.5 messages are JSON (``"plain"``, ``{"text":..}``, ``[..]``);
    anything that does not parse as JSON is the bare 1.20.5+ form."""
    if msg_str == "":
        return True
    try:
        json.loads(msg_str)
    except (ValueError, TypeError):
        return True
    return False


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store = svc.structures
    if not store.dir.exists():
        return True, "no structures directory"

    version_map = svc.versions
    any_below_boundary = any(
        (dv := version_map.get(v)) is not None and dv < _SIGN_FORMAT_DV for v in ctx.mc_versions
    ) if version_map else False
    if not any_below_boundary:
        return True, "skipped (all targeted versions >= 1.20.5)"

    errors: list[str] = []
    files_with_errors: set[Path] = set()
    bad_sign_count = 0

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        rel = store.rel(nbt_path)
        # Gate on the wired target range, not the stored DataVersion: files are
        # saved on the newest release and converted per version.
        file_min_version = svc.file_min_version(nbt_path)
        file_min_dv = version_map.get(file_min_version)
        if file_min_dv is not None and file_min_dv >= _SIGN_FORMAT_DV:
            continue

        names = structure.palette_names()
        sign_indices = {i for i, name in enumerate(names) if "sign" in name}
        if not sign_indices:
            continue

        for _, _, _, block_nbt in structure.blocks_in_states(sign_indices):
            if block_nbt is None:
                continue
            sign_bad = False
            for face in ("front_text", "back_text"):
                face_compound = block_nbt.get(face)
                if not isinstance(face_compound, dict):
                    continue
                messages = face_compound.get("messages")
                if not isinstance(messages, list):
                    continue
                for msg in messages:
                    if _is_bare(str(msg)):
                        errors.append(
                            f"[ERROR] {rel}: sign {face} has bare string message"
                            f" (new sign format, incompatible with min target {file_min_version})"
                        )
                        sign_bad = True
            if sign_bad:
                bad_sign_count += 1
                files_with_errors.add(nbt_path)

    for msg in errors:
        print(f"  {msg}")

    if errors:
        return False, f"{bad_sign_count} sign(s) with incompatible format in {len(files_with_errors)} file(s)"
    return True, "all signs valid (or no signs found)"
