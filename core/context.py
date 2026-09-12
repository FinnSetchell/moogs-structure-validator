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
from core.mcversions import VersionIndex, max_version, min_version
from core.project import Project
from core.ranges import NBTVersionInfo, build_nbt_version_ranges
from core.structures import StructureStore


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
        self.project = Project(Path(ctx.project_root), ctx.namespace)
        self.mc_versions: list[str] = list(getattr(ctx, "mc_versions", []) or [])
        self.refresh: bool = bool(getattr(ctx, "refresh", False))
        self.mcmeta = Mcmeta(self.mc_versions, CACHE_DIR, self.refresh)
        self.structures = StructureStore(self.project, getattr(ctx, "orphan_nbts", None))
        self._ranges: dict[Path, NBTVersionInfo] | None = None
        self._global: tuple[str, str] | None = None

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
                self._ranges = build_nbt_version_ranges(self.project, self.mc_versions)
            else:
                self._ranges = {}
        return self._ranges

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
