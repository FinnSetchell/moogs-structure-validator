"""Tests for check_msl_placements_and_processors."""
from __future__ import annotations

import json
from pathlib import Path

from checks import check_msl_placements_and_processors as mod
from tests.nbt_helpers import (
    FakeContext,
    block_entry,
    save,
    stub_registries,
    structure_nbt,
)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _ns_data(root: Path, ns: str = "test") -> Path:
    return root / "src" / "main" / "resources" / "data" / ns


def _write_manifest(root: Path, presets: list[dict]) -> None:
    _write_json(_ns_data(root) / "moogs_structures" / "replace_vanilla.json",
                {"presets": presets})


def _write_structure(root: Path, id_: str) -> None:
    ns, _, path = id_.partition(":")
    _write_json(_ns_data(root, ns) / "worldgen" / "structure" / f"{path}.json",
                {"type": "test"})


def _write_set(root: Path, id_: str, placement: dict,
               structures: list[dict] | None = None) -> None:
    ns, _, path = id_.partition(":")
    _write_json(_ns_data(root, ns) / "worldgen" / "structure_set" / f"{path}.json", {
        "structures": structures if structures is not None else [{"structure": id_, "weight": 1}],
        "placement": placement,
    })


def _write_processor_list(root: Path, id_: str, processors: list[dict]) -> None:
    ns, _, path = id_.partition(":")
    _write_json(_ns_data(root, ns) / "worldgen" / "processor_list" / f"{path}.json",
                {"processors": processors})


def _write_pool_with_processors(root: Path, id_: str, processor_list_id: str) -> None:
    ns, _, path = id_.partition(":")
    _write_json(_ns_data(root, ns) / "worldgen" / "template_pool" / f"{path}.json", {
        "fallback": "minecraft:empty",
        "elements": [{
            "weight": 1,
            "element": {
                "element_type": "minecraft:single_pool_element",
                "location": f"{ns}:piece",
                "projection": "rigid",
                "processors": processor_list_id,
            },
        }],
    })


def _ctx(root: Path) -> FakeContext:
    return FakeContext("test", ["1.21"], root)


def _write_container_nbt(root: Path, loot_table: str) -> None:
    import nbtlib
    from nbtlib import Compound, Int, String
    from tests.nbt_helpers import _int_list
    palette = [
        Compound({"Name": String("minecraft:air")}),
        Compound({"Name": String("minecraft:chest")}),
    ]
    chest_nbt = Compound({"LootTable": String(loot_table)})
    block = block_entry(1, pos=(0, 0, 0), nbt=chest_nbt)
    nbt_file = structure_nbt(3953, blocks=[block], palette=palette)
    path = _ns_data(root) / "structure" / "piece.nbt"
    save(nbt_file, path)


# ---------- conditional_concentric_rings ----------

def _rings(**overrides) -> dict:
    p = {
        "type": "moogs_structures:conditional_concentric_rings",
        "salt": 1, "distance": 32, "spread": 3,
        "preferred_biomes": "#minecraft:stronghold_biased_to",
        "modid": "test", "vanilla_key": "stronghold",
        "enabled_count": 128, "disabled_count": 26,
    }
    p.update(overrides)
    return p


def _stronghold_preset(replacement: str = "test:my_stronghold") -> dict:
    return {
        "id": "replace_stronghold",
        "replacements": [{
            "vanilla_key": "stronghold",
            "vanilla_structure": "minecraft:stronghold",
            "replacement_structure": replacement,
        }],
    }


def test_conditional_rings_matching_preset_passes(tmp_path):
    _write_structure(tmp_path, "test:my_stronghold")
    _write_manifest(tmp_path, [_stronghold_preset()])
    _write_set(tmp_path, "test:stronghold_set", _rings())
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_conditional_rings_no_matching_preset_fails(tmp_path):
    _write_manifest(tmp_path, [])
    _write_set(tmp_path, "test:stronghold_set", _rings())
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_conditional_rings_missing_manifest_fails_when_own_ns(tmp_path):
    _write_set(tmp_path, "test:stronghold_set", _rings())
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_conditional_rings_other_modid_warns_not_errors(tmp_path, capsys):
    _write_manifest(tmp_path, [])
    _write_set(tmp_path, "test:stronghold_set", _rings(modid="othermod"))
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "WARN" in out


def test_conditional_rings_enabled_lt_disabled_warns(tmp_path, capsys):
    _write_structure(tmp_path, "test:my_stronghold")
    _write_manifest(tmp_path, [_stronghold_preset()])
    _write_set(tmp_path, "test:stronghold_set", _rings(enabled_count=1, disabled_count=100))
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "WARN" in out and "inverted" in out


def test_conditional_rings_structure_id_missing_json_fails(tmp_path):
    _write_manifest(tmp_path, [_stronghold_preset("test:my_stronghold")])
    _write_structure(tmp_path, "test:my_stronghold")
    _write_set(tmp_path, "test:stronghold_set", _rings(structure_id="test:missing"))
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


# ---------- advanced_random_spread ----------

def _spread(**overrides) -> dict:
    p = {
        "type": "moogs_structures:advanced_random_spread",
        "salt": 1, "spacing": 20, "separation": 4,
    }
    p.update(overrides)
    return p


def test_advanced_spread_no_structure_id_passes(tmp_path):
    _write_set(tmp_path, "test:s", _spread())
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_advanced_spread_structure_id_resolves_and_matches_set_passes(tmp_path):
    _write_structure(tmp_path, "test:s")
    _write_set(tmp_path, "test:set", _spread(structure_id="test:s"),
               structures=[{"structure": "test:s", "weight": 1}])
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_advanced_spread_structure_id_not_in_set_fails(tmp_path):
    _write_structure(tmp_path, "test:s")
    _write_structure(tmp_path, "test:other")
    _write_set(tmp_path, "test:set", _spread(structure_id="test:other"),
               structures=[{"structure": "test:s", "weight": 1}])
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_advanced_spread_structure_id_missing_json_fails(tmp_path):
    _write_set(tmp_path, "test:set", _spread(structure_id="test:missing"),
               structures=[{"structure": "test:missing", "weight": 1}])
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


# ---------- vanilla_loot_swap_processor ----------

def _swap(**overrides) -> dict:
    p = {
        "processor_type": "moogs_structures:vanilla_loot_swap_processor",
        "modid": "test",
        "vanilla_key": "desert_pyramid",
        "loot_table_mapping": {"test:wall_chest": "minecraft:chests/desert_pyramid"},
    }
    p.update(overrides)
    return p


def _pyramid_preset(replacement: str = "test:my_pyramid") -> dict:
    return {
        "id": "replace_pyramid",
        "replacements": [{
            "vanilla_key": "desert_pyramid",
            "vanilla_structure": "minecraft:desert_pyramid",
            "replacement_structure": replacement,
        }],
    }


def test_swap_valid_and_wired_passes(tmp_path, monkeypatch):
    stub_registries(monkeypatch)
    # Vanilla loot table registry contains our TO id via monkeypatch below.
    from checks import check_msl_placements_and_processors as ppmod
    monkeypatch.setattr(ppmod, "_load_vanilla_loot_tables",
                        lambda ctx: {"minecraft:chests/desert_pyramid"})
    _write_structure(tmp_path, "test:my_pyramid")
    _write_manifest(tmp_path, [_pyramid_preset()])
    _write_processor_list(tmp_path, "test:swap_loot", [_swap()])
    _write_pool_with_processors(tmp_path, "test:pyramid_pool", "test:swap_loot")
    _write_container_nbt(tmp_path, "test:wall_chest")
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_swap_no_preset_fails(tmp_path, monkeypatch):
    from checks import check_msl_placements_and_processors as ppmod
    monkeypatch.setattr(ppmod, "_load_vanilla_loot_tables",
                        lambda ctx: {"minecraft:chests/desert_pyramid"})
    _write_manifest(tmp_path, [])
    _write_processor_list(tmp_path, "test:swap_loot", [_swap()])
    _write_pool_with_processors(tmp_path, "test:p", "test:swap_loot")
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_swap_unwired_processor_list_fails(tmp_path, monkeypatch):
    from checks import check_msl_placements_and_processors as ppmod
    monkeypatch.setattr(ppmod, "_load_vanilla_loot_tables",
                        lambda ctx: {"minecraft:chests/desert_pyramid"})
    _write_structure(tmp_path, "test:my_pyramid")
    _write_manifest(tmp_path, [_pyramid_preset()])
    _write_processor_list(tmp_path, "test:swap_loot", [_swap()])
    # Deliberately do not write a template_pool that references the list.
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_swap_to_not_a_vanilla_loot_table_fails(tmp_path, monkeypatch):
    from checks import check_msl_placements_and_processors as ppmod
    monkeypatch.setattr(ppmod, "_load_vanilla_loot_tables",
                        lambda ctx: {"minecraft:chests/desert_pyramid"})
    _write_structure(tmp_path, "test:my_pyramid")
    _write_manifest(tmp_path, [_pyramid_preset()])
    bad = _swap()
    bad["loot_table_mapping"] = {"test:wall_chest": "minecraft:not_a_real_table"}
    _write_processor_list(tmp_path, "test:swap_loot", [bad])
    _write_pool_with_processors(tmp_path, "test:p", "test:swap_loot")
    _write_container_nbt(tmp_path, "test:wall_chest")
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_swap_from_key_not_used_by_any_container_warns(tmp_path, monkeypatch, capsys):
    from checks import check_msl_placements_and_processors as ppmod
    monkeypatch.setattr(ppmod, "_load_vanilla_loot_tables",
                        lambda ctx: {"minecraft:chests/desert_pyramid"})
    _write_structure(tmp_path, "test:my_pyramid")
    _write_manifest(tmp_path, [_pyramid_preset()])
    _write_processor_list(tmp_path, "test:swap_loot", [_swap()])
    _write_pool_with_processors(tmp_path, "test:p", "test:swap_loot")
    # No container NBT written -> FROM key is dead.
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed  # warn only
    assert "dead mapping" in out
