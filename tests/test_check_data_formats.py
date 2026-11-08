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
                           "filtered", "modify_contents", "exploration_map"],
    "loot_condition_type": ["random_chance", "survives_explosion", "all_of", "any_of", "inverted",
                            "entity_properties"],
    "item": ["diamond", "book", "iron_ingot", "stone"],
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
