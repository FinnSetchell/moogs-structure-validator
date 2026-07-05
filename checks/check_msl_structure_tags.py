"""Validates MSL structure tag files a consuming mod ships under
data/moogs_structures/tags/worldgen/structure/.

MSL defines three structure tags: no_basalt and no_delta suppress nether
basalt columns and delta lava inside tagged structures, larger_locate_search
widens the /locate radius. A tag file with any other name does nothing, so
unknown names are flagged as likely typos. Structure ids in the project's
own namespace must resolve to a structure JSON.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from validator import ValidatorContext

_KNOWN_TAGS = {"no_basalt", "no_delta", "larger_locate_search"}


def _iter_values(values: list) -> list[tuple[str, object]]:
    """Yield (id, raw entry) for each tag value, handling the object form."""
    out = []
    for entry in values:
        if isinstance(entry, str):
            out.append((entry, entry))
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str):
            out.append((entry["id"], entry))
        else:
            out.append(("", entry))
    return out


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    tags_dir = (ctx.project_root / "src" / "main" / "resources" / "data"
                / "moogs_structures" / "tags" / "worldgen" / "structure")

    if not tags_dir.exists():
        return True, "no msl structure tags"

    files = sorted(tags_dir.rglob("*.json"))
    if not files:
        return True, "no msl structure tags"

    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    bad: list[str] = []

    for json_path in files:
        rel = json_path.relative_to(tags_dir)
        tag_name = rel.with_suffix("").as_posix()

        if tag_name not in _KNOWN_TAGS:
            bad.append(f"{rel}: unknown MSL structure tag {tag_name!r} "
                       f"(known: {', '.join(sorted(_KNOWN_TAGS))})")

        try:
            with json_path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            bad.append(f"{rel}: invalid JSON: {e}")
            continue

        values = data.get("values") if isinstance(data, dict) else None
        if not isinstance(values, list):
            bad.append(f"{rel}: missing values list")
            continue

        for value_id, raw in _iter_values(values):
            if not value_id:
                bad.append(f"{rel}: malformed tag entry {raw!r}")
                continue
            ref = value_id.lstrip("#")
            namespace, _, path = (ref if ":" in ref else f"minecraft:{ref}").partition(":")
            if namespace != ctx.namespace or value_id.startswith("#"):
                continue
            structure_file = namespace_root / "worldgen" / "structure" / f"{path}.json"
            if not structure_file.exists():
                bad.append(f"{rel}: structure {ref!r} not found in this project")

    for msg in bad:
        print(f"  [WARN] msl structure tag: {msg}")
    if not bad:
        print(f"  {len(files)} msl structure tag file(s), all valid")

    summary = (
        f"{len(files)} file(s), {len(bad)} problem(s)"
        if bad
        else f"{len(files)} file(s), all valid"
    )
    return not bad, summary
