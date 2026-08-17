"""Read data/<ns>/moogs_structures/replace_vanilla.json.

Shared by check_msl_replace_vanilla (validates the file itself) and
check_msl_placements_and_processors (cross-refs the presets from
conditional_concentric_rings placements and vanilla_loot_swap_processors).

The MSL parser lives in ReplaceVanillaManager.parseManifest. It's lenient: any
malformed preset/replacement is skipped with a log line, so the file never
prevents datapack load. That's exactly why this parses forgivingly too and
lets the check module decide what to error/warn on.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


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

    def by_vanilla_key(self) -> dict[str, list[PresetReplacement]]:
        out: dict[str, list[PresetReplacement]] = {}
        for r in self.replacements:
            out.setdefault(r.vanilla_key, []).append(r)
        return out


def manifest_path(namespace_root: Path) -> Path:
    return namespace_root / "moogs_structures" / "replace_vanilla.json"


def load(namespace_root: Path) -> ReplaceVanillaFile | None:
    """Return parsed manifest, or None if the file doesn't exist / isn't valid JSON."""
    path = manifest_path(namespace_root)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
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
                preset_id=preset_id,
                preset_index=pi,
                replacement_index=ri,
                vanilla_key=vk,
                vanilla_structure=vs,
                replacement_structure=rs if isinstance(rs, str) else None,
            ))

    return ReplaceVanillaFile(
        path=path,
        raw=raw,
        presets=presets,
        structures=structures,
        replacements=replacements,
    )
