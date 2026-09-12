"""Every structure file of the project, loaded once and shared by all checks."""
from __future__ import annotations

from pathlib import Path

from core.nbt import Structure, load_structure
from core.project import Project


class StructureStore:
    def __init__(self, project: Project, orphans: set[Path] | None = None) -> None:
        self.project = project
        self.dir = project.structures_dir
        self._orphans_given = orphans
        self._orphans: set[Path] | None = None
        self._loaded: dict[Path, tuple[Structure | None, Exception | None]] = {}
        self._resolved: dict[Path, Path] = {}

    @property
    def files(self) -> list[Path]:
        """Every ``.nbt`` under the structures directory, sorted."""
        return self.project.nbt_files(self.dir)

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.dir))

    def resolved(self, path: Path) -> Path:
        hit = self._resolved.get(path)
        if hit is None:
            hit = path.resolve()
            self._resolved[path] = hit
        return hit

    def set_orphans(self, orphans: set[Path]) -> None:
        """Replace the orphan set (the CLI computes it after building the context)."""
        self._orphans_given = orphans
        self._orphans = None

    def is_orphan(self, path: Path) -> bool:
        """Whether no template pool references this file."""
        if self._orphans is None:
            given = self._orphans_given or set()
            self._orphans = {self.resolved(p) for p in given} | set(given)
        return bool(self._orphans) and self.resolved(path) in self._orphans

    def checked_files(self) -> list[Path]:
        """Files the content checks look at: everything that is not an orphan."""
        return [p for p in self.files if not self.is_orphan(p)]

    def load(self, path: Path) -> Structure:
        """The parsed structure, cached. Re-raises the load error each time for
        a file that cannot be read, so every check reports it the same way."""
        hit = self._loaded.get(path)
        if hit is None:
            try:
                hit = (load_structure(path), None)
            except Exception as e:
                hit = (None, e)
            self._loaded[path] = hit
        structure, err = hit
        if err is not None:
            raise err
        return structure  # type: ignore[return-value]

    def try_load(self, path: Path) -> Structure | None:
        try:
            return self.load(path)
        except Exception:
            return None

    def preload(self) -> None:
        """Parse every file up front (each later check then finds it cached)."""
        for p in self.files:
            self.try_load(p)
