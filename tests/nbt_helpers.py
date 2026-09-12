"""Helpers to build a minimal on-disk datapack layout and structure NBTs for tests."""
from __future__ import annotations

import json
from pathlib import Path

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


# Stable releases and their DataVersions, as misode/mcmeta's version index
# reports them. tests/test_boundaries.py checks the boundary constants against it.
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


def version_entries(version_map: dict[str, int] | None = None) -> list[dict]:
    """A mcmeta-shaped version index (newest first) for ``version_map``."""
    vm = VANILLA_VERSION_MAP if version_map is None else version_map
    return [
        {"id": v, "name": v, "type": "release", "stable": True, "data_version": dv}
        for v, dv in sorted(vm.items(), key=lambda kv: -kv[1])
    ]


def stub_registries(monkeypatch, entities: set[str] | None = None,
                    items: set[str] | None = None, blocks: set[str] | None = None,
                    effects: set[str] | None = None, enchantments: set[str] | None = None,
                    attributes: set[str] | None = None,
                    template_pools: set[str] | None = None,
                    version_map: dict[str, int] | None = None) -> None:
    """Redirect the two network-backed fetches in ``core.mcmeta`` to in-memory data.

    Every registry lookup goes through ``fetch_registry_data`` and every
    DataVersion lookup through ``fetch_version_entries``, so patching those two
    covers every check. The same sets are served for every MC version.
    """
    default_by_key = {
        "entity_type": entities or set(),
        "item": items or set(),
        "block": blocks or set(),
        "mob_effect": effects or set(),
        "enchantment": enchantments or set(),
        "attribute": attributes or set(),
        "worldgen/template_pool": template_pools or set(),
    }

    def fake_fetch_registry_data(version, cache_dir, refresh):
        # Bare names, as mcmeta ships them; callers add the minecraft: prefix.
        return {k: [n.split(":", 1)[1] if ":" in n else n for n in v]
                for k, v in default_by_key.items()}

    def fake_fetch_version_entries(cache_dir, refresh):
        return version_entries(version_map)

    from core import mcmeta as _mcmeta
    monkeypatch.setattr(_mcmeta, "fetch_registry_data", fake_fetch_registry_data)
    monkeypatch.setattr(_mcmeta, "fetch_version_entries", fake_fetch_version_entries)


def build_datapack(tmp_path: Path, namespace: str = "test") -> tuple[Path, Path, Path]:
    """Create the src/main/resources/data/<ns> layout; return (root, structures_dir, pool_dir)."""
    ns_root = tmp_path / "src" / "main" / "resources" / "data" / namespace
    structures = ns_root / "structures"
    pools = ns_root / "worldgen" / "template_pool"
    structures.mkdir(parents=True, exist_ok=True)
    pools.mkdir(parents=True, exist_ok=True)
    return tmp_path, structures, pools
