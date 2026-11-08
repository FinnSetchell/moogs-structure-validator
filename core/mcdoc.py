"""How each Minecraft version reads a data pack JSON file, from the vanilla-mcdoc model.

`vanilla-mcdoc <https://github.com/SpyglassMC/vanilla-mcdoc>`_ describes every
data pack format the game has had, with each field, union member and enum value
marked ``#[since="X"]`` / ``#[until="X"]``. Spyglass publishes it compiled to a
JSON symbol table; a pinned copy ships in ``data/format_model/`` (see
``tools/update_format_model.py``, which also proves it against every version's
own vanilla data before it is accepted).

:class:`Reader` walks one JSON value against one type *as one version reads it*
and returns what that version would do differently from what the author wrote:

* ``foreign-key``  -- a key this version does not read, which another version
  does (``functions`` on 26.3, ``modifier`` before 26.3). Whether that is an
  error depends on whether the object also carries the form this version reads;
  the finding names those counterpart keys and whether one is present.
* ``unknown-key``  -- a key no version reads.
* ``missing``      -- a required field this version needs is absent; the game
  refuses the whole file.
* ``unknown-id``   -- a ``minecraft:`` id (a type, an item, a tag ...) that this
  version's registry does not hold; the game refuses the whole file.
* ``shape``        -- a value of the wrong kind (object where a list is read).

The game ignores keys it does not read without a word (Mojang's record codecs
skip unknown fields), so the first two are exactly the silent failures this
module exists to find. Ids without a namespace are read as ``minecraft:``
(``Identifier.bySeparator`` falls back to the default namespace), so
``enchant_randomly`` is a valid spelling and is checked as
``minecraft:enchant_randomly``.

Objects whose type is a mod's own (``moogs_structures:...``) cannot be judged
here: only the fields the vanilla base type declares are checked, and no key is
reported unknown or missing on them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

Version = tuple

# --- versions -------------------------------------------------------------------

def _vt(s: str) -> Version:
    return tuple(int(x) for x in s.split("."))


def _attrs(node) -> list:
    a = node.get("attributes") if isinstance(node, dict) else None
    return a if isinstance(a, list) else []


def _attr(node, name: str):
    for a in _attrs(node):
        if isinstance(a, dict) and a.get("name") == name:
            return a
    return None


def _attr_literal(node, name: str):
    a = _attr(node, name)
    if a is None:
        return None
    v = a.get("value")
    if isinstance(v, dict) and v.get("kind") == "literal":
        return v.get("value", {}).get("value")
    return None


def _window(node) -> tuple[Version | None, Version | None]:
    s = _attr_literal(node, "since")
    u = _attr_literal(node, "until")
    return (_vt(s) if isinstance(s, str) else None, _vt(u) if isinstance(u, str) else None)


def _meet(a: tuple, b: tuple) -> tuple:
    """Intersection of two (since, until) windows."""
    s = a[0] if b[0] is None else b[0] if a[0] is None else max(a[0], b[0])
    u = a[1] if b[1] is None else b[1] if a[1] is None else min(a[1], b[1])
    return (s, u)


class At:
    """Active at exactly one version."""
    __slots__ = ("v",)

    def __init__(self, v: Version):
        self.v = v

    def ok(self, w) -> bool:
        s, u = w
        return (s is None or s <= self.v) and (u is None or self.v < u)


class JustBefore:
    """Active at the last version before ``v``."""
    __slots__ = ("v",)

    def __init__(self, v: Version):
        self.v = v

    def ok(self, w) -> bool:
        s, u = w
        return (s is None or s < self.v) and (u is None or u >= self.v)


class AnyVersion:
    def ok(self, w) -> bool:
        s, u = w
        return s is None or u is None or s < u


ANY = AnyVersion()


def version_points(symbols: dict) -> list[Version]:
    """Every distinct since/until version named anywhere in the model."""
    found: set[str] = set()

    def walk(t):
        if isinstance(t, dict):
            for a in _attrs(t):
                if isinstance(a, dict) and a.get("name") in ("since", "until"):
                    v = _attr_literal({"attributes": [a]}, a["name"])
                    if isinstance(v, str):
                        found.add(v)
            for v in t.values():
                walk(v)
        elif isinstance(t, list):
            for v in t:
                walk(v)

    walk(symbols.get("mcdoc", {}))
    walk(symbols.get("mcdoc/dispatcher", {}))
    return sorted(_vt(v) for v in found)


# --- ids ------------------------------------------------------------------------

def normalize_id(value: str) -> str:
    """``foo`` -> ``minecraft:foo``; the game reads a bare path that way."""
    return value if ":" in value else "minecraft:" + value


def _bare(value: str) -> str:
    return value[len("minecraft:"):] if value.startswith("minecraft:") else value


@dataclass(frozen=True)
class IdSpec:
    registry: str | None
    tags: str | None          # None (no tags), "allowed", "implicit", "required"
    definition: bool
    asset: bool = False       # a path into a resource pack (textures, models): not a registry


# Registries that name resource pack files, not game registry entries.
_ASSET_REGISTRIES = frozenset({"texture", "model", "atlas", "font", "lang", "shader", "post_effect",
                               "item_definition", "block_definition", "sound", "equipment"})


def _id_spec(node) -> IdSpec | None:
    a = _attr(node, "id")
    if a is None:
        return None
    v = a.get("value")
    if v is None:
        return IdSpec(None, None, False)
    if v.get("kind") == "literal":
        reg = v.get("value", {}).get("value")
        return IdSpec(reg if isinstance(reg, str) else None, None, False, asset=reg in _ASSET_REGISTRIES)
    if v.get("kind") == "tree":
        vals = v.get("values", {})

        def lit(key):
            x = vals.get(key)
            return x.get("value", {}).get("value") if isinstance(x, dict) and x.get("kind") == "literal" else None

        reg = lit("registry")
        tags = lit("tags")
        return IdSpec(reg if isinstance(reg, str) else None, tags if isinstance(tags, str) else None,
                      bool(lit("definition")), asset=lit("path") is not None or reg in _ASSET_REGISTRIES)
    return IdSpec(None, None, False)


# --- findings -------------------------------------------------------------------

@dataclass
class Finding:
    path: str
    code: str               # foreign-key | unknown-key | missing | unknown-id | unknown-tag | shape
    key: str | None = None  # the key concerned (foreign-key, unknown-key, missing)
    detail: str = ""
    # foreign-key only: the keys this version reads instead, and whether the
    # object carries one of them (the file is then written in both forms).
    counterparts: tuple[str, ...] = ()
    counterpart_present: bool = False
    # foreign-key only: the window in which the key *is* read, for messages.
    known_window: tuple = (None, None)


_INDEX = re.compile(r"\[\d+\]")


def _join(path: str, key) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else str(key)


# --- the reader ---------------------------------------------------------------------

class _Field:
    __slots__ = ("key", "keytype", "type", "optional", "window", "owner")

    def __init__(self, key, keytype, type_, optional, window, owner=None):
        self.key = key            # str, or None for a dynamic-key field
        self.keytype = keytype    # mcdoc type of the key for dynamic-key fields
        self.type = type_
        self.optional = optional
        self.window = window      # versions that read it, enclosing spreads included
        self.owner = owner        # the struct node that declares it


class _Flat:
    """A struct's fields for one value, with spreads and dispatches resolved."""
    __slots__ = ("fields", "open", "custom")

    def __init__(self):
        self.fields: list[_Field] = []
        self.open = False     # some part could not be resolved: keys may be valid
        self.custom = False   # dispatched to a type the model does not know (a mod's own)


class Reader:
    """Reads values the way one Minecraft version does.

    ``registry(name)`` returns the set of ``minecraft:`` ids registry ``name``
    holds at this version, or None when that cannot be told (the check then
    stays silent). ``tags(name)`` does the same for ``#minecraft:`` tags.
    ``local_id(registry, id)`` says whether the project itself defines a
    ``minecraft:`` id (a pack may add entries to vanilla's data registries).
    """

    def __init__(self, symbols: dict, version: Version,
                 registry: Callable[[str], set | None],
                 tags: Callable[[str], set | None],
                 local_id: Callable[[str, str], bool] | None = None):
        self.types: dict = symbols["mcdoc"]
        self.dispatchers: dict = symbols["mcdoc/dispatcher"]
        self.version = version
        self.at = At(version)
        self._registry = registry
        self._tags = tags
        self._local_id = local_id or (lambda reg, id_: False)
        # Optional census of which declared fields the values read used:
        # (id(owning struct), key) -> count, with each field's window.
        self.usage: dict | None = None
        self.usage_windows: dict = {}
        self.usage_paths: dict = {}
        self.usage_prefix = ""

    # -- public
    def resource_type(self, registry: str):
        """The mcdoc type of a data pack resource kind (``loot_table`` ...), or None."""
        t = self.dispatchers.get("minecraft:resource", {}).get(registry)
        if t is None or not self.at.ok(_window(t)):
            return None
        return t

    def read(self, value, type_, path: str = "") -> list[Finding]:
        out: list[Finding] = []
        self._check(value, type_, {}, [], path, out)
        return out

    def check_id(self, value: str, spec: IdSpec, path: str, out: list[Finding]) -> None:
        """Report a ``minecraft:`` id (or tag) that this version does not hold."""
        if spec.registry is None or spec.definition or spec.asset or not isinstance(value, str) or not value:
            return
        if spec.tags == "implicit" and not value.startswith("#"):
            value = "#" + value   # a tag named without the '#', as tag entries do
        if value.startswith("#"):
            if spec.tags is None:
                out.append(Finding(path, "shape", detail=f"`{value}` is a tag, but a single "
                                                         f"{spec.registry} id is read here"))
                return
            tag = normalize_id(value[1:])
            if not tag.startswith("minecraft:"):
                return
            known = self._tags(spec.registry)
            if known is not None and tag not in known and not self._local_id("tags/" + spec.registry, tag):
                out.append(Finding(path, "unknown-tag", detail=f"tag `#{tag}` does not exist in "
                                                               f"{spec.registry} on this version"))
            return
        if value.startswith("!"):  # negated id lists (block predicates) read the rest
            value = value[1:]
        id_ = normalize_id(value)
        if not id_.startswith("minecraft:"):
            return
        known = self._registry(spec.registry)
        if known is not None and id_ not in known and not self._local_id(spec.registry, id_):
            out.append(Finding(path, "unknown-id", detail=f"`{id_}` is not a {spec.registry} on this version"))

    # -- resolution
    def _deref(self, t, env: dict):
        """Follow references (and bound template parameters) to a concrete node."""
        seen = 0
        while isinstance(t, dict) and t.get("kind") == "reference":
            path = t.get("path")
            if path in env:
                t = env[path]
            else:
                nxt = self.types.get(path)
                if nxt is None:
                    return None
                t = nxt
            seen += 1
            if seen > 64:
                return None
        return t

    def _instantiate(self, t, env: dict):
        """``concrete`` -> the template's child with its parameters bound."""
        child = self._deref(t.get("child"), env)
        if not isinstance(child, dict) or child.get("kind") != "template":
            return child, env
        params = [p.get("path") for p in child.get("typeParams", [])]
        args = t.get("typeArgs", [])
        new_env = dict(env)
        for p, a in zip(params, args):
            new_env[p] = a
        return child.get("child"), new_env

    def _dispatch(self, registry: str, indices: list, frames: list, pred) -> tuple[object, bool, bool]:
        """Resolve a dispatcher for the current object.

        Returns ``(type or None, open, custom)``: ``open`` when the target is
        unknown and keys must not be judged; ``custom`` when the index names a
        type outside ``minecraft:`` (a mod's own).
        """
        table = self.dispatchers.get(registry)
        if table is None:
            return None, True, False
        if len(indices) != 1:
            return None, True, False
        idx = indices[0]
        key = None
        if idx.get("kind") == "static":
            key = idx.get("value")
            if key == "%fallback":
                return None, True, False
        else:
            key = self._access(idx.get("accessor", []), frames)
            if key is None:
                t = table.get("%none")
                if t is not None:
                    return t, False, False
                # The index key is absent. In the every-version view that only
                # means this version's index is not the one the value uses (a
                # loot function keyed by `function` has no `type`): nothing to add.
                return None, pred is not ANY, False
            if not isinstance(key, str):
                return None, True, False
        if not isinstance(key, str):
            return None, True, False
        if key.startswith("#"):
            return None, True, False
        nid = normalize_id(key)
        custom = not nid.startswith("minecraft:") and not nid.startswith("mcdoc:")
        t = table.get(_bare(nid)) if not custom else table.get(nid)
        if t is None and nid.startswith("mcdoc:"):
            t = table.get(nid)
        if t is None:
            t = table.get("%unknown")
            if t is None or custom:
                return None, True, custom
        if not pred.ok(_window(t)):
            return None, True, False
        return t, False, False

    @staticmethod
    def _access(accessor: list, frames: list):
        """Evaluate a dynamic dispatcher index against the object stack.

        ``frames`` holds ``(object, key)`` pairs, innermost last; ``key`` is the
        map key the object sits under, for ``%key`` indices.
        """
        depth = len(frames) - 1
        i = 0
        while i < len(accessor) and isinstance(accessor[i], dict):
            kw = accessor[i].get("keyword")
            if kw == "parent":
                depth -= 1
            elif kw == "key":
                return frames[depth][1] if depth >= 0 else None
            i += 1
        if depth < 0:
            return None
        cur = frames[depth][0]
        for step in accessor[i:]:
            if isinstance(step, dict) or not isinstance(cur, dict):
                return None
            cur = cur.get(step)
        return cur

    def flatten(self, t, value: dict, env: dict, frames: list, pred) -> _Flat:
        flat = _Flat()
        self._flatten(t, value, env, frames, pred, (None, None), flat, 0)
        return flat

    def _flatten(self, t, value, env, frames, pred, win, flat: _Flat, depth: int) -> None:
        if depth > 32:
            flat.open = True
            return
        t = self._deref(t, env)
        if t is None:
            flat.open = True
            return
        win = _meet(win, _window(t))
        kind = t.get("kind")
        if kind == "concrete":
            child, env2 = self._instantiate(t, env)
            self._flatten(child, value, env2, frames, pred, win, flat, depth + 1)
            return
        if kind == "template":
            self._flatten(t.get("child"), value, env, frames, pred, win, flat, depth + 1)
            return
        if kind == "dispatcher":
            target, opened, custom = self._dispatch(t.get("registry"), t.get("parallelIndices", []), frames, pred)
            if custom:
                flat.custom = True
            if opened:
                flat.open = True
                return
            if target is None:
                return
            self._flatten(target, value, env, frames, pred, win, flat, depth + 1)
            return
        if kind == "union":
            # A spread of a union: take the member that fits the value best.
            members = [m for m in t.get("members", []) if pred.ok(_meet(win, _window(m)))]
            structs = []
            for m in members:
                md = self._deref(m, env)
                if isinstance(md, dict) and md.get("kind") in ("struct", "reference", "concrete", "dispatcher"):
                    structs.append(m)
            if len(structs) == 1:
                self._flatten(structs[0], value, env, frames, pred, win, flat, depth + 1)
            else:
                flat.open = True
            return
        if kind != "struct":
            flat.open = True
            return
        for f in t.get("fields", []):
            fw = _meet(win, _window(f))
            if f.get("kind") == "spread":
                if not pred.ok(fw):
                    continue
                self._flatten(f.get("type"), value, env, frames, pred, fw, flat, depth + 1)
                continue
            if not pred.ok(fw):
                continue
            key = f.get("key")
            if isinstance(key, str):
                flat.fields.append(_Field(key, None, f.get("type"), bool(f.get("optional")), fw, t))
            else:
                flat.fields.append(_Field(None, key, f.get("type"), True, fw, t))

    # -- checking
    def _check(self, value, t, env, frames, path, out, siblings=None) -> None:
        t0 = t
        t = self._deref(t, env)
        if t is None:
            return
        kind = t.get("kind")
        if kind == "concrete":
            child, env2 = self._instantiate(t, env)
            self._check(value, child, env2, frames, path, out, siblings)
            return
        if kind == "template":
            self._check(value, t.get("child"), env, frames, path, out, siblings)
            return
        if kind == "union":
            self._check_union(value, t, env, frames, path, out, siblings)
            return
        if kind == "struct":
            self._check_struct(value, t, env, frames, path, out, siblings)
            return
        if kind == "dispatcher":
            # A dispatcher as a field's type is indexed from the object holding
            # the field (``config: minecraft:structure_config[[type]]`` reads the
            # sibling ``type``), so the frames are left as they are.
            target, _opened, _custom = self._dispatch(t.get("registry"), t.get("parallelIndices", []),
                                                      frames, self.at)
            if target is not None:
                self._check(value, target, env, frames, path, out)
            return
        if kind == "list" or kind in ("byte_array", "int_array", "long_array"):
            if not isinstance(value, list):
                out.append(Finding(path, "shape", detail=f"a list is read here, found {_kind_name(value)}"))
                return
            item = t.get("item")
            if item is None:
                return
            for i, v in enumerate(value):
                self._check(v, item, env, frames, _join(path, i), out)
            return
        if kind == "tuple":
            if not isinstance(value, list):
                out.append(Finding(path, "shape", detail=f"a list is read here, found {_kind_name(value)}"))
                return
            for i, (v, it) in enumerate(zip(value, t.get("items", []))):
                self._check(v, it, env, frames, _join(path, i), out)
            return
        if kind == "string":
            if isinstance(value, (dict, list)):
                out.append(Finding(path, "shape", detail=f"a string is read here, found {_kind_name(value)}"))
                return
            spec = _id_spec(t) or _id_spec(t0)
            if spec is not None and isinstance(value, str):
                self.check_id(value, spec, path, out)
            return
        if kind in ("int", "long", "short", "byte", "float", "double", "boolean"):
            if isinstance(value, (dict, list)):
                out.append(Finding(path, "shape", detail=f"a {kind} is read here, found {_kind_name(value)}"))
            return
        if kind == "literal":
            lit = t.get("value", {}).get("value")
            if isinstance(lit, str) and isinstance(value, str):
                if _bare(normalize_id(value)) != _bare(normalize_id(lit)) and value != lit:
                    out.append(Finding(path, "shape", detail=f"`{lit}` is read here, found `{value}`"))
            elif lit != value:
                out.append(Finding(path, "shape", detail=f"{lit!r} is read here, found {value!r}"))
            return
        if kind == "enum":
            self._check_enum(value, t, t0, path, out)
            return
        # any, unsafe, indexed and anything newer: nothing to judge
        return

    def _check_enum(self, value, t, t0, path, out) -> None:
        if isinstance(value, (dict, list)):
            out.append(Finding(path, "shape", detail=f"one of a fixed set of values is read here, "
                                                     f"found {_kind_name(value)}"))
            return
        allowed = [e.get("value") for e in t.get("values", []) if self.at.ok(_window(e))]
        if value in allowed:
            return
        if isinstance(value, str):
            if ":" in value and not value.startswith("minecraft:"):
                return  # another namespace: not ours to judge
            if _bare(value) in allowed or normalize_id(value) in allowed:
                return
            ever = [e.get("value") for e in t.get("values", [])]
            when = ""
            if _bare(value) in ever or value in ever:
                when = " (it is read on other versions)"
            out.append(Finding(path, "unknown-id", detail=f"`{value}` is not one of the values this "
                                                          f"version reads here{when}"))
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if not any(isinstance(a, (int, float)) and a == value for a in allowed):
            out.append(Finding(path, "unknown-id", detail=f"{value} is not one of the values this version reads here"))

    def _check_union(self, value, t, env, frames, path, out, siblings=None) -> None:
        members = [m for m in t.get("members", []) if self.at.ok(_window(m))]
        if not members:
            out.append(Finding(path, "shape", detail="this version reads nothing here"))
            return
        best: list[Finding] | None = None
        best_score = None
        # Every version's members (and those of any union this one sits in), to
        # recognise another version's form of the value.
        everyone = list(t.get("members", [])) + list(siblings or [])
        for m in members:
            trial: list[Finding] = []
            self._check(value, m, env, frames, path, trial, siblings=everyone)
            score = (sum(1 for f in trial if f.code == "shape" and f.path == path),
                     sum(1 for f in trial if f.code != "foreign-key" or not f.counterpart_present),
                     len(trial))
            if best_score is None or score < best_score:
                best, best_score = trial, score
                if score == (0, 0, 0):
                    break
        out.extend(best or [])

    def _check_struct(self, value, t, env, frames, path, out, siblings=None) -> None:
        if not isinstance(value, dict):
            out.append(Finding(path, "shape", detail=f"an object is read here, found {_kind_name(value)}"))
            return
        frames = frames + [(value, frames[-1][1] if frames else None)]
        flat = self.flatten(t, value, env, frames, self.at)
        by_key: dict[str, _Field] = {}
        dynamic: list[_Field] = []
        for f in flat.fields:
            if f.key is not None:
                by_key.setdefault(f.key, f)
            else:
                dynamic.append(f)
        judge_keys = not flat.open and not flat.custom
        start = len(out)
        for k in value:
            child_path = _join(path, k)
            f = by_key.get(k)
            if f is not None:
                if self.usage is not None:
                    uk = (id(f.owner), k)
                    self.usage[uk] = self.usage.get(uk, 0) + 1
                    self.usage_windows[uk] = f.window
                    paths = self.usage_paths.setdefault(uk, set())
                    if len(paths) < 64:
                        paths.add(self.usage_prefix + _INDEX.sub("[]", child_path))
                self._check(value[k], f.type, env, frames, child_path, out)
                continue
            matched = False
            for df in dynamic:
                trial: list[Finding] = []
                self._check(k, df.keytype, env, frames, child_path, trial)
                if not any(x.code == "shape" for x in trial):
                    out.extend(x for x in trial if x.code == "unknown-id")
                    kframes = frames[:-1] + [(value, k)]
                    self._check(value[k], df.type, env, kframes, child_path, out)
                    matched = True
                    break
            if matched:
                continue
            if ":" in k and not k.startswith("minecraft:"):
                continue  # a loader's own key (fabric:load_conditions, neoforge:conditions ...)
            if k.startswith("_"):
                continue  # an author's note ("_comment"): no game key starts with "_"
            self._classify_unknown(k, value, t, env, frames, flat, judge_keys, child_path, out, siblings)
        if not flat.custom:
            # A required key named as the replacement of an old-form key is
            # already reported on that key.
            named = {c for f in out[start:] if f.code == "foreign-key" and f.path == _join(path, f.key)
                     for c in f.counterparts}
            for k, f in by_key.items():
                if not f.optional and k not in value and k not in named:
                    out.append(Finding(path, "missing", key=k, detail=f"`{k}` is required"))

    def _classify_unknown(self, k, value, t, env, frames, flat_now: _Flat, judge_keys: bool,
                          path: str, out: list[Finding], siblings=None) -> None:
        """A key this version does not read: is it another version's form?

        Another version may read it on this same type (a field with its own
        since/until), or on a different member of the union this value sits in
        (a block state was ``{Name}`` before 26.3 and ``{id}`` after).
        """
        every = self.flatten(t, value, env, frames, ANY)
        windows = [f.window for f in every.fields if f.key == k]
        source = t
        if not windows and siblings:
            for m in siblings:
                for leaf, mw in self._leaves(m, env, (None, None)):
                    if self._deref(leaf, env) is t:
                        continue
                    found = [_meet(mw, f.window) for f in self.flatten(leaf, value, env, frames, ANY).fields
                             if f.key == k]
                    found = [w for w in found if ANY.ok(w)]
                    if found:
                        windows, source = found, leaf
                        break
                if windows:
                    break
        if not windows:
            if judge_keys and not every.open:
                out.append(Finding(path, "unknown-key", key=k, detail=f"no version reads `{k}` here"))
            return
        if flat_now.custom:
            return
        if value.get(k) in ([], {}):
            return  # an empty list or object: ignoring it loses nothing
        # The edge between this version and the nearest window that reads k.
        v = self.version
        before = [w for w in windows if w[1] is not None and w[1] <= v]
        after = [w for w in windows if w[0] is not None and w[0] > v]
        if before:
            edge = max(w[1] for w in before)
            other = self.flatten(source, value, env, frames, JustBefore(edge))
            known = max(before, key=lambda w: w[1])
        elif after:
            edge = min(w[0] for w in after)
            other = self.flatten(source, value, env, frames, At(edge))
            known = min(after, key=lambda w: w[0])
        else:
            return  # read on this version after all (a window quirk): leave it
        now_keys = {f.key: f for f in flat_now.fields if f.key is not None}
        other_keys = {f.key for f in other.fields if f.key is not None}
        candidates = [now_keys[key] for key in now_keys if key not in other_keys]
        k_field = next((f for f in other.fields if f.key == k), None)
        # A replacement arrives at the edge where k leaves (or leaves where k
        # arrives). Not for another union member: the whole type changed there,
        # and the windows of its fields say nothing about the swap.
        if source is t:
            at_edge = [c for c in candidates if (c.window[0] == edge if before else c.window[1] == edge)]
            if at_edge:
                candidates = at_edge
        counterparts = self._pair(k_field, candidates, env) if k_field is not None else candidates
        names = tuple(sorted(f.key for f in counterparts))
        present = any(n in value for n in names)
        out.append(Finding(path, "foreign-key", key=k, counterparts=names, counterpart_present=present,
                           known_window=known))

    def _leaves(self, m, env, win, depth: int = 0):
        """Struct-like members of a (possibly nested) union, with their windows."""
        if depth > 6:
            return
        w = _meet(win, _window(m))
        md = self._deref(m, env)
        if not isinstance(md, dict):
            return
        kind = md.get("kind")
        if kind == "union":
            for mm in md.get("members", []):
                yield from self._leaves(mm, env, w, depth + 1)
        elif kind in ("struct", "concrete", "dispatcher", "template"):
            yield m, w

    def _pair(self, field: _Field, candidates: list[_Field], env) -> list[_Field]:
        """The candidates that carry the same kind of thing as ``field``: by name
        first (``ArmorDropChances`` -> ``drop_chances``), then by what the types
        refer to (``functions`` and ``modifier`` both hold loot functions)."""
        if len(candidates) <= 1:
            return candidates
        norm = lambda s: s.replace("_", "").lower()
        named = [c for c in candidates
                 if c.key and field.key and (norm(c.key) in norm(field.key) or norm(field.key) in norm(c.key))]
        if named:
            return named
        sig = self._signature(field.type, env)
        scored = []
        for c in candidates:
            cs = self._signature(c.type, env)
            overlap = len(sig & cs)
            scored.append((overlap, c))
        top = max(s for s, _ in scored)
        if top == 0:
            return candidates
        return [c for s, c in scored if s == top]

    def _signature(self, t, env, depth: int = 0, seen=None) -> set[str]:
        """Registries and dispatchers reachable from a type: what it 'is about'."""
        if seen is None:
            seen = set()
        out: set[str] = set()
        if depth > 6 or not isinstance(t, dict):
            return out
        if t.get("kind") == "reference":
            p = t.get("path")
            if p in seen:
                return out
            seen = seen | {p}
        spec = _id_spec(t)
        if spec is not None and spec.registry:
            out.add("id:" + spec.registry)
        t = self._deref(t, env)
        if not isinstance(t, dict):
            return out
        spec = _id_spec(t)
        if spec is not None and spec.registry:
            out.add("id:" + spec.registry)
        kind = t.get("kind")
        if kind == "dispatcher":
            out.add("dispatch:" + str(t.get("registry")))
        elif kind == "list":
            out |= self._signature(t.get("item"), env, depth + 1, seen)
        elif kind == "union":
            for m in t.get("members", []):
                out |= self._signature(m, env, depth + 1, seen)
        elif kind == "struct":
            for f in t.get("fields", []):
                ft = f.get("type")
                if f.get("kind") == "spread":
                    out |= self._signature(ft, env, depth + 1, seen)
                elif depth < 4:
                    out |= self._signature(ft, env, depth + 1, seen)
        elif kind == "concrete":
            out |= self._signature(t.get("child"), env, depth + 1, seen)
            for a in t.get("typeArgs", []):
                out |= self._signature(a, env, depth + 1, seen)
        elif kind == "template":
            out |= self._signature(t.get("child"), env, depth + 1, seen)
        return out


def _kind_name(value) -> str:
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, bool):
        return "a boolean"
    if value is None:
        return "null"
    return "a number"
