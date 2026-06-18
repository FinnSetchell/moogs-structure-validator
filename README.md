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
| `check_loot_tables` | Every `LootTable` field in block-entity NBT resolves to an actual `loot_table/*.json` in the data pack. | Fails |
| `check_loot_table_schemas` | Each `loot_table/*.json` is valid against the bundled Minecraft JSON schema. | Fails |
| `check_registries` | Block and item IDs in loot tables and NBT palettes exist in the MC registries for the targeted versions. Validates palette entries against the per-file minimum version (derived from versioned pool elements). | Fails |
| `check_worldgen_schemas` | Template pool, structure, structure set, and processor list JSON files validate against bundled MC schemas. | Fails |
| `check_entity_nbt` | Entity IDs in structure NBT exist in the entity registry. Enforces the 1.20.5 item-format boundary: files targeting pre-1.20.5 must use the old item shape (`Count`), files targeting 1.20.5+ must use the new shape (`count`). | Fails |
| `check_sign_nbt` | For mods targeting pre-1.20.5: sign block-entity NBT uses the old text format (`Text1`..`Text4`), not the new components-based format. Skipped entirely when all targeted versions are 1.20.5 or later. | Fails |
| `check_biome_tags` | Biome tag references in structure JSON resolve to known vanilla or loader-namespace (`c:`, `forge:`, `neoforge:`) tags. | Warns on unrecognized loader tags; fails on missing vanilla tags |
| `check_containers` | Containers in NBT structures (chests, trapped chests, barrels, all 17 shulker box variants, dispensers, droppers) are not empty and do not have hardcoded items without a loot table. Hoppers skip the empty warning (they fill from the world); dispensers and droppers skip the hardcoded-items warning (hardcoded contents are intentional). Orphaned NBT files are excluded. *(expanded in v1.5.0)* | Warn only |
| `check_jigsaw_pools` | Every jigsaw block's `pool` field in non-orphaned NBT files references a real template pool. `minecraft:*` refs are always valid; own-namespace refs must have a matching `.json` in `worldgen/template_pool/`; any other namespace warns. *(new in v1.5.0)* | Warn only |
| `check_processor_rules` | Block IDs in `worldgen/processor_list/*.json` exist in the block registry for the targeted versions. Handles both vanilla (`input_predicate.block`, `output_state.Name`) and MSL custom processor formats by recursively collecting `Name`-keyed and `block`-keyed values. Tag refs (`#...`) are skipped. *(new in v1.5.0)* | Warn only |

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
