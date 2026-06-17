from __future__ import annotations

import json
import urllib.request
from pathlib import Path

_VERSIONS_URL = "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json"


def load_version_map(cache_dir: Path, refresh: bool) -> dict[str, int]:
    cache_file = cache_dir / "versions.json"
    if cache_file.exists() and not refresh:
        with cache_file.open() as f:
            entries = json.load(f)
    else:
        try:
            with urllib.request.urlopen(_VERSIONS_URL) as resp:
                entries = json.loads(resp.read().decode())
            with cache_file.open("w") as f:
                json.dump(entries, f)
        except Exception as e:
            print(f"  [WARN] could not fetch versions.json: {e}")
            return {}

    return {e["id"]: e["data_version"] for e in entries if e.get("stable")}
