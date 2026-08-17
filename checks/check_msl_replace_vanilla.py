"""Validate data/<ns>/moogs_structures/replace_vanilla.json.

Covers the presets block, the structures block, and the vanilla tag hookups a
replacement needs to actually be discoverable in-game (eyes of ender for
strongholds, ocean explorer maps for monuments). See MSL:
- config/ReplaceVanillaManager.java  (presets parser)
- config/StructureListManager.java   (structures block)

The parser is lenient (warn-and-skip on malformed data), so a broken preset
silently disables the feature at runtime. This check exists to close that gap:
missing/typo'd required fields -> ERROR; likely mistakes that still load ->
WARN (printed, doesn't fail the check).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from utils import replace_vanilla as rv

if TYPE_CHECKING:
    from validator import ValidatorContext


# Small stable set. If MSL ever gains support for additional vanilla structures
# (e.g. trial_chambers replacement) add them here — nothing else in the check
# needs to change.
_VANILLA_STRUCTURES: set[str] = {
    "minecraft:ancient_city",
    "minecraft:bastion_remnant",
    "minecraft:buried_treasure",
    "minecraft:desert_pyramid",
    "minecraft:end_city",
    "minecraft:fortress",
    "minecraft:igloo",
    "minecraft:jungle_pyramid",
    "minecraft:mansion",
    "minecraft:mineshaft",
    "minecraft:mineshaft_mesa",
    "minecraft:monument",
    "minecraft:nether_fossil",
    "minecraft:ocean_ruin_cold",
    "minecraft:ocean_ruin_warm",
    "minecraft:pillager_outpost",
    "minecraft:ruined_portal",
    "minecraft:ruined_portal_desert",
    "minecraft:ruined_portal_jungle",
    "minecraft:ruined_portal_mountain",
    "minecraft:ruined_portal_nether",
    "minecraft:ruined_portal_ocean",
    "minecraft:ruined_portal_swamp",
    "minecraft:shipwreck",
    "minecraft:shipwreck_beached",
    "minecraft:stronghold",
    "minecraft:swamp_hut",
    "minecraft:trail_ruins",
    "minecraft:trial_chambers",
    "minecraft:village_desert",
    "minecraft:village_plains",
    "minecraft:village_savanna",
    "minecraft:village_snowy",
    "minecraft:village_taiga",
}


# Vanilla structures whose discovery depends on a namespaced tag. If a preset
# replaces one of these, the replacement must be added to the vanilla tag or the
# gameplay hookup silently breaks (eyes of ender don't lead to the stronghold,
# ocean explorer maps don't lead to the monument).
_TAG_HOOKUPS: dict[str, str] = {
    "minecraft:stronghold": "eye_of_ender_located",
    "minecraft:monument":   "on_ocean_explorer_maps",
}

_ID_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _is_id(s: object) -> bool:
    return isinstance(s, str) and bool(_ID_RE.match(s))


def _structure_exists(namespace_root: Path, id_: str) -> bool:
    """True if data/<id_ns>/worldgen/structure/<id_path>.json exists (any pack root)."""
    ns, _, path = id_.partition(":")
    if not ns or not path:
        return False
    # The mod's own structures live under project_root/src/main/resources/data/<ns>/...
    data_root = namespace_root.parent
    return (data_root / ns / "worldgen" / "structure" / f"{path}.json").exists()


def _structure_set_exists(namespace_root: Path, id_: str) -> bool:
    ns, _, path = id_.partition(":")
    if not ns or not path:
        return False
    data_root = namespace_root.parent
    return (data_root / ns / "worldgen" / "structure_set" / f"{path}.json").exists()


def _vanilla_tag_contains(project_root: Path, tag: str, entry_id: str) -> bool:
    """True if data/minecraft/tags/worldgen/structure/<tag>.json lists entry_id."""
    tag_path = (project_root / "src" / "main" / "resources"
                / "data" / "minecraft" / "tags" / "worldgen" / "structure"
                / f"{tag}.json")
    if not tag_path.exists():
        return False
    try:
        with tag_path.open(encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    values = data.get("values")
    if not isinstance(values, list):
        return False
    for v in values:
        if isinstance(v, str) and v == entry_id:
            return True
        if isinstance(v, dict) and v.get("id") == entry_id:
            return True
    return False


def _validate_presets(
    manifest: rv.ReplaceVanillaFile,
    namespace_root: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    seen_ids: dict[str, int] = {}
    for pi, preset in enumerate(manifest.presets):
        where = f"presets[{pi}]"
        if not isinstance(preset, dict):
            errors.append(f"  [ERROR] {where}: not an object")
            continue

        pid = preset.get("id")
        if not isinstance(pid, str) or not pid.strip():
            errors.append(f"  [ERROR] {where}.id: missing or empty")
        else:
            if pid in seen_ids:
                errors.append(
                    f"  [ERROR] {where}.id = {pid!r}: duplicate of presets[{seen_ids[pid]}] "
                    f"(the second one silently overwrites the first)"
                )
            else:
                seen_ids[pid] = pi

        default_enabled = preset.get("default_enabled")
        if default_enabled is not None and not isinstance(default_enabled, bool):
            errors.append(
                f"  [ERROR] {where}.default_enabled: must be boolean, got {type(default_enabled).__name__}"
            )

        replacements = preset.get("replacements")
        if not isinstance(replacements, list) or not replacements:
            errors.append(f"  [ERROR] {where}.replacements: missing or empty")
            continue

        for ri, rep in enumerate(replacements):
            rwhere = f"{where}.replacements[{ri}]"
            if not isinstance(rep, dict):
                errors.append(f"  [ERROR] {rwhere}: not an object")
                continue

            vk = rep.get("vanilla_key")
            if not isinstance(vk, str) or not vk.strip():
                errors.append(f"  [ERROR] {rwhere}.vanilla_key: missing (parser skips this replacement)")

            vs = rep.get("vanilla_structure")
            if not isinstance(vs, str) or not vs.strip():
                errors.append(f"  [ERROR] {rwhere}.vanilla_structure: missing (parser skips this replacement)")
            elif not _is_id(vs):
                errors.append(f"  [ERROR] {rwhere}.vanilla_structure = {vs!r}: not a valid resource id")
            elif vs not in _VANILLA_STRUCTURES:
                errors.append(
                    f"  [ERROR] {rwhere}.vanilla_structure = {vs!r}: not a known vanilla structure"
                )

            rs = rep.get("replacement_structure")
            if rs is None:
                errors.append(
                    f"  [ERROR] {rwhere}.replacement_structure: missing "
                    f"(vanilla will be cancelled but nothing replaces it)"
                )
            elif not isinstance(rs, str) or not _is_id(rs):
                errors.append(f"  [ERROR] {rwhere}.replacement_structure = {rs!r}: not a valid resource id")
            elif not _structure_exists(namespace_root, rs):
                errors.append(
                    f"  [ERROR] {rwhere}.replacement_structure = {rs!r}: "
                    f"no worldgen/structure JSON found"
                )


def _validate_tag_hookups(
    manifest: rv.ReplaceVanillaFile,
    project_root: Path,
    warnings: list[str],
) -> None:
    for pi, preset in enumerate(manifest.presets):
        if not isinstance(preset, dict):
            continue
        for ri, rep in enumerate(preset.get("replacements", []) or []):
            if not isinstance(rep, dict):
                continue
            vs = rep.get("vanilla_structure")
            rs = rep.get("replacement_structure")
            if not isinstance(vs, str) or not isinstance(rs, str):
                continue
            tag = _TAG_HOOKUPS.get(vs)
            if tag is None:
                continue
            if not _vanilla_tag_contains(project_root, tag, rs):
                warnings.append(
                    f"  [WARN] presets[{pi}].replacements[{ri}]: replacing {vs} with {rs} but "
                    f"{rs} is not in data/minecraft/tags/worldgen/structure/{tag}.json "
                    f"(gameplay hookup will not find it)"
                )


def _validate_structures_block(
    manifest: rv.ReplaceVanillaFile,
    namespace_root: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    block = manifest.structures
    if block is None:
        # Not an error; the block is optional. Only note it if the raw file
        # had a "structures" key with the wrong shape.
        if "structures" in manifest.raw and not isinstance(manifest.raw["structures"], dict):
            errors.append(f"  [ERROR] structures: must be an object")
        else:
            warnings.append(f"  [WARN] no 'structures' block: no metadata for structure preview UI")
        return

    mod_slug = block.get("mod_slug")
    template = block.get("preview_url_template")

    if mod_slug is None and template is None:
        warnings.append(
            f"  [WARN] structures: neither 'mod_slug' nor 'preview_url_template' set "
            f"(preview buttons will be disabled)"
        )

    if template is not None:
        if not isinstance(template, str):
            errors.append(f"  [ERROR] structures.preview_url_template: must be string")
        else:
            placeholders = set(_PLACEHOLDER_RE.findall(template))
            if "{structure}" not in template:
                warnings.append(
                    f"  [WARN] structures.preview_url_template: no '{{structure}}' token; "
                    f"every row will point at the same URL"
                )
            unsupported = placeholders - {"structure", "mc_version"}
            for token in sorted(unsupported):
                warnings.append(
                    f"  [WARN] structures.preview_url_template: unsupported token '{{{token}}}' "
                    f"(only {{structure}} and {{mc_version}} are substituted)"
                )

    entries = block.get("entries")
    if entries is None:
        return
    if not isinstance(entries, list):
        errors.append(f"  [ERROR] structures.entries: must be an array")
        return
    for ei, entry in enumerate(entries):
        ewhere = f"structures.entries[{ei}]"
        if not isinstance(entry, dict):
            errors.append(f"  [ERROR] {ewhere}: not an object")
            continue
        sid = entry.get("structure")
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"  [ERROR] {ewhere}.structure: missing")
        elif not _is_id(sid):
            errors.append(f"  [ERROR] {ewhere}.structure = {sid!r}: not a valid resource id")
        elif not _structure_set_exists(namespace_root, sid):
            errors.append(
                f"  [ERROR] {ewhere}.structure = {sid!r}: no worldgen/structure_set JSON found"
            )


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    manifest = rv.load(namespace_root)

    if manifest is None:
        path = rv.manifest_path(namespace_root)
        if path.exists():
            # Existed but couldn't parse.
            print(f"  [ERROR] {path.relative_to(ctx.project_root)}: invalid JSON")
            return False, "replace_vanilla.json is not valid JSON"
        print("  no replace_vanilla.json (skipping)")
        return True, "no replace_vanilla.json"

    errors: list[str] = []
    warnings: list[str] = []

    if not manifest.presets and manifest.structures is None:
        warnings.append(
            "  [WARN] replace_vanilla.json exists but has neither 'presets' nor 'structures' — "
            "the file has no effect"
        )

    _validate_presets(manifest, namespace_root, errors, warnings)
    _validate_tag_hookups(manifest, ctx.project_root, warnings)
    _validate_structures_block(manifest, namespace_root, errors, warnings)

    for msg in warnings:
        print(msg)
    for msg in errors:
        print(msg)

    n_presets = len(manifest.presets)
    n_reps = len(manifest.replacements)
    if not errors and not warnings:
        print(f"  {n_presets} preset(s), {n_reps} replacement(s), 0 issues")
    else:
        print(f"  {n_presets} preset(s), {n_reps} replacement(s), "
              f"{len(errors)} error(s), {len(warnings)} warning(s)")

    if errors:
        return False, f"{len(errors)} error(s), {len(warnings)} warning(s)"
    if warnings:
        return True, f"0 errors, {len(warnings)} warning(s)"
    return True, f"{n_presets} preset(s), {n_reps} replacement(s), all valid"
