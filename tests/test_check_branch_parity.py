"""Tests for check_branch_parity. Each test builds a git repo with a 1.21 branch
checked out and a 1.20 branch beside it, then compares the two."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from checks import check_branch_parity as mod
from tests.nbt_helpers import FakeContext

WG = Path("src/main/resources/data/test/worldgen")
POOL = {"fallback": "minecraft:empty", "elements": [{"weight": 1, "element": {
    "element_type": "moogs_structures:versioned_single_pool_element", "location": "test:v1_21/house",
    "locations": {"1.21-26.3": "test:v1_21/house"}, "projection": "rigid", "processors": "minecraft:empty",
    "override_liquid_settings": "ignore_waterlogging"}}]}
STRUCTURE = {"type": "moogs_structures:moogs_structures_generic_jigsaw_structure", "biomes": "#test:snowy",
             "step": "surface_structures", "spawn_overrides": {}, "start_pool": "test:house", "size": 1,
             "start_height": {"absolute": 0}, "liquid_settings": "ignore_waterlogging"}
SET = {"structures": [{"structure": "test:house", "weight": 1}, {"structure": "test:barn", "weight": 2}],
       "placement": {"type": "minecraft:random_spread", "salt": 1234, "spacing": 48, "separation": 30}}
PROCS = {"processors": [{"processor_type": "moogs_structures:remove_floating_blocks_processor"}]}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    *args], check=True, capture_output=True)


def _write(root: Path, files: dict[str, object]) -> None:
    for rel, data in files.items():
        path = root / WG / rel
        if data is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")


def _repo(tmp_path: Path, files_120: dict, files_121: dict) -> Path:
    """A repo on 1.21-datapack whose 1.20-datapack branch holds ``files_120``."""
    root = tmp_path / "mod"
    root.mkdir()
    _git(root, "init", "-q", "-b", "1.20-datapack")
    _write(root, files_120)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "1.20")
    _git(root, "checkout", "-q", "-b", "1.21-datapack")
    _write(root, files_121)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", "1.21")
    return root


def _base_120() -> dict:
    pool = json.loads(json.dumps(POOL))
    element = pool["elements"][0]["element"]
    element.update(location="test:v1_20/house", locations={"1.20-1.20.6": "test:v1_20/house"})
    del element["override_liquid_settings"]
    structure = {k: v for k, v in STRUCTURE.items() if k != "liquid_settings"}
    waterlog = {"processors": [{"processor_type": "moogs_structures:waterlogging_fix_processor"}]}
    return {"template_pool/house.json": pool, "structure/house.json": structure, "structure_set/house.json": SET,
            "processor_list/clean.json": PROCS, "processor_list/waterlog.json": waterlog}


def _run(root: Path, capsys, branch: str | None = "1.20-datapack") -> tuple[bool, str, str]:
    ctx = FakeContext("test", ["1.21.1"], root)
    ctx.compare_branch = branch
    passed, summary = mod.run(ctx)
    return passed, summary, capsys.readouterr().out


def test_only_version_forced_differences_pass_quietly(tmp_path, capsys):
    # Other NBT paths, 1.21's liquid settings, a 1.20-only waterlogging list, and the
    # set's members in another order: nothing a player would see differ.
    shuffled = {**SET, "structures": list(reversed(SET["structures"]))}
    root = _repo(tmp_path, _base_120(), {"template_pool/house.json": POOL, "structure/house.json": STRUCTURE,
                                         "structure_set/house.json": shuffled, "processor_list/waterlog.json": None})
    passed, summary, out = _run(root, capsys)
    assert passed and summary == "matches 1.20-datapack", out
    assert "[WARN]" not in out


def test_a_placement_that_differs_warns_with_both_values(tmp_path, capsys):
    root = _repo(tmp_path, _base_120(), {"structure_set/house.json": {
        **SET, "placement": {**SET["placement"], "spacing": 43, "separation": 22}}})
    passed, summary, out = _run(root, capsys)
    assert passed and summary == "1 file(s) differ from 1.20-datapack, 0 on one branch only", out
    assert "[WARN] structure_set/house.json differs from 1.20-datapack for no version reason" in out
    assert "placement > spacing: 43 here, 48 on 1.20-datapack" in out
    assert "placement > separation: 22 here, 30 on 1.20-datapack" in out


def test_extra_set_members_are_named(tmp_path, capsys):
    root = _repo(tmp_path, _base_120(), {"structure_set/house.json": {
        **SET, "structures": SET["structures"] + [{"structure": "test:well", "weight": 1}]}})
    _, _, out = _run(root, capsys)
    assert "structures: only here: test:well (weight 1)" in out, out


def test_a_structure_setting_on_one_branch_warns(tmp_path, capsys):
    root = _repo(tmp_path, _base_120(), {"structure/house.json": {
        **STRUCTURE, "biomes": "#test:is_snowy", "cannot_spawn_in_liquid": True}})
    _, _, out = _run(root, capsys)
    assert 'biomes: "#test:is_snowy" here, "#test:snowy" on 1.20-datapack' in out, out
    assert "cannot_spawn_in_liquid: true here, unset on 1.20-datapack" in out, out


def test_a_pool_that_differs_beyond_its_nbt_paths_warns(tmp_path, capsys):
    pool = json.loads(json.dumps(POOL))
    pool["elements"][0]["weight"] = 3
    root = _repo(tmp_path, _base_120(), {"template_pool/house.json": pool})
    _, _, out = _run(root, capsys)
    assert "[WARN] template_pool/house.json" in out and "elements > 0 > weight: 3 here, 1 on 1.20-datapack" in out


def test_files_on_one_branch_are_listed(tmp_path, capsys):
    root = _repo(tmp_path, _base_120(), {"structure/barn.json": STRUCTURE, "processor_list/clean.json": None})
    _, summary, out = _run(root, capsys)
    assert "[WARN] structure: 1 file(s) only here: barn.json" in out, out
    assert "[WARN] processor_list: 1 file(s) only on 1.20-datapack: clean.json" in out, out
    # The 1.20-only waterlogging list is not listed: nothing else is in it.
    assert "waterlog.json" not in out
    assert summary.endswith("2 on one branch only")


def test_the_remote_branch_is_used_when_there_is_no_local_one(tmp_path, capsys):
    root = _repo(tmp_path, _base_120(), {"structure_set/house.json": {**SET, "placement": {
        **SET["placement"], "salt": 99}}})
    _git(root, "update-ref", "refs/remotes/origin/1.20-datapack", "1.20-datapack")
    _git(root, "branch", "-q", "-D", "1.20-datapack")
    _, _, out = _run(root, capsys)
    assert "differs from origin/1.20-datapack" in out and "salt: 99 here, 1234 on origin/1.20-datapack" in out


@pytest.mark.parametrize("branch, said", [(None, "no compare_branch in validator.json"),
                                          ("1.19-datapack", "this clone has no branch '1.19-datapack'")])
def test_without_another_branch_it_passes_and_says_why(tmp_path, capsys, branch, said):
    root = _repo(tmp_path, _base_120(), {})
    passed, _, out = _run(root, capsys, branch)
    assert passed and said in out, out


def test_a_pool_name_and_the_item_format_change_do_not_count(tmp_path, capsys):
    # No version reads a pool's name; armour written as `tag` before 1.20.5 and `components` from it.
    old_armor = {"processors": [{"processor_type": "moogs_structures:equip_armor_stand_processor", "armor_sets": [
        {"weight": 1, "armor": {"chest": {"id": "minecraft:iron_chestplate", "Count": 1,
                                          "tag": {"Trim": {"material": "minecraft:copper"}}}}}]}]}
    new_armor = json.loads(json.dumps(old_armor))
    chest = new_armor["processors"][0]["armor_sets"][0]["armor"]["chest"]
    del chest["Count"], chest["tag"]
    chest.update(count=1, components={"minecraft:trim": {"material": "minecraft:copper"}})
    base = _base_120()
    base["processor_list/armor.json"] = old_armor
    root = _repo(tmp_path, base, {"template_pool/house.json": {**POOL, "name": "test:house"},
                                  "processor_list/armor.json": new_armor})
    _, summary, out = _run(root, capsys)
    assert summary == "matches 1.20-datapack", out


def test_a_pool_with_another_piece_names_it(tmp_path, capsys):
    pool = json.loads(json.dumps(POOL))
    barn = json.loads(json.dumps(pool["elements"][0]))
    barn["element"].update(location="test:v1_21/barn", locations={"1.21-26.3": "test:v1_21/barn"})
    pool["elements"].append(barn)
    root = _repo(tmp_path, _base_120(), {"template_pool/house.json": pool})
    _, _, out = _run(root, capsys)
    assert "elements: 2 here, 1 on 1.20-datapack; pieces only here: barn" in out, out
