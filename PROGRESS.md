## Done
- [x] Created PROGRESS.md, requirements.txt, and README.md scaffolding
- [x] `validator.py` — entry point: config loading, check orchestration, CLI args
- [x] `registries/fetcher.py` — multi-version registry fetch, intersection, per-version caching
- [x] Stub check modules created (all 6 checks)

## In Progress

## Pending
- [ ] `utils/paths.py` — disk-detecting path resolver + MC 1.21 rename map; patch nbt_check + check_data_integrity to use it
- [ ] `checks/check_loot_tables.py` — loot table refs in NBT files (port)
- [ ] `checks/check_loot_table_schemas.py` — loot table JSON vs MC schema (port)
- [ ] `checks/check_registries.py` — item/block names vs MC registries (port)
- [ ] `checks/check_worldgen_schemas.py` — worldgen JSON vs MC schemas (NEW)
- [ ] `schemas/patcher.py` — patches upstream schemas for MC version + MSL
- [ ] `schemas/msl_extensions.json` — MSL schema additions
- [ ] End-to-end integration test against MoogsBountifulStructures
