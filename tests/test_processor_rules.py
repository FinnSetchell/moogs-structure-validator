"""Tests for MSL registry cross-checks in check_processor_rules."""
from __future__ import annotations

import json
from pathlib import Path

from tests.nbt_helpers import FakeContext

from checks import check_processor_rules as mod


def _write_processor_list(root: Path, namespace: str, name: str, processors: list[dict]) -> None:
    path = (root / "src" / "main" / "resources" / "data" / namespace
            / "worldgen" / "processor_list" / name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"processors": processors}, f)


def _ctx(root: Path, **registries) -> FakeContext:
    ctx = FakeContext("test", ["1.21"], root)
    ctx.valid_blocks = registries.get("blocks", set())
    ctx.valid_items = registries.get("items", set())
    ctx.valid_entities = registries.get("entities", set())
    return ctx


def test_spawner_unknown_entity_fails(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:spawner_randomizing_processor",
        "weighted_entities": [{"entity": "minecraft:zombei", "weight": 1}],
    }])
    passed, summary = mod.run(_ctx(tmp_path, entities={"minecraft:zombie"}))
    assert not passed
    assert "zombei" in summary or "invalid" in summary


def test_spawner_known_entity_passes(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:spawner_randomizing_processor",
        "weighted_entities": [{"entity": "minecraft:zombie", "weight": 1}],
    }])
    passed, _ = mod.run(_ctx(tmp_path, entities={"minecraft:zombie"}))
    assert passed


def test_spawner_inverted_delays_fails(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:spawner_randomizing_processor",
        "weighted_entities": [{"entity": "minecraft:zombie", "weight": 1}],
        "min_spawn_delay": 800,
        "max_spawn_delay": 200,
    }])
    passed, _ = mod.run(_ctx(tmp_path, entities={"minecraft:zombie"}))
    assert not passed


def test_vault_unknown_key_item_fails(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:vault_randomizing_processor",
        "loot_table": "minecraft:chests/trial_chambers/reward",
        "key_item": "minecraft:trail_key",
    }])
    passed, _ = mod.run(_ctx(tmp_path, items={"minecraft:trial_key"}))
    assert not passed


def test_vault_local_loot_table_missing_fails(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:vault_randomizing_processor",
        "loot_table": "test:chests/vault_reward",
    }])
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_vault_local_loot_table_present_passes(tmp_path):
    loot = (tmp_path / "src" / "main" / "resources" / "data" / "test"
            / "loot_table" / "chests" / "vault_reward.json")
    loot.parent.mkdir(parents=True, exist_ok=True)
    loot.write_text("{}", encoding="utf-8")
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:vault_randomizing_processor",
        "loot_table": "test:chests/vault_reward",
    }])
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_vault_foreign_loot_table_skipped(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:vault_randomizing_processor",
        "loot_table": "minecraft:chests/trial_chambers/reward",
    }])
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_trial_spawner_local_config_missing_fails(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "moogs_structures:trial_spawner_randomizing_processor",
        "normal_config": "test:spawners/breeze",
    }])
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_unknown_block_id_fails(tmp_path):
    _write_processor_list(tmp_path, "test", "p.json", [{
        "processor_type": "minecraft:rule",
        "rules": [{
            "output_state": {"Name": "minecraft:cobblestone"},
        }],
    }])
    passed, _ = mod.run(_ctx(tmp_path, blocks={"minecraft:stone"}))
    assert not passed


def test_unparseable_file_fails(tmp_path):
    path = (tmp_path / "src" / "main" / "resources" / "data" / "test"
            / "worldgen" / "processor_list" / "broken.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed
