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

## Pending
- [ ] Extend `check_registries._collect_ids` with additional item locations (set_contents, give_item, etc.) as further gaps surface during real releases
