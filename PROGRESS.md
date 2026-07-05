## Done
- [x] Created PROGRESS.md, requirements.txt, and README.md scaffolding
- [x] `validator.py` — entry point: config loading, check orchestration, CLI args; summary table output
- [x] `registries/fetcher.py` — multi-version registry fetch; switched to union (any version valid = passes); fixed data format (`data["item"]` not `"minecraft:item".entries`)
- [x] `registries/version_probe.py` — identifies which MC version first added a block ID (used for annotation in registry failure output)
- [x] `utils/paths.py` — disk-detecting path resolver with MC 1.21 rename map
- [x] `checks/nbt_check.py` — NBT readability check
- [x] `checks/check_data_integrity.py` — pool→NBT→worldgen→structure_set reference chain; MSL element type is `moogs_structures:versioned_single_pool_element`
- [x] `checks/check_loot_tables.py` — loot table refs in NBT files
- [x] `checks/check_loot_table_schemas.py` — loot table JSON vs MC schema (resolve_refs, patch_schema, Draft4Validator, referencing.Registry)
- [x] `checks/check_registries.py` — item/block IDs in loot tables + NBT palettes vs MC registries; version-aware palette checking with block-added-in annotation
- [x] `checks/check_worldgen_schemas.py` — worldgen JSON vs bundled minimal schemas
- [x] `schemas/template_pool.json`, `structure.json`, `structure_set.json`, `processor_list.json` — bundled minimal JSON schemas; template_pool accepts both `element_type` and `type` fields
- [x] `schemas/msl_*.json` — MSL element type and placement schemas
- [x] `schemas/patcher.py` — apply_msl hook always applied to template pool schema
- [x] Removed `msl` flag from config — MSL element types handled transparently
- [x] `.gitignore` — excludes `.claude/`, `scratch/`, `cache/`, `__pycache__/`
- [x] Integration test: `validator.json` and `validate.bat` in MoogsBountifulStructures for local testing
- [x] MBS `release.yml` updated to use moogs-structure-validator; publish blocked on validate
- [x] Tagged `v1` on moogs-structure-validator

## v1.7.0 additions (2026-07-05)
- [x] `utils/nbt_versions.py` extended: `_build_nbt_version_ranges` returning (min, max) per NBT; `collect_versioned_elements` for coverage inspection
- [x] `utils/boundaries.py` -- named DataVersion boundaries + `side_of` helper (OLD/NEW/SPANS)
- [x] `utils/entity_walk.py` -- iterates every entity including Passengers + spawner-nested SpawnData/SpawnPotentials
- [x] `registries/fetcher.py.fetch_registry_set` for on-demand mob_effect/enchantment sets
- [x] `checks/check_version_coverage.py` -- new coverage check
- [x] `checks/check_book_contents.py` -- new book component check
- [x] `checks/check_text_components.py` -- new JSON/SNBT text component check at 1.21.5
- [x] `checks/check_entity_nbt.py` -- adds recursion, mob-effect boundary, DataVersion FAIL on wired mismatch
- [x] `checks/check_entity_equipment_shape.py` -- full forbidden-keys set both sides + SPANS + item-id validation
- [x] `checks/check_item_format.py` -- walks block-entity items; enchantments-shape check across three eras
- [x] `checks/check_registries.py._collect_ids` -- handles set_contents / give_item

## v1.7.1 additions (2026-07-05)
- [x] `checks/check_attribute_ids.py` -- attribute id prefix check at 1.21.2; entity Attributes/attributes list shape at 1.21
- [x] `checks/check_potion_effects.py` -- CustomPotionEffects/custom_potion_effects/potion_contents.custom_effects across 1.20.2 and 1.20.5 boundaries
- [x] `checks/check_entity_nbt_keys.py` -- range-aware (min+max, not just min); uses iter_entities for recursion
- [x] `tests/nbt_helpers.py`, `tests/test_fixtures_end_to_end.py` -- fixture-based end-to-end tests (17 new, 41 total in suite)

## Pending
