from __future__ import annotations

from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import nbtlib

from registries.fetcher import fetch_registry_set
from utils.boundaries import DV_1_21, DV_1_21_2, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


_PREFIXES = ("generic.", "player.", "zombie.")


def _strip_ns(id_: str) -> str:
    if id_.startswith("minecraft:"):
        return id_[len("minecraft:"):]
    return id_


def _has_legacy_prefix(bare_id: str) -> bool:
    return any(bare_id.startswith(p) for p in _PREFIXES)


def _iter_entity_attribute_ids(entity_nbt: nbtlib.Compound, entity_path: str) -> Iterator[tuple[str, str, str]]:
    """Yield (id, path, shape) where shape is 'legacy' (Attributes) or 'new' (attributes).

    Only *attribute* ids are yielded -- i.e. `Attributes[i].Name` and
    `attributes[i].id`. The nested `attributes[i].modifiers[j].id` is NOT an
    attribute id: since 1.21 it is the modifier's own resource location (an
    identity used for add/remove and stacking), e.g. vanilla's
    `minecraft:random_spawn_bonus` on a naturally-spawned mob's follow_range.
    Those ids live in no registry at all -- there is no attribute-modifier
    registry in any version -- so they cannot be validated here, and looking
    them up in the `attribute` registry flagged every naturally-spawned mob
    captured into a structure. Skipped deliberately; the legacy `Attributes`
    branch below has always (correctly) skipped `Modifiers` for the same reason.
    """
    legacy = entity_nbt.get("Attributes")
    if isinstance(legacy, list):
        for i, entry in enumerate(legacy):
            if not isinstance(entry, nbtlib.Compound):
                continue
            name = entry.get("Name")
            if name is not None:
                yield str(name), f"{entity_path}.Attributes[{i}].Name", "legacy"

    new_ = entity_nbt.get("attributes")
    if isinstance(new_, list):
        for i, entry in enumerate(new_):
            if not isinstance(entry, nbtlib.Compound):
                continue
            id_tag = entry.get("id")
            if id_tag is not None:
                yield str(id_tag), f"{entity_path}.attributes[{i}].id", "new"
            # entry["modifiers"][j]["id"] is intentionally not yielded -- see docstring.


def _iter_item_attribute_ids(item: nbtlib.Compound, slot_path: str) -> Iterator[tuple[str, str, str]]:
    tag = item.get("tag")
    if isinstance(tag, nbtlib.Compound):
        mods = tag.get("AttributeModifiers")
        if isinstance(mods, list):
            for i, m in enumerate(mods):
                if not isinstance(m, nbtlib.Compound):
                    continue
                name = m.get("AttributeName")
                if name is not None:
                    yield str(name), f"{slot_path}.tag.AttributeModifiers[{i}].AttributeName", "legacy"

    comps = item.get("components")
    if isinstance(comps, nbtlib.Compound):
        am = comps.get("minecraft:attribute_modifiers")
        modifiers = None
        if isinstance(am, nbtlib.Compound):
            modifiers = am.get("modifiers")
        elif isinstance(am, list):
            modifiers = am
        if isinstance(modifiers, list):
            for i, m in enumerate(modifiers):
                if not isinstance(m, nbtlib.Compound):
                    continue
                for key in ("type", "attribute"):
                    val = m.get(key)
                    if val is not None:
                        yield str(val), f"{slot_path}.components.minecraft:attribute_modifiers[{i}].{key}", "new"
                        break


def _iter_entity_items(entity_nbt: nbtlib.Compound, entity_path: str) -> Iterator[tuple[str, nbtlib.Compound]]:
    for list_field in ("HandItems", "ArmorItems"):
        items = entity_nbt.get(list_field)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{entity_path}.{list_field}[{i}]", item
    for field in ("body_armor_item", "SaddleItem", "Item"):
        item = entity_nbt.get(field)
        if isinstance(item, nbtlib.Compound):
            yield f"{entity_path}.{field}", item
    equip = entity_nbt.get("equipment")
    if isinstance(equip, nbtlib.Compound):
        for slot, item in equip.items():
            if isinstance(item, nbtlib.Compound):
                yield f"{entity_path}.equipment.{slot}", item


def _iter_block_items(nbt: nbtlib.Compound) -> Iterator[tuple[str, nbtlib.Compound]]:
    for i, block_entry in enumerate(nbt.get("blocks") or []):
        block_nbt = block_entry.get("nbt")
        if not isinstance(block_nbt, nbtlib.Compound):
            continue
        base = f"blocks[{i}].nbt"
        items = block_nbt.get("Items")
        if isinstance(items, list):
            for j, item in enumerate(items):
                if isinstance(item, nbtlib.Compound):
                    yield f"{base}.Items[{j}]", item
        for field in ("Book", "item"):
            it = block_nbt.get(field)
            if isinstance(it, nbtlib.Compound):
                yield f"{base}.{field}", it


def _flag(attr_id: str, path: str, rel: str, shape: str,
          min_v: str, max_v: str, min_dv: int, max_dv: int,
          valid_min: set[str] | None, valid_max: set[str] | None) -> list[str]:
    """Flag an attribute id if its prefix form is wrong for the target range.

    Uses per-version `attribute` registry when available: an id must appear in
    both the min-version and max-version registries. If either lookup misses,
    figure out whether it's a prefix mismatch and emit a targeted message.
    """
    bare = _strip_ns(attr_id)
    prefixed = _has_legacy_prefix(bare)
    fq = attr_id if ":" in attr_id else f"minecraft:{bare}"
    unfq = f"minecraft:{bare[bare.index('.') + 1:]}" if prefixed else fq
    fqfq = f"minecraft:generic.{bare}" if not prefixed else fq

    # Boundary at 1.21 (Attributes -> attributes): only shape-check here.
    field_side = side_of(min_dv, max_dv, DV_1_21)
    errors: list[str] = []
    if shape == "legacy" and field_side == BoundarySide.NEW:
        errors.append(
            f"[ERROR] {rel}: {path}: legacy `Attributes` list on a min>=1.21 target"
            f" ({min_v}); use `attributes` with namespaced ids at 1.21+"
        )
        return errors
    if shape == "new" and field_side == BoundarySide.OLD:
        errors.append(
            f"[ERROR] {rel}: {path}: new `attributes` list on a max<1.21 target"
            f" ({max_v}); use `Attributes` with `Name`/`Base` before 1.21"
        )
        return errors
    if field_side == BoundarySide.SPANS:
        errors.append(
            f"[ERROR] {rel}: {path}: attribute list across range {min_v}..{max_v}"
            f" spans 1.21 (Attributes -> attributes rename); no single shape works on both sides"
        )
        return errors

    # Prefix check at 1.21.2.
    prefix_side = side_of(min_dv, max_dv, DV_1_21_2)

    # If both registries are available, prefer the registry-based check.
    if valid_min is not None and valid_max is not None:
        if prefix_side == BoundarySide.NEW and fq not in valid_min:
            # min registry (1.21.2+) uses unprefixed ids
            if prefixed:
                errors.append(
                    f"[ERROR] {rel}: {path}: attribute id '{attr_id}' has legacy prefix on a"
                    f" min>=1.21.2 target ({min_v}); use '{unfq}'"
                )
            else:
                errors.append(
                    f"[ERROR] {rel}: {path}: unknown attribute id '{attr_id}' (min target {min_v})"
                )
        elif prefix_side == BoundarySide.OLD and fq not in valid_max:
            if not prefixed:
                errors.append(
                    f"[ERROR] {rel}: {path}: attribute id '{attr_id}' is missing legacy prefix on"
                    f" a max<1.21.2 target ({max_v}); use '{fqfq}'"
                )
            else:
                errors.append(
                    f"[ERROR] {rel}: {path}: unknown attribute id '{attr_id}' (max target {max_v})"
                )
        elif prefix_side == BoundarySide.SPANS and (prefixed or not prefixed):
            # Attribute id must be one shape or the other; either way it breaks somewhere.
            if prefixed and fq not in valid_min:
                errors.append(
                    f"[ERROR] {rel}: {path}: attribute id '{attr_id}' is prefixed but wired"
                    f" range {min_v}..{max_v} spans 1.21.2 (prefixes dropped); would fail on"
                    f" the newer side"
                )
            elif not prefixed and fq not in valid_max:
                errors.append(
                    f"[ERROR] {rel}: {path}: attribute id '{attr_id}' is unprefixed but wired"
                    f" range {min_v}..{max_v} spans 1.21.2 (prefixes required earlier); would"
                    f" fail on the older side"
                )
        return errors

    # Fallback prefix-only logic when registries are unavailable.
    if prefix_side == BoundarySide.NEW and prefixed:
        errors.append(
            f"[ERROR] {rel}: {path}: attribute id '{attr_id}' has legacy prefix on a"
            f" min>=1.21.2 target ({min_v}); prefixes were dropped at 1.21.2"
        )
    elif prefix_side == BoundarySide.SPANS and prefixed:
        errors.append(
            f"[ERROR] {rel}: {path}: attribute id '{attr_id}' is prefixed but wired range"
            f" {min_v}..{max_v} spans 1.21.2"
        )
    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")
    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"
    version_map = load_version_map(cache_dir, ctx.refresh)
    if not version_map:
        return True, "skipped (no version map)"

    global_min_version = min(ctx.mc_versions, key=_parse_version)
    global_max_version = max(ctx.mc_versions, key=_parse_version)
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    nbt_ranges = {}
    if template_pool_dir.exists():
        nbt_ranges = _build_nbt_version_ranges(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version,
            ctx.mc_versions, global_max_version,
        )

    attr_cache: dict[str, set[str]] = {}

    def attrs_for(version: str) -> set[str] | None:
        if version not in attr_cache:
            try:
                attr_cache[version] = fetch_registry_set(version, cache_dir, ctx.refresh, "attribute")
            except Exception:
                attr_cache[version] = set()
        return attr_cache[version] or None

    errors: list[str] = []
    files_checked = 0
    attrs_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue
        files_checked += 1
        rel = str(nbt_path.relative_to(structures_dir))

        info = nbt_ranges.get(nbt_path)
        file_min = info.min_version if info else global_min_version
        file_max = info.max_version if info else global_max_version
        min_dv = version_map.get(file_min)
        max_dv = version_map.get(file_max)
        if min_dv is None or max_dv is None:
            continue

        valid_min = attrs_for(file_min)
        valid_max = attrs_for(file_max)

        for entity_nbt, entity_path in iter_entities(nbt):
            for attr_id, path, shape in _iter_entity_attribute_ids(entity_nbt, entity_path):
                attrs_checked += 1
                errors.extend(_flag(
                    attr_id, path, rel, shape,
                    file_min, file_max, min_dv, max_dv, valid_min, valid_max,
                ))
            for slot_path, item in _iter_entity_items(entity_nbt, entity_path):
                for attr_id, path, shape in _iter_item_attribute_ids(item, slot_path):
                    attrs_checked += 1
                    errors.extend(_flag(
                        attr_id, path, rel, shape,
                        file_min, file_max, min_dv, max_dv, valid_min, valid_max,
                    ))

        for slot_path, item in _iter_block_items(nbt):
            for attr_id, path, shape in _iter_item_attribute_ids(item, slot_path):
                attrs_checked += 1
                errors.extend(_flag(
                    attr_id, path, rel, shape,
                    file_min, file_max, min_dv, max_dv, valid_min, valid_max,
                ))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {attrs_checked} attribute id(s) checked -- all valid")

    if errors:
        return False, f"{len(errors)} attribute id error(s)"
    return True, f"{files_checked} files, {attrs_checked} attribute ids checked"
