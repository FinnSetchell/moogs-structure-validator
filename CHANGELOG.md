# changelog

## v1.8.2 -- 2026-07-27

### Fixed
- check_attribute_ids raised a false `unknown attribute id` error for every attribute modifier on every naturally-spawned mob captured into a structure. `_iter_entity_attribute_ids` descended into `attributes[i].modifiers[j].id` and validated those ids against the `attribute` registry. Since 1.21, `modifiers[].id` is not an attribute id -- it is the *modifier's own* resource location, the identity the game uses to add/remove/stack that modifier. Vanilla writes `minecraft:random_spawn_bonus` there when a mob spawns naturally (on `follow_range`), plus ids like `minecraft:leader_zombie_bonus`. None of those live in the `attribute` registry, and there is no attribute-modifier registry in any version (verified against the 1.21 / 1.21.2 / 1.21.5 / 1.21.9 / 26.2 registry summaries), so the lookup could never succeed. Modifier ids are now skipped -- they cannot be validated against anything, and the comment in the source says so. The legacy `Attributes` branch of the same function never descended into `Modifiers`; the asymmetry was the tell that this was an oversight rather than intent.

Real data that tripped it, from `mss/structure/arena/arena_3.nbt` (DataVersion 4556):

```
attributes: [
  { id: "minecraft:follow_range", base: 16.0,
    modifiers: [ { id: "minecraft:random_spawn_bonus",
                   amount: 0.0233..., operation: "add_multiplied_base" } ] },
  { id: "minecraft:movement_speed", base: 0.25 } ]
```

### Impact
309 false errors across the fleet's 1.21-datapack branches. Five branches had *only* these and were being blocked from releasing on a validator finding with no defect behind it. Counts are for `check_attribute_ids` alone, before -> after:

| branch (1.21-datapack) | before | after | |
| --- | ---: | ---: | --- |
| MoogsMineshaftsReimagined | 20 | 0 | all false |
| MoogsMissingVillages | 17 | 0 | all false |
| MoogsSoaringStructures | 28 | 0 | all false |
| MoogsTemplesReimagined | 120 | 0 | all false |
| MoogsVoyagerStructures | 96 | 0 | all false |
| MoogsNetherStructures2 | 55 | 27 | 28 false, 27 genuine and still reported |
| MoogsEndStructures | 414 | 414 | 0 false, all genuine and still reported |

Every one of the 309 suppressed errors was on a `.modifiers[...]` path; no error on any other path shape changed, and no new errors appeared. The genuine findings that remain are all the real `legacy Attributes list on a min>=1.21 target` shape errors.

### Added
- `test_attribute_modifier_id_is_not_an_attribute_id` -- a naturally-spawned zombie with a `minecraft:random_spawn_bonus` modifier must pass.
- `test_bad_attribute_id_still_fails_alongside_a_modifier` -- the same entity plus one genuinely unknown *attribute* id must still fail, with exactly one error. Guards against the over-correction of silencing the parent list along with the modifiers.

Both tests fail on v1.8.1 and pass here. Suite: 96 tests, all green.

## v1.8.1 -- 2026-07-06

### Fixed
- check_sign_nbt no longer trusts the source NBT's `DataVersion` as a signal for "what schema this file contains". Structures in Moog's mods are saved on the newest MC release and downgraded manually per-version, so the file DV routinely sits above 1.20.5 even when the palette content targets 1.20.1. The old DV floor (`if nbt.DataVersion < 3836: continue`) silently skipped these files. Now the check gates only on the mod's wired target range (`file_min_dv`) and inspects each sign block entity structurally. Detection of the new bare-string message format was also tightened: pre-1.20.5 sign messages are JSON-encoded text components (`"text"`, `{"text":"foo"}`, `[...]`), so a message is treated as bare only when it fails to JSON-parse (or is the empty string). The previous heuristic (`not startswith('"')`) false-positived on `{"text":""}` style pre-1.20.5 messages once the DV floor was lifted.

### Audited (no change needed)
- check_item_format, check_entity_equipment_shape, check_attribute_ids, check_entity_nbt_keys, check_entity_nbt: reviewed for the same class of bug. All already gate structural checks on the wired mod target range (`file_min_dv`/`file_max_dv` from `_build_nbt_version_ranges`), not on the source NBT's `DataVersion`. `check_entity_nbt` uses source DV only for informational drift reporting.

### Context
- Escape that motivated this: MoogsVoyagerStructures issue #85. Three houses (`diorite_and_deepslate_house`, `mud_brick_house_1`, `prismarine_house_1`) were saved with DV 3465 (1.20.1) but contained the 1.20.5+ two-sided sign format with bare empty messages. Chunk generation crashed on 1.20.1; validator reported PASS because the DV floor skipped the files before the structural check ran.

## v1.8.0 -- 2026-07-05

MSL compatibility coverage pass. Every datapack-facing extension in MoogsStructureLib (surveyed from the 26.1.0-26.1.2 branch; 26.2.0 has no datapack-facing changes) is now inspected and validated.

### Fixed
- msl_generic_jigsaw_structure / msl_generic_nether_jigsaw_structure schemas capped `size` at 30; MSL's codec allows 0-128 (its raised piece cap). Sizes 31-128 no longer fail.
- nether jigsaw `land_search_direction` was missing the `FIXED_HEIGHT` enum value.

### Added
- check_worldgen_schemas now dispatches MSL type-specific schemas that previously existed but were never applied: structure files by `type`, template pool elements by `element_type` (recursing into list elements), structure set placements by `placement.type`, and processor list entries by `processor_type`. Unknown `moogs_structures:*` ids in any of these positions are flagged as typos.
- schemas/msl_processors.json -- field shapes, required vs optional, and value ranges for all 10 MSL processors (pillar, spawner_randomizing, trial_spawner_randomizing, vault_randomizing, equip_armor_stand, close_off_fluid_sources, remove_floating_blocks, super_gravity, flood_with_water, random_replace_with_properties), taken from the 26.1 codecs.
- schemas/msl_enhanced_terrain_adaptation.json -- kernel fields, carve/bury/none actions, padding, and the band restriction; applied on the nether jigsaw structure and as the per-element override on versioned and mirroring pool elements (schemas support local file $ref inlining now).
- check_processor_rules cross-checks MSL processor references: spawner `weighted_entities` against the entity registry, vault key items against the item registry, project-local loot table and trial_spawner config refs against the datapack, and min_spawn_delay vs max_spawn_delay. The check now FAILS on findings (was warn-only) and block ids honour `extra_ids`.
- check_spawn_counts -- new check for `msl_pieces_spawn_counts` and `msl_pieces_spawn_counts_additions` files: entry shape, the always_spawn_this_many <= never_spawn_more_than_this_many constraint MSL errors on at load, file id resolving to a structure in the project, and nbt_piece_name refs resolving to template NBTs.
- check_msl_structure_tags -- new check for `no_basalt` / `no_delta` / `larger_locate_search` tag files under data/moogs_structures; unknown tag names flagged as typos, own-namespace structure ids must resolve.
- inverted `y_allowance` ranges (max_y_allowed < min_y_allowed) on MSL structures are flagged; MSL hard-crashes at datapack load on these.

### Removed
- schemas/msl_extensions.json -- stale doc stub with the wrong `msl:` namespace that nothing loaded.

### Tests
- 42 new tests across test_worldgen_schemas.py, test_processor_rules.py, test_spawn_counts.py, test_msl_structure_tags.py. Suite total: 94.
- Verified against MoogsNetherStructures2 and MoogsVoyagerStructures `1.21-datapack`: zero new findings on known-good packs, with the dispatch exercised (52 MSL structures, 7 MSL processor lists, 84 versioned pools, 2 tag files in MNS2).

## v1.7.1 -- 2026-07-05

### Added
- check_attribute_ids -- validates entity `Attributes` (legacy) / `attributes` list plus item AttributeModifiers against the target range's attribute registry. Flags legacy list on min>=1.21 target and new list on max<1.21 target (list-shape rename); flags prefixed ids (`generic.`/`player.`/`zombie.`) on min>=1.21.2 targets and unprefixed on max<1.21.2; spans on either boundary FAIL.
- check_potion_effects -- flags potion/splash_potion/lingering_potion/tipped_arrow items and area_effect_cloud entities whose effect keys sit on the wrong side of the 1.20.5 envelope boundary (`tag.CustomPotionEffects`/`custom_potion_effects` vs `components.minecraft:potion_contents.custom_effects`), plus the 1.20.2 PascalCase-to-snake_case rename inside `tag`.

### Changed
- check_entity_nbt_keys is now range-aware: a rule's key-valid DV window must fully contain the file's `(min_dv, max_dv)` range; violations distinguish "entirely older", "entirely newer", and "spans that boundary". Also switches to iter_entities so passengers and spawner-nested entities go through the same rules.
- check_entity_nbt DataVersion drift downgraded from FAIL to INFO. MC's data fixer handles raw DV drift on load; content-focused checks flag actual schema mismatches.

### Tests
- tests/nbt_helpers.py + tests/test_fixtures_end_to_end.py -- 17 fixture-based end-to-end tests covering pass and fail cases for seven checks (equipment shape, book contents, text components, version coverage, attribute ids, potion effects, per-mob key rules). Suite total: 41.

## v1.7.0 -- 2026-07-05

### Added
- check_version_coverage -- validates that every `moogs_structures:versioned_single_pool_element` `locations` map covers every version in `mc_versions`; reports uncovered versions (FAIL, since fallback to `location` is usually the wrong format), overlapping ranges (WARN), inverted or unparseable ranges (FAIL)
- check_book_contents -- walks writable/written books in containers, lecterns, chiseled bookshelves, decorated pots, item frames, and entity hands; enforces components form on 1.20.5+ targets and JSON-string vs SNBT page encoding across the 1.21.5 boundary; flags spanning ranges as unfixable
- check_text_components -- JSON-string vs SNBT-compound text component check at the 1.21.5 boundary, covering entity CustomName, item custom_name/item_name/lore, sign front_text/back_text messages, text_display text

### Extended
- check_entity_nbt now recurses into `Passengers`, `SpawnData.entity`, and `SpawnPotentials[].data.entity` (was previously top-level entities only); adds 1.20.2 mob-effect boundary check (`ActiveEffects` vs `active_effects` + PascalCase fields + effect id validation against per-version mob_effect registry); DataVersion drift reported as INFO only (MC's data fixer handles the load; the content-focused checks flag actual schema mismatches)
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
