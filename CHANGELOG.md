# changelog

## v1.7.0 -- 2026-07-05

### Added
- check_version_coverage -- validates that every `moogs_structures:versioned_single_pool_element` `locations` map covers every version in `mc_versions`; reports uncovered versions (FAIL, since fallback to `location` is usually the wrong format), overlapping ranges (WARN), inverted or unparseable ranges (FAIL)
- check_book_contents -- walks writable/written books in containers, lecterns, chiseled bookshelves, decorated pots, item frames, and entity hands; enforces components form on 1.20.5+ targets and JSON-string vs SNBT page encoding across the 1.21.5 boundary; flags spanning ranges as unfixable
- check_text_components -- JSON-string vs SNBT-compound text component check at the 1.21.5 boundary, covering entity CustomName, item custom_name/item_name/lore, sign front_text/back_text messages, text_display text

### Extended
- check_entity_nbt now recurses into `Passengers`, `SpawnData.entity`, and `SpawnPotentials[].data.entity` (was previously top-level entities only); adds 1.20.2 mob-effect boundary check (`ActiveEffects` vs `active_effects` + PascalCase fields + effect id validation against per-version mob_effect registry); DataVersion consistency upgraded from WARN to FAIL when a file's DataVersion exceeds the DataVersion of its lowest wired range's minimum version
- check_entity_equipment_shape now checks the full pre-1.21.5 forbidden-keys set (`ArmorItems`, `HandItems`, `ArmorDropChances`, `HandDropChances`, `body_armor_item`, `body_armor_drop_chance`, `SaddleItem`, `Saddle`) and post-1.21.5 forbidden-keys (`equipment`, `drop_chances`, `fall_distance`); FAILs loudly on ranges that span 1.21.5; validates item ids inside every equipment slot
- check_item_format walks items in block-entity slots too (containers, lecterns, decorated pots) not just entity hands; adds enchantments shape check across the three eras (`tag.Enchantments` pre-1.20.5, `components.minecraft:enchantments` with `levels` wrapper on 1.20.5-1.21.4, unwrapped on 1.21.5+); validates enchantment ids per version registry with sweeping->sweeping_edge hint
- check_registries `_collect_ids` now also grabs item ids from `set_contents`/`give_item` function nodes

### Internal
- utils/nbt_versions.py: new `_build_nbt_version_ranges` returns (min, max) target-version pairs per NBT; adds `collect_versioned_elements` for coverage inspection; old `_build_nbt_min_versions` kept as a wrapper
- utils/boundaries.py: named DV constants (DV_1_20_2/1_20_5/1_21/1_21_2/1_21_5) plus `side_of(min_dv, max_dv, boundary)` returning OLD/NEW/SPANS
- utils/entity_walk.py: shared iterator yielding every entity in a structure NBT, including riders and spawner-nested entities
- registries/fetcher.py: `fetch_registry_set(version, cache_dir, refresh, key)` for on-demand mob_effect/enchantment registries

## v1.6.1 — 2026-06-21

### Added
- mc 26.2 support (DV 4903, pack format 88.0, released 2026-06-16)
- biome tag map entries for NeoForge and Fabric across all 26.x versions (26.1 / 26.1.1 / 26.1.2 / 26.2); loader biome tag check now active for 26.x targets
- check_no_spawn_eggs - flags spawn egg items in structure container NBT (chest/barrel/shulker/hopper/dispenser/dropper/chest_minecart/hopper_minecart/item_frame/glow_item_frame) and in loot table entries

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
