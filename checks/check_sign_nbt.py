from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.nbt_versions import _build_nbt_min_versions, _parse_version
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


_VERSIONS_URL = "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json"
_SIGN_FORMAT_DV = 3836  # 1.20.5 — new sign format (bare strings, components key)


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


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"
    version_map = _load_version_map(cache_dir, ctx.refresh)

    any_below_boundary = False
    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is not None and dv < _SIGN_FORMAT_DV:
                any_below_boundary = True
                break

    if not any_below_boundary:
        return True, "skipped (all targeted versions >= 1.20.5)"

    global_min_version = min(ctx.mc_versions, key=_parse_version)
    nbt_min_versions: dict[Path, str] = {}
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if template_pool_dir.exists():
        nbt_min_versions = _build_nbt_min_versions(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version, ctx.mc_versions
        )

    errors: list[str] = []
    files_with_errors: set[Path] = set()
    bad_sign_count = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        try:
            nbt = nbtlib.load(str(nbt_path))
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        rel = str(nbt_path.relative_to(structures_dir))

        dv_tag = nbt.get("DataVersion")
        if dv_tag is None or int(dv_tag) < _SIGN_FORMAT_DV:
            continue

        file_min_version = nbt_min_versions.get(nbt_path, global_min_version)
        file_min_dv = version_map.get(file_min_version)
        if file_min_dv is not None and file_min_dv >= _SIGN_FORMAT_DV:
            continue

        palette = nbt.get("palette") or []
        sign_indices: set[int] = set()
        for i, state in enumerate(palette):
            if "sign" in str(state.get("Name", "")):
                sign_indices.add(i)

        if not sign_indices:
            continue

        for block_entry in nbt.get("blocks") or []:
            state_tag = block_entry.get("state")
            if state_tag is None or int(state_tag) not in sign_indices:
                continue

            block_nbt = block_entry.get("nbt")
            if not isinstance(block_nbt, nbtlib.Compound):
                continue

            sign_bad = False

            if "components" in block_nbt:
                errors.append(
                    f"[ERROR] {rel}: sign has 'components' key"
                    f" (new sign format, incompatible with min target {file_min_version})"
                )
                sign_bad = True

            for face in ("front_text", "back_text"):
                face_compound = block_nbt.get(face)
                if not isinstance(face_compound, nbtlib.Compound):
                    continue
                messages = face_compound.get("messages")
                if messages is None:
                    continue
                for msg in messages:
                    msg_str = str(msg)
                    if msg_str == "" or not msg_str.startswith('"'):
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
