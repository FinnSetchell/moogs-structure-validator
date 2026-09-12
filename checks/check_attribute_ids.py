"""Attribute ids have the right shape and naming for the file's target range.

Entity attributes and an item stack's attribute modifiers are two different
things that moved on two different releases: entity ``Attributes`` became
``attributes`` at 1.21, while an item's modifiers travelled with the rest of
item NBT at 1.20.5 (``tag.AttributeModifiers`` ->
``components.minecraft:attribute_modifiers``). Naming is a third boundary
common to both: at 1.21.2 attribute ids lost their ``generic.`` / ``player.`` /
``zombie.`` prefixes.

Only *attribute* ids are validated against the ``attribute`` registry. A
modifier's own ``id`` (since 1.21 a resource location such as
``minecraft:random_spawn_bonus``) lives in no registry and is skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, TYPE_CHECKING

from core.context import services
from core.items import block_entity_items, entity_items
from core.mcversions import DV_1_20_5, DV_1_21, DV_1_21_2, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

_PREFIXES = ("generic.", "player.", "zombie.")


@dataclass(frozen=True)
class _ShapeBoundary:
    dv: int
    version: str
    legacy: str
    new: str
    label: str


_SHAPE_BOUNDARIES: dict[str, _ShapeBoundary] = {
    "entity": _ShapeBoundary(DV_1_21, "1.21", "`Attributes` list", "`attributes` list", "attribute list"),
    "item": _ShapeBoundary(DV_1_20_5, "1.20.5", "`tag.AttributeModifiers`",
                           "`components.minecraft:attribute_modifiers`", "item attribute modifiers"),
}


def _strip_ns(id_: str) -> str:
    return id_[len("minecraft:"):] if id_.startswith("minecraft:") else id_


def _has_legacy_prefix(bare_id: str) -> bool:
    return any(bare_id.startswith(p) for p in _PREFIXES)


def _iter_entity_attribute_ids(entity: dict, entity_path: str) -> Iterator[tuple[str, str, str]]:
    """``(id, path, shape)`` for ``Attributes[i].Name`` (legacy) and ``attributes[i].id`` (new).
    ``attributes[i].modifiers[j].id`` is deliberately not yielded (see module doc)."""
    legacy = entity.get("Attributes")
    if isinstance(legacy, list):
        for i, entry in enumerate(legacy):
            if isinstance(entry, dict) and entry.get("Name") is not None:
                yield str(entry["Name"]), f"{entity_path}.Attributes[{i}].Name", "legacy"
    new_ = entity.get("attributes")
    if isinstance(new_, list):
        for i, entry in enumerate(new_):
            if isinstance(entry, dict) and entry.get("id") is not None:
                yield str(entry["id"]), f"{entity_path}.attributes[{i}].id", "new"


def _iter_item_attribute_ids(item: dict, slot_path: str) -> Iterator[tuple[str, str, str]]:
    tag = item.get("tag")
    if isinstance(tag, dict):
        mods = tag.get("AttributeModifiers")
        if isinstance(mods, list):
            for i, m in enumerate(mods):
                if isinstance(m, dict) and m.get("AttributeName") is not None:
                    yield str(m["AttributeName"]), f"{slot_path}.tag.AttributeModifiers[{i}].AttributeName", "legacy"

    comps = item.get("components")
    if isinstance(comps, dict):
        am = comps.get("minecraft:attribute_modifiers")
        modifiers = am.get("modifiers") if isinstance(am, dict) else (am if isinstance(am, list) else None)
        if isinstance(modifiers, list):
            for i, m in enumerate(modifiers):
                if not isinstance(m, dict):
                    continue
                for key in ("type", "attribute"):
                    val = m.get(key)
                    if val is not None:
                        yield str(val), f"{slot_path}.components.minecraft:attribute_modifiers[{i}].{key}", "new"
                        break


def _flag(attr_id: str, path: str, rel: str, shape: str, origin: str,
          min_v: str, max_v: str, min_dv: int, max_dv: int,
          valid_min: set[str] | None, valid_max: set[str] | None) -> list[str]:
    bare = _strip_ns(attr_id)
    prefixed = _has_legacy_prefix(bare)
    fq = attr_id if ":" in attr_id else f"minecraft:{bare}"
    unfq = f"minecraft:{bare[bare.index('.') + 1:]}" if prefixed else fq
    fqfq = f"minecraft:generic.{bare}" if not prefixed else fq

    b = _SHAPE_BOUNDARIES[origin]
    field_side = side_of(min_dv, max_dv, b.dv)
    errors: list[str] = []
    if shape == "legacy" and field_side == BoundarySide.NEW:
        errors.append(
            f"[ERROR] {rel}: {path}: legacy {b.legacy} on a min>={b.version} target"
            f" ({min_v}); use {b.new} at {b.version}+"
        )
        return errors
    if shape == "new" and field_side == BoundarySide.OLD:
        errors.append(
            f"[ERROR] {rel}: {path}: new {b.new} on a max<{b.version} target"
            f" ({max_v}); use {b.legacy} before {b.version}"
        )
        return errors
    if field_side == BoundarySide.SPANS:
        errors.append(
            f"[ERROR] {rel}: {path}: {b.label} across range {min_v}..{max_v}"
            f" spans {b.version} ({b.legacy} -> {b.new});"
            f" no single shape works on both sides"
        )
        return errors

    prefix_side = side_of(min_dv, max_dv, DV_1_21_2)

    if valid_min is not None and valid_max is not None:
        if prefix_side == BoundarySide.NEW and fq not in valid_min:
            if prefixed:
                errors.append(
                    f"[ERROR] {rel}: {path}: attribute id '{attr_id}' has legacy prefix on a"
                    f" min>=1.21.2 target ({min_v}); use '{unfq}'"
                )
            else:
                errors.append(f"[ERROR] {rel}: {path}: unknown attribute id '{attr_id}' (min target {min_v})")
        elif prefix_side == BoundarySide.OLD and fq not in valid_max:
            if not prefixed:
                errors.append(
                    f"[ERROR] {rel}: {path}: attribute id '{attr_id}' is missing legacy prefix on"
                    f" a max<1.21.2 target ({max_v}); use '{fqfq}'"
                )
            else:
                errors.append(f"[ERROR] {rel}: {path}: unknown attribute id '{attr_id}' (max target {max_v})")
        elif prefix_side == BoundarySide.SPANS:
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

    # Registries unavailable: prefix-only reasoning.
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
    svc = services(ctx)
    store, reg = svc.structures, svc.mcmeta
    if not store.dir.exists():
        return True, "no structures directory"
    if not svc.versions:
        return True, "skipped (no version map)"

    attr_sets: dict[str, set[str] | None] = {}

    def attrs_for(version: str) -> set[str] | None:
        if version not in attr_sets:
            try:
                attr_sets[version] = reg.registry(version, "attribute") or None
            except Exception:
                attr_sets[version] = None
        return attr_sets[version]

    errors: list[str] = []
    files_checked = 0
    attrs_checked = 0

    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        fr = svc.file_range(nbt_path)
        if not fr.resolved:
            continue
        valid_min = attrs_for(fr.min_version)
        valid_max = attrs_for(fr.max_version)
        args = (fr.min_version, fr.max_version, fr.min_dv, fr.max_dv, valid_min, valid_max)

        for entity, entity_path in structure.walk_entities():
            for attr_id, path, shape in _iter_entity_attribute_ids(entity, entity_path):
                attrs_checked += 1
                errors.extend(_flag(attr_id, path, rel, shape, "entity", *args))
            for slot_path, item in entity_items(entity, entity_path):
                for attr_id, path, shape in _iter_item_attribute_ids(item, slot_path):
                    attrs_checked += 1
                    errors.extend(_flag(attr_id, path, rel, shape, "item", *args))

        for slot_path, item in block_entity_items(structure.block_entities):
            for attr_id, path, shape in _iter_item_attribute_ids(item, slot_path):
                attrs_checked += 1
                errors.extend(_flag(attr_id, path, rel, shape, "item", *args))

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s), {attrs_checked} attribute id(s) checked -- all valid")
        return True, f"{files_checked} files, {attrs_checked} attribute ids checked"
    return False, f"{len(errors)} attribute id error(s)"
