# Minecraft structure NBT format reference

Scope: Java Edition, 1.20 and later. This document is the implementation
reference for the `moogs-structure-validator` NBT checks. The primary source
of truth is `misode/mcmeta`, which ships data per version on git tags. The
validator must be able to verify any structure NBT file against any
Minecraft version in scope, dynamically, by fetching the matching mcmeta
tag at runtime. The Minecraft Wiki and deepslate's TypeScript types are
used as secondary references for plain language spec text and for parser
behaviour. If you change a rule in the validator, update the matching
section here first.

Verification target: every Minecraft Java release from 1.20 (DataVersion 3463)
through the current latest. Older versions are out of scope. Snapshots and
prereleases are not in scope but their tags exist in mcmeta and the same
URL patterns work if needed.

A note on terminology: "structure NBT" means the binary `.nbt` file shipped in
a data pack at `data/<namespace>/structure/<path>.nbt` (1.21 and later) or
`data/<namespace>/structures/<path>.nbt` (1.20.x). That file is the input to
a jigsaw or structure block at world generation time. It is not the same
thing as the JSON wrapper at `data/<namespace>/worldgen/structure/...` (that
file is already covered by `schemas/structure.json`).

## 1. Sources

### 1.1 Primary: misode/mcmeta (data per version)

`misode/mcmeta` exposes Mojang's data through git tags following the scheme
`<version>-<flavor>`. There are nine flavors per version. Four are relevant
here:

| Flavor | Contents | Use |
|---|---|---|
| `data` | Full vanilla data pack including binary `.nbt` files. | Vanilla structure files for cross reference. |
| `data-json` | JSON files only from the data pack. | Vanilla `worldgen/template_pool/*.json`, etc. Strips `.nbt`. |
| `registries` | Flat JSON arrays of resource IDs per registry. | "Does this block ID exist in this version" lookups. |
| `summary` | Aggregated and derived JSON, including each block's state property schema and the version index. | Property validation for palette entries. |

Tag listing endpoint: `https://api.github.com/repos/misode/mcmeta/tags?per_page=100`.
The repo has thousands of tags (every release, prerelease, release candidate,
and snapshot). The tags relevant to a 1.20+ validator include `1.20`, `1.20.1`
through `1.20.6`, `1.21` through `1.21.11`, and so on. Each version exists
with all nine flavor suffixes, e.g. `1.21.4-data-json`, `1.21.4-summary`.

The same content also exists on rolling branches `data`, `data-json`,
`registries`, `summary`, `assets`, `assets-json`, `assets-tiny`, `atlas`,
`diff`, plus `main`. Rolling branches always track the latest published
version. The validator should pin to specific version tags rather than rolling
branches so it can verify mods that target multiple versions deterministically.

Concrete URL patterns the validator should use:

```
# Block state property schema for a given version
https://raw.githubusercontent.com/misode/mcmeta/<version>-summary/blocks/data.min.json

# Flat list of block IDs for a given version
https://raw.githubusercontent.com/misode/mcmeta/<version>-registries/block/data.json

# Flat list of block_entity_type IDs for a given version
https://raw.githubusercontent.com/misode/mcmeta/<version>-registries/block_entity_type/data.json

# Flat list of entity-type IDs for a given version
https://raw.githubusercontent.com/misode/mcmeta/<version>-registries/entity_type/data.json

# Vanilla template pool JSON for a given version
https://raw.githubusercontent.com/misode/mcmeta/<version>-data-json/data/minecraft/worldgen/template_pool/<group>/<name>.json

# Vanilla structure .nbt for a given version (path differs per version, see section 2)
https://raw.githubusercontent.com/misode/mcmeta/<version>-data/data/minecraft/structure/<path>.nbt    # 1.21+
https://raw.githubusercontent.com/misode/mcmeta/<version>-data/data/minecraft/structures/<path>.nbt   # 1.20.x

# Version index: id -> data_version mapping for every released version
https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.min.json
```

The version index file is an array of objects, newest first. Each entry has
this verbatim shape (sample at `1.21.4-summary`):

```json
{
  "id": "1.21.4",
  "name": "1.21.4",
  "release_target": null,
  "type": "release",
  "stable": true,
  "data_version": 4189,
  "protocol_version": 769,
  "data_pack_version": 61,
  "data_pack_version_minor": 0,
  "resource_pack_version": 46,
  "resource_pack_version_minor": 0,
  "build_time": "2024-12-03T10:09:48+00:00",
  "release_time": "2024-12-03T10:12:57+00:00",
  "sha1": "828f15370612cf3bc9d10f0c7cd38464f8ef76a1"
}
```

Schema for `summary/blocks/data.min.json`: keys are bare block IDs without
the `minecraft:` prefix; each value is a two element array
`[propertiesObject, defaultsObject]`. `propertiesObject` maps each property
name to an array of allowed string values. `defaultsObject` maps each
property name to its default string value. Verbatim entry for `oak_stairs`
at `1.21.4-summary`:

```json
[
  {
    "facing": ["north", "south", "west", "east"],
    "half": ["top", "bottom"],
    "shape": ["straight", "inner_left", "inner_right", "outer_left", "outer_right"],
    "waterlogged": ["true", "false"]
  },
  {
    "facing": "north",
    "half": "bottom",
    "shape": "straight",
    "waterlogged": "false"
  }
]
```

Schema for the registry files (`<version>-registries/<registry>/data.json`):
flat JSON array of bare resource IDs. Example, `1.21.4-registries/block_entity_type/data.json`
contains 45 entries starting `["banner", "barrel", "beacon", "bed", "beehive",
"bell", "blast_furnace", "brewing_stand", ...]`.

Mcmeta gap, important: there is no file in mcmeta that maps each block ID to
"does this block carry a block entity". The `block_entity_type` registry
lists block entity types, not the blocks that use them. The validator must
maintain its own mapping from block ID to whether that block has a block
entity (see section 14).

### 1.2 Secondary: Minecraft Wiki

Plain language descriptions of NBT shape and field semantics. Citation tags
used in this doc:

| Tag | Page |
|---|---|
| MW | https://minecraft.wiki/w/Structure_file#NBT_structure |
| SB | https://minecraft.wiki/w/Structure_Block#Block_data |
| JB | https://minecraft.wiki/w/Jigsaw_Block#Block_data |
| TP | https://minecraft.wiki/w/Template_pool |
| NBT | https://minecraft.wiki/w/NBT_format |
| DV | https://minecraft.wiki/w/Data_version |

The wiki is a useful prose source but it is not authoritative for any field
that has a concrete representation in mcmeta. When wiki and mcmeta disagree,
mcmeta wins.

### 1.3 Secondary: deepslate (parser behaviour)

`misode/deepslate` is a TypeScript library that reads structure NBT for
rendering and editing. Its source is the closest thing to a reference
parser. Citation tags:

| Tag | Path |
|---|---|
| DS/Structure | https://github.com/misode/deepslate/blob/main/src/core/Structure.ts |
| DS/BlockState | https://github.com/misode/deepslate/blob/main/src/core/BlockState.ts |
| DS/BlockPos | https://github.com/misode/deepslate/blob/main/src/core/BlockPos.ts |
| DS/NbtFile | https://github.com/misode/deepslate/blob/main/src/nbt/NbtFile.ts |

Note on deepslate paths: structure related types live under `src/core/`, not
`src/structure/`. deepslate's `Structure.fromNbt` only parses `size`,
`palette`, and `blocks` (DS/Structure, the `fromNbt` static method). It does
not parse `palettes`, `entities`, `DataVersion`, or `author`. That is a
deepslate gap, not a spec gap; the validator must check all six.

## 2. File location, encoding, compression

The folder name depends on the Minecraft version:

| MC range | Folder | Verified against |
|---|---|---|
| 1.20.x (DataVersion 3463 to 3839) | `data/<namespace>/structures/` | Tag `1.20.1-data` lists `data/minecraft/structures/` |
| 1.21+ (DataVersion 3953 and up) | `data/<namespace>/structure/` | Tag `1.21.4-data` lists `data/minecraft/structure/` |

The rename happened in the 1.21 cycle (snapshot 24w21a renamed the registry
folder). A 1.20.x data pack with `structure/` will not have its files
discovered, and a 1.21+ data pack with `structures/` likewise. The validator
needs to branch on `mc_versions` to know which folder to scan.

Saved world structure exports (from a structure block in SAVE mode) still go
to `<world>/generated/<namespace>/structures/` (plural). That path is not the
validator's concern.

The file is gzipped NBT in big endian byte order. The first two bytes of any
valid file are `0x1F 0x8B` (gzip magic). After decompression the stream is a
single named root tag, which is a `TAG_Compound` (NBT, "Binary format";
DS/NbtFile lines covering `hasGzipHeader` and `readNamedTag`).

Bedrock structure files use a different layout (8 byte header, little
endian). The validator only needs to handle Java; if a file has no gzip
header and no zlib header it should be flagged as malformed rather than
attempting Bedrock parsing (DS/NbtFile, the `read` method's autodetect
chain).

## 3. Root tag layout

Every entry below cites MW unless noted. Whether a key is required reflects
what the game actually loads and what real vanilla files contain (see
MM/data samples).

| Key | Type | Required | Notes |
|---|---|---|---|
| `DataVersion` | TAG_Int | yes (>= 1.11) | See section 9. |
| `size` | TAG_List of 3 TAG_Int | yes | See section 4. |
| `palette` | TAG_List of TAG_Compound | one of palette / palettes | Section 5. |
| `palettes` | TAG_List of TAG_List | one of palette / palettes | Section 5.2. |
| `blocks` | TAG_List of TAG_Compound | yes | Section 6. May be empty. |
| `entities` | TAG_List of TAG_Compound | yes | Section 7. May be empty. |
| `author` | TAG_String | deprecated | Pre 1.13 only. Vanilla used `"?"`. |
| `version` | TAG_Int | obsolete | Pre 1.11 only. Always `1`. Removed. |

`MCVERSION` is not part of the structure NBT root. If a tool emits it, treat
it as a nonstandard extension and warn (no MW citation, because no spec
mentions it).

deepslate's `Structure.fromNbt` only parses `size`, `palette`, and `blocks`
(DS/Structure, the `fromNbt` static method). It does not parse `palettes`,
`entities`, `DataVersion`, or `author`. That is a deepslate gap, not a spec
gap. The validator must check all six fields even though deepslate ignores
four of them.

## 4. `size`

A `TAG_List` of exactly three `TAG_Int` values: `[sizeX, sizeY, sizeZ]`. The
list element type must be `TAG_Int`. A `TAG_Int_Array` is not accepted by the
game (MW; DS/BlockPos, `BlockPos.fromNbt` calls `getAsTuple(3, ...)` on a
list and only accepts int entries).

Constraints:

* Each axis must be a non negative int. The wiki does not give an explicit
  upper bound. The structure block UI caps each axis at 48 (SB), so saved
  vanilla files never exceed 48x48x48. Mod authored files commonly go
  higher. The validator should warn above 256 and fail hard above some
  reasonable ceiling (suggested: 4096) to catch garbage from integer
  overflow.
* `sizeX * sizeY * sizeZ` must fit in a signed 32 bit int. Values where the
  product overflows are a known crash class.

## 5. Palettes

### 5.1 `palette` (single)

A `TAG_List` of `TAG_Compound`. Each compound is one block state:

```
TAG_Compound
  Name        TAG_String     resource location, e.g. "minecraft:oak_planks"
  Properties  TAG_Compound   optional; only present when the block has state props
    <prop>    TAG_String     each value stored as a string
```

Citations: MW for shape; DS/BlockState `fromNbt` for the parser, which calls
`Identifier.parse` on `Name` and reads `Properties` as a string to string
map.

`Name` rules:

* Lowercase resource location: `[a-z0-9_.-]+:[a-z0-9_./-]+`. The namespace
  defaults to `minecraft` when the colon is omitted (DS/BlockState, parses
  via `Identifier.parse`).
* Must reference an actual block in the registries for the target
  `DataVersion`. The existing `check_registries.py` already covers this.

`Properties` rules:

* The compound, when present, may be empty or contain any subset of the
  block's state properties. The game does not require every property; the
  unspecified ones default to whatever the block defines. (MW.)
* Every property value is a `TAG_String`, even for booleans and integers.
  A boolean `true` must be `"true"`, not `1b`. (MW; DS/BlockState `fromNbt`
  calls `getAsString` on every value.)
* Property keys and values must match the block's actual state declaration
  in the target version. The canonical machine readable source is mcmeta's
  `<version>-summary/blocks/data.min.json`. Each block is keyed by its bare
  ID (no `minecraft:` prefix). The value is a two element array
  `[propertiesObject, defaultsObject]`, where `propertiesObject` maps each
  property name to an array of allowed string values, and
  `defaultsObject` gives the default for each property. See section 1.1 for
  the verbatim shape. The validator should fetch this file at the version
  pinned by `DataVersion`, then check each palette entry's `Properties`
  against the listed property keys and allowed value sets. This catches
  typos like `facing=norht`, invalid combinations like `type=double` on a
  block that does not have `type`, and silent default fallbacks.

Palette entries are identified by index. Two entries with the same `Name`
and the same `Properties` are typically deduplicated by the saving tool
(DS/Structure, `addBlock` does this), but duplicates are not actually
illegal; the game will read them.

### 5.2 `palettes` (multiple)

A `TAG_List` whose element type is itself `TAG_List` (NBT type 9 nested). Each
inner list has the exact shape of section 5.1. At placement time the game
picks one inner palette at random based on coordinates. Vanilla shipwrecks
use this to swap between intact and broken variants. (MW.)

Constraints:

* Each inner palette must have the same length, because every `block.state`
  is a single index that must resolve in every palette (MW; this is implied
  by the game using one `state` value across all variants). A mismatched
  count is a crash class.
* Exactly one of `palette` or `palettes` must be present. Both at once is a
  spec violation; neither is a hard error (the game will fail to load the
  structure with no useful blocks).

## 6. `blocks`

A `TAG_List` of `TAG_Compound`. Each entry:

```
TAG_Compound
  state  TAG_Int                       0-based index into the chosen palette
  pos    TAG_List of 3 TAG_Int         [x, y, z], structure local coords
  nbt    TAG_Compound (optional)       block entity NBT; only present
                                       when the block in question has one
```

Citations: MW; DS/Structure `fromNbt` reads `pos`, `state`, `nbt` and
treats an empty compound for `nbt` as absent.

Rules:

* `state` must be a valid index into the active palette: `0 <= state <
  palette.length`. With `palettes`, all variant palettes share the same
  length, so the same bound applies. A palette index out of bounds is a
  crash class (DS/Structure `toPlacedBlock` throws on this case).
* `pos` must lie inside the size box: `0 <= pos[i] < size[i]` on every axis.
  A position outside the box is a crash class (DS/Structure constructor
  throws on this; the game refuses to load).
* `pos` element type must be `TAG_Int`. Doubles or longs are a hard error.
* `nbt` is present iff the block at `palette[state].Name` has a block
  entity in the target version. The list of block entity owners is the
  `block_entity_type` registry. The validator can derive the required set
  from `MM/registries` (the blocks index in mcmeta gives this implicitly).
* When `nbt` is present, it must not contain `x`, `y`, or `z` keys. The
  game injects those at placement time using the structure's world origin
  plus the entry's `pos`. Authoring tools sometimes leave them in; this is a
  known cause of duplicated tile entities or silent overwrites (MW
  explicitly says "Does not contain x, y, or z fields").
* `nbt` must include the `id` field naming the block entity type when the
  block requires it (e.g. a chest's `nbt` needs `id: "minecraft:chest"`).
  Modern versions are lenient and synthesize this from the block, but
  tools that edit by hand should always include it. (MW, "Block entity
  format", general rule applied here.)
* The order of entries in `blocks` does matter for one specific case:
  blocks at higher `pos.y` should follow blocks at lower `pos.y` so that
  block updates during placement do not knock supported blocks off
  unsupported parents. The game itself does a stable update pass after
  placement, so this is a rendering or generation hygiene rule, not a validity
  rule, but malformed orderings can produce duplicate items in chests
  (MW, the "Notes" subsection on the Structure_file page).

## 7. `entities`

A `TAG_List` of `TAG_Compound`. Each entry:

```
TAG_Compound
  pos       TAG_List of 3 TAG_Double   precise position, may be sub block
  blockPos  TAG_List of 3 TAG_Int      block aligned position the entity
                                       sits in (for chunk loading purposes)
  nbt       TAG_Compound  (required)   full entity NBT, including `id`
```

Citations: MW.

Rules:

* `pos` is doubles, `blockPos` is ints. Mixing the types is a hard error.
* `nbt.id` must be a known entity ID for the target `DataVersion`. The list
  is the `entity_type` registry (MM/registries gives this).
* `pos` and `blockPos` should agree: `floor(pos[i]) == blockPos[i]` for
  each axis. A mismatch is not always rejected by the game, but it
  desynchronises chunk loading hints and is a known cause of "ghost"
  entities (no MW citation; this is implementation behaviour, validator
  should warn).
* `pos` should generally lie within the size box; the game tolerates
  entities outside the box (e.g. minecart trails for cinematics) but a
  validator probably wants to warn.

deepslate does not parse `entities` at all (DS/Structure, no reference to
`entities` in the source). The validator cannot rely on deepslate's
silence as a signal of validity here.

## 8. Block entity NBT for blocks the validator cares about

For most blocks that carry a block entity (chest, furnace, sign, etc.) the
content of `blocks[i].nbt` is the standard block entity format documented
on the wiki under "Block entity format". The validator's nbt loot check
already covers chest contents. The two cases worth pinning down because
they directly drive jigsaw generation are structure blocks and jigsaw
blocks.

### 8.1 Structure block (`minecraft:structure_block`)

Inherits the common block entity tags plus (SB):

| Field | Type | Notes |
|---|---|---|
| `name` | TAG_String | Structure resource location. |
| `author` | TAG_String | Local to this block entity. Not the same as the deprecated root `author`. Vanilla uses `"?"`. |
| `metadata` | TAG_String | Function name when in DATA mode; empty otherwise. |
| `mode` | TAG_String | Enum: `SAVE`, `LOAD`, `CORNER`, `DATA`. |
| `posX`, `posY`, `posZ` | TAG_Int | Origin offset relative to the structure block. |
| `sizeX`, `sizeY`, `sizeZ` | TAG_Int | Bounding box dimensions for SAVE mode. |
| `rotation` | TAG_String | Enum: `NONE`, `CLOCKWISE_90`, `CLOCKWISE_180`, `COUNTERCLOCKWISE_90`. |
| `mirror` | TAG_String | Enum: `NONE`, `LEFT_RIGHT`, `FRONT_BACK`. |
| `ignoreEntities` | TAG_Byte (boolean) | 0 or 1. |
| `powered` | TAG_Byte (boolean) | 0 or 1. |
| `showboundingbox` | TAG_Byte (boolean) | 0 or 1. |
| `integrity` | TAG_Float | 0.0 to 1.0, fraction of blocks placed in LOAD mode. |
| `seed` | TAG_Long | Integrity seed. 0 means random per placement. |

In DATA mode, allowed `metadata` values are vanilla specific marker strings
(e.g. `chest`, `Sentry`, `Elytra`, `ChestSouth`, `Mage`, `treasure_chest`).
A modded structure can use any string; the validator should not whitelist.

Common malformed cases:

* `mode` outside the four enum strings. The game throws and refuses to
  load (SB).
* `integrity` outside `[0.0, 1.0]`. Silently clamped, but the validator
  should warn because authors often use the wrong range (e.g. 0..100).
* `mirror` or `rotation` lowercase. Java Edition uses uppercase enum
  values. Bedrock differs.

### 8.2 Jigsaw block (`minecraft:jigsaw`)

Inherits the common block entity tags plus (JB):

| Field | Type | Notes |
|---|---|---|
| `name` | TAG_String | Resource location. The "name" of this jigsaw. Other jigsaws connect to it via their `target`. Default `minecraft:empty`. |
| `target` | TAG_String | Resource location. The `name` of the matching jigsaw on the next piece. Default `minecraft:empty`. |
| `pool` | TAG_String | Resource location of the next template pool to draw from. Required for any jigsaw that should expand. |
| `final_state` | TAG_String | Block state string this block becomes after generation. Default `minecraft:air`. |
| `joint` | TAG_String | Enum: `rollable` or `aligned`. Only meaningful when the block faces up or down. |
| `selection_priority` | TAG_Int | Higher tries first when picking which jigsaw in the current piece to expand. |
| `placement_priority` | TAG_Int | Higher causes the resulting child to expand its own jigsaws sooner. |

Block state property: `orientation` (TAG_String inside the block state
properties, not inside the block entity NBT). Allowed values: `down_east`,
`down_north`, `down_south`, `down_west`, `east_up`, `north_up` (default),
`south_up`, `up_east`, `up_north`, `up_south`, `up_west`, `west_up` (JB).

Validator rules specifically aimed at the crash classes Finn has been
hitting:

* `pool` is a resource location and must reference a real
  `worldgen/template_pool` JSON in the same data pack or in vanilla. A
  pool that does not exist causes the structure to silently fail to
  generate, then crash on save in some versions (JB; MM/data-json shows
  every vanilla pool present at `data/minecraft/worldgen/template_pool/`).
* `target` should match a `name` that some other jigsaw in the referenced
  pool actually emits. The default `minecraft:empty` is fine for terminal
  jigsaws. A typo in `target` is silent at load time but produces empty
  branches at generation.
* `final_state` is parsed as a block state string, e.g.
  `minecraft:smooth_stone_slab[type=top,waterlogged=false]`. A malformed
  block state here is a crash class. The parser is the same one used for
  `/setblock`, so the validator can reuse the block state grammar from
  `BlockState.parse` (DS/BlockState, the `parse` static method).
* `final_state` cannot be `minecraft:jigsaw`. The game does not allow a
  jigsaw to become another jigsaw; that produces infinite expansion.
* `joint` must be exactly `rollable` or `aligned`. Lowercase. Anything
  else fails the codec.
* `selection_priority` and `placement_priority` are both `TAG_Int` and
  default to 0 if absent. They were both promoted to `TAG_Int` in 1.20.
  Pre-1.20 files only had `selection_priority` (no
  `placement_priority`). For DataVersion < 3463, presence of
  `placement_priority` should warn, not fail (DV; JB).
* `orientation` (block state prop) outside the 12 allowed strings is a
  hard error. A common mistake when editing by hand is writing `north`
  instead of `north_up`.

## 9. DataVersion handling

`DataVersion` is the saving game's data version, a monotonically increasing
int. The authoritative source for the full table is mcmeta's version index
at `https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.min.json`
(see section 1.1 for shape). The validator should fetch this once at startup
and cache the `id -> data_version` mapping for every release.

Reference values for the 1.20+ scope, for quick orientation:

| Java release | DataVersion |
|---|---|
| 1.21.4 | 4189 |
| 1.21.3 | 4082 |
| 1.21.2 | 4080 |
| 1.21.1 | 3955 |
| 1.21 | 3953 |
| 1.20.6 | 3839 |
| 1.20.5 | 3837 |
| 1.20.4 | 3700 |
| 1.20.3 | 3698 |
| 1.20.2 | 3578 |
| 1.20.1 | 3465 |
| 1.20 | 3463 |

These numbers are duplicated here for human reference only. The validator
must read them from the mcmeta version index, not hard code them, so it
picks up new releases automatically.

The validator should:

* Require `DataVersion` to be present and an int.
* Resolve the file's `DataVersion` to a Mojang version ID via the mcmeta
  version index. If no exact match exists (e.g. a snapshot data version),
  fall back to the highest stable release with a `data_version <=` the
  file's value.
* Fail if the resolved ID is below the lowest version in the project
  config's `mc_versions`. A 1.16 structure inside a 1.21 mod will load
  but silently lose unmapped blocks.
* Fail if the resolved ID is above the highest version in `mc_versions`.
  A 1.21.4 structure in a 1.21 mod refuses to load on 1.21.0; the game
  compares `DataVersion` against `SharedConstants.WORLD_VERSION` on load.
* When the mod targets a span (e.g. 1.21 to 1.21.4), allow any value in
  the closed interval and warn outside it.
* For each version in `mc_versions`, fetch the matching mcmeta tag's
  blocks schema (`<version>-summary/blocks/data.min.json`) and registry
  files (`<version>-registries/<reg>/data.json`) so palette validation,
  registry checks, and checks for whether a block entity is required can
  run against the correct version's data.

Version specific shape differences relevant to validation:

* `placement_priority` on jigsaw block entities arrived in 1.20
  (DataVersion 3463). For files claiming DataVersion < 3463, presence of
  `placement_priority` should warn. (JB; mcmeta version index.)
* The data pack folder for structures is `structures/` on 1.20.x and
  `structure/` from