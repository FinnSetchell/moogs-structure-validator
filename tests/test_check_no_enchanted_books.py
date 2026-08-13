from __future__ import annotations

import json
from pathlib import Path

from checks import check_no_enchanted_books
from utils.loot_tables import iter_enchanted_book_loot_entries


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
