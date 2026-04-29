from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


_VERSIONS_URL = "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json"


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


def _is_valid(id_: str, valid_set: set[str], extra_ids: set[str]) -> bool:
    if id_ in valid_set:
        return True
    if id_ in extra_ids:
        return True
    ns = id_.split(":", 1)[0]
    if f"{ns}:*" in extra_ids:
        return True
    return False


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"

    version_map = _load_version_map(cache_dir, ctx.refresh)

    max_allowed_dv: int | None = None
    max_version_name: str | None = None
    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is None:
                print(f"  [WARN] version '{v}' not found in versions.json — skipping DataVersion check for it")
                continue
            if max_allowed_dv is None or dv > max_allowed_dv:
                max_allowed_dv = dv
                max_version_name = v

    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        try:
            nbt = nbtlib.load(str(nbt_path))
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        files_checked += 1
        rel = nbt_path.name

        if max_allowed_dv is not None:
            dv_tag = nbt.get("DataVersion")
            if dv_tag is not None:
                dv = int(dv_tag)
                if dv > max_allowed_dv:
                    dv_version_name = next(
                        (k for k, v in version_map.items() if v == dv), str(dv)
                    )
                    errors.append(
                        f"[ERROR] {rel}: DataVersion {dv} ({dv_version_name}) exceeds max allowed"
                        f" {max_allowed_dv} ({max_version_name}) — structure was saved in a newer game version"
                    )

        for entity_entry in nbt.get("entities") or []:
            entity_nbt = entity_entry.get("nbt")
            if entity_nbt is None:
                continue
            id_tag = entity_nbt.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            entities_checked += 1
            if not _is_valid(entity_id, ctx.valid_entities, ctx.extra_ids):
                errors.append(f"[ERROR] {rel}: unknown entity ID '{entity_id}'")

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {entities_checked} entity ID(s) checked — all valid")

    if errors:
        return False, f"{len(errors)} error(s)"
    return True, f"{files_checked} files, {entities_checked} entities checked"
