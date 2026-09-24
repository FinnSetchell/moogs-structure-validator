"""Overlay packs (``"overlay": true`` in validator.json).

An overlay pack ships part of a data pack for a mod it extends, usually in that
mod's namespace: structure files and pool overrides, but no loot tables, no
worldgen structures, no structure sets. References into the parent mod cannot
be verified from the pack, so they are listed, not failed. Everything the pack
does ship is still checked as strictly as a full mod's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from nbtlib import Compound, String

from core.project import Project
from tests.nbt_helpers import (
    FakeContext,
    block_entry,
    build_datapack,
    save,
    stub_registries,
    structure_nbt,
    write_pool,
)


def _ctx(root: Path, overlay: bool) -> FakeContext:
    ctx = FakeContext("test", ["1.21.5", "1.21.11"], root)
    ctx.overlay = overlay
    return ctx


def _element(location: str) -> dict:
    return {"weight": 1, "element": {
        "element_type": "minecraft:single_pool_element", "location": location,
        "projection": "rigid", "processors": "minecraft:empty",
    }}


def _overlay_pack(tmp_path: Path, monkeypatch, *, loot: str = "test:chests/ship",
                  jigsaw_pool: str = "test:ship/side_pool", pool_refs: tuple[str, ...] = ("test:ship",)):
    """A compat pack: one structure and its pool override, nothing else."""
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, blocks={"minecraft:chest", "minecraft:jigsaw"})
    palette = [Compound({"Name": String("minecraft:chest")}), Compound({"Name": String("minecraft:jigsaw")})]
    blocks = [
        block_entry(0, pos=(0, 0, 0), nbt=Compound({"id": String("minecraft:chest"), "LootTable": String(loot)})),
        block_entry(1, pos=(1, 0, 0), nbt=Compound({"id": String("minecraft:jigsaw"), "pool": String(jigsaw_pool)})),
    ]
    save(structure_nbt(4325, blocks=blocks, palette=palette, size=(2, 1, 1)), structures / "ship.nbt")
    write_pool(pools / "ship" / "start.json", [_element(r) for r in pool_refs])
    return root


# ---------- check_data_integrity ----------

def test_overlay_pack_without_worldgen_or_sets_passes(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch)
    from checks import check_data_integrity as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    out = capsys.readouterr().out
    assert passed, summary
    assert summary == "all cross-references OK"
    assert "[3/7] Structure -> Pool  not in this pack" in out
    assert "[4/7] Set -> Structure   not in this pack" in out


def test_full_mod_without_worldgen_or_sets_still_fails(tmp_path, monkeypatch):
    """The option is opt-in: a mod that is not declared an overlay keeps the rule."""
    root = _overlay_pack(tmp_path, monkeypatch)
    from checks import check_data_integrity as mod
    passed, summary = mod.run(_ctx(root, overlay=False))
    assert not passed
    assert summary == "required directory missing"


def test_overlay_pool_naming_a_parent_piece_is_listed_not_failed(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch, pool_refs=("test:ship", "test:parent/piece"))
    from checks import check_data_integrity as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    out = capsys.readouterr().out
    assert passed, summary
    assert "1 not in this pack (expected from the parent mod)" in out
    assert "test:parent/piece" in out
    assert summary == "all cross-references OK  (1 expected from the parent mod)"


def test_overlay_structure_placed_by_the_parent_is_listed_not_failed(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch)
    ws = root / "src" / "main" / "resources" / "data" / "test" / "worldgen" / "structure"
    ws.mkdir(parents=True)
    (ws / "bop_ship.json").write_text(json.dumps({"type": "minecraft:jigsaw", "start_pool": "test:ship/start"}),
                                      encoding="utf-8")
    from checks import check_data_integrity as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    out = capsys.readouterr().out
    assert passed, summary
    assert "bop_ship.json" in out and "expected from the parent mod" in out


def test_overlay_orphans_still_warn(tmp_path, monkeypatch, capsys):
    """A structure file nothing in the pack names is still reported: the pack's
    own files are checked as for any mod."""
    root = _overlay_pack(tmp_path, monkeypatch)
    save(structure_nbt(4325), root / "src" / "main" / "resources" / "data" / "test" / "structures" / "stray.nbt")
    from checks import check_data_integrity as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    assert passed
    assert "1 orphan warning" in summary
    assert "stray.nbt" in capsys.readouterr().out


def test_overlay_bad_msl_element_key_still_fails(tmp_path, monkeypatch):
    root = _overlay_pack(tmp_path, monkeypatch)
    pools = root / "src" / "main" / "resources" / "data" / "test" / "worldgen" / "template_pool"
    write_pool(pools / "bad.json", [{"weight": 1, "element": {
        "type": "moogs_structures:versioned_single_pool_element", "location": "test:ship",
    }}])
    from checks import check_data_integrity as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    assert not passed
    assert summary == "cross-reference errors found"


# ---------- check_loot_tables ----------

def test_overlay_without_loot_tables_passes_and_lists_the_parent_table(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch)
    from checks import check_loot_tables as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    out = capsys.readouterr().out
    assert passed, summary
    assert "test:chests/ship" in out and "expected from the parent mod" in out
    assert summary == "1 / 1 structures have loot tables (1 from the parent mod)"


def test_full_mod_without_loot_tables_still_fails(tmp_path, monkeypatch):
    root = _overlay_pack(tmp_path, monkeypatch)
    from checks import check_loot_tables as mod
    passed, summary = mod.run(_ctx(root, overlay=False))
    assert not passed
    assert summary == "loot table directory missing"


def test_overlay_loot_table_the_pack_ships_is_not_listed(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch)
    lt = root / "src" / "main" / "resources" / "data" / "test" / "loot_table" / "chests" / "ship.json"
    lt.parent.mkdir(parents=True)
    lt.write_text('{"pools": []}', encoding="utf-8")
    from checks import check_loot_tables as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    assert passed
    assert summary == "1 / 1 structures have loot tables"
    assert "parent mod" not in capsys.readouterr().out


# ---------- check_jigsaw_pools ----------

def test_overlay_jigsaw_into_a_parent_pool_is_counted_not_warned(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch)
    from checks import check_jigsaw_pools as mod
    passed, summary = mod.run(_ctx(root, overlay=True))
    out = capsys.readouterr().out
    assert passed
    assert "WARN" not in out
    assert summary == "1 jigsaw block(s), all valid (1 pool(s) from the parent mod)"


def test_full_mod_jigsaw_into_a_missing_pool_still_warns(tmp_path, monkeypatch, capsys):
    root = _overlay_pack(tmp_path, monkeypatch)
    from checks import check_jigsaw_pools as mod
    passed, summary = mod.run(_ctx(root, overlay=False))
    assert passed  # warn-only, as always
    assert "pool not found" in capsys.readouterr().out
    assert summary == "1 jigsaw block(s), 1 pool warning(s)"


def test_overlay_jigsaw_into_another_namespace_still_warns(tmp_path, monkeypatch, capsys):
    """Overlay covers the pack's own namespace only; a stray namespace is still a finding."""
    root = _overlay_pack(tmp_path, monkeypatch, jigsaw_pool="othermod:side_pool")
    from checks import check_jigsaw_pools as mod
    mod.run(_ctx(root, overlay=True))
    assert "unknown namespace" in capsys.readouterr().out


# ---------- resource lookup and config ----------

def test_resource_lookup_cannot_say_missing_in_an_overlay(tmp_path):
    full = Project(tmp_path, "test")
    overlay = Project(tmp_path, "test", overlay=True)
    assert full.resource_exists("test:chests/vault", "loot_table") is False
    assert overlay.resource_exists("test:chests/vault", "loot_table") is None
    assert overlay.resource_exists("minecraft:chests/vault", "loot_table") is None


def test_config_rejects_a_non_boolean_overlay(tmp_path):
    import validator
    cfg = tmp_path / "validator.json"
    cfg.write_text(json.dumps({"namespace": "t", "mc_versions": ["1.21"], "overlay": "yes"}), encoding="utf-8")
    with pytest.raises(ValueError, match="overlay"):
        validator.load_config(cfg)
    cfg.write_text(json.dumps({"namespace": "t", "mc_versions": ["1.21"], "overlay": True}), encoding="utf-8")
    assert validator.load_config(cfg)["overlay"] is True
