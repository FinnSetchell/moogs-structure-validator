"""Data fetched from misode/mcmeta and the loader repositories, with caching.

Two layers:

* module-level ``fetch_*`` functions do the disk cache + HTTP. They are the
  seam the test suite patches (``tests/nbt_helpers.stub_registries``), and they
  are deliberately plain functions with no in-process memory.
* :class:`Mcmeta` wraps them for one validator run and memoises every answer,
  so a registry file is read and parsed once no matter how many checks ask.

Sources (all pinned per MC version, so cache entries never go stale):

* ``https://raw.githubusercontent.com/misode/mcmeta/<version>-summary/registries/data.json``
  -- every registry as a flat list of bare ids (``item``, ``block``,
  ``entity_type``, ``mob_effect``, ``enchantment``, ``attribute``, ``loot_table``,
  ``worldgen/structure``, ``worldgen/template_pool``, ...).
* ``https://raw.githubusercontent.com/misode/mcmeta/<version>-summary/data/tag/worldgen/biome/data.json``
  -- vanilla biome tags.
* ``https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json``
  -- the version index (rolling; refreshed with ``--refresh``).
* GitHub contents API for loader biome tags (see ``data/biome_tag_map.json``).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

from core.mcversions import VersionIndex

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"

_REGISTRY_URL = "https://raw.githubusercontent.com/misode/mcmeta/{version}-summary/registries/data.json"
_BIOME_TAGS_URL = "https://raw.githubusercontent.com/misode/mcmeta/{version}-summary/data/tag/worldgen/biome/data.json"
_VERSIONS_URL = "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json"
_LOOT_SCHEMA_URL = "https://raw.githubusercontent.com/misode/minecraft-json-schemas/master/java/data/loot_table.json"

_TIMEOUT = 60


def _http_json(url: str, headers: dict[str, str] | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(path)


def _cached(path: Path, refresh: bool, fetch):
    """Return the cached JSON at ``path``, or fetch it and cache it."""
    if path.exists() and not refresh:
        try:
            return _read_json(path)
        except (OSError, ValueError):
            pass  # unreadable cache entry: refetch below
    data = fetch()
    _write_json(path, data)
    return data


# --- fetch seams ----------------------------------------------------------------

def fetch_registry_data(version: str, cache_dir: Path, refresh: bool) -> dict:
    """The full mcmeta registries summary for one MC version (raises on failure)."""
    cache_file = cache_dir / f"{version}-registries.json"
    if cache_file.exists() and not refresh:
        return _read_json(cache_file)
    print(f"  fetching {version}...")
    data = _http_json(_REGISTRY_URL.format(version=version))
    _write_json(cache_file, data)
    return data


def fetch_version_entries(cache_dir: Path, refresh: bool) -> list[dict]:
    """The mcmeta version index (every version, newest first); ``[]`` on failure."""
    cache_file = cache_dir / "versions.json"
    if cache_file.exists() and not refresh:
        try:
            return _read_json(cache_file)
        except (OSError, ValueError):
            pass
    try:
        entries = _http_json(_VERSIONS_URL)
    except Exception as e:
        print(f"  [WARN] could not fetch versions.json: {e}")
        return []
    _write_json(cache_file, entries)
    return entries


def fetch_vanilla_biome_tags(version: str, cache_dir: Path, refresh: bool) -> dict | None:
    """Vanilla biome tag map for one MC version; None (after a WARN) on failure."""
    cache_file = cache_dir / f"{version}-biome-tags.json"
    if cache_file.exists() and not refresh:
        return _read_json(cache_file)
    try:
        data = _http_json(_BIOME_TAGS_URL.format(version=version))
    except Exception as e:
        print(f"  [WARN] could not fetch biome tags for {version}: {e}")
        return None
    _write_json(cache_file, data)
    return data


def fetch_github_dir_names(repo: str, path: str, ref: str, cache_file: Path, refresh: bool) -> list[str] | None:
    """Names (without ``.json``) of the JSON files in a GitHub directory; None on failure."""
    if cache_file.exists() and not refresh:
        return _read_json(cache_file)
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    items = _http_json(url, headers={"Accept": "application/vnd.github+json"})
    names = [
        item["name"][:-5]
        for item in items
        if item.get("type") == "file" and item.get("name", "").endswith(".json")
    ]
    _write_json(cache_file, names)
    return names


def fetch_loot_table_schema(cache_dir: Path, refresh: bool) -> dict:
    cache_file = cache_dir / "schema-loot_table.json"
    if cache_file.exists() and not refresh:
        return _read_json(cache_file)
    print("  fetching schema...")
    data = _http_json(_LOOT_SCHEMA_URL)
    _write_json(cache_file, data)
    return data


def fetch_schema_ref(uri: str, cache_dir: Path, refresh: bool) -> dict:
    """A ``$ref`` target of the loot-table schema, cached by URI hash."""
    cache_file = cache_dir / "schema-refs" / hashlib.md5(uri.encode()).hexdigest()
    return _cached(cache_file, refresh, lambda: _http_json(uri))


LOOT_SCHEMA_URL = _LOOT_SCHEMA_URL


# --- the per-run accessor ---------------------------------------------------------

def _ns(names) -> set[str]:
    return {"minecraft:" + n for n in names}


class Mcmeta:
    """Memoised access to everything above, for one validator run.

    ``registry(version, key)`` answers "which ``minecraft:`` ids does registry
    ``key`` hold at ``version``"; ``union(key)`` folds that over every targeted
    version. Both raise if the registry file cannot be fetched, so callers that
    would rather stay silent than guess catch the exception themselves.
    """

    def __init__(self, mc_versions: list[str], cache_dir: Path = CACHE_DIR, refresh: bool = False):
        self.mc_versions = list(mc_versions)
        self.cache_dir = cache_dir
        self.refresh = refresh
        self._data: dict[str, dict] = {}
        self._sets: dict[tuple[str, str], set[str]] = {}
        self._unions: dict[str, set[str]] = {}
        self._index: VersionIndex | None = None
        self._biome_tags: dict[str, set[str]] = {}
        self._loader_tags: dict[str, set[str]] = {}

    # registries
    def data(self, version: str) -> dict:
        if version not in self._data:
            self._data[version] = fetch_registry_data(version, self.cache_dir, self.refresh)
        return self._data[version]

    def registry(self, version: str, key: str) -> set[str]:
        k = (version, key)
        if k not in self._sets:
            self._sets[k] = _ns(self.data(version).get(key, []))
        return self._sets[k]

    def union(self, key: str) -> set[str]:
        if key not in self._unions:
            out: set[str] = set()
            for v in self.mc_versions:
                out |= self.registry(v, key)
            self._unions[key] = out
        return self._unions[key]

    def prefetch(self) -> None:
        """Fetch every targeted version's registries up front, in parallel."""
        from concurrent.futures import ThreadPoolExecutor
        missing = [v for v in self.mc_versions if v not in self._data]
        if not missing:
            return
        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as ex:
            for v, d in zip(missing, ex.map(lambda v: fetch_registry_data(v, self.cache_dir, self.refresh), missing)):
                self._data[v] = d

    # version index
    @property
    def versions(self) -> VersionIndex:
        if self._index is None:
            self._index = VersionIndex(fetch_version_entries(self.cache_dir, self.refresh))
        return self._index

    def version_added(self, registry_key: str, id_: str, after: str) -> str | None:
        """The first stable release newer than ``after`` whose ``registry_key``
        holds ``id_``; None if no probed release has it.

        Used to annotate an unknown id with "added in X". Only ``minecraft:`` ids
        can be answered. Releases whose registries cannot be fetched are skipped.
        """
        if not id_.startswith("minecraft:"):
            return None
        bare = id_[len("minecraft:"):]
        for version in self.versions.stable_after(after):
            try:
                names = self.data(version).get(registry_key, [])
            except Exception:
                continue
            if bare in names:
                return version
        return None

    # biome tags
    def vanilla_biome_tags(self, version: str) -> set[str]:
        if version not in self._biome_tags:
            data = fetch_vanilla_biome_tags(version, self.cache_dir, self.refresh)
            self._biome_tags[version] = _ns(data.keys()) if data else set()
        return self._biome_tags[version]

    def loader_biome_tags(self, loader_name: str, range_key: str, entry: dict) -> set[str]:
        """Tag names a loader ships at the pinned ref in ``data/biome_tag_map.json``.
        Empty (after a WARN) when GitHub cannot be reached."""
        cache_key = f"{loader_name}/{range_key}"
        if cache_key not in self._loader_tags:
            repo, ref, path = entry["repository"], entry["ref"], entry["path"]
            cache_file = self.cache_dir / f"loader-{repo.replace('/', '-')}-{ref[:16]}.json"
            try:
                names = fetch_github_dir_names(repo, path, ref, cache_file, self.refresh)
            except Exception as e:
                print(f"  [WARN] could not fetch loader tags for {loader_name} {range_key}: {e}")
                names = None
            self._loader_tags[cache_key] = set(names or [])
        return self._loader_tags[cache_key]
