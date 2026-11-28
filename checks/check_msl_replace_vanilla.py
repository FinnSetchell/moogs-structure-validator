"""``data/<ns>/moogs_structures/replace_vanilla.json`` (MSL 3.1.0+).

Covers the presets block, the per-replacement ``options`` block, the structures
block, and the vanilla tag hookups a replacement needs to be discoverable
in-game (eyes of ender for strongholds, ocean explorer maps for monuments).
MSL's parser is lenient -- it warns and
skips malformed data -- so a broken preset silently disables the feature at
runtime. Missing or mistyped required fields are errors; likely mistakes that
still load are warnings.

The set of vanilla structures a preset may replace comes from mcmeta's
``worldgen/structure`` registry across the targeted versions, so a structure
added in a later Minecraft release is recognised as soon as the project
targets it. The bundled list is the fallback when the registry cannot be read.

MSL takes any structure id as the one to replace, another mod's included (Fortress
Reimagined replaces Nether Structures' mega fortress); the replacement then applies
only when that mod is installed. The validator cannot see another mod's structures,
so such a target is checked against the mod's loader files instead: one whose
namespace no loader file names as a dependency of any kind warns, since a misspelt
id would never apply and nothing would say so.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from core import replace_vanilla as rv
from core.context import Services, services
from core.project import Project

if TYPE_CHECKING:
    from core.context import ValidatorContext


# Fallback when mcmeta is unreachable: the vanilla structures as of 26.2.
_VANILLA_STRUCTURES_FALLBACK: set[str] = {
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
_VANILLA_STRUCTURES = _VANILLA_STRUCTURES_FALLBACK

# Vanilla structures whose discovery depends on a namespaced tag. If a preset
# replaces one of these, the replacement must be added to the tag or the
# gameplay hookup silently breaks.
_TAG_HOOKUPS: dict[str, str] = {
    "minecraft:stronghold": "eye_of_ender_located",
    "minecraft:monument":   "on_ocean_explorer_maps",
}

_FABRIC_DEPENDENCY_KEYS = ("depends", "recommends", "suggests")

_ID_RE = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")

# Per-replacement fidelity switches (MSL 3.3.0+). Each defaults to true when
# absent and the whole block is optional, so a misspelled key is invisible at
# runtime: MSL logs one warning and keeps the default, meaning the behaviour the
# author meant to switch OFF stays on.
_REPLACEMENT_OPTIONS: tuple[str, ...] = (
    "alias_lookups",
    "inherit_spawn_overrides",
    "redirect_locate",
    "mirror_tags",
)


def _vanilla_structures(svc: Services) -> set[str]:
    """Every vanilla ``worldgen/structure`` id on any targeted version.

    mcmeta's summary omits the registry for a few versions (1.21 among them),
    so the union is taken over the versions that do carry it; the bundled list
    stands in when none do or the fetch fails.
    """
    found: set[str] = set()
    for v in svc.mc_versions:
        try:
            found |= svc.mcmeta.registry(v, "worldgen/structure")
        except Exception:
            continue
    return found | _VANILLA_STRUCTURES_FALLBACK if found else set(_VANILLA_STRUCTURES_FALLBACK)


def _is_id(s: object) -> bool:
    return isinstance(s, str) and bool(_ID_RE.match(s))


def _structure_exists(project: Project, id_: str) -> bool:
    ns, _, path = id_.partition(":")
    if not ns or not path:
        return False
    return (project.data_root / ns / "worldgen" / "structure" / f"{path}.json").exists()


def _structure_set_exists(project: Project, id_: str) -> bool:
    ns, _, path = id_.partition(":")
    if not ns or not path:
        return False
    return (project.data_root / ns / "worldgen" / "structure_set" / f"{path}.json").exists()


def _declared_mods(project: Project) -> set[str] | None:
    """The mod ids the loader files name as dependencies of any kind (Fabric
    ``depends``, ``recommends`` or ``suggests``, a Quilt ``depends`` entry, a Forge
    or NeoForge ``[[dependencies.*]]`` block, mandatory or optional). None when the
    mod has no loader files, as a plain datapack has nowhere to name one."""
    res = project.data_root.parent
    mods: set[str] = set()
    found = False
    meta = project.try_json(res / "fabric.mod.json")
    if isinstance(meta, dict):
        found = True
        for key in _FABRIC_DEPENDENCY_KEYS:
            if isinstance(meta.get(key), dict):
                mods |= set(meta[key])
    meta = project.try_json(res / "quilt.mod.json")
    if isinstance(meta, dict):
        found = True
        loader = meta.get("quilt_loader") if isinstance(meta.get("quilt_loader"), dict) else {}
        for dep in loader.get("depends") or []:
            dep_id = dep.get("id") if isinstance(dep, dict) else dep
            if isinstance(dep_id, str):
                mods.add(dep_id)
    for toml in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
        try:
            text = (res / toml).read_text(encoding="utf-8")
        except OSError:
            continue
        found = True
        for block in re.split(r"\[\[dependencies\.", text)[1:]:
            m = re.search(r"""^\s*modId\s*=\s*["']([^"']+)["']""", block, re.MULTILINE)
            if m:
                mods.add(m.group(1))
    return mods if found else None


def _vanilla_tag_contains(project: Project, tag: str, entry_id: str) -> bool:
    """True if ``data/minecraft/tags/worldgen/structure/<tag>.json`` lists ``entry_id``."""
    tag_path = project.data_root / "minecraft" / "tags" / "worldgen" / "structure" / f"{tag}.json"
    if not tag_path.exists():
        return False
    data = project.try_json(tag_path)
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


def _validate_options(rep: dict, rwhere: str, errors: list[str]) -> None:
    """The optional ``options`` block on one replacement."""
    if "options" not in rep:
        return
    options = rep["options"]
    if not isinstance(options, dict):
        errors.append(
            f"  [ERROR] {rwhere}.options: must be an object, got {type(options).__name__}"
        )
        return
    for key, value in options.items():
        if key not in _REPLACEMENT_OPTIONS:
            errors.append(
                f"  [ERROR] {rwhere}.options.{key}: unknown option (ignored at runtime; "
                f"valid options are {', '.join(_REPLACEMENT_OPTIONS)})"
            )
        elif not isinstance(value, bool):
            errors.append(
                f"  [ERROR] {rwhere}.options.{key}: must be boolean, got {type(value).__name__}"
            )


def _validate_target(vs: str, rwhere: str, project: Project, vanilla: set[str],
                     declared: set[str] | None, errors: list[str], warnings: list[str]) -> None:
    """The structure a replacement stands in for: vanilla, this mod's own, or another mod's."""
    ns = vs.partition(":")[0]
    if ns == "minecraft":
        if vs not in vanilla:
            errors.append(f"  [ERROR] {rwhere}.vanilla_structure = {vs!r}: not a known vanilla structure")
    elif ns == project.namespace:
        if not _structure_exists(project, vs):
            errors.append(f"  [ERROR] {rwhere}.vanilla_structure = {vs!r}: no worldgen/structure JSON found")
    elif declared is not None and ns not in declared:
        warnings.append(
            f"  [WARN] {rwhere}.vanilla_structure = {vs!r}: another mod's structure, replaced only when "
            f"that mod is installed, and no loader file names {ns!r} as a dependency (an optional one "
            f"will do), so a misspelt id would go unnoticed"
        )


def _validate_presets(manifest: rv.ReplaceVanillaFile, project: Project, vanilla: set[str],
                      errors: list[str], warnings: list[str]) -> None:
    declared = _declared_mods(project)
    seen_ids: dict[str, int] = {}
    for pi, preset in enumerate(manifest.presets):
        where = f"presets[{pi}]"
        if not isinstance(preset, dict):
            errors.append(f"  [ERROR] {where}: not an object")
            continue

        pid = preset.get("id")
        if not isinstance(pid, str) or not pid.strip():
            errors.append(f"  [ERROR] {where}.id: missing or empty")
        elif pid in seen_ids:
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
            else:
                _validate_target(vs, rwhere, project, vanilla, declared, errors, warnings)

            rs = rep.get("replacement_structure")
            if rs is None:
                errors.append(
                    f"  [ERROR] {rwhere}.replacement_structure: missing "
                    f"(vanilla will be cancelled but nothing replaces it)"
                )
            elif not isinstance(rs, str) or not _is_id(rs):
                errors.append(f"  [ERROR] {rwhere}.replacement_structure = {rs!r}: not a valid resource id")
            elif not _structure_exists(project, rs):
                errors.append(
                    f"  [ERROR] {rwhere}.replacement_structure = {rs!r}: "
                    f"no worldgen/structure JSON found"
                )

            _validate_options(rep, rwhere, errors)


def _validate_tag_hookups(manifest: rv.ReplaceVanillaFile, project: Project, warnings: list[str]) -> None:
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
            if not _vanilla_tag_contains(project, tag, rs):
                warnings.append(
                    f"  [WARN] presets[{pi}].replacements[{ri}]: replacing {vs} with {rs} but "
                    f"{rs} is not in data/minecraft/tags/worldgen/structure/{tag}.json "
                    f"(gameplay hookup will not find it)"
                )


def _validate_structures_block(manifest: rv.ReplaceVanillaFile, project: Project,
                               errors: list[str], warnings: list[str]) -> None:
    block = manifest.structures
    if block is None:
        if "structures" in manifest.raw and not isinstance(manifest.raw["structures"], dict):
            errors.append("  [ERROR] structures: must be an object")
        else:
            warnings.append("  [WARN] no 'structures' block: no metadata for structure preview UI")
        return

    mod_slug = block.get("mod_slug")
    template = block.get("preview_url_template")

    if mod_slug is None and template is None:
        warnings.append(
            "  [WARN] structures: neither 'mod_slug' nor 'preview_url_template' set "
            "(preview buttons will be disabled)"
        )

    if template is not None:
        if not isinstance(template, str):
            errors.append("  [ERROR] structures.preview_url_template: must be string")
        else:
            placeholders = set(_PLACEHOLDER_RE.findall(template))
            if "{structure}" not in template:
                warnings.append(
                    "  [WARN] structures.preview_url_template: no '{structure}' token; "
                    "every row will point at the same URL"
                )
            for token in sorted(placeholders - {"structure", "mc_version"}):
                warnings.append(
                    f"  [WARN] structures.preview_url_template: unsupported token '{{{token}}}' "
                    f"(only {{structure}} and {{mc_version}} are substituted)"
                )

    entries = block.get("entries")
    if entries is None:
        return
    if not isinstance(entries, list):
        errors.append("  [ERROR] structures.entries: must be an array")
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
        elif not _structure_set_exists(project, sid):
            errors.append(f"  [ERROR] {ewhere}.structure = {sid!r}: no worldgen/structure_set JSON found")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    manifest = rv.load(project)

    if manifest is None:
        path = rv.manifest_path(project)
        if path.exists():
            print(f"  [ERROR] {path.relative_to(project.root)}: invalid JSON")
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

    _validate_presets(manifest, project, _vanilla_structures(svc), errors, warnings)
    _validate_tag_hookups(manifest, project, warnings)
    _validate_structures_block(manifest, project, errors, warnings)

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
