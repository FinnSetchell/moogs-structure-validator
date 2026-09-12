"""The mod project on disk: where things live, and cached reads of them.

A project is ``<root>/src/main/resources/data/<namespace>/...``. Registry
folders were renamed from plural to singular at 1.21 (``structures`` ->
``structure``, ``loot_tables`` -> ``loot_table``); :meth:`Project.data_dir`
resolves whichever form exists.

Every JSON file is parsed at most once per run and every directory listed at
most once; a dozen checks read the same template pools, and this is where that
stops costing anything.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

_PLURAL_FORMS = {
    "structure":        "structures",
    "loot_table":       "loot_tables",
    "advancement":      "advancements",
    "recipe":           "recipes",
    "predicate":        "predicates",
    "item_modifier":    "item_modifiers",
    "function":         "functions",
    "tags/item":        "tags/items",
    "tags/block":       "tags/blocks",
    "tags/entity_type": "tags/entity_types",
    "tags/fluid":       "tags/fluids",
    "tags/game_event":  "tags/game_events",
    "tags/function":    "tags/functions",
}

MSL_VERSIONED_ELEMENT = "moogs_structures:versioned_single_pool_element"


def read_json(path: Path) -> Any:
    """Parse one JSON file (UTF-8, BOM tolerated). Raises on failure."""
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def loc_to_path(location: str, namespace: str, base_dir: Path, ext: str) -> Path | None:
    """``"<ns>:<path>"`` -> ``base_dir/<path><ext>``; None when the namespace
    is not ours (or the string has no namespace at all)."""
    if ":" not in location:
        return None
    ns, path = location.split(":", 1)
    if ns != namespace:
        return None
    return base_dir / (path + ext)


def namespaced(ref: str) -> str:
    return ref if ":" in ref else f"minecraft:{ref}"


def element_type(element: dict) -> str:
    """A pool element's type id: ``element_type`` (MSL) or ``type`` (vanilla)."""
    return element.get("element_type") or element.get("type", "")


def pool_locations(pool_data: dict) -> list[str]:
    """Every structure location a template pool names: each element's
    ``location`` plus, for MSL versioned elements, every ``locations`` value."""
    locations: list[str] = []
    for entry in pool_data.get("elements", []):
        element = entry.get("element", {})
        loc = element.get("location")
        if loc:
            locations.append(loc)
        if element_type(element) == MSL_VERSIONED_ELEMENT:
            for versioned_loc in element.get("locations", {}).values():
                locations.append(versioned_loc)
    return locations


class Project:
    def __init__(self, project_root: Path, namespace: str) -> None:
        self.root = Path(project_root)
        self.namespace = namespace
        self.data_root = self.root / "src" / "main" / "resources" / "data"
        self.namespace_root = self.data_root / namespace
        self._listings: dict[tuple[str, str], list[Path]] = {}
        self._json: dict[Path, tuple[Any, Exception | None]] = {}

    # -- layout
    def data_dir(self, name: str) -> Path:
        """The singular or plural form of a registry folder, whichever exists
        (singular when neither does, so callers can test ``.exists()``)."""
        singular = self.namespace_root / name
        if singular.exists():
            return singular
        plural = _PLURAL_FORMS.get(name)
        if plural:
            plural_path = self.namespace_root / plural
            if plural_path.exists():
                return plural_path
        return singular

    def all_data_dirs(self, name: str) -> list[Path]:
        """Every existing form of a registry folder (a project may carry both)."""
        dirs: list[Path] = []
        singular = self.namespace_root / name
        if singular.exists():
            dirs.append(singular)
        plural = _PLURAL_FORMS.get(name)
        if plural:
            plural_path = self.namespace_root / plural
            if plural_path.exists() and plural_path not in dirs:
                dirs.append(plural_path)
        return dirs if dirs else [singular]

    @property
    def structures_dir(self) -> Path:
        return self.data_dir("structure")

    @property
    def loot_table_dir(self) -> Path:
        return self.data_dir("loot_table")

    @property
    def template_pool_dir(self) -> Path:
        return self.namespace_root / "worldgen" / "template_pool"

    @property
    def worldgen_structure_dir(self) -> Path:
        return self.namespace_root / "worldgen" / "structure"

    @property
    def structure_set_dir(self) -> Path:
        return self.namespace_root / "worldgen" / "structure_set"

    @property
    def processor_list_dir(self) -> Path:
        return self.namespace_root / "worldgen" / "processor_list"

    # -- listings
    def files(self, directory: Path, pattern: str = "*.json") -> list[Path]:
        """Sorted recursive listing, computed once per (directory, pattern).
        Empty when the directory does not exist."""
        key = (str(directory), pattern)
        hit = self._listings.get(key)
        if hit is None:
            hit = sorted(directory.rglob(pattern)) if directory.exists() else []
            self._listings[key] = hit
        return hit

    def json_files(self, directory: Path) -> list[Path]:
        return self.files(directory, "*.json")

    def nbt_files(self, directory: Path) -> list[Path]:
        return self.files(directory, "*.nbt")

    # -- JSON
    def _read(self, path: Path) -> tuple[Any, Exception | None]:
        hit = self._json.get(path)
        if hit is None:
            try:
                hit = (read_json(path), None)
            except Exception as e:  # unreadable or not JSON
                hit = (None, e)
            self._json[path] = hit
        return hit

    def load_json(self, path: Path) -> Any:
        """Parsed JSON, cached. Raises the original error for a bad file."""
        data, err = self._read(path)
        if err is not None:
            raise err
        return data

    def try_json(self, path: Path) -> Any | None:
        """Parsed JSON, or None for a file that cannot be read or parsed."""
        return self._read(path)[0]

    def json_or_report(self, path: Path, report: Callable[[Exception], None]) -> Any | None:
        """Parsed JSON; calls ``report(error)`` and returns None for a bad file."""
        data, err = self._read(path)
        if err is not None:
            report(err)
            return None
        return data

    def json_dicts(self, directory: Path) -> list[tuple[Path, dict]]:
        """``(path, data)`` for every parseable JSON object under ``directory``."""
        out = []
        for path in self.json_files(directory):
            data = self.try_json(path)
            if isinstance(data, dict):
                out.append((path, data))
        return out

    # -- pools
    def pools(self) -> list[tuple[Path, dict]]:
        """Every parseable template pool as ``(path, data)``."""
        return self.json_dicts(self.template_pool_dir)

    def resource_exists(self, ref: str, data_type: str) -> bool | None:
        """Whether ``ref`` names a JSON resource of ``data_type`` in this project.
        None when the ref is not in our namespace (nothing to check locally)."""
        ns, _, path = namespaced(ref).partition(":")
        if ns != self.namespace:
            return None
        return any((d / f"{path}.json").exists() for d in self.all_data_dirs(data_type))
