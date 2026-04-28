# moogs-structure-validator

A shared Python validation tool for Finn's Minecraft structure mods. Catches data integrity problems before a release goes out: broken file references, invalid MC item/block names, malformed JSON, orphaned NBT files, and more.

---

## Per-project config (`validator.json`)

Place this file at the root of each mod project:

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

`@allowed_ids.json` is a flat JSON array of strings (can include wildcards) at the project root.

---

## Usage

```
python validator/validator.py --config project/validator.json --project-root project [--refresh]
```

- `--refresh` forces a re-fetch of cached registries

Exits with code `0` on success, `1` if any check fails.

---

## GitHub Actions integration

Add these steps to your mod's `release.yml`:

```yaml
- uses: actions/checkout@v4
  with: { path: project }

- uses: actions/checkout@v4
  with:
    repository: FinnSetchell/moogs-structure-validator
    ref: v1
    path: validator

- name: Install dependencies
  run: pip install -r validator/requirements.txt

- name: Run validator
  run: python validator/validator.py --config project/validator.json --project-root project
```

---

## Checks performed

| Check | Description |
|---|---|
| `check_data_integrity` | Validates the pool→NBT→worldgen→structure_set reference chain |
| `check_loot_tables` | Verifies loot table references in NBT files resolve to real files |
| `check_loot_table_schemas` | Validates loot table JSON against MC JSON schemas |
| `check_registries` | Validates item/block IDs against MC registries for all targeted versions |
| `check_worldgen_schemas` | Validates worldgen JSON (template pools, structures, structure sets, processor lists) against MC schemas |
| `nbt_check` | Verifies all NBT files are readable |
