# changelog

## v1.6.1 — 2026-06-21

### Added
- mc 26.2 support (DV 4903, pack format 88.0, released 2026-06-16)
- biome tag map entries for NeoForge and Fabric across all 26.x versions (26.1 / 26.1.1 / 26.1.2 / 26.2); loader biome tag check now active for 26.x targets

## v1.6.0 — 2026-06-20

### Added
- check_item_format - flags items using legacy tag on 1.20.5+ targets or components on pre-1.20.5 targets across every entity item slot (HandItems, ArmorItems, body_armor_item, SaddleItem, Inventory, Items, item-frame Item, 1.21.5+ equipment)
- check_entity_equipment_shape - flags minecraft:* entities using ArmorItems/HandItems on DV >=4325 targets (should use equipment) or equipment compound on DV <4325 targets
- check_entity_nbt_keys - table-driven per-mob version-gated key validation; currently covers painting Motive/variant and wolf variant; extensible via registries/entity_nbt_keys.json

## v1.5.1 — 2026-06-18

### Docs
- full README rewrite covering all 13 checks + new cli flags
- merged NBT-STRUCTURE-FORMAT.md to main
- added CONTRIBUTING.md with check contract + workflow
- added VERSIONING.md codifying tag policy

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
