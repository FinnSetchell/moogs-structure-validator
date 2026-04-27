import json
import pathlib
import urllib.request


_REGISTRY_URL = "https://raw.githubusercontent.com/misode/mcmeta/{version}-summary/registries/data.json"


def _fetch_version(version: str, cache_dir: pathlib.Path, refresh: bool) -> dict:
    cache_file = cache_dir / f"{version}-registries.json"
    if cache_file.exists() and not refresh:
        with cache_file.open() as f:
            return json.load(f)

    print(f"[registries] fetching {version}...")
    url = _REGISTRY_URL.format(version=version)
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())

    with cache_file.open("w") as f:
        json.dump(data, f)

    return data


def fetch_registries(
    mc_versions: list[str], cache_dir: pathlib.Path, refresh: bool
) -> tuple[set[str], set[str]]:
    items_per_version: list[set[str]] = []
    blocks_per_version: list[set[str]] = []

    for version in mc_versions:
        data = _fetch_version(version, cache_dir, refresh)
        items_per_version.append(set(data.get("minecraft:item", {}).get("entries", {}).keys()))
        blocks_per_version.append(set(data.get("minecraft:block", {}).get("entries", {}).keys()))

    valid_items = items_per_version[0].intersection(*items_per_version[1:]) if items_per_version else set()
    valid_blocks = blocks_per_version[0].intersection(*blocks_per_version[1:]) if blocks_per_version else set()

    print(f"[registries] {len(valid_items)} items, {len(valid_blocks)} blocks valid across all versions")
    return valid_items, valid_blocks
