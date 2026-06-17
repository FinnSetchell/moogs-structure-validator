# changelog

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
