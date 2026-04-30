from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from utils.nbt_versions import _parse_version

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


def _namespace_from_path(path: str) -> str:
    m = re.search(r'/data/([^/]+)/tags/', path)
    return m.group(1) if m else ""


def _fetch_loader_tag_set(
    loader_name: str,
    range_key: str,
    entry: dict,
    cache_dir: Path,
    refresh: bool,
    run_cache: dict[str, set[str]],
) -> set[str]:
    cache_key = f"{loader_name}/{range_key}"
    if cache_key in run_cache:
        return run_cache[cache_key]

    repo = entry["repository"]
    ref = entry["ref"]
    path = entry["path"]
    sanitised_repo = repo.replace("/", "-")
    cache_file = cache_dir / f"loader-{sanitised_repo}-{ref[:16]}.json"

    if cache_file.exists() and not refresh:
        with cache_file.open() as f:
            names = json.load(f)
    else:
        url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req) as resp:
                items = json.loads(resp.read().decode())
            names = [
                item["name"][:-5]
                for item in items
                if item.get("type") == "file" and item.get("name", "").endswith(".json")
            ]
            with cache_file.open("w") as f:
                json.dump(names, f)
        except Exception as e:
            print(f"  [WARN] could not fetch loader tags for {loader_name} {range_key}: {e}")
            run_cache[cache_key] = set()
            return set()

    tag_set = set(names)
    run_cache[cache_key] = tag_set
    return tag_set


def _check_loader_tag_existence(
    tag_files: list[tuple[Path, list]],
    min_version: str,
    cache_dir: Path,
    refresh: bool,
) -> list[str]:
    map_path = Path(__file__).parent.parent / "data" / "biome_tag_map.json"
    with map_path.open(encoding="utf-8") as f:
        biome_tag_map: dict[str, dict[str, dict]] = json.load(f)

    run_cache: dict[str, set[str]] = {}
    warnings: list[str] = []

    # Collect all unique loader tag references across all files
    tag_occurrences: dict[str, list[str]] = {}  # tag_ref -> list of filenames
    for json_path, values in tag_files:
        for entry in values:
            tag_ref: str | None = None
            if isinstance(entry, str) and entry.startswith("#"):
                tag_ref = entry[1:]
            elif isinstance(entry, dict):
                id_val = entry.get("id", "")
                if isinstance(id_val, str) and id_val.startswith("#"):
                    tag_ref = id_val[1:]
            if tag_ref and ":" in tag_ref:
                ns = tag_ref.split(":")[0]
                if ns in _LOADER_NAMESPACES:
                    if tag_ref not in tag_occurrences:
                        tag_occurrences[tag_ref] = []
                    tag_occurrences[tag_ref].append(json_path.name)

    for tag_ref, file_names in tag_occurrences.items():
        tag_ns, tag_path = tag_ref.split(":", 1)

        # Find all map entries (across all loaders) that serve this namespace for min_version
        matching: list[tuple[str, str, dict]] = []  # (loader_name, range_key, entry)
        for loader_name, ranges in biome_tag_map.items():
            if loader_name == "vanilla":
                continue
            for range_key, entry in ranges.items():
                if (
                    _namespace_from_path(entry["path"]) == tag_ns
                    and min_version in entry.get("versions", [])
                ):
                    matching.append((loader_name, range_key, entry))

        if not matching:
            continue

        found_in: list[str] = []
        missing_in: list[tuple[str, str, dict]] = []

        for loader_name, range_key, entry in matching:
            tag_set = _fetch_loader_tag_set(loader_name, range_key, entry, cache_dir, refresh, run_cache)
            tag_style = entry.get("tag_style", "is_prefixed")

            if tag_style == "unprefixed":
                found = tag_path in tag_set or tag_path.removeprefix("is_") in tag_set
            else:
                found = tag_path in tag_set

            if found:
                found_in.append(loader_name)
            else:
                missing_in.append((loader_name, range_key, entry))

        file_label = file_names[0]

        if not found_in and missing_in:
            loader_ns_label = tag_ns
            warnings.append(
                f"[WARN] {file_label}: #{tag_ns}:{tag_path} not found in any {loader_ns_label}: loader for {min_version}"
            )
        elif missing_in:
            for loader_name, range_key, entry in missing_in:
                msg = f"[WARN] {file_label}: #{tag_ns}:{tag_path} not found in {loader_name} {range_key}"
                tag_style = entry.get("tag_style", "is_prefixed")
                if tag_style == "unprefixed":
                    msg += f" (Fabric API v1 uses unprefixed names — consider #c:{tag_path.removeprefix('is_')})"
                warnings.append(msg)

    return warnings


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

    # Phase 2: loader tag existence (warnings only, do not affect pass/fail)
    loader_warnings: list[str] = []
    if min_version:
        loader_warnings = _check_loader_tag_existence(tag_files, min_version, cache_dir, ctx.refresh)
        for msg in loader_warnings:
            print(f"  {msg}")

    n_files = len(tag_files)
    summary_suffix = f", {len(loader_warnings)} loader tag warning(s)" if loader_warnings else ""
    if errors:
        return False, f"{len(errors)} error(s){summary_suffix}"
    return True, f"{n_files} files checked{summary_suffix}"
