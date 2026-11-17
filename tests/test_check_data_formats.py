"""check_data_formats and check_claimed_versions: data read the way each version reads it.

The fixtures are tiny packs read with the pinned vanilla-mcdoc model in
data/format_model, so a model bump that changes how 26.2 or 26.3 read a loot
table shows up here. Registries are stubbed per version; a registry the stub
does not list is not judged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from checks import check_claimed_versions, check_data_formats
from core import msl_upgrade
from core.claims import format_range, manifest_targets, parse_claim
from core.formats import load_model, version_reader
from tests.nbt_helpers import FakeContext

# Stable releases as mcmeta reports them, with data pack formats.
VERSIONS = [
    ("1.20.6", 3839, 41, 0), ("1.21", 3953, 48, 0), ("1.21.1", 3955, 48, 0),
    ("1.21.4", 4189, 61, 0), ("1.21.5", 4325, 71, 0),
    ("26.2", 4903, 107, 1), ("26.3", 5023, 121, 0), ("26.4", 5130, 130, 0),
]

REGISTRIES = {
    "loot_function_type": ["set_count", "enchant_randomly", "enchant_with_levels", "set_contents", "sequence",
                           "filtered", "modify_contents", "exploration_map", "set_item", "set_name",
                           "discard", "set_written_book_pages", "set_book_cover"],
    "loot_condition_type": ["random_chance", "survives_explosion", "all_of", "any_of", "inverted",
                            "entity_properties"],
    "item": ["diamond", "book", "iron_ingot", "stone", "chain", "iron_chain", "map", "filled_map",
             "buried_treasure_map", "abandoned_camp_map"],
    "block": ["stone", "water", "iron_chain"],
    "worldgen/biome": ["plains", "desert"],
    "tag/worldgen/biome": ["is_overworld"],
}


@pytest.fixture
def stubbed(monkeypatch):
    from core import mcmeta

    def fake_registry_data(version, cache_dir, refresh):
        return {k: list(v) for k, v in REGISTRIES.items()}

    def fake_version_entries(cache_dir, refresh):
        return [{"id": v, "name": v, "type": "release", "stable": True, "data_version": dv,
                 "data_pack_version": f, "data_pack_version_minor": m}
                for v, dv, f, m in sorted(VERSIONS, key=lambda x: -x[1])]

    monkeypatch.setattr(mcmeta, "fetch_registry_data", fake_registry_data)
    monkeypatch.setattr(mcmeta, "fetch_version_entries", fake_version_entries)
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _project(tmp_path: Path, files: dict[str, object], *, msl: bool = False, pack: dict | None = None) -> Path:
    res = tmp_path / "src" / "main" / "resources"
    for rel, data in files.items():
        _write(res / rel, data)
    if msl:
        _write(res / "fabric.mod.json", {"id": "test", "depends": {"moogs_structures": ">=3.0.0"}})
    if pack is not None:
        _write(res / "pack.mcmeta", pack)
    (res / "data" / "test").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _run(root: Path, versions: list[str], claims: list[str] | None = None, check=check_data_formats):
    ctx = FakeContext("test", versions, root)
    ctx.claims = claims or []
    return check.run(ctx)


# --- loot tables in old, new and both forms ----------------------------------------

OLD_ENTRY = {"type": "minecraft:item", "name": "minecraft:diamond",
             "functions": [{"function": "minecraft:set_count", "count": 3}]}
NEW_ENTRY = {"type": "minecraft:item", "name": "minecraft:diamond",
             "modifier": {"type": "minecraft:set_count", "count": 3}}
DUAL_ENTRY = {"type": "minecraft:item", "name": "minecraft:diamond",
              "functions": [{"function": "minecraft:set_count", "count": 3}],
              "modifier": [{"type": "minecraft:set_count", "count": 3}]}


def _table(entry, **pool):
    return {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [entry], **pool}]}


def test_old_loot_form_fails_on_26_3_only(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(OLD_ENTRY)})
    passed, summary = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert "on 26.3" in summary and "26.2" not in summary.split("error(s) on ")[1]
    assert "`functions` is ignored" in out and "reads `modifier` instead" in out


def test_old_loot_form_passes_on_the_versions_that_read_it(tmp_path, stubbed):
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(OLD_ENTRY)})
    passed, _ = _run(root, ["1.21", "1.21.1", "26.2"])
    assert passed


def test_new_loot_form_alone_fails_before_26_3(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(NEW_ENTRY)})
    passed, summary = _run(root, ["26.2", "26.3"])
    assert not passed
    assert "on 26.2" in summary
    assert "`modifier` is ignored" in capsys.readouterr().out


def test_both_forms_side_by_side_pass_everywhere(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(DUAL_ENTRY)})
    passed, summary = _run(root, ["1.21", "26.2", "26.3"])
    out = capsys.readouterr().out
    assert passed, out
    assert "written in two version forms" in out


def test_half_converted_pool_conditions_fail_on_26_3(tmp_path, stubbed, capsys):
    # functions done, pool conditions forgotten: 26.3 drops the condition and
    # the pool rolls every time.
    table = _table(DUAL_ENTRY, conditions=[{"condition": "minecraft:random_chance", "chance": 0.5}])
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert "`conditions` is ignored" in out and "reads `condition` instead" in out


def test_msl_rewrite_rescues_conditions_but_not_functions(tmp_path, stubbed, capsys):
    # With Moog's Structure Lib, 26.3 reads the file after MSL's rewrite:
    # conditions and function ids are upgraded, the functions list is not.
    table = _table(OLD_ENTRY, conditions=[{"condition": "minecraft:random_chance", "chance": 0.5}])
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table}, msl=True)
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert "`functions` is ignored" in out
    # the conditions are named only as what MSL's rewrite rescues, never as an error
    lines = [line for line in out.splitlines() if "`conditions` is ignored" in line]
    assert len(lines) == 1 and lines[0].lstrip().startswith("first in")
    assert "Moog's Structure Lib rewrites" in out


def test_msl_rewrite_inside_an_ignored_form_is_not_reported(tmp_path, stubbed, capsys):
    # Both forms, typed ranges: MSL still renames `function` inside the old
    # `functions` list, but 26.3 ignores that list, so nothing depends on MSL.
    table = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [DUAL_ENTRY]}]}
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table}, msl=True)
    passed, summary = _run(root, ["26.2", "26.3"])
    assert passed and "warning" not in summary, capsys.readouterr().out


def test_msl_rewrite_alone_is_a_warning(tmp_path, stubbed, capsys):
    table = {"type": "minecraft:chest", "pools": [{"rolls": {"min": 1, "max": 3}, "entries": [DUAL_ENTRY]}]}
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table}, msl=True)
    passed, summary = _run(root, ["26.2", "26.3"])
    assert passed
    assert "warning" in summary


def test_typo_key_fails_and_comment_key_does_not(tmp_path, stubbed, capsys):
    typo = {"type": "minecraft:item", "name": "minecraft:diamond", "weigth": 3}
    note = {"type": "minecraft:item", "name": "minecraft:diamond", "_comment": "rare"}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(typo),
                               "data/test/loot_table/b.json": _table(note)})
    passed, _ = _run(root, ["1.21"])
    out = capsys.readouterr().out
    assert not passed
    assert "`weigth` is read by no version" in out
    assert "_comment" not in out


def test_unknown_item_on_a_version_rejects_the_file(tmp_path, stubbed, capsys):
    entry = {"type": "minecraft:item", "name": "minecraft:mace"}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(entry)})
    passed, _ = _run(root, ["1.21"])
    assert not passed
    assert "`minecraft:mace` is not a item on this version" in capsys.readouterr().out


def test_unnamespaced_ids_are_read_as_minecraft(tmp_path, stubbed):
    entry = {"type": "item", "name": "diamond", "functions": [{"function": "set_count", "count": 2}]}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(entry)})
    passed, _ = _run(root, ["1.21"])
    assert passed


# --- which files a version loads -----------------------------------------------------

def test_overlay_for_26_3_replaces_the_base_file(tmp_path, stubbed, capsys):
    pack = {"pack": {"pack_format": 48, "supported_formats": [48, 121], "min_format": 48, "max_format": 121},
            "overlays": {"entries": [{"formats": [121, 121], "min_format": 121, "max_format": 121,
                                      "directory": "ov_26_3"}]}}
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(OLD_ENTRY),
                               "ov_26_3/data/test/loot_table/chest.json": _table(NEW_ENTRY)}, pack=pack)
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_plural_folder_is_not_loaded_from_1_21(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_tables/chest.json": _table(OLD_ENTRY)})
    passed, _ = _run(root, ["1.20.6", "1.21"])
    out = capsys.readouterr().out
    assert not passed
    assert "on 1.21" in out and "does not load `loot_tables/`" in out


def test_tag_entry_missing_on_a_version_fails_unless_optional(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {
        "data/test/tags/worldgen/biome/bad.json": {"values": ["minecraft:plains", "minecraft:pale_garden"]},
        "data/test/tags/worldgen/biome/ok.json": {"values": ["minecraft:plains", "#minecraft:is_overworld",
                                                             {"id": "minecraft:pale_garden", "required": False}]},
    })
    passed, _ = _run(root, ["1.21"])
    out = capsys.readouterr().out
    assert not passed
    assert "bad.json" in out and "ok.json" not in out


# --- versions -----------------------------------------------------------------------------

def test_a_version_the_model_was_never_proven_against_fails(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(DUAL_ENTRY)})
    passed, summary = _run(root, ["26.3"], claims=["26.3-26.4"])
    assert not passed
    assert "never proven" in summary
    assert "26.4: the format model has not been proven" in capsys.readouterr().out


MANIFEST = """\
schema: 1
mod:
  id: test
discord:
  embedColor: "#0f2b52"   # a colour, not a comment
targets:
  - branch: 1.20-datapack
    mc: { start: "1.20", end: "1.20.6" }
  - branch: 1.21-datapack
    mc:
      start: "1.21"
      end: "26.3"   # fleet standard
"""


def test_publish_manifest_claim_beyond_validator_json_fails(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {})
    (root / ".github").mkdir()
    (root / ".github" / "moogs-publish.yml").write_text(MANIFEST, encoding="utf-8")
    passed, summary = _run(root, ["1.21", "1.21.1", "1.21.4", "1.21.5", "26.2"], check=check_claimed_versions)
    out = capsys.readouterr().out
    assert not passed
    assert "claimed but never checked: 26.3" in out


def test_claims_covered_by_validator_json_pass(tmp_path, stubbed):
    pack = {"pack": {"pack_format": 48, "supported_formats": [48, 121]}}
    root = _project(tmp_path, {}, pack=pack)
    passed, _ = _run(root, ["1.21", "1.21.1", "1.21.4", "1.21.5", "26.2", "26.3"], check=check_claimed_versions)
    assert passed


def test_pack_mcmeta_range_and_cli_claim_are_read(tmp_path, stubbed, capsys):
    pack = {"pack": {"pack_format": 48, "supported_formats": [48, 121]}}
    root = _project(tmp_path, {}, pack=pack)
    passed, _ = _run(root, ["1.21", "1.21.1"], claims=["1.21-26.2"], check=check_claimed_versions)
    out = capsys.readouterr().out
    assert not passed
    assert "pack.mcmeta: 1.21-26.3" in out and "--claim: 1.21-26.2" in out


def test_manifest_reader_handles_flow_and_block_styles():
    targets = manifest_targets(MANIFEST)
    assert {"branch": "1.20-datapack", "start": "1.20", "end": "1.20.6"} in targets
    assert {"branch": "1.21-datapack", "start": "1.21", "end": "26.3"} in targets


def test_format_ranges():
    assert format_range({"supported_formats": [48, 121]}, new_fields=False) == ((48, 0), (121, 99))
    assert format_range({"min_format": 48, "max_format": 121.0}, new_fields=True) == ((48, 0), (121, 99))
    assert format_range({"min_format": [107, 1], "max_format": [107, 1]}, new_fields=True) == ((107, 1), (107, 1))
    assert parse_claim("1.21-26.3") == ("1.21", "26.3") and parse_claim("26.3") == ("26.3", "26.3")
    assert parse_claim("next") is None


# --- MSL's rewrite and the reader ------------------------------------------------------

def test_msl_rewrite_matches_moogs_structure_lib():
    table = {"pools": [{"rolls": {"min": 1, "max": 2},
                        "conditions": [{"condition": "minecraft:random_chance", "chance": 0.5},
                                       {"condition": "minecraft:survives_explosion"}],
                        "entries": [{"type": "minecraft:item", "name": "minecraft:stone",
                                     "functions": [{"function": "minecraft:set_count", "count": 2,
                                                    "conditions": [{"condition": "minecraft:random_chance",
                                                                    "chance": 0.1}]}]}]}]}
    out, n = msl_upgrade.upgrade("loot_table", table)
    pool = out["pools"][0]
    assert pool["rolls"]["type"] == "minecraft:uniform"
    assert pool["condition"]["type"] == "minecraft:all_of"
    assert [t["type"] for t in pool["condition"]["terms"]] == ["minecraft:random_chance", "minecraft:survives_explosion"]
    fn = pool["entries"][0]["functions"][0]           # the list key itself is left alone, as in MSL
    assert fn["type"] == "minecraft:set_count" and fn["condition"]["type"] == "minecraft:random_chance"
    assert "conditions" in table["pools"][0]           # the input is not touched
    # pool conditions, its two condition ids, the range, the function id, the
    # function's conditions and its condition id: MSL counts each rewrite
    assert n == 7

    proc = {"processors": [{"rules": [{"output_state": {"Name": "minecraft:chain", "Properties": {"axis": "y"}}}]}]}
    out, n = msl_upgrade.upgrade("worldgen/processor_list", proc, {"minecraft:iron_chain"})
    assert out["processors"][0]["rules"][0]["output_state"] == {"id": "minecraft:iron_chain",
                                                                "properties": {"axis": "y"}}


def test_block_state_written_in_both_forms_passes_on_26_2_and_26_3():
    model = load_model()
    rule = {"input_predicate": {"predicate_type": "minecraft:always_true"},
            "location_predicate": {"predicate_type": "minecraft:always_true"}}
    rt = {"kind": "reference", "path": "::java::data::worldgen::processor_list::ProcessorList"}
    for state, ok_on in (({"Name": "minecraft:stone"}, {"26.2"}),
                         ({"id": "minecraft:stone"}, {"26.3"}),
                         ({"Name": "minecraft:stone", "id": "minecraft:stone"}, {"26.2", "26.3"})):
        data = {"processors": [{"processor_type": "minecraft:rule",
                                "rules": [dict(rule, output_state=state)]}]}
        for v in ("26.2", "26.3"):
            findings = version_reader(model, v, REGISTRIES, set()).read(data, rt)
            bad = [f for f in findings if f.code != "foreign-key" or not f.counterpart_present]
            assert (not bad) == (v in ok_on), (state, v, bad)


def test_a_stale_version_index_is_refetched_before_claims_are_read(tmp_path, monkeypatch, capsys):
    # The cached index stops at 26.2; the manifest claims 26.3. The claim must
    # not shrink to 26.2: the index is refetched, and 26.3 is then checked.
    from core import mcmeta
    calls = []

    def entries(cache_dir, refresh):
        calls.append(refresh)
        known = VERSIONS if refresh else [v for v in VERSIONS if v[0] not in ("26.3", "26.4")]
        return [{"id": v, "name": v, "type": "release", "stable": True, "data_version": dv,
                 "data_pack_version": f, "data_pack_version_minor": m} for v, dv, f, m in known]

    monkeypatch.setattr(mcmeta, "fetch_registry_data", lambda v, c, r: dict(REGISTRIES))
    monkeypatch.setattr(mcmeta, "fetch_version_entries", entries)
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(OLD_ENTRY)})
    (root / ".github").mkdir()
    (root / ".github" / "moogs-publish.yml").write_text(MANIFEST, encoding="utf-8")
    passed, summary = _run(root, ["1.21", "1.21.1", "26.2"])
    assert True in calls
    assert not passed and "on 26.3" in summary


# --- the MSL a mod runs with ---------------------------------------------------------

def _msl_project(tmp_path: Path, files: dict, fabric: str, gradle: str | None = None) -> Path:
    root = _project(tmp_path, files)
    res = root / "src" / "main" / "resources"
    _write(res / "fabric.mod.json", {"id": "test", "depends": {"moogs_structures": fabric}})
    (res / "META-INF").mkdir(parents=True, exist_ok=True)
    (res / "META-INF" / "neoforge.mods.toml").write_text(
        '[[dependencies.test]]\nmodId = "moogs_structures"\nmandatory = true\n'
        'versionRange = "${structure_lib_version_range}"\n', encoding="utf-8")
    if gradle is not None:
        (root / "gradle.properties").write_text(f"structure_lib_version_range={gradle}\n", encoding="utf-8")
    return root


def test_declared_minimum_is_the_lowest_any_loader_allows(tmp_path):
    root = _msl_project(tmp_path, {}, fabric=">=3.3.0", gradle="[3.0.0,)")
    low, sources = msl_upgrade.declared_minimum(root)
    assert low == (3, 0, 0)
    assert any("fabric.mod.json" in s for s in sources) and any("gradle.properties" in s for s in sources)
    assert msl_upgrade.range_floor("*") == (0, 0, 0)
    assert msl_upgrade.range_floor("^3.1") == (3, 1, 0)
    assert msl_upgrade.range_floor("${structure_lib_version_range}") is None


def test_msl_features_follow_the_oldest_build_a_mod_can_run_with(tmp_path):
    data = {"oldest_build": {"1.21.1": "1.0.0", "26.3": "3.3.0"},
            "features": {"legacy_data_upgrade": {"what": "x", "mc_from": "26.3", "msl_from": "3.3.0"},
                         "trial_spawner_configs": {"what": "y", "mc_from": "1.21", "mc_until": "1.21.2",
                                                   "msl_from": "3.0.0"}}}
    path = tmp_path / "builds.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    b = msl_upgrade.MslBuilds(path)
    # "*" on 26.3 still means 3.3.0 or newer: no older MSL exists there.
    assert b.applies("legacy_data_upgrade", "26.3", (0, 0, 0)) == (True, True)
    assert b.applies("legacy_data_upgrade", "26.2", (0, 0, 0)) == (False, False)
    # On 1.21.1 a "*" mod can run with MSL 1.0.0, which has no trial spawner configs.
    assert b.applies("trial_spawner_configs", "1.21.1", (0, 0, 0)) == (True, False)
    assert b.applies("trial_spawner_configs", "1.21.1", (3, 0, 0)) == (True, True)


TRIAL = {"spawn_potentials": [{"weight": 1, "data": {"entity": {"id": "minecraft:zombie"}}}]}


def test_msl_reads_trial_spawner_configs_before_vanilla_does(tmp_path, stubbed, capsys):
    root = _msl_project(tmp_path, {"data/test/trial_spawner/arena.json": TRIAL}, fabric=">=3.0.0")
    passed, summary = _run(root, ["1.21.1"])
    out = capsys.readouterr().out
    assert passed and "nothing reads this file" not in out, out
    assert "which reads data/<ns>/trial_spawner" in out


def test_a_minimum_below_the_msl_that_reads_them_fails(tmp_path, stubbed, capsys):
    # With MSL older than 3.0.0 on 1.21.1 the configs are never read: broken in
    # game with the MSL the mod allows, so it blocks.
    root = _msl_project(tmp_path, {"data/test/trial_spawner/arena.json": TRIAL}, fabric="*")
    passed, summary = _run(root, ["1.21.1"])
    out = capsys.readouterr().out
    assert not passed
    assert "[ERROR] on 1.21.1 this mod allows MSL 1.0.0" in out
    assert "Raise the moogs_structures minimum to 3.0.0" in out


def test_no_too_old_msl_error_where_no_build_the_mod_accepts_exists(tmp_path, stubbed, capsys):
    # MNS 1.21 asking for an MSL not yet published: nothing runs on 1.21.1, which the
    # refusal says. It is not "this mod allows MSL any version, older than 3.0.0".
    root = _msl_project(tmp_path, {"data/test/trial_spawner/arena.json": TRIAL}, fabric=">=9.0.0")
    passed, summary = _run(root, ["1.21.1"])
    out = capsys.readouterr().out
    assert not passed and "1 error(s)" in summary, out
    assert "accepts no MSL build published there" in out, out
    assert "this mod allows MSL" not in out, out


def test_allowlisted_key_passes_and_the_same_key_elsewhere_does_not(tmp_path, stubbed, capsys):
    harmless = {"type": "minecraft:item", "name": "minecraft:book",
                "functions": [{"function": "minecraft:enchant_with_levels", "levels": 5, "only_compatible": True}]}
    stray = {"type": "minecraft:item", "name": "minecraft:book",
             "functions": [{"function": "minecraft:set_count", "count": 1, "only_compatible": True}]}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(harmless)})
    passed, _ = _run(root, ["1.21"])
    assert passed, capsys.readouterr().out
    root2 = _project(tmp_path / "two", {"data/test/loot_table/b.json": _table(stray)})
    passed, _ = _run(root2, ["1.21"])
    assert not passed
    assert "`only_compatible` is read by no version" in capsys.readouterr().out


# --- review fixes (2026-11-08) ---------------------------------------------------------

SET3 = {"function": "minecraft:set_count", "count": 3}
ENCH = {"function": "minecraft:enchant_randomly"}


def _dual(functions, modifier):
    return {"type": "minecraft:item", "name": "minecraft:diamond", "functions": functions, "modifier": modifier}


@pytest.mark.parametrize("entry", [
    _dual([SET3], []),                                                    # 26.3 loses the count
    _dual([SET3, ENCH], [{"type": "minecraft:set_count", "count": 3}]),  # 26.3 loses the enchant
    _dual([], [{"type": "minecraft:set_count", "count": 3}]),             # 1.21-26.2 lose the count
])
def test_both_forms_present_but_disagreeing_fail(tmp_path, stubbed, capsys, entry):
    root = _project(tmp_path, {"data/test/loot_table/chest.json": _table(entry)})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert "pools[0].entries[0].modifier" in out
    assert "disagree" in out or "loses it" in out or "lose it" in out


def test_agreeing_forms_pass_whatever_their_layout(tmp_path, stubbed, capsys):
    # one modifier object for a one-item list; all_of for a condition list; 3.0 for 3
    entry = {"type": "minecraft:item", "name": "minecraft:diamond",
             "functions": [{"function": "set_count", "count": 3.0}],
             "modifier": {"type": "minecraft:set_count", "count": 3}}
    table = _table(entry, conditions=[{"condition": "minecraft:random_chance", "chance": 0.5},
                                      {"condition": "minecraft:survives_explosion"}],
                   condition={"type": "minecraft:all_of", "terms": [
                       {"type": "minecraft:random_chance", "chance": 0.5},
                       {"type": "minecraft:survives_explosion"}]})
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_library_table_edited_in_one_form_only_fails(tmp_path, stubbed, capsys):
    # The review's case on MFR intact/library.json: an enchant added to the book's
    # old form only, and the paper's 26.3 form emptied.
    book = {"type": "minecraft:item", "name": "minecraft:book",
            "functions": [{"function": "minecraft:set_count",
                           "count": {"type": "minecraft:uniform", "min": 1, "max": 3}},
                          {"function": "minecraft:enchant_randomly"}],
            "modifier": {"type": "minecraft:set_count", "count": {"type": "minecraft:uniform", "min": 1, "max": 3}}}
    paper = {"type": "minecraft:item", "name": "minecraft:diamond",
             "functions": [{"function": "minecraft:set_count",
                            "count": {"type": "minecraft:uniform", "min": 2, "max": 7}}],
             "modifier": []}
    table = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [book, paper]}]}
    root = _project(tmp_path, {"data/test/loot_table/library.json": table}, msl=True)
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert "pools[0].entries[0].modifier" in out and "enchant_randomly" in out
    assert "pools[0].entries[1].modifier" in out


def test_require_claim_fails_without_a_published_window(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {})
    ctx = FakeContext("test", ["1.21", "1.21.1"], root)
    ctx.claims, ctx.require_claim = [], True
    passed, summary = check_claimed_versions.run(ctx)
    assert not passed and "no published window" in summary
    ctx2 = FakeContext("test", ["1.21", "1.21.1"], root)
    ctx2.claims, ctx2.require_claim = ["1.21-1.21.1"], True
    passed, _ = check_claimed_versions.run(ctx2)
    assert passed


def test_github_actions_requires_a_claim(tmp_path, stubbed, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    root = _project(tmp_path, {})
    passed, _ = _run(root, ["1.21", "1.21.1"], check=check_claimed_versions)
    assert not passed
    assert "GITHUB_ACTIONS is set" in capsys.readouterr().out


SHEEP = {"condition": "minecraft:entity_properties", "entity": "this",
         "predicate": {"type_specific": {"type": "minecraft:sheep", "color": "white"}}}


def test_a_key_removed_before_the_version_is_an_error(tmp_path, stubbed, capsys):
    # The sheep colour moved into components at 1.21.5: the condition stops checking it.
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(OLD_ENTRY, conditions=[SHEEP])})
    passed, summary = _run(root, ["1.21.4", "1.21.5"])
    out = capsys.readouterr().out
    assert not passed and "on 1.21.5" in summary
    assert "`color` is ignored" in out and "removed or moved" in out


def test_a_key_that_only_arrives_later_is_a_warning(tmp_path, stubbed, capsys):
    entry = {"type": "minecraft:item", "name": "minecraft:book",
             "functions": [{"function": "minecraft:enchant_randomly", "include_additional_cost_component": True}]}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(entry)})
    passed, summary = _run(root, ["1.21.1"])
    assert passed and "warning" in summary, capsys.readouterr().out


def test_a_rewrite_newer_than_the_mods_msl_does_not_rescue(tmp_path, stubbed, monkeypatch, capsys):
    # Pretend MSL only rewrote condition lists from 9.0.0: a mod allowing 3.x gets
    # no credit for it, so the 26.3 error on the old pool conditions stands.
    monkeypatch.setitem(msl_upgrade.REWRITE_SINCE, "conditions", (9, 0, 0))
    table = _table(DUAL_ENTRY, conditions=[{"condition": "minecraft:random_chance", "chance": 0.5}])
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table}, msl=True)
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert "`conditions` is ignored" in out
    assert "[ERROR] on 26.3 this mod allows MSL" in out


def test_both_folder_spellings_each_loaded_by_their_own_versions_pass(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_tables/chest.json": _table(OLD_ENTRY),
                               "data/test/loot_table/chest.json": _table(OLD_ENTRY)})
    passed, _ = _run(root, ["1.20.6", "1.21"])
    assert passed, capsys.readouterr().out


def test_a_string_where_a_number_is_read_and_a_null_required_field_fail(tmp_path, stubbed, capsys):
    entry = {"type": "minecraft:item", "name": "minecraft:diamond",
             "functions": [{"function": "minecraft:set_count", "count": "3"}]}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(entry),
                               "data/test/loot_table/b.json": {"pools": [{"rolls": None, "entries": [OLD_ENTRY]}]},
                               "data/test/loot_table/c.json": _table(dict(OLD_ENTRY, weight=None))})
    passed, _ = _run(root, ["1.21"])
    out = capsys.readouterr().out
    assert not passed
    assert "a.json" in out and "found a string" in out
    assert "b.json" in out and "`rolls` is required" in out
    assert "c.json" not in out   # a null optional field is simply absent


def test_allowlist_matches_the_value(tmp_path, stubbed, capsys):
    false_one = {"type": "minecraft:item", "name": "minecraft:book",
                 "functions": [{"function": "minecraft:enchant_with_levels", "levels": 5, "only_compatible": False}]}
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(false_one)})
    passed, _ = _run(root, ["1.21"])
    assert not passed
    assert "`only_compatible` is read by no version" in capsys.readouterr().out


def test_unreadable_json_anywhere_under_data_fails(tmp_path, stubbed, capsys):
    res = tmp_path / "src" / "main" / "resources" / "data"
    for rel in ("test/predicate/broken.json", "minecraft/tags/worldgen/biome/x.json", "test/moogs_structures/x.json"):
        (res / rel).parent.mkdir(parents=True, exist_ok=True)
        (res / rel).write_text('{"values": ["minecraft:plains",],}', encoding="utf-8")
    passed, _ = _run(tmp_path, ["1.21"])
    out = capsys.readouterr().out
    assert not passed
    assert out.count("not valid JSON") == 3


# --- second review (2026-11-08) --------------------------------------------------------

def test_inline_table_in_set_contents_as_the_converter_writes_it_passes(tmp_path, stubbed, capsys):
    # Exactly what MFR's scripts/loot_26_3.py writes for a box holding an inline
    # table: the set_contents entries, and the table inside them, in 26.3 form only.
    inner_old = {"type": "minecraft:item", "name": "minecraft:diamond",
                 "functions": [{"function": "minecraft:set_count", "count": 2}],
                 "conditions": [{"condition": "minecraft:random_chance", "chance": 0.5}]}
    inner_new = {"type": "minecraft:item", "name": "minecraft:diamond",
                 "modifier": {"type": "minecraft:set_count", "count": 2},
                 "condition": {"type": "minecraft:random_chance", "chance": 0.5}}
    box = {"type": "minecraft:item", "name": "minecraft:stone",
           "functions": [{"function": "minecraft:set_contents", "component": "minecraft:container", "entries": [
               {"type": "minecraft:loot_table", "value": {"pools": [{"rolls": 1, "entries": [inner_old]}]}}]}],
           "modifier": {"type": "minecraft:set_contents", "component": "minecraft:container", "entries": [
               {"type": "minecraft:loot_table", "value": {"pools": [{"rolls": 1, "entries": [inner_new]}]}}]}}
    root = _project(tmp_path, {"data/test/loot_table/box.json": _table(box)})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_functions_in_another_order_say_what_differs(tmp_path, stubbed, capsys):
    entry = _dual([SET3, ENCH], [{"type": "minecraft:enchant_randomly"}, {"type": "minecraft:set_count", "count": 3}])
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(entry)})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert ("26.3 reads the same 2 functions in another order (minecraft:enchant_randomly, minecraft:set_count); "
            "the old form's `functions` runs minecraft:set_count, minecraft:enchant_randomly") in out
    assert "(absent)" not in out


def test_another_function_in_one_place_is_named(tmp_path, stubbed, capsys):
    entry = _dual([SET3], [{"type": "minecraft:enchant_randomly"}])
    root = _project(tmp_path, {"data/test/loot_table/a.json": _table(entry)})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed
    assert ("26.3 reads a minecraft:enchant_randomly here, where the old form's `functions` has a "
            "minecraft:set_count") in out
    assert "pools[0].entries[0].modifier[0]" in out


OVERLAY_PACK = {"pack": {"pack_format": 48, "supported_formats": [48, 121], "min_format": 48, "max_format": 121},
                "overlays": {"entries": [{"formats": [121, 121], "min_format": 121, "max_format": 121,
                                          "directory": "ov_26_3"}]}}


def test_forms_split_across_an_overlay_are_compared(tmp_path, stubbed, capsys):
    # The base file has the enchant; the 26.3 overlay copy of the same table lost it.
    base = _table({"type": "minecraft:item", "name": "minecraft:book", "functions": [SET3, ENCH]})
    overlay = _table({"type": "minecraft:item", "name": "minecraft:book",
                      "modifier": {"type": "minecraft:set_count", "count": 3}})
    root = _project(tmp_path, {"data/test/loot_table/t.json": base, "ov_26_3/data/test/loot_table/t.json": overlay},
                    pack=OVERLAY_PACK)
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert "ov_26_3/data/test/loot_table/t.json" in out
    assert "the old form is read from data/test/loot_table/t.json" in out
    assert "pools[0].entries[0].modifier" in out and "26.3 lacks minecraft:enchant_randomly" in out
    assert "26.3 loses it" in out


def test_an_overlay_copy_with_no_modifier_at_all_fails(tmp_path, stubbed, capsys):
    base = _table(OLD_ENTRY)
    overlay = _table({"type": "minecraft:item", "name": "minecraft:diamond"})
    root = _project(tmp_path, {"data/test/loot_table/t.json": base, "ov_26_3/data/test/loot_table/t.json": overlay},
                    pack=OVERLAY_PACK)
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert "pools[0].entries[0].modifier" in out and "26.3 reads nothing here" in out


# Across a base file and its overlay the whole table must agree (the review's
# probes e02 to e05: each passed before, at most with a warning).

BOOK = {"type": "minecraft:item", "name": "minecraft:book", "functions": [ENCH]}
BOOK_NEW = {"type": "minecraft:item", "name": "minecraft:book", "modifier": {"type": "minecraft:enchant_randomly"}}


def _overlay_fails(tmp_path, base, overlay, capsys):
    root = _project(tmp_path, {"data/test/loot_table/t.json": base, "ov_26_3/data/test/loot_table/t.json": overlay},
                    pack=OVERLAY_PACK)
    passed, summary = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "warning" not in summary, out
    return out


def test_e02_an_overlay_dropping_a_pool_fails(tmp_path, stubbed, capsys):
    base = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [OLD_ENTRY]},
                                                 {"rolls": 1, "entries": [BOOK]}]}
    out = _overlay_fails(tmp_path, base, _table(NEW_ENTRY), capsys)
    assert "at pools" in out
    assert "26.3 reads 1 pool here, where the old form has 2 (26.3 lacks a pool of minecraft:book)" in out


def test_e03_an_overlay_dropping_an_entry_fails(tmp_path, stubbed, capsys):
    base = {"type": "minecraft:chest", "pools": [{"rolls": 1, "entries": [OLD_ENTRY, BOOK]}]}
    out = _overlay_fails(tmp_path, base, _table(NEW_ENTRY), capsys)
    assert "pools[0].entries" in out
    assert "26.3 reads 1 entry here, where the old form has 2 (26.3 lacks minecraft:book): 26.3 loses it" in out


def test_e04_an_overlay_rolling_another_item_fails(tmp_path, stubbed, capsys):
    stone = dict(NEW_ENTRY, name="minecraft:stone")
    out = _overlay_fails(tmp_path, _table(OLD_ENTRY), _table(stone), capsys)
    assert "pools[0].entries[0].name" in out
    assert '26.3 reads "minecraft:stone" here, but the old form gives "minecraft:diamond"' in out


def test_e05_an_overlay_with_other_rolls_fails(tmp_path, stubbed, capsys):
    base = {"type": "minecraft:chest", "pools": [{"rolls": 3, "entries": [OLD_ENTRY]}]}
    out = _overlay_fails(tmp_path, base, _table(NEW_ENTRY), capsys)
    assert "pools[0].rolls" in out and "26.3 reads 1 here, but the old form gives 3" in out


def test_an_overlay_that_agrees_with_its_base_passes(tmp_path, stubbed, capsys):
    base = {"type": "minecraft:chest", "pools": [{"rolls": 3.0, "entries": [OLD_ENTRY, BOOK],
                                                  "conditions": [{"condition": "minecraft:random_chance",
                                                                  "chance": 0.5}]}]}
    overlay = {"type": "minecraft:chest", "pools": [{"rolls": 3, "entries": [NEW_ENTRY, BOOK_NEW],
                                                     "condition": {"type": "random_chance", "chance": 0.5}}]}
    root = _project(tmp_path, {"data/test/loot_table/t.json": base, "ov_26_3/data/test/loot_table/t.json": overlay},
                    pack=OVERLAY_PACK)
    passed, summary = _run(root, ["1.21", "26.2", "26.3"])
    assert passed and "warning" not in summary, capsys.readouterr().out


def test_a_predicate_naming_another_condition_in_each_form_fails(tmp_path, stubbed, capsys):
    # 1.21 to 26.2 read a random chance; 26.3 reads survives_explosion.
    pred = {"condition": "minecraft:random_chance", "type": "minecraft:survives_explosion", "chance": 0.5}
    root = _project(tmp_path, {"data/test/predicate/p.json": pred})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert ("26.3 reads a minecraft:survives_explosion here, where the old form's `condition` has a "
            "minecraft:random_chance") in out


def test_predicate_and_item_modifier_as_the_converter_writes_them_pass(tmp_path, stubbed, capsys):
    # Exactly what MFR's scripts/loot_26_3.py writes: both forms merged in one object.
    pred = {"condition": "minecraft:all_of", "type": "minecraft:all_of", "terms": [
        {"condition": "minecraft:random_chance", "type": "minecraft:random_chance", "chance": 0.5},
        {"condition": "minecraft:survives_explosion", "type": "minecraft:survives_explosion"}]}
    one = {"function": "minecraft:set_count", "type": "minecraft:set_count", "count": 2,
           "conditions": [{"condition": "minecraft:random_chance", "chance": 0.5}],
           "condition": {"type": "minecraft:random_chance", "chance": 0.5}}
    # (one object: 26.3 loads an item modifier file with the single-function codec, so
    # a list file, which 1.21 to 26.2 read as a sequence, is refused there)
    seq = {"function": "minecraft:sequence", "type": "minecraft:sequence", "functions": [
        {"function": "minecraft:set_count", "type": "minecraft:set_count", "count": 2},
        {"function": "minecraft:enchant_randomly", "type": "minecraft:enchant_randomly"}]}
    root = _project(tmp_path, {"data/test/predicate/p.json": pred, "data/test/item_modifier/one.json": one,
                               "data/test/item_modifier/seq.json": seq})
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_an_item_modifier_losing_its_condition_on_26_3_fails(tmp_path, stubbed, capsys):
    im = {"function": "minecraft:set_count", "type": "minecraft:set_count", "count": 2,
          "conditions": [{"condition": "minecraft:random_chance", "chance": 0.5}],
          "condition": {"type": "minecraft:random_chance", "chance": 0.25}}
    seq = {"function": "minecraft:sequence", "type": "minecraft:sequence", "functions": [
        {"function": "minecraft:set_count", "type": "minecraft:set_count", "count": 2},
        {"function": "minecraft:enchant_randomly", "type": "minecraft:set_count", "count": 2}]}
    root = _project(tmp_path, {"data/test/item_modifier/im.json": im, "data/test/item_modifier/seq.json": seq})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert "condition.chance" in out and "26.3 reads 0.25 here, but the old form's `function` gives 0.5" in out
    assert "functions[1]" in out and "where the old form's `function` has a minecraft:enchant_randomly" in out


# One test per comparison rule (each was a mutation no test caught).

def _fails_at(tmp_path, table, where, capsys):
    root = _project(tmp_path, {"data/test/loot_table/t.json": table})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert where in out, out
    return out


def test_rule_conditions_are_compared(tmp_path, stubbed, capsys):
    entry = dict(OLD_ENTRY, modifier={"type": "minecraft:set_count", "count": 3},
                 conditions=[{"condition": "minecraft:random_chance", "chance": 0.5}],
                 condition={"type": "minecraft:random_chance", "chance": 0.25})
    _fails_at(tmp_path, _table(entry), "pools[0].entries[0].condition.chance", capsys)


def test_rule_children_and_inline_tables_are_compared(tmp_path, stubbed, capsys):
    wrong = _dual([SET3], {"type": "minecraft:set_count", "count": 4})
    alternatives = {"type": "minecraft:alternatives", "children": [wrong]}
    _fails_at(tmp_path, _table(alternatives), "pools[0].entries[0].children[0].modifier[0].count", capsys)
    inline = {"type": "minecraft:loot_table", "value": {"pools": [{"rolls": 1, "entries": [wrong]}]}}
    _fails_at(tmp_path / "inline", _table(inline), "pools[0].entries[0].value.pools[0].entries[0].modifier[0].count",
              capsys)


def test_rule_pool_level_forms_are_compared(tmp_path, stubbed, capsys):
    table = _table(DUAL_ENTRY, functions=[SET3], modifier={"type": "minecraft:set_count", "count": 2})
    _fails_at(tmp_path, table, "pools[0].modifier[0].count", capsys)


NESTED_OLD = [{"function": "minecraft:sequence", "functions": [SET3, ENCH]},
              {"function": "minecraft:filtered", "item_filter": {"items": "minecraft:diamond"},
               "on_pass": {"function": "minecraft:set_count", "count": 1}},
              {"function": "minecraft:modify_contents", "component": "minecraft:container",
               "modifier": {"function": "minecraft:set_count", "count": 2}}]
NESTED_NEW = [{"type": "minecraft:sequence", "functions": [{"type": "minecraft:set_count", "count": 3},
                                                          {"type": "minecraft:enchant_randomly"}]},
              {"type": "minecraft:filtered", "item_filter": {"items": "minecraft:diamond"},
               "on_pass": {"type": "minecraft:set_count", "count": 1}},
              {"type": "minecraft:modify_contents", "component": "minecraft:container",
               "modifier": {"type": "minecraft:set_count", "count": 2}}]


def test_rule_nested_functions_are_converted(tmp_path, stubbed, capsys):
    # sequence, filtered and modify_contents hold more functions: built in 26.3 form too
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(_dual(NESTED_OLD, NESTED_NEW))})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out
    wrong = json.loads(json.dumps(NESTED_NEW))
    wrong[0]["functions"][1] = {"type": "minecraft:set_count", "count": 1}
    _fails_at(tmp_path / "wrong", _table(_dual(NESTED_OLD, wrong)), "modifier[0].functions[1]", capsys)


def test_rule_tag_entry_items_are_compared(tmp_path, stubbed, capsys):
    entry = {"type": "minecraft:tag", "name": "minecraft:logs", "expand": True, "items": "#minecraft:planks"}
    out = _fails_at(tmp_path, _table(entry), "pools[0].entries[0].items", capsys)
    assert '`name` gives "#minecraft:logs"' in out


def test_rule_map_destinations_become_tags(tmp_path, stubbed, monkeypatch, capsys):
    monkeypatch.setitem(REGISTRIES, "tag/worldgen/structure", ["on_treasure_maps"])
    old = [{"function": "minecraft:exploration_map", "destination": "minecraft:on_treasure_maps"}]
    good = {"type": "minecraft:exploration_map", "destination": "#minecraft:on_treasure_maps"}
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(_dual(old, good))})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out
    bare = {"type": "minecraft:exploration_map", "destination": "minecraft:on_treasure_maps"}
    _fails_at(tmp_path / "bare", _table(_dual(old, bare)), "modifier[0].destination", capsys)


def test_a_condition_type_without_a_namespace_reads_as_minecraft(tmp_path, stubbed, capsys):
    entry = dict(DUAL_ENTRY, conditions=[{"condition": "random_chance", "chance": 0.5}],
                 condition={"type": "random_chance", "chance": 0.5})
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(entry)})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out



# MFR's converter writes a list item modifier file as one sequence (26.3 reads one
# function per file); this is its exact output for a two-step list.
SEQUENCE_BOTH = {"function": "minecraft:sequence", "type": "minecraft:sequence", "functions": [
    {"function": "minecraft:set_count", "type": "minecraft:set_count", "count": 2,
     "conditions": [{"condition": "minecraft:random_chance", "chance": 0.5}],
     "condition": {"type": "minecraft:random_chance", "chance": 0.5}},
    {"function": "minecraft:enchant_randomly", "type": "minecraft:enchant_randomly"}]}
STEPS_OLD = [{"function": "minecraft:set_count", "count": 2,
              "conditions": [{"condition": "minecraft:random_chance", "chance": 0.5}]},
             {"function": "minecraft:enchant_randomly"}]


def test_a_list_item_modifier_written_as_one_sequence_passes_everywhere(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/item_modifier/steps.json": SEQUENCE_BOTH})
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_a_list_item_modifier_is_refused_on_26_3(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/item_modifier/steps.json": STEPS_OLD})
    passed, summary = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "on 26.3" in summary, out
    assert "found a list" in out


def test_a_list_against_a_26_3_overlay_sequence_is_compared(tmp_path, stubbed, capsys):
    # The base list is the sequence 1.21 to 26.2 run; the overlay's sequence lost a step.
    good = {"type": "minecraft:sequence", "functions": [
        {"type": "minecraft:set_count", "count": 2, "condition": {"type": "minecraft:random_chance", "chance": 0.5}},
        {"type": "minecraft:enchant_randomly"}]}
    root = _project(tmp_path, {"data/test/item_modifier/steps.json": STEPS_OLD,
                               "ov_26_3/data/test/item_modifier/steps.json": good}, pack=OVERLAY_PACK)
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out
    short = {"type": "minecraft:sequence", "functions": good["functions"][:1]}
    root = _project(tmp_path / "short", {"data/test/item_modifier/steps.json": STEPS_OLD,
                                         "ov_26_3/data/test/item_modifier/steps.json": short}, pack=OVERLAY_PACK)
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed, out
    assert "functions[1]" in out and "26.3 loses it" in out



# Round four of the review: correct overlay layouts that must pass.

def test_f01_an_older_copy_has_nothing_to_agree_with_26_3_on(tmp_path, stubbed, capsys):
    # The base is read by 1.21 to 1.21.4; an overlay for 1.21.5 to 26.3 swaps chain for
    # iron_chain in both forms. 26.3 is compared with what 26.2 reads (the overlay), not the base.
    pack = {"pack": {"pack_format": 48, "supported_formats": [48, 121], "min_format": 48, "max_format": 121},
            "overlays": {"entries": [{"formats": [71, 121], "min_format": 71, "max_format": 121,
                                      "directory": "ov_new"}]}}
    chain = dict(OLD_ENTRY, name="minecraft:chain")
    iron = dict(DUAL_ENTRY, name="minecraft:iron_chain")
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(chain),
                               "ov_new/data/test/loot_table/t.json": _table(iron)}, pack=pack)
    passed, _ = _run(root, ["1.21", "1.21.4", "1.21.5", "26.2", "26.3"])
    assert passed, capsys.readouterr().out



def test_f02_ids_without_a_namespace_read_as_minecraft(tmp_path, stubbed, capsys):
    # The game reads "diamond" as minecraft:diamond, in an overlay or beside the old form.
    bare = {"type": "item", "name": "diamond", "modifier": {"type": "set_count", "count": 3}}
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(OLD_ENTRY),
                               "ov_26_3/data/test/loot_table/t.json": _table(bare)}, pack=OVERLAY_PACK)
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out
    tag = {"type": "minecraft:tag", "name": "minecraft:logs", "expand": True, "items": "#logs"}
    root = _project(tmp_path / "tag", {"data/test/loot_table/t.json": _table(tag)})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out



GEM_POOL = {"rolls": 1, "entries": [OLD_ENTRY, BOOK]}
GEM_POOL_NEW = {"rolls": 1, "entries": [NEW_ENTRY, BOOK_NEW]}
IRON = {"type": "minecraft:item", "name": "minecraft:iron_ingot"}


def test_f03_pools_and_entries_in_another_order_pass(tmp_path, stubbed, capsys):
    # Pool order, and entry order in a pool, do not change what a chest rolls.
    base = {"type": "minecraft:chest", "pools": [GEM_POOL, {"rolls": 2, "entries": [IRON]}]}
    overlay = {"type": "minecraft:chest", "pools": [{"rolls": 2, "entries": [IRON]},
                                                    {"rolls": 1, "entries": [BOOK_NEW, NEW_ENTRY]}]}
    root = _project(tmp_path, {"data/test/loot_table/t.json": base, "ov_26_3/data/test/loot_table/t.json": overlay},
                    pack=OVERLAY_PACK)
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_f03_a_change_in_a_moved_pool_is_still_found(tmp_path, stubbed, capsys):
    base = {"type": "minecraft:chest", "pools": [GEM_POOL, {"rolls": 2, "entries": [IRON]}]}
    overlay = {"type": "minecraft:chest", "pools": [{"rolls": 3, "entries": [IRON]}, GEM_POOL_NEW]}
    out = _overlay_fails(tmp_path, base, overlay, capsys)
    assert "pools[0].rolls" in out and "26.3 reads 3 here, but the old form gives 2" in out
    moved = {"type": "minecraft:chest", "pools": [{"rolls": 2, "entries": [IRON]},
                                                  {"rolls": 1, "entries": [BOOK_NEW]}]}
    out = _overlay_fails(tmp_path / "lost", base, moved, capsys)
    assert "pools[1].entries" in out and "26.3 lacks minecraft:diamond" in out



# --- MSL versions as each loader reads them ---------------------------------------------

@pytest.mark.parametrize("spec, version, ok", [
    (">=1.1.0", "1.1.0-1.20-1.20.4", False),     # a pre-release of 1.1.0 to Fabric
    (">=1.1.0-0", "1.1.0-1.20-1.20.4", True),
    (">=1.1.0-0", "1.0.2-1.21.4-fabric", False),
    ("*", "1.0.0-fabric", True),
    (">=3.3.0", "3.3.0+fabric", True),          # build metadata is ignored
    (">=2.0.2", "2.0.2-fabric", False),
    ("^3.0.0", "3.9.1+fabric", True),
    ("^3.0.0", "4.0.0", False),
    (">=3.0.0 <3.4.0", "3.4.0", False),
])
def test_fabric_reads_msl_versions_as_semantic_versions(spec, version, ok):
    assert msl_upgrade.fabric_accepts(spec, version) is ok


@pytest.mark.parametrize("spec, version, ok", [
    ("[1.1.0,)", "1.1.0-1.20-1.20.4", True),    # a numeric qualifier sorts above the release
    ("[3.2.0,)", "3.2.0-alpha.1", False),
    ("[1.0,2.0)", "2.0.0", False),
    ("1.0", "0.1", True),                       # a bare version only recommends
])
def test_forge_reads_msl_versions_as_maven_versions(spec, version, ok):
    assert msl_upgrade.maven_accepts(spec, version) is ok


def _fabric_dep(root: Path, fabric: str) -> Path:
    res = root / "src" / "main" / "resources"
    _write(res / "fabric.mod.json", {"id": "test", "depends": {"moogs_structures": fabric}})
    (res / "data" / "test").mkdir(parents=True, exist_ok=True)
    return root


def test_the_oldest_build_a_predicate_accepts_is_the_msl_it_runs_with(tmp_path):
    b = msl_upgrade.MslBuilds()
    star, _ = msl_upgrade.declared_minimum(_fabric_dep(tmp_path / "a", "*"))
    plain, _ = msl_upgrade.declared_minimum(_fabric_dep(tmp_path / "b", ">=1.1.0"))
    dash, _ = msl_upgrade.declared_minimum(_fabric_dep(tmp_path / "c", ">=1.1.0-0"))
    assert b.effective("1.21.1", star) == (1, 0, 0)
    assert b.effective("1.21.1", dash) == (1, 1, 0)
    assert b.effective("1.21.1", plain) > (1, 1, 0)   # every 1.1.0 build there is passed over
    assert b.passed_over("1.20.1", plain) == [("fabric.mod.json `>=1.1.0`", "1.1.0")]
    assert b.passed_over("1.20.1", dash) == []


def test_a_minimum_no_build_meets_is_an_error(tmp_path, stubbed, capsys):
    root = _fabric_dep(tmp_path, ">=9.0.0")
    passed, summary = _run(root, ["1.21", "1.21.1"])
    out = capsys.readouterr().out
    assert not passed and "error" in summary, out
    assert "[ERROR] on 1.21-1.21.1 fabric.mod.json `>=9.0.0` accepts no MSL build" in out


def test_a_minimum_that_passes_over_its_own_release_warns(tmp_path, stubbed, capsys):
    root = _fabric_dep(tmp_path, ">=1.1.0")
    passed, summary = _run(root, ["1.21", "1.21.1"])
    out = capsys.readouterr().out
    assert passed and "warning" in summary, out
    assert "fabric.mod.json `>=1.1.0` rejects the MSL 1.1.0 builds there" in out
    assert "Write `>=1.1.0-0` to accept them" in out



def test_loader_files_that_meet_no_build_are_one_error_naming_the_newest(tmp_path, stubbed, capsys):
    # MSL 3.1.2 and later stop at 1.21.8 on one line and start at 1.21.10 on the next,
    # so a mod asking for 3.3.0 has nothing to run with on 1.21.9 (1.21.4 here stands in).
    root = _fabric_dep(tmp_path, ">=9.0.0")
    res = root / "src" / "main" / "resources"
    _write(res / "quilt.mod.json", {"quilt_loader": {"id": "test", "depends": [
        {"id": "moogs_structures", "versions": ">=9.0.0"}]}})
    passed, summary = _run(root, ["1.21.4"])
    out = capsys.readouterr().out
    assert not passed and "1 error(s)" in summary, out
    assert ("[ERROR] on 1.21.4 fabric.mod.json `>=9.0.0`, quilt.mod.json `>=9.0.0` accept no MSL build published "
            "there (the newest is ") in out
    assert "so no player can run the mod there" in out


def test_no_msl_line_where_no_build_the_mod_accepts_exists(tmp_path, stubbed, capsys):
    # R3's M12b: capped below MSL's first 26.3 build, the mod runs nowhere on 26.3, so
    # nothing says it runs there with some MSL; the refusal says why.
    table = {"type": "minecraft:chest", "pools": [{"rolls": {"min": 1, "max": 3}, "entries": [DUAL_ENTRY]}]}
    root = _project(tmp_path, {"data/test/loot_table/chest.json": table})
    _fabric_dep(root, ">=3.0.0 <3.3.0")
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "accepts no MSL build published there" in out, out
    assert "it runs with MSL" not in out, out
    root = _project(tmp_path / "open", {"data/test/loot_table/chest.json": table})
    _fabric_dep(root, ">=3.0.0")
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert passed and "on 26.3 it runs with MSL 3.3.0 or newer" in out, out



# --- 26.3 treasure maps --------------------------------------------------------------------
# On 26.3 exploration_map writes the map onto the item it is given, so a plain
# minecraft:map stays blank; vanilla names each map's own item (buried_treasure_map
# for #minecraft:on_treasure_maps) and keeps only filled maps.

MAP_OLD = {"function": "minecraft:exploration_map", "destination": "minecraft:on_treasure_maps",
           "decoration": "red_x", "zoom": 1, "skip_existing_chunks": False}
MAP_NEW = {"type": "minecraft:exploration_map", "destination": "#minecraft:on_treasure_maps",
           "decoration": "red_x", "zoom": 1, "skip_existing_chunks": False}
KEEP_FILLED = {"type": "minecraft:filtered", "item_filter": {"predicates": {"minecraft:map_id": {}}},
               "on_fail": {"type": "minecraft:discard"}}
SET_TREASURE = {"type": "minecraft:set_item", "item": "minecraft:buried_treasure_map"}


def _map_entry(modifier, name="minecraft:map", functions=(MAP_OLD,)):
    e = {"type": "minecraft:item", "name": name, "modifier": modifier}
    if functions is not None:
        e["functions"] = list(functions)
    return e


@pytest.fixture
def map_tags(monkeypatch):
    monkeypatch.setitem(REGISTRIES, "tag/worldgen/structure", ["on_treasure_maps"])


def test_a_map_written_as_mos_does_passes(tmp_path, stubbed, map_tags, capsys):
    # MOS 5671664: minecraft:map in both forms; the 26.3 form sets the treasure map first.
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(_map_entry([SET_TREASURE, MAP_NEW, KEEP_FILLED]))})
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_a_plain_map_on_26_3_is_blank_and_said_once(tmp_path, stubbed, map_tags, capsys):
    # MOS before 5671664: the 26.3 form only renamed the keys.
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(_map_entry(MAP_NEW))})
    passed, summary = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "1 error(s) on 26.3" in summary, out
    assert "so this gives a blank map" in out
    assert "set_item minecraft:buried_treasure_map, the one vanilla uses for #minecraft:on_treasure_maps" in out
    assert "disagree" not in out and "loses it" not in out   # not again as a disagreement


def test_only_26_3_a_plain_map_fails_and_vanillas_layout_passes(tmp_path, stubbed, map_tags, capsys):
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(_map_entry(MAP_NEW, functions=None))})
    passed, _ = _run(root, ["26.3"])
    assert not passed and "blank map" in capsys.readouterr().out
    vanilla = _map_entry([MAP_NEW, KEEP_FILLED], name="minecraft:buried_treasure_map", functions=None)
    root = _project(tmp_path / "vanilla", {"data/test/loot_table/t.json": _table(vanilla)})
    passed, _ = _run(root, ["26.3"])
    assert passed, capsys.readouterr().out


def test_a_destination_vanilla_has_no_map_for_takes_any_map_item(tmp_path, stubbed, capsys):
    old = dict(MAP_OLD, destination="test:ruins")
    new = dict(MAP_NEW, destination="#test:ruins")
    files = {"data/test/tags/worldgen/structure/ruins.json": {"values": []}}
    camp = {"type": "minecraft:set_item", "item": "minecraft:abandoned_camp_map"}
    root = _project(tmp_path, dict(files, **{"data/test/loot_table/t.json": _table(
        _map_entry([camp, new, KEEP_FILLED], functions=[old]))}))
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out
    root = _project(tmp_path / "blank", dict(files, **{"data/test/loot_table/t.json": _table(
        _map_entry(new, functions=[old]))}))
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "set_item a map item" in out, out


def test_an_overlay_map_with_the_steps_passes(tmp_path, stubbed, map_tags, capsys):
    base = _table({"type": "minecraft:item", "name": "minecraft:map", "functions": [MAP_OLD]})
    overlay = _table(_map_entry([SET_TREASURE, MAP_NEW, KEEP_FILLED], functions=None))
    root = _project(tmp_path, {"data/test/loot_table/t.json": base, "ov_26_3/data/test/loot_table/t.json": overlay},
                    pack=OVERLAY_PACK)
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_the_converter_puts_the_map_steps_around_exploration_map():
    from core.loot_forms import Converter
    conv = Converter({"minecraft:on_treasure_maps"})
    named = {"function": "minecraft:set_name", "name": "Treasure"}
    got = conv.entry_function_list({"type": "minecraft:item", "name": "minecraft:map"}, [MAP_OLD, named])
    assert [f["type"] for f in got] == ["minecraft:set_item", "minecraft:exploration_map", "minecraft:filtered",
                                        "minecraft:set_name"]
    assert got[0]["item"] == "minecraft:buried_treasure_map"
    plain = conv.entry_function_list({"type": "minecraft:item", "name": "minecraft:compass"}, [MAP_OLD])
    assert plain["type"] == "minecraft:exploration_map"


# --- a loot function argument in the wrong shape ---------------------------------------------
# MES's lore book wrote set_written_book_pages' `mode` as {"type": "replace_all"}. Every version
# reads a plain string there; the game refused the table, and as the treasure tables point at
# it, the whole loot registry, so MES's datapack did not load at all.

PAGES = [{"text": "The fleet drifts forever."}]


def _book(mode):
    return {"type": "minecraft:item", "name": "minecraft:book",
            "functions": [{"function": "minecraft:set_written_book_pages", "pages": PAGES, "mode": mode}],
            "modifier": [{"type": "minecraft:set_written_book_pages", "pages": PAGES, "mode": mode}]}


def test_a_book_page_mode_written_as_an_object_fails_on_every_version(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_table/lore.json": _table(_book({"type": "replace_all"}))})
    passed, summary = _run(root, ["1.21", "26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "on 1.21, 26.2-26.3" in summary, out
    assert "on 1.21, 26.2: one of a fixed set of values is read here, found an object" in out, out
    assert "at pools[0].entries[0].functions[0].mode" in out and "at pools[0].entries[0].modifier[0].mode" in out


def test_a_book_page_mode_written_as_a_string_passes(tmp_path, stubbed, capsys):
    root = _project(tmp_path, {"data/test/loot_table/lore.json": _table(_book("replace_all"))})
    passed, _ = _run(root, ["1.21", "26.2", "26.3"])
    assert passed, capsys.readouterr().out


@pytest.mark.parametrize("function, key, bad", [
    ({"function": "minecraft:set_count", "count": 3}, "count", "3"),
    ({"function": "minecraft:enchant_randomly", "options": "#minecraft:on_random_loot"}, "options",
     {"type": "#minecraft:on_random_loot"}),
    ({"function": "minecraft:exploration_map", "destination": "#minecraft:on_treasure_maps", "zoom": 2},
     "zoom", "2"),
    ({"function": "minecraft:set_book_cover", "title": "T", "author": "A", "generation": 0}, "generation", "0"),
    ({"function": "minecraft:set_name", "name": {"text": "Map"}, "target": "item_name"}, "target",
     {"type": "item_name"}),
])
def test_function_arguments_the_mods_write_fail_in_the_wrong_shape(tmp_path, stubbed, capsys, function, key, bad):
    entry = {"type": "minecraft:item", "name": "minecraft:book", "functions": [function]}
    root = _project(tmp_path, {"data/test/loot_table/good.json": _table(entry)})
    assert _run(root, ["1.21"])[0], capsys.readouterr().out
    entry["functions"] = [{**function, key: bad}]
    root = _project(tmp_path, {"data/test/loot_table/good.json": _table(entry)})
    passed, _ = _run(root, ["1.21"])
    out = capsys.readouterr().out
    assert not passed and f"at pools[0].entries[0].functions[0].{key}" in out, out


# --- what a 26.3 modifier can be ------------------------------------------------------------
# A function, a list of functions or an item modifier id: a number or a boolean is none of
# them, alone or in a list, and 26.3 rejects the file (JsonOps reads no number as a string).

SET2 = {"type": "minecraft:set_count", "count": 2}


@pytest.mark.parametrize("modifier, at, found", [
    (5, "modifier", "a number"),
    (True, "modifier", "a boolean"),
    ([5], "modifier[0]", "a number"),
    ([SET2, 5], "modifier[1]", "a number"),
])
def test_a_26_3_modifier_that_is_no_function_or_id_fails_on_26_3(tmp_path, stubbed, capsys, modifier, at, found):
    entry = {"type": "minecraft:item", "name": "minecraft:diamond", "modifier": modifier}
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(entry)})
    passed, summary = _run(root, ["26.3"])
    out = capsys.readouterr().out
    assert not passed and "1 error(s) on 26.3" in summary, out
    assert f"is read here, found {found}" in out and "an id" in out, out
    assert f"at pools[0].entries[0].{at}" in out, out


def test_a_number_beside_a_good_old_form_fails_on_26_3_itself(tmp_path, stubbed, capsys):
    entry = {"type": "minecraft:item", "name": "minecraft:diamond",
             "functions": [{"function": "minecraft:set_count", "count": 2}], "modifier": [SET2, 7]}
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(entry)})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "on 26.3: an id or an object is read here, found a number" in out, out


def test_a_condition_or_modifier_named_by_id_still_passes(tmp_path, stubbed, capsys):
    entry = {"type": "minecraft:item", "name": "minecraft:diamond", "modifier": ["test:extra", SET2],
             "condition": "test:sometimes"}
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(entry)})
    passed, _ = _run(root, ["26.3"])
    assert passed, capsys.readouterr().out


# --- treasure maps on a pool or the whole table, and maps by chance -------------------------
# R2's planted pool: exploration_map on the pool, a plain minecraft:map entry under it.

PLAIN_MAP = {"type": "minecraft:item", "name": "minecraft:map"}
CHANCE_OLD = [{"condition": "minecraft:random_chance", "chance": 0.5}]
CHANCE_NEW = {"type": "minecraft:random_chance", "chance": 0.5}


def test_a_pool_level_map_on_a_plain_map_is_blank_on_26_3(tmp_path, stubbed, map_tags, capsys):
    table = {"pools": [{"rolls": 1, "functions": [MAP_OLD], "modifier": MAP_NEW, "entries": [PLAIN_MAP]}]}
    root = _project(tmp_path, {"data/test/loot_table/t.json": table})
    passed, summary = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "1 error(s) on 26.3" in summary, out
    assert "this exploration_map runs on the plain minecraft:map from pools[0].entries[0]" in out, out
    assert "Move it onto the map entry" in out and "set_item minecraft:buried_treasure_map" in out, out
    assert "at pools[0].modifier" in out, out


def test_a_table_level_map_on_a_plain_map_is_blank_on_26_3(tmp_path, stubbed, map_tags, capsys):
    pool = {"rolls": 1, "entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}, PLAIN_MAP]}
    table = {"functions": [MAP_OLD], "modifier": MAP_NEW, "pools": [pool]}
    root = _project(tmp_path, {"data/test/loot_table/t.json": table})
    passed, _ = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "the plain minecraft:map from pools[0].entries[1]" in out, out
    assert "\n        at modifier\n" in out, out


def test_a_pool_level_map_on_an_entry_that_sets_its_map_item_passes(tmp_path, stubbed, map_tags, capsys):
    entry = dict(PLAIN_MAP, modifier=SET_TREASURE)
    table = {"pools": [{"rolls": 1, "modifier": [MAP_NEW, KEEP_FILLED], "entries": [entry]}]}
    root = _project(tmp_path, {"data/test/loot_table/t.json": table})
    passed, _ = _run(root, ["26.3"])
    assert passed, capsys.readouterr().out


def test_a_map_by_chance_no_longer_gives_the_empty_map_on_26_3(tmp_path, stubbed, map_tags, capsys):
    # Before 26.3 a failed chance leaves a plain empty map; the 26.3 form has already set
    # the map item, so the filter throws it away and the entry gives nothing.
    old = dict(MAP_OLD, conditions=CHANCE_OLD)
    new = [SET_TREASURE, dict(MAP_NEW, condition=CHANCE_NEW), KEEP_FILLED]
    root = _project(tmp_path, {"data/test/loot_table/t.json": _table(_map_entry(new, functions=[old]))})
    passed, summary = _run(root, ["26.2", "26.3"])
    out = capsys.readouterr().out
    assert not passed and "1 error(s) on 26.3" in summary, out
    assert "this exploration_map has a condition" in out and "a failed condition gives nothing: the filter after it throws" in out, out
    assert "Put the condition on the entry instead" in out, out
    # with the chance on the entry, both forms give a filled map or nothing
    entry = dict(_map_entry([SET_TREASURE, MAP_NEW, KEEP_FILLED]), conditions=CHANCE_OLD, condition=CHANCE_NEW)
    root = _project(tmp_path / "moved", {"data/test/loot_table/t.json": _table(entry)})
    passed, _ = _run(root, ["26.2", "26.3"])
    assert passed, capsys.readouterr().out


def test_blank_maps_follow_the_items_through_each_level():
    from core.loot_forms import blank_maps
    inner = {"pools": [{"rolls": 1, "entries": [PLAIN_MAP]}]}
    nested = {"pools": [{"rolls": 1, "modifier": MAP_NEW, "entries": [
        {"type": "minecraft:alternatives", "children": [{"type": "minecraft:loot_table", "value": inner}]}]}]}
    assert [w for w, _ in blank_maps(nested)] == ["pools[0].modifier"]
    said_once = {"pools": [{"rolls": 1, "modifier": MAP_NEW, "entries": [dict(PLAIN_MAP, modifier=MAP_NEW)]}]}
    assert [w for w, _ in blank_maps(said_once)] == ["pools[0].entries[0].modifier"]
    compass = {"pools": [{"rolls": 1, "modifier": MAP_NEW,
                          "entries": [{"type": "minecraft:item", "name": "minecraft:compass"}]}]}
    assert blank_maps(compass) == []
    unfiltered = {"pools": [{"rolls": 1, "entries": [dict(PLAIN_MAP, modifier=[
        SET_TREASURE, dict(MAP_NEW, condition=CHANCE_NEW)])]}]}
    assert "a map item with no map on it" in blank_maps(unfiltered)[0][1]
    by_chance_on_the_pool = {"pools": [{"rolls": 1, "modifier": [dict(MAP_NEW, condition=CHANCE_NEW), KEEP_FILLED],
                                        "entries": [dict(PLAIN_MAP, modifier=SET_TREASURE)]}]}
    assert [w for w, m in blank_maps(by_chance_on_the_pool) if "has a condition" in m] == ["pools[0].modifier"]
