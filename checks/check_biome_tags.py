from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from validator import ValidatorContext

_LOADER_NAMESPACES = {"c", "forge", "neoforge"}
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


def _fetch_vanilla_biome_tags(version: str, cache_dir: Path, refresh: bool) -> set[str]:
    cache_file = cache_dir / f"{version}-biome-tags.json"
    if cache_file.exists() and not refresh:
        with cache_file.open() as f:
            data = json.load(f)
    else:
        url = f"https://raw.githubusercontent.com/misode/mcmeta/{version}-summary/data/tag/worldgen/biome/data.json"
        try:
            with urllib.request.urlopen(url) as resp:
                data = json.loads(resp.read().decode())
            with cache_file.open("w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"  [WARN] could not fetch biome tags for {version}: {e}")
            return set()
    return {f"minecraft:{key}" for key in data}


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    biome_tags_dir = namespace_root / "tags" / "worldgen" / "biome"

    if not biome_tags_dir.exists():
        return True, "no biome tags"

    cache_dir = Path(__file__).parent.parent / "cache"

    tag_files: list[tuple[Path, list]] = []
    for json_path in sorted(biome_tags_dir.rglob("*.json")):
        try:
            with json_path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [WARN] could not parse {json_path.name}: {e}")
            continue
        tag_files.append((json_path, data.get("values", [])))

    errors: list[str] = []

    # Task A: loader-specific tag namespaces must use {"id": "...", "required": false}
    for json_path, values in tag_files:
        for entry in values:
            if isinstance(entry, str) and entry.startswith("#"):
                ns = entry[1:].split(":")[0] if ":" in entry else ""
                if ns in _LOADER_NAMESPACES:
                    errors.append(
                        f'[ERROR] {json_path.name}: {entry!r} — loader tag must be {{"id": "...", "required": false}}'
                    )
            elif isinstance(entry, dict):
                id_val = entry.get("id", "")
                if isinstance(id_val, str) and id_val.startswith("#"):
                    ns = id_val[1:].split(":")[0] if ":" in id_val else ""
                    if ns in _LOADER_NAMESPACES and entry.get("required") is not False:
                        errors.append(
                            f'[ERROR] {json_path.name}: {entry!r} — loader tag must be {{"id": "...", "required": false}}'
                        )

    # Task B: vanilla minecraft tag existence for the minimum supported version
    version_map = _load_version_map(cache_dir, ctx.refresh)
    min_version: str | None = None
    min_dv: int | None = None
    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is None:
                continue
            if min_dv is None or dv < min_dv:
                min_dv = dv
                min_version = v

    if min_version:
        vanilla_tags = _fetch_vanilla_biome_tags(min_version, cache_dir, ctx.refresh)
        if vanilla_tags:
            for json_path, values in tag_files:
                for entry in values:
                    tag_ref: str | None = None
                    if isinstance(entry, str) and entry.startswith("#"):
                        tag_ref = entry[1:]
                    elif isinstance(entry, dict):
                        id_val = entry.get("id", "")
                        if isinstance(id_val, str) and id_val.startswith("#"):
                            tag_ref = id_val[1:]
                    if tag_ref and tag_ref.startswith("minecraft:"):
                        if tag_ref not in vanilla_tags:
                            path_part = tag_ref.split(":", 1)[1]
                            errors.append(
                                f"[ERROR] {json_path.name}: #minecraft:{path_part} did not exist in {min_version}"
                            )

    for msg in errors:
        print(f"  {msg}")

    n_files = len(tag_files)
    if errors:
        return False, f"{len(errors)} error(s)"
    return True, f"{n_files} files checked"
