"""Cross-reference checks for MSL 3.1.0+ placements and processors.

The schema pass in check_worldgen_schemas covers shape. This check covers
relationships that JSON schemas can't express:

- conditional_concentric_rings placements must reference a preset that exists
  in this pack's replace_vanilla.json (otherwise ReplaceVanillaManager.isEnabled
  always returns false and the ring count is stuck on disabled_count forever).

- vanilla_loot_swap_processor entries must (a) reference a preset that exists,
  (b) map from loot tables that are actually used by some container in the
  pack's NBTs (dead FROM keys silently do nothing), (c) map to loot tables
  that exist in vanilla, and (d) live inside a processor_list that is
  referenced by at least one template_pool element -- an unwired swap list
  never fires.

- advanced_random_spread with an explicit structure_id must point at a
  structure that appears in the owning set's `structures` list.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from checks.check_containers import _CONTAINER_BLOCKS
from registries.fetcher import fetch_registry_set
from utils.nbt_cache import load_nbt
from utils.paths import data_dir
from utils import replace_vanilla as rv

if TYPE_CHECKING:
    from validator import ValidatorContext


_CACHE_DIR = Path(__file__).parent.parent / "cache"


def _walk_structure_sets(ns_root: Path):
    d = ns_root / "worldgen" / "structure_set"
    if not d.exists():
        return
    for path in sorted(d.rglob("*.json")):
        try:
            with path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        yield path.relative_to(d), data


def _walk_processor_lists(ns_root: Path):
    d = ns_root / "worldgen" / "processor_list"
    if not d.exists():
        return
    for path in sorted(d.rglob("*.json")):
        try:
            with path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        yield path.relative_to(d), data


def _collect_pool_processor_refs(ns_root: Path) -> set[str]:
    """Every string referenced under a template_pool element's `processors` field."""
    refs: set[str] = set()
    d = ns_root / "worldgen" / "template_pool"
    if not d.exists():
        return refs
    for path in sorted(d.rglob("*.json")):
        try:
            with path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        def visit(node):
            if isinstance(node, dict):
                # Element wrapper can nest via list_pool_element.
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
        visit(data)
    return refs


def _collect_container_loot_refs(ctx) -> set[str]:
    """LootTable ids referenced by any container block in any structure NBT."""
    refs: set[str] = set()
    ns_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structure_dir = data_dir(ns_root, "structure")
    if not structure_dir.exists():
        return refs
    for nbt_path in sorted(structure_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue
        palette = nbt.get("palette")
        blocks = nbt.get("blocks")
        if palette is None or blocks is None:
            continue
        container_indices = {
            i for i, state in enumerate(palette)
            if str(state.get("Name", "")) in _CONTAINER_BLOCKS
        }
        for block in blocks:
            if int(block.get("state", -1)) not in container_indices:
                continue
            block_nbt = block.get("nbt")
            if block_nbt is None:
                continue
            loot = block_nbt.get("LootTable")
            if isinstance(loot, nbtlib.String) or isinstance(loot, str):
                refs.add(str(loot))
    return refs


def _resource_id_to_relpath(id_: str) -> tuple[str, str] | None:
    ns, _, path = id_.partition(":")
    if not ns or not path:
        return None
    return ns, path


def _structure_exists(project_root: Path, id_: str) -> bool:
    parts = _resource_id_to_relpath(id_)
    if parts is None:
        return False
    ns, path = parts
    return (project_root / "src" / "main" / "resources" / "data" / ns
            / "worldgen" / "structure" / f"{path}.json").exists()


def _load_vanilla_loot_tables(ctx) -> set[str] | None:
    """Union of vanilla loot table ids across every targeted MC version.

    Returns None if the registry can't be fetched, so callers can skip the
    check rather than raise false positives.
    """
    versions = getattr(ctx, "mc_versions", [])
    if not versions:
        return None
    tables: set[str] = set()
    for v in versions:
        try:
            tables |= fetch_registry_set(v, _CACHE_DIR, getattr(ctx, "refresh", False), "loot_table")
        except Exception:
            return None
    return tables


def _preset_lookup(manifest: rv.ReplaceVanillaFile | None) -> set[str]:
    """Set of vanilla_key values with at least one replacement in our own manifest."""
    if manifest is None:
        return set()
    return {r.vanilla_key for r in manifest.replacements}


def _check_conditional_rings(
    ns_root: Path,
    project_root: Path,
    manifest: rv.ReplaceVanillaFile | None,
    ns: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    preset_keys = _preset_lookup(manifest)
    for rel, data in _walk_structure_sets(ns_root):
        placement = data.get("placement")
        if not isinstance(placement, dict):
            continue
        if placement.get("type") != "moogs_structures:conditional_concentric_rings":
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
        if isinstance(sid, str) and not _structure_exists(project_root, sid):
            errors.append(
                f"  [ERROR] {where}: structure_id = {sid!r} does not resolve to a real structure"
            )


def _check_advanced_random_spread(
    ns_root: Path,
    project_root: Path,
    errors: list[str],
) -> None:
    for rel, data in _walk_structure_sets(ns_root):
        placement = data.get("placement")
        if not isinstance(placement, dict):
            continue
        if placement.get("type") != "moogs_structures:advanced_random_spread":
            continue
        where = f"structure_set/{rel}"
        sid = placement.get("structure_id")
        if not isinstance(sid, str):
            continue

        if not _structure_exists(project_root, sid):
            errors.append(
                f"  [ERROR] {where}: structure_id = {sid!r} does not resolve to a real structure"
            )

        # Consistency with owning set: structure_id should be one of the set's structures.
        own_structures = {
            s.get("structure") for s in (data.get("structures") or [])
            if isinstance(s, dict) and isinstance(s.get("structure"), str)
        }
        if own_structures and sid not in own_structures:
            errors.append(
                f"  [ERROR] {where}: structure_id = {sid!r} is not in this set's structures list "
                f"({sorted(own_structures)!r})"
            )


def _check_vanilla_loot_swap(
    ns_root: Path,
    manifest: rv.ReplaceVanillaFile | None,
    ns: str,
    ctx,
    errors: list[str],
    warnings: list[str],
) -> None:
    preset_keys = _preset_lookup(manifest)
    pool_processor_refs = _collect_pool_processor_refs(ns_root)

    lazy: dict[str, set[str] | None] = {}
    def container_refs() -> set[str]:
        if "containers" not in lazy:
            lazy["containers"] = _collect_container_loot_refs(ctx)
        return lazy["containers"]  # type: ignore[return-value]

    def vanilla_tables() -> set[str] | None:
        if "vanilla" not in lazy:
            lazy["vanilla"] = _load_vanilla_loot_tables(ctx)
        return lazy["vanilla"]

    for rel, data in _walk_processor_lists(ns_root):
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
            if not isinstance(p, dict):
                continue
            if p.get("processor_type") != "moogs_structures:vanilla_loot_swap_processor":
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
    ns_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    manifest = rv.load(ns_root)

    errors: list[str] = []
    warnings: list[str] = []

    _check_conditional_rings(ns_root, ctx.project_root, manifest, ctx.namespace, errors, warnings)
    _check_advanced_random_spread(ns_root, ctx.project_root, errors)
    _check_vanilla_loot_swap(ns_root, manifest, ctx.namespace, ctx, errors, warnings)

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
