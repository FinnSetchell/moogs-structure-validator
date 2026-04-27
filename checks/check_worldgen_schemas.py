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


def run(ctx: ValidatorContext) -> bool:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace

    failed = False
    total = 0

    for subdir, schema_file in _SUBDIRS:
        worldgen_dir = namespace_root / "worldgen" / subdir
        if not worldgen_dir.exists():
            continue

        schema = _load_schema(schema_file)
        if subdir == "template_pool" and ctx.msl:
            schema = schemas.patcher.apply_msl(schema)

        validator = jsonschema.Draft4Validator(schema)

        files = sorted(worldgen_dir.rglob("*.json"))
        for json_path in files:
            rel = json_path.relative_to(worldgen_dir)
            try:
                with json_path.open() as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  [ERROR] {rel} — invalid JSON: {e}")
                failed = True
                continue

            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            for error in errors:
                path = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
                print(f"  [SCHEMA] {rel} @ {path} — {error.message}")
                failed = True

            total += 1

    print(f"[check_worldgen_schemas] checked {total} worldgen file(s)")
    return not failed
