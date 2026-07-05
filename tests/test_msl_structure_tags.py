"""Tests for check_msl_structure_tags."""
from __future__ import annotations

import json
from pathlib import Path

from tests.nbt_helpers import FakeContext

from checks import check_msl_structure_tags as mod


def _write_tag(root: Path, name: str, values: list) -> None:
    path = (root / "src" / "main" / "resources" / "data" / "moogs_structures"
            / "tags" / "worldgen" / "structure" / f"{name}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"values": values}, f)


def _write_structure(root: Path, namespace: str, rel: str) -> None:
    path = (root / "src" / "main" / "resources" / "data" / namespace
            / "worldgen" / "structure" / rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_no_tag_files_passes(tmp_path):
    passed, summary = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed
    assert "no msl structure tags" in summary


def test_valid_tag_passes(tmp_path):
    _write_structure(tmp_path, "test", "fortress.json")
    _write_tag(tmp_path, "no_basalt", ["test:fortress"])
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_unknown_tag_name_fails(tmp_path):
    _write_structure(tmp_path, "test", "fortress.json")
    _write_tag(tmp_path, "no_basault", ["test:fortress"])
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_missing_structure_fails(tmp_path):
    _write_tag(tmp_path, "no_delta", ["test:fortress"])
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_foreign_namespace_skipped(tmp_path):
    _write_tag(tmp_path, "larger_locate_search", ["othermod:fortress"])
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_object_entry_form_supported(tmp_path):
    _write_structure(tmp_path, "test", "fortress.json")
    _write_tag(tmp_path, "no_basalt", [{"id": "test:fortress", "required": False}])
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert passed


def test_malformed_entry_fails(tmp_path):
    _write_tag(tmp_path, "no_basalt", [42])
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed


def test_missing_values_fails(tmp_path):
    path = (tmp_path / "src" / "main" / "resources" / "data" / "moogs_structures"
            / "tags" / "worldgen" / "structure" / "no_basalt.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"value": []}', encoding="utf-8")
    passed, _ = mod.run(FakeContext("test", ["1.21"], tmp_path))
    assert not passed
