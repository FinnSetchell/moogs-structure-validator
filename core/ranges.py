"""Which Minecraft versions each structure file is wired to serve.

A structure is saved on one version and then converted per version, so the
``DataVersion`` inside it says nothing about where it is used. What does is the
template pool that references it: a plain element serves every targeted version,
and an MSL ``versioned_single_pool_element`` maps version ranges to files. This
module turns the pools into a ``(min, max)`` target range per NBT path, which is
what every version-sensitive check gates on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.mcversions import format_version, parse_range, parse_version, version_in_range
from core.project import MSL_VERSIONED_ELEMENT, Project, element_type, loc_to_path


@dataclass
class RangeInfo:
    """One ``locations`` entry inside a versioned element."""
    pool_rel: str
    element_index: int
    range_key: str
    low: tuple[int, ...] | None   # None if malformed
    high: tuple[int, ...] | None
    nbt_path: Path | None         # None if the location is not in our namespace
    location: str


@dataclass
class PoolCoverage:
    """All range entries of one versioned element (for the coverage check)."""
    pool_rel: str
    element_index: int
    default_location: str | None
    ranges: list[RangeInfo] = field(default_factory=list)


@dataclass(frozen=True)
class NBTVersionInfo:
    min_version: str
    max_version: str


def collect_versioned_elements(project: Project) -> list[PoolCoverage]:
    """Every MSL versioned element in the project with its range entries."""
    result: list[PoolCoverage] = []
    pool_dir = project.template_pool_dir
    structures_dir = project.structures_dir
    for json_path, data in project.pools():
        pool_rel = str(json_path.relative_to(pool_dir))
        for idx, entry in enumerate(data.get("elements", [])):
            element = entry.get("element", {})
            if element_type(element) != MSL_VERSIONED_ELEMENT:
                continue
            cov = PoolCoverage(pool_rel, idx, element.get("location"))
            for range_key, loc in (element.get("locations") or {}).items():
                parsed = parse_range(range_key)
                low, high = parsed if parsed else (None, None)
                cov.ranges.append(RangeInfo(
                    pool_rel, idx, range_key, low, high,
                    loc_to_path(loc, project.namespace, structures_dir, ".nbt"), loc,
                ))
            result.append(cov)
    return result


def build_nbt_version_ranges(project: Project, mc_versions: list[str]) -> dict[Path, NBTVersionInfo]:
    """``(min, max)`` target version for every NBT a pool references.

    * A versioned ref contributes each range's low/high.
    * The default ``location`` of a versioned element serves the targeted
      versions no range covers, and stretches that file's range to include them.
    * An unversioned ref (plain element) serves the whole targeted range.
    * A file referenced both ways takes the widest of everything.
    """
    global_min = parse_version(min(mc_versions, key=parse_version))
    global_max = parse_version(max(mc_versions, key=parse_version))
    structures_dir = project.structures_dir
    ns = project.namespace

    lows: dict[Path, tuple[int, ...]] = {}
    highs: dict[Path, tuple[int, ...]] = {}
    unversioned: set[Path] = set()

    def bump(path: Path, low: tuple[int, ...], high: tuple[int, ...]) -> None:
        if path not in lows or low < lows[path]:
            lows[path] = low
        if path not in highs or high > highs[path]:
            highs[path] = high

    for _, data in project.pools():
        for entry in data.get("elements", []):
            element = entry.get("element", {})
            if element_type(element) == MSL_VERSIONED_ELEMENT:
                locations = element.get("locations") or {}
                for range_key, loc in locations.items():
                    parsed = parse_range(range_key)
                    if parsed is None:
                        continue
                    low, high = parsed
                    if low > high:
                        continue  # inverted: the coverage check reports it
                    nbt_path = loc_to_path(loc, ns, structures_dir, ".nbt")
                    if nbt_path is not None:
                        bump(nbt_path, low, high)
                default_loc = element.get("location")
                if default_loc:
                    nbt_path = loc_to_path(default_loc, ns, structures_dir, ".nbt")
                    if nbt_path is not None:
                        uncovered = [
                            parse_version(v) for v in mc_versions
                            if not any(version_in_range(v, rk) for rk in locations)
                        ]
                        if uncovered:
                            bump(nbt_path, min(uncovered), max(uncovered))
            else:
                loc = element.get("location")
                if loc:
                    nbt_path = loc_to_path(loc, ns, structures_dir, ".nbt")
                    if nbt_path is not None:
                        unversioned.add(nbt_path)

    result: dict[Path, NBTVersionInfo] = {}
    for path in set(lows) | set(highs) | unversioned:
        low = lows.get(path, global_min)
        high = highs.get(path, global_max)
        if path in unversioned:
            low = min(low, global_min)
            high = max(high, global_max)
        result[path] = NBTVersionInfo(format_version(low), format_version(high))
    return result
