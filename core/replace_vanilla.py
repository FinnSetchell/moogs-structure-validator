"""Read ``data/<ns>/moogs_structures/replace_vanilla.json``.

Shared by ``check_msl_replace_vanilla`` (validates the file itself),
``check_msl_placements_and_processors`` (cross-refs presets) and
``check_data_integrity`` (a replacement structure counts as placed).

MSL's parser (``ReplaceVanillaManager.parseManifest``) is lenient: any malformed
preset or replacement is skipped with a log line, so the file never prevents
datapack load. This parses just as forgivingly and lets the checks decide what
to error or warn on.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.project import Project


@dataclass(frozen=True)
class PresetReplacement:
    preset_id: str
    preset_index: int
    replacement_index: int
    vanilla_key: str
    vanilla_structure: str
    replacement_structure: str | None


@dataclass
class ReplaceVanillaFile:
    path: Path
    raw: dict[str, Any]
    presets: list[dict[str, Any]]
    structures: dict[str, Any] | None
    replacements: list[PresetReplacement]

    def vanilla_keys(self) -> set[str]:
        return {r.vanilla_key for r in self.replacements}


def manifest_path(project: Project) -> Path:
    return project.namespace_root / "moogs_structures" / "replace_vanilla.json"


def load(project: Project) -> ReplaceVanillaFile | None:
    """The parsed manifest, or None if it does not exist or is not a JSON object."""
    path = manifest_path(project)
    if not path.exists():
        return None
    raw = project.try_json(path)
    if not isinstance(raw, dict):
        return None

    presets_raw = raw.get("presets")
    presets = presets_raw if isinstance(presets_raw, list) else []
    structures_raw = raw.get("structures")
    structures = structures_raw if isinstance(structures_raw, dict) else None

    replacements: list[PresetReplacement] = []
    for pi, preset in enumerate(presets):
        if not isinstance(preset, dict):
            continue
        preset_id = preset.get("id") if isinstance(preset.get("id"), str) else ""
        for ri, rep in enumerate(preset.get("replacements", []) or []):
            if not isinstance(rep, dict):
                continue
            vk = rep.get("vanilla_key")
            vs = rep.get("vanilla_structure")
            if not isinstance(vk, str) or not isinstance(vs, str):
                continue
            rs = rep.get("replacement_structure")
            replacements.append(PresetReplacement(
                preset_id, pi, ri, vk, vs, rs if isinstance(rs, str) else None,
            ))

    return ReplaceVanillaFile(path, raw, presets, structures, replacements)
