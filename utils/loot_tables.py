from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

_SPAWN_EGG_RE = re.compile(r"^minecraft:.+_spawn_egg$")


def _walk_entries(node: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        if (
            node.get("type") == "minecraft:item"
            and isinstance(node.get("name"), str)
            and _SPAWN_EGG_RE.match(node["name"])
        ):
            yield path, node["name"]
        for key in ("entries", "children"):
            sub = node.get(key)
            if isinstance(sub, list):
                for i, child in enumerate(sub):
                    yield from _walk_entries(child, f"{path}.{key}[{i}]")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk_entries(item, f"{path}[{i}]")


def iter_spawn_egg_loot_entries(json_path: Path) -> Iterator[tuple[str, str]]:
    """Yield (path_description, item_id) for spawn-egg item entries in a loot table JSON."""
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
            yield from _walk_entries(entry, f"pools[{pi}].entries[{ei}]")
