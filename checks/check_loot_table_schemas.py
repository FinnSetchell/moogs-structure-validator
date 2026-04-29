from __future__ import annotations

import copy
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import jsonschema
import referencing
import referencing.jsonschema

from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


_SCHEMA_URL = "https://raw.githubusercontent.com/misode/minecraft-json-schemas/master/java/data/loot_table.json"
_CACHE_FILE = Path(__file__).parent.parent / "cache" / "schema-loot_table.json"
_REFS_CACHE_DIR = Path(__file__).parent.parent / "cache" / "schema-refs"


def resolve_refs(node: object, base_url: str) -> object:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and not v.startswith("#") and "://" not in v:
                out[k] = urljoin(base_url, v)
            else:
                out[k] = resolve_refs(v, base_url)
        return out
    elif isinstance(node, list):
        return [resolve_refs(item, base_url) for item in node]
    return node


def patch_schema(schema: dict) -> dict:
    s = copy.deepcopy(schema)

    s.pop("additionalProperties", None)
    props = s.setdefault("properties", {})
    props.setdefault("type", {"type": "string"})
    props.setdefault("random_sequence", {"type": "string"})

    pools_items = (
        s.get("properties", {})
        .get("pools", {})
        .get("items", {})
    )
    if pools_items:
        pools_items.pop("additionalProperties", None)
        dist = {"oneOf": [{"type": ["number", "integer"]}, {"type": "object"}]}
        pool_props = pools_items.setdefault("properties", {})
        pool_props["rolls"] = dist
        pool_props["bonus_rolls"] = dist

        entries_items = pool_props.get("entries", {}).get("items", {})
        if entries_items:
            entries_items.pop("oneOf", None)
            entries_items.pop("required", None)
            entries_items.pop("additionalProperties", None)
            entries_items["type"] = "object"
            entries_items["required"] = ["type"]
            entries_items["properties"] = {
                "type": {"type": "string"},
                "name": {},
                "weight": {},
                "quality": {},
                "functions": {},
                "conditions": {},
                "children": {},
                "entries": {},
                "expand": {},
                "value": {},
            }

    defs = s.get("definitions", {})
    if "function" in defs:
        defs["function"] = {
            "type": "object",
            "required": ["function"],
            "properties": {"function": {"type": "string"}},
        }

    return s


def make_retriever(cache_dir: Path, refresh: bool):
    cache_dir.mkdir(parents=True, exist_ok=True)

    def retriever(uri: str):
        key = hashlib.md5(uri.encode()).hexdigest()
        cache_file = cache_dir / key
        if cache_file.exists() and not refresh:
            with cache_file.open() as f:
                contents = json.load(f)
        else:
            with urllib.request.urlopen(uri) as resp:
                contents = json.loads(resp.read().decode())
            with cache_file.open("w") as f:
                json.dump(contents, f)
        return referencing.Resource.from_contents(
            contents,
            default_specification=referencing.jsonschema.DRAFT4,
        )

    return retriever


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    loot_table_dir = data_dir(namespace_root, "loot_table")

    if not loot_table_dir.exists():
        print("  no loot table directory — skipped")
        return True, "skipped (no loot tables)"

    files = sorted(loot_table_dir.rglob("*.json"))
    if not files:
        print("  no loot table files found")
        return True, "0 files"

    if _CACHE_FILE.exists() and not ctx.refresh:
        with _CACHE_FILE.open() as f:
            schema = json.load(f)
    else:
        print("  fetching schema...")
        with urllib.request.urlopen(_SCHEMA_URL) as resp:
            schema = json.loads(resp.read().decode())
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        with _CACHE_FILE.open("w") as f:
            json.dump(schema, f)

    schema = resolve_refs(schema, _SCHEMA_URL)
    schema = patch_schema(schema)

    registry = referencing.Registry(retrieve=make_retriever(_REFS_CACHE_DIR, ctx.refresh))
    validator = jsonschema.Draft4Validator(schema, registry=registry)

    error_count = 0
    for json_path in files:
        rel = json_path.relative_to(loot_table_dir)
        try:
            with json_path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  {rel} — invalid JSON: {e}")
            error_count += 1
            continue

        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        for error in errors:
            path_str = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
            print(f"  {rel} @ {path_str}")
            print(f"    {error.message}")
            error_count += 1

    if error_count == 0:
        print(f"  {len(files)} files, 0 schema errors")

    summary = f"{len(files)} files, 0 errors" if error_count == 0 else f"{len(files)} files, {error_count} schema error(s)"
    return error_count == 0, summary
