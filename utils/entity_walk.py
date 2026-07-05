"""Walk every entity compound in a structure NBT, including nested ones.

Nested entity sources handled:
  - top-level `entities` list (each has an `nbt` compound)
  - `Passengers` (list of entity compounds, recursive)
  - block-entity spawner: `SpawnData.entity`, `SpawnPotentials[].data.entity`
    (both nest a full entity compound, and both should be recursed into)
"""
from __future__ import annotations

from typing import Iterator

import nbtlib


SPAWNER_BLOCK_IDS = {
    "minecraft:spawner",
    "minecraft:trial_spawner",
}


def _walk_entity(
    entity_nbt: nbtlib.Compound, path: str
) -> Iterator[tuple[nbtlib.Compound, str]]:
    """Yield (entity_compound, dotted path) for `entity_nbt` and every nested rider."""
    yield entity_nbt, path
    passengers = entity_nbt.get("Passengers")
    if isinstance(passengers, list):
        for i, rider in enumerate(passengers):
            if isinstance(rider, nbtlib.Compound):
                yield from _walk_entity(rider, f"{path}.Passengers[{i}]")


def iter_entities(nbt: nbtlib.Compound) -> Iterator[tuple[nbtlib.Compound, str]]:
    """Yield (entity_compound, path) for every entity discoverable in a structure NBT.

    Path is a human-readable dotted trail like "entities[3].Passengers[0]" or
    "blocks[42].nbt.SpawnData.entity".
    """
    for i, entity_entry in enumerate(nbt.get("entities") or []):
        entity_nbt = entity_entry.get("nbt")
        if isinstance(entity_nbt, nbtlib.Compound):
            yield from _walk_entity(entity_nbt, f"entities[{i}]")

    # Spawner block entities live inside `blocks[].nbt` and hold entity compounds
    # under SpawnData.entity and SpawnPotentials[].data.entity.
    for i, block_entry in enumerate(nbt.get("blocks") or []):
        block_nbt = block_entry.get("nbt")
        if not isinstance(block_nbt, nbtlib.Compound):
            continue
        base = f"blocks[{i}].nbt"

        spawn_data = block_nbt.get("SpawnData")
        if isinstance(spawn_data, nbtlib.Compound):
            entity_nbt = spawn_data.get("entity")
            if isinstance(entity_nbt, nbtlib.Compound):
                yield from _walk_entity(entity_nbt, f"{base}.SpawnData.entity")

        potentials = block_nbt.get("SpawnPotentials")
        if isinstance(potentials, list):
            for j, potential in enumerate(potentials):
                if not isinstance(potential, nbtlib.Compound):
                    continue
                data = potential.get("data")
                if not isinstance(data, nbtlib.Compound):
                    continue
                entity_nbt = data.get("entity")
                if isinstance(entity_nbt, nbtlib.Compound):
                    yield from _walk_entity(
                        entity_nbt, f"{base}.SpawnPotentials[{j}].data.entity"
                    )
