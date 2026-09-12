"""Worldgen JSON validates against the bundled vanilla and MSL schemas.

Template pools, structures, structure sets and processor lists are checked
against ``schemas/*.json``. Any ``moogs_structures:*`` type id is then
dispatched to its MSL schema; an id MSL does not register is an error (typo
catcher), except that a type MSL registers on *some* targeted version is real
content and stays silent (``_MSL_TYPE_WINDOWS``).

Two ``y_allowance`` shapes a JSON schema cannot express are checked by hand:
``max_y_allowed`` below ``min_y_allowed`` (MSL rejects it at datapack load), and
a ``max`` with no ``min`` on the generic jigsaw type (MSL unwraps the absent
``min`` and crashes chunk generation).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

import schemas.patcher
from core.context import services
from core.mcversions import DV_1_21, DV_VERSION_NAMES, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

_SUBDIRS: list[tuple[str, str]] = [
    ("template_pool",  "template_pool.json"),
    ("structure",      "structure.json"),
    ("structure_set",  "structure_set.json"),
    ("processor_list", "processor_list.json"),
]

_MSL_PREFIX = "moogs_structures:"

# GenericJigsawStructure.offsetToNewHeight unwraps minYAllowed inside a branch guarded
# only on maxYAllowed, so this type crashes chunkgen when a y_allowance has a max and no
# min. The nether type overrides that code path and is not affected.
_CRASHING_Y_ALLOWANCE_TYPE = "moogs_structures:moogs_structures_generic_jigsaw_structure"

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
    "moogs_structures:conditional_concentric_rings": "msl_conditional_concentric_rings.json",
}

# MSL's registries are not identical across Minecraft versions: a few types exist on
# one side of a boundary only, because they wrap (or work around) vanilla features that
# appeared or disappeared there. Every type NOT listed here is registered identically on
# every MSL branch (verified by diffing the modinit registries across 1.20-1.20.4,
# 1.20.5-1.20.6, 1.21-1.21.1, 1.21.2-1.21.3, 1.21.4, 1.21.5-1.21.10, 1.21.11,
# 26.1.0-26.1.2 and 26.2.0; only MoogsStructuresProcessors differs).
#
# Values are (added_dv, removed_dv): the first DataVersion MSL registers the type
# (None = always) and the first at which it no longer does (None = still does).
_MSL_TYPE_WINDOWS: dict[str, tuple[int | None, int | None]] = {
    "moogs_structures:waterlogging_fix_processor": (None, DV_1_21),      # 1.20 line only
    "moogs_structures:trial_spawner_randomizing_processor": (DV_1_21, None),
    "moogs_structures:vault_randomizing_processor": (DV_1_21, None),
}

_schema_cache: dict[str, dict] = {}
_validator_cache: dict[int, jsonschema.Draft4Validator] = {}


def _resolve_local_refs(node):
    """Inline ``{"$ref": "<file>.json"}`` nodes pointing at sibling schema files."""
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
        with (_SCHEMAS_DIR / filename).open(encoding="utf-8") as f:
            _schema_cache[filename] = _resolve_local_refs(json.load(f))
    return _schema_cache[filename]


def _validator_for(schema: dict) -> jsonschema.Draft4Validator:
    """One compiled validator per schema object (they are all module-level singletons)."""
    v = _validator_cache.get(id(schema))
    if v is None:
        v = jsonschema.Draft4Validator(schema)
        _validator_cache[id(schema)] = v
    return v


def _is_registered(type_id: str, dv_range: tuple[int, int] | None) -> bool:
    """True if MSL registers ``type_id`` on at least ONE targeted MC version.

    Deliberately asymmetric: a type is unknown only when it is unknown for EVERY
    targeted version. A branch is one artifact shipped across a whole MC range,
    and content that works anywhere in that range is content the author meant.
    """
    window = _MSL_TYPE_WINDOWS.get(type_id)
    if window is None or dv_range is None:
        return True  # registered everywhere, or range unresolvable: stay quiet
    added, removed = window
    min_dv, max_dv = dv_range
    if added is not None and side_of(min_dv, max_dv, added) == BoundarySide.OLD:
        return False
    if removed is not None and side_of(min_dv, max_dv, removed) == BoundarySide.NEW:
        return False
    return True


def _unknown_reason(kind: str, type_id: str, in_registry: bool) -> str:
    if not in_registry:
        return f"unknown MSL {kind} {type_id!r}"
    added, removed = _MSL_TYPE_WINDOWS[type_id]
    if removed is not None:
        boundary = DV_VERSION_NAMES.get(removed, f"DataVersion {removed}")
        return (f"MSL {kind} {type_id!r} was removed at {boundary};"
                f" no targeted MC version registers it")
    boundary = DV_VERSION_NAMES.get(added, f"DataVersion {added}")
    return (f"MSL {kind} {type_id!r} was only added at {boundary};"
            f" no targeted MC version registers it")


def _print_errors(validator: jsonschema.Draft4Validator, data, subdir: str, rel, where: str) -> int:
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    for error in errors:
        path_str = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else where
        print(f"  [{subdir}] {rel} @ {path_str}")
        print(f"    {error.message}")
    return len(errors)


def _validate_against(schema: str | dict, data, subdir: str, rel, where: str) -> int:
    if isinstance(schema, str):
        schema = _load_schema(schema)
    return _print_errors(_validator_for(schema), data, subdir, rel, where)


def _iter_pool_elements(data: dict):
    """``(index_path, element)`` for every element, recursing into list_pool_element."""
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


def _check_y_allowance(rel, stype: str, data: dict) -> int:
    allowance = data.get("y_allowance")
    if not isinstance(allowance, dict):
        return 0
    min_y = allowance.get("min_y_allowed")
    max_y = allowance.get("max_y_allowed")
    if isinstance(min_y, int) and isinstance(max_y, int) and max_y < min_y:
        print(f"  [structure] {rel} @ y_allowance")
        print(f"    max_y_allowed {max_y} is less than min_y_allowed {min_y}")
        return 1
    if max_y is not None and min_y is None and stype == _CRASHING_Y_ALLOWANCE_TYPE:
        print(f"  [structure] {rel} @ y_allowance")
        print(f"    max_y_allowed {max_y} is set with no min_y_allowed;"
              f" this crashes chunk generation")
        print(f"    add min_y_allowed (the dimension floor, e.g. -64,"
              f" preserves current behaviour)")
        return 1
    return 0


def _check_msl_types(subdir: str, rel, data: dict, dv_range) -> int:
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
                errors += _check_y_allowance(rel, stype, data)

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
    svc = services(ctx)
    project = svc.project

    # Lazy: the version map may need the network, and most files only use types
    # registered on every MSL branch. Resolved on first use, at most once.
    resolved: list[tuple[int, int] | None] = []

    def dv_range() -> tuple[int, int] | None:
        if not resolved:
            index = svc.versions
            resolved.append(index.dv_range(list(ctx.mc_versions)) if index else None)
        return resolved[0]

    failed = False
    error_count = 0
    counts: dict[str, int] = {}

    for subdir, schema_file in _SUBDIRS:
        worldgen_dir = project.namespace_root / "worldgen" / subdir
        if not worldgen_dir.exists():
            continue

        schema = _load_schema(schema_file)
        if subdir == "template_pool":
            schema = _patched_pool_schema()
        validator = _validator_for(schema)

        files = project.json_files(worldgen_dir)
        counts[subdir] = len(files)

        for json_path in files:
            rel = json_path.relative_to(worldgen_dir)
            try:
                data = project.load_json(json_path)
            except json.JSONDecodeError as e:
                print(f"  [{subdir}] {rel} — invalid JSON: {e}")
                error_count += 1
                failed = True
                continue

            n = _print_errors(validator, data, subdir, rel, "(root)")
            n += _check_msl_types(subdir, rel, data, dv_range)
            if n:
                error_count += n
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


_patched_pool: list[dict] = []


def _patched_pool_schema() -> dict:
    if not _patched_pool:
        _patched_pool.append(schemas.patcher.apply_msl(_load_schema("template_pool.json")))
    return _patched_pool[0]
