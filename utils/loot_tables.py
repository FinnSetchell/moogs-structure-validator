from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterator

_SPAWN_EGG_RE = re.compile(r"^minecraft:.+_spawn_egg$")


def _walk_entries(
    node: object,
    path: str,
    predicate: Callable[[str], bool],
) -> Iterator[tuple[str, str]]:
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
    json_path: Path,
    predicate: Callable[[str], bool],
) -> Iterator[tuple[str, str]]:
    """Yield (path_description, item_id) for item entries whose id matches predicate."""
    try:
        with json_path.open(encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return
    pools = data.get("pools")
    if not isinstance(pools, list):
        return
    for pi, pool in enumerate(pools):
        entries = pool.get("entries")
        if not isinstance(entries, list):
            continue
        for ei, entry in enumerate(entries):
            yield from _walk_entries(entry, f"pools[{pi}].entries[{ei}]", predicate)


def iter_spawn_egg_loot_entries(json_path: Path) -> Iterator[tuple[str, str]]:
    """Yield (path_description, item_id) for spawn-egg item entries in a loot table JSON."""
    yield from iter_matching_loot_entries(json_path, lambda name: bool(_SPAWN_EGG_RE.match(name)))


def iter_enchanted_book_loot_entries(json_path: Path) -> Iterator[tuple[str, str]]:
    """Yield (path_description, item_id) for minecraft:enchanted_book item entries.

    Using enchanted_book as a loot item is almost always a bug: enchantments on
    enchanted books are populated by the enchant_randomly / set_enchantments
    functions applied to minecraft:book, so an enchanted_book entry drops an
    empty enchanted book with no enchantments.
    """
    yield from iter_matching_loot_entries(json_path, lambda name: name == "minecraft:enchanted_book")
