"""A data pack as one Minecraft version sees it, and the model it is read with.

Three things decide what a version does with a file under ``data/``:

* **Which files it loads.** Folder names were made singular at 1.21
  (``loot_tables`` -> ``loot_table``); a version reads only its own spelling and
  skips the other folder without a word. ``pack.mcmeta`` overlays (1.20.2+) lay
  extra folders over the base pack for a range of pack formats; a file in an
  active overlay replaces the base file at the same path, and later overlays
  win over earlier ones.
* **How it reads each file** -- the vanilla-mcdoc model in ``data/format_model``
  (see ``core/mcdoc.py``), and for tags, the ``replace`` / ``values`` shape every
  version since 1.16.2 shares.
* **Which ids exist** -- that version's registries and tags from mcmeta.

``data/format_model/model.json`` records where the model came from and every
version it was proven against: ``tools/update_format_model.py`` reads each
version's own vanilla data with it and accepts the model only when that comes
out clean. A version not in that list has not been checked, and the check says
so instead of passing it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.claims import NEW_FORMAT_FIELDS, format_range
from core.mcdoc import Finding, IdSpec, Reader, _vt
from core.project import _PLURAL_FORMS

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "data" / "format_model"

V1_21 = (1, 21)
OVERLAYS_SINCE = (18, 0)      # 1.20.2 (23w31a): pack.mcmeta overlays


# --- the model --------------------------------------------------------------------

@dataclass
class FormatModel:
    symbols: dict
    meta: dict

    @property
    def ref(self) -> str:
        return str(self.meta.get("mcdoc_ref", "?"))

    @property
    def verified(self) -> dict:
        return self.meta.get("verified", {})

    @property
    def gaps(self) -> list[dict]:
        return self.meta.get("gaps", [])

    def gap_for(self, kind: str, version: str, finding: Finding) -> dict | None:
        """A known model gap that explains ``finding`` (see model.json ``gaps``)."""
        for g in self.gaps:
            if g.get("kind") != kind or g.get("code") != finding.code:
                continue
            if g.get("key") is not None and g.get("key") != finding.key:
                continue
            if g.get("versions") and version not in g["versions"]:
                continue
            if g.get("path_suffix") and not finding.path.endswith(g["path_suffix"]):
                continue
            return g
        return None


_MODEL_CACHE: dict[Path, FormatModel] = {}


def apply_patches(symbols: dict, patches: list[dict]) -> list[str]:
    """Correct the model where vanilla data shows it wrong (model.json ``patches``).

    Each patch names a struct (``type``), one of its fields (``key``) and the
    window the game really reads it in (``since`` / ``until``). Returns the
    patches that matched nothing, so a model bump that fixes or moves the field
    is noticed.
    """
    unmatched = []
    for p in patches:
        node = symbols.get("mcdoc", {}).get(p.get("type"))
        hit = False
        if isinstance(node, dict) and node.get("kind") == "struct":
            for f in node.get("fields", []):
                if f.get("kind") == "pair" and f.get("key") == p.get("key"):
                    attrs = [a for a in f.get("attributes", []) or []
                             if a.get("name") not in ("since", "until")]
                    for name in ("since", "until"):
                        if p.get(name):
                            attrs.append({"name": name, "value": {"kind": "literal",
                                                                  "value": {"kind": "string", "value": p[name]}}})
                    f["attributes"] = attrs
                    hit = True
        if not hit:
            unmatched.append(f"{p.get('type')}.{p.get('key')}")
    return unmatched


def load_model(model_dir: Path = MODEL_DIR) -> FormatModel:
    """The pinned model, with its patches applied. Raises when it is missing or unreadable."""
    model_dir = Path(model_dir)
    hit = _MODEL_CACHE.get(model_dir)
    if hit is None:
        with (model_dir / "model.json").open(encoding="utf-8") as f:
            meta = json.load(f)
        with (model_dir / "symbols.json").open(encoding="utf-8") as f:
            symbols = json.load(f)
        apply_patches(symbols, meta.get("patches", []))
        hit = _MODEL_CACHE[model_dir] = FormatModel(symbols, meta)
    return hit


# --- which files a version loads ---------------------------------------------------

# plural -> singular, for the folders renamed at 1.21 (24w21a)
_SINGULAR = {plural: singular for singular, plural in _PLURAL_FORMS.items()}


@dataclass(frozen=True)
class Resource:
    rel: str                  # path under data/: "<ns>/<kind dir>/<path>.json"
    namespace: str
    kind: str                 # registry kind with today's spelling: "loot_table", "tags/worldgen/biome"
    id: str                   # "<ns>:<path>"
    tag_registry: str | None  # for tags: the registry the tag holds ("worldgen/biome")
    read_from: tuple | None   # first version that loads this folder spelling
    read_until: tuple | None  # first version that no longer loads it

    def loaded_on(self, version: tuple) -> bool:
        return ((self.read_from is None or version >= self.read_from)
                and (self.read_until is None or version < self.read_until))


def classify(rel: str, resource_kinds: set[str], registries: set[str]) -> Resource | None:
    """Work out what ``data/<rel>`` is. None for anything that is not JSON data
    a vanilla registry reads (an MSL config file, a function, ...)."""
    parts = rel.split("/")
    if len(parts) < 3 or not rel.endswith(".json"):
        return None
    ns, rest = parts[0], "/".join(parts[1:])
    if rest.startswith("tags/"):
        sub = rest[len("tags/"):]
        read_from = read_until = None
        legacy = next((p for p in sorted(_SINGULAR, key=len, reverse=True)
                       if p.startswith("tags/") and sub.startswith(p[len("tags/"):] + "/")), None)
        if legacy is not None:
            reg = _SINGULAR[legacy][len("tags/"):]
            path = sub[len(legacy) - len("tags/") + 1:]
            read_until = V1_21
        else:
            reg = next((r for r in sorted(registries, key=len, reverse=True) if sub.startswith(r + "/")), None)
            if reg is None:
                return None
            path = sub[len(reg) + 1:]
            if f"tags/{reg}" in _PLURAL_FORMS:
                read_from = V1_21
        return Resource(rel, ns, f"tags/{reg}", f"{ns}:{path[:-5]}", reg, read_from, read_until)
    read_from = read_until = None
    for plural, singular in _SINGULAR.items():
        if not plural.startswith("tags/") and rest.startswith(plural + "/"):
            kind, path, read_until = singular, rest[len(plural) + 1:], V1_21
            break
    else:
        kind = next((k for k in sorted(resource_kinds, key=len, reverse=True) if rest.startswith(k + "/")), None)
        if kind is None:
            return None
        path = rest[len(kind) + 1:]
        if kind in _PLURAL_FORMS:
            read_from = V1_21
    if kind not in resource_kinds:
        return None
    return Resource(rel, ns, kind, f"{ns}:{path[:-5]}", None, read_from, read_until)


@dataclass
class Overlay:
    directory: str
    block: dict


@dataclass
class Pack:
    """``pack.mcmeta`` and the overlays it declares."""
    resources_root: Path
    meta: dict | None
    overlays: list[Overlay] = field(default_factory=list)

    @classmethod
    def read(cls, resources_root: Path, try_json) -> "Pack":
        meta = try_json(resources_root / "pack.mcmeta") if (resources_root / "pack.mcmeta").is_file() else None
        overlays: list[Overlay] = []
        if isinstance(meta, dict):
            entries = (meta.get("overlays") or {}).get("entries") if isinstance(meta.get("overlays"), dict) else None
            for e in entries or []:
                if isinstance(e, dict) and isinstance(e.get("directory"), str):
                    overlays.append(Overlay(e["directory"], e))
        return cls(resources_root, meta if isinstance(meta, dict) else None, overlays)

    def active_overlays(self, pack_format: tuple[int, int] | None) -> list[str]:
        """Overlay folders a version with this data pack format lays over the base, in order."""
        if pack_format is None or pack_format < OVERLAYS_SINCE:
            return []
        out = []
        for o in self.overlays:
            rng = format_range(o.block, new_fields=pack_format >= NEW_FORMAT_FIELDS)
            if rng is not None and rng[0] <= pack_format <= rng[1]:
                out.append(o.directory)
        return out


def effective_files(resources_root: Path, overlay_dirs: list[str], list_json) -> dict[str, Path]:
    """``data/``-relative path -> the file a version loads, overlays applied."""
    out: dict[str, Path] = {}
    for base in [resources_root / "data"] + [resources_root / d / "data" for d in overlay_dirs]:
        for p in list_json(base):
            out[p.relative_to(base).as_posix()] = p
    return out


# --- tags -----------------------------------------------------------------------------

def read_tag(value, registry: str, reader: Reader) -> list[Finding]:
    """Read a tag file as one version does.

    A ``minecraft:`` entry the version does not have (or a ``#minecraft:`` tag it
    does not ship) fails the whole tag on that version unless the entry is the
    object form with ``"required": false``.
    """
    out: list[Finding] = []
    if not isinstance(value, dict):
        out.append(Finding("", "shape", detail="a tag file is an object with a `values` list"))
        return out
    for k in value:
        if k in ("replace", "values") or k.startswith("_"):
            continue  # ("_comment" and the like are authors' notes)
        if ":" in k and not k.startswith("minecraft:"):
            continue  # a loader's own key
        out.append(Finding(k, "unknown-key", key=k, detail=f"no version reads `{k}` in a tag file"))
    values = value.get("values")
    if values is None:
        out.append(Finding("", "missing", key="values", detail="`values` is required"))
        return out
    if not isinstance(values, list):
        out.append(Finding("values", "shape", detail="`values` is a list"))
        return out
    spec = IdSpec(registry, "allowed", False)
    for i, entry in enumerate(values):
        path = f"values[{i}]"
        if isinstance(entry, str):
            reader.check_id(entry, spec, path, out)
        elif isinstance(entry, dict):
            if not isinstance(entry.get("id"), str):
                out.append(Finding(path, "missing", key="id", detail="`id` is required"))
                continue
            if entry.get("required", True) is False:
                continue
            reader.check_id(entry["id"], spec, path + ".id", out)
        else:
            out.append(Finding(path, "shape", detail="a tag entry is an id or an object with `id`"))
    return out


# --- a reader for one version ---------------------------------------------------------

def version_reader(model: FormatModel, version: str, registry_data: dict | None,
                   local_ids: set[tuple[str, str]], neighbours=None) -> Reader:
    """A :class:`Reader` for ``version`` backed by mcmeta's registry summary.

    mcmeta ships some lists empty (``worldgen/structure`` and its tags for 1.21
    and 1.21.1). ``neighbours(key)`` may then return the same list from the
    nearest releases before and after; an id either of them has counts as
    known, so only an id both lack is reported. Without neighbours, or when a
    registry is not listed at all, it is left alone rather than failing every
    id in it.
    """
    data = registry_data or {}
    cache: dict[str, set | None] = {}

    def lookup(key: str):
        if key not in cache:
            names = data.get(key)
            if not names and neighbours is not None:
                names = neighbours(key)
            cache[key] = {"minecraft:" + n for n in names} if names else None
        return cache[key]

    def registry(name: str):
        return lookup(name)

    def tags(name: str):
        return lookup("tag/" + name)

    def local_id(reg: str, id_: str) -> bool:
        return (reg, id_) in local_ids

    return Reader(model.symbols, _vt(version), registry, tags, local_id)


def neighbour_lists(version: str, order: list[str], fetch):
    """``neighbours`` for :func:`version_reader`: the union of a list from the
    nearest releases before and after ``version`` that list it non-empty.
    ``fetch(version)`` returns a registry summary or raises."""
    def find(key: str):
        if version not in order:
            return None
        i = order.index(version)
        found = []
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(order):
                try:
                    names = (fetch(order[j]) or {}).get(key)
                except Exception:
                    names = None
                if names:
                    found.append(set(names))
                    break
                j += step
        if len(found) < 2:
            return None   # bracketed on one side only: cannot be told
        return sorted(found[0] | found[1])
    return find
