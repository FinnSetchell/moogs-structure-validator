"""Walkers over loot table JSON."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

from core.project import read_json

SPAWN_EGG_RE = re.compile(r"^minecraft:.+_spawn_egg$")


def is_spawn_egg(item_id: str) -> bool:
    return bool(SPAWN_EGG_RE.match(item_id))


def _walk_entries(node: object, path: str, predicate: Callable[[str], bool]) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        if (
            node.get("type") == "minecraft:item"
            and isinstance(node.get("name"), str)
            and predicate(node["name"])
        ):
            yield path, node["name"]
        for key in ("entries", "children"):
            sub = node.get(key)
            if isinstance(sub, list):
                for i, child in enumerate(sub):
                    yield from _walk_entries(child, f"{path}.{key}[{i}]", predicate)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk_entries(item, f"{path}[{i}]", predicate)


def iter_matching_loot_entries(
    json_path: Path, predicate: Callable[[str], bool], data: object = None,
) -> Iterator[tuple[str, str]]:
    """``(path, item_id)`` for every ``minecraft:item`` entry whose id satisfies
    ``predicate``. Pass ``data`` to reuse an already-parsed table; a file that
    cannot be read yields nothing."""
    if data is None:
        try:
            data = read_json(json_path)
        except Exception:
            return
    if not isinstance(data, dict):
        return
    pools = data.get("pools")
    if not isinstance(pools, list):
        return
    for pi, pool in enumerate(pools):
        entries = pool.get("entries") if isinstance(pool, dict) else None
        if not isinstance(entries, list):
            continue
        for ei, entry in enumerate(entries):
            yield from _walk_entries(entry, f"pools[{pi}].entries[{ei}]", predicate)


def iter_spawn_egg_loot_entries(json_path: Path, data: object = None) -> Iterator[tuple[str, str]]:
    yield from iter_matching_loot_entries(json_path, is_spawn_egg, data)


def iter_enchanted_book_loot_entries(json_path: Path, data: object = None) -> Iterator[tuple[str, str]]:
    """``minecraft:enchanted_book`` item entries. Using it as a loot item is
    almost always a bug: enchantments come from ``enchant_randomly`` /
    ``set_enchantments`` applied to ``minecraft:book``, so an ``enchanted_book``
    entry drops an empty enchanted book."""
    yield from iter_matching_loot_entries(json_path, lambda name: name == "minecraft:enchanted_book", data)


def collect_loot_ids(node: object, items: set[str], blocks: set[str]) -> None:
    """Item and block ids a loot table names: item entries, ``set_item`` style
    functions, ``set_contents``/``give_item`` payloads, and
    ``block_state_property`` conditions."""
    if isinstance(node, dict):
        entry_type = node.get("type", "")
        condition = node.get("condition", "")

        if isinstance(entry_type, str) and entry_type.endswith(":item"):
            name = node.get("name")
            if isinstance(name, str) and ":" in name:
                items.add(name)

        if isinstance(condition, str) and condition.endswith(":block_state_property"):
            block = node.get("block")
            if isinstance(block, str) and ":" in block:
                blocks.add(block)

        func = node.get("function", "")
        if isinstance(func, str) and func:
            name = node.get("name")
            if isinstance(name, str) and ":" in name:
                items.add(name)
            if func.endswith(":set_contents") or func.endswith(":give_item"):
                item = node.get("item")
                if isinstance(item, dict):
                    for key in ("id", "name"):
                        val = item.get(key)
                        if isinstance(val, str) and ":" in val:
                            items.add(val)
                elif isinstance(item, str) and ":" in item:
                    items.add(item)

        for val in node.values():
            collect_loot_ids(val, items, blocks)
    elif isinstance(node, list):
        for item in node:
            collect_loot_ids(item, items, blocks)
