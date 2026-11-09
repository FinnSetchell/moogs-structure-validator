"""``minecraft:enchanted_book`` must not be handed out as loot.

An ``enchanted_book`` item given by loot is never enchanted, on any version: the
game hands out an empty enchanted book. Enchantments come from ``minecraft:book``
with ``enchant_randomly``, ``enchant_with_levels`` or ``set_enchantments``. So the
id is an error wherever loot can name the item: an item entry (in any pool, child,
inline table or ``set_contents`` list) and a ``set_item`` / ``set_contents`` /
``give_item`` function, in every loot table and item modifier of every namespace
(``data/minecraft`` overrides too), in both folder spellings and in every
``pack.mcmeta`` overlay. Palettes and structure NBT may place a real enchanted book
directly and are not read here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.formats import Pack
from core.loot import iter_enchanted_book_mentions

if TYPE_CHECKING:
    from core.context import ValidatorContext

_LOOT_FOLDERS = {"loot_table", "loot_tables", "item_modifier", "item_modifiers"}


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    project = services(ctx).project
    resources = project.data_root.parent
    roots = [project.data_root]
    roots += [resources / o.directory / "data" for o in Pack.read(resources, project.try_json).overlays]

    errors: list[str] = []
    files = 0
    for root in roots:
        if not root.exists():
            continue
        for json_path in project.json_files(root):
            parts = json_path.relative_to(root).parts
            if len(parts) < 3 or parts[1] not in _LOOT_FOLDERS:
                continue
            files += 1
            shown = json_path.relative_to(resources).as_posix()
            for where, item_id in iter_enchanted_book_mentions(project.try_json(json_path)):
                errors.append(f"  [ERROR] {shown}: {where or '(file)'} = {item_id}")

    for msg in errors:
        print(msg)

    if not errors:
        print(f"  no enchanted_book handed out by {files} loot table / item modifier file(s)")
        return True, "no enchanted_book entries in loot tables"

    print(
        "  enchanted_book handed out as loot is never enchanted, on any version. "
        "Use minecraft:book with enchant_randomly / enchant_with_levels / set_enchantments instead."
    )
    return False, f"{len(errors)} enchanted_book entry/entries found"
