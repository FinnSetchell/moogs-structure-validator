from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from utils.paths import data_dir as _data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


def _loc_to_path(location: str, namespace: str, base_dir: Path, ext: str) -> Path | None:
    if ":" not in location:
        return None
    ns, path = location.split(":", 1)
    if ns != namespace:
        return None
    return base_dir / (path + ext)


def _load_json(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [ERROR] Could not read {path.name}: {e}")
        return None


def _collect_pool_locations(pool_data: dict) -> list[str]:
    locations = []
    for entry in pool_data.get("elements", []):
        element = entry.get("element", {})
        loc = element.get("location")
        if loc:
            locations.append(loc)
        el_type = element.get("element_type") or element.get("type", "")
        if el_type == "moogs_structures:versioned_single_pool_element":
            for versioned_loc in element.get("locations", {}).values():
                locations.append(versioned_loc)
    return locations


def _check_pool_to_nbt(
    template_pool_dir: Path, structures_dir: Path, namespace: str
) -> list[str]:
    errors = []
    for json_path in sorted(template_pool_dir.rglob("*.json")):
        data = _load_json(json_path)
        if data is None:
            continue
        pool_rel = json_path.relative_to(template_pool_dir)
        for loc in _collect_pool_locations(data):
            nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
            if nbt_path is None:
                continue
            if not nbt_path.exists():
                errors.append(f"{pool_rel}  ->  {loc}  (no matching .nbt)")
    return errors


def _check_orphaned_nbt(
    template_pool_dir: Path, structures_dir: Path, namespace: str
) -> list[str]:
    referenced: set[Path] = set()
    for json_path in sorted(template_pool_dir.rglob("*.json")):
        data = _load_json(json_path)
        if data is None:
            continue
        for loc in _collect_pool_locations(data):
            nbt_path = _loc_to_path(loc, namespace, structures_dir, ".nbt")
            if nbt_path:
                referenced.add(nbt_path.resolve())

    orphans = []
    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() not in referenced:
            orphans.append(str(nbt_path.relative_to(structures_dir)))
    return orphans


def _check_structure_to_pool(
    worldgen_structure_dir: Path, template_pool_dir: Path, namespace: str
) -> list[str]:
    errors = []
    for json_path in sorted(worldgen_structure_dir.rglob("*.json")):
        data = _load_json(json_path)
        if data is None:
            continue
        start_pool = data.get("start_pool")
        if not start_pool:
            continue
        pool_path = _loc_to_path(start_pool, namespace, template_pool_dir, ".json")
        if pool_path is None:
            continue
        if not pool_path.exists():
            rel = json_path.relative_to(worldgen_structure_dir)
            errors.append(f"{rel}  ->  {start_pool}  (pool not found)")
    return errors


def _check_set_to_structure(
    structure_set_dir: Path, worldgen_structure_dir: Path, namespace: str
) -> list[str]:
    errors = []
    for json_path in sorted(structure_set_dir.rglob("*.json")):
        data = _load_json(json_path)
        if data is None:
            continue
        rel = json_path.relative_to(structure_set_dir)
        for entry in data.get("structures", []):
            structure_loc = entry.get("structure", "")
            struct_path = _loc_to_path(structure_loc, namespace, worldgen_structure_dir, ".json")
            if struct_path is None:
                continue
            if not struct_path.exists():
                errors.append(f"{rel}  ->  {structure_loc}  (worldgen structure not found)")
    return errors


def _check_pool_fallbacks(ctx: ValidatorContext, namespace_root: Path) -> list[str]:
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if not template_pool_dir.exists():
        return []
    errors = []
    for json_path in sorted(template_pool_dir.rglob("*.json")):
        data = _load_json(json_path)
        if data is None:
            continue
        fallback = data.get("fallback")
        if not isinstance(fallback, str) or ":" not in fallback:
            continue
        fallback_ns, fallback_path = fallback.split(":", 1)
        if fallback_ns == "minecraft":
            continue
        if fallback_ns != ctx.namespace:
            continue
        expected = template_pool_dir / (fallback_path + ".json")
        if not expected.exists():
            rel = json_path.relative_to(template_pool_dir)
            errors.append(f"{rel}  ->  fallback '{fallback}'  (pool not found)")
    return errors


def _check_msl_element_key(ctx: ValidatorContext, namespace_root: Path) -> list[str]:
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if not template_pool_dir.exists():
        return []
    errors = []
    for file in sorted(template_pool_dir.rglob("*.json")):
        data = _load_json(file)
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


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = _data_dir(namespace_root, "structure")
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    worldgen_structure_dir = namespace_root / "worldgen" / "structure"
    structure_set_dir = namespace_root / "worldgen" / "structure_set"

    for d in [structures_dir, template_pool_dir, worldgen_structure_dir, structure_set_dir]:
        if not d.exists():
            print(f"  directory not found: {d}")
            return False, "required directory missing"

    failed = False
    orphan_count = 0

    errors = _check_pool_to_nbt(template_pool_dir, structures_dir, ctx.namespace)
    if errors:
        print(f"  [1/6] Pool -> NBT        {len(errors)} missing:")
        for e in errors:
            print(f"          {e}")
        failed = True
    else:
        print(f"  [1/6] Pool -> NBT        OK")

    orphans = _check_orphaned_nbt(template_pool_dir, structures_dir, ctx.namespace)
    orphan_count = len(orphans)
    if orphans:
        print(f"  [2/6] Orphaned NBT       {orphan_count} unreferenced:")
        for o in orphans:
            print(f"          {o}")
    else:
        print(f"  [2/6] Orphaned NBT       OK")

    errors = _check_structure_to_pool(worldgen_structure_dir, template_pool_dir, ctx.namespace)
    if errors:
        print(f"  [3/6] Structure -> Pool  {len(errors)} missing:")
        for e in errors:
            print(f"          {e}")
        failed = True
    else:
        print(f"  [3/6] Structure -> Pool  OK")

    errors = _check_set_to_structure(structure_set_dir, worldgen_structure_dir, ctx.namespace)
    if errors:
        print(f"  [4/6] Set -> Structure   {len(errors)} missing:")
        for e in errors:
            print(f"          {e}")
        failed = True
    else:
        print(f"  [4/6] Set -> Structure   OK")

    fallback_errors = _check_pool_fallbacks(ctx, namespace_root)
    if fallback_errors:
        print(f"  [5/6] Pool fallbacks     {len(fallback_errors)} missing:")
        for e in fallback_errors:
            print(f"          {e}")
        failed = True
    else:
        print(f"  [5/6] Pool fallbacks     OK")

    msl_key_errors = _check_msl_element_key(ctx, namespace_root)
    if msl_key_errors:
        print(f"  [6/6] MSL element keys   {len(msl_key_errors)} bad:")
        for e in msl_key_errors:
            print(e)
        failed = True
    else:
        print(f"  [6/6] MSL element keys   OK")

    if failed:
        summary = "cross-reference errors found"
    elif orphan_count:
        summary = f"all cross-references OK  ({orphan_count} orphan warning)"
    else:
        summary = "all cross-references OK"

    return not failed, summary
