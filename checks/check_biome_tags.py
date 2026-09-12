"""Biome tag references resolve.

* A loader-namespace tag (``c:``, ``forge:``, ``neoforge:``) must be written as
  ``{"id": ..., "required": false}`` so the pack still loads on a loader that
  lacks it -- error otherwise.
* A ``minecraft:`` tag must exist in vanilla at the lowest targeted version
  (misode/mcmeta) -- error otherwise.
* A loader tag is looked up in each loader's generated tag set for the lowest
  targeted version (pinned in ``data/biome_tag_map.json``) -- warning only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from core.context import Services, services

if TYPE_CHECKING:
    from core.context import ValidatorContext

_LOADER_NAMESPACES = {"c", "forge", "neoforge"}
_MAP_PATH = Path(__file__).parent.parent / "data" / "biome_tag_map.json"


def _namespace_from_path(path: str) -> str:
    m = re.search(r"/data/([^/]+)/tags/", path)
    return m.group(1) if m else ""


def _tag_ref(entry) -> str | None:
    """The ``ns:path`` of a ``#tag`` entry (string or object form), else None."""
    if isinstance(entry, str) and entry.startswith("#"):
        return entry[1:]
    if isinstance(entry, dict):
        id_val = entry.get("id", "")
        if isinstance(id_val, str) and id_val.startswith("#"):
            return id_val[1:]
    return None


def _check_loader_tag_existence(svc: Services, tag_files: list[tuple[Path, list]], min_version: str) -> list[str]:
    with _MAP_PATH.open(encoding="utf-8") as f:
        biome_tag_map: dict[str, dict[str, dict]] = json.load(f)

    warnings: list[str] = []
    tag_occurrences: dict[str, list[str]] = {}
    for json_path, values in tag_files:
        for entry in values:
            tag_ref = _tag_ref(entry)
            if tag_ref and ":" in tag_ref and tag_ref.split(":")[0] in _LOADER_NAMESPACES:
                tag_occurrences.setdefault(tag_ref, []).append(json_path.name)

    for tag_ref, file_names in tag_occurrences.items():
        tag_ns, tag_path = tag_ref.split(":", 1)

        matching: list[tuple[str, str, dict]] = []
        for loader_name, ranges in biome_tag_map.items():
            if loader_name == "vanilla":
                continue
            for range_key, entry in ranges.items():
                if _namespace_from_path(entry["path"]) == tag_ns and min_version in entry.get("versions", []):
                    matching.append((loader_name, range_key, entry))
        if not matching:
            continue

        found_in: list[str] = []
        missing_in: list[tuple[str, str, dict]] = []
        for loader_name, range_key, entry in matching:
            tag_set = svc.mcmeta.loader_biome_tags(loader_name, range_key, entry)
            if entry.get("tag_style", "is_prefixed") == "unprefixed":
                found = tag_path in tag_set or tag_path.removeprefix("is_") in tag_set
            else:
                found = tag_path in tag_set
            (found_in if found else missing_in).append(loader_name if found else (loader_name, range_key, entry))  # type: ignore[arg-type]

        file_label = file_names[0]
        if not found_in and missing_in:
            warnings.append(
                f"[WARN] {file_label}: #{tag_ns}:{tag_path} not found in any {tag_ns}: loader for {min_version}"
            )
        elif missing_in:
            for loader_name, range_key, entry in missing_in:
                msg = f"[WARN] {file_label}: #{tag_ns}:{tag_path} not found in {loader_name} {range_key}"
                if entry.get("tag_style", "is_prefixed") == "unprefixed":
                    msg += f" (Fabric API v1 uses unprefixed names — consider #c:{tag_path.removeprefix('is_')})"
                warnings.append(msg)

    return warnings


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    biome_tags_dir = project.namespace_root / "tags" / "worldgen" / "biome"
    if not biome_tags_dir.exists():
        return True, "no biome tags"

    tag_files: list[tuple[Path, list]] = []
    for json_path in project.json_files(biome_tags_dir):
        try:
            data = project.load_json(json_path)
        except Exception as e:
            print(f"  [WARN] could not parse {json_path.name}: {e}")
            continue
        tag_files.append((json_path, data.get("values", [])))

    errors: list[str] = []

    # Loader tags must be optional entries.
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

    # Vanilla tags must exist at the lowest targeted version.
    version_map = svc.versions
    min_version: str | None = None
    min_dv: int | None = None
    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is not None and (min_dv is None or dv < min_dv):
                min_dv, min_version = dv, v

    if min_version:
        vanilla_tags = svc.mcmeta.vanilla_biome_tags(min_version)
        if vanilla_tags:
            for json_path, values in tag_files:
                for entry in values:
                    tag_ref = _tag_ref(entry)
                    if tag_ref and tag_ref.startswith("minecraft:") and tag_ref not in vanilla_tags:
                        errors.append(
                            f"[ERROR] {json_path.name}: #minecraft:{tag_ref.split(':', 1)[1]} did not exist in {min_version}"
                        )

    for msg in errors:
        print(f"  {msg}")

    loader_warnings: list[str] = []
    if min_version:
        loader_warnings = _check_loader_tag_existence(svc, tag_files, min_version)
        for msg in loader_warnings:
            print(f"  {msg}")

    summary_suffix = f", {len(loader_warnings)} loader tag warning(s)" if loader_warnings else ""
    if errors:
        return False, f"{len(errors)} error(s){summary_suffix}"
    return True, f"{len(tag_files)} files checked{summary_suffix}"
