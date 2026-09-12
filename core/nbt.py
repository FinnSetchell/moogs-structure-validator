"""Structure NBT: a parser that produces plain Python values, and the per-file
index every NBT check reads from.

Why a parser of our own
-----------------------
A structure file is almost entirely its ``blocks`` list, and that list is almost
entirely three-int positions and a palette index: across Moog's Voyager
Structures 1,268,478 block entries carry 4,339 block entities. A general NBT
library builds a typed object for every one of those ints. This parser walks the
bytes directly and keeps plain blocks in two flat ``array('i')`` buffers; only
block entities, entities and the palette become dicts.

Plain values only: TAG_Compound -> dict, TAG_List -> list, TAG_String -> str,
integer tags -> int, TAG_Float/TAG_Double -> float, the three array tags ->
``array('b' | 'i' | 'q')``. Compound keys keep file order.

``nbtlib`` stays as the fallback: if this parser rejects a file, the file is
handed to nbtlib and its result converted (or its error reported), so a file this
parser cannot read is never a file the validator cannot read.
"""
from __future__ import annotations

import gzip
import io
import struct
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

TAG_END, TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE = range(7)
TAG_BYTE_ARRAY, TAG_STRING, TAG_LIST, TAG_COMPOUND, TAG_INT_ARRAY, TAG_LONG_ARRAY = range(7, 13)

_INT = struct.Struct(">i")
_SCALARS = {
    TAG_BYTE: struct.Struct(">b"),
    TAG_SHORT: struct.Struct(">h"),
    TAG_INT: _INT,
    TAG_LONG: struct.Struct(">q"),
    TAG_FLOAT: struct.Struct(">f"),
    TAG_DOUBLE: struct.Struct(">d"),
}
_LIST_FORMATS = {TAG_BYTE: "b", TAG_SHORT: "h", TAG_INT: "i", TAG_LONG: "q", TAG_FLOAT: "f", TAG_DOUBLE: "d"}
_ARRAY_CODES = {TAG_BYTE_ARRAY: ("b", 1), TAG_INT_ARRAY: ("i", 4), TAG_LONG_ARRAY: ("q", 8)}

# The layout the game writes for a block without a block entity:
#   TAG_List "pos" of 3 ints, TAG_Int "state", TAG_End -- 36 bytes exactly.
_POS_HEADER = b"\x09\x00\x03pos\x03\x00\x00\x00\x03"
_STATE_HEADER = b"\x03\x00\x05state"
_PLAIN_BLOCK = struct.Struct(">11siii8siB")
_PLAIN_BLOCK_SIZE = _PLAIN_BLOCK.size  # 36


class NbtParseError(ValueError):
    pass


def decode_string(raw: bytes) -> str:
    """Decode a TAG_String payload.

    The game writes Java modified UTF-8: NUL as C0 80 and supplementary
    characters as surrogate pairs. Plain UTF-8 covers every real file seen so
    far, so try that first and only unpick the Java form when it fails.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        text = raw.replace(b"\xc0\x80", b"\x00").decode("utf-8", "surrogatepass")
        return text.encode("utf-16", "surrogatepass").decode("utf-16")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return raw.decode("utf-8", "replace")


@dataclass(frozen=True)
class BlockEntity:
    """A ``blocks[index]`` entry that carries an ``nbt`` compound."""
    index: int
    state: int
    pos: tuple[int, int, int] | None
    nbt: dict


class Blocks:
    """The ``blocks`` list of a structure, stored flat.

    ``states[i]`` is the palette index of block ``i`` and ``positions[3i:3i+3]``
    its x, y, z. Entries that do not fit that shape (a missing or non-int
    ``state``, a ``pos`` that is not three ints) keep their raw compound in
    ``odd`` so nothing about them is lost; ``state_of``/``pos_of`` consult it.
    """

    __slots__ = ("count", "states", "positions", "entities", "odd", "_by_state", "_entity_by_index")

    def __init__(self) -> None:
        self.count = 0
        self.states: array = array("i")
        self.positions: array = array("i")
        self.entities: list[BlockEntity] = []
        self.odd: dict[int, dict] = {}
        self._by_state: dict[int, list[int]] | None = None
        self._entity_by_index: dict[int, BlockEntity] | None = None

    def add_plain(self, x: int, y: int, z: int, state: int) -> None:
        self.states.append(state)
        self.positions.extend((x, y, z))
        self.count += 1

    def add_entry(self, entry: dict) -> None:
        """Absorb a generically parsed block compound."""
        index = self.count
        pos = entry.get("pos")
        state = entry.get("state")
        good_pos = isinstance(pos, list) and len(pos) == 3 and all(isinstance(v, int) for v in pos)
        good_state = isinstance(state, int) and not isinstance(state, bool)
        if good_pos and good_state:
            self.states.append(state)
            self.positions.extend(pos)
        else:
            # Keep the arrays aligned; the truth lives in `odd`.
            self.states.append(state if good_state else -1)
            self.positions.extend(pos if good_pos else (0, 0, 0))
            self.odd[index] = entry
        self.count += 1
        nbt = entry.get("nbt")
        if isinstance(nbt, dict):
            self.entities.append(BlockEntity(
                index,
                state if good_state else -1,
                tuple(pos) if good_pos else None,  # type: ignore[arg-type]
                nbt,
            ))

    def __len__(self) -> int:
        return self.count

    def state_of(self, index: int) -> int:
        """Palette index of block ``index``; -1 when the entry has no usable ``state``."""
        return self.states[index]

    def pos_of(self, index: int) -> tuple[int, int, int] | None:
        if index in self.odd:
            pos = self.odd[index].get("pos")
            if isinstance(pos, list):
                try:
                    return tuple(int(v) for v in pos)  # type: ignore[return-value]
                except (TypeError, ValueError):
                    return None
            return None
        base = 3 * index
        p = self.positions
        return p[base], p[base + 1], p[base + 2]

    def entity_at(self, index: int) -> BlockEntity | None:
        if self._entity_by_index is None:
            self._entity_by_index = {be.index: be for be in self.entities}
        return self._entity_by_index.get(index)

    def indices_with_states(self, wanted) -> list[int]:
        """Indices of every block whose palette index is in ``wanted``, in file order."""
        if not wanted:
            return []
        if self._by_state is None:
            by_state: dict[int, list[int]] = {}
            for i, s in enumerate(self.states):
                lst = by_state.get(s)
                if lst is None:
                    by_state[s] = [i]
                else:
                    lst.append(i)
            self._by_state = by_state
        hits = [self._by_state[s] for s in wanted if s in self._by_state]
        if not hits:
            return []
        if len(hits) == 1:
            return hits[0]
        merged = [i for lst in hits for i in lst]
        merged.sort()
        return merged


class _Parser:
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def root(self) -> tuple[dict, Blocks | None]:
        data = self.data
        if not data or data[0] != TAG_COMPOUND:
            raise NbtParseError("root tag is not a compound")
        n = (data[1] << 8) | data[2]
        off = 3 + n  # root name is discarded, as the game does
        root, blocks, off = self._compound(off, at_root=True)
        return root, blocks

    def _compound(self, off: int, at_root: bool = False) -> tuple[dict, Blocks | None, int]:
        data = self.data
        out: dict = {}
        blocks: Blocks | None = None
        try:
            while True:
                t = data[off]
                off += 1
                if t == TAG_END:
                    return out, blocks, off
                n = (data[off] << 8) | data[off + 1]
                off += 2
                name = decode_string(data[off:off + n])
                off += n
                if at_root and name == "blocks" and t == TAG_LIST and blocks is None:
                    blocks, off = self._blocks(off)
                    continue
                value, off = self._payload(t, off)
                out[name] = value
        except IndexError:
            raise NbtParseError("unexpected end of data") from None

    def _payload(self, t: int, off: int):
        data = self.data
        if t == TAG_COMPOUND:
            value, _, off = self._compound(off)
            return value, off
        if t == TAG_LIST:
            return self._list(off)
        if t == TAG_STRING:
            n = (data[off] << 8) | data[off + 1]
            off += 2
            end = off + n
            if end > len(data):
                raise NbtParseError("unexpected end of data")
            return decode_string(data[off:end]), end
        s = _SCALARS.get(t)
        if s is not None:
            try:
                return s.unpack_from(data, off)[0], off + s.size
            except struct.error:
                raise NbtParseError("unexpected end of data") from None
        arr = _ARRAY_CODES.get(t)
        if arr is not None:
            code, width = arr
            n = _INT.unpack_from(data, off)[0]
            off += 4
            if n < 0:
                raise NbtParseError("negative array length")
            end = off + n * width
            if end > len(data):
                raise NbtParseError("unexpected end of data")
            values = array(code, data[off:end])
            if width > 1 and struct.pack("=i", 1)[0] == 1:  # little-endian host
                values.byteswap()
            return values, end
        raise NbtParseError(f"unknown tag id {t}")

    def _list(self, off: int):
        data = self.data
        t = data[off]
        n = _INT.unpack_from(data, off + 1)[0]
        off += 5
        if n <= 0:
            return [], off
        fmt = _LIST_FORMATS.get(t)
        if fmt is not None:
            s = struct.Struct(f">{n}{fmt}")
            try:
                values = list(s.unpack_from(data, off))
            except struct.error:
                raise NbtParseError("unexpected end of data") from None
            return values, off + s.size
        if t == TAG_COMPOUND:
            out = []
            compound = self._compound
            for _ in range(n):
                value, _, off = compound(off)
                out.append(value)
            return out, off
        if t == TAG_STRING:
            out = []
            for _ in range(n):
                m = (data[off] << 8) | data[off + 1]
                off += 2
                out.append(decode_string(data[off:off + m]))
                off += m
            if off > len(data):
                raise NbtParseError("unexpected end of data")
            return out, off
        if t == TAG_LIST or t in _ARRAY_CODES:
            out = []
            payload = self._payload
            for _ in range(n):
                value, off = payload(t, off)
                out.append(value)
            return out, off
        if t == TAG_END:
            raise NbtParseError("list of TAG_End with non-zero length")
        raise NbtParseError(f"unknown list element tag id {t}")

    def _blocks(self, off: int) -> tuple[Blocks, int]:
        data = self.data
        t = data[off]
        n = _INT.unpack_from(data, off + 1)[0]
        off += 5
        blocks = Blocks()
        if n <= 0:
            return blocks, off
        if t != TAG_COMPOUND:
            raise NbtParseError("blocks list is not a list of compounds")
        unpack = _PLAIN_BLOCK.unpack_from
        pos_header, state_header = _POS_HEADER, _STATE_HEADER
        states, positions = blocks.states, blocks.positions
        compound = self._compound
        plain = 0
        limit = len(data) - _PLAIN_BLOCK_SIZE
        for _ in range(n):
            if off <= limit:
                h1, x, y, z, h2, state, end = unpack(data, off)
                if h1 == pos_header and h2 == state_header and end == 0:
                    states.append(state)
                    positions.extend((x, y, z))
                    plain += 1
                    off += _PLAIN_BLOCK_SIZE
                    continue
            if plain:
                blocks.count += plain
                plain = 0
            entry, _, off = compound(off)
            blocks.add_entry(entry)
        blocks.count += plain
        return blocks, off


def parse_bytes(data: bytes) -> tuple[dict, Blocks]:
    """Parse uncompressed NBT bytes into ``(root_without_blocks, blocks)``."""
    root, blocks = _Parser(data).root()
    return root, (blocks if blocks is not None else Blocks())


# --- nbtlib fallback ---------------------------------------------------------------

def _from_nbtlib(tag):
    import nbtlib
    if isinstance(tag, nbtlib.Compound):
        return {str(k): _from_nbtlib(v) for k, v in tag.items()}
    if isinstance(tag, nbtlib.List):
        return [_from_nbtlib(v) for v in tag]
    if isinstance(tag, nbtlib.String):
        return str(tag)
    if isinstance(tag, (nbtlib.Byte, nbtlib.Short, nbtlib.Int, nbtlib.Long)):
        return int(tag)
    if isinstance(tag, (nbtlib.Float, nbtlib.Double)):
        return float(tag)
    if isinstance(tag, nbtlib.ByteArray):
        return array("b", tag.tobytes())
    if isinstance(tag, nbtlib.IntArray):
        return array("i", tag.tolist())
    if isinstance(tag, nbtlib.LongArray):
        return array("q", tag.tolist())
    return tag


def parse_with_nbtlib(data: bytes) -> tuple[dict, Blocks]:
    """Parse via nbtlib and convert. Raises nbtlib's own error on failure."""
    import nbtlib
    tree = nbtlib.File.parse(io.BytesIO(data))
    root = _from_nbtlib(tree)
    blocks = Blocks()
    raw_blocks = root.pop("blocks", None)
    if isinstance(raw_blocks, list):
        for entry in raw_blocks:
            if isinstance(entry, dict):
                blocks.add_entry(entry)
            else:
                blocks.add_entry({})
    elif raw_blocks is not None:
        root["blocks"] = raw_blocks
    return root, blocks


# --- the indexed structure ----------------------------------------------------------

SPAWNER_BLOCK_IDS = {"minecraft:spawner", "minecraft:trial_spawner"}


def _walk_entity(entity: dict, path: str, out: list) -> None:
    out.append((entity, path))
    passengers = entity.get("Passengers")
    if isinstance(passengers, list):
        for i, rider in enumerate(passengers):
            if isinstance(rider, dict):
                _walk_entity(rider, f"{path}.Passengers[{i}]", out)


class Structure:
    """A parsed structure file plus the indexes the checks share.

    ``root`` holds every top-level key except ``blocks`` (``DataVersion``,
    ``size``, ``palette``/``palettes``, ``entities``, ...); ``blocks`` is the
    flat :class:`Blocks`. Everything else is derived once and cached.
    """

    __slots__ = ("root", "blocks", "_walked", "_loot_refs")

    def __init__(self, root: dict, blocks: Blocks) -> None:
        self.root = root
        self.blocks = blocks
        self._walked: list[tuple[dict, str]] | None = None
        self._loot_refs: set[str] | None = None

    # -- top-level fields
    @property
    def data_version(self) -> int | None:
        dv = self.root.get("DataVersion")
        return dv if isinstance(dv, int) and not isinstance(dv, bool) else None

    @property
    def palette(self) -> list | None:
        """The single ``palette`` list, or None (files using ``palettes`` have none)."""
        p = self.root.get("palette")
        return p if isinstance(p, list) else None

    @property
    def palette_variants(self) -> list[list]:
        """Every palette: ``[palette]`` for the single form, each inner list of
        ``palettes`` for the multi-variant form, ``[]`` when neither exists."""
        p = self.palette
        if p is not None:
            return [p]
        ps = self.root.get("palettes")
        if isinstance(ps, list):
            return [v for v in ps if isinstance(v, list)]
        return []

    def palette_names(self, variant: int = 0) -> list[str]:
        """Block id by palette index for one variant; ``"?"`` where ``Name`` is missing."""
        variants = self.palette_variants
        if variant >= len(variants):
            return []
        return [str(state.get("Name", "?")) if isinstance(state, dict) else "?" for state in variants[variant]]

    @property
    def entities(self) -> list:
        """Top-level ``entities`` entries (each normally ``{pos, blockPos, nbt}``)."""
        e = self.root.get("entities")
        return e if isinstance(e, list) else []

    @property
    def block_entities(self) -> list[BlockEntity]:
        return self.blocks.entities

    # -- derived indexes
    def walk_entities(self) -> list[tuple[dict, str]]:
        """Every entity compound with a dotted path: top-level entities and their
        riders, then spawner block entities' ``SpawnData.entity`` and
        ``SpawnPotentials[].data.entity`` (riders included), in file order."""
        if self._walked is None:
            out: list[tuple[dict, str]] = []
            for i, entry in enumerate(self.entities):
                if isinstance(entry, dict):
                    nbt = entry.get("nbt")
                    if isinstance(nbt, dict):
                        _walk_entity(nbt, f"entities[{i}]", out)
            for be in self.blocks.entities:
                base = f"blocks[{be.index}].nbt"
                spawn_data = be.nbt.get("SpawnData")
                if isinstance(spawn_data, dict):
                    entity = spawn_data.get("entity")
                    if isinstance(entity, dict):
                        _walk_entity(entity, f"{base}.SpawnData.entity", out)
                potentials = be.nbt.get("SpawnPotentials")
                if isinstance(potentials, list):
                    for j, potential in enumerate(potentials):
                        if not isinstance(potential, dict):
                            continue
                        data = potential.get("data")
                        if not isinstance(data, dict):
                            continue
                        entity = data.get("entity")
                        if isinstance(entity, dict):
                            _walk_entity(entity, f"{base}.SpawnPotentials[{j}].data.entity", out)
            self._walked = out
        return self._walked

    def blocks_in_states(self, wanted) -> Iterator[tuple[int, int, tuple[int, int, int] | None, dict | None]]:
        """``(index, state, pos, nbt)`` for every block whose palette index is in
        ``wanted``, in file order. ``nbt`` is None for a plain block."""
        blocks = self.blocks
        for i in blocks.indices_with_states(wanted):
            be = blocks.entity_at(i)
            yield i, blocks.state_of(i), blocks.pos_of(i), (be.nbt if be is not None else None)

    def loot_table_refs(self) -> set[str]:
        """Every string under a ``LootTable`` key anywhere in the file."""
        if self._loot_refs is None:
            refs: set[str] = set()
            _collect_key_strings(self.root, "LootTable", refs)
            for be in self.blocks.entities:
                _collect_key_strings(be.nbt, "LootTable", refs)
            self._loot_refs = refs
        return self._loot_refs


def _collect_key_strings(node, key: str, out: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                out.add(v)
            else:
                _collect_key_strings(v, key, out)
    elif isinstance(node, list):
        for item in node:
            _collect_key_strings(item, key, out)


# --- loading -------------------------------------------------------------------------

def parse_structure(raw: bytes) -> Structure:
    """Parse gzipped or plain NBT bytes. Raises on a file neither parser accepts."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        root, blocks = parse_bytes(raw)
    except Exception:
        # Let nbtlib have the final say: either it parses the file (and we use
        # its tree) or its error is the one worth reporting.
        root, blocks = parse_with_nbtlib(raw)
    return Structure(root, blocks)


def load_structure(path: Path) -> Structure:
    return parse_structure(path.read_bytes())
