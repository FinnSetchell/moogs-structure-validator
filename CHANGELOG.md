# changelog

## v1.10.0 -- 2026-08-27

### Fixed
- **`check_registries` skipped the NBT palette scan entirely on any project without a `loot_table` directory.** The check opened with an early `return True, "skipped (no loot tables)"` and the palette scan sat below it, so a pack shipping structures but no loot tables reported PASS having looked at nothing. The two halves are independent and now run that way: a missing `loot_table` directory skips only the loot-table half, and the check returns early only when neither a loot table nor a structure directory exists.

  The palette is still validated at each file's **minimum** covered version only, and the reason is now written down in the source. On load the game runs a structure through DataFixerUpper keyed on the file's own `DataVersion`, so a block renamed in a later version (`chain` -> `iron_chain`, `grass` -> `short_grass`) is re-mapped upward automatically. A palette valid at the floor is valid at every version above it -- checking every covered version would only invent errors.

- **`check_attribute_ids` judged item attribute modifiers against the 1.21 entity-attribute boundary.** An item stack's attribute modifiers are a different thing from an entity's attribute list and did not move with them. Entity `Attributes` became `attributes` at 1.21 (DV 3953); an item's modifiers travelled with the rest of item NBT a full release earlier, at 1.20.5 (DV 3837), when `tag` became `components`. `_flag()` applied DV 3953 to both, which produced errors in both directions on 1.20.5/1.20.6 targets: a correct `components` -> `minecraft:attribute_modifiers` stack was reported as a shape error, and a stale `tag.AttributeModifiers` on the same file went unreported.

  The origin ("entity" or "item") is now threaded through to `_flag()` and selects the boundary from a small table. The 1.21.2 prefix boundary (`generic.max_health` -> `max_health`) is unchanged and still applies to both, as it always did.

- **`check_processor_rules` read entity and item NBT as block states.** `_collect_block_ids` recursed into every dict and harvested any `Name` or `block` string containing a colon. That is right for block states (`output_state.Name`, `input_predicate.block`) but it also descended into `weighted_entities[].nbt` and item `tag` payloads, and vanilla NBT reuses both key names for unrelated things: `nbt.attributes[].Name` is a pre-1.20.5 attribute modifier id, `tag.display.Name` is an item display name, `nbt.carriedBlockState.Name` is an entity's carried block. The check then reported those strings as missing block IDs and failed the run.

  Only pre-1.20.5 data trips it -- from 1.21 attributes serialise as `{"id": ..., "base": ...}` with no `Name` key -- so it hit `1.20-datapack` branches only. Recursion now skips `nbt` and `tag` payloads.

  Verified on `MoogsTemplesReimagined`, which ships the same processor lists on both a 1.20 and a 1.21 branch: the 1.20 branch dropped exactly `generic.armor`, `generic.attack_damage`, `generic.max_health` and `generic.movement_speed`, the 1.21 branch was unchanged, and both branches now collect an identical set of block IDs. No true positive is lost.

### Added
- **`check_block_entity_components`** -- the `components` key on a block entity arrived at 1.20.5, and each per-version variant is emitted by that era's own game writer, so the rule is symmetric and both halves are errors, keyed on the file's minimum covered version:

  - minimum below 1.20.5 -- no block entity may carry the key;
  - minimum at or above 1.20.5 -- every block entity must carry it.

  The first half already existed inside `check_sign_nbt`, applied to signs only, so a chest or barrel carrying the key on a pre-1.20.5 file went unreported. The second half was not checked at all.

  Files written by older tooling fail the second half, and that is the intended result rather than a false positive: the converter now guarantees both directions, so the failure list names the projects that still need re-running. On the current portfolio that is 60 of 99 files on MSS. **Do not soften the check or add per-block exceptions to quiet it** -- including for the known converter-side gap on injected bed block entities, which is being fixed in the converter. An exception would hide exactly the files the check exists to find.

- **`check_no_particles`** -- policy check: builds ship no particle-emitting entities. Flags any `minecraft:area_effect_cloud` carrying a particle field, walking riders and spawner-nested entities via `iter_entities`. The field was renamed at 1.21.6, so `Particle` and `custom_particle` are treated identically; this is a policy rule rather than a version-format one and neither spelling is wanted on any version.

### Changed
- `check_sign_nbt` no longer reports the `components` key. It keeps the sign-only text-format rules (`front_text` / `back_text` messages are JSON-encoded text components before 1.20.5, bare strings after), which really are sign-specific. The components key moved to `check_block_entity_components`.
- `tests/nbt_helpers.stub_registries` also patches `registries.version_probe._fetch_version`, which binds the name at import time and so was left reaching the network when a check annotated an unknown block ID.

### Tests
- 23 new fixture tests. Full suite: 180 passed.

### Impact
`check_no_particles` is clean across `MoogsSoaringStructures`, `MoogsVoyagerStructures-1.21-datapack` and `MoogsTemplesReimagined-1.21-datapack`.

`check_block_entity_components` passes on MTR and names the reconversion queue on the other two:

```
   FAIL  check_block_entity_components   60 of 99 file(s) need reconversion     (MSS)
   FAIL  check_block_entity_components   101 of 256 file(s) need reconversion   (MVS)
   PASS  check_block_entity_components   118 files, 3213 block entities checked (MTR)
```

Those failures are the point of the check, not a regression to work around: they are the files still carrying older converter output. They clear when the projects are re-run.

## v1.9.0 -- 2026-08-17

### Added
- **`check_no_enchanted_books`** -- flags `minecraft:enchanted_book` as a loot-table item entry. This is a common authoring bug: the author writes `enchanted_book` intending to give the player an enchanted book, but enchantments on an `enchanted_book` entry are populated by `enchant_randomly` / `set_enchantments` applied to a **`minecraft:book`** stack, so the raw `enchanted_book` entry drops an unenchanted book at runtime. Walks every `loot_table/**/*.json`, recursing into `entries[]` / `children[]` (groups, alternatives). Fails the check when any entry with `"type": "minecraft:item", "name": "minecraft:enchanted_book"` is found. Loot tables only; container NBTs may legitimately place an enchanted-book item stack directly (enchantments there travel with the item stack).

- **MSL 3.1.0 support.** MSL 3.1.0 adds `moogs_structures:vanilla_loot_swap_processor`, `moogs_structures:conditional_concentric_rings` (structure placement), and two optional fields on `moogs_structures:advanced_random_spread`. The parsers are lenient (warn-and-skip on malformed data), so a broken preset silently disables the feature at runtime; this release closes that gap.

  Schemas (validated by the existing `check_worldgen_schemas`):
  - `schemas/msl_conditional_concentric_rings.json` -- required: `type`, `salt`, `distance` (0-1023), `spread` (0-1023), `preferred_biomes`, `modid`, `vanilla_key`, `enabled_count` (1-4095), `disabled_count` (0-4095). Optional: `structure_id`, `locate_offset`, `frequency_reduction_method`, `frequency`, `exclusion_zone`. Out-of-range values are hard datapack load errors in MSL, not warn-skips.
  - `moogs_structures:vanilla_loot_swap_processor` in `schemas/msl_processors.json` -- required: `processor_type`, `modid`, `vanilla_key`, `loot_table_mapping` (non-empty). Optional `seed_strategy` restricted to `{preserve, randomize, clear}`; any other value silently behaves as `preserve` in MSL, so we reject it.
  - `msl_advanced_random_spread.json` extended with the two runtime-derivable optional fields (`spacing_key`, `structure_id`).

  Two new checks that layer cross-references on top of the schema pass:

  **`check_msl_replace_vanilla`** validates `data/<ns>/moogs_structures/replace_vanilla.json`.
  - **Presets:** each `id` present, non-empty, and unique in the file (a duplicate silently overwrites the earlier preset in `PRESET_DEFAULTS`); each replacement has `vanilla_key` and `vanilla_structure` (parser skips the whole replacement otherwise -> dead preset); `vanilla_structure` is a known vanilla structure id; `replacement_structure` is present and resolves to `data/<ns>/worldgen/structure/<path>.json` (missing/typo'd -> mixin cancels vanilla but nothing replaces it); `default_enabled` is boolean.
  - **Structures block:** `preview_url_template` (if set) contains `{structure}`; only `{structure}` and `{mc_version}` are substituted (any other `{token}` is a WARN); `entries[].structure` resolves to a real `structure_set` JSON. WARN when neither `mod_slug` nor `preview_url_template` is set (preview UI disabled). WARN when the file exists but has neither `presets` nor `structures` (no effect).
  - **Vanilla tag hookups:** a preset replacing `minecraft:stronghold` must add its `replacement_structure` to `data/minecraft/tags/worldgen/structure/eye_of_ender_located.json` (or eyes of ender don't lead to it); same for `minecraft:monument` and `on_ocean_explorer_maps.json`. WARN, not ERROR: the pack still loads, gameplay is just missing the hookup.

  **`check_msl_placements_and_processors`** owns the cross-references that JSON schemas can't express.
  - **`conditional_concentric_rings`:** `(modid, vanilla_key)` must match a preset in this pack's `replace_vanilla.json` (when `modid == ctx.namespace`) -- otherwise `ReplaceVanillaManager.isEnabled` always returns false and the ring count is stuck on `disabled_count` forever. WARN when `modid` targets another mod's preset (can't verify from this pack). WARN when `enabled_count < disabled_count` (enabled is the "replacing vanilla, full density" case; the inverse is almost always wrong). `structure_id` (if set) must resolve.
  - **`vanilla_loot_swap_processor`:** the same preset match. FROM keys in `loot_table_mapping` must be used as a `LootTable` on some container in the pack's NBTs (dead FROM key silently does nothing) -- WARN. TO values must be real vanilla loot tables on at least one targeted MC version (via `fetch_registry_set(v, cache, refresh, "loot_table")`) -- ERROR. The containing `processor_list` must be referenced by at least one `template_pool` element's `processors` field -- an unwired swap list never fires -- ERROR.
  - **`advanced_random_spread`:** `structure_id` (if set) must resolve to a real structure AND be in the owning set's `structures` list (consistency with the owning set).

### Changed
- Two-tier reporting in the new MSL checks: WARN prints but doesn't fail the check; ERROR fails. Existing check semantics unchanged.

### Tests
- 46 new tests (`test_worldgen_schemas.py` +15, `test_check_no_enchanted_books.py` +7, `test_check_msl_replace_vanilla.py` +19, `test_check_msl_placements_and_processors.py` +15). Full suite: 157 passed.

### Impact
`MoogsTemplesReimagined-1.21-datapack`, which ships an MSL 3.1.0 `replace_vanilla.json` with four presets (desert / jungle / monument / stronghold), 3 `vanilla_loot_swap_processor` lists, and a `conditional_concentric_rings` placement:

```
-  FAIL  check_worldgen_schemas   38 files, 4 error(s)  (unknown MSL types)
+  PASS  check_worldgen_schemas   39 files, 0 errors
+  PASS  check_msl_replace_vanilla             4 preset(s), 4 replacement(s), all valid
+  PASS  check_msl_placements_and_processors   all MSL placement/processor cross-refs OK
-  24 passed, 1 failed
+  27 passed
```

Same clean pass on `MoogsTemplesReimagined` (`1.20-datapack`).

## v1.8.3 -- 2026-07-27

### Fixed
- check_worldgen_schemas raised a false `unknown MSL processor type` error for `moogs_structures:waterlogging_fix_processor` on every `1.20-datapack` branch. `schemas/msl_processors.json` was a single flat registry of exactly the ten processor types MSL registers at 1.21+, with no Minecraft-version awareness at all, and `_check_msl_types` flagged anything not in it. But MSL's registries are not stable across MC versions: `MoogsStructuresProcessors` registers **nine** types on the 1.20 line and **ten** from 1.21 onward, and the two sets are not nested. `waterlogging_fix_processor` is real, registered, working content on 1.20-1.20.6 -- it was dropped at 1.21, not never-existed.

Verified by diffing all four MSL modinit registries across the nine live branches (`1.20-1.20.4`, `1.20.5-1.20.6`, `1.21-1.21.1`, `1.21.2-1.21.3`, `1.21.4`, `1.21.5-1.21.10`, `1.21.11`, `26.1.0-26.1.2`, `26.2.0`):

| type | 1.20 line | 1.21+ |
| --- | :---: | :---: |
| `waterlogging_fix_processor` | yes | **no** |
| `trial_spawner_randomizing_processor` | **no** | yes |
| `vault_randomizing_processor` | **no** | yes |
| other 8 processors | yes | yes |

`MoogsStructuresStructures`, `MoogsStructuresStructurePieces` (pool elements), `MoogsStructuresPlacements` and `MoogsStructuresStructurePlacementType` are byte-for-byte identical in content on all nine branches -- the structure, element and placement schema registries had no version blindness to fix.

### Changed
- MSL type validation is now MC-version aware, reusing the mechanism the other version-sensitive checks already use (`utils.versions.load_version_map` for MC version -> DataVersion, `utils.boundaries.side_of` against a named `DV_*` constant -- the same pair `check_entity_equipment_shape` uses for its 1.21.5 boundary). No second version mechanism was introduced.
- The rule, stated in the source: **a type is reported unknown only when MSL registers it on no version the repo targets.** A branch is one artifact shipped across a whole MC range, so content that works anywhere in that range is content the author meant to write. A `1.20`-`1.20.6` branch is therefore silent about `waterlogging_fix_processor`; a `1.21`+ branch is still told about it, because there it really is dead data; a branch spanning the boundary is silent, because half its target range registers it.
- Version gating is resolved lazily and only when a version-sensitive type actually appears, and is skipped entirely when the version map is unavailable or a target version is unmapped. Both fallbacks can only under-report -- they can never invent the false positive this release removes.
- Rejected version-sensitive types now say *why* (`... was removed at 1.21; no targeted MC version registers it`) instead of the flat `unknown MSL processor type`. Genuine typos still get the original message.

### Added
- `moogs_structures:waterlogging_fix_processor` in `schemas/msl_processors.json`, gated to the 1.20 line. Field shape derived from the class, not guessed: `WaterloggingFixProcessor.CODEC` on MSL `1.20-1.20.4` is `Codec.unit(WaterloggingFixProcessor::new)`, so the processor takes **no** fields -- the only valid JSON is `{"processor_type": "moogs_structures:waterlogging_fix_processor"}`.

### Impact
`MoogsSoaringStructures` `1.20-datapack`, whose 25 template pools name `mss:waterlogging_fix_processor` as their sole `processors` value, before -> after:

```
-  FAIL  check_worldgen_schemas         162 files, 1 error(s)
+  PASS  check_worldgen_schemas         162 files, 0 errors
-  21 passed, 3 failed
+  22 passed, 2 failed
```

Every other check section is byte-identical; the two remaining failures (`check_entity_equipment_shape`, `check_attribute_ids`) are untouched. Swept every `1.20-datapack` branch in the fleet for the mirror case -- a 1.21-only type on a 1.20 target, which the new gating would newly flag -- and there is none, so this release adds no error anywhere. `MoogsVoyagerStructures-Integrated` `1.20-datapack` carries the same `waterlogging_fix_processor.json` and gains the same clearance.

### Tests
- `test_waterlogging_processor_passes_on_1_20_repo` -- accepted on a 1.20-only target.
- `test_waterlogging_processor_fails_on_1_21_repo` -- still exactly one error on a 1.21-only target.
- `test_waterlogging_processor_passes_on_repo_spanning_1_21` -- the mixed case stays silent.
- `test_trial_spawner_processor_fails_on_1_20_repo` / `test_trial_spawner_processor_passes_on_1_21_repo` -- the mirror direction.
- `test_unknown_processor_type_still_fails_on_1_20_repo` -- guards the over-correction: gating must not switch the typo catcher off.
- `test_version_gating_is_silent_without_a_version_map` / `test_version_gating_is_silent_when_a_target_version_is_unmapped` -- the permissive fallbacks.

Suite: 104 tests, all green.

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
