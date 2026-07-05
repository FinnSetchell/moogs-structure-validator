"""End-to-end fixture tests. Each test builds a mini datapack in a tmp dir,
writes real .nbt / pool.json files, monkeypatches network calls, and invokes
a check module's `run` against a FakeContext, asserting on the returned
(passed, summary) tuple and the check's exit signal."""
from __future__ import annotations

from pathlib import Path

import nbtlib
from nbtlib import Compound, Int, List, String

from tests.nbt_helpers import (
    FakeContext,
    build_datapack,
    entity_entry,
    block_entry,
    save,
    stub_registries,
    structure_nbt,
    versioned_element,
    write_pool,
)


def _wire(pool_path: Path, structure_ref: str, locations: dict[str, str]) -> None:
    write_pool(pool_path, [versioned_element(structure_ref, locations)])


# ---------- check_entity_equipment_shape ----------

def test_equipment_legacy_key_on_1_21_5_target_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"}, items={"minecraft:iron_sword"})

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "HandItems": List[Compound]([
            Compound({"id": String("minecraft:iron_sword"), "count": Int(1)}),
            Compound({}),
        ]),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21.5-1.21.11": "test:z"})

    from checks import check_entity_equipment_shape as mod
    ctx = FakeContext("test", ["1.21.5", "1.21.6", "1.21.7", "1.21.8", "1.21.9",
                                "1.21.10", "1.21.11"], root)
    passed, summary = mod.run(ctx)
    assert not passed
    assert "HandItems" in summary or "equipment" in summary or "error" in summary


def test_equipment_new_key_on_1_21_4_target_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"}, items={"minecraft:iron_sword"})

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "equipment": Compound({
            "mainhand": Compound({"id": String("minecraft:iron_sword"), "count": Int(1)}),
        }),
    })
    nbt = structure_nbt(4189, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21-1.21.4": "test:z"})

    from checks import check_entity_equipment_shape as mod
    ctx = FakeContext("test", ["1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_equipment_correct_shape_passes(tmp_path, monkeypatch, capsys):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"}, items={"minecraft:iron_sword"})

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "HandItems": List[Compound]([
            Compound({"id": String("minecraft:iron_sword"), "count": Int(1)}),
            Compound({}),
        ]),
    })
    nbt = structure_nbt(4189, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21-1.21.4": "test:z"})

    from checks import check_entity_equipment_shape as mod
    ctx = FakeContext("test", ["1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4"], root)
    passed, _ = mod.run(ctx)
    assert passed


# ---------- check_book_contents ----------

def test_book_json_string_page_on_1_21_5_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:item_frame"}, items={"minecraft:written_book"})

    frame = Compound({
        "id": String("minecraft:item_frame"),
        "Item": Compound({
            "id": String("minecraft:written_book"),
            "count": Int(1),
            "components": Compound({
                "minecraft:written_book_content": Compound({
                    "pages": List[String]([String('{"text":"Hi"}')]),
                    "title": Compound({"raw": String("t")}),
                    "author": String("a"),
                }),
            }),
        }),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(frame)])
    save(nbt, structures / "b.nbt")
    _wire(pools / "p.json", "test:b", {"1.21.5-1.21.11": "test:b"})

    from checks import check_book_contents as mod
    ctx = FakeContext("test", ["1.21.5", "1.21.11"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_book_bare_string_page_on_1_21_5_passes(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:item_frame"}, items={"minecraft:written_book"})

    frame = Compound({
        "id": String("minecraft:item_frame"),
        "Item": Compound({
            "id": String("minecraft:written_book"),
            "count": Int(1),
            "components": Compound({
                "minecraft:written_book_content": Compound({
                    "pages": List[String]([String("Hello world")]),
                }),
            }),
        }),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(frame)])
    save(nbt, structures / "b.nbt")
    _wire(pools / "p.json", "test:b", {"1.21.5-1.21.11": "test:b"})

    from checks import check_book_contents as mod
    ctx = FakeContext("test", ["1.21.5", "1.21.11"], root)
    passed, _ = mod.run(ctx)
    assert passed


# ---------- check_text_components ----------

def test_json_custom_name_on_1_21_5_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"})

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "CustomName": String('{"text":"Bob"}'),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21.5-1.21.11": "test:z"})

    from checks import check_text_components as mod
    ctx = FakeContext("test", ["1.21.5", "1.21.11"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_bare_custom_name_on_1_21_5_passes(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"})

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "CustomName": String("Bob"),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21.5-1.21.11": "test:z"})

    from checks import check_text_components as mod
    ctx = FakeContext("test", ["1.21.5", "1.21.11"], root)
    passed, _ = mod.run(ctx)
    assert passed


# ---------- check_version_coverage ----------

def test_coverage_gap_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch)
    nbt = structure_nbt(4325)
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21-1.21.4": "test:z"})

    from checks import check_version_coverage as mod
    # 1.21.5 and 1.21.6 uncovered -> FAIL
    ctx = FakeContext("test", ["1.21", "1.21.4", "1.21.5", "1.21.6"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_coverage_full_passes(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch)
    nbt = structure_nbt(4325)
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {
        "1.21-1.21.4": "test:z",
        "1.21.5-1.21.6": "test:z",
    })

    from checks import check_version_coverage as mod
    ctx = FakeContext("test", ["1.21", "1.21.4", "1.21.5", "1.21.6"], root)
    passed, _ = mod.run(ctx)
    assert passed


def test_coverage_inverted_range_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch)
    nbt = structure_nbt(4325)
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21.4-1.21": "test:z"})

    from checks import check_version_coverage as mod
    ctx = FakeContext("test", ["1.21", "1.21.4"], root)
    passed, _ = mod.run(ctx)
    assert not passed


# ---------- check_attribute_ids ----------

def test_attribute_prefix_on_1_21_2_target_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"},
                    attributes={"minecraft:max_health"})  # 1.21.2+ registry uses unprefixed

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "attributes": List[Compound]([
            Compound({"id": String("minecraft:generic.max_health"), "base": Int(20)}),
        ]),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21.2-1.21.11": "test:z"})

    from checks import check_attribute_ids as mod
    ctx = FakeContext("test", ["1.21.2", "1.21.11"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_attribute_unprefixed_on_pre_1_21_2_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:zombie"},
                    attributes={"minecraft:generic.max_health"})  # pre-1.21.2 uses prefixed

    zombie = Compound({
        "id": String("minecraft:zombie"),
        "attributes": List[Compound]([
            Compound({"id": String("minecraft:max_health"), "base": Int(20)}),
        ]),
    })
    nbt = structure_nbt(3953, entities=[entity_entry(zombie)])
    save(nbt, structures / "z.nbt")
    _wire(pools / "p.json", "test:z", {"1.21-1.21.1": "test:z"})

    from checks import check_attribute_ids as mod
    ctx = FakeContext("test", ["1.21", "1.21.1"], root)
    passed, _ = mod.run(ctx)
    assert not passed


# ---------- check_potion_effects ----------

def test_potion_tag_effects_on_1_21_5_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:item_frame"}, items={"minecraft:potion"})

    frame = Compound({
        "id": String("minecraft:item_frame"),
        "Item": Compound({
            "id": String("minecraft:potion"),
            "count": Int(1),
            "tag": Compound({
                "custom_potion_effects": List[Compound]([
                    Compound({"id": String("minecraft:speed"), "amplifier": Int(0), "duration": Int(200)}),
                ]),
            }),
        }),
    })
    nbt = structure_nbt(4325, entities=[entity_entry(frame)])
    save(nbt, structures / "p.nbt")
    _wire(pools / "p.json", "test:p", {"1.21.5-1.21.11": "test:p"})

    from checks import check_potion_effects as mod
    ctx = FakeContext("test", ["1.21.5", "1.21.11"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_potion_components_on_pre_1_20_5_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:item_frame"}, items={"minecraft:potion"})

    frame = Compound({
        "id": String("minecraft:item_frame"),
        "Item": Compound({
            "id": String("minecraft:potion"),
            "count": Int(1),
            "components": Compound({
                "minecraft:potion_contents": Compound({
                    "custom_effects": List[Compound]([
                        Compound({"id": String("minecraft:speed")}),
                    ]),
                }),
            }),
        }),
    })
    nbt = structure_nbt(3700, entities=[entity_entry(frame)])
    save(nbt, structures / "p.nbt")
    _wire(pools / "p.json", "test:p", {"1.20-1.20.4": "test:p"})

    from checks import check_potion_effects as mod
    ctx = FakeContext("test", ["1.20", "1.20.4"], root)
    passed, _ = mod.run(ctx)
    assert not passed


# ---------- check_entity_nbt_keys (range-aware) ----------

def test_painting_motive_on_1_21_target_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:painting"})

    painting = Compound({
        "id": String("minecraft:painting"),
        "Motive": String("minecraft:kebab"),
    })
    nbt = structure_nbt(3953, entities=[entity_entry(painting)])
    save(nbt, structures / "p.nbt")
    _wire(pools / "p.json", "test:p", {"1.21-1.21.1": "test:p"})

    from checks import check_entity_nbt_keys as mod
    ctx = FakeContext("test", ["1.21", "1.21.1"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_painting_variant_on_pre_1_21_target_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:painting"})

    painting = Compound({
        "id": String("minecraft:painting"),
        "variant": String("minecraft:kebab"),
    })
    nbt = structure_nbt(3700, entities=[entity_entry(painting)])
    save(nbt, structures / "p.nbt")
    _wire(pools / "p.json", "test:p", {"1.20-1.20.4": "test:p"})

    from checks import check_entity_nbt_keys as mod
    ctx = FakeContext("test", ["1.20", "1.20.4"], root)
    passed, _ = mod.run(ctx)
    assert not passed


def test_wolf_variant_spanning_1_20_5_fails(tmp_path, monkeypatch):
    root, structures, pools = build_datapack(tmp_path)
    stub_registries(monkeypatch, entities={"minecraft:wolf"})

    wolf = Compound({
        "id": String("minecraft:wolf"),
        "variant": String("minecraft:pale"),
    })
    nbt = structure_nbt(3837, entities=[entity_entry(wolf)])
    save(nbt, structures / "w.nbt")
    _wire(pools / "p.json", "test:w", {"1.20-1.20.6": "test:w"})

    from checks import check_entity_nbt_keys as mod
    ctx = FakeContext("test", ["1.20", "1.20.4", "1.20.5", "1.20.6"], root)
    passed, _ = mod.run(ctx)
    assert not passed
