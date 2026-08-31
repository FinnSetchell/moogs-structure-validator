from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

from registries.fetcher import _fetch_version, fetch_registry_set
from utils.boundaries import DV_1_20_2, DV_1_20_5, BoundarySide, side_of
from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.nbt_versions import _build_nbt_version_ranges, _parse_version
from utils.paths import data_dir
from utils.versions import load_version_map

if TYPE_CHECKING:
    from validator import ValidatorContext


_NEW_ITEM_FORMAT_DV = DV_1_20_5  # 1.20.5

# Fields on the old (pre-1.20.2) ActiveEffects entry.
_LEGACY_EFFECT_FIELDS = frozenset({
    "Id", "Amplifier", "Duration", "Ambient", "ShowParticles", "ShowIcon", "HiddenEffect",
})


def _is_valid(id_: str, valid_set: set[str], extra_ids: set[str]) -> bool:
    if id_ in valid_set:
        return True
    if id_ in extra_ids:
        return True
    ns = id_.split(":", 1)[0]
    if f"{ns}:*" in extra_ids:
        return True
    return False


def _check_item_format(
    item: nbtlib.Compound, slot_desc: str, entity_id: str, rel: str,
    expect_old: bool, min_version_name: str,
) -> str | None:
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


def _check_mob_effects(
    entity_nbt: nbtlib.Compound, entity_path: str, entity_id: str, rel: str,
    min_version: str, max_version: str, min_dv: int, max_dv: int,
    valid_effect_ids: set[str] | None,
    extra_ids: set[str],
) -> list[str]:
    """Check ActiveEffects vs active_effects at the 1.20.2 boundary.
    Also checks per-effect id / field format.
    """
    errors: list[str] = []
    side = side_of(min_dv, max_dv, DV_1_20_2)

    legacy = entity_nbt.get("ActiveEffects")
    new = entity_nbt.get("active_effects")

    if side == BoundarySide.NEW:
        if isinstance(legacy, list) and legacy:
            errors.append(
                f"[ERROR] {rel}: {entity_path} ({entity_id}) uses legacy `ActiveEffects` on"
                f" a min>=1.20.2 target ({min_version}); use `active_effects`"
            )
        if isinstance(new, list):
            for i, eff in enumerate(new):
                if not isinstance(eff, nbtlib.Compound):
                    continue
                eff_path = f"{entity_path}.active_effects[{i}]"
                id_tag = eff.get("id")
                if id_tag is None:
                    errors.append(f"[ERROR] {rel}: {eff_path}: missing `id`")
                    continue
                id_str = str(id_tag)
                if not id_str.startswith("minecraft:") and ":" in id_str:
                    # allow non-vanilla ids via extra_ids
                    if not _is_valid(id_str, valid_effect_ids or set(), extra_ids):
                        errors.append(
                            f"[ERROR] {rel}: {eff_path}: unknown mob_effect id '{id_str}'"
                            f" (min target {min_version})"
                        )
                elif valid_effect_ids is not None and not _is_valid(id_str, valid_effect_ids, extra_ids):
                    errors.append(
                        f"[ERROR] {rel}: {eff_path}: unknown mob_effect id '{id_str}'"
                        f" (min target {min_version})"
                    )
                # PascalCase fields on new-format effect = FAIL
                bad = [f for f in _LEGACY_EFFECT_FIELDS if f in eff]
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
    else:  # SPANS
        if isinstance(legacy, list) or isinstance(new, list):
            errors.append(
                f"[ERROR] {rel}: {entity_path} ({entity_id}) has mob effects but its wired"
                f" range {min_version}..{max_version} spans 1.20.2 (renamed here);"
                f" no single file can be correct on both sides"
            )

    return errors


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")

    if not structures_dir.exists():
        return True, "no structures directory"

    cache_dir = Path(__file__).parent.parent / "cache"

    version_map = load_version_map(cache_dir, ctx.refresh)

    max_allowed_dv: int | None = None
    max_version_name: str | None = None
    min_allowed_dv: int | None = None
    min_version_name: str | None = None

    if version_map:
        for v in ctx.mc_versions:
            dv = version_map.get(v)
            if dv is None:
                print(f"  [WARN] version '{v}' not found in versions.json -- skipping DataVersion check for it")
                continue
            if max_allowed_dv is None or dv > max_allowed_dv:
                max_allowed_dv = dv
                max_version_name = v
            if min_allowed_dv is None or dv < min_allowed_dv:
                min_allowed_dv = dv
                min_version_name = v

    if min_allowed_dv is None:
        item_check_mode: str | None = None
    elif min_allowed_dv < _NEW_ITEM_FORMAT_DV:
        item_check_mode = "old"
    else:
        item_check_mode = "new"

    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    global_min_version = min(ctx.mc_versions, key=_parse_version)
    global_max_version = max(ctx.mc_versions, key=_parse_version)
    nbt_ranges = {}
    if template_pool_dir.exists():
        nbt_ranges = _build_nbt_version_ranges(
            template_pool_dir, structures_dir, ctx.namespace, global_min_version,
            ctx.mc_versions, global_max_version,
        )
    non_minecraft_valid_entities = {e for e in ctx.valid_entities if not e.startswith("minecraft:")}
    version_entity_cache: dict[str, set[str]] = {}
    version_effect_cache: dict[str, set[str]] = {}

    def valid_entities_for(version: str) -> set[str]:
        if version not in version_entity_cache:
            vdata = _fetch_version(version, cache_dir, ctx.refresh)
            version_entity_cache[version] = (
                {"minecraft:" + n for n in vdata.get("entity_type", [])}
                | non_minecraft_valid_entities
            )
        return version_entity_cache[version]

    def valid_effects_for(version: str) -> set[str]:
        if version not in version_effect_cache:
            version_effect_cache[version] = fetch_registry_set(
                version, cache_dir, ctx.refresh, "mob_effect"
            )
        return version_effect_cache[version]

    dv_outdated: dict[tuple[int, str], list[str]] = defaultdict(list)
    dv_wired_info: list[str] = []
    errors: list[str] = []
    files_checked = 0
    entities_checked = 0

    for nbt_path in sorted(structures_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception as e:
            print(f"  [WARN] could not load {nbt_path.name}: {e}")
            continue

        files_checked += 1
        rel = str(nbt_path.relative_to(structures_dir))

        info = nbt_ranges.get(nbt_path)
        file_min = info.min_version if info else global_min_version
        file_max = info.max_version if info else global_max_version
        is_wired = info is not None
        file_min_dv = version_map.get(file_min)
        file_max_dv = version_map.get(file_max)

        if file_min_dv is None:
            file_item_mode = item_check_mode
        else:
            file_item_mode = "old" if file_min_dv < _NEW_ITEM_FORMAT_DV else "new"

        dv_tag = nbt.get("DataVersion")
        if dv_tag is not None:
            file_dv = int(dv_tag)
            if is_wired and file_min_dv is not None and file_dv > file_min_dv:
                dv_wired_info.append(
                    f"[INFO] {rel}: DataVersion {file_dv} > wired min target"
                    f" {file_min} (DV {file_min_dv}); MC's data fixer handles the load,"
                    f" but content checks may still flag schema issues"
                )
            elif max_allowed_dv is not None and file_dv > max_allowed_dv:
                dv_version_name = next(
                    (k for k, v in version_map.items() if v == file_dv), str(file_dv)
                )
                dv_outdated[(file_dv, dv_version_name)].append(rel)

        for entity_nbt, entity_path in iter_entities(nbt):
            id_tag = entity_nbt.get("id")
            if id_tag is None:
                continue
            entity_id = str(id_tag)
            entities_checked += 1

            if not _is_valid(entity_id, valid_entities_for(file_min), ctx.extra_ids):
                errors.append(f"[ERROR] {rel}: {entity_path}: unknown entity ID '{entity_id}'")

            if file_item_mode is not None:
                expect_old = file_item_mode == "old"
                for list_field in ("HandItems", "ArmorItems"):
                    items_tag = entity_nbt.get(list_field)
                    if items_tag is None:
                        continue
                    for slot, item in enumerate(items_tag):
                        if not isinstance(item, nbtlib.Compound):
                            continue
                        msg = _check_item_format(
                            item, f"{entity_path}.{list_field}[{slot}]", entity_id, rel,
                            expect_old, file_min,
                        )
                        if msg:
                            errors.append(msg)
                body_item = entity_nbt.get("body_armor_item")
                if isinstance(body_item, nbtlib.Compound):
                    msg = _check_item_format(
                        body_item, f"{entity_path}.body_armor_item", entity_id, rel,
                        expect_old, file_min,
                    )
                    if msg:
                        errors.append(msg)

            if file_min_dv is not None and file_max_dv is not None:
                valid_effects: set[str] | None
                if version_map.get(file_min) is not None:
                    try:
                        valid_effects = valid_effects_for(file_min)
                    except Exception:
                        valid_effects = None
                else:
                    valid_effects = None
                errors.extend(_check_mob_effects(
                    entity_nbt, entity_path, entity_id, rel,
                    file_min, file_max, file_min_dv, file_max_dv,
                    valid_effects, ctx.extra_ids,
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
