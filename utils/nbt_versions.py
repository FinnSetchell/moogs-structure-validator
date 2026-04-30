from __future__ import annotations

import json
from pathlib import Path

from checks.check_data_integrity import _loc_to_path


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _build_nbt_min_versions(
    template_pool_dir: Path,
    structures_dir: Path,
    namespace: str,
    global_min_version: str,
) -> dict[Path, str]:
    versioned: dict[Path, tuple[int, ...]] = {}
    unversioned: set[Path] = set()

    for json_path in sorted(template_pool_dir.rglob("*.json")):
        try:
            with json_path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            continue

        for entry in data.get("elements", []):
            element = entry.get("element", {})
            el_type = element.get("element_type") or element.get("type", "")
            if el_type == "moogs_structures:versioned_single_pool_element":
                for range_key, loc in element.get("locations", {}).items():
                    lower = range_key.split("-")[0]
                    nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                    if nbt_path is None:
                        continue
                    parsed = _parse_version(lower)
                    if nbt_path not in versioned or parsed < versioned[nbt_path]:
                        versioned[nbt_path] = parsed
            else:
                loc = element.get("location")
                if loc:
                    nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                    if nbt_path is not None:
                        unversioned.add(nbt_path)

    result: dict[Path, tuple[int, ...]] = dict(versioned)
    global_parsed = _parse_version(global_min_version)
    for nbt_path in unversioned:
        if nbt_path not in result:
            result[nbt_path] = global_parsed

    return {p: ".".join(str(x) for x in v) for p, v in result.items()}
