from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

import schemas.patcher
from utils.boundaries import BOUNDARIES, DV_1_21, BoundarySide, side_of
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
_CACHE_DIR = Path(__file__).parent.parent / "cache"

_SUBDIRS: list[tuple[str, str]] = [
    ("template_pool",  "template_pool.json"),
    ("structure",      "structure.json"),
    ("structure_set",  "structure_set.json"),
    ("processor_list", "processor_list.json"),
]

_MSL_PREFIX = "moogs_structures:"

# MSL type-specific schemas, dispatched on the "type" / "element_type" value.
_MSL_STRUCTURE_SCHEMAS: dict[str, str] = {
    "moogs_structures:moogs_structures_generic_jigsaw_structure": "msl_generic_jigsaw_structure.json",
    "moogs_structures:moogs_structures_generic_nether_jigsaw_structure": "msl_generic_nether_jigsaw_structure.json",
}
_MSL_ELEMENT_SCHEMAS: dict[str, str] = {
    "moogs_structures:versioned_single_pool_element": "msl_versioned_pool_element.json",
    "moogs_structures:mirroring_single_pool_element": "msl_mirroring_pool_element.json",
    "moogs_structures:legacy_ocean_bottom_single_pool_element": "msl_legacy_ocean_bottom_pool_element.json",
}
_MSL_PLACEMENT_SCHEMAS: dict[str, str] = {
    "moogs_structures:advanced_random_spread": "msl_advanced_random_spread.json",
}

# MSL's own registries are not stable across Minecraft versions: a handful of types
# exist only on one side of a version boundary, because they wrap (or work around)
# vanilla features that themselves appeared or disappeared there. Every type NOT
# listed here is registered identically on every MSL branch -- verified by diffing
# the four modinit registries across 1.20-1.20.4, 1.20.5-1.20.6, 1.21-1.21.1,
# 1.21.2-1.21.3, 1.21.4, 1.21.5-1.21.10, 1.21.11, 26.1.0-26.1.2 and 26.2.0. Only
# MoogsStructuresProcessors differs; MoogsStructuresStructures,
# MoogsStructuresStructurePieces (pool elements), MoogsStructuresPlacements and
# MoogsStructuresStructurePlacementType are identical on all nine branches.
#
# Values are (added_dv, removed_dv) as DataVersions, reusing the named boundary
# constants in utils.boundaries:
#   added_dv    first DataVersion at which MSL registers the type (None = always had it)
#   removed_dv  first DataVersion at which MSL no longer registers it (None = still has it)
_MSL_TYPE_WINDOWS: dict[str, tuple[int | None, int | None]] = {
    # Registered on the 1.20 line only. Dropped when MSL moved to 1.21.
    "moogs_structures:waterlogging_fix_processor": (None, DV_1_21),
    # Wrap trial spawners / vaults, which are 1.21 vanilla features.
    "moogs_structures:trial_spawner_randomizing_processor": (DV_1_21, None),
    "moogs_structures:vault_randomizing_processor": (DV_1_21, None),
}

# DataVersion -> the MC version that introduced it, for human-readable messages.
_DV_VERSION_NAMES: dict[int, str] = {b.dv: b.first_new_version for b in BOUNDARIES.values()}

_schema_cache: dict[str, dict] = {}


def _resolve_dv_range(ctx) -> tuple[int, int] | None:
    """(min, max) DataVersion across every MC version the repo targets, or None.

    Same source of truth the other version-sensitive checks use
    (check_entity_equipment_shape): utils.versions.load_version_map maps MC version
    -> DataVersion, and utils.boundaries.side_of decides which side of a named
    boundary a (min, max) range sits on.

    Returns None -- meaning "do not version-gate at all" -- when the map is
    unavailable or any targeted version is missing from it. That can only ever
    under-report a genuinely dead type; it can never invent a false positive,
    which is the failure mode this gating exists to remove.
    """
    version_map = load_version_map(_CACHE_DIR, getattr(ctx, "refresh", False))
    if not version_map:
        return None
    dvs = [version_map.get(v) for v in getattr(ctx, "mc_versions", [])]
    if not dvs or any(dv is None for dv in dvs):
        return None
    return min(dvs), max(dvs)


def _dv_range_resolver(ctx):
    """Memoised, lazy accessor for _resolve_dv_range.

    Lazy on purpose: load_version_map can hit the network, and the overwhelming
    majority of files use types that are registered on every MSL branch. The map is
    only consulted once a type from _MSL_TYPE_WINDOWS actually turns up.
    """
    cached: list[tuple[int, int] | None] = []

    def resolve() -> tuple[int, int] | None:
        if not cached:
            cached.append(_resolve_dv_range(ctx))
        return cached[0]

    return resolve


def _is_registered(type_id: str, dv_range: tuple[int, int] | None) -> bool:
    """True if MSL registers `type_id` on at least ONE targeted MC version.

    The rule -- deliberately asymmetric -- is: a type is "unknown" only when it is
    unknown for EVERY version the repo targets. A branch is one artifact shipped
    across a whole MC range, and content that works anywhere in that range is
    content the author meant to write; flagging it would be a false positive.
    So a 1.20-1.20.6 branch stays silent about waterlogging_fix_processor (MSL
    registers it across all of 1.20), while a 1.21+ branch is still told about it,
    because there it really is dead data.
    """
    window = _MSL_TYPE_WINDOWS.get(type_id)
    if window is None:
        return True  # registered on every MSL branch
    if dv_range is None:
        return True  # version range unresolvable -- stay quiet rather than guess
    added, removed = window
    min_dv, max_dv = dv_range
    if added is not None and side_of(min_dv, max_dv, added) == BoundarySide.OLD:
        return False  # every targeted version predates the type's introduction
    if removed is not None and side_of(min_dv, max_dv, removed) == BoundarySide.NEW:
        return False  # every targeted version postdates the type's removal
    return True


def _unknown_reason(kind: str, type_id: str, in_registry: bool) -> str:
    """Message for a rejected moogs_structures:* type id."""
    if not in_registry:
        return f"unknown MSL {kind} {type_id!r}"
    added, removed = _MSL_TYPE_WINDOWS[type_id]
    if removed is not None:
        boundary = _DV_VERSION_NAMES.get(removed, f"DataVersion {removed}")
        return (f"MSL {kind} {type_id!r} was removed at {boundary};"
                f" no targeted MC version registers it")
    boundary = _DV_VERSION_NAMES.get(added, f"DataVersion {added}")
    return (f"MSL {kind} {type_id!r} was only added at {boundary};"
            f" no targeted MC version registers it")


def _resolve_local_refs(node):
    """Inline {"$ref": "<file>.json"} nodes pointing at sibling schema files."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.endswith(".json"):
            return _load_schema(ref)
        return {k: _resolve_local_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_local_refs(x) for x in node]
    return node


def _load_schema(filename: str) -> dict:
    if filename not in _schema_cache:
        with (_SCHEMAS_DIR / filename).open() as f:
            _schema_cache[filename] = _resolve_local_refs(json.load(f))
    return _schema_cache[filename]


def _validate_against(schema: str | dict, data: dict, subdir: str, rel, where: str) -> int:
    """Validate data against a type-specific schema; print and count errors."""
    if isinstance(schema, str):
        schema = _load_schema(schema)
    validator = jsonschema.Draft4Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    for error in errors:
        path_str = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else where
        print(f"  [{subdir}] {rel} @ {path_str}")
        print(f"    {error.message}")
    return len(errors)


def _iter_pool_elements(data: dict):
    """Yield (index_path, element_dict) for every element in a template pool,
    recursing into list_pool_element nesting."""
    def walk(elements, prefix):
        for i, entry in enumerate(elements):
            if not isinstance(entry, dict):
                continue
            element = entry.get("element", entry)
            if not isinstance(element, dict):
                continue
            yield f"{prefix}elements > {i}", element
            nested = element.get("elements")
            if isinstance(nested, list):
                yield from walk(nested, f"{prefix}elements > {i} > ")

    elements = data.get("elements")
    if isinstance(elements, list):
        yield from walk(elements, "")


def _check_msl_types(subdir: str, rel, data: dict, dv_range) -> int:
    """Apply MSL type-specific schemas on top of the base schema pass.

    Unknown moogs_structures:* type ids are flagged (typo catcher): the game
    silently falls back or hard-fails on these, so they never work as intended.

    `dv_range` is the memoised resolver from _dv_range_resolver; a known type is
    only rejected when MSL registers it on none of the repo's target versions
    (see _is_registered).
    """
    errors = 0

    if subdir == "structure":
        stype = data.get("type")
        if isinstance(stype, str) and stype.startswith(_MSL_PREFIX):
            schema_file = _MSL_STRUCTURE_SCHEMAS.get(stype)
            if schema_file is None or not _is_registered(stype, dv_range()):
                print(f"  [{subdir}] {rel} @ type")
                print(f"    {_unknown_reason('structure type', stype, schema_file is not None)}")
                errors += 1
            else:
                errors += _validate_against(schema_file, data, subdir, rel, "(root)")
                # MSL throws at datapack load when max_y_allowed < min_y_allowed;
                # json schema can't compare fields, so check it here.
                allowance = data.get("y_allowance")
                if isinstance(allowance, dict):
                    min_y = allowance.get("min_y_allowed")
                    max_y = allowance.get("max_y_allowed")
                    if isinstance(min_y, int) and isinstance(max_y, int) and max_y < min_y:
                        print(f"  [{subdir}] {rel} @ y_allowance")
                        print(f"    max_y_allowed {max_y} is less than min_y_allowed {min_y}")
                        errors += 1

    elif subdir == "template_pool":
        for where, element in _iter_pool_elements(data):
            etype = element.get("element_type") or element.get("type")
            if isinstance(etype, str) and etype.startswith(_MSL_PREFIX):
                schema_file = _MSL_ELEMENT_SCHEMAS.get(etype)
                if schema_file is None or not _is_registered(etype, dv_range()):
                    print(f"  [{subdir}] {rel} @ {where}")
                    print(f"    {_unknown_reason('pool element type', etype, schema_file is not None)}")
                    errors += 1
                else:
                    errors += _validate_against(schema_file, element, subdir, rel, where)

    elif subdir == "processor_list":
        processors = data.get("processors")
        if isinstance(processors, list):
            proc_schemas = _load_schema("msl_processors.json")
            for i, proc in enumerate(processors):
                if not isinstance(proc, dict):
                    continue
                ptype = proc.get("processor_type")
                if isinstance(ptype, str) and ptype.startswith(_MSL_PREFIX):
                    schema = proc_schemas.get(ptype)
                    if schema is None or not _is_registered(ptype, dv_range()):
                        print(f"  [{subdir}] {rel} @ processors > {i}")
                        print(f"    {_unknown_reason('processor type', ptype, schema is not None)}")
                        errors += 1
                    else:
                        errors += _validate_against(schema, proc, subdir, rel, f"processors > {i}")

    elif subdir == "structure_set":
        placement = data.get("placement")
        if isinstance(placement, dict):
            ptype = placement.get("type")
            if isinstance(ptype, str) and ptype.startswith(_MSL_PREFIX):
                schema_file = _MSL_PLACEMENT_SCHEMAS.get(ptype)
                if schema_file is None or not _is_registered(ptype, dv_range()):
                    print(f"  [{subdir}] {rel} @ placement > type")
                    print(f"    {_unknown_reason('structure placement type', ptype, schema_file is not None)}")
                    errors += 1
                else:
                    errors += _validate_against(schema_file, placement, subdir, rel, "placement")

    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace

    failed = False
    error_count = 0
    counts: dict[str, int] = {}
    dv_range = _dv_range_resolver(ctx)

    for subdir, schema_file in _SUBDIRS:
        worldgen_dir = namespace_root / "worldgen" / subdir
        if not worldgen_dir.exists():
            continue

        schema = _load_schema(schema_file)
        if subdir == "template_pool":
            schema = schemas.patcher.apply_msl(schema)

        validator = jsonschema.Draft4Validator(schema)

        files = sorted(worldgen_dir.rglob("*.json"))
        counts[subdir] = len(files)

        for json_path in files:
            rel = json_path.relative_to(worldgen_dir)
            try:
                with json_path.open(encoding="utf-8-sig") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  [{subdir}] {rel} — invalid JSON: {e}")
                error_count += 1
                failed = True
                continue

            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            for error in errors:
                path_str = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
                print(f"  [{subdir}] {rel} @ {path_str}")
                print(f"    {error.message}")
                error_count += 1
                failed = True

            msl_errors = _check_msl_types(subdir, rel, data, dv_range)
            if msl_errors:
                error_count += msl_errors
                failed = True

    total = sum(counts.values())
    count_str = "  ".join(f"{k}: {v}" for k, v in counts.items() if v > 0)

    if error_count == 0:
        print(f"  {total} files validated, 0 schema errors")
    else:
        print(f"  {total} files validated, {error_count} schema error(s)")
    if count_str:
        print(f"  ({count_str})")

    summary = f"{total} files, 0 errors" if error_count == 0 else f"{total} files, {error_count} error(s)"
    return not failed, summary
