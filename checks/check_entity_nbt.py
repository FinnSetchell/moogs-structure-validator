"""Entities in structure files: known ids, item shape, mob-effect shape, and
DataVersion drift.

* every entity id exists in the entity registry at the file's minimum version;
* hand/armor/body items use ``Count`` before 1.20.5 and ``count`` from it;
* mob effects use ``ActiveEffects`` before 1.20.2 and ``active_effects`` from
  it, with snake_case fields and known effect ids on the new side;
* a file saved on a newer game than its wired target is reported (drift is
  informational: the data fixer loads it, but content checks may still fire).
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from core.context import services
from core.ids import is_valid, non_minecraft
from core.mcversions import DV_1_20_2, DV_1_20_5, BoundarySide, side_of

if TYPE_CHECKING:
    from core.context import ValidatorContext

# Fields on the old (pre-1.20.2) ActiveEffects entry.
_LEGACY_EFFECT_FIELDS = frozenset({
    "Id", "Amplifier", "Duration", "Ambient", "ShowParticles", "ShowIcon", "HiddenEffect",
})


def _check_item_format(item: dict, slot_desc: str, entity_id: str, rel: str,
                       expect_old: bool, min_version_name: str) -> str | None:
    if "id" not in item:
        return None
    has_old = "Count" in item
    has_new = "count" in item
    if expect_old and has_new:
        return (
            f"[ERROR] {rel}: entity {entity_id} has new-format item in {slot_desc}"
            f" (min target version is {min_version_name}, pre-1.20.5 clients will misread it)"
        )
    if not expect_old and has_old:
        return (
            f"[ERROR] {rel}: entity {entity_id} has old-format item in {slot_desc}"
            f" (min target version is {min_version_name}, expected new item format)"
        )
    return None


def _check_mob_effects(entity: dict, entity_path: str, entity_id: str, rel: str,
                       min_version: str, max_version: str, min_dv: int, max_dv: int,
                       valid_effect_ids: set[str] | None, extra_ids: set[str]) -> list[str]:
    errors: list[str] = []
    side = side_of(min_dv, max_dv, DV_1_20_2)
    legacy = entity.get("ActiveEffects")
    new = entity.get("active_effects")

    if side == BoundarySide.NEW:
        if isinstance(legacy, list) and legacy:
            errors.append(
                f"[ERROR] {rel}: {entity_path} ({entity_id}) uses legacy `ActiveEffects` on"
                f" a min>=1.20.2 target ({min_version}); use `active_effects`"
            )
        if isinstance(new, list):
            for i, eff in enumerate(new):
                if not isinstance(eff, dict):
                    continue
                eff_path = f"{entity_path}.active_effects[{i}]"
                id_tag = eff.get("id")
                if id_tag is None:
                    errors.append(f"[ERROR] {rel}: {eff_path}: missing `id`")
                    continue
                id_str = str(id_tag)
                if not id_str.startswith("minecraft:") and ":" in id_str:
                    if not is_valid(id_str, valid_effect_ids or set(), extra_ids):
                        errors.append(
                            f"[ERROR] {rel}: {eff_path}: unknown mob_effect id '{id_str}'"
                            f" (min target {min_version})"
                        )
                elif valid_effect_ids is not None and not is_valid(id_str, valid_effect_ids, extra_ids):
                    errors.append(
                        f"[ERROR] {rel}: {eff_path}: unknown mob_effect id '{id_str}'"
                        f" (min target {min_version})"
                    )
                # Sorted: this list is printed, and set order varies per process.
                bad = sorted(f for f in _LEGACY_EFFECT_FIELDS if f in eff)
                if bad:
                    errors.append(
                        f"[ERROR] {rel}: {eff_path}: PascalCase field(s) {bad} on new-format"
                        f" effect (min target {min_version})"
                    )
    elif side == BoundarySide.OLD:
        if isinstance(new, list) and new:
            errors.append(
                f"[ERROR] {rel}: {entity_path} ({entity_id}) uses new `active_effects` on a"
                f" max<1.20.2 target ({max_version}); use `ActiveEffects`"
            )
    else:
        if isinstance(legacy, list) or isinstance(new, list):
            errors.append(
                f"[ERROR] {rel}: {entity_path} ({entity_id}) has mob effects but its wired"
                f" range {min_version}..{max_version} spans 1.20.2 (renamed here);"
                f" no single file can be correct on both sides"
            )
    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    store, reg = svc.structures, svc.mcmeta
    if not store.dir.exists():
        return True, "no structures directory"

    version_map = svc.versions
    max_allowed_dv: int | None = None
    max_version_name: str | None = None
    min_allowed_dv: int | None = None
    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is None:
                print(f"  [WARN] version '{v}' not found in versions.json -- skipping DataVersion check for it")
                continue
            if max_allowed_dv is None or dv > max_allowed_dv:
                max_allowed_dv, max_version_name = dv, v
            if min_allowed_dv is None or dv < min_allowed_dv:
                min_allowed_dv = dv

    if min_allowed_dv is None:
        item_check_mode: str | None = None
    else:
        item_check_mode = "old" if min_allowed_dv < DV_1_20_5 else "new"

    modded_entities = non_minecraft(ctx.valid_entities)
    entity_sets: dict[str, set[str]] = {}
    effect_sets: dict[str, set[str] | None] = {}

    def valid_entities_for(version: str) -> set[str]:
        s = entity_sets.get(version)
        if s is None:
            s = reg.registry(version, "entity_type") | modded_entities
            entity_sets[version] = s
        return s

    def valid_effects_for(version: str) -> set[str] | None:
        if version not in effect_sets:
            try:
                effect_sets[version] = reg.registry(version, "mob_effect")
            except Exception:
                effect_sets[version] = None
        return effect_sets[version]

    dv_outdated: dict[tuple[int, str], list[str]] = defaultdict(list)
    dv_wired_info: list[str] = []
    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in store.checked_files():
        try:
            structure = store.load(nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        files_checked += 1
        rel = store.rel(nbt_path)
        fr = svc.file_range(nbt_path)
        file_min, file_max = fr.min_version, fr.max_version
        file_min_dv, file_max_dv = fr.min_dv, fr.max_dv

        if file_min_dv is None:
            file_item_mode = item_check_mode
        else:
            file_item_mode = "old" if file_min_dv < DV_1_20_5 else "new"

        file_dv = structure.data_version
        if file_dv is not None:
            if fr.wired and file_min_dv is not None and file_dv > file_min_dv:
                dv_wired_info.append(
                    f"[INFO] {rel}: DataVersion {file_dv} > wired min target"
                    f" {file_min} (DV {file_min_dv}); MC's data fixer handles the load,"
                    f" but content checks may still flag schema issues"
                )
            elif max_allowed_dv is not None and file_dv > max_allowed_dv:
                dv_outdated[(file_dv, version_map.name_of(file_dv))].append(rel)

        for entity, entity_path in structure.walk_entities():
            id_tag = entity.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            entities_checked += 1

            if not is_valid(entity_id, valid_entities_for(file_min), ctx.extra_ids):
                errors.append(f"[ERROR] {rel}: {entity_path}: unknown entity ID '{entity_id}'")

            if file_item_mode is not None:
                expect_old = file_item_mode == "old"
                for list_field in ("HandItems", "ArmorItems"):
                    items_tag = entity.get(list_field)
                    if not isinstance(items_tag, list):
                        continue
                    for slot, item in enumerate(items_tag):
                        if not isinstance(item, dict):
                            continue
                        msg = _check_item_format(item, f"{entity_path}.{list_field}[{slot}]",
                                                 entity_id, rel, expect_old, file_min)
                        if msg:
                            errors.append(msg)
                body_item = entity.get("body_armor_item")
                if isinstance(body_item, dict):
                    msg = _check_item_format(body_item, f"{entity_path}.body_armor_item",
                                             entity_id, rel, expect_old, file_min)
                    if msg:
                        errors.append(msg)

            if file_min_dv is not None and file_max_dv is not None:
                errors.extend(_check_mob_effects(
                    entity, entity_path, entity_id, rel,
                    file_min, file_max, file_min_dv, file_max_dv,
                    valid_effects_for(file_min), ctx.extra_ids,
                ))

    if dv_wired_info:
        print(f"  DataVersion drift: {len(dv_wired_info)} file(s) saved in a newer MC"
              f" version than their wired min target (informational, not a failure):")
        for msg in dv_wired_info[:10]:
            print(f"  {msg}")
        if len(dv_wired_info) > 10:
            print(f"    ...and {len(dv_wired_info) - 10} more")

    if dv_outdated:
        total_outdated = sum(len(v) for v in dv_outdated.values())
        print(f"  DataVersions: {total_outdated} file(s) saved in newer game versions (max allowed: {max_version_name}/{max_allowed_dv}):")
        dv_w = max(len(name) for _, name in dv_outdated) + 2
        for (dv, dv_version_name), files in sorted(dv_outdated.items()):
            shown = ", ".join(files[:3])
            suffix = f"  (+ {len(files) - 3} more)" if len(files) > 3 else ""
            count = f"{len(files)} file" + ("s" if len(files) != 1 else "")
            print(f"    {dv_version_name:<{dv_w}} (dv {dv})  {count}: {shown}{suffix}")

    for msg in errors:
        print(f"  {msg}")

    if not dv_outdated and not errors and not dv_wired_info:
        print(f"  {files_checked} file(s), {entities_checked} entity ID(s) checked -- all valid")

    n_outdated = sum(len(v) for v in dv_outdated.values())
    if errors:
        return False, f"{n_outdated} warning(s), {len(errors)} error(s)"
    if dv_outdated:
        return True, f"{n_outdated} warning(s), 0 errors"
    return True, f"{files_checked} files, {entities_checked} entities checked"
