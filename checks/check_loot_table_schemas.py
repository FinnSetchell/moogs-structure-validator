from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


_SCHEMA_URL = "https://raw.githubusercontent.com/misode/minecraft-json-schemas/main/data/loot_table.json"
_CACHE_FILE = Path(__file__).parent.parent / "cache" / "schema-loot_table.json"


def _load_schema(refresh: bool) -> dict:
    if _CACHE_FILE.exists() and not refresh:
        with _CACHE_FILE.open() as f:
            return json.load(f)

    print("[check_loot_table_schemas] fetching schema...")
    with urllib.request.urlopen(_SCHEMA_URL) as resp:
        schema = json.loads(resp.read().decode())

    _CACHE_FILE.parent.mkdir(exist_ok=True)
    with _CACHE_FILE.open("w") as f:
        json.dump(schema, f)

    return schema


def run(ctx: ValidatorContext) -> bool:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    loot_table_dir = data_dir(namespace_root, "loot_table")

    if not loot_table_dir.exists():
        print(f"[check_loot_table_schemas] loot table directory not found: {loot_table_dir}")
        return True

    schema = _load_schema(ctx.refresh)
    validator = jsonschema.Draft7Validator(schema)

    files = sorted(loot_table_dir.rglob("*.json"))
    if not files:
        print("[check_loot_table_schemas] no loot table files found")
        return True

    failed = False
    for json_path in files:
        rel = json_path.relative_to(loot_table_dir)
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

    if not failed:
        print(f"[check_loot_table_schemas] all {len(files)} loot table(s) valid")

    return not failed
