"""Tests for MSL type dispatch in check_worldgen_schemas. Each test writes
worldgen JSON files into a tmp datapack and asserts on the check result."""
from __future__ import annotations

import json
from pathlib import Path

from tests.nbt_helpers import FakeContext

from checks import check_worldgen_schemas as mod


def _write(root: Path, namespace: str, subdir: str, name: str, data: dict) -> None:
    path = root / "src" / "main" / "resources" / "data" / namespace / "worldgen" / subdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _generic_structure(**overrides) -> dict:
    data = {
        "type": "moogs_structures:moogs_structures_generic_jigsaw_structure",
        "biomes": "#minecraft:is_overworld",
        "step": "surface_structures",
        "spawn_overrides": {},
        "start_pool": "test:start",
        "size": 6,
        "start_height": {"absolute": 0},
    }
    data.update(overrides)
    return data


def _pool(elements: list[dict]) -> dict:
    return {
        "fallback": "minecraft:empty",
        "elements": [{"weight": 1, "element": e} for e in elements],
    }


def test_generic_structure_size_128_passes(tmp_path):
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(size=128))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_generic_structure_size_129_fails(tmp_path):
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(size=129))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_unknown_msl_structure_type_fails(tmp_path):
    _write(tmp_path, "test", "structure", "s.json",
           _generic_structure(type="moogs_structures:generic_jigsaw_structure"))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_nether_structure_fixed_height_passes(tmp_path):
    data = _generic_structure(
        type="moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
        land_search_direction="FIXED_HEIGHT",
        ledge_offset_y=10,
    )
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_nether_structure_missing_search_direction_fails(tmp_path):
    data = _generic_structure(
        type="moogs_structures:moogs_structures_generic_nether_jigsaw_structure")
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_versioned_element_without_locations_fails(tmp_path):
    element = {
        "element_type": "moogs_structures:versioned_single_pool_element",
        "projection": "rigid",
        "processors": "minecraft:empty",
    }
    _write(tmp_path, "test", "template_pool", "p.json", _pool([element]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_versioned_element_valid_passes(tmp_path):
    element = {
        "element_type": "moogs_structures:versioned_single_pool_element",
        "location": "test:a",
        "locations": {"1.21-1.21.4": "test:a"},
        "projection": "rigid",
        "processors": "minecraft:empty",
    }
    _write(tmp_path, "test", "template_pool", "p.json", _pool([element]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_unknown_msl_element_type_fails(tmp_path):
    element = {
        "element_type": "moogs_structures:versioned_pool_element",
        "location": "test:a",
    }
    _write(tmp_path, "test", "template_pool", "p.json", _pool([element]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_mirroring_element_bad_mirror_fails(tmp_path):
    element = {
        "element_type": "moogs_structures:mirroring_single_pool_element",
        "location": "test:a",
        "mirror": "UP_DOWN",
        "projection": "rigid",
    }
    _write(tmp_path, "test", "template_pool", "p.json", _pool([element]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_advanced_random_spread_missing_salt_fails(tmp_path):
    data = {
        "structures": [{"structure": "test:s", "weight": 1}],
        "placement": {
            "type": "moogs_structures:advanced_random_spread",
            "spacing": 30,
            "separation": 20,
        },
    }
    _write(tmp_path, "test", "structure_set", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_advanced_random_spread_valid_passes(tmp_path):
    data = {
        "structures": [{"structure": "test:s", "weight": 1}],
        "placement": {
            "type": "moogs_structures:advanced_random_spread",
            "salt": 1234,
            "spacing": 30,
            "separation": 20,
            "super_exclusion_zone": {
                "other_set": ["minecraft:villages"],
                "chunk_count": 6,
            },
        },
    }
    _write(tmp_path, "test", "structure_set", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed
