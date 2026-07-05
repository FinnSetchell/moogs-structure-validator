from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from utils.paths import all_data_dirs

if TYPE_CHECKING:
    from validator import ValidatorContext


def _collect_block_ids(obj: object, out: list[str]) -> None:
    """Recursively collect block IDs from a processor JSON value.

    Targets any dict with a "Name" key (block state objects) and any
    string-valued "block" key (input_predicate.block style). Tag refs
    starting with "#" are skipped.
    """
    if isinstance(obj, dict):
        name = obj.get("Name")
        if isinstance(name, str) and ":" in name and not name.startswith("#"):
            out.append(name)
        block = obj.get("block")
        if isinstance(block, str) and ":" in block and not block.startswith("#"):
            out.append(block)
        for v in obj.values():
            _collect_block_ids(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_block_ids(item, out)


def _namespaced(ref: str) -> str:
    return ref if ":" in ref else f"minecraft:{ref}"


def _resource_exists(ctx: ValidatorContext, ref: str, data_type: str) -> bool | None:
    """Check a project-local resource reference. Returns None when the ref
    points outside this project (vanilla or another mod) and can't be verified."""
    namespace, _, path = _namespaced(ref).partition(":")
    if namespace != ctx.namespace:
        return None
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / namespace
    return any((d / f"{path}.json").exists() for d in all_data_dirs(namespace_root, data_type))


def _check_msl_references(ctx: ValidatorContext, rel, proc: dict, index: int, bad: list[str]) -> None:
    ptype = proc.get("processor_type")
    where = f"{rel} processors[{index}]"

    if ptype == "moogs_structures:spawner_randomizing_processor":
        entities = proc.get("weighted_entities")
        if isinstance(entities, list):
            for entry in entities:
                if not isinstance(entry, dict):
                    continue
                entity = entry.get("entity")
                if isinstance(entity, str):
                    entity_id = _namespaced(entity)
                    if entity_id not in ctx.valid_entities and entity_id not in ctx.extra_ids:
                        bad.append(f"{where}: entity {entity_id!r} not in entity registry")
        min_delay = proc.get("min_spawn_delay")
        max_delay = proc.get("max_spawn_delay")
        if isinstance(min_delay, int) and isinstance(max_delay, int) and min_delay > max_delay:
            bad.append(f"{where}: min_spawn_delay {min_delay} greater than max_spawn_delay {max_delay}")

    elif ptype == "moogs_structures:vault_randomizing_processor":
        for key in ("key_item", "ominous_key_item"):
            item = proc.get(key)
            if isinstance(item, str):
                item_id = _namespaced(item)
                if item_id not in ctx.valid_items and item_id not in ctx.extra_ids:
                    bad.append(f"{where}: {key} {item_id!r} not in item registry")
        for key in ("loot_table", "ominous_loot_table"):
            ref = proc.get(key)
            if isinstance(ref, str) and _resource_exists(ctx, ref, "loot_table") is False:
                bad.append(f"{where}: {key} {ref!r} has no loot table file in this project")

    elif ptype == "moogs_structures:trial_spawner_randomizing_processor":
        for key in ("normal_config", "ominous_config"):
            ref = proc.get(key)
            if isinstance(ref, str) and _resource_exists(ctx, ref, "trial_spawner") is False:
                bad.append(f"{where}: {key} {ref!r} has no trial_spawner config file in this project")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    processor_list_dir = namespace_root / "worldgen" / "processor_list"

    if not processor_list_dir.exists():
        return True, "no processor_list directory"

    files = sorted(processor_list_dir.rglob("*.json"))
    if not files:
        return True, "no processor_list files"

    bad: list[str] = []
    file_count = 0

    for json_path in files:
        rel = json_path.relative_to(processor_list_dir)
        try:
            with json_path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [ERROR] {rel}: {e}")
            bad.append(str(rel))
            continue

        processors = data.get("processors", [])
        if isinstance(processors, str):
            # string ref (e.g. "minecraft:empty") — nothing to validate
            file_count += 1
            continue

        ids: list[str] = []
        _collect_block_ids(processors, ids)

        for block_id in ids:
            if block_id not in ctx.valid_blocks and block_id not in ctx.extra_ids:
                bad.append(f"{rel}: {block_id!r} not in block registry")

        if isinstance(processors, list):
            for i, proc in enumerate(processors):
                if isinstance(proc, dict):
                    _check_msl_references(ctx, rel, proc, i, bad)

        file_count += 1

    for msg in bad:
        print(f"  [WARN] processor rule: {msg}")

    if not bad:
        print(f"  {file_count} processor_list file(s), all references valid")

    summary = (
        f"{file_count} file(s), {len(bad)} invalid reference(s)"
        if bad
        else f"{file_count} file(s), all valid"
    )
    return not bad, summary
