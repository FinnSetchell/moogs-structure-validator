# moogs-structure-validator

A Python CLI tool that validates Minecraft structure mod data packs before release. It parses NBT structure files, worldgen JSON, loot tables, and biome tags, then cross-checks them against each other and against version-specific Minecraft registries fetched from `misode/mcmeta`. Used in CI on every mod release across Finn's structure mod portfolio.

---

## Install / usage

No PyPI package. Consumers clone the repo and run directly:

```bash
pip install -r validator/requirements.txt

python validator/validator.py \
  --config project/validator.json \
  --project-root project
```

Exits `0` on success, `1` if any check fails.

**All flags:**

| Flag | Description |
|---|---|
| `--config PATH` | Path to `validator.json` (required) |
| `--project-root PATH` | Root of the mod project to validate (required) |
| `--refresh` | Force re-fetch of cached registries |
| `--check NAME` | Run only the named check (can repeat) |
| `--skip-check NAME` | Skip the named check (can repeat) |
| `--json` | Emit machine-readable JSON to stdout; human output goes to stderr |

Examples:

```bash
# Run only registry and loot-table checks
python validator/validator.py --config p/validator.json --project-root p \
  --check check_registries --check check_loot_tables

# Skip sign check on a modern-only mod
python validator/validator.py --config p/validator.json --project-root p \
  --skip-check check_sign_nbt

# JSON output for CI tooling
python validator/validator.py --config p/validator.json --project-root p --json
```

---

## Configuration

Place `validator.json` at the root of each mod project:

```json
{
  "namespace": "mbs",
  "mc_versions": ["1.21", "1.21.1"],
  "extra_ids": [
    "create:copper_ingot",
    "biomesoplenty:*",
    "@allowed_ids.json"
  ]
}
```

| Field | Description |
|---|---|
| `namespace` | The mod's datapack namespace |
| `mc_versions` | Every MC version this mod targets; drives registry fetching and versioned NBT logic |
| `extra_ids` | Additional IDs to treat as valid: exact (`"create:copper_ingot"`), wildcard namespace (`"biomesoplenty:*"`), or file reference (`"@allowed_ids.json"`) |

`@allowed_ids.json` is a flat JSON array of strings (wildcards allowed) at the project root.

---

## Checks

Checks run in order. The first column is the name to use with `--check` / `--skip-check`.

| Check | What it validates | Exit behavior |
|---|---|---|
| `check_directory_names` | Data pack uses the right folder names for the target versions: singular (`structure`, `loot_table`) for 1.21+, plural for 1.20.x. Skips when `mc_versions` spans the 1.21 boundary. | Fails |
| `nbt_check` | Every `.nbt` file under the structures directory parses as valid gzipped NBT. | Fails on unreadable files |
| `check_data_integrity` | Pool-to-NBT-to-worldgen-to-structure-set reference chain: all NBT files referenced by template pools exist; all worldgen structures reference real files; structure sets reference real structures. Handles `moogs_structures:versioned_single_pool_element` pool elements. | Fails |
| `check_version_coverage` | For every `moogs_structures:versioned_single_pool_element` in a template pool, the `locations` map must cover the full `mc_versions` range and each range string must parse. Malformed or inverted ranges (`1.21.5-1.21`) fail; a version in `mc_versions` that no range covers fails. *(new in v1.7.0)* | Fails |
| `check_loot_tables` | Every `LootTable` field in block-entity NBT resolves to an actual `loot_table/*.json` in the data pack. | Fails |
| `check_loot_table_schemas` | Each `loot_table/*.json` is valid against the bundled Minecraft JSON schema. | Fails |
| `check_registries` | Block and item IDs in loot tables and NBT palettes exist in the MC registries for the targeted versions. The two halves are independent — a pack with no `loot_table` directory still has its palettes scanned. Validates palette entries against the per-file minimum version (derived from versioned pool elements); the game re-maps renamed blocks upward through DataFixerUpper on load, so the floor is the only version that can fail. | Fails |
| `check_worldgen_schemas` | Template pool, structure, structure set, and processor list JSON files validate against bundled MC + MSL schemas. Unknown `moogs_structures:*` type ids are rejected (typo catcher). MSL types with per-MC-version registration windows (e.g. `waterlogging_fix_processor` on 1.20 only, `trial_spawner_randomizing_processor` on 1.21+) are only flagged when they're dead on **every** targeted MC version. *(MSL version-gated in v1.8.3; MSL 3.1.0 types added in v1.9.0)* | Fails |
| `check_entity_nbt` | Entity IDs in structure NBT exist in the entity registry. Enforces the 1.20.5 item-format boundary: files targeting pre-1.20.5 must use the old item shape (`Count`), files targeting 1.20.5+ must use the new shape (`count`). | Fails |
| `check_sign_nbt` | For mods targeting pre-1.20.5: sign block-entity text uses the old format — `front_text` / `back_text` messages are JSON-encoded text components, not the bare strings 1.20.5+ writes. Skipped entirely when all targeted versions are 1.20.5 or later. The `components` key is not sign-specific and is checked by `check_block_entity_components`. | Fails |
| `check_block_entity_components` | The block-entity `components` key arrived at 1.20.5, and each per-version variant is written by that era's own game writer, so the rule is symmetric: a file whose minimum covered version is below 1.20.5 must not carry the key on any block entity, and a file at or above 1.20.5 must carry it on every one. Generalises a rule `check_sign_nbt` previously applied to signs only. Gated on the file's wired target range, not its stored `DataVersion`. Files produced by older tooling fail by design — the failure list is the set of projects still needing a reconversion pass, so do not add per-block exceptions to quiet it. | Fails |
| `check_text_components` | Text-component values on items and item lore across the 1.21.5 SNBT/JSON boundary. Pre-1.21.5: text components in item NBT must be a JSON object or JSON array string. 1.21.5+: they must be SNBT (bare strings or SNBT compounds), never JSON. Bare non-JSON strings never flagged (they're valid on 1.21.5+ and ambiguous before). *(new in v1.7.0)* | Fails |
| `check_biome_tags` | Biome tag references in structure JSON resolve to known vanilla or loader-namespace (`c:`, `forge:`, `neoforge:`) tags. | Warns on unrecognized loader tags; fails on missing vanilla tags |
| `check_containers` | Containers in NBT structures (chests, trapped chests, barrels, all 17 shulker box variants, dispensers, droppers) are not empty and do not have hardcoded items without a loot table. Hoppers skip the empty warning (they fill from the world); dispensers and droppers skip the hardcoded-items warning (hardcoded contents are intentional). Orphaned NBT files are excluded. *(expanded in v1.5.0)* | Warn only |
| `check_jigsaw_pools` | Every jigsaw block's `pool` field in non-orphaned NBT files references a real template pool. `minecraft:*` refs are always valid; own-namespace refs must have a matching `.json` in `worldgen/template_pool/`; any other namespace warns. *(new in v1.5.0)* | Warn only |
| `check_processor_rules` | Block IDs in `worldgen/processor_list/*.json` exist in the block registry for the targeted versions. Handles both vanilla (`input_predicate.block`, `output_state.Name`) and MSL custom processor formats by recursively collecting `Name`-keyed and `block`-keyed values. Tag refs (`#...`) are skipped, as are entity/item NBT payloads (`nbt`, `tag`) — vanilla NBT reuses `Name` for attribute modifier ids and item display names, which are not block states. Also cross-checks MSL processor references (spawner entity ids, vault key items and loot tables, trial spawner configs). *(new in v1.5.0)* | Fails |
| `check_spawn_counts` | Validates MSL's `msl_pieces_spawn_counts` and `msl_pieces_spawn_counts_additions` files (per-piece spawn caps keyed by structure id). Required `nbt_piece_name` present + resolvable; int fields are ints; `always_spawn_this_many <= never_spawn_more_than_this_many` (MSL errors at load otherwise); unknown fields flagged as likely typos. *(new in v1.8.0)* | Fails |
| `check_msl_structure_tags` | Validates MSL structure tag files under `data/moogs_structures/tags/worldgen/structure/`. MSL defines exactly three tags: `no_basalt`, `no_delta`, `larger_locate_search`. Any other tag filename does nothing (typo catcher). Structure ids in the project's own namespace must resolve to a structure JSON. *(new in v1.8.0)* | Fails |
| `check_msl_replace_vanilla` | Validates `data/<ns>/moogs_structures/replace_vanilla.json` (MSL 3.1.0+). Presets: each `id` unique + non-empty; every replacement has `vanilla_key`, a known `vanilla_structure`, and a `replacement_structure` that resolves to a real worldgen structure JSON. Structures block: `preview_url_template` (if set) contains `{structure}` and uses only supported tokens; `entries[].structure` resolves to a real structure set. Warns if a stronghold or monument replacement isn't listed in the corresponding vanilla tag (`eye_of_ender_located`, `on_ocean_explorer_maps`) — without it, eyes of ender / ocean explorer maps still find vanilla. *(new in v1.9.0)* | Fails on ERROR; WARN prints only |
| `check_msl_placements_and_processors` | Cross-refs for MSL 3.1.0+ placements and processors. `conditional_concentric_rings`: `(modid, vanilla_key)` must match a preset in this pack's `replace_vanilla.json` (else placement stays on `disabled_count` forever); warns if `enabled_count < disabled_count`; `structure_id` (if set) must resolve. `vanilla_loot_swap_processor`: same preset check; TO ids must be real vanilla loot tables; warns on FROM keys that aren't used as `LootTable` on any container in the pack; the containing processor list must be referenced by at least one `template_pool` element (an unwired swap list never fires). `advanced_random_spread`: `structure_id` (if set) must resolve and be in the owning set's `structures` list. *(new in v1.9.0)* | Fails on ERROR; WARN prints only |
| `check_item_format` | Items in entity NBT (all equipment and inventory slots: `HandItems`, `ArmorItems`, `body_armor_item`, `SaddleItem`, `ArmorItem`, `DecorItem`, `Inventory`, `Items`, item-frame `Item`, and 1.21.5+ `equipment`) must use the correct custom-data key for the file's target MC version. Pre-1.20.5: items must use `tag` not `components`. 1.20.5+: items must use `components` not `tag`. Items with no custom data are skipped. *(new in v1.6.0)* | Fails |
| `check_book_contents` | For `minecraft:writable_book` and `minecraft:written_book` items anywhere in entity NBT: page contents use the correct format for the file's target MC version. Pre-1.20.5: pages are a `tag.pages` list of raw strings. 1.20.5 to 1.21.4: pages are `components["minecraft:writable_book_content"].pages` / `written_book_content.pages` with `raw` + `filtered`. 1.21.5+: pages are SNBT under the same components. Flags stale formats on the wrong side of the boundary. *(new in v1.7.0)* | Fails |
| `check_potion_effects` | Potion item custom effects (`minecraft:potion`, `splash_potion`, `lingering_potion`, `tipped_arrow`) use the correct key + shape for the file's target MC version, across two boundaries: pre-1.20.2 `CustomPotionEffects` (list under `tag`), 1.20.2 to 1.20.4 `custom_potion_effects` (still under `tag`), 1.20.5+ `minecraft:potion_contents.custom_effects` (under `components`). *(new in v1.7.1)* | Fails |
| `check_entity_equipment_shape` | Entity equipment slot keys must match the file's target MC version. On 1.21.5+ targets (DataVersion ≥ 4325): `ArmorItems` and `HandItems` are invalid — use the `equipment` compound. On pre-1.21.5 targets: `equipment` compound is invalid — use `ArmorItems`/`HandItems`. Only validates `minecraft:*` entities. This catches the canonical armor-stand bug class (equipment authored in the wrong format for the target version). *(new in v1.6.0)* | Fails |
| `check_attribute_ids` | Attribute id shape and naming. Entity attributes: pre-1.21 an `Attributes` list of maps, 1.21+ an `attributes` list of `{id, base}`. An item stack's attribute modifiers are a separate thing on a separate boundary: `tag.AttributeModifiers` before 1.20.5, `components` → `minecraft:attribute_modifiers` from 1.20.5. Naming is a third boundary common to both — 1.21.2+ attribute ids lose their `generic.` / `player.` / `zombie.` prefixes. Only base attribute ids are validated against the `attribute` registry; modifier ids are free-form (not registry entries). *(new in v1.7.1; scope narrowed in v1.8.x)* | Fails |
| `check_entity_nbt_keys` | Per-mob version-gated key validation. Checks that version-restricted NBT keys only appear in files targeting the right MC version range. First-cut table covers: `minecraft:painting` (`Motive` is pre-1.21 only; `variant` is 1.21+ only) and `minecraft:wolf` (`variant` is 1.20.5+ only). Only `minecraft:*` entities are checked. Table lives in `registries/entity_nbt_keys.json` and can be extended without code changes. *(new in v1.6.0)* | Fails |
| `check_no_spawn_eggs` | Spawn eggs must not appear in container block-entity `Items` lists (chests, trapped chests, barrels, hoppers, dispensers, droppers, all 17 shulker box variants, decorated pots), container entity `Items` lists (chest minecarts, hopper minecarts), item frame entity `Item` slots, or loot table JSON entries with `"type": "minecraft:item"`. Any item ID matching `minecraft:*_spawn_egg` in these locations is an error. Orphaned NBT files are excluded. *(new in v1.6.1)* | Fails |
| `check_no_enchanted_books` | `minecraft:enchanted_book` must not appear as a loot-table item entry. It's a common bug where the author meant `minecraft:book` + `enchant_randomly` / `set_enchantments`; a raw `enchanted_book` entry drops an unenchanted book. Loot tables only (NBT palettes may legitimately place enchanted books directly). *(new in v1.9.0)* | Fails |
| `check_no_particles` | Policy: builds ship no particle-emitting entities. Flags any `minecraft:area_effect_cloud` carrying a particle field — `Particle` before 1.21.6, `custom_particle` from 1.21.6 — anywhere in a structure, including riders and spawner-nested entities. Not version-gated: neither spelling is wanted on any version. | Fails |

Orphaned NBTs (files on disk not referenced by any template pool) are excluded from all checks except `nbt_check`.

---

## CI integration

All mod repos use this pattern in `validate.yml` and `release.yml`. Pin to a specific version tag for reproducible CI runs:

```yaml
- uses: actions/checkout@v4
  with: { path: project }

- uses: actions/checkout@v4
  with:
    repository: FinnSetchell/moogs-structure-validator
    ref: v1.5.0        # pin to a semver tag for reproducibility
    path: validator    # or use ref: v1 for auto-updates within v1.x

- name: Install dependencies
  run: pip install -r validator/requirements.txt

- name: Run validator
  run: python validator/validator.py --config project/validator.json --project-root project
```

See [VERSIONING.md](docs/VERSIONING.md) for the full tag policy and tradeoffs between `v1` (moving) and `v1.x.x` (pinned).

---

## Development

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for how to add a new check, the check contract, and available `ctx` helpers.

---

## Versioning + stability

See [VERSIONING.md](docs/VERSIONING.md) for the tag strategy, breaking-change definition, and recommended consumer pinning.
