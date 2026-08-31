"""Named DataVersion boundaries and helpers for per-NBT boundary decisions."""
from __future__ import annotations

from dataclasses import dataclass


# All boundaries verified against misode/technical-changes + minecraft.wiki.
# Names match the *first* MC version that has the new format.
DV_1_20_2 = 3578   # 23w32a: mob effects renamed (ActiveEffects -> active_effects)
DV_1_20_5 = 3837   # 24w09a: items switch from Count/tag to count/components
DV_1_21   = 3953   # 24w21a: entity Attributes -> attributes
DV_1_21_2 = 4080   # 24w33a: attribute ids lose generic./player./zombie. prefixes
DV_1_21_5 = 4325   # 25w02a/25w03a: unified equipment, drop_chances map, text SNBT


@dataclass(frozen=True)
class Boundary:
    """A DataVersion boundary. `first_new_version` is the MC version at which the new format lands."""
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


class BoundarySide:
    OLD = "old"      # entire range is strictly before the boundary
    NEW = "new"      # entire range is at or after the boundary
    SPANS = "spans"  # range crosses the boundary; boundary-sensitive content is unfixable


def side_of(min_dv: int, max_dv: int, boundary_dv: int) -> str:
    """Return which side of a boundary a (min_dv, max_dv) range sits on."""
    if max_dv < boundary_dv:
        return BoundarySide.OLD
    if min_dv >= boundary_dv:
        return BoundarySide.NEW
    return BoundarySide.SPANS


def resolve_dv(version_map: dict[str, int], version: str) -> int | None:
    return version_map.get(version)
