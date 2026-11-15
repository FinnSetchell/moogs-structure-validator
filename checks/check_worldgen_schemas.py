"""Worldgen JSON validates against the bundled vanilla and MSL schemas.

Template pools, structures, structure sets and processor lists are checked
against ``schemas/*.json``. Any ``moogs_structures:*`` type id is then
dispatched to its MSL schema; an id MSL does not register is an error (typo
catcher), except that a type MSL registers on *some* targeted version is real
content and stays silent (``_MSL_TYPE_WINDOWS``).

A type also has to exist in every MSL the mod allows: a ``moogs_structures:`` type
first shipped in a later MSL than the mod's declared ``moogs_structures`` minimum
(raised on each Minecraft version to the oldest MSL published there) is an error,
since with an older MSL the file names an unregistered type and fails to load
(``_MSL_TYPE_SINCE``). The same goes for a field MSL added to a type later
(``_MSL_FIELD_SINCE``): an older MSL skips it without a word, so what it sets is
lost there. And for a value MSL accepts in a field only from a later release
(``_MSL_VALUE_SINCE``): an older MSL cannot read it. A field some Minecraft line
of MSL never reads, in any release, warns on those versions (``_MSL_FIELD_WINDOWS``).

Two ``y_allowance`` shapes a JSON schema cannot express are checked by hand:
``max_y_allowed`` below ``min_y_allowed`` (MSL rejects it at datapack load), and
a ``max`` with no ``min`` on the generic jigsaw type (MSL unwraps the absent
``min`` and crashes chunk generation). So are the rules MSL's codec applies to a
versioned element's ``adaptation_area`` once it has read it: exactly one of
``columns`` or ``footprint``, ``[min, max]`` ranges, and a rigid projection.

A structure set's ``salt`` above 2147483647 warns: Minecraft keeps the low 32 bits
of it, so the set is placed with another salt than the one written (an error when
that comes out negative, which the salt's codec refuses).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

import schemas.patcher
from core import msl_upgrade
from core.context import services
from core.mcversions import DV_1_21, DV_VERSION_NAMES, BoundarySide, parse_version, side_of

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
_INT_MAX = 2 ** 31 - 1

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
_VERSIONED_ELEMENT = "moogs_structures:versioned_single_pool_element"
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

# The first MSL release that registers each type, from MSL's git tags (read with
# `git grep` on every tag) and its CHANGELOG. 3.0.0 added the processors (first
# tags 1.21.1-3.0.0-alpha.1 and 1.20.4-3.0.0-alpha.2; trial spawner and vault in
# commit 02c2aed), 3.1.0 the replace-vanilla processor and placement, 3.1.2 the
# hanging entity anchor, 3.5.0 the follow floor, rail slope and rail rotation processors
# (from their branches, follow-floor-processor and rail-slope-processor). MSL 1.x is not tagged,
# so it was read from the published jars themselves (the registration classes'
# string constants of 1.0.0, 1.0.1, 1.0.2 and 1.1.0 builds, on Fabric, Forge and
# NeoForge): every type in tag v2.0.0 is in
# 1.0.0 except versioned_single_pool_element, first in 1.1.0 (git: added 2025-11-11,
# after 1.0.2 shipped). Types not listed are in MSL 1.0.0, the first release.
_MSL_TYPE_SINCE: dict[str, tuple[int, int, int]] = {
    "moogs_structures:versioned_single_pool_element": (1, 1, 0),
    "moogs_structures:pillar_processor": (3, 0, 0),
    "moogs_structures:spawner_randomizing_processor": (3, 0, 0),
    "moogs_structures:trial_spawner_randomizing_processor": (3, 0, 0),
    "moogs_structures:vault_randomizing_processor": (3, 0, 0),
    "moogs_structures:equip_armor_stand_processor": (3, 0, 0),
    "moogs_structures:close_off_fluid_sources_processor": (3, 0, 0),
    "moogs_structures:remove_floating_blocks_processor": (3, 0, 0),
    "moogs_structures:random_replace_with_properties_processor": (3, 0, 0),
    "moogs_structures:super_gravity_processor": (3, 0, 0),
    "moogs_structures:flood_with_water_processor": (3, 0, 0),
    "moogs_structures:vanilla_loot_swap_processor": (3, 1, 0),
    "moogs_structures:conditional_concentric_rings": (3, 1, 0),
    "moogs_structures:hanging_entity_anchor_processor": (3, 1, 2),
    "moogs_structures:follow_floor_processor": (3, 5, 0),
    "moogs_structures:rail_slope_processor": (3, 5, 0),
    "moogs_structures:rail_rotation_processor": (3, 5, 0),
}

# Fields MSL added to a type after the type itself: the first release whose codec
# reads each, from the same pass over MSL's tags (`fieldOf` / `optionalFieldOf` per
# class; the first tag on any Minecraft line that reads it, and no line reads it
# earlier). An older MSL's codec skips the field without a word.
_MSL_FIELD_SINCE: dict[tuple[str, str], tuple[int, int, int]] = {
    ("moogs_structures:advanced_random_spread", "spacing_key"): (3, 1, 0),
    ("moogs_structures:advanced_random_spread", "structure_id"): (3, 1, 0),
    ("moogs_structures:advanced_random_spread", "when_replacing"): (3, 3, 0),
    ("moogs_structures:moogs_structures_generic_jigsaw_structure", "enhanced_terrain_adaptation"): (3, 4, 0),
    ("moogs_structures:moogs_structures_generic_nether_jigsaw_structure", "enhanced_terrain_adaptation"): (3, 0, 0),
    ("moogs_structures:mirroring_single_pool_element", "enhanced_terrain_adaptation"): (3, 0, 0),
    ("moogs_structures:legacy_ocean_bottom_single_pool_element", "enhanced_terrain_adaptation"): (3, 0, 0),
    ("moogs_structures:versioned_single_pool_element", "enhanced_terrain_adaptation"): (3, 0, 0),
    ("moogs_structures:versioned_single_pool_element", "adaptation_area"): (3, 6, 0),
}

# Values a field accepts only from a later MSL release, from the branch that adds them
# (mixed-adaptation: "none" in EnhancedTerrainAdaptation.CODEC). An older MSL's codec
# cannot read the value: from 1.20.5 the file fails to load, while on 1.20-1.20.4
# DataFixerUpper 6's optionalFieldOf drops a value it cannot read without a word.
_MSL_VALUE_SINCE: dict[tuple[str, str, str], tuple[int, int, int]] = {
    (type_id, "enhanced_terrain_adaptation", "none"): (3, 6, 0)
    for type_id in ("moogs_structures:moogs_structures_generic_jigsaw_structure",
                    "moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
                    "moogs_structures:versioned_single_pool_element",
                    "moogs_structures:mirroring_single_pool_element",
                    "moogs_structures:legacy_ocean_bottom_single_pool_element")
}

# Fields MSL reads on some Minecraft lines only, in every release: (first DataVersion
# read, first DataVersion no longer read, what is lost), as _MSL_TYPE_WINDOWS. No
# release of MSL's 1.20 lines (1.20-1.20.4 and 1.20.5-1.20.6, 3.0.0 to 3.4.x) reads a
# versioned element's own terrain adaptation; the 1.21 lines do from 3.0.0. Raising
# the minimum cannot help there, so it warns instead of failing.
_MSL_FIELD_WINDOWS: dict[tuple[str, str], tuple[int | None, int | None, str]] = {
    ("moogs_structures:versioned_single_pool_element", "enhanced_terrain_adaptation"): (
        DV_1_21, None,
        "MSL's 1.20 lines skip it on this pool element, so those pieces get no carving of their own "
        "there; the structure-wide carving (the structure's own enhanced_terrain_adaptation) still applies"),
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


def _check_adaptation_area(rel, where: str, element: dict) -> int:
    """MSL 3.6.0's checks on a versioned element's ``adaptation_area`` after its codec
    has read the fields (``AdaptationArea.check``, ``ColumnRect.RANGE``,
    ``VersionAwareSinglePoolElement.checkArea``). The rigid projection is checked on the
    whole element, so a terrain-matching one fails the pool on every version; the other
    two fail it from 1.20.5, while on 1.20-1.20.4 (DataFixerUpper 6) MSL drops the area
    without a word."""
    area = element.get("adaptation_area")
    if not isinstance(area, dict):
        return 0
    at = f"{where} > adaptation_area"
    problems: list[tuple[str, str]] = []
    if ("columns" in area) == ("footprint" in area):
        problems.append((at, 'needs exactly one of "columns" or "footprint"'))
    columns = area.get("columns")
    for i, rect in enumerate(columns if isinstance(columns, list) else []):
        for axis in ("x", "z"):
            pair = rect.get(axis) if isinstance(rect, dict) else None
            if (isinstance(pair, list) and len(pair) == 2 and all(isinstance(n, int) for n in pair)
                    and pair[0] > pair[1]):
                problems.append((f"{at} > columns > {i} > {axis}",
                                 f"a column range is [min, max], and {pair[0]} is more than {pair[1]}"))
    if element.get("projection") != "rigid":
        problems.append((at, 'needs "projection": "rigid"; MSL refuses the pool otherwise, as only a rigid '
                             'piece is shaped around'))
    for path, message in problems:
        print(f"  [template_pool] {rel} @ {path}")
        print(f"    {message}")
    return len(problems)


def _check_salt(rel, data: dict) -> tuple[int, int]:
    """``(errors, warnings)`` for a placement ``salt`` above the int range. Gson reads a JSON
    number lazily and the salt's codec (``ExtraCodecs.NON_NEGATIVE_INT``, in vanilla's
    placements and MSL's ``advanced_random_spread`` alike) takes its ``intValue()``, which
    keeps the low 32 bits: another salt, or a negative one the codec refuses."""
    placement = data.get("placement")
    salt = placement.get("salt") if isinstance(placement, dict) else None
    if isinstance(salt, bool) or not isinstance(salt, int) or salt <= _INT_MAX:
        return 0, 0
    read = (salt + 2 ** 31) % 2 ** 32 - 2 ** 31
    if read < 0:
        print(f"  [structure_set] {rel} @ placement > salt")
        print(f"    {salt} is above {_INT_MAX}: Minecraft keeps its low 32 bits, reads {read} and refuses "
              f"the set, as a salt cannot be negative")
        return 1, 0
    print(f"  [WARN] structure_set/{rel.as_posix() if hasattr(rel, 'as_posix') else rel} @ placement > salt")
    print(f"    {salt} is above {_INT_MAX}: Minecraft keeps its low 32 bits and places the set with "
          f"salt {read} instead")
    return 0, 1


def _check_msl_types(subdir: str, rel, data: dict, dv_range, used: dict | None = None) -> int:
    errors = 0

    def note(type_id, obj):
        if used is None:
            return
        where = f"{subdir}/{rel.as_posix() if hasattr(rel, 'as_posix') else rel}"
        used.setdefault(type_id, set()).add(where)
        for (t, field) in _MSL_FIELD_SINCE:
            if t == type_id and field in obj:
                used.setdefault((t, field), set()).add(where)
        for (t, field, value) in _MSL_VALUE_SINCE:
            if t == type_id and obj.get(field) == value:
                used.setdefault((t, field, value), set()).add(where)

    if subdir == "structure":
        stype = data.get("type")
        if isinstance(stype, str) and stype.startswith(_MSL_PREFIX):
            note(stype, data)
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
                note(etype, element)
                schema_file = _MSL_ELEMENT_SCHEMAS.get(etype)
                if schema_file is None or not _is_registered(etype, dv_range()):
                    print(f"  [{subdir}] {rel} @ {where}")
                    print(f"    {_unknown_reason('pool element type', etype, schema_file is not None)}")
                    errors += 1
                else:
                    errors += _validate_against(schema_file, element, subdir, rel, where)
                    if etype == _VERSIONED_ELEMENT:
                        errors += _check_adaptation_area(rel, where, element)

    elif subdir == "processor_list":
        processors = data.get("processors")
        if isinstance(processors, list):
            proc_schemas = _load_schema("msl_processors.json")
            for i, proc in enumerate(processors):
                if not isinstance(proc, dict):
                    continue
                ptype = proc.get("processor_type")
                if isinstance(ptype, str) and ptype.startswith(_MSL_PREFIX):
                    note(ptype, proc)
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
                note(ptype, placement)
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
    salt_warnings = 0
    counts: dict[str, int] = {}
    used_types: dict[str, set[str]] = {}

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
            n += _check_msl_types(subdir, rel, data, dv_range, used_types)
            if subdir == "structure_set" and isinstance(data, dict):
                salt_errors, salt_warns = _check_salt(rel, data)
                n += salt_errors
                salt_warnings += salt_warns
            if n:
                error_count += n
                failed = True

    n_msl = _check_msl_releases(ctx, svc, used_types)
    if n_msl:
        error_count += n_msl
        failed = True
    warn_count = _check_msl_field_windows(ctx, svc, used_types) + salt_warnings

    total = sum(counts.values())
    count_str = "  ".join(f"{k}: {v}" for k, v in counts.items() if v > 0)

    if error_count == 0:
        print(f"  {total} files validated, 0 schema errors")
    else:
        print(f"  {total} files validated, {error_count} schema error(s)")
    if count_str:
        print(f"  ({count_str})")

    summary = f"{total} files, 0 errors" if error_count == 0 else f"{total} files, {error_count} error(s)"
    if warn_count:
        summary += f", {warn_count} warning(s)"
    return not failed, summary


def _window_has(key, version_dv: int | None) -> bool:
    """Whether MSL reads a type (``type_id``), a field (``(type_id, field)``) or a
    field's value (``(type_id, field, value)``) on a version at all: its MC window, in
    any release."""
    if version_dv is None:
        return True
    if not isinstance(key, str):
        field = _MSL_FIELD_WINDOWS.get(key[:2])
        if field is not None and not _in_window(field[0], field[1], version_dv):
            return False
        key = key[0]
    window = _MSL_TYPE_WINDOWS.get(key)
    return window is None or _in_window(window[0], window[1], version_dv)


def _in_window(added, removed, version_dv: int) -> bool:
    return (added is None or version_dv >= added) and (removed is None or version_dv < removed)


def _check_msl_field_windows(ctx, svc, used: dict) -> int:
    """Warnings for fields no release of MSL reads on some targeted versions."""
    index = svc.versions if any(k in used for k in _MSL_FIELD_WINDOWS) else None
    if index is None:
        return 0
    order = sorted((v for v in ctx.mc_versions if parse_version(v)), key=parse_version)
    warns = 0
    for key, (added, removed, why) in sorted(_MSL_FIELD_WINDOWS.items()):
        if key not in used:
            continue
        skipped = [v for v in order if index.get(v) is not None and _window_has(key[0], index.get(v))
                   and not _in_window(added, removed, index.get(v))]
        if not skipped:
            continue
        warns += 1
        files = sorted(used[key])
        more = f" (+{len(files) - 3} more)" if len(files) > 3 else ""
        print(f"  [WARN] {key[0]} `{key[1]}` is skipped on {_version_runs(skipped, order)}")
        print(f"    {why}. In {', '.join(files[:3])}{more}.")
    return warns


def _check_msl_releases(ctx, svc, used: dict) -> int:
    """Types, fields and values first shipped in a later MSL than the oldest one the mod allows."""
    floored: dict = {t: since for t, since in _MSL_TYPE_SINCE.items() if t in used}
    floored.update({k: since for k, since in _MSL_FIELD_SINCE.items() if k in used})
    floored.update({k: since for k, since in _MSL_VALUE_SINCE.items() if k in used})
    if not floored:
        return 0
    declared, sources = msl_upgrade.declared_minimum(svc.project.root)
    if not sources:
        return 0   # not an MSL mod: the unknown-type error above already covers it
    builds = msl_upgrade.MslBuilds()
    index = svc.versions
    order = sorted((v for v in ctx.mc_versions if parse_version(v)), key=parse_version)
    errors = 0
    for key, since in sorted(floored.items(), key=lambda kv: str(kv[0])):
        type_id = key if isinstance(key, str) else key[0]
        short = []
        for v in order:
            if not _window_has(key, index.get(v) if index else None):
                continue
            eff = builds.effective(v, declared)
            if eff is not None and eff < since:
                short.append((v, eff))
        if not short:
            continue
        errors += 1
        lows = sorted({e for _, e in short})
        files = sorted(used[key])
        more = f" (+{len(files) - 3} more)" if len(files) > 3 else ""
        runs = _version_runs([v for v, _ in short], order)
        allows = f"this mod allows MSL {msl_upgrade.fmt(lows[0])} ({'; '.join(sources)})"
        if isinstance(key, str):
            print(f"  [msl] {type_id} first shipped in MSL {msl_upgrade.fmt(since)}")
            print(f"    on {runs} {allows}, which does not register it, so "
                  f"{', '.join(files[:3])}{more} fail to load there. Raise the moogs_structures minimum "
                  f"to {msl_upgrade.fmt(since)}{_fabric_hint(since)}.")
        elif len(key) == 3:
            named = f"{', '.join(files[:3])}{more}"
            fails = [v for v, _ in short if parse_version(v) >= (1, 20, 5)]
            dropped = [v for v, _ in short if parse_version(v) < (1, 20, 5)]
            effects = [f"{named} fail to load on {_version_runs(fails, order)}"] if fails else []
            if dropped:
                effects.append(f"on {_version_runs(dropped, order)} the field is dropped without a word, "
                               f"so {named} lose what it sets")
            print(f"  [msl] {type_id} `{key[1]}: \"{key[2]}\"` first accepted by MSL {msl_upgrade.fmt(since)}")
            print(f"    on {runs} {allows}, which cannot read it: {'; '.join(effects)}. Raise the "
                  f"moogs_structures minimum to {msl_upgrade.fmt(since)}{_fabric_hint(since)}.")
        else:
            print(f"  [msl] {type_id} `{key[1]}` first read by MSL {msl_upgrade.fmt(since)}")
            print(f"    on {runs} {allows}, which skips it without a word, so "
                  f"{', '.join(files[:3])}{more} lose what it sets there. Raise the moogs_structures "
                  f"minimum to {msl_upgrade.fmt(since)}{_fabric_hint(since)}.")
    return errors


def _fabric_hint(since) -> str:
    """MSL's 1.x and 2.x Fabric builds call themselves "1.1.0-1.20-1.20.4": Fabric and
    Quilt order that below 1.1.0, so the minimum is spelled with "-0" there."""
    if tuple(since) >= (3, 0, 0):
        return ""
    v = msl_upgrade.fmt(since)
    return (f" (`>={v}-0` in fabric.mod.json and quilt.mod.json: MSL's {v} Fabric builds carry a "
            f"suffix, which Fabric orders below {v}, so `>={v}` would reject them)")


def _version_runs(versions: list[str], order: list[str]) -> str:
    idx = {v: i for i, v in enumerate(order)}
    runs: list[list[str]] = []
    for v in versions:
        if runs and idx[v] == idx[runs[-1][-1]] + 1:
            runs[-1].append(v)
        else:
            runs.append([v])
    return ", ".join(r[0] if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in runs)


_patched_pool: list[dict] = []


def _patched_pool_schema() -> dict:
    if not _patched_pool:
        _patched_pool.append(schemas.patcher.apply_msl(_load_schema("template_pool.json")))
    return _patched_pool[0]
