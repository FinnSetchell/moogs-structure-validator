"""Policy: our builds ship no particle-emitting entities.

``minecraft:area_effect_cloud`` is the entity that carries this risk: captured
into a structure, it emits its particle forever wherever the structure
generates. The field naming the particle was renamed at 1.21.6 (``Particle``
-> ``custom_particle``); both spellings are unwanted on every version, so this
is not version-gated.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext

_AREA_EFFECT_CLOUD = "minecraft:area_effect_cloud"
_PARTICLE_FIELDS = ("Particle", "custom_particle")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    store = services(ctx).structures
    if not store.dir.exists():
        return True, "no structures directory"

    errors: list[str] = []
    files_checked = 0

    for nbt_path in store.checked_files():
        structure = store.try_load(nbt_path)
        if structure is None:
            continue
        files_checked += 1
        rel = store.rel(nbt_path)

        for entity, entity_path in structure.walk_entities():
            if str(entity.get("id", "")) != _AREA_EFFECT_CLOUD:
                continue
            for field in _PARTICLE_FIELDS:
                if field in entity:
                    errors.append(
                        f"[ERROR] {rel}: {entity_path}: {_AREA_EFFECT_CLOUD} carries"
                        f" `{field}` -- builds must not contain particle-emitting entities"
                    )

    for msg in errors:
        print(f"  {msg}")

    if not errors:
        print(f"  {files_checked} file(s) checked -- no particle-emitting entities")
        return True, f"{files_checked} files, no particle-emitting entities"
    return False, f"{len(errors)} particle-emitting entity field(s)"
