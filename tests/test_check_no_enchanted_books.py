from __future__ import annotations

import json
from pathlib import Path

from checks import check_no_enchanted_books
from core.loot import iter_enchanted_book_loot_entries


class _Ctx:
    def __init__(self, project_root: Path, namespace: str = "test"):
        self.project_root = project_root
        self.namespace = namespace


def _write_loot_table(root: Path, rel: str, data: dict) -> Path:
    lt_dir = root / "src" / "main" / "resources" / "data" / "test" / "loot_table"
    path = lt_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_iter_finds_top_level_entry(tmp_path):
    p = _write_loot_table(tmp_path, "a.json", {
        "pools": [{"entries": [{"type": "minecraft:item", "name": "minecraft:enchanted_book"}]}]
    })
    hits = list(iter_enchanted_book_loot_entries(p))
    assert len(hits) == 1
    assert hits[0][1] == "minecraft:enchanted_book"


def test_iter_finds_nested_in_group(tmp_path):
    p = _write_loot_table(tmp_path, "b.json", {
        "pools": [{"entries": [{
            "type": "minecraft:group",
            "children": [{"type": "minecraft:item", "name": "minecraft:enchanted_book"}],
        }]}]
    })
    hits = list(iter_enchanted_book_loot_entries(p))
    assert len(hits) == 1


def test_iter_ignores_plain_book(tmp_path):
    p = _write_loot_table(tmp_path, "c.json", {
        "pools": [{"entries": [{"type": "minecraft:item", "name": "minecraft:book"}]}]
    })
    assert list(iter_enchanted_book_loot_entries(p)) == []


def test_iter_ignores_other_namespaces(tmp_path):
    p = _write_loot_table(tmp_path, "d.json", {
        "pools": [{"entries": [{"type": "minecraft:item", "name": "othermod:enchanted_book"}]}]
    })
    assert list(iter_enchanted_book_loot_entries(p)) == []


def test_check_fails_when_enchanted_book_present(tmp_path, capsys):
    _write_loot_table(tmp_path, "chests/foo.json", {
        "pools": [{"entries": [{"type": "minecraft:item", "name": "minecraft:enchanted_book"}]}]
    })
    passed, summary = check_no_enchanted_books.run(_Ctx(tmp_path))
    assert not passed
    assert "enchanted_book" in summary


def test_check_passes_when_only_plain_books(tmp_path, capsys):
    _write_loot_table(tmp_path, "chests/bar.json", {
        "pools": [{"entries": [{
            "type": "minecraft:item",
            "name": "minecraft:book",
            "functions": [{"function": "minecraft:enchant_randomly"}],
        }]}]
    })
    passed, summary = check_no_enchanted_books.run(_Ctx(tmp_path))
    assert passed
    assert "no enchanted_book" in summary


def test_check_passes_when_no_loot_table_dir(tmp_path):
    passed, _ = check_no_enchanted_books.run(_Ctx(tmp_path))
    assert passed



# --- every place loot can name the item ---------------------------------------------------

BOOK_ENTRY = {"type": "minecraft:item", "name": "minecraft:enchanted_book"}


def _put(root: Path, rel: str, data) -> None:
    path = root / "src" / "main" / "resources" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _table(*entries) -> dict:
    return {"pools": [{"rolls": 1, "entries": list(entries)}]}


def _fails_with(tmp_path, capsys, files: dict, where: str):
    for rel, data in files.items():
        _put(tmp_path, rel, data)
    (tmp_path / "src" / "main" / "resources" / "data" / "test").mkdir(parents=True, exist_ok=True)
    passed, _ = check_no_enchanted_books.run(_Ctx(tmp_path))
    out = capsys.readouterr().out
    assert not passed, out
    assert where in out, out
    assert "Use minecraft:book with enchant_randomly" in out


def test_a_vanilla_override_table_fails(tmp_path, capsys):
    _fails_with(tmp_path, capsys, {"data/minecraft/loot_table/chests/simple_dungeon.json": _table(BOOK_ENTRY)},
                "data/minecraft/loot_table/chests/simple_dungeon.json: pools[0].entries[0].name")


def test_the_plural_folder_fails_too(tmp_path, capsys):
    _fails_with(tmp_path, capsys, {"data/test/loot_tables/old.json": _table(BOOK_ENTRY),
                                   "data/test/loot_table/new.json": _table(BOOK_ENTRY)},
                "data/test/loot_tables/old.json: pools[0].entries[0].name")


def test_an_overlay_table_is_read(tmp_path, capsys):
    pack = {"pack": {"pack_format": 48}, "overlays": {"entries": [{"formats": [48, 121], "directory": "ov"}]}}
    _fails_with(tmp_path, capsys, {"pack.mcmeta": pack, "ov/data/test/loot_table/new.json": _table(BOOK_ENTRY)},
                "ov/data/test/loot_table/new.json: pools[0].entries[0].name")


def test_an_inline_table_and_a_bare_id_fail(tmp_path, capsys):
    inline = {"type": "minecraft:loot_table", "value": _table({"type": "item", "name": "enchanted_book"})}
    _fails_with(tmp_path, capsys, {"data/test/loot_table/a.json": _table(inline)},
                "pools[0].entries[0].value.pools[0].entries[0].name = enchanted_book")


def test_set_item_in_both_forms_fails(tmp_path, capsys):
    old = {"type": "minecraft:item", "name": "minecraft:book",
           "functions": [{"function": "minecraft:set_item", "item": "minecraft:enchanted_book"}],
           "modifier": {"type": "minecraft:set_item", "item": "minecraft:enchanted_book"}}
    for rel, data in {"data/test/loot_table/a.json": _table(old)}.items():
        _put(tmp_path, rel, data)
    passed, _ = check_no_enchanted_books.run(_Ctx(tmp_path))
    out = capsys.readouterr().out
    assert not passed
    assert "pools[0].entries[0].functions[0].item" in out and "pools[0].entries[0].modifier.item" in out


def test_a_set_contents_payload_fails(tmp_path, capsys):
    box = {"type": "minecraft:item", "name": "minecraft:shulker_box",
           "functions": [{"function": "minecraft:set_contents", "component": "minecraft:container",
                          "entries": [BOOK_ENTRY]}]}
    _fails_with(tmp_path, capsys, {"data/test/loot_table/a.json": _table(box)},
                "pools[0].entries[0].functions[0].entries[0].name")


def test_an_item_modifier_fails(tmp_path, capsys):
    _fails_with(tmp_path, capsys,
                {"data/test/item_modifier/swap.json": {"function": "minecraft:set_item",
                                                       "item": "minecraft:enchanted_book"}},
                "data/test/item_modifier/swap.json: item")


def test_a_condition_that_tests_for_the_item_passes(tmp_path, capsys):
    entry = {"type": "minecraft:item", "name": "minecraft:book",
             "functions": [{"function": "minecraft:enchant_randomly"}],
             "conditions": [{"condition": "minecraft:match_tool",
                             "predicate": {"items": "minecraft:enchanted_book"}}]}
    _put(tmp_path, "data/test/loot_table/a.json", _table(entry))
    passed, _ = check_no_enchanted_books.run(_Ctx(tmp_path))
    assert passed, capsys.readouterr().out
