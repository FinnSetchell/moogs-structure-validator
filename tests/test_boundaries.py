from core.mcversions import (
    DV_1_20_2, DV_1_20_5, DV_1_21, DV_1_21_2, DV_1_21_5, BoundarySide, side_of,
)
from tests.nbt_helpers import VANILLA_VERSION_MAP


def test_side_of_entirely_old():
    # min & max both below the boundary
    assert side_of(3000, 3800, DV_1_20_5) == BoundarySide.OLD


def test_side_of_entirely_new():
    # min at boundary is NEW
    assert side_of(DV_1_20_5, 5000, DV_1_20_5) == BoundarySide.NEW


def test_side_of_spans():
    # min pre-boundary, max post-boundary
    assert side_of(3800, 5000, DV_1_20_5) == BoundarySide.SPANS


def test_side_of_max_just_below():
    assert side_of(3000, DV_1_20_5 - 1, DV_1_20_5) == BoundarySide.OLD


def test_side_of_min_just_above():
    assert side_of(DV_1_21_5, DV_1_21_5, DV_1_21_5) == BoundarySide.NEW


def test_boundary_constants_match_the_version_index():
    """Each boundary is the DataVersion of the first release with the new format."""
    assert DV_1_20_2 == VANILLA_VERSION_MAP["1.20.2"]
    assert DV_1_20_5 == VANILLA_VERSION_MAP["1.20.5"]
    assert DV_1_21 == VANILLA_VERSION_MAP["1.21"]
    assert DV_1_21_2 == VANILLA_VERSION_MAP["1.21.2"]
    assert DV_1_21_5 == VANILLA_VERSION_MAP["1.21.5"]
