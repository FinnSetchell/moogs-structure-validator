# Contributing a new check

## Check contract

Every check is a Python module in `checks/` with one public function:

```python
def run(ctx: ValidatorContext) -> tuple[bool, str]:
    ...
```

- Return `True` if the check passed, `False` if it failed. A `False` return causes the validator to exit with code `1`.
- The `str` is a one-line summary printed after the check name in the run output (e.g. `"99 files, 0 errors"` or `"3 unknown block IDs"`).
- Print per-finding detail lines to stdout before returning. Use `[ERROR]` for failures, `[WARN]` for informational issues that do not fail the check.
- Checks that are always informational (like `check_containers`) return `True` unconditionally and use `[WARN]` lines.
- Keep every string ASCII-safe (`>=` rather than the one-character form); `tests/test_output_encoding.py` enforces it.

## What `ctx` carries

`ctx` is a `ValidatorContext` dataclass from `core/context.py`:

| Field | Type | Contents |
|---|---|---|
| `ctx.namespace` | `str` | Mod's datapack namespace (e.g. `"mbs"`) |
| `ctx.mc_versions` | `list[str]` | Targeted MC versions (e.g. `["1.21", "1.21.1"]`) |
| `ctx.project_root` | `Path` | Root directory of the mod project |
| `ctx.extra_ids` | `set[str]` | Extra valid ids from `validator.json` (exact ids and `ns:*` wildcards) |
| `ctx.valid_blocks` | `set[str]` | Block ids valid for the union of all targeted versions |
| `ctx.valid_items` | `set[str]` | Item ids valid for the union of all targeted versions |
| `ctx.valid_entities` | `set[str]` | Entity-type ids valid for the union of all targeted versions |
| `ctx.orphan_nbts` | `set[Path]` | Resolved paths of NBT files not referenced by any template pool |
| `ctx.refresh` | `bool` | Whether `--refresh` was passed |

## The services: everything read once per run

Call `services(ctx)` at the top of `run`. It returns the per-run `Services`
object, built the first time any check asks and shared by all of them:

```python
from core.context import services

def run(ctx):
    svc = services(ctx)
    project, store, reg = svc.project, svc.structures, svc.mcmeta
```

**`svc.project`** (`core/project.py`) -- the project on disk.

- `project.namespace_root`, `project.data_root`
- `project.structures_dir`, `project.loot_table_dir` -- singular or plural form, whichever exists (`data_dir(name)` for anything else; `all_data_dirs(name)` when both may coexist)
- `project.template_pool_dir`, `worldgen_structure_dir`, `structure_set_dir`, `processor_list_dir`
- `project.json_files(dir)` / `project.nbt_files(dir)` -- sorted recursive listings, computed once
- `project.load_json(path)` (raises), `project.try_json(path)` (None on failure), `project.json_or_report(path, report)` -- parsed once per file
- `project.pools()` -- every parseable template pool as `(path, data)`
- `project.resource_exists(ref, "loot_table")` -- local resource lookup (None for another namespace)

**`svc.structures`** (`core/structures.py`) -- every structure file, parsed once.

```python
for nbt_path in store.checked_files():      # non-orphans, sorted
    structure = store.try_load(nbt_path)    # or store.load(...) to see the error
    if structure is None:
        continue
    rel = store.rel(nbt_path)
```

`store.files` lists every file (orphans included -- `nbt_check` uses it).

**The parsed `Structure`** (`core/nbt.py`) -- plain Python values: compounds are
`dict`, lists `list`, strings `str`, numbers `int`/`float`. Keys keep file order.

- `structure.data_version`, `structure.root` (every top-level key except `blocks`)
- `structure.palette` (the single `palette`, or None for the `palettes` form), `structure.palette_variants`, `structure.palette_names()`
- `structure.block_entities` -- every `blocks[i]` with an `nbt` compound, as `BlockEntity(index, state, pos, nbt)`
- `structure.blocks_in_states({palette indices})` -- `(index, state, pos, nbt_or_None)` for every block of those palette entries, in file order
- `structure.walk_entities()` -- `(entity, path)` for every entity, riders and spawner-nested entities included, e.g. `entities[3].Passengers[0]` or `blocks[42].nbt.SpawnData.entity`
- `structure.entities` -- the raw top-level `entities` entries
- `structure.loot_table_refs()` -- every `LootTable` string in the file

Item slots on entities and block entities: `core/items.py` (`entity_items`,
`entity_items_for_dv`, `block_entity_items`) yields `(path, item)` pairs whose
paths point at exactly one compound.

**`svc.mcmeta`** (`core/mcmeta.py`) -- misode/mcmeta data, memoised per run.

- `reg.registry("1.21.4", "block")` -- `minecraft:` ids of one registry at one version (any key mcmeta ships: `item`, `entity_type`, `mob_effect`, `enchantment`, `attribute`, `loot_table`, `worldgen/structure`, `worldgen/template_pool`, ...)
- `reg.union("item")` -- the same over every targeted version
- `reg.version_added("block", "minecraft:copper_bulb", after="1.20.4")` -- first stable release after `after` that has the id
- `reg.vanilla_biome_tags(version)`, `reg.loader_biome_tags(...)`
- `svc.versions` -- the `VersionIndex`: `get("1.21.4") -> 4189`, `name_of(4189) -> "1.21.4"`, `dv_range(versions)`, `stable_after(version)`

Everything comes from `https://raw.githubusercontent.com/misode/mcmeta/<version>-summary/...`,
pinned per version and cached under `cache/` forever (the rolling version index
refreshes with `--refresh`). New Minecraft releases need no code change: name
them in `mc_versions` and the matching summary is fetched.

**Version ranges** -- which versions a file is wired to serve, from the template
pools (`core/ranges.py`):

```python
fr = svc.file_range(nbt_path)      # FileRange: min_version, max_version, min_dv, max_dv, wired
if not fr.resolved:                # a version the index does not know
    continue
side = side_of(fr.min_dv, fr.max_dv, DV_1_21_5)   # BoundarySide.OLD / NEW / SPANS
```

`svc.file_min_version(path)` when only the floor matters. The named boundaries
(`DV_1_20_2`, `DV_1_20_5`, `DV_1_21`, `DV_1_21_2`, `DV_1_21_5`) and `side_of`
live in `core/mcversions.py`; `tests/test_boundaries.py` checks them against the
version index.

## Where to register a new check

1. Create `checks/my_check.py` with a `run(ctx)` function.
2. Add its name to `CHECK_NAMES` in `validator.py` at the position where it should run. The name is what users pass to `--check` / `--skip-check`.

## Testing your check

```bash
py -3.13 -m pytest -q
```

Most checks are covered by fixture tests in `tests/test_fixtures_end_to_end.py`:
each builds a mini datapack in a tmp dir, writes real `.nbt` and pool JSON,
redirects the two network fetches via `tests/nbt_helpers.stub_registries`, and
asserts on the `(passed, summary)` tuple your `run` returns. Add yours there.
`stub_registries` serves whatever registry sets you hand it for every version,
plus a fixed version index (`VANILLA_VERSION_MAP`).

Then test against a real project:

```bash
# Run just your check against a real mod project
python validator/validator.py \
  --config /path/to/mod/validator.json \
  --project-root /path/to/mod \
  --check my_check

# Full run to confirm no regressions
python validator/validator.py \
  --config /path/to/mod/validator.json \
  --project-root /path/to/mod
```

MoogsSoaringStructures (MSS) and MoogsNetherStructures2 (MNS) are the reference smoke-test mods used during development. MSS is a clean baseline (all checks pass); MNS has known warnings that are expected.

## Style

- Match the existing Python style: type hints, `from __future__ import annotations`, `TYPE_CHECKING` guard for the `ValidatorContext` import.
- Go through `services(ctx)` for every file read, registry lookup and structure; never parse a file in a check.
- Use full relative paths in messages: `store.rel(nbt_path)`, not `nbt_path.name`.
- Return early with `return True, "no <thing> directory"` when the relevant directory does not exist.
- Iterate sets in sorted order wherever the order reaches the output; set order changes from one process to the next.
