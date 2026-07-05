from utils.boundaries import DV_1_20_5, DV_1_21_5, BoundarySide, side_of


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
