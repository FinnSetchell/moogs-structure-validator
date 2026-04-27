from __future__ import annotations

from pathlib import Path

from registries.fetcher import _fetch_version


PROBE_VERSIONS = [
    "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4", "1.21.5",
    "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10", "1.21.11",
    "26.1", "26.1.1", "26.1.2",
]


def find_version_added(block_id: str, cache_dir: Path, refresh: bool) -> str | None:
    if not block_id.startswith("minecraft:"):
        return None
    bare = block_id[len("minecraft:"):]
    for version in PROBE_VERSIONS:
        try:
            data = _fetch_version(version, cache_dir, refresh)
        except Exception:
            continue
        if bare in data.get("block", []):
            return version
    return None
