"""The reference chain between pools, structure files, worldgen structures and
structure sets, in both directions:

1. every location a template pool names exists on disk;
2. every structure file on disk is named by some pool (orphans warn);
3. every worldgen structure's ``start_pool`` exists;
4. every structure a structure_set names exists;
5. every worldgen structure is placed by something -- a structure_set in any
   namespace, or an MSL ``replace_vanilla`` replacement (a structure nothing
   places can never generate, and the failure is silent);
6. every pool ``fallback`` in our namespace exists;
7. MSL pool elements use ``element_type`` rather than ``type``.

An overlay pack (``"overlay": true`` in ``validator.json``) ships only part of
a data pack for a mod it extends, usually in that mod's namespace. None of the
four directories is required, a step whose directory is absent reports "not in
this pack", and a reference in steps 1 and 3-6 that does not resolve inside
the pack is listed as expected from the parent mod instead of failing: the
validator cannot see the parent. Step 2 (orphans) and step 7 (element keys) are
about the pack's own files and behave as for any mod.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core import replace_vanilla
from core.context import services
from core.project import Project, loc_to_path, pool_locations

if TYPE_CHECKING:
    from core.context import ValidatorContext


def _read(project: Project, path: Path) -> dict | None:
    return project.json_or_report(
        path, lambda e: print(f"  [ERROR] Could not read {path.name}: {e}")
    )


def _check_pool_to_nbt(project: Project) -> list[str]:
    errors = []
    pool_dir, structures_dir, ns = project.template_pool_dir, project.structures_dir, project.namespace
    for json_path in project.json_files(pool_dir):
        data = _read(project, json_path)
        if data is None:
            continue
        pool_rel = json_path.relative_to(pool_dir)
        for loc in pool_locations(data):
            nbt_path = loc_to_path(loc, ns, structures_dir, ".nbt")
            if nbt_path is not None and not nbt_path.exists():
                errors.append(f"{pool_rel}  ->  {loc}  (no matching .nbt)")
    return errors


def _check_orphaned_nbt(project: Project) -> list[str]:
    """Structure files (relative paths) that no template pool references."""
    referenced: set[Path] = set()
    structures_dir, ns = project.structures_dir, project.namespace
    for json_path in project.json_files(project.template_pool_dir):
        data = _read(project, json_path)
        if data is None:
            continue
        for loc in pool_locations(data):
            nbt_path = loc_to_path(loc, ns, structures_dir, ".nbt")
            if nbt_path:
                referenced.add(nbt_path.resolve())
    return [
        str(nbt_path.relative_to(structures_dir))
        for nbt_path in project.nbt_files(structures_dir)
        if nbt_path.resolve() not in referenced
    ]


def _check_structure_to_pool(project: Project) -> list[str]:
    errors = []
    structure_dir, pool_dir, ns = project.worldgen_structure_dir, project.template_pool_dir, project.namespace
    for json_path in project.json_files(structure_dir):
        data = _read(project, json_path)
        if data is None:
            continue
        start_pool = data.get("start_pool")
        if not start_pool:
            continue
        pool_path = loc_to_path(start_pool, ns, pool_dir, ".json")
        if pool_path is not None and not pool_path.exists():
            errors.append(f"{json_path.relative_to(structure_dir)}  ->  {start_pool}  (pool not found)")
    return errors


def _check_set_to_structure(project: Project) -> list[str]:
    errors = []
    set_dir, structure_dir, ns = project.structure_set_dir, project.worldgen_structure_dir, project.namespace
    for json_path in project.json_files(set_dir):
        data = _read(project, json_path)
        if data is None:
            continue
        rel = json_path.relative_to(set_dir)
        for entry in data.get("structures", []):
            structure_loc = entry.get("structure", "")
            struct_path = loc_to_path(structure_loc, ns, structure_dir, ".json")
            if struct_path is not None and not struct_path.exists():
                errors.append(f"{rel}  ->  {structure_loc}  (worldgen structure not found)")
    return errors


def _check_structure_placed(
    worldgen_structure_dir: Path, data_root: Path, namespace_root: Path, namespace: str,
    project: Project | None = None,
) -> list[str]:
    """Every worldgen structure must be placed by something.

    Two things count: an entry in any ``worldgen/structure_set`` under ``data/``
    (every namespace, since a pack may override a vanilla set to slot its
    structure in), or being a ``replacement_structure`` in an MSL
    ``replace_vanilla.json`` preset (it generates through the vanilla set).
    """
    if project is None:
        project = Project(data_root.parents[3], namespace)
    placed: set[str] = set()

    for set_dir in sorted(data_root.glob("*/worldgen/structure_set")):
        for json_path in project.json_files(set_dir):
            data = _read(project, json_path)
            if data is None:
                continue
            for entry in data.get("structures", []):
                loc = entry.get("structure")
                if isinstance(loc, str) and loc:
                    placed.add(loc if ":" in loc else f"minecraft:{loc}")

    manifest = replace_vanilla.load(project)
    if manifest is not None:
        for replacement in manifest.replacements:
            loc = replacement.replacement_structure
            if loc:
                placed.add(loc if ":" in loc else f"minecraft:{loc}")

    errors = []
    for json_path in project.json_files(worldgen_structure_dir):
        rel = json_path.relative_to(worldgen_structure_dir).with_suffix("").as_posix()
        if f"{namespace}:{rel}" not in placed:
            errors.append(
                f"{rel}.json  ->  in no structure_set, and not an MSL"
                f" replace_vanilla replacement_structure  (can never generate)"
            )
    return errors


def _check_pool_fallbacks(project: Project) -> list[str]:
    pool_dir = project.template_pool_dir
    if not pool_dir.exists():
        return []
    errors = []
    for json_path in project.json_files(pool_dir):
        data = _read(project, json_path)
        if data is None:
            continue
        fallback = data.get("fallback")
        if not isinstance(fallback, str) or ":" not in fallback:
            continue
        fallback_ns, fallback_path = fallback.split(":", 1)
        if fallback_ns != project.namespace:
            continue
        if not (pool_dir / (fallback_path + ".json")).exists():
            errors.append(f"{json_path.relative_to(pool_dir)}  ->  fallback '{fallback}'  (pool not found)")
    return errors


def _check_msl_element_key(project: Project) -> list[str]:
    pool_dir = project.template_pool_dir
    if not pool_dir.exists():
        return []
    errors = []
    for file in project.json_files(pool_dir):
        data = _read(project, file)
        if data is None:
            continue
        for entry in data.get("elements", []):
            target = entry.get("element", entry)
            value = target.get("type", "")
            if value.startswith("moogs_structures:"):
                errors.append(
                    f'  [ERROR] {file.name}: element uses "type" for {value!r} — must use "element_type" instead'
                )
    return errors


def _report(step: str, label: str, errors: list[str], noun: str, indent: str = "          ") -> bool:
    if errors:
        print(f"  {step} {label}{len(errors)} {noun}:")
        for e in errors:
            print(f"{indent}{e}" if indent else e)
        return True
    print(f"  {step} {label}OK")
    return False


def _report_outside(step: str, label: str, refs: list[str]) -> None:
    """An overlay pack's unresolved references: listed, never a failure."""
    if refs:
        print(f"  {step} {label}{len(refs)} not in this pack (expected from the parent mod):")
        for r in refs:
            print(f"          {r}")
    else:
        print(f"  {step} {label}OK")


def _run_overlay(project: Project) -> tuple[bool, str]:
    have_structures = project.structures_dir.exists()
    have_pools = project.template_pool_dir.exists()
    have_worldgen = project.worldgen_structure_dir.exists()
    have_sets = project.structure_set_dir.exists()

    def absent(step: str, label: str) -> None:
        print(f"  {step} {label}not in this pack")

    outside = 0

    def step(num: str, label: str, present: bool, compute) -> None:
        nonlocal outside
        if not present:
            absent(num, label)
            return
        refs = compute()
        outside += len(refs)
        _report_outside(num, label, refs)

    step("[1/7]", "Pool -> NBT        ", have_pools, lambda: _check_pool_to_nbt(project))

    orphans: list[str] = []
    if have_structures and have_pools:
        orphans = _check_orphaned_nbt(project)
        _report("[2/7]", "Orphaned NBT       ", orphans, "unreferenced")
    else:
        absent("[2/7]", "Orphaned NBT       ")

    step("[3/7]", "Structure -> Pool  ", have_worldgen, lambda: _check_structure_to_pool(project))
    step("[4/7]", "Set -> Structure   ", have_sets, lambda: _check_set_to_structure(project))
    step("[5/7]", "Structure -> Set   ", have_worldgen, lambda: _check_structure_placed(
        project.worldgen_structure_dir, project.data_root, project.namespace_root, project.namespace, project,
    ))
    step("[6/7]", "Pool fallbacks     ", have_pools, lambda: _check_pool_fallbacks(project))

    failed = False
    if have_pools:
        failed = _report("[7/7]", "MSL element keys   ", _check_msl_element_key(project), "bad", indent="")
    else:
        absent("[7/7]", "MSL element keys   ")

    if failed:
        return False, "cross-reference errors found"
    notes = []
    if orphans:
        notes.append(f"{len(orphans)} orphan warning")
    if outside:
        notes.append(f"{outside} expected from the parent mod")
    summary = "all cross-references OK"
    return True, f"{summary}  ({', '.join(notes)})" if notes else summary


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    project = services(ctx).project
    if project.overlay:
        return _run_overlay(project)

    for d in [project.structures_dir, project.template_pool_dir,
              project.worldgen_structure_dir, project.structure_set_dir]:
        if not d.exists():
            print(f"  directory not found: {d}")
            return False, "required directory missing"

    failed = False
    failed |= _report("[1/7]", "Pool -> NBT        ", _check_pool_to_nbt(project), "missing")

    orphans = _check_orphaned_nbt(project)
    _report("[2/7]", "Orphaned NBT       ", orphans, "unreferenced")

    failed |= _report("[3/7]", "Structure -> Pool  ", _check_structure_to_pool(project), "missing")
    failed |= _report("[4/7]", "Set -> Structure   ", _check_set_to_structure(project), "missing")
    failed |= _report("[5/7]", "Structure -> Set   ", _check_structure_placed(
        project.worldgen_structure_dir, project.data_root, project.namespace_root, project.namespace, project,
    ), "unplaced")
    failed |= _report("[6/7]", "Pool fallbacks     ", _check_pool_fallbacks(project), "missing")
    failed |= _report("[7/7]", "MSL element keys   ", _check_msl_element_key(project), "bad", indent="")

    if failed:
        summary = "cross-reference errors found"
    elif orphans:
        summary = f"all cross-references OK  ({len(orphans)} orphan warning)"
    else:
        summary = "all cross-references OK"
    return not failed, summary
