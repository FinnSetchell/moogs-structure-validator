# changelog

## v1.5.0 — 2026-06-18

### Added
- check_containers extended to cover 17 shulker box variants, hopper, dispenser, dropper
- check_jigsaw_pools -- validates jigsaw block pool references against same-datapack template_pool/
- check_processor_rules -- registry-validates block IDs inside processor list rules (handles tag refs + plain block IDs)

## v1.4.0 — 2026-06-17

### Added
- --check / --skip-check / --json cli flags
- parallel registry fetches
- per-run nbt parse cache

### Fixed
- check_entity_nbt now reports full relative path
- several checks were processing orphaned nbts; now skipped consistently

### Internal
- _load_version_map extracted to utils/versions.py (deduped across checks)
