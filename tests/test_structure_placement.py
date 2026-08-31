"""A worldgen structure that nothing places can never generate.

`check_data_integrity` already walks structure_set -> structure (does the named
structure exist). These cover the reverse: structure -> structure_set (does
anything ask the game to look for it). A structure in no set fails silently at
runtime -- it only shows up as `could_not_locate` in a sweep.
"""
from __future__ import annotations

import json
from pathlib import Path

from checks.check_data_integrity import _check_structure_placed


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _pack(tmp_path: Path, namespace: str = "test") -> tuple[Path, Path, Path, Path]:
    data_root = tmp_path / "src" / "main" / "resources" / "data"
    namespace_root = data_root / namespace
    structures = namespace_root / "worldgen" / "structure"
    sets = namespace_root / "worldgen" / "structure_set"
    structures.mkdir(parents=True, exist_ok=True)
    sets.mkdir(parents=True, exist_ok=True)
    return data_root, namespace_root, structures, sets


def _run(data_root: Path, namespace_root: Path, namespace: str = "test") -> list[str]:
    return _check_structure_placed(
        namespace_root / "worldgen" / "structure", data_root, namespace_root, namespace
    )


def test_structure_named_by_a_set_passes(tmp_path):
    data_root, ns_root, structures, sets = _pack(tmp_path)
    _write(structures / "well.json", {"type": "minecraft:jigsaw"})
    _write(sets / "wells.json", {"structures": [{"structure": "test:well", "weight": 1}]})

    assert _run(data_root, ns_root) == []


def test_structure_in_no_set_is_flagged(tmp_path):
    data_root, ns_root, structures, sets = _pack(tmp_path)
    _write(structures / "well.json", {"type": "minecraft:jigsaw"})
    _write(structures / "orphan.json", {"type": "minecraft:jigsaw"})
    _write(sets / "wells.json", {"structures": [{"structure": "test:well", "weight": 1}]})

    errors = _run(data_root, ns_root)
    assert len(errors) == 1
    assert errors[0].startswith("orphan.json")


def test_nested_structure_path_is_matched(tmp_path):
    """Sets reference nested structures with a slashed path, not just a bare name."""
    data_root, ns_root, structures, sets = _pack(tmp_path)
    _write(structures / "wells" / "desert.json", {"type": "minecraft:jigsaw"})
    _write(sets / "wells.json",
           {"structures": [{"structure": "test:wells/desert", "weight": 1}]})

    assert _run(data_root, ns_root) == []


def test_msl_replacement_structure_counts_as_placed(tmp_path):
    """MSL swaps a replacement in for a vanilla structure, so it generates through
    that structure's set and legitimately has none of its own."""
    data_root, ns_root, structures, sets = _pack(tmp_path)
    _write(structures / "desert_temple.json", {"type": "minecraft:jigsaw"})
    _write(ns_root / "moogs_structures" / "replace_vanilla.json", {
        "presets": [{
            "id": "desert",
            "replacements": [{
                "vanilla_key": "minecraft:desert_pyramid",
                "vanilla_structure": "minecraft:desert_pyramid",
                "replacement_structure": "test:desert_temple",
            }],
        }],
    })

    assert _run(data_root, ns_root) == []


def test_a_set_in_another_namespace_still_counts(tmp_path):
    """A pack may override a vanilla set to slot its own structure into it."""
    data_root, ns_root, structures, _sets = _pack(tmp_path)
    _write(structures / "well.json", {"type": "minecraft:jigsaw"})
    _write(data_root / "minecraft" / "worldgen" / "structure_set" / "villages.json",
           {"structures": [{"structure": "test:well", "weight": 1}]})

    assert _run(data_root, ns_root) == []


def test_set_entry_without_a_namespace_defaults_to_minecraft(tmp_path):
    """A bare `well` in a set means `minecraft:well`, so it does not place test:well."""
    data_root, ns_root, structures, sets = _pack(tmp_path)
    _write(structures / "well.json", {"type": "minecraft:jigsaw"})
    _write(sets / "wells.json", {"structures": [{"structure": "well", "weight": 1}]})

    assert len(_run(data_root, ns_root)) == 1


def test_malformed_set_does_not_hide_unplaced_structures(tmp_path):
    data_root, ns_root, structures, sets = _pack(tmp_path)
    _write(structures / "well.json", {"type": "minecraft:jigsaw"})
    (sets / "broken.json").write_text("{not json", encoding="utf-8")

    assert len(_run(data_root, ns_root)) == 1
