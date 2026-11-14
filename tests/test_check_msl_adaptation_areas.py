"""Tests for check_msl_adaptation_areas: adaptation areas MSL loads but that shape less
than they say. Each test builds a tiny pack: a structure, its start pool and NBTs."""
from __future__ import annotations

import json
from pathlib import Path

from nbtlib import Compound, String

from checks import check_msl_adaptation_areas as mod
from tests.nbt_helpers import FakeContext, block_entry, build_datapack, save, structure_nbt

CARVE = {"kernel_size": 6, "kernel_distance": 2, "top": "carve", "bottom": "bury"}


def _structure(**overrides) -> dict:
    data = {"type": "moogs_structures:moogs_structures_generic_jigsaw_structure",
            "biomes": "#minecraft:is_overworld", "step": "surface_structures", "spawn_overrides": {},
            "start_pool": "test:start", "size": 6, "start_height": {"absolute": 0},
            "enhanced_terrain_adaptation": CARVE}
    data.update(overrides)
    return data


def _area(**overrides) -> dict:
    element = {"element_type": "moogs_structures:versioned_single_pool_element", "location": "test:start",
               "projection": "rigid", "processors": "minecraft:empty",
               "adaptation_area": {"columns": [{"x": [2, 5], "z": [0, 15]}]}}
    element.update(overrides)
    return element


def _pack(tmp_path: Path, structure: dict, start: list[dict], pools: dict[str, list[dict]] | None = None,
          jigsaw_to: str | None = None) -> Path:
    """A 16x8x16 start piece (with one jigsaw to ``jigsaw_to``), its pool and the structure."""
    root, structures, pool_dir = build_datapack(tmp_path)
    palette = [Compound({"Name": String("minecraft:stone")}), Compound({"Name": String("minecraft:jigsaw")})]
    blocks = [block_entry(0, (0, 0, 0))]
    if jigsaw_to:
        blocks.append(block_entry(1, (8, 0, 0), Compound({"pool": String(jigsaw_to)})))
    save(structure_nbt(3955, blocks=blocks, palette=palette, size=(16, 8, 16)), structures / "start.nbt")
    for name, elements in {"start": start, **(pools or {})}.items():
        (pool_dir / f"{name}.json").write_text(json.dumps(
            {"fallback": "minecraft:empty", "elements": [{"weight": 1, "element": e} for e in elements]}),
            encoding="utf-8")
    sdir = pool_dir.parent / "structure"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "s.json").write_text(json.dumps(structure), encoding="utf-8")
    return root


def _run(root: Path, capsys) -> tuple[bool, str, str]:
    passed, summary = mod.run(FakeContext("test", ["1.21.1"], root))
    return passed, summary, capsys.readouterr().out


def test_an_area_its_structure_shapes_is_quiet(tmp_path, capsys):
    root = _pack(tmp_path, _structure(), [_area(adaptation_area={
        "columns": [{"x": [2, 5], "z": [0, 15]}], "outside_follows_ground": True})])
    passed, summary, out = _run(root, capsys)
    assert passed and "[WARN]" not in out, out
    assert summary == "1 adaptation area(s), all OK"


def test_no_areas_says_so(tmp_path, capsys):
    root = _pack(tmp_path, _structure(), [_area(adaptation_area=None)])
    passed, summary, out = _run(root, capsys)
    assert passed and summary == "no adaptation areas", out


def test_an_area_with_no_adaptation_to_shape_with_warns(tmp_path, capsys):
    root = _pack(tmp_path, _structure(enhanced_terrain_adaptation="none"), [_area()])
    passed, summary, out = _run(root, capsys)
    assert passed and "1 warning(s)" in summary, out
    assert "template_pool/start.json @ elements > 0 > adaptation_area" in out
    assert "no enhanced_terrain_adaptation that changes the ground, on the element or in structure/s.json" in out
    # The element's own settings are enough, whatever the structure has.
    root = _pack(tmp_path / "own", _structure(enhanced_terrain_adaptation=None), [_area(
        enhanced_terrain_adaptation=CARVE)])
    passed, summary, out = _run(root, capsys)
    assert "[WARN]" not in out, out


def test_an_element_that_turns_its_adaptation_off_warns(tmp_path, capsys):
    root = _pack(tmp_path, _structure(), [_area(enhanced_terrain_adaptation={
        "kernel_size": 1, "kernel_distance": 2, "top": "carve", "bottom": "bury"})])
    _, _, out = _run(root, capsys)
    assert "the element's own enhanced_terrain_adaptation changes nothing" in out, out


def test_an_area_under_a_vanilla_structure_warns(tmp_path, capsys):
    root = _pack(tmp_path, _structure(type="minecraft:jigsaw"), [_area(adaptation_area={
        "columns": [{"x": [2, 5], "z": [0, 15]}], "outside_follows_ground": True})])
    _, _, out = _run(root, capsys)
    assert ("the area shapes no ground in structure/s.json: only MSL's two jigsaw structures are shaped "
            "(outside_follows_ground still works)") in out, out


def test_following_the_ground_under_a_vanilla_beard_warns(tmp_path, capsys):
    area = _area(adaptation_area={"columns": [{"x": [2, 5], "z": [0, 15]}], "outside_follows_ground": True})
    root = _pack(tmp_path, _structure(terrain_adaptation="beard_thin"), [area])
    _, _, out = _run(root, capsys)
    assert "the vanilla terrain_adaptation of structure/s.json beards the whole box first" in out, out
    # Without outside_follows_ground the beard takes nothing from the area.
    root = _pack(tmp_path / "plain", _structure(terrain_adaptation="beard_thin"), [_area()])
    _, _, out = _run(root, capsys)
    assert "[WARN]" not in out, out


def test_columns_past_the_template_warn(tmp_path, capsys):
    root = _pack(tmp_path, _structure(), [_area(adaptation_area={"columns": [
        {"x": [2, 5], "z": [0, 15]}, {"x": [10, 16], "z": [-1, 3]}]})])
    passed, summary, out = _run(root, capsys)
    assert passed and "2 warning(s)" in summary, out
    assert "columns > 1 x [10, 16] runs past start.nbt, whose x goes 0 to 15" in out, out
    assert "columns > 1 z [-1, 3] runs past start.nbt, whose z goes 0 to 15" in out, out
    assert "columns > 0" not in out


def test_a_pool_reached_through_a_jigsaw_is_judged_by_its_structure(tmp_path, capsys):
    side = [_area(location="test:start")]
    root = _pack(tmp_path, _structure(enhanced_terrain_adaptation=None), [_area(adaptation_area=None)],
                 pools={"side": side, "loose": side}, jigsaw_to="test:side")
    _, summary, out = _run(root, capsys)
    assert "template_pool/side.json" in out and "in structure/s.json" in out, out
    # No structure reaches the loose pool, so nothing is said about its structure.
    assert "template_pool/loose.json" not in out, out
    assert "2 adaptation area(s), 1 warning(s)" == summary
