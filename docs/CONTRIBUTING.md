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

## What `ctx` carries

`ctx` is a `ValidatorContext` dataclass from `validator.py`:

| Field | Type | Contents |
|---|---|---|
| `ctx.namespace` | `str` | Mod's datapack namespace (e.g. `"mbs"`) |
| `ctx.mc_versions` | `list[str]` | Targeted MC versions (e.g. `["1.21", "1.21.1"]`) |
| `ctx.project_root` | `Path` | Root directory of the mod project |
| `ctx.extra_ids` | `set[str]` | Resolved extra-valid IDs from `validator.json` (wildcards already expanded where possible) |
| `ctx.valid_blocks` | `set[str]` | Block IDs valid for the union of all targeted versions |
| `ctx.valid_items` | `set[str]` | Item IDs valid for the union of all targeted versions |
| `ctx.valid_entities` | `set[str]` | Entity-type IDs valid for the union of all targeted versions |
| `ctx.orphan_nbts` | `set[Path]` | Resolved paths of NBT files not referenced by any template pool |
| `ctx.nbt_cache` | `dict` | Parsed NBT cache (use the helper below, do not read directly) |
| `ctx.refresh` | `bool` | Whether `--refresh` was passed |

Derive the structures directory with `utils.paths.data_dir`:

```python
from utils.paths import data_dir

namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
structure_dir = data_dir(namespace_root, "structure")  # handles singular/plural per version
```

## Available helpers

**NBT cache** (`utils/nbt_cache.py`) -- use this instead of calling `nbtlib.load` directly. Parsed NBT is cached on `ctx` after `nbt_check` runs, so subsequent checks get the in-memory compound for free:

```python
from utils.nbt_cache import load_nbt

nbt = load_nbt(ctx, nbt_path)  # returns nbtlib.Compound; raises on parse failure
```

**Version map** (`utils/versions.py`) -- fetches or reads the cached `versions.json` from `misode/mcmeta`. Returns a list of version entry dicts (fields: `id`, `data_version`, `type`, etc.):

```python
from utils.versions import load_version_map

versions = load_version_map(ctx.refresh)
```

Used by `check_entity_nbt`, `check_sign_nbt`, and `check_biome_tags` to find data-version boundaries. If your check needs to compare `DataVersion` integers against version strings, use this.

## Where to register a new check

1. Create `checks/my_check.py` with a `run(ctx)` function.
2. Open `validator.py` and find `_check_modules()`. Add an import and a tuple to the return list in the position where you want the check to run:

```python
import checks.my_check as my_check
...
return [
    ...
    ("my_check", my_check),
]
```

The check name (first element of the tuple) is what users pass to `--check` and `--skip-check`.

## Testing your check

The project has no automated test suite. Test manually:

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
- Skip orphaned NBTs: `if nbt_path.resolve() in ctx.orphan_nbts: continue`.
- Use full relative paths in messages: `nbt_path.relative_to(structure_dir)`, not `nbt_path.name`.
- Return early with `return True, "no <thing> directory"` when the relevant directory does not exist.
