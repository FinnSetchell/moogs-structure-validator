## Done
- [x] Created PROGRESS.md, requirements.txt, and README.md scaffolding
- [x] `validator.py` — entry point: config loading, check orchestration, CLI args
- [x] `registries/fetcher.py` — multi-version registry fetch, intersection, per-version caching
- [x] Stub check modules created (all 6 checks)
- [x] `utils/paths.py` — disk-detecting path resolver with MC 1.21 rename map
- [x] `checks/nbt_check.py` — NBT readability check (ported + patched for paths)
- [x] `checks/check_data_integrity.py` — pool→NBT→worldgen→structure_set chain (ported + patched)
- [x] `checks/check_loot_tables.py` — loot table refs in NBT files (ported)
- [x] `checks/check_loot_table_schemas.py` — initial implementation (needs rewrite, reference script now available)
- [x] `checks/check_registries.py` — initial implementation (needs NBT palette check + broader item collection)

## In Progress

## Pending
- [ ] Fix `check_loot_table_schemas.py` — rewrite with resolve_refs, patch_schema, Draft4Validator, referencing.Registry retriever
- [ ] Fix `check_registries.py` — add NBT palette block check + broaden item collection to catch function+name pattern
- [ ] `schemas/patcher.py` + `schemas/msl_extensions.json` + `checks/check_worldgen_schemas.py` — schema infrastructure + worldgen validation (NEW)
- [ ] End-to-end integration test against MoogsBountifulStructures
