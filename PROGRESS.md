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
- [x] `schemas/msl_extensions.json` — MSL element type documentation
- [x] `schemas/patcher.py` — apply_msl hook for template pool schema
- [x] Integration test: `validator.json` and `validate.bat` added to MoogsBountifulStructures for local testing; version compatibility issues resolved

## In Progress

## Pending
- [ ] Update MBS `release.yml` to use moogs-structure-validator instead of local scripts
- [ ] Fix `validator.json` in MBS: `msl` should be `false` (MBS uses no MSL element types)
- [ ] Tag a `v1` release on moogs-structure-validator once release workflow is wired up
- [ ] Extend `check_registries._collect_ids` with additional item locations (set_contents, give_item, etc.) as further gaps surface
