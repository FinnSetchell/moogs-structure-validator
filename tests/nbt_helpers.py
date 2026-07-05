"""Helpers to build a minimal on-disk datapack layout and structure NBTs for tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import nbtlib
from nbtlib import Compound, Double, File, Float, Int, List, String


def _int_list(*xs):
    return List[Int]([Int(x) for x in xs])


def _float_list(*xs):
    return List[Float]([Float(x) for x in xs])


def _double_list(*xs):
    return List[Double]([Double(x) for x in xs])


def structure_nbt(
    data_version: int,
    entities: list[Compound] | None = None,
    blocks: list[Compound] | None = None,
    palette: list[Compound] | None = None,
    size: tuple[int, int, int] = (1, 1, 1),
) -> File:
    if palette is None:
        palette = [Compound({"Name": String("minecraft:air")})]
    root = Compound({
        "DataVersion": Int(data_version),
        "size": _int_list(*size),
        "blocks": List[Compound](blocks or []),
        "entities": List[Compound](entities or []),
        "palette": List[Compound](palette),
    })
    return File(root, gzipped=True, root_name="")


def entity_entry(entity_nbt: Compound, pos=(0.5, 0.0, 0.5), block_pos=(0, 0, 0)) -> Compound:
    return Compound({
        "blockPos": _int_list(*block_pos),
        "pos": _double_list(*pos),
        "nbt": entity_nbt,
    })


def block_entry(state: int, pos=(0, 0, 0), nbt: Compound | None = None) -> Compound:
    entry = Compound({"state": Int(state), "pos": _int_list(*pos)})
    if nbt is not None:
        entry["nbt"] = nbt
    return entry


def save(nbt_file: File, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nbt_file.save(str(path), gzipped=True)


def write_pool(path: Path, elements: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"name": path.stem, "fallback": "minecraft:empty", "elements": elements}, f)


def versioned_element(default: str, locations: dict[str, str]) -> dict:
    return {
        "weight": 1,
        "element": {
            "element_type": "moogs_structures:versioned_single_pool_element",
            "location": default,
            "locations": locations,
            "projection": "rigid",
            "processors": "minecraft:empty",
        },
    }


class FakeContext:
    """Duck-typed ValidatorContext for tests."""
    def __init__(self, namespace: str, mc_versions: list[str], project_root: Path):
        self.namespace = namespace
        self.mc_versions = mc_versions
        self.project_root = project_root
        self.refresh = False
        self.extra_ids: set[str] = set()
        self.extra_ids_raw: list[str] = []
        self.valid_blocks: set[str] = set()
        self.valid_items: set[str] = set()
        self.valid_entities: set[str] = set()
        self.orphan_nbts: set[Path] = set()
        self.nbt_cache: dict = {}


VANILLA_VERSION_MAP = {
    "1.20": 3463,
    "1.20.1": 3465,
    "1.20.2": 3578,
    "1.20.4": 3700,
    "1.20.5": 3837,
    "1.20.6": 3839,
    "1.21": 3953,
    "1.21.1": 3955,
    "1.21.2": 4080,
    "1.21.3": 4082,
    "1.21.4": 4189,
    "1.21.5": 4325,
    "1.21.6": 4435,
    "1.21.7": 4438,
    "1.21.8": 4440,
    "1.21.9": 4554,
    "1.21.10": 4556,
    "1.21.11": 4576,
}


def stub_registries(monkeypatch, entities: set[str] | None = None,
                    items: set[str] | None = None, blocks: set[str] | None = None,
                    effects: set[str] | None = None, enchantments: set[str] | None = None,
                    attributes: set[str] | None = None) -> None:
    """Redirect network-backed helpers to in-memory sets keyed by registry name."""
    default_by_key = {
        "entity_type": entities or set(),
        "item": items or set(),
        "block": blocks or set(),
        "mob_effect": effects or set(),
        "enchantment": enchantments or set(),
        "attribute": attributes or set(),
    }

    def fake_fetch_version(version, cache_dir, refresh):
        # Strip minecraft: prefix so callers can re-add it as they already do.
        return {k: [n.split(":", 1)[1] if ":" in n else n for n in v]
                for k, v in default_by_key.items()}

    def fake_fetch_registry_set(version, cache_dir, refresh, key):
        return {n if ":" in n else f"minecraft:{n}" for n in default_by_key.get(key, set())}

    def fake_load_version_map(cache_dir, refresh):
        return dict(VANILLA_VERSION_MAP)

    from registries import fetcher as _fetcher
    from utils import versions as _versions
    monkeypatch.setattr(_fetcher, "_fetch_version", fake_fetch_version)
    monkeypatch.setattr(_fetcher, "fetch_registry_set", fake_fetch_registry_set)
    monkeypatch.setattr(_versions, "load_version_map", fake_load_version_map)
    # Some check modules import these names directly; redirect their bindings too.
    import importlib, pkgutil
    import checks as _checks_pkg
    for _, modname, _ in pkgutil.iter_modules(_checks_pkg.__path__):
        module = importlib.import_module(f"checks.{modname}")
        if hasattr(module, "_fetch_version"):
            monkeypatch.setattr(module, "_fetch_version", fake_fetch_version)
        if hasattr(module, "fetch_registry_set"):
            monkeypatch.setattr(module, "fetch_registry_set", fake_fetch_registry_set)
        if hasattr(module, "load_version_map"):
            monkeypatch.setattr(module, "load_version_map", fake_load_version_map)


def build_datapack(tmp_path: Path, namespace: str = "test") -> tuple[Path, Path, Path]:
    """Create the src/main/resources/data/<ns> layout; return (root, structures_dir, pool_dir)."""
    ns_root = tmp_path / "src" / "main" / "resources" / "data" / namespace
    structures = ns_root / "structures"
    pools = ns_root / "worldgen" / "template_pool"
    structures.mkdir(parents=True, exist_ok=True)
    pools.mkdir(parents=True, exist_ok=True)
    return tmp_path, structures, pools
