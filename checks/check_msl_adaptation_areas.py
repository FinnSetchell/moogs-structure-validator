"""Adaptation areas that do less than they say (MSL 3.6.0+, warn-only).

A versioned element's ``adaptation_area`` narrows MSL's enhanced terrain adaptation
to some columns of a rigid piece, and with ``outside_follows_ground`` the columns
outside it follow the ground. ``check_worldgen_schemas`` checks its shape. MSL
loads all of these, but they shape less than the author expects:

* nothing to shape with: neither the element nor a structure that reaches its pool
  has an ``enhanced_terrain_adaptation`` that changes the ground (absent, ``"none"``,
  or settings with a kernel radius of 0 or nothing to do above and below), so only
  ``outside_follows_ground`` does anything;
* a structure that reaches the pool is not one of MSL's two jigsaw types, the only
  ones MSL shapes the ground for (``outside_follows_ground`` still works there);
* ``outside_follows_ground`` under a structure whose vanilla ``terrain_adaptation`` is
  not ``none``: vanilla beards the whole box first, so the outside has nothing left
  to follow;
* a ``columns`` rectangle that runs past the template's size, read from each NBT the
  element names: MSL ignores the columns outside the piece.

A structure reaches a pool through its ``start_pool``, each pool's ``fallback`` and
the jigsaw blocks of the pieces placed, as far as this pack's own files go.

Not checked: a ``footprint`` that matches no block. That needs the contents of its
block tag (vanilla tags differ by Minecraft version), which the validator does not
load.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from checks.check_worldgen_schemas import _iter_pool_elements
from core.context import Services, services
from core.nbt import Structure
from core.project import MSL_VERSIONED_ELEMENT, element_type, loc_to_path, namespaced, pool_locations

if TYPE_CHECKING:
    from core.context import ValidatorContext

_MSL_JIGSAW_STRUCTURES = {
    "moogs_structures:moogs_structures_generic_jigsaw_structure",
    "moogs_structures:moogs_structures_generic_nether_jigsaw_structure",
}


def _shapes_ground(adaptation) -> bool:
    """Whether an ``enhanced_terrain_adaptation`` changes the ground. MSL reads
    ``"none"``, a kernel radius (``kernel_size / 2``) of 0 and nothing to do above and
    below all as no adaptation (``EnhancedTerrainAdaptation.orNone``)."""
    if not isinstance(adaptation, dict):
        return False
    size = adaptation.get("kernel_size")
    if isinstance(size, int) and size // 2 == 0:
        return False
    return not (adaptation.get("top") == "none" and adaptation.get("bottom") == "none")


def _jigsaw_pools(structure: Structure | None) -> set[str]:
    if structure is None or structure.palette is None:
        return set()
    jigsaws = {i for i, name in enumerate(structure.palette_names()) if name == "minecraft:jigsaw"}
    pools = set()
    for _, _, _, block_nbt in structure.blocks_in_states(jigsaws):
        pool = block_nbt.get("pool") if block_nbt is not None else None
        if pool is not None:
            pools.add(namespaced(str(pool)))
    return pools


def _structures_by_pool(svc: Services) -> dict[str, list[tuple[str, dict]]]:
    """Each pool id, with every structure ``(file, data)`` whose generation reaches it."""
    project, store = svc.project, svc.structures
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
                    found |= _jigsaw_pools(store.try_load(path))
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
    return reached


def _names(structures: list[tuple[str, dict]]) -> str:
    files = sorted(f for f, _ in structures)
    return ", ".join(files[:3]) + (f" (+{len(files) - 3} more)" if len(files) > 3 else "")


def _past_template(svc: Services, element: dict, area: dict) -> list[str]:
    """A message per ``columns`` range that runs past a template the element names."""
    project, store = svc.project, svc.structures
    columns = area.get("columns")
    if not isinstance(columns, list):
        return []
    sizes: list[tuple[str, list]] = []
    locations = [element.get("location")] + list((element.get("locations") or {}).values())
    for location in dict.fromkeys(loc for loc in locations if isinstance(loc, str)):
        path = loc_to_path(namespaced(location), project.namespace, store.dir, ".nbt")
        structure = store.try_load(path) if path is not None and path.exists() else None
        size = structure.root.get("size") if structure is not None else None
        if isinstance(size, list) and len(size) == 3 and all(isinstance(n, int) for n in size):
            sizes.append((store.rel(path).replace("\\", "/"), size))
    out = []
    for i, rect in enumerate(columns):
        for axis, dim in (("x", 0), ("z", 2)):
            pair = rect.get(axis) if isinstance(rect, dict) else None
            if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(n, int) for n in pair)):
                continue
            past = [(rel, size[dim]) for rel, size in sizes if pair[0] < 0 or pair[1] > size[dim] - 1]
            if past:
                rel, width = past[0]
                more = f" (+{len(past) - 1} more)" if len(past) > 1 else ""
                out.append(f"columns > {i} {axis} {pair} runs past {rel}{more}, whose {axis} goes 0 to "
                           f"{width - 1}: MSL ignores the columns outside the piece")
    return out


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    areas = []
    pool_dir = project.template_pool_dir
    for path, data in project.pools():
        pool_id = f"{project.namespace}:{path.relative_to(pool_dir).with_suffix('').as_posix()}"
        for where, element in _iter_pool_elements(data):
            if element_type(element) == MSL_VERSIONED_ELEMENT and isinstance(element.get("adaptation_area"), dict):
                areas.append((f"template_pool/{path.relative_to(pool_dir).as_posix()}", where, pool_id, element))
    if not areas:
        print("  no adaptation areas")
        return True, "no adaptation areas"

    reached = _structures_by_pool(svc)
    warnings: list[str] = []
    for file, where, pool_id, element in areas:
        area = element["adaptation_area"]
        structures = reached.get(pool_id, [])
        msl = [s for s in structures if s[1].get("type") in _MSL_JIGSAW_STRUCTURES]
        other = [s for s in structures if s not in msl]
        problems = []
        own = element.get("enhanced_terrain_adaptation")
        if own is not None and not _shapes_ground(own):
            problems.append("the element's own enhanced_terrain_adaptation changes nothing, so the area "
                            "shapes no ground")
        elif own is None:
            bare = [s for s in msl if not _shapes_ground(s[1].get("enhanced_terrain_adaptation"))]
            if bare:
                problems.append(f"no enhanced_terrain_adaptation that changes the ground, on the element or in "
                                f"{_names(bare)}, so the area shapes none there")
        if other:
            follows = " (outside_follows_ground still works)" if area.get("outside_follows_ground") is True else ""
            problems.append(f"the area shapes no ground in {_names(other)}: only MSL's two jigsaw structures "
                            f"are shaped{follows}")
        if area.get("outside_follows_ground") is True:
            bearded = [s for s in structures if s[1].get("terrain_adaptation", "none") != "none"]
            if bearded:
                problems.append(f"the vanilla terrain_adaptation of {_names(bearded)} beards the whole box "
                                f"first, so the columns outside the area have no ground left to follow there")
        problems += _past_template(svc, element, area)
        for problem in problems:
            warnings.append(f"  [WARN] {file} @ {where} > adaptation_area\n    {problem}")

    for msg in warnings:
        print(msg)
    if not warnings:
        print(f"  {len(areas)} adaptation area(s), all shape what they say")
        return True, f"{len(areas)} adaptation area(s), all OK"
    return True, f"{len(areas)} adaptation area(s), {len(warnings)} warning(s)"
