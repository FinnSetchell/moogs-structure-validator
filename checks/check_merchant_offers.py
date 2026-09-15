"""Merchants placed by a structure carry their trades.

A wandering trader, or a villager that already has a profession, rolls its
trades the first time anything reads them. Saved without ``Offers`` it does that
when the game first touches the entity, which before Moog's Structure Lib 3.3.1
was during world generation; a map trade rolled there searches for a structure
from a worker thread and freezes the server. Spawner-nested entities are spawned
later on the server thread and are left alone.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext

_NO_TRADES = {"minecraft:none", "minecraft:nitwit", "none", "nitwit"}


def _is_merchant(entity: dict) -> bool:
    entity_id = str(entity.get("id", ""))
    if entity_id == "minecraft:wandering_trader":
        return True
    if entity_id != "minecraft:villager":
        return False
    data = entity.get("VillagerData")
    if not isinstance(data, dict):
        return False
    return str(data.get("profession", "minecraft:none")) not in _NO_TRADES


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    store = services(ctx).structures
    warnings: list[str] = []
    merchants = 0

    if store.dir.exists():
        for nbt_path in store.checked_files():
            structure = store.try_load(nbt_path)
            if structure is None:
                continue
            rel = store.rel(nbt_path)
            for entity, path in structure.walk_entities():
                if path.startswith("blocks[") or not _is_merchant(entity):
                    continue
                merchants += 1
                if "Offers" not in entity:
                    warnings.append(
                        f"  [WARN] {rel}: {path} {entity.get('id')} has no saved trades; "
                        f"they roll on first use, which needs Moog's Structure Lib 3.3.1 or newer to stay off the world generation thread"
                    )

    for msg in warnings:
        print(msg)

    if not merchants:
        print("  no merchants placed by structures")
        return True, "no merchants"
    if not warnings:
        print(f"  {merchants} merchant(s) carry saved trades")
        return True, f"{merchants} merchants with saved trades"
    return True, f"{len(warnings)} of {merchants} merchant(s) without saved trades"
