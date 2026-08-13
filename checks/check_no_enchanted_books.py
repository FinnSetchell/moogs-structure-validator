from __future__ import annotations

from typing import TYPE_CHECKING

from utils.loot_tables import iter_enchanted_book_loot_entries
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    loot_table_dir = data_dir(namespace_root, "loot_table")

    errors: list[str] = []

    if loot_table_dir.exists():
        for json_path in sorted(loot_table_dir.rglob("*.json")):
            rel = str(json_path.relative_to(loot_table_dir))
            for entry_path, item_id in iter_enchanted_book_loot_entries(json_path):
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
