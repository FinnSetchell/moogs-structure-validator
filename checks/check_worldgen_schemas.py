from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

import schemas.patcher

if TYPE_CHECKING:
    from validator import ValidatorContext

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

_SUBDIRS: list[tuple[str, str]] = [
    ("template_pool",  "template_pool.json"),
    ("structure",      "structure.json"),
    ("structure_set",  "structure_set.json"),
    ("processor_list", "processor_list.json"),
]


def _load_schema(filename: str) -> dict:
    with (_SCHEMAS_DIR / filename).open() as f:
        return json.load(f)


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace

    failed = False
    error_count = 0
    counts: dict[str, int] = {}

    for subdir, schema_file in _SUBDIRS:
        worldgen_dir = namespace_root / "worldgen" / subdir
        if not worldgen_dir.exists():
            continue

        schema = _load_schema(schema_file)
        if subdir == "template_pool" and ctx.msl:
            schema = schemas.patcher.apply_msl(schema)

        validator = jsonschema.Draft4Validator(schema)

        files = sorted(worldgen_dir.rglob("*.json"))
        counts[subdir] = len(files)

        for json_path in files:
            rel = json_path.relative_to(worldgen_dir)
            try:
                with json_path.open() as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  [{subdir}] {rel} — invalid JSON: {e}")
                error_count += 1
                failed = True
                continue

            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            for error in errors:
                path_str = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
                print(f"  [{subdir}] {rel} @ {path_str}")
                print(f"    {error.message}")
                error_count += 1
                failed = True

    total = sum(counts.values())
    count_str = "  ".join(f"{k}: {v}" for k, v in counts.items() if v > 0)

    if error_count == 0:
        print(f"  {total} files validated, 0 schema errors")
    else:
        print(f"  {total} files validated, {error_count} schema error(s)")
    if count_str:
        print(f"  ({count_str})")

    summary = f"{total} files, 0 errors" if error_count == 0 else f"{total} files, {error_count} error(s)"
    return not failed, summary
