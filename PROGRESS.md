## v1.10.0 additions (2026-08-27)
- [x] `checks/check_registries.py` -- palette scan no longer sits behind the loot-table early return; the two halves run independently, and the DFU min-version reasoning is stated in the source
- [x] `checks/check_attribute_ids.py` -- `_ShapeBoundary` table: item attribute modifiers use the 1.20.5 boundary, entity attributes keep 1.21; the 1.21.2 prefix boundary is unchanged for both
- [x] `checks/check_block_entity_components.py` -- a `components` key on any block entity in a file floored below 1.20.5 is an ERROR, generalising the sign-only rule to every block entity. The "must carry it at 1.20.5+" direction is deliberately absent: vanilla omits the key on 4832 of 4848 block entities in its own structure files and mixes both shapes within a single file, so requiring it flags correct data
- [x] `checks/check_data_integrity.py` -- new step 5/7 `Structure -> Set`: flags any worldgen structure that no structure_set names and no MSL `replace_vanilla` preset uses as a `replacement_structure`; scans structure_sets in every namespace under `data/`
- [x] `checks/check_no_particles.py` -- policy: no `minecraft:area_effect_cloud` carrying `Particle` (pre-1.21.6) or `custom_particle` (1.21.6+)
- [x] `checks/check_sign_nbt.py` -- components-key rule removed; sign text rules kept
- [x] `tests/nbt_helpers.py` -- `stub_registries` also patches `registries.version_probe._fetch_version`

## v1.9.0 additions (2026-08-17)
- [x] `checks/check_no_enchanted_books.py` -- fails when `minecraft:enchanted_book` appears as a loot-table item entry (the "book vs enchanted_book" bug that silently drops an unenchanted book)
- [x] `utils/loot_tables.py` -- extracted a generic `iter_matching_loot_entries(json_path, predicate)` walker; `iter_spawn_egg_loot_entries` is now a thin wrapper on top; added `iter_enchanted_book_loot_entries`
- [x] MSL 3.1.0 support: three new schema types wired into `check_worldgen_schemas` (`vanilla_loot_swap_processor`, `conditional_concentric_rings`, `advanced_random_spread` `+spacing_key/+structure_id`)
- [x] `checks/check_msl_replace_vanilla.py` -- validates `data/<ns>/moogs_structures/replace_vanilla.json`: presets, `structures` block, stronghold/monument vanilla-tag hookups
- [x] `checks/check_msl_placements_and_processors.py` -- cross-refs `conditional_concentric_rings` + `vanilla_loot_swap_processor` + `advanced_random_spread` against presets, loot-table registry, container NBTs, and template-pool `processors` wiring
- [x] `utils/replace_vanilla.py` -- shared parser for `replace_vanilla.json` consumed by both MSL checks

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

## v1.8.0 additions (2026-07-05)
- [x] MSL source survey (branch 26.1.0-26.1.2; 26.2.0 confirmed identical datapack-wise) -- all 10 processors, 3 pool element types, 2 structure types, spawn counts format, structure tags
- [x] schema fixes: `size` cap 0-128, `FIXED_HEIGHT` land search direction
- [x] `checks/check_worldgen_schemas.py` -- MSL type dispatch (structures, pool elements, placements, processors); unknown moogs_structures ids flagged; local $ref inlining
- [x] `schemas/msl_processors.json` + `schemas/msl_blockstate.json` -- per-processor field schemas
- [x] `schemas/msl_enhanced_terrain_adaptation.json` -- shared across nether structure + versioned/mirroring element overrides
- [x] `checks/check_processor_rules.py` -- entity/item/loot/trial_spawner reference cross-checks; fails on findings
- [x] `checks/check_spawn_counts.py` -- msl_pieces_spawn_counts + _additions validation
- [x] `checks/check_msl_structure_tags.py` -- no_basalt / no_delta / larger_locate_search tag validation
- [x] inverted y_allowance detection
- [x] 42 new tests (94 total); clean delta on MNS2 + MVS 1.21-datapack

## v1.8.2 additions (2026-07-27)
- [x] `checks/check_attribute_ids.py` -- stop validating `attributes[i].modifiers[j].id` against the `attribute` registry; it is the modifier's own resource location, not an attribute id, and no attribute-modifier registry exists on any version
- [x] 2 regression tests (96 total); 309 false errors cleared across 6 branches, genuine errors on MNS2 (27) and MES (414) unchanged

## v1.8.3 additions (2026-07-27)
- [x] `checks/check_worldgen_schemas.py` -- MSL type validation is MC-version aware; `_MSL_TYPE_WINDOWS` (added_dv, removed_dv) gates types via `utils.versions.load_version_map` + `utils.boundaries.side_of`, the same mechanism `check_entity_equipment_shape` uses. A type is unknown only when no targeted MC version registers it
- [x] `schemas/msl_processors.json` -- added `moogs_structures:waterlogging_fix_processor` (1.20 line only; `Codec.unit`, no fields)
- [x] MSL registry survey across all nine branches: only `MoogsStructuresProcessors` differs by version (waterlogging_fix 1.20-only; trial_spawner + vault 1.21+). Structures / pool elements / placements identical everywhere
- [x] 8 new tests (104 total); MoogsSoaringStructures 1.20-datapack `check_worldgen_schemas` 1 -> 0 errors, all other sections byte-identical

## Pending
