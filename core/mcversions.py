"""Minecraft version strings, DataVersions, and the format boundaries the checks
reason about.

A *version* is a release id such as ``1.21.4`` or ``26.2``; it orders as a tuple
of ints. A *DataVersion* is the integer the game stamps into saved data. The map
between the two comes from misode/mcmeta's version index (see ``core.mcmeta``);
the named boundary constants below are DataVersions of the first release that
carries a new data format, verified against that index.
"""
from __future__ import annotations

from dataclasses import dataclass


# --- version strings -------------------------------------------------------

def parse_version(v: str) -> tuple[int, ...]:
    """``"1.21.4"`` -> ``(1, 21, 4)``. Raises ValueError on anything else."""
    return tuple(int(x) for x in v.split("."))


def try_parse_version(v: str) -> tuple[int, ...] | None:
    try:
        return parse_version(v)
    except (ValueError, TypeError, AttributeError):
        return None


def format_version(v: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in v)


def parse_range(range_key: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Parse a versioned-element range key.

    ``"1.21"`` -> ``((1, 21), (1, 21))``; ``"1.21-1.21.4"`` -> ``((1, 21), (1, 21, 4))``.
    Returns None when the key is malformed. An inverted range still parses;
    callers reject it with ``low > high``.
    """
    parts = range_key.split("-")
    try:
        if len(parts) == 1:
            v = parse_version(parts[0])
            return v, v
        if len(parts) == 2:
            return parse_version(parts[0]), parse_version(parts[1])
    except (ValueError, TypeError):
        return None
    return None


def version_in_range(version: str, range_key: str) -> bool:
    parsed = parse_range(range_key)
    if parsed is None:
        return False
    low, high = parsed
    return low <= parse_version(version) <= high


def min_version(versions: list[str]) -> str:
    return min(versions, key=parse_version)


def max_version(versions: list[str]) -> str:
    return max(versions, key=parse_version)


# --- DataVersion boundaries ---------------------------------------------------
# Names match the *first* MC release that has the new format. Values are checked
# against the mcmeta version index by tests/test_boundaries.py.

DV_1_20_2 = 3578   # 23w32a: mob effects renamed (ActiveEffects -> active_effects)
DV_1_20_5 = 3837   # 24w09a: items switch from Count/tag to count/components
DV_1_21   = 3953   # 24w21a: entity Attributes -> attributes
DV_1_21_2 = 4080   # 24w33a: attribute ids lose generic./player./zombie. prefixes
DV_1_21_5 = 4325   # 25w02a/25w03a: unified equipment, drop_chances map, text SNBT


@dataclass(frozen=True)
class Boundary:
    """A DataVersion boundary. ``first_new_version`` is the MC release at which
    the new format lands."""
    name: str
    dv: int
    first_new_version: str
    description: str


BOUNDARIES: dict[str, Boundary] = {
    "1.20.2": Boundary("mob-effect", DV_1_20_2, "1.20.2", "ActiveEffects/PascalCase -> active_effects/snake_case"),
    "1.20.5": Boundary("item-format", DV_1_20_5, "1.20.5", "Count/tag -> count/components (item stacks)"),
    "1.21":   Boundary("attributes", DV_1_21, "1.21", "Attributes -> attributes (list-of-maps -> namespaced ids)"),
    "1.21.2": Boundary("attribute-prefix", DV_1_21_2, "1.21.2", "attribute ids lose generic./player./zombie. prefixes"),
    "1.21.5": Boundary("equipment-and-text", DV_1_21_5, "1.21.5", "equipment/drop_chances map; text SNBT; enchantments unwrapped"),
}

# DataVersion -> the release that introduced it, for messages.
DV_VERSION_NAMES: dict[int, str] = {b.dv: b.first_new_version for b in BOUNDARIES.values()}


class BoundarySide:
    OLD = "old"      # entire range is strictly before the boundary
    NEW = "new"      # entire range is at or after the boundary
    SPANS = "spans"  # range crosses the boundary; boundary-sensitive content is unfixable


def side_of(min_dv: int, max_dv: int, boundary_dv: int) -> str:
    """Which side of a boundary a ``(min_dv, max_dv)`` range sits on."""
    if max_dv < boundary_dv:
        return BoundarySide.OLD
    if min_dv >= boundary_dv:
        return BoundarySide.NEW
    return BoundarySide.SPANS


# --- the version index ------------------------------------------------------

class VersionIndex:
    """``id -> DataVersion`` for every stable release, plus ordering helpers.

    Built from mcmeta's ``versions/data.json`` (newest first). Only stable
    releases are kept: that is what ``mc_versions`` in a project config names,
    and it is what the wired ranges of a versioned pool element are written in.
    """

    def __init__(self, entries: list[dict]):
        self.data_version: dict[str, int] = {}
        for e in entries:
            if e.get("stable") and isinstance(e.get("id"), str) and isinstance(e.get("data_version"), int):
                self.data_version[e["id"]] = e["data_version"]
        # Oldest first; ties impossible for distinct ids.
        self.stable_ascending: list[str] = sorted(
            (v for v in self.data_version if try_parse_version(v) is not None),
            key=parse_version,
        )
        self._name_by_dv: dict[int, str] = {}
        for v in self.stable_ascending:
            self._name_by_dv.setdefault(self.data_version[v], v)

    def __bool__(self) -> bool:
        return bool(self.data_version)

    def get(self, version: str) -> int | None:
        return self.data_version.get(version)

    def name_of(self, dv: int) -> str:
        """The release with exactly this DataVersion, else the number as text."""
        return self._name_by_dv.get(dv, str(dv))

    def dv_range(self, versions: list[str]) -> tuple[int, int] | None:
        """(min, max) DataVersion across ``versions``; None if any is unmapped."""
        dvs = [self.data_version.get(v) for v in versions]
        if not dvs or any(dv is None for dv in dvs):
            return None
        return min(dvs), max(dvs)  # type: ignore[type-var]

    def stable_after(self, version: str) -> list[str]:
        """Stable releases strictly newer than ``version``, oldest first."""
        floor = try_parse_version(version)
        if floor is None:
            return list(self.stable_ascending)
        return [v for v in self.stable_ascending if parse_version(v) > floor]
