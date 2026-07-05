from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

import schemas.patcher

if TYPE_CHECKING:
    from validator import ValidatorContext

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

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

_schema_cache: dict[str, dict] = {}


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


def _check_msl_types(subdir: str, rel, data: dict) -> int:
    """Apply MSL type-specific schemas on top of the base schema pass.

    Unknown moogs_structures:* type ids are flagged (typo catcher): the game
    silently falls back or hard-fails on these, so they never work as intended.
    """
    errors = 0

    if subdir == "structure":
        stype = data.get("type")
        if isinstance(stype, str) and stype.startswith(_MSL_PREFIX):
            schema_file = _MSL_STRUCTURE_SCHEMAS.get(stype)
            if schema_file is None:
                print(f"  [{subdir}] {rel} @ type")
                print(f"    unknown MSL structure type {stype!r}")
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
                if schema_file is None:
                    print(f"  [{subdir}] {rel} @ {where}")
                    print(f"    unknown MSL pool element type {etype!r}")
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
                    if schema is None:
                        print(f"  [{subdir}] {rel} @ processors > {i}")
                        print(f"    unknown MSL processor type {ptype!r}")
                        errors += 1
                    else:
                        errors += _validate_against(schema, proc, subdir, rel, f"processors > {i}")

    elif subdir == "structure_set":
        placement = data.get("placement")
        if isinstance(placement, dict):
            ptype = placement.get("type")
            if isinstance(ptype, str) and ptype.startswith(_MSL_PREFIX):
                schema_file = _MSL_PLACEMENT_SCHEMAS.get(ptype)
                if schema_file is None:
                    print(f"  [{subdir}] {rel} @ placement > type")
                    print(f"    unknown MSL structure placement type {ptype!r}")
                    errors += 1
                else:
                    errors += _validate_against(schema_file, placement, subdir, rel, "placement")

    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace

    failed = False
    error_count = 0
    counts: dict[str, int] = {}

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

            msl_errors = _check_msl_types(subdir, rel, data)
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
