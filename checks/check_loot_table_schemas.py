"""Each ``loot_table/*.json`` validates against misode's loot table JSON schema.

The schema is fetched from misode/minecraft-json-schemas (with its ``$ref``
targets) and cached. It is then loosened where it is stricter than the game:
extra top-level keys, numeric or provider ``rolls``, any entry ``type``, and
functions validated only for having a ``function`` id -- the game accepts all
of these, and the point here is malformed structure, not exhaustive typing.
"""
from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import jsonschema
import referencing
import referencing.jsonschema

from core import mcmeta
from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext


def resolve_refs(node: object, base_url: str) -> object:
    """Make every relative ``$ref`` absolute against the schema's own URL."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and not v.startswith("#") and "://" not in v:
                out[k] = urljoin(base_url, v)
            else:
                out[k] = resolve_refs(v, base_url)
        return out
    if isinstance(node, list):
        return [resolve_refs(item, base_url) for item in node]
    return node


def patch_schema(schema: dict) -> dict:
    s = copy.deepcopy(schema)

    s.pop("additionalProperties", None)
    props = s.setdefault("properties", {})
    props.setdefault("type", {"type": "string"})
    props.setdefault("random_sequence", {"type": "string"})

    pools_items = s.get("properties", {}).get("pools", {}).get("items", {})
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


def _retriever(cache_dir, refresh: bool):
    def retrieve(uri: str):
        return referencing.Resource.from_contents(
            mcmeta.fetch_schema_ref(uri, cache_dir, refresh),
            default_specification=referencing.jsonschema.DRAFT4,
        )
    return retrieve


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    loot_table_dir = project.loot_table_dir

    if not loot_table_dir.exists():
        print("  no loot table directory — skipped")
        return True, "skipped (no loot tables)"

    files = project.json_files(loot_table_dir)
    if not files:
        print("  no loot table files found")
        return True, "0 files"

    schema = mcmeta.fetch_loot_table_schema(svc.mcmeta.cache_dir, svc.refresh)
    schema = patch_schema(resolve_refs(schema, mcmeta.LOOT_SCHEMA_URL))
    registry = referencing.Registry(retrieve=_retriever(svc.mcmeta.cache_dir, svc.refresh))
    validator = jsonschema.Draft4Validator(schema, registry=registry)

    error_count = 0
    for json_path in files:
        rel = json_path.relative_to(loot_table_dir)
        try:
            data = project.load_json(json_path)
        except json.JSONDecodeError as e:
            print(f"  {rel} — invalid JSON: {e}")
            error_count += 1
            continue

        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            path_str = " > ".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
            print(f"  {rel} @ {path_str}")
            print(f"    {error.message}")
            error_count += 1

    if error_count == 0:
        print(f"  {len(files)} files, 0 schema errors")

    summary = f"{len(files)} files, 0 errors" if error_count == 0 else f"{len(files)} files, {error_count} schema error(s)"
    return error_count == 0, summary
