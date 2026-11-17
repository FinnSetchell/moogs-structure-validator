"""The context a check receives, and the per-run services hanging off it.

``ValidatorContext`` is the plain data the CLI builds from ``validator.json``
and the registries. ``services(ctx)`` attaches (once) the project layout, the
mcmeta accessor, the structure store and the pool-derived version ranges, so a
check never rebuilds any of them. It works on any object with ``project_root``
and ``namespace`` -- the test suite's stand-in contexts included.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.mcmeta import CACHE_DIR, Mcmeta
from core.mcversions import VersionIndex, max_version, min_version, parse_range, version_in_range
from core.nbt import Structure
from core.project import Project, loc_to_path, namespaced, pool_locations
from core.ranges import NBTVersionInfo, build_nbt_version_ranges
from core.structures import StructureStore

MSL_JIGSAW_STRUCTURES = frozenset({
    "moogs_structures:moogs_structures_generic_jigsaw_structure",
    "moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
})


def structure_gate(data: dict) -> str | None:
    """The ``mc_versions`` range an MSL jigsaw structure generates on (MSL 4.0.0): it has
    no biomes and is never placed on any other version. None when it has none, or one
    MSL refuses (check_worldgen_schemas reports that)."""
    gate = data.get("mc_versions") if data.get("type") in MSL_JIGSAW_STRUCTURES else None
    gate = "".join(gate.split()) if isinstance(gate, str) else None   # MSL trims around each version
    parsed = parse_range(gate) if gate else None
    return gate if parsed is not None and parsed[0] <= parsed[1] else None


def jigsaw_pools(structure: Structure | None) -> set[str]:
    """The pools a structure piece's jigsaw blocks name."""
    if structure is None or structure.palette is None:
        return set()
    jigsaws = {i for i, name in enumerate(structure.palette_names()) if name == "minecraft:jigsaw"}
    pools = set()
    for _, _, _, block_nbt in structure.blocks_in_states(jigsaws):
        pool = block_nbt.get("pool") if block_nbt is not None else None
        if pool is not None:
            pools.add(namespaced(str(pool)))
    return pools


@dataclass
class ValidatorContext:
    namespace: str
    mc_versions: list[str]
    extra_ids_raw: list[str]
    project_root: Path
    refresh: bool
    extra_ids: set[str] = field(default_factory=set)
    valid_blocks: set[str] = field(default_factory=set)
    valid_items: set[str] = field(default_factory=set)
    valid_entities: set[str] = field(default_factory=set)
    orphan_nbts: set[Path] = field(default_factory=set)
    # An overlay pack extends another mod instead of standing alone (a compat or
    # overlay pack). See Project.overlay.
    overlay: bool = False


class FileRange:
    """The target range of one structure file, with DataVersions resolved."""
    __slots__ = ("min_version", "max_version", "min_dv", "max_dv", "wired")

    def __init__(self, min_version: str, max_version: str, min_dv: int | None, max_dv: int | None, wired: bool):
        self.min_version = min_version
        self.max_version = max_version
        self.min_dv = min_dv
        self.max_dv = max_dv
        self.wired = wired

    @property
    def resolved(self) -> bool:
        return self.min_dv is not None and self.max_dv is not None


class Services:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.project = Project(Path(ctx.project_root), ctx.namespace,
                               overlay=bool(getattr(ctx, "overlay", False)))
        self.mc_versions: list[str] = list(getattr(ctx, "mc_versions", []) or [])
        self.refresh: bool = bool(getattr(ctx, "refresh", False))
        self.mcmeta = Mcmeta(self.mc_versions, CACHE_DIR, self.refresh)
        self.structures = StructureStore(self.project, getattr(ctx, "orphan_nbts", None))
        self._ranges: dict[Path, NBTVersionInfo] | None = None
        self._global: tuple[str, str] | None = None
        self._reached: dict[str, list[tuple[str, dict]]] | None = None
        self._pool_versions: dict[str, list[str]] | None = None

    # -- versions
    @property
    def versions(self) -> VersionIndex:
        return self.mcmeta.versions

    @property
    def global_min(self) -> str:
        if self._global is None:
            self._global = (min_version(self.mc_versions), max_version(self.mc_versions))
        return self._global[0]

    @property
    def global_max(self) -> str:
        if self._global is None:
            self._global = (min_version(self.mc_versions), max_version(self.mc_versions))
        return self._global[1]

    @property
    def nbt_ranges(self) -> dict[Path, NBTVersionInfo]:
        """Pool-derived ``(min, max)`` per NBT path; empty without pools."""
        if self._ranges is None:
            if self.project.template_pool_dir.exists() and self.mc_versions:
                self._ranges = build_nbt_version_ranges(self.project, self.mc_versions, self.pool_versions())
            else:
                self._ranges = {}
        return self._ranges

    def structures_by_pool(self) -> dict[str, list[tuple[str, dict]]]:
        """Each pool id, with every structure ``(file, data)`` whose generation reaches it:
        through its ``start_pool``, each pool's ``fallback`` and the jigsaw blocks of the
        pieces placed, as far as this pack's own files go."""
        if self._reached is not None:
            return self._reached
        project, store = self.project, self.structures
        ns, pool_dir = project.namespace, project.template_pool_dir
        pools = {f"{ns}:{path.relative_to(pool_dir).with_suffix('').as_posix()}": data
                 for path, data in project.pools()}
        edges: dict[str, set[str]] = {}

        def next_pools(pool_id: str) -> set[str]:
            if pool_id not in edges:
                data = pools.get(pool_id) or {}
                found = {namespaced(data["fallback"])} if isinstance(data.get("fallback"), str) else set()
                for location in pool_locations(data):
                    path = loc_to_path(namespaced(location), ns, store.dir, ".nbt")
                    if path is not None and path.exists():
                        found |= jigsaw_pools(store.try_load(path))
                edges[pool_id] = found
            return edges[pool_id]

        reached: dict[str, list[tuple[str, dict]]] = {}
        structure_dir = project.worldgen_structure_dir
        for path, data in project.json_dicts(structure_dir):
            start = data.get("start_pool")
            if not isinstance(start, str):
                continue
            seen = {namespaced(start)}
            todo = list(seen)
            while todo:
                for pool_id in next_pools(todo.pop()) - seen:
                    seen.add(pool_id)
                    todo.append(pool_id)
            file = f"structure/{path.relative_to(structure_dir).as_posix()}"
            for pool_id in seen:
                reached.setdefault(pool_id, []).append((file, data))
        self._reached = reached
        return reached

    def pool_versions(self) -> dict[str, list[str]]:
        """The targeted versions a pool is generated on, for each pool that only
        structures with their own ``mc_versions`` reach: the versions any of them names.
        A pool not listed here is generated on every targeted version."""
        if self._pool_versions is None:
            self._pool_versions = {}
            structure_dir = self.project.worldgen_structure_dir
            if structure_dir.exists() and any(
                    structure_gate(data) for _, data in self.project.json_dicts(structure_dir)):
                for pool_id, structures in self.structures_by_pool().items():
                    gates = [structure_gate(data) for _, data in structures]
                    served = [v for v in self.mc_versions if gates and all(gates)
                              and any(version_in_range(v, g) for g in gates)]
                    if served:   # a pool generated on no targeted version is left as it was
                        self._pool_versions[pool_id] = served
        return self._pool_versions

    def file_range(self, nbt_path: Path) -> FileRange:
        """Target range of a file: its wired range, else the whole project range."""
        info = self.nbt_ranges.get(nbt_path)
        if info is not None:
            lo, hi, wired = info.min_version, info.max_version, True
        else:
            lo, hi, wired = self.global_min, self.global_max, False
        vm = self.versions
        return FileRange(lo, hi, vm.get(lo), vm.get(hi), wired)

    def file_min_version(self, nbt_path: Path) -> str:
        info = self.nbt_ranges.get(nbt_path)
        return info.min_version if info is not None else self.global_min


def services(ctx) -> Services:
    svc = getattr(ctx, "_services", None)
    if svc is None:
        svc = Services(ctx)
        try:
            ctx._services = svc
        except AttributeError:
            pass  # a context without a __dict__: rebuild per call, still correct
    return svc
