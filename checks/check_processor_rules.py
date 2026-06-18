from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

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
            if block_id not in ctx.valid_blocks:
                bad.append(f"{rel}: {block_id!r} not in block registry")

        file_count += 1

    for msg in bad:
        print(f"  [WARN] processor rule: {msg}")

    if not bad:
        print(f"  {file_count} processor_list file(s), all block IDs valid")

    summary = (
        f"{file_count} file(s), {len(bad)} invalid block ID(s)"
        if bad
        else f"{file_count} file(s), all valid"
    )
    return True, summary
