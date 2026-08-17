"""Tests for check_msl_replace_vanilla: presets, structures block, tag hookups."""
from __future__ import annotations

import json
from pathlib import Path

from checks import check_msl_replace_vanilla as mod
from tests.nbt_helpers import FakeContext


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def _write_manifest(root: Path, data) -> None:
    _write_json(root / "src" / "main" / "resources" / "data" / "test"
                / "moogs_structures" / "replace_vanilla.json", data)


def _write_structure(root: Path, id_: str) -> None:
    ns, _, path = id_.partition(":")
    _write_json(root / "src" / "main" / "resources" / "data" / ns
                / "worldgen" / "structure" / f"{path}.json", {"type": "test"})


def _write_structure_set(root: Path, id_: str) -> None:
    ns, _, path = id_.partition(":")
    _write_json(root / "src" / "main" / "resources" / "data" / ns
                / "worldgen" / "structure_set" / f"{path}.json",
                {"structures": [], "placement": {"type": "minecraft:random_spread"}})


def _write_vanilla_tag(root: Path, tag: str, values: list[str]) -> None:
    _write_json(root / "src" / "main" / "resources" / "data" / "minecraft"
                / "tags" / "worldgen" / "structure" / f"{tag}.json",
                {"replace": False, "values": values})


def _ctx(root: Path) -> FakeContext:
    return FakeContext("test", ["1.21"], root)


def _preset(id_: str, vanilla: str, replacement: str) -> dict:
    return {
        "id": id_,
        "replacements": [{
            "vanilla_key": vanilla.split(":", 1)[1],
            "vanilla_structure": vanilla,
            "replacement_structure": replacement,
        }],
    }


# ---------- no manifest ----------

def test_no_manifest_passes(tmp_path):
    passed, summary = mod.run(_ctx(tmp_path))
    assert passed
    assert "no replace_vanilla.json" in summary


def test_invalid_json_fails(tmp_path):
    path = tmp_path / "src" / "main" / "resources" / "data" / "test" / "moogs_structures" / "replace_vanilla.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


# ---------- presets ----------

def test_valid_preset_passes(tmp_path):
    _write_structure(tmp_path, "test:my_pyramid")
    _write_manifest(tmp_path, {
        "presets": [_preset("replace_pyramid", "minecraft:desert_pyramid", "test:my_pyramid")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_missing_replacement_structure_json_fails(tmp_path):
    _write_manifest(tmp_path, {
        "presets": [_preset("replace_pyramid", "minecraft:desert_pyramid", "test:nope")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_unknown_vanilla_structure_fails(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "presets": [_preset("bad_vanilla", "minecraft:not_a_real_structure", "test:x")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_missing_vanilla_key_fails(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "presets": [{
            "id": "p",
            "replacements": [{
                "vanilla_structure": "minecraft:desert_pyramid",
                "replacement_structure": "test:x",
            }],
        }],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_missing_replacement_structure_field_fails(tmp_path):
    _write_manifest(tmp_path, {
        "presets": [{
            "id": "p",
            "replacements": [{
                "vanilla_key": "desert_pyramid",
                "vanilla_structure": "minecraft:desert_pyramid",
            }],
        }],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_duplicate_preset_id_fails(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_structure(tmp_path, "test:y")
    _write_manifest(tmp_path, {
        "presets": [
            _preset("dupe", "minecraft:desert_pyramid", "test:x"),
            _preset("dupe", "minecraft:jungle_pyramid", "test:y"),
        ],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_missing_preset_id_fails(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "presets": [{
            "replacements": [{
                "vanilla_key": "desert_pyramid",
                "vanilla_structure": "minecraft:desert_pyramid",
                "replacement_structure": "test:x",
            }],
        }],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_default_enabled_non_bool_fails(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "presets": [{
            "id": "p",
            "default_enabled": "yes",
            "replacements": [{
                "vanilla_key": "desert_pyramid",
                "vanilla_structure": "minecraft:desert_pyramid",
                "replacement_structure": "test:x",
            }],
        }],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


# ---------- tag hookups (warnings only) ----------

def test_stronghold_missing_tag_warns_but_passes(tmp_path, capsys):
    _write_structure(tmp_path, "test:my_stronghold")
    _write_manifest(tmp_path, {
        "presets": [_preset("replace_stronghold", "minecraft:stronghold", "test:my_stronghold")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "WARN" in out and "eye_of_ender_located" in out


def test_stronghold_present_in_tag_no_warning(tmp_path, capsys):
    _write_structure(tmp_path, "test:my_stronghold")
    _write_vanilla_tag(tmp_path, "eye_of_ender_located", ["test:my_stronghold"])
    _write_manifest(tmp_path, {
        "presets": [_preset("replace_stronghold", "minecraft:stronghold", "test:my_stronghold")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "eye_of_ender_located" not in out


def test_monument_present_as_id_object_no_warning(tmp_path, capsys):
    _write_structure(tmp_path, "test:my_monument")
    _write_vanilla_tag(tmp_path, "on_ocean_explorer_maps", [{"id": "test:my_monument"}])
    _write_manifest(tmp_path, {
        "presets": [_preset("replace_monument", "minecraft:monument", "test:my_monument")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "on_ocean_explorer_maps" not in out


# ---------- structures block ----------

def test_preview_template_missing_structure_token_warns(tmp_path, capsys):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "structures": {"preview_url_template": "https://example.com/preview"},
        "presets": [_preset("p", "minecraft:desert_pyramid", "test:x")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "{structure}" in out or "structure" in out


def test_preview_template_unsupported_token_warns(tmp_path, capsys):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "structures": {"preview_url_template": "https://example.com/{structure}/{unknown}"},
        "presets": [_preset("p", "minecraft:desert_pyramid", "test:x")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "unknown" in out


def test_no_slug_no_template_warns(tmp_path, capsys):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "structures": {"mod_name": "Test"},
        "presets": [_preset("p", "minecraft:desert_pyramid", "test:x")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "preview" in out.lower()


def test_entries_structure_must_resolve_to_structure_set(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_manifest(tmp_path, {
        "structures": {
            "mod_slug": "t",
            "entries": [{"structure": "test:missing_set"}],
        },
        "presets": [_preset("p", "minecraft:desert_pyramid", "test:x")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert not passed


def test_entries_structure_set_exists_passes(tmp_path):
    _write_structure(tmp_path, "test:x")
    _write_structure_set(tmp_path, "test:my_set")
    _write_manifest(tmp_path, {
        "structures": {
            "mod_slug": "t",
            "entries": [{"structure": "test:my_set"}],
        },
        "presets": [_preset("p", "minecraft:desert_pyramid", "test:x")],
    })
    passed, _ = mod.run(_ctx(tmp_path))
    assert passed


def test_empty_manifest_warns_but_passes(tmp_path, capsys):
    _write_manifest(tmp_path, {})
    passed, _ = mod.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert passed
    assert "WARN" in out
