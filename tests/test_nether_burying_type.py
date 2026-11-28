"""burying_type on MSL's Nether jigsaw type: only LOWEST_CORNER, and never with FIXED_HEIGHT or CEILING
(MSL refuses all of these)."""
from __future__ import annotations

import pytest

from tests.nbt_helpers import FakeContext
from tests.test_worldgen_schemas import _generic_structure, _write

from checks import check_worldgen_schemas as mod

NETHER = "moogs_structures:moogs_structures_generic_nether_jigsaw_structure"


def _passes(tmp_path, **fields) -> bool:
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(type=NETHER, **fields))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    return passed


def test_lowest_corner_with_a_land_search_passes(tmp_path):
    assert _passes(tmp_path, land_search_direction="HIGHEST_LAND", burying_type="LOWEST_CORNER")


def test_lowest_corner_with_lowest_land_passes(tmp_path):
    assert _passes(tmp_path, land_search_direction="LOWEST_LAND", burying_type="LOWEST_CORNER")


def test_no_burying_type_passes(tmp_path):
    assert _passes(tmp_path, land_search_direction="FIXED_HEIGHT")


def test_other_burying_types_fail(tmp_path):
    for burying in ("AVERAGE_LAND", "LOWEST_SIDE", "lowest_corner"):
        assert not _passes(tmp_path, land_search_direction="HIGHEST_LAND", burying_type=burying), burying


@pytest.mark.parametrize("direction", ["FIXED_HEIGHT", "CEILING"])
def test_lowest_corner_without_a_land_search_fails(tmp_path, capsys, direction):
    assert not _passes(tmp_path, land_search_direction=direction, burying_type="LOWEST_CORNER")
    assert "burying_type needs a land search" in capsys.readouterr().out
