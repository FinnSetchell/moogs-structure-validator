"""Tests for MSL type dispatch in check_worldgen_schemas. Each test writes
worldgen JSON files into a tmp datapack and asserts on the check result."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.nbt_helpers import FakeContext, stub_registries

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


def test_y_allowance_inverted_fails(tmp_path):
    data = _generic_structure(y_allowance={"min_y_allowed": 60, "max_y_allowed": 20})
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_y_allowance_valid_passes(tmp_path):
    data = _generic_structure(y_allowance={"min_y_allowed": 20, "max_y_allowed": 60})
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_y_allowance_max_without_min_fails(tmp_path):
    """MSL guards this branch on maxYAllowed and then unwraps minYAllowed inside it,
    so a max with no min throws during chunk generation."""
    data = _generic_structure(y_allowance={"max_y_allowed": 41})
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_y_allowance_min_without_max_passes(tmp_path):
    """The mirrored branch guards minYAllowed correctly, so a min with no max is fine.
    MoogsEndStructures ships 25 structures shaped this way without incident."""
    data = _generic_structure(y_allowance={"min_y_allowed": 45})
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


# MSL's 1.20 builds read top-level min_y_allowed / max_y_allowed / allowed_y_range_from_start;
# its 1.21 builds read y_allowance only. Each skips the other's keys without a word.
LINE_1_20 = ["1.20", "1.20.1", "1.20.2", "1.20.4", "1.20.6"]
LINE_1_21 = ["1.21", "1.21.1", "1.21.4", "26.3"]
NETHER = {"type": "moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
          "land_search_direction": "HIGHEST_LAND"}


@pytest.mark.parametrize("versions, fields", [
    (LINE_1_20, {"min_y_allowed": 20, "max_y_allowed": 60, "allowed_y_range_from_start": 10}),
    (LINE_1_21, {"y_allowance": {"min_y_allowed": 20, "max_y_allowed": 60}}),
    (LINE_1_20 + LINE_1_21, {"min_y_allowed": 20, "max_y_allowed": 60,
                             "y_allowance": {"min_y_allowed": 20, "max_y_allowed": 60}}),
])
def test_height_limits_in_the_form_each_line_reads_pass(tmp_path, capsys, versions, fields):
    for i, base in enumerate(({}, NETHER)):
        _write(tmp_path, "test", "structure", f"s{i}.json", _generic_structure(**base, **fields))
    passed, _ = mod.run(FakeContext("test", versions, tmp_path))
    assert passed, capsys.readouterr().out


@pytest.mark.parametrize("base", [{}, NETHER])
def test_y_allowance_on_the_1_20_line_fails(tmp_path, capsys, base):
    _write(tmp_path, "test", "structure", "s.json",
           _generic_structure(**base, y_allowance={"min_y_allowed": 20, "max_y_allowed": 60}))
    passed, _ = mod.run(FakeContext("test", LINE_1_20, tmp_path))
    out = capsys.readouterr().out
    assert not passed
    assert "s.json @ y_allowance\n    skipped on 1.20-1.20.6: MSL's 1.20 builds read the height limits" in out


@pytest.mark.parametrize("fields, at", [
    ({"min_y_allowed": 20, "max_y_allowed": 60}, "min_y_allowed, max_y_allowed"),
    ({"allowed_y_range_from_start": 10}, "allowed_y_range_from_start"),
    ({"y_allowance": {"min_y_allowed": 20}, "allowed_y_range_from_start": 10}, "allowed_y_range_from_start"),
])
def test_top_level_height_limits_on_the_1_21_line_fail(tmp_path, capsys, fields, at):
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(**fields))
    passed, _ = mod.run(FakeContext("test", LINE_1_21, tmp_path))
    out = capsys.readouterr().out
    assert not passed
    assert f"s.json @ {at}\n    skipped on 1.21-26.3: MSL's 1.21 builds read min_y_allowed" in out, out


def test_nether_y_allowance_max_without_min_passes(tmp_path):
    """The nether type overrides postLayoutAdjustments and never reaches the crashing
    code, so the same shape is safe there."""
    data = _generic_structure(
        type="moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
        land_search_direction="FIXED_HEIGHT",
        ledge_offset_y=10,
        y_allowance={"max_y_allowed": 35},
    )
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


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


def test_enhanced_terrain_adaptation_valid_passes(tmp_path):
    element = {
        "element_type": "moogs_structures:versioned_single_pool_element",
        "location": "test:a",
        "projection": "rigid",
        "processors": "minecraft:empty",
        "enhanced_terrain_adaptation": {
            "kernel_size": 5,
            "kernel_distance": 8,
            "top": "carve",
            "bottom": "bury",
            "band": {"bottom": 0, "top": 3, "piece_heights": [24, 25, 27]},
        },
    }
    _write(tmp_path, "test", "template_pool", "p.json", _pool([element]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_enhanced_terrain_adaptation_bad_action_fails(tmp_path):
    element = {
        "element_type": "moogs_structures:versioned_single_pool_element",
        "location": "test:a",
        "projection": "rigid",
        "enhanced_terrain_adaptation": {
            "kernel_size": 5,
            "kernel_distance": 8,
            "top": "smooth",
            "bottom": "none",
        },
    }
    _write(tmp_path, "test", "template_pool", "p.json", _pool([element]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_enhanced_terrain_adaptation_band_missing_top_fails(tmp_path):
    data = _generic_structure(
        type="moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
        land_search_direction="HIGHEST_LAND",
        enhanced_terrain_adaptation={
            "kernel_size": 5,
            "kernel_distance": 8,
            "top": "carve",
            "bottom": "none",
            "band": {"bottom": 0},
        },
    )
    _write(tmp_path, "test", "structure", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def _processor_list(processors: list[dict]) -> dict:
    return {"processors": processors}


def test_spawner_processor_valid_passes(tmp_path):
    proc = {
        "processor_type": "moogs_structures:spawner_randomizing_processor",
        "weighted_entities": [
            {"entity": "minecraft:zombie", "weight": 3},
            {"entity": "minecraft:skeleton", "weight": 1, "nbt": {}},
        ],
        "spawn_count": 4,
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_spawner_processor_missing_entities_fails(tmp_path):
    proc = {
        "processor_type": "moogs_structures:spawner_randomizing_processor",
        "delay": 20,
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_spawner_processor_zero_weight_fails(tmp_path):
    proc = {
        "processor_type": "moogs_structures:spawner_randomizing_processor",
        "weighted_entities": [{"entity": "minecraft:zombie", "weight": 0}],
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_unknown_msl_processor_type_fails(tmp_path):
    proc = {"processor_type": "moogs_structures:spawner_randomising_processor"}
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


# MSL 4.0.0: follow_floor_processor (search_range Codec.intRange(1, 64), default 16;
# offset an int, default 0) and rail_slope_processor (no fields).
def test_follow_floor_and_rail_slope_processors_pass(tmp_path):
    procs = [{"processor_type": "moogs_structures:follow_floor_processor"},
             {"processor_type": "moogs_structures:follow_floor_processor", "search_range": 64, "offset": -2},
             {"processor_type": "moogs_structures:follow_floor_processor", "search_range": 1},
             {"processor_type": "moogs_structures:rail_slope_processor"}]
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list(procs))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_rail_rotation_processor_passes(tmp_path):
    # MSL 4.0.0, MapCodec.unit: MSL adds it to its own structures, and a pool may list it.
    proc = {"processor_type": "moogs_structures:rail_rotation_processor"}
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.20.1", "1.21.1"], tmp_path))
    assert passed


def test_follow_floor_search_range_out_of_range_fails(tmp_path, capsys):
    # StrictOptionalField: MSL refuses a value outside 1-64.
    for bad, why in ((0, "less than the minimum of 1"), (65, "greater than the maximum of 64")):
        root = tmp_path / str(bad)
        proc = {"processor_type": "moogs_structures:follow_floor_processor", "search_range": bad}
        _write(root, "test", "processor_list", "p.json", _processor_list([proc]))
        passed, _ = mod.run(FakeContext("test", ["1.21"], root))
        out = capsys.readouterr().out
        assert not passed, out
        assert "p.json @ search_range" in out and why in out, out


def test_follow_floor_offset_must_be_a_whole_number(tmp_path):
    proc = {"processor_type": "moogs_structures:follow_floor_processor", "offset": 1.5}
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


ANCHOR = {"processor_type": "moogs_structures:hanging_entity_anchor_processor"}


def test_hanging_entity_anchor_processor_passes(tmp_path):
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([ANCHOR]))
    passed, _ = mod.run(FakeContext("test", ["1.20.1", "1.21.1"], tmp_path))
    assert passed


def test_hanging_entity_anchor_misspelled_fails(tmp_path, capsys):
    proc = {"processor_type": "moogs_structures:hanging_entity_anchor"}
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    assert not passed
    assert "unknown MSL processor type 'moogs_structures:hanging_entity_anchor'" in capsys.readouterr().out


def test_pillar_processor_valid_passes(tmp_path):
    proc = {
        "processor_type": "moogs_structures:pillar_processor",
        "pillar_trigger_and_replacements": [
            {
                "trigger": {"Name": "minecraft:yellow_wool"},
                "replacement": {"Name": "minecraft:basalt", "Properties": {"axis": "y"}},
            },
        ],
        "direction": "down",
        "pillar_state_randomizer": {
            "entries": [
                {"block": {"Name": "minecraft:magma_block"}, "probability": 0.25, "max_y": 40},
            ],
            "default": {"Name": "minecraft:basalt"},
        },
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_pillar_processor_bad_direction_fails(tmp_path):
    proc = {
        "processor_type": "moogs_structures:pillar_processor",
        "pillar_trigger_and_replacements": [
            {"trigger": {"Name": "minecraft:yellow_wool"}, "replacement": {"Name": "minecraft:basalt"}},
        ],
        "direction": "downward",
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_vault_processor_missing_loot_table_fails(tmp_path):
    proc = {
        "processor_type": "moogs_structures:vault_randomizing_processor",
        "key_item": "minecraft:trial_key",
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


# ---------- vanilla_loot_swap_processor (MSL 3.1.0+) ----------

def _swap_proc(**overrides) -> dict:
    proc = {
        "processor_type": "moogs_structures:vanilla_loot_swap_processor",
        "modid": "test",
        "vanilla_key": "desert_pyramid",
        "loot_table_mapping": {
            "test:wall_chest": "minecraft:chests/desert_pyramid",
        },
    }
    proc.update(overrides)
    return proc


def test_vanilla_loot_swap_valid_passes(tmp_path):
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([_swap_proc()]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_vanilla_loot_swap_valid_with_seed_strategy_passes(tmp_path):
    _write(tmp_path, "test", "processor_list", "p.json",
           _processor_list([_swap_proc(seed_strategy="randomize")]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_vanilla_loot_swap_bad_seed_strategy_fails(tmp_path):
    _write(tmp_path, "test", "processor_list", "p.json",
           _processor_list([_swap_proc(seed_strategy="shuffle")]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_vanilla_loot_swap_missing_modid_fails(tmp_path):
    proc = _swap_proc()
    del proc["modid"]
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_vanilla_loot_swap_empty_mapping_fails(tmp_path):
    _write(tmp_path, "test", "processor_list", "p.json",
           _processor_list([_swap_proc(loot_table_mapping={})]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


# ---------- conditional_concentric_rings (MSL 3.1.0+) ----------

def _rings(**overrides) -> dict:
    placement = {
        "type": "moogs_structures:conditional_concentric_rings",
        "salt": 12345,
        "distance": 32,
        "spread": 3,
        "preferred_biomes": "#minecraft:stronghold_biased_to",
        "modid": "test",
        "vanilla_key": "stronghold",
        "enabled_count": 128,
        "disabled_count": 26,
    }
    placement.update(overrides)
    return {"structures": [{"structure": "test:s", "weight": 1}], "placement": placement}


def test_conditional_rings_valid_passes(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json", _rings())
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_conditional_rings_distance_out_of_range_fails(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json", _rings(distance=1024))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_conditional_rings_enabled_count_zero_fails(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json", _rings(enabled_count=0))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_conditional_rings_missing_modid_fails(tmp_path):
    data = _rings()
    del data["placement"]["modid"]
    _write(tmp_path, "test", "structure_set", "s.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_conditional_rings_biome_list_passes(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json",
           _rings(preferred_biomes=["minecraft:plains", "minecraft:forest"]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


# ---------- advanced_random_spread 3.1.0 optional fields ----------

def _spread(**overrides) -> dict:
    placement = {
        "type": "moogs_structures:advanced_random_spread",
        "salt": 42,
        "spacing": 20,
        "separation": 4,
    }
    placement.update(overrides)
    return {"structures": [{"structure": "test:s", "weight": 1}], "placement": placement}


def test_advanced_spread_with_spacing_key_and_structure_id_passes(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json",
           _spread(spacing_key="test:s", structure_id="test:s"))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_advanced_spread_bad_structure_id_pattern_fails(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json",
           _spread(structure_id="Not A Valid ID"))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


# ---------- advanced_random_spread when_replacing ----------

def _when_replacing(**overrides) -> dict:
    block = {"modid": "test", "vanilla_key": "fortress", "spacing": 40, "separation": 8}
    block.update(overrides)
    return block


def test_advanced_spread_when_replacing_valid_passes(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json",
           _spread(when_replacing=_when_replacing()))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_advanced_spread_when_replacing_missing_field_fails(tmp_path):
    block = _when_replacing()
    del block["vanilla_key"]
    _write(tmp_path, "test", "structure_set", "s.json", _spread(when_replacing=block))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_advanced_spread_when_replacing_unknown_key_fails(tmp_path, capsys):
    _write(tmp_path, "test", "structure_set", "s.json",
           _spread(when_replacing=_when_replacing(density=3)))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    out = capsys.readouterr().out
    assert not passed
    assert "density" in out


def test_advanced_spread_when_replacing_negative_spacing_fails(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json",
           _spread(when_replacing=_when_replacing(spacing=-1)))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_advanced_spread_when_replacing_non_object_fails(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json", _spread(when_replacing="yes"))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_advanced_spread_when_replacing_modid_not_string_fails(tmp_path):
    _write(tmp_path, "test", "structure_set", "s.json",
           _spread(when_replacing=_when_replacing(modid=7)))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_flood_processor_valid_passes(tmp_path):
    procs = [
        {"processor_type": "moogs_structures:flood_with_water_processor", "flood_level": 62},
        {"processor_type": "moogs_structures:remove_floating_blocks_processor"},
        {"processor_type": "minecraft:rule", "rules": []},
    ]
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list(procs))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_random_replace_probability_out_of_range_fails(tmp_path):
    proc = {
        "processor_type": "moogs_structures:random_replace_with_properties_processor",
        "input_block": "minecraft:stone",
        "output_block": "minecraft:cobblestone",
        "probability": 1.5,
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


# --- MC-version gating of MSL types -----------------------------------------
# MSL registers waterlogging_fix_processor on the 1.20 line only (branches
# 1.20-1.20.4 and 1.20.5-1.20.6) and dropped it at 1.21; trial_spawner and vault
# processors are the mirror case, 1.21+ only. A type is "unknown" only when no
# targeted MC version registers it.

_MC_1_20 = ["1.20", "1.20.1", "1.20.2", "1.20.4", "1.20.5", "1.20.6"]
_MC_1_21 = ["1.21", "1.21.1"]
_MC_SPANNING = ["1.20.6", "1.21", "1.21.1"]

_WATERLOGGING = {"processor_type": "moogs_structures:waterlogging_fix_processor"}


def test_waterlogging_processor_passes_on_1_20_repo(tmp_path, monkeypatch):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([_WATERLOGGING]))
    passed, summary = mod.run(FakeContext("test", _MC_1_20, tmp_path))
    assert passed, summary


def test_waterlogging_processor_fails_on_1_21_repo(tmp_path, monkeypatch):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([_WATERLOGGING]))
    passed, summary = mod.run(FakeContext("test", _MC_1_21, tmp_path))
    assert not passed
    assert summary == "1 files, 1 error(s)"


def test_waterlogging_processor_passes_on_repo_spanning_1_21(tmp_path, monkeypatch):
    # 1.20.6 is targeted, and MSL registers it there -- so it is real content.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([_WATERLOGGING]))
    passed, summary = mod.run(FakeContext("test", _MC_SPANNING, tmp_path))
    assert passed, summary


def test_trial_spawner_processor_fails_on_1_20_repo(tmp_path, monkeypatch):
    # Mirror case: added at 1.21, so it is dead data on a 1.20-only branch.
    stub_registries(monkeypatch)
    proc = {
        "processor_type": "moogs_structures:trial_spawner_randomizing_processor",
        "normal_config": "minecraft:trial_chamber/normal",
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", _MC_1_20, tmp_path))
    assert not passed


def test_trial_spawner_processor_passes_on_1_21_repo(tmp_path, monkeypatch):
    stub_registries(monkeypatch)
    proc = {
        "processor_type": "moogs_structures:trial_spawner_randomizing_processor",
        "normal_config": "minecraft:trial_chamber/normal",
    }
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, summary = mod.run(FakeContext("test", _MC_1_21, tmp_path))
    assert passed, summary


def test_unknown_processor_type_still_fails_on_1_20_repo(tmp_path, monkeypatch):
    # Guards the over-correction: version gating must not turn the typo catcher off.
    stub_registries(monkeypatch)
    proc = {"processor_type": "moogs_structures:waterlogging_fix_processorr"}
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([proc]))
    passed, _ = mod.run(FakeContext("test", _MC_1_20, tmp_path))
    assert not passed


def test_version_gating_is_silent_without_a_version_map(tmp_path, monkeypatch):
    # No version map (offline, or an unrecognised target version) => never gate,
    # because a wrong guess here is exactly the false positive being fixed.
    from core import mcmeta as _mcmeta
    monkeypatch.setattr(_mcmeta, "fetch_version_entries", lambda cache_dir, refresh: [])
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([_WATERLOGGING]))
    passed, summary = mod.run(FakeContext("test", _MC_1_21, tmp_path))
    assert passed, summary


def test_version_gating_is_silent_when_a_target_version_is_unmapped(tmp_path, monkeypatch):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([_WATERLOGGING]))
    passed, summary = mod.run(FakeContext("test", ["1.21", "26.2"], tmp_path))
    assert passed, summary


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


# --- MSL types by MSL release ------------------------------------------------------------

def _msl_mod(root: Path, fabric: str) -> None:
    res = root / "src" / "main" / "resources"
    res.mkdir(parents=True, exist_ok=True)
    (res / "fabric.mod.json").write_text(json.dumps({"id": "test", "depends": {"moogs_structures": fabric}}),
                                         encoding="utf-8")


TRIAL_PROC = {"processors": [{"processor_type": "moogs_structures:trial_spawner_randomizing_processor",
                              "normal_config": "test:arena/normal"}]}


def test_a_type_newer_than_the_msl_the_mod_allows_fails(tmp_path, monkeypatch, capsys):
    # trial_spawner_randomizing_processor first shipped in MSL 3.0.0; with "*" a
    # 1.21.1 player can run MSL 1.0.0, which does not register it.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "mobs.json", TRIAL_PROC)
    _msl_mod(tmp_path, "*")
    passed, summary = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "first shipped in MSL 3.0.0" in out
    assert "Raise the moogs_structures minimum to 3.0.0" in out


def test_a_minimum_that_covers_the_type_passes(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "mobs.json", TRIAL_PROC)
    _msl_mod(tmp_path, ">=3.0.0")
    passed, _ = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out


@pytest.mark.parametrize("ptype", ["follow_floor_processor", "rail_slope_processor",
                                   "rail_rotation_processor"])
def test_the_follow_floor_and_rail_processors_need_msl_4_0_0(tmp_path, monkeypatch, capsys, ptype):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json",
           _processor_list([{"processor_type": f"moogs_structures:{ptype}"}]))
    _msl_mod(tmp_path, ">=3.4.0")
    passed, _ = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert f"moogs_structures:{ptype} first shipped in MSL 4.0.0" in out, out
    assert "Raise the moogs_structures minimum to 4.0.0" in out, out
    # A 4.0.0 minimum is not judged here: no MSL 4.0.0 build is published yet, which
    # check_data_formats reports as a minimum no build meets.
    root = tmp_path / "min"
    _write(root, "test", "processor_list", "p.json", _processor_list([{"processor_type": f"moogs_structures:{ptype}"}]))
    _msl_mod(root, ">=4.0.0")
    passed, _ = mod.run(FakeContext("test", ["1.21", "1.21.1"], root))
    assert passed, capsys.readouterr().out


def test_the_hanging_entity_anchor_needs_msl_3_1_2(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([ANCHOR]))
    _msl_mod(tmp_path, ">=3.1.0")
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "moogs_structures:hanging_entity_anchor_processor first shipped in MSL 3.1.2" in out, out
    root = tmp_path / "min"
    _write(root, "test", "processor_list", "p.json", _processor_list([ANCHOR]))
    _msl_mod(root, ">=3.1.2")
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], root))
    assert passed, capsys.readouterr().out


def test_types_in_the_oldest_msl_tag_have_no_floor(tmp_path, monkeypatch, capsys):
    # The generic jigsaw structure is already in MSL's oldest tag (2.0.0); MSL 1.x
    # is not in git, so nothing is assumed about it and "*" passes.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "structure", "s.json", _generic_structure())
    _write(tmp_path, "test", "template_pool", "start.json", _pool([
        {"element_type": "minecraft:single_pool_element", "location": "test:start",
         "projection": "rigid", "processors": "minecraft:empty"}]))
    _msl_mod(tmp_path, "*")
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out


SPREAD_SET = {"structures": [{"structure": "test:fort", "weight": 1}],
              "placement": {"type": "moogs_structures:advanced_random_spread", "salt": 1, "spacing": 116,
                            "separation": 76, "when_replacing": {"modid": "test", "vanilla_key": "fortress",
                                                                 "spacing": 30, "separation": 12}}}


def test_a_field_newer_than_the_msl_the_mod_allows_fails(tmp_path, monkeypatch, capsys):
    # advanced_random_spread is in MSL 2.0.0, but its when_replacing arrived in
    # 3.3.0: MSL 3.0.0 skips it, so the replacement spacing is never used.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "structure_set", "fort.json", SPREAD_SET)
    _msl_mod(tmp_path, ">=3.0.0")
    passed, _ = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "moogs_structures:advanced_random_spread `when_replacing` first read by MSL 3.3.0" in out
    assert "structure_set/fort.json lose what it sets there" in out


def test_a_minimum_that_covers_the_field_passes(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "structure_set", "fort.json", SPREAD_SET)
    _msl_mod(tmp_path, ">=3.3.0")
    passed, _ = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out


def test_a_pool_element_field_is_gated_too(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([
        {"element_type": "moogs_structures:mirroring_single_pool_element", "location": "test:start",
         "projection": "rigid", "processors": "minecraft:empty", "mirror": "FRONT_BACK"}]))
    _msl_mod(tmp_path, "*")
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out
    _write(tmp_path, "test", "template_pool", "start.json", _pool([
        {"element_type": "moogs_structures:mirroring_single_pool_element", "location": "test:start",
         "projection": "rigid", "processors": "minecraft:empty", "mirror": "FRONT_BACK",
         "enhanced_terrain_adaptation": {"kernel_size": 0, "kernel_distance": 0, "top": "none",
                                         "bottom": "none"}}]))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "mirroring_single_pool_element `enhanced_terrain_adaptation` first read by MSL 3.0.0" in out


VERSIONED_WITH_CARVING = {"element_type": "moogs_structures:versioned_single_pool_element",
                          "location": "test:start", "projection": "rigid", "processors": "minecraft:empty",
                          "enhanced_terrain_adaptation": {"kernel_size": 4, "kernel_distance": 2,
                                                          "top": "carve", "bottom": "none"}}


def test_per_piece_carving_on_1_20_needs_msl_3_4_2(tmp_path, monkeypatch, capsys):
    # MSL's 1.21 lines read a versioned element's own carving from 3.0.0, its 1.20 lines
    # only from 3.4.2: with 3.3.0 allowed, the 1.20 pieces lose it and 1.21 keeps it.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([VERSIONED_WITH_CARVING]))
    _msl_mod(tmp_path, ">=3.3.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.20.6", "1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert ("versioned_single_pool_element `enhanced_terrain_adaptation` first read by MSL 3.0.0 "
            "(3.4.2 on its 1.20 lines)") in out
    assert "on 1.20.4-1.20.6 this mod allows MSL 3.3" in out
    assert "Raise the moogs_structures minimum to 3.4.2." in out


def test_per_piece_carving_on_1_20_passes_with_msl_3_4_2(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([VERSIONED_WITH_CARVING]))
    _msl_mod(tmp_path, ">=3.4.2")
    passed, summary = mod.run(FakeContext("test", ["1.20.4", "1.20.6", "1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert passed and "warning" not in summary, out
    assert "[WARN]" not in out and "first read by MSL" not in out


def test_per_piece_carving_on_1_21_needs_msl_3_0_0_only(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([VERSIONED_WITH_CARVING]))
    _msl_mod(tmp_path, ">=3.3.0")
    passed, summary = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert passed and "warning" not in summary and "[WARN]" not in out, out


def test_a_low_minimum_on_both_lines_is_raised_to_the_1_20_release(tmp_path, monkeypatch, capsys):
    # (1.1.0 is the first MSL with the versioned element itself.)
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([VERSIONED_WITH_CARVING]))
    _msl_mod(tmp_path, ">=1.1.0-0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "first read by MSL 3.0.0 (3.4.2 on its 1.20 lines)" in out
    assert "on 1.20.4-1.21.1 this mod allows" in out and "minimum to 3.4.2." in out



VERSIONED_POOL = {"element_type": "moogs_structures:versioned_single_pool_element", "location": "test:start",
                  "projection": "rigid", "processors": "minecraft:empty"}


def test_the_versioned_element_needs_msl_1_1_0(tmp_path, monkeypatch, capsys):
    # MSL 1.0.0 and 1.0.1 do not register it ("Failed to load registries" on MES with "*").
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([VERSIONED_POOL]))
    _msl_mod(tmp_path, "*")
    passed, _ = mod.run(FakeContext("test", ["1.21", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "versioned_single_pool_element first shipped in MSL 1.1.0" in out
    assert "`>=1.1.0-0` in fabric.mod.json and quilt.mod.json" in out


def test_the_versioned_element_with_the_fabric_spelling_passes(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "start.json", _pool([VERSIONED_POOL]))
    _msl_mod(tmp_path, ">=1.1.0-0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.20.6", "1.21", "1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out


# --- MSL 4.0.0 adaptation areas and "none" ---------------------------------------------

def _area_element(**overrides) -> dict:
    element = {"element_type": "moogs_structures:versioned_single_pool_element", "location": "test:start",
               "projection": "rigid", "processors": "minecraft:empty",
               "adaptation_area": {"columns": [{"x": [2, 5], "z": [0, 3]}], "outside_follows_ground": True}}
    element.update(overrides)
    return element


def test_adaptation_areas_and_none_pass(tmp_path, capsys):
    # Both ways of naming the columns, and "none" in every place MSL takes an adaptation.
    _write(tmp_path, "test", "template_pool", "p.json", _pool([
        _area_element(),
        _area_element(adaptation_area={"footprint": {"layers": 2, "blocks": "#minecraft:logs", "margin": 1}},
                      enhanced_terrain_adaptation="none"),
        {"element_type": "moogs_structures:mirroring_single_pool_element", "location": "test:a",
         "projection": "rigid", "mirror": "FRONT_BACK", "enhanced_terrain_adaptation": "none"},
        {"element_type": "moogs_structures:legacy_ocean_bottom_single_pool_element", "location": "test:b",
         "projection": "rigid", "enhanced_terrain_adaptation": "none"}]))
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(enhanced_terrain_adaptation="none"))
    _write(tmp_path, "test", "structure", "n.json", _generic_structure(
        type="moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
        land_search_direction="HIGHEST_LAND", enhanced_terrain_adaptation="none"))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out


@pytest.mark.parametrize("change, message", [
    ({"adaptation_area": {"columns": [{"x": [0, 1], "z": [0, 1]}], "footprint": {}}},
     'needs exactly one of "columns" or "footprint"'),
    ({"adaptation_area": {"outside_follows_ground": True}}, 'needs exactly one of "columns" or "footprint"'),
    ({"adaptation_area": {"columns": [{"x": [5, 2], "z": [0, 3]}]}}, "and 5 is more than 2"),
    ({"projection": "terrain_matching"}, 'needs "projection": "rigid"'),
    ({"adaptation_area": {"columns": []}}, "should be non-empty"),
    ({"adaptation_area": {"columns": [{"x": [1], "z": [0, 3]}]}}, "is too short"),
    ({"adaptation_area": {"footprint": {"layers": 65}}}, "greater than the maximum of 64"),
    ({"adaptation_area": {"footprint": {"margin": 17}}}, "greater than the maximum of 16"),
    ({"adaptation_area": {"footprint": {"blocks": "minecraft:logs"}}}, "does not match"),
    ({"enhanced_terrain_adaptation": "off"}, "'off' does not match '^none$'"),
])
def test_adaptation_area_shapes_msl_refuses_fail(tmp_path, capsys, change, message):
    _write(tmp_path, "test", "template_pool", "p.json", _pool([_area_element(**change)]))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert message in out, out


def test_terrain_adaptation_strings_other_than_none_fail_on_structures(tmp_path, capsys):
    # The generic jigsaw's adaptation was not checked at all before; now it takes the same values.
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(enhanced_terrain_adaptation="carve"))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed and "'carve' does not match '^none$'" in out, out


def test_an_adaptation_area_needs_msl_4_0_0(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "p.json", _pool([_area_element()]))
    _msl_mod(tmp_path, ">=3.4.0")
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "versioned_single_pool_element `adaptation_area` first read by MSL 4.0.0" in out, out
    assert "Raise the moogs_structures minimum to 4.0.0" in out, out
    # No MSL 4.0.0 build is published yet: check_data_formats reports that minimum.
    root = tmp_path / "min"
    _write(root, "test", "template_pool", "p.json", _pool([_area_element()]))
    _msl_mod(root, ">=4.0.0")
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], root))
    assert passed, capsys.readouterr().out


def test_terrain_adaptation_none_needs_msl_4_0_0(tmp_path, monkeypatch, capsys):
    # From 1.20.5 an older MSL refuses the string; on 1.20-1.20.4 its DataFixerUpper drops it.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "structure", "s.json", _generic_structure(enhanced_terrain_adaptation="none"))
    _msl_mod(tmp_path, ">=3.4.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.20.6", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert ('moogs_structures_generic_jigsaw_structure `enhanced_terrain_adaptation: "none"` '
            "first accepted by MSL 4.0.0") in out, out
    assert "structure/s.json fail to load on 1.20.6-1.21.1" in out, out
    assert "on 1.20.4 the field is dropped without a word" in out, out
    root = tmp_path / "min"
    _write(root, "test", "structure", "s.json", _generic_structure(enhanced_terrain_adaptation="none"))
    _msl_mod(root, ">=4.0.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.20.6", "1.21.1"], root))
    assert passed, capsys.readouterr().out


def test_none_on_a_versioned_element_before_msl_3_4_2_is_skipped_on_1_20(tmp_path, monkeypatch, capsys):
    # Before 3.4.2 MSL's 1.20 builds skip a versioned element's own adaptation whole, so
    # its "none" is dropped on 1.20.6 rather than failing the file, as it does on 1.21.1.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "template_pool", "p.json",
           _pool([dict(VERSIONED_WITH_CARVING, enhanced_terrain_adaptation="none")]))
    _msl_mod(tmp_path, ">=3.3.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.6", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert ('versioned_single_pool_element `enhanced_terrain_adaptation: "none"` '
            "first accepted by MSL 4.0.0") in out, out
    assert "template_pool/p.json fail to load on 1.21.1" in out, out
    assert "on 1.20.6 the field is dropped without a word" in out, out


# --- MSL 4.1.0 structures hanging from ceilings ----------------------------------------

def _hanging_structure(**overrides) -> dict:
    return _generic_structure(**{"type": "moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
                                 "land_search_direction": "CEILING", "ledge_offset_y": 2, **overrides})


CEILING_PROC = {"processor_type": "moogs_structures:follow_ceiling_processor"}


def test_hanging_structures_and_the_follow_ceiling_processor_pass(tmp_path, capsys):
    # Registered on every Minecraft line, with follow_floor_processor's fields.
    _write(tmp_path, "test", "structure", "s.json", _hanging_structure(cannot_spawn_in_liquid=True))
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([
        CEILING_PROC, {**CEILING_PROC, "search_range": 64, "offset": 3}, {**CEILING_PROC, "search_range": 1}]))
    passed, _ = mod.run(FakeContext("test", ["1.20.1", "1.21.1"], tmp_path))
    assert passed, capsys.readouterr().out


@pytest.mark.parametrize("change, message", [
    ({"search_range": 0}, "less than the minimum of 1"),
    ({"search_range": 65}, "greater than the maximum of 64"),
    ({"offset": 1.5}, "is not of type 'integer'"),
])
def test_follow_ceiling_fields_msl_refuses_fail(tmp_path, capsys, change, message):
    # StrictOptionalField: a value out of range fails the list instead of reading as the default.
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([{**CEILING_PROC, **change}]))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed and message in out, out


def test_a_land_search_direction_msl_cannot_read_fails(tmp_path, capsys):
    # StringRepresentable.fromEnum reads the upper-case names only.
    _write(tmp_path, "test", "structure", "s.json", _hanging_structure(land_search_direction="ceiling"))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed and "s.json @ land_search_direction" in out, out


def test_the_follow_ceiling_processor_needs_msl_4_1_0(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "processor_list", "p.json", _processor_list([CEILING_PROC]))
    _msl_mod(tmp_path, ">=3.4.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.1", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "moogs_structures:follow_ceiling_processor first shipped in MSL 4.1.0" in out, out
    assert "Raise the moogs_structures minimum to 4.1.0" in out, out
    root = tmp_path / "min"
    _write(root, "test", "processor_list", "p.json", _processor_list([CEILING_PROC]))
    _msl_mod(root, ">=4.1.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.1", "1.21.1"], root))
    assert passed, capsys.readouterr().out


def test_hanging_from_a_ceiling_needs_msl_4_1_0_on_every_version(tmp_path, monkeypatch, capsys):
    # land_search_direction is required, so an older MSL refuses the structure on 1.20-1.20.4 too.
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "structure", "s.json", _hanging_structure())
    _msl_mod(tmp_path, ">=3.4.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert ('moogs_structures_generic_nether_jigsaw_structure `land_search_direction: "CEILING"` '
            "first accepted by MSL 4.1.0") in out, out
    assert "structure/s.json fail to load on 1.20.4-1.21.1" in out, out
    assert "dropped without a word" not in out, out
    root = tmp_path / "min"
    _write(root, "test", "structure", "s.json", _hanging_structure())
    _msl_mod(root, ">=4.1.0")
    passed, _ = mod.run(FakeContext("test", ["1.20.4", "1.21.1"], root))
    assert passed, capsys.readouterr().out


# --- salts above the int range ---------------------------------------------------------

def _salted_set(salt: int) -> dict:
    return {"structures": [{"structure": "test:tree", "weight": 1}],
            "placement": {"type": "minecraft:random_spread", "salt": salt, "spacing": 30, "separation": 12}}


def test_a_salt_above_the_int_range_warns_with_the_salt_minecraft_uses(tmp_path, capsys):
    # MVS's dark oak dead tree: Gson keeps the low 32 bits of 22201927364.
    _write(tmp_path, "test", "structure_set", "tree.json", _salted_set(22201927364))
    passed, summary = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert passed and "1 warning(s)" in summary, out
    assert "[WARN] structure_set/tree.json @ placement > salt" in out, out
    assert "22201927364 is above 2147483647" in out and "with salt 727090884 instead" in out, out


def test_a_salt_that_comes_out_negative_fails(tmp_path, capsys):
    _write(tmp_path, "test", "structure_set", "tree.json", _salted_set(2 ** 31))
    passed, _ = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    out = capsys.readouterr().out
    assert not passed and "reads -2147483648 and refuses the set" in out, out


def test_the_largest_int_salt_is_quiet(tmp_path, capsys):
    _write(tmp_path, "test", "structure_set", "tree.json", _salted_set(2 ** 31 - 1))
    passed, summary = mod.run(FakeContext("test", ["1.21.1"], tmp_path))
    assert passed and "warning" not in summary, capsys.readouterr().out


# --- MSL 4.0.0: a structure that generates only on some Minecraft versions -----------------

@pytest.mark.parametrize("gate, ok", [("1.21.4-26.3", True), ("1.21.4", True), (" 1.21.4 - 26.3 ", True),
                                      ("26.3-1.21.4", False), ("1.21.x", False), ("1.21.4-", False)])
def test_a_structures_mc_versions_must_be_a_range_msl_reads(tmp_path, capsys, gate, ok):
    for i, base in enumerate(({}, NETHER)):
        _write(tmp_path, "test", "structure", f"s{i}.json",
               _generic_structure(**base, mc_versions=gate, y_allowance={"min_y_allowed": 20}))
    passed, _ = mod.run(FakeContext("test", ["1.21.4", "26.3"], tmp_path))
    out = capsys.readouterr().out
    assert passed == ok, out
    if gate == "26.3-1.21.4":
        assert "s0.json @ mc_versions\n    '26.3-1.21.4' has its minimum above its maximum" in out


def test_a_structures_mc_versions_needs_msl_4_0_0(tmp_path, monkeypatch, capsys):
    stub_registries(monkeypatch)
    _write(tmp_path, "test", "structure", "s.json",
           _generic_structure(mc_versions="1.21.4-26.3", y_allowance={"min_y_allowed": 20}))
    _msl_mod(tmp_path, ">=3.4.0")
    passed, _ = mod.run(FakeContext("test", ["1.21.1", "1.21.4"], tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert "moogs_structures:moogs_structures_generic_jigsaw_structure `mc_versions` first read by MSL 4.0.0" in out
