"""core.nbt: the structure parser and the per-file index.

Files are written with nbtlib (the reference implementation the parser is
verified against) and read back with core.nbt.
"""
from __future__ import annotations

import gzip
import io
from array import array

import nbtlib
import pytest
from nbtlib import Byte, ByteArray, Compound, Double, Int, IntArray, List, Long, LongArray, String

from core.nbt import Blocks, decode_string, load_structure, parse_bytes, parse_structure
from tests.nbt_helpers import _int_list, block_entry, entity_entry, save, structure_nbt


def _chest(loot: str) -> Compound:
    return Compound({"id": String("minecraft:chest"), "LootTable": String(loot)})


def _spawner(entity: Compound) -> Compound:
    return Compound({
        "id": String("minecraft:spawner"),
        "SpawnData": Compound({"entity": entity}),
        "SpawnPotentials": List[Compound]([Compound({"data": Compound({"entity": entity}), "weight": Int(1)})]),
    })


def _zombie(rider: Compound | None = None) -> Compound:
    z = Compound({"id": String("minecraft:zombie")})
    if rider is not None:
        z["Passengers"] = List[Compound]([rider])
    return z


def test_plain_blocks_and_block_entities_are_indexed(tmp_path):
    palette = [Compound({"Name": String("minecraft:stone")}), Compound({"Name": String("minecraft:chest")})]
    blocks = [
        block_entry(0, pos=(0, 0, 0)),
        block_entry(1, pos=(1, 2, 3), nbt=_chest("test:a")),
        block_entry(0, pos=(4, 5, 6)),
        block_entry(1, pos=(7, 8, 9), nbt=_chest("test:b")),
    ]
    path = tmp_path / "s.nbt"
    save(structure_nbt(4325, blocks=blocks, palette=palette, size=(10, 10, 10)), path)

    s = load_structure(path)
    assert s.data_version == 4325
    assert s.root["size"] == [10, 10, 10]
    assert s.palette_names() == ["minecraft:stone", "minecraft:chest"]
    assert len(s.blocks) == 4
    assert list(s.blocks.states) == [0, 1, 0, 1]
    assert s.blocks.pos_of(2) == (4, 5, 6)
    assert [(be.index, be.state, be.pos, be.nbt["LootTable"]) for be in s.block_entities] == [
        (1, 1, (1, 2, 3), "test:a"),
        (3, 1, (7, 8, 9), "test:b"),
    ]
    assert list(s.blocks_in_states({1})) == [
        (1, 1, (1, 2, 3), s.block_entities[0].nbt),
        (3, 1, (7, 8, 9), s.block_entities[1].nbt),
    ]
    assert list(s.blocks_in_states({0})) == [(0, 0, (0, 0, 0), None), (2, 0, (4, 5, 6), None)]
    assert s.loot_table_refs() == {"test:a", "test:b"}


def test_block_entry_with_unusual_key_order_parses_the_same(tmp_path):
    # The game writes pos, state, nbt; other tools may not. Both must index alike.
    reordered = Compound({"state": Int(0), "pos": _int_list(3, 2, 1)})
    reordered_with_nbt = Compound({"nbt": _chest("test:c"), "state": Int(0), "pos": _int_list(9, 9, 9)})
    path = tmp_path / "s.nbt"
    save(structure_nbt(4325, blocks=[reordered, reordered_with_nbt], size=(10, 10, 10)), path)

    s = load_structure(path)
    assert list(s.blocks.states) == [0, 0]
    assert s.blocks.pos_of(0) == (3, 2, 1)
    assert s.blocks.odd == {}
    assert [(be.index, be.pos) for be in s.block_entities] == [(1, (9, 9, 9))]


def test_malformed_block_entry_is_kept_in_odd(tmp_path):
    no_state = Compound({"pos": _int_list(1, 1, 1)})
    bad_pos = Compound({"state": Int(0), "pos": List[Int]([Int(1)])})
    path = tmp_path / "s.nbt"
    save(structure_nbt(4325, blocks=[block_entry(0), no_state, bad_pos]), path)

    s = load_structure(path)
    assert len(s.blocks) == 3
    assert s.blocks.state_of(1) == -1
    assert s.blocks.pos_of(1) == (1, 1, 1)
    assert s.blocks.state_of(2) == 0
    assert s.blocks.pos_of(2) == (1,)
    assert set(s.blocks.odd) == {1, 2}


def test_entities_riders_and_spawner_data_are_walked_in_file_order(tmp_path):
    rider = Compound({"id": String("minecraft:skeleton")})
    palette = [Compound({"Name": String("minecraft:spawner")})]
    blocks = [block_entry(0, pos=(0, 0, 0), nbt=_spawner(_zombie()))]
    path = tmp_path / "s.nbt"
    save(structure_nbt(4325, entities=[entity_entry(_zombie(rider))], blocks=blocks, palette=palette), path)

    s = load_structure(path)
    assert [(e["id"], p) for e, p in s.walk_entities()] == [
        ("minecraft:zombie", "entities[0]"),
        ("minecraft:skeleton", "entities[0].Passengers[0]"),
        ("minecraft:zombie", "blocks[0].nbt.SpawnData.entity"),
        ("minecraft:zombie", "blocks[0].nbt.SpawnPotentials[0].data.entity"),
    ]
    assert len(s.entities) == 1


def test_palettes_form_exposes_variants_and_no_single_palette(tmp_path):
    root = Compound({
        "DataVersion": Int(4325),
        "size": _int_list(1, 1, 1),
        "blocks": List[Compound]([block_entry(0)]),
        "entities": List[Compound]([]),
        "palettes": List[List[Compound]]([
            List[Compound]([Compound({"Name": String("minecraft:stone")})]),
            List[Compound]([Compound({"Name": String("minecraft:dirt")})]),
        ]),
    })
    path = tmp_path / "s.nbt"
    save(nbtlib.File(root, gzipped=True, root_name=""), path)

    s = load_structure(path)
    assert s.palette is None
    assert [s.palette_names(i) for i in range(2)] == [["minecraft:stone"], ["minecraft:dirt"]]
    assert len(s.palette_variants) == 2


def test_scalar_and_array_tags_become_plain_values(tmp_path):
    entity = Compound({
        "id": String("minecraft:zombie"),
        "Health": nbtlib.Float(20.0),
        "Age": Byte(-1),
        "UUID": IntArray([1, -2, 3, 4]),
        "Motion": List[Double]([Double(0.5), Double(0.0), Double(-0.5)]),
        "Big": Long(2**40),
        "Bytes": ByteArray([1, 2, 3]),
        "Longs": LongArray([2**40, -1]),
    })
    path = tmp_path / "s.nbt"
    save(structure_nbt(4325, entities=[entity_entry(entity)]), path)

    e = load_structure(path).walk_entities()[0][0]
    assert e["Health"] == 20.0 and isinstance(e["Health"], float)
    assert e["Age"] == -1 and isinstance(e["Age"], int)
    assert e["UUID"] == array("i", [1, -2, 3, 4])
    assert e["Motion"] == [0.5, 0.0, -0.5]
    assert e["Big"] == 2**40
    assert e["Bytes"] == array("b", [1, 2, 3])
    assert e["Longs"] == array("q", [2**40, -1])


def test_uncompressed_and_gzipped_bytes_both_parse():
    f = structure_nbt(4325, blocks=[block_entry(0, pos=(1, 2, 3))])
    buf = io.BytesIO()
    f.write(buf)
    raw = buf.getvalue()
    for data in (raw, gzip.compress(raw)):
        s = parse_structure(data)
        assert s.data_version == 4325
        assert s.blocks.pos_of(0) == (1, 2, 3)


def test_decode_string_handles_java_modified_utf8():
    assert decode_string("plain ascii".encode()) == "plain ascii"
    assert decode_string("señal ≥ 1".encode("utf-8")) == "señal ≥ 1"
    # Java writes NUL as C0 80 and supplementary characters as surrogate pairs.
    assert decode_string(b"a\xc0\x80b") == "a\x00b"
    assert decode_string("\U0001F600".encode("utf-16", "surrogatepass")
                         .decode("utf-16", "surrogatepass")
                         .encode("utf-8", "surrogatepass")) == "\U0001F600"
    assert decode_string(b"\xff\xfe") == "��"  # garbage still decodes


def test_corrupt_data_raises_from_the_reference_parser():
    """Whatever this parser thinks, nbtlib has the final say on a bad file: it is
    handed anything the fast parser rejects, and its error is the one reported."""
    with pytest.raises(KeyError):
        parse_structure(b"\x7f\x00\x00")  # unknown root tag id
    with pytest.raises(KeyError):
        parse_structure(b"not nbt at all")
    # nbtlib reads a file cut off mid-tag as far as it goes; so, therefore, do we.
    assert parse_structure(gzip.compress(b"\x0a\x00\x00\x03\x00\x01x")).root == {"x": 0}


def test_parse_bytes_matches_nbtlib_on_a_generated_file(tmp_path):
    from core.nbt import _from_nbtlib
    palette = [Compound({"Name": String("minecraft:stone")}), Compound({"Name": String("minecraft:chest")})]
    blocks = [block_entry(i % 2, pos=(i, 0, 0), nbt=_chest("t:x") if i % 2 else None) for i in range(50)]
    f = structure_nbt(4325, blocks=blocks, palette=palette, entities=[entity_entry(_zombie())], size=(50, 1, 1))
    buf = io.BytesIO()
    f.write(buf)
    data = buf.getvalue()

    root, parsed_blocks = parse_bytes(data)
    reference = _from_nbtlib(nbtlib.File.parse(io.BytesIO(data)))
    ref_blocks = Blocks()
    for entry in reference.pop("blocks"):
        ref_blocks.add_entry(entry)
    assert root == reference
    assert list(root) == list(reference)  # key order too
    assert parsed_blocks.states == ref_blocks.states
    assert parsed_blocks.positions == ref_blocks.positions
    assert [(b.index, b.state, b.pos, b.nbt) for b in parsed_blocks.entities] == \
        [(b.index, b.state, b.pos, b.nbt) for b in ref_blocks.entities]
