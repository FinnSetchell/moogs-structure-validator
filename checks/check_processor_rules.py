"""References inside ``worldgen/processor_list`` resolve.

Every block id a processor names (``input_predicate.block``, ``output_state.Name``
and the MSL equivalents) must exist in the block registry. MSL processors are
cross-checked too: spawner entity ids, vault key items and loot tables, trial
spawner configs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.project import namespaced

if TYPE_CHECKING:
    from core.context import ValidatorContext

# Entity/item NBT payloads. Vanilla NBT reuses "Name" (attribute modifiers on
# pre-1.20.5 entities, item display names) and "block" (e.g. carriedBlockState),
# so recursing into these yields strings that are not block ids.
_NBT_PAYLOAD_KEYS = {"nbt", "tag"}


def _collect_block_ids(obj: object, out: list[str]) -> None:
    """Block ids a processor JSON value names: any dict's ``Name`` (block state
    objects) and any string ``block`` key. Tag refs (``#...``) and NBT payloads
    are skipped."""
    if isinstance(obj, dict):
        name = obj.get("Name")
        if isinstance(name, str) and ":" in name and not name.startswith("#"):
            out.append(name)
        block = obj.get("block")
        if isinstance(block, str) and ":" in block and not block.startswith("#"):
            out.append(block)
        for key, value in obj.items():
            if key in _NBT_PAYLOAD_KEYS:
                continue
            _collect_block_ids(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_block_ids(item, out)


def _check_msl_references(ctx: ValidatorContext, rel, proc: dict, index: int, bad: list[str]) -> None:
    project = services(ctx).project
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
                    entity_id = namespaced(entity)
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
                item_id = namespaced(item)
                if item_id not in ctx.valid_items and item_id not in ctx.extra_ids:
                    bad.append(f"{where}: {key} {item_id!r} not in item registry")
        for key in ("loot_table", "ominous_loot_table"):
            ref = proc.get(key)
            if isinstance(ref, str) and project.resource_exists(ref, "loot_table") is False:
                bad.append(f"{where}: {key} {ref!r} has no loot table file in this project")

    elif ptype == "moogs_structures:trial_spawner_randomizing_processor":
        for key in ("normal_config", "ominous_config"):
            ref = proc.get(key)
            if isinstance(ref, str) and project.resource_exists(ref, "trial_spawner") is False:
                bad.append(f"{where}: {key} {ref!r} has no trial_spawner config file in this project")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    project = services(ctx).project
    processor_list_dir = project.processor_list_dir
    if not processor_list_dir.exists():
        return True, "no processor_list directory"

    files = project.json_files(processor_list_dir)
    if not files:
        return True, "no processor_list files"

    bad: list[str] = []
    file_count = 0

    for json_path in files:
        rel = json_path.relative_to(processor_list_dir)
        try:
            data = project.load_json(json_path)
        except Exception as e:
            print(f"  [ERROR] {rel}: {e}")
            bad.append(str(rel))
            continue

        processors = data.get("processors", [])
        if isinstance(processors, str):
            file_count += 1  # a reference such as "minecraft:empty": nothing to validate
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
