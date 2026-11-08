# Format model verification

vanilla-mcdoc `1a674539af7150444db0e2fa8fc46318f91ed86b`, checked 2026-11-08 by `tools/update_format_model.py`.

Each release's own vanilla data (misode/mcmeta `<version>-data-json`), read as that release.

| Release | Files | Kinds | Unexplained | Known gaps hit |
|---|---|---|---|---|
| 1.20 | 4877 | 38 | 0 | 7 |
| 1.20.1 | 4877 | 38 | 0 | 7 |
| 1.20.2 | 4884 | 38 | 0 | 7 |
| 1.20.3 | 4956 | 38 | 0 | 7 |
| 1.20.4 | 4956 | 38 | 0 | 7 |
| 1.20.5 | 5104 | 41 | 0 | 7 |
| 1.20.6 | 5104 | 41 | 0 | 7 |
| 1.21 | 5552 | 45 | 0 | 7 |
| 1.21.1 | 5552 | 45 | 0 | 7 |
| 1.21.2 | 5771 | 47 | 0 | 5 |
| 1.21.3 | 5771 | 47 | 0 | 5 |
| 1.21.4 | 5860 | 47 | 0 | 5 |
| 1.21.5 | 5962 | 54 | 0 | 5 |
| 1.21.6 | 6048 | 56 | 0 | 5 |
| 1.21.7 | 6050 | 56 | 0 | 5 |
| 1.21.8 | 6050 | 56 | 0 | 5 |
| 1.21.9 | 6255 | 56 | 0 | 5 |
| 1.21.10 | 6255 | 56 | 0 | 5 |
| 1.21.11 | 6299 | 59 | 0 | 5 |
| 26.1 | 6977 | 69 | 0 | 15 |
| 26.1.1 | 6977 | 69 | 0 | 15 |
| 26.1.2 | 6977 | 69 | 0 | 15 |
| 26.2 | 7210 | 70 | 0 | 15 |
| 26.3 | 8269 | 78 | 0 | 16 |

Known gaps (model.json `gaps`) explained these findings:

- vanilla's ancient city wall pool names a structure file vanilla does not ship (a bug in vanilla itself): 24
- vanilla-mcdoc has no `step_sound` on wolf sound variants; vanilla 26.1 and later ships it on every one: 70
- vanilla-mcdoc leaves `category` off the special crafting recipes (armor_dye, map_cloning, ...); the game reads it on them: 94
- vanilla-mcdoc requires `result.id` on the 26.3 map_extending recipe, whose result vanilla writes without one: 1

## Fields vanilla stopped writing that the model still reads

Advisory. Each line is a field vanilla used at least three times in one release and not at all in the next, while the model says the next release still reads it. Most are content changes (vanilla stopped needing an optional field); a rename the model missed would show up here.

- 1.20.4 -> 1.20.5: `CopyNbt.ops` (37 uses before, none after; the model still reads it)
- 1.20.4 -> 1.20.5: `CopyNbt.op` (72 uses before, none after; the model still reads it)
- 1.20.4 -> 1.20.5: `CopyNbt.source` (72 uses before, none after; the model still reads it)
- 1.20.4 -> 1.20.5: `CopyNbt.target` (72 uses before, none after; the model still reads it)
- 1.20.4 -> 1.20.5: `SetContents.entries` (17 uses before, none after; the model still reads it)
- 1.20.6 -> 1.21: `RandomChanceWithLooting.looting_multiplier` (10 uses before, none after; the model still reads it)
- 1.21.4 -> 1.21.5: `DirectMultiNoise.biome` (7598 uses before, none after; the model still reads it)
- 1.21.4 -> 1.21.5: `DirectMultiNoise.parameters` (7598 uses before, none after; the model still reads it)
- 1.21.4 -> 1.21.5: `FrogPredicate.variant` (3 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `LootPool.bonus_rolls` (1465 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.components` (40 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.equipment` (19 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.flags` (30 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.movement` (3 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.movement_affected_by` (5 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.predicates` (27 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `OldEntityPredicate.vehicle` (6 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `SetEnchantments.add` (11 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `WeirdScaledSampler.input` (3 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `WeirdScaledSampler.noise` (3 uses before, none after; the model still reads it)
- 26.1.2 -> 26.2: `WeirdScaledSampler.rarity_value_mapper` (3 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `CarverDebugSettings.air_state` (3 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `CarverDebugSettings.barrier_state` (3 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `CarverDebugSettings.lava_state` (3 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `CarverDebugSettings.water_state` (3 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `NetherForestVegetationConfig.state_provider` (6 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `NetherForestVegetationConfig.spread_height` (6 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `NetherForestVegetationConfig.spread_width` (6 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `RandomOffsetModifier.xz_spread` (84 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `RandomOffsetModifier.y_spread` (84 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `ShiftedNoise.shift_x` (13 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `ShiftedNoise.shift_y` (13 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `ShiftedNoise.shift_z` (13 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `SimpleStateProvider.state` (203 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `YClampedGradient.from_y` (29 uses before, none after; the model still reads it)
- 26.2 -> 26.3: `YClampedGradient.to_y` (29 uses before, none after; the model still reads it)

## Fields vanilla started writing that the model says the release before already read

Advisory, the mirror of the list above. Each line is a field vanilla first used in one release that the model says the previous release already read. Most are new content using an old field; a field the model dates too early would show up here. Confirmed ones go in model.json `patches`.

- 1.20.6 -> 1.21: `OldEntityPredicate.equipment` (none before, 19 uses after; the model says 1.20.6 already read it)
- 1.21.11 -> 26.1: `EnchantRandomly.only_compatible` (none before, 4 uses after; the model says 1.21.11 already read it)
- 1.21.11 -> 26.1: `ExplorationMap.search_radius` (none before, 10 uses after; the model says 1.21.11 already read it)
- 1.21.11 -> 26.1: `OldEntityPredicate.predicates` (none before, 27 uses after; the model says 1.21.11 already read it)
