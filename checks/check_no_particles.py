"""Policy: our builds ship no particle-emitting entities.

`minecraft:area_effect_cloud` is the entity that carries this risk -- it can be
captured into a structure and then emits its particle forever wherever the
structure generates. The field naming the particle was renamed at 1.21.6
(`Particle` -> `custom_particle`), so both spellings are treated the same: this
is a policy rule, not a version-format rule, and neither is wanted on any
version.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from utils.entity_walk import iter_entities
from utils.nbt_cache import load_nbt
from utils.paths import data_dir

if TYPE_CHECKING:
    from validator import ValidatorContext


_AREA_EFFECT_CLOUD = "minecraft:area_effect_cloud"

# Pre-1.21.6 and 1.21.6+ names for the same field.
_PARTICLE_FIELDS = ("Particle", "custom_particle")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structure_dir = data_dir(namespace_root, "structure")

    if not structure_dir.exists():
        return True, "no structures directory"

    errors: list[str] = []
    files_checked = 0

    for nbt_path in sorted(structure_dir.rglob("*.nbt")):
        if nbt_path.resolve() in ctx.orphan_nbts:
            continue
        try:
            nbt = load_nbt(ctx, nbt_path)
        except Exception:
            continue
        files_checked += 1
        rel = str(nbt_path.relative_to(structure_dir))

        for entity_nbt, entity_path in iter_entities(nbt):
            if str(entity_nbt.get("id", "")) != _AREA_EFFECT_CLOUD:
                continue
            for field in _PARTICLE_FIELDS:
                if field in entity_nbt:
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
