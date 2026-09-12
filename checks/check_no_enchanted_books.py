"""``minecraft:enchanted_book`` must not appear as a loot-table item entry.

The author almost always meant ``minecraft:book`` with ``enchant_randomly`` or
``set_enchantments``; a raw ``enchanted_book`` entry drops an unenchanted book.
Loot tables only -- a palette may legitimately place enchanted books directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.loot import iter_enchanted_book_loot_entries

if TYPE_CHECKING:
    from core.context import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    project = services(ctx).project
    loot_table_dir = project.loot_table_dir

    errors: list[str] = []
    if loot_table_dir.exists():
        for json_path in project.json_files(loot_table_dir):
            rel = str(json_path.relative_to(loot_table_dir))
            for entry_path, item_id in iter_enchanted_book_loot_entries(json_path, project.try_json(json_path)):
                errors.append(f"  [ERROR] loot_table/{rel}: {entry_path} = {item_id}")

    for msg in errors:
        print(msg)

    if not errors:
        print("  no enchanted_book entries found in loot tables")
        return True, "no enchanted_book entries in loot tables"

    print(
        "  enchanted_book as a loot item drops an unenchanted book. "
        "Use minecraft:book with enchant_randomly / set_enchantments instead."
    )
    return False, f"{len(errors)} enchanted_book entry/entries found"
