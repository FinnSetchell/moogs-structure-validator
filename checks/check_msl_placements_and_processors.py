"""Cross-references for MSL 3.1.0+ placements and processors.

The schema pass in ``check_worldgen_schemas`` covers shape. This covers the
relationships a JSON schema cannot express:

* ``conditional_concentric_rings`` must name a preset that exists in this
  pack's ``replace_vanilla.json`` (otherwise ``ReplaceVanillaManager.isEnabled``
  is always false and the ring count is stuck on ``disabled_count``);
* ``vanilla_loot_swap_processor`` must (a) name a preset that exists, (b) map
  from loot tables some container in the pack actually uses (a dead FROM key
  does nothing), (c) map to loot tables that exist in vanilla, and (d) live in
  a processor list some template pool element references -- an unwired swap
  list never fires;
* ``advanced_random_spread`` with an explicit ``structure_id`` must point at a
  structure in the owning set's ``structures`` list.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from checks.check_containers import CONTAINER_BLOCKS
from core import replace_vanilla as rv
from core.context import Services, services
from core.project import Project

if TYPE_CHECKING:
    from core.context import ValidatorContext


def _walk(project: Project, directory):
    for path in project.json_files(directory):
        data = project.try_json(path)
        if isinstance(data, dict):
            yield path.relative_to(directory), data


def _collect_pool_processor_refs(project: Project) -> set[str]:
    """Every string a template pool element names under ``processors``."""
    refs: set[str] = set()

    def visit(node):
        if isinstance(node, dict):
            element = node.get("element", node)
            if isinstance(element, dict):
                procs = element.get("processors")
                if isinstance(procs, str):
                    refs.add(procs)
                nested = element.get("elements")
                if isinstance(nested, list):
                    for n in nested:
                        visit(n)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    for _, data in project.pools():
        visit(data)
    return refs


def _collect_container_loot_refs(svc: Services) -> set[str]:
    """``LootTable`` ids on any container block in any checked structure."""
    refs: set[str] = set()
    store = svc.structures
    if not store.dir.exists():
        return refs
    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None or structure.palette is None:
            continue
        container_indices = {
            i for i, name in enumerate(structure.palette_names()) if name in CONTAINER_BLOCKS
        }
        for _, _, _, block_nbt in structure.blocks_in_states(container_indices):
            if block_nbt is None:
                continue
            loot = block_nbt.get("LootTable")
            if isinstance(loot, str):
                refs.add(loot)
    return refs


def _structure_exists(project: Project, id_: str) -> bool:
    ns, _, path = id_.partition(":")
    if not ns or not path:
        return False
    return (project.data_root / ns / "worldgen" / "structure" / f"{path}.json").exists()


def _load_vanilla_loot_tables(ctx) -> set[str] | None:
    """Union of vanilla loot table ids across every targeted MC version, or
    None if the registry cannot be fetched (callers then skip that rule)."""
    svc = services(ctx)
    if not svc.mc_versions:
        return None
    try:
        return set(svc.mcmeta.union("loot_table"))
    except Exception:
        return None


def _preset_keys(manifest: rv.ReplaceVanillaFile | None) -> set[str]:
    return manifest.vanilla_keys() if manifest is not None else set()


def _check_conditional_rings(project: Project, manifest, errors: list[str], warnings: list[str]) -> None:
    preset_keys = _preset_keys(manifest)
    ns = project.namespace
    for rel, data in _walk(project, project.structure_set_dir):
        placement = data.get("placement")
        if not isinstance(placement, dict) or placement.get("type") != "moogs_structures:conditional_concentric_rings":
            continue
        modid = placement.get("modid")
        vk = placement.get("vanilla_key")
        where = f"structure_set/{rel}"

        if isinstance(modid, str) and isinstance(vk, str):
            if modid == ns:
                if vk not in preset_keys:
                    errors.append(
                        f"  [ERROR] {where}: (modid={modid!r}, vanilla_key={vk!r}) "
                        f"has no matching preset in replace_vanilla.json "
                        f"(placement stays on disabled_count forever)"
                    )
            else:
                warnings.append(
                    f"  [WARN] {where}: (modid={modid!r}, vanilla_key={vk!r}) "
                    f"targets another mod's preset; can't verify from this pack"
                )

        enabled = placement.get("enabled_count")
        disabled = placement.get("disabled_count")
        if isinstance(enabled, int) and isinstance(disabled, int) and enabled < disabled:
            warnings.append(
                f"  [WARN] {where}: enabled_count ({enabled}) < disabled_count ({disabled}) "
                f"— enabled is the 'replacing vanilla, full density' case; likely inverted"
            )

        sid = placement.get("structure_id")
        if isinstance(sid, str) and not _structure_exists(project, sid):
            errors.append(f"  [ERROR] {where}: structure_id = {sid!r} does not resolve to a real structure")


def _check_advanced_random_spread(project: Project, errors: list[str]) -> None:
    for rel, data in _walk(project, project.structure_set_dir):
        placement = data.get("placement")
        if not isinstance(placement, dict) or placement.get("type") != "moogs_structures:advanced_random_spread":
            continue
        where = f"structure_set/{rel}"
        sid = placement.get("structure_id")
        if not isinstance(sid, str):
            continue

        if not _structure_exists(project, sid):
            errors.append(f"  [ERROR] {where}: structure_id = {sid!r} does not resolve to a real structure")

        own_structures = {
            s.get("structure") for s in (data.get("structures") or [])
            if isinstance(s, dict) and isinstance(s.get("structure"), str)
        }
        if own_structures and sid not in own_structures:
            errors.append(
                f"  [ERROR] {where}: structure_id = {sid!r} is not in this set's structures list "
                f"({sorted(own_structures)!r})"
            )


def _check_vanilla_loot_swap(ctx, svc: Services, manifest, errors: list[str], warnings: list[str]) -> None:
    project = svc.project
    ns = project.namespace
    preset_keys = _preset_keys(manifest)
    pool_processor_refs = _collect_pool_processor_refs(project)

    lazy: dict[str, object] = {}

    def container_refs() -> set[str]:
        if "containers" not in lazy:
            lazy["containers"] = _collect_container_loot_refs(svc)
        return lazy["containers"]  # type: ignore[return-value]

    def vanilla_tables() -> set[str] | None:
        if "vanilla" not in lazy:
            lazy["vanilla"] = _load_vanilla_loot_tables(ctx)
        return lazy["vanilla"]  # type: ignore[return-value]

    for rel, data in _walk(project, project.processor_list_dir):
        processors = data.get("processors")
        if not isinstance(processors, list):
            continue
        pl_id = f"{ns}:{str(rel).replace(chr(92), '/').removesuffix('.json')}"
        contains_swap = any(
            isinstance(p, dict) and p.get("processor_type") == "moogs_structures:vanilla_loot_swap_processor"
            for p in processors
        )
        if contains_swap and pl_id not in pool_processor_refs:
            errors.append(
                f"  [ERROR] processor_list/{rel}: contains vanilla_loot_swap_processor but "
                f"the list ({pl_id}) is not referenced by any template_pool element (never fires)"
            )

        for i, p in enumerate(processors):
            if not isinstance(p, dict) or p.get("processor_type") != "moogs_structures:vanilla_loot_swap_processor":
                continue
            where = f"processor_list/{rel} @ processors[{i}]"

            modid = p.get("modid")
            vk = p.get("vanilla_key")
            if isinstance(modid, str) and isinstance(vk, str):
                if modid == ns:
                    if vk not in preset_keys:
                        errors.append(
                            f"  [ERROR] {where}: (modid={modid!r}, vanilla_key={vk!r}) "
                            f"has no matching preset in replace_vanilla.json (swap never fires)"
                        )
                else:
                    warnings.append(
                        f"  [WARN] {where}: (modid={modid!r}, vanilla_key={vk!r}) "
                        f"targets another mod's preset; can't verify from this pack"
                    )

            mapping = p.get("loot_table_mapping")
            if not isinstance(mapping, dict):
                continue

            crefs = container_refs()
            vtabs = vanilla_tables()
            for from_id, to_id in mapping.items():
                if from_id not in crefs:
                    warnings.append(
                        f"  [WARN] {where}: FROM key {from_id!r} is not used as LootTable "
                        f"on any container in this pack (dead mapping)"
                    )
                if vtabs is not None and to_id not in vtabs:
                    errors.append(
                        f"  [ERROR] {where}: TO value {to_id!r} is not a vanilla loot table "
                        f"on any targeted MC version"
                    )


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    manifest = rv.load(project)

    errors: list[str] = []
    warnings: list[str] = []

    _check_conditional_rings(project, manifest, errors, warnings)
    _check_advanced_random_spread(project, errors)
    _check_vanilla_loot_swap(ctx, svc, manifest, errors, warnings)

    for msg in warnings:
        print(msg)
    for msg in errors:
        print(msg)

    if not errors and not warnings:
        print("  all MSL placement/processor cross-refs OK")

    if errors:
        return False, f"{len(errors)} error(s), {len(warnings)} warning(s)"
    if warnings:
        return True, f"0 errors, {len(warnings)} warning(s)"
    return True, "all MSL placement/processor cross-refs OK"
