"""Tests for check_spawn_counts (msl_pieces_spawn_counts and _additions)."""
from __future__ import annotations

import json
from pathlib import Path

from tests.nbt_helpers import FakeContext

from checks import check_spawn_counts as mod


def _ns_root(root: Path, namespace: str = "test") -> Path:
    return root / "src" / "main" / "resources" / "data" / namespace


def _write_counts(root: Path, rel: str, data: dict,
                  dir_name: str = "msl_pieces_spawn_counts") -> None:
    path = _ns_root(root) / dir_name / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _write_structure(root: Path, rel: str) -> None:
    path = _ns_root(root) / "worldgen" / "structure" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def _write_nbt(root: Path, rel: str) -> None:
    path = _ns_root(root) / "structure" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _valid_counts(piece: str = "test:tower/turret") -> dict:
    return {"pieces_spawn_counts": [{
        "nbt_piece_name": piece,
        "always_spawn_this_many": 1,
        "never_spawn_more_than_this_many": 3,
        "minimum_distance_from_center_piece": 0,
    }]}


def test_no_files_passes(tmp_path):
    passed, summary = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed
    assert "no spawn count" in summary


def test_valid_file_passes(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_nbt(tmp_path, "tower/turret.nbt")
    _write_counts(tmp_path, "tower.json", _valid_counts())
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_missing_structure_fails(tmp_path):
    _write_nbt(tmp_path, "tower/turret.nbt")
    _write_counts(tmp_path, "tower.json", _valid_counts())
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_missing_piece_nbt_fails(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_counts(tmp_path, "tower.json", _valid_counts("test:tower/missing"))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_foreign_piece_namespace_skipped(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_counts(tmp_path, "tower.json", _valid_counts("othermod:tower/turret"))
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_always_greater_than_never_fails(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_nbt(tmp_path, "tower/turret.nbt")
    data = {"pieces_spawn_counts": [{
        "nbt_piece_name": "test:tower/turret",
        "always_spawn_this_many": 5,
        "never_spawn_more_than_this_many": 3,
    }]}
    _write_counts(tmp_path, "tower.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_missing_counts_list_fails(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_counts(tmp_path, "tower.json", {"piece_spawn_counts": []})
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_unknown_field_fails(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_nbt(tmp_path, "tower/turret.nbt")
    data = {"pieces_spawn_counts": [{
        "nbt_piece_name": "test:tower/turret",
        "never_spawn_more_then_this_many": 3,
    }]}
    _write_counts(tmp_path, "tower.json", data)
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_additions_dir_validated_too(tmp_path):
    _write_structure(tmp_path, "tower.json")
    _write_nbt(tmp_path, "tower/turret.nbt")
    data = {"pieces_spawn_counts": [{
        "nbt_piece_name": "test:tower/turret",
        "always_spawn_this_many": 4,
        "never_spawn_more_than_this_many": 2,
    }]}
    _write_counts(tmp_path, "tower.json", data, dir_name="msl_pieces_spawn_counts_additions")
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_plural_structures_dir_supported(tmp_path):
    _write_structure(tmp_path, "tower.json")
    path = _ns_root(tmp_path) / "structures" / "tower" / "turret.nbt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    _write_counts(tmp_path, "tower.json", _valid_counts())
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed
