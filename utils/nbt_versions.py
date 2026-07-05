from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from checks.check_data_integrity import _loc_to_path


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _fmt_version(v: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


def _parse_range(range_key: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Parse a "1.21-1.21.4" range key into (low, high). Returns None if malformed."""
    parts = range_key.split("-")
    try:
        if len(parts) == 1:
            v = _parse_version(parts[0])
            return v, v
        if len(parts) == 2:
            return _parse_version(parts[0]), _parse_version(parts[1])
    except (ValueError, TypeError):
        return None
    return None


def _version_in_range(version: str, range_key: str) -> bool:
    parsed = _parse_range(range_key)
    if parsed is None:
        return False
    low, high = parsed
    v = _parse_version(version)
    return low <= v <= high


@dataclass
class RangeInfo:
    """One `locations` entry (or the default `location`) inside a versioned element."""
    pool_rel: str  # e.g. "my_structure/rooms.json"
    element_index: int
    range_key: str  # e.g. "1.21-1.21.4" or "default"
    low: tuple[int, ...] | None  # None if malformed
    high: tuple[int, ...] | None
    nbt_path: Path | None  # None if location does not resolve to this project
    location: str
    is_default: bool = False  # True for the top-level `location` field


@dataclass
class PoolCoverage:
    """All range entries seen inside one versioned element (for coverage checks)."""
    pool_rel: str
    element_index: int
    default_location: str | None
    ranges: list[RangeInfo] = field(default_factory=list)  # excludes the default


@dataclass
class NBTVersionInfo:
    min_version: str
    max_version: str


def _walk_pools(template_pool_dir: Path):
    """Yield (json_path, pool_data) for every parseable pool JSON."""
    for json_path in sorted(template_pool_dir.rglob("*.json")):
        try:
            with json_path.open(encoding="utf-8-sig") as f:
                yield json_path, json.load(f)
        except (json.JSONDecodeError, OSError):
            continue


def collect_versioned_elements(
    template_pool_dir: Path,
    structures_dir: Path,
    namespace: str,
) -> list[PoolCoverage]:
    """Return every versioned_single_pool_element with its range entries."""
    result: list[PoolCoverage] = []
    for json_path, data in _walk_pools(template_pool_dir):
        pool_rel = str(json_path.relative_to(template_pool_dir))
        for idx, entry in enumerate(data.get("elements", [])):
            element = entry.get("element", {})
            el_type = element.get("element_type") or element.get("type", "")
            if el_type != "moogs_structures:versioned_single_pool_element":
                continue

            default_loc = element.get("location")
            cov = PoolCoverage(pool_rel=pool_rel, element_index=idx, default_location=default_loc)

            for range_key, loc in (element.get("locations") or {}).items():
                parsed = _parse_range(range_key)
                low, high = (parsed if parsed else (None, None))
                nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                cov.ranges.append(RangeInfo(
                    pool_rel=pool_rel,
                    element_index=idx,
                    range_key=range_key,
                    low=low,
                    high=high,
                    nbt_path=nbt_path,
                    location=loc,
                ))

            result.append(cov)
    return result


def _build_nbt_version_ranges(
    template_pool_dir: Path,
    structures_dir: Path,
    namespace: str,
    global_min_version: str,
    mc_versions: list[str] | None = None,
    global_max_version: str | None = None,
) -> dict[Path, NBTVersionInfo]:
    """For every NBT referenced by a pool, compute (min, max) target version.

    Rules:
      - Versioned refs: NBT.min = min of all range lows serving it; NBT.max = max of all range highs.
      - Default `location` of a versioned element applies to versions NOT covered by any range;
        it stretches the NBT's min/max to include those uncovered versions.
      - Unversioned refs (plain single/legacy elements): NBT gets (global_min, global_max).
      - An NBT referenced by both: min = min of everything, max = max of everything.
    """
    global_min_parsed = _parse_version(global_min_version)
    if global_max_version is None:
        global_max_parsed = _parse_version(
            max(mc_versions, key=_parse_version) if mc_versions else global_min_version
        )
    else:
        global_max_parsed = _parse_version(global_max_version)

    lows: dict[Path, tuple[int, ...]] = {}
    highs: dict[Path, tuple[int, ...]] = {}

    def bump(path: Path, low: tuple[int, ...], high: tuple[int, ...]) -> None:
        if path not in lows or low < lows[path]:
            lows[path] = low
        if path not in highs or high > highs[path]:
            highs[path] = high

    unversioned: set[Path] = set()

    for json_path, data in _walk_pools(template_pool_dir):
        for entry in data.get("elements", []):
            element = entry.get("element", {})
            el_type = element.get("element_type") or element.get("type", "")
            if el_type == "moogs_structures:versioned_single_pool_element":
                locations_dict = element.get("locations") or {}

                for range_key, loc in locations_dict.items():
                    parsed = _parse_range(range_key)
                    if parsed is None:
                        continue
                    low, high = parsed
                    if low > high:
                        continue  # inverted range: coverage check reports this
                    nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                    if nbt_path is None:
                        continue
                    bump(nbt_path, low, high)

                # Default location covers versions not otherwise covered.
                default_loc = element.get("location")
                if default_loc and mc_versions:
                    nbt_path = _loc_to_path(default_loc, namespace, structures_dir, ".nbt")
                    if nbt_path is not None:
                        uncovered = [
                            v for v in mc_versions
                            if not any(_version_in_range(v, rk) for rk in locations_dict)
                        ]
                        if uncovered:
                            parsed_uncovered = [_parse_version(v) for v in uncovered]
                            bump(nbt_path, min(parsed_uncovered), max(parsed_uncovered))
                        # else: fully covered by ranges -- default is dead code; leave alone.
            else:
                loc = element.get("location")
                if loc:
                    nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
                    if nbt_path is not None:
                        unversioned.add(nbt_path)

    result: dict[Path, NBTVersionInfo] = {}
    all_paths = set(lows) | set(highs) | unversioned
    for path in all_paths:
        low = lows.get(path, global_min_parsed)
        high = highs.get(path, global_max_parsed)
        if path in unversioned:
            if low > global_min_parsed:
                low = global_min_parsed
            if high < global_max_parsed:
                high = global_max_parsed
        result[path] = NBTVersionInfo(_fmt_version(low), _fmt_version(high))
    return result


def _build_nbt_min_versions(
    template_pool_dir: Path,
    structures_dir: Path,
    namespace: str,
    global_min_version: str,
    mc_versions: list[str] | None = None,
) -> dict[Path, str]:
    """Backward-compat wrapper returning only the min-version dict."""
    ranges = _build_nbt_version_ranges(
        template_pool_dir, structures_dir, namespace, global_min_version, mc_versions
    )
    return {p: info.min_version for p, info in ranges.items()}
