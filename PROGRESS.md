## Done
- [x] Created PROGRESS.md, requirements.txt, and README.md scaffolding
- [x] `validator.py` — entry point: config loading, check orchestration, CLI args
- [x] `registries/fetcher.py` — multi-version registry fetch, intersection, per-version caching
- [x] `utils/paths.py` — disk-detecting path resolver with MC 1.21 rename map
- [x] `checks/nbt_check.py` — NBT readability check
- [x] `checks/check_data_integrity.py` — pool→NBT→worldgen→structure_set reference chain
- [x] `checks/check_loot_tables.py` — loot table refs in NBT files
- [x] `checks/check_loot_table_schemas.py` — loot table JSON vs MC schema (resolve_refs, patch_schema, Draft4Validator, referencing.Registry)
- [x] `checks/check_registries.py` — item/block IDs in loot tables + NBT palettes vs MC registries
- [x] `checks/check_worldgen_schemas.py` — worldgen JSON vs bundled minimal schemas
- [x] `schemas/template_pool.json`, `structure.json`, `structure_set.json`, `processor_list.json` — bundled minimal JSON schemas
- [x] `schemas/msl_extensions.json` — MSL element type documentation
- [x] `schemas/patcher.py` — apply_msl hook for template pool schema

## In Progress

## Pending
- [ ] Add `validator.json` to MoogsBountifulStructures and run end-to-end integration test
- [ ] Wire up the GitHub Actions step in MoogsBountifulStructures `release.yml`
- [ ] Extend `check_registries._collect_ids` with additional item locations (set_contents, give_item, etc.) as gaps surface during integration testing
- [ ] Tag a `v1` release once integration test passes
