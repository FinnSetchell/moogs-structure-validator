"""Do the two loot forms a pack carries say the same thing?

A loot table written for 1.21 to 26.3 carries both forms: ``functions`` /
``conditions`` (1.21 to 26.2) and ``modifier`` / ``condition`` (26.3). Each
version reads only its own, so the pack works on every version only if the two
agree. A ``modifier`` missing a function the old form has is the issue-93 loss
on 26.3 again, with both keys present.

The two forms can sit side by side in one file, or in two files: a base file and
a pack overlay that only one side loads. Either way, what the old side reads is
compared with what 26.3 reads. Item modifier and predicate files carry both
forms in one object (``function`` and ``type``, ``conditions`` and
``condition``), so the whole object is compared. An item modifier file that is a
list is the ``minecraft:sequence`` it stands for on 1.21 to 26.2; 26.3 reads one
function per file, so the converter writes it as that sequence, in both forms.

This builds the 26.3 form from the old one, the way MFR's ``scripts/loot_26_3.py``
writes it (Moog's Structure Lib's renames plus ``functions`` -> ``modifier`` and
26.3's deeper renames), and compares it with what 26.3 reads. Both sides are read
the way 26.3 does:

* a single ``modifier`` object and a one-item list are the same, as are one
  condition and an ``all_of`` of just that condition, and a condition list and
  an ``all_of`` of its items;
* a type id with no namespace is ``minecraft:``; ``1.0`` is ``1``;
* key order does not matter.
"""
from __future__ import annotations

import json
from typing import Iterable

LOOT_RENAME = (26, 3)   # the first version that reads `modifier` / `condition` instead
FORM_KINDS = ("loot_table", "item_modifier", "predicate")

_NESTED_FUNCTION_FIELDS = {
    "sequence": {"functions": "function_list"},
    "filtered": {"on_pass": "function", "on_fail": "function"},
    "modify_contents": {"modifier": "function"},
    "set_contents": {"entries": "entry_list"},
}
_NESTED_CONDITION_FIELDS = {
    "inverted": {"term": "condition"},
    "all_of": {"terms": "condition_list"},
    "any_of": {"terms": "condition_list"},
}
# exploration_map: the explorer map tags 26.3 renamed (same contents, new names)
_MAP_TAGS_RENAMED = {
    "minecraft:on_jungle_explorer_maps": "minecraft:on_jungle_pyramid_maps",
    "minecraft:on_ocean_explorer_maps": "minecraft:on_ocean_monument_maps",
    "minecraft:on_swamp_explorer_maps": "minecraft:on_swamp_hut_maps",
    "minecraft:on_trial_chambers_maps": "minecraft:on_buried_trial_chambers_maps",
    "minecraft:on_woodland_explorer_maps": "minecraft:on_woodland_mansion_maps",
}

DISAGREE = "forms-disagree"   # the two forms say different things: ERROR
UNPAIRED = "forms-unpaired"   # an overlay laid out differently, so nothing can be paired: WARN


class _Absent:
    def __repr__(self):
        return "(absent)"


ABSENT = _Absent()


def _short(type_id):
    return type_id.split(":", 1)[1] if isinstance(type_id, str) and ":" in type_id else type_id


def _ns(type_id):
    if isinstance(type_id, str) and ":" not in type_id and not type_id.startswith("#"):
        return "minecraft:" + type_id
    return type_id


def _tagged(v: str) -> str:
    return v if v.startswith("#") else "#" + v


class Converter:
    """Old form -> 26.3 form. ``structure_tags`` are the structure tags 26.3
    knows (vanilla's and the pack's own), for exploration_map destinations."""

    def __init__(self, structure_tags: Iterable[str] = ()):
        self.structure_tags = set(structure_tags)

    def condition(self, c):
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return self.condition_list(c)
        if not isinstance(c, dict):
            return c
        ctype = _ns(c.get("condition", c.get("type")))
        sid = _short(ctype)
        if sid == "reference" and isinstance(c.get("name"), str):
            return c["name"]
        nested = _NESTED_CONDITION_FIELDS.get(sid, {})
        out = {"type": ctype}
        for k, v in c.items():
            if k in ("condition", "type"):
                continue
            kind = nested.get(k)
            if kind == "condition":
                out[k] = self.condition(v)
            elif kind == "condition_list" and isinstance(v, list):
                out[k] = [self.condition(x) for x in v]
            else:
                out[k] = v
        if sid == "block_state_property" and "block" in out:
            renamed = {"type": "minecraft:match_block", "blocks": out.pop("block")}
            if "properties" in out:
                renamed["state"] = out.pop("properties")
            del out["type"]
            renamed.update(out)
            out = renamed
        elif sid == "damage_source_properties":
            pred = out.get("predicate")
            if isinstance(pred, dict) and isinstance(pred.get("tags"), list):
                pred = dict(pred)
                pred["tags"] = [dict(t, id=_tagged(t["id"])) if isinstance(t, dict) and isinstance(t.get("id"), str)
                                else t for t in pred["tags"]]
                out["predicate"] = pred
        return out

    def condition_list(self, conds):
        conds = [self.condition(c) for c in conds]
        if not conds:
            return None
        if len(conds) == 1:
            return conds[0]
        return {"type": "minecraft:all_of", "terms": conds}

    def function(self, f):
        if isinstance(f, str):
            return f
        if isinstance(f, list):
            return self.function_list(f)
        if not isinstance(f, dict):
            return f
        ftype = _ns(f.get("function", f.get("type")))
        sid = _short(ftype)
        if sid == "reference" and isinstance(f.get("name"), str):
            return f["name"]
        nested = _NESTED_FUNCTION_FIELDS.get(sid, {})
        out = {"type": ftype}
        for k, v in f.items():
            if k in ("function", "type"):
                continue
            if k == "conditions":
                cond = self.condition_list(v) if isinstance(v, list) else self.condition(v)
                if cond is not None:
                    out["condition"] = cond
                continue
            kind = nested.get(k)
            if kind == "function":
                out[k] = self.function(v)
            elif kind == "function_list":
                out[k] = [self.function(x) for x in v] if isinstance(v, list) else self.function(v)
            elif kind == "entry_list" and isinstance(v, list):
                out[k] = [self.entry_new_only(e) for e in v]
            else:
                out[k] = v
        if sid == "exploration_map":
            out["destination"] = self.map_destination(out.get("destination", "minecraft:on_treasure_maps"))
        return out

    def function_list(self, funcs):
        funcs = [self.function(f) for f in funcs]
        if not funcs:
            return None
        if len(funcs) == 1:
            return funcs[0]
        return funcs

    def map_destination(self, v):
        if not isinstance(v, str):
            return v
        tag = _ns(v.lstrip("#"))
        tag = _MAP_TAGS_RENAMED.get(tag, tag)
        if tag in self.structure_tags:
            return "#" + tag
        return v   # not a tag: the converter keeps it and reports it

    def _site_new_only(self, o: dict) -> dict:
        """``functions`` / ``conditions`` replaced by the 26.3 keys built from them
        (the script's ``with_new_keys`` then dropping the old keys)."""
        if "functions" in o:
            v = o.pop("functions")
            o.pop("modifier", None)
            m = self.function_list(v) if isinstance(v, list) else None
            if m is not None:
                o["modifier"] = m
        if "conditions" in o:
            v = o.pop("conditions")
            o.pop("condition", None)
            c = self.condition_list(v) if isinstance(v, list) else None
            if c is not None:
                o["condition"] = c
        return o

    def table_new_only(self, t):
        """A table written inline inside a part only 26.3 reads: 26.3 form only
        (the script's ``convert_table(only_new=True)``)."""
        if not isinstance(t, dict):
            return t
        t = self._site_new_only(dict(t))
        if isinstance(t.get("pools"), list):
            pools = []
            for p in t["pools"]:
                if isinstance(p, dict):
                    p = dict(p)
                    if isinstance(p.get("entries"), list):
                        p["entries"] = [self.entry_new_only(e) for e in p["entries"]]
                    p = self._site_new_only(p)
                pools.append(p)
            t["pools"] = pools
        return t

    def entry_new_only(self, e):
        """An entry inside a part only 26.3 reads (a set_contents list): 26.3 form
        only (the script's ``convert_entry(only_new=True)``)."""
        if not isinstance(e, dict):
            return e
        e = dict(e)
        if isinstance(e.get("children"), list):
            e["children"] = [self.entry_new_only(c) for c in e["children"]]
        if _short(e.get("type")) == "loot_table" and isinstance(e.get("value"), dict):
            e["value"] = self.table_new_only(e["value"])
        e = self._site_new_only(e)
        if _short(e.get("type")) == "tag" and isinstance(e.get("name"), str):
            e.pop("items", None)
            e["items"] = _tagged(e.pop("name"))
        return e


# --- what each side reads of an object written in both forms at once ----------------------
# Item modifier and predicate files carry both forms in one object. 1.21 to 26.2
# dispatch on `function` / `condition` and skip `type` and the 26.3 keys; 26.3
# dispatches on `type` and skips the old keys.

def old_function(f):
    if not isinstance(f, dict) or "function" not in f:
        return f
    out = {k: v for k, v in f.items() if k not in ("type", "condition")}
    for k, kind in _NESTED_FUNCTION_FIELDS.get(_short(_ns(f["function"])), {}).items():
        if k in out:
            out[k] = _map(out[k], kind, old_function, old_entry)
    if isinstance(out.get("conditions"), list):
        out["conditions"] = [old_condition(c) for c in out["conditions"]]
    return out


def new_function(f):
    if not isinstance(f, dict) or "type" not in f:
        return f
    out = {k: v for k, v in f.items() if k not in ("function", "conditions")}
    for k, kind in _NESTED_FUNCTION_FIELDS.get(_short(_ns(f["type"])), {}).items():
        if k in out:
            out[k] = _map(out[k], kind, new_function, new_entry)
    if "condition" in out:
        out["condition"] = new_condition(out["condition"])
    return out


def _map(v, kind, fn, entry):
    if kind == "function":
        return fn(v)
    if kind == "function_list":
        return [fn(x) for x in v] if isinstance(v, list) else fn(v)
    if kind == "entry_list" and isinstance(v, list):
        return [entry(e) for e in v]
    return v


def old_condition(c):
    if isinstance(c, list):
        return [old_condition(x) for x in c]
    if not isinstance(c, dict) or not isinstance(c.get("condition"), str):
        return c
    sid = _short(_ns(c["condition"]))
    drop = {"type", "blocks", "state"} if sid == "block_state_property" else {"type"}
    out = {k: v for k, v in c.items() if k not in drop}
    return _nested_conditions(out, sid, old_condition)


def new_condition(c):
    if isinstance(c, list):
        return [new_condition(x) for x in c]
    if not isinstance(c, dict) or not isinstance(c.get("type"), str):
        return c
    sid = _short(_ns(c["type"]))
    drop = {"condition", "block", "properties"} if sid == "match_block" else {"condition"}
    out = {k: v for k, v in c.items() if k not in drop}
    return _nested_conditions(out, sid, new_condition)


def _nested_conditions(out, sid, fn):
    for k, kind in _NESTED_CONDITION_FIELDS.get(sid, {}).items():
        if k in out:
            out[k] = fn(out[k]) if kind == "condition" else (
                [fn(x) for x in out[k]] if isinstance(out[k], list) else out[k])
    return out


def old_entry(e):
    """An entry (a set_contents list in an item modifier written in both forms)."""
    if not isinstance(e, dict):
        return e
    tag = _short(e.get("type")) == "tag" and "name" in e
    out = {k: v for k, v in e.items() if k not in ("modifier", "condition") and not (tag and k == "items")}
    if isinstance(out.get("functions"), list):
        out["functions"] = [old_function(f) for f in out["functions"]]
    if isinstance(out.get("conditions"), list):
        out["conditions"] = [old_condition(c) for c in out["conditions"]]
    if isinstance(out.get("children"), list):
        out["children"] = [old_entry(c) for c in out["children"]]
    if _short(e.get("type")) == "loot_table" and isinstance(out.get("value"), dict):
        out["value"] = _table_view(out["value"], old_entry, ("modifier", "condition"))
    return out


def new_entry(e):
    if not isinstance(e, dict):
        return e
    tag = _short(e.get("type")) == "tag" and "items" in e
    out = {k: v for k, v in e.items() if k not in ("functions", "conditions") and not (tag and k == "name")}
    if "modifier" in out:
        out["modifier"] = _map(out["modifier"], "function_list", new_function, new_entry)
    if "condition" in out:
        out["condition"] = new_condition(out["condition"])
    if isinstance(out.get("children"), list):
        out["children"] = [new_entry(c) for c in out["children"]]
    if _short(e.get("type")) == "loot_table" and isinstance(out.get("value"), dict):
        out["value"] = _table_view(out["value"], new_entry, ("functions", "conditions"))
    return out


def _table_view(t, entry, drop):
    out = {k: v for k, v in t.items() if k not in drop}
    if isinstance(out.get("pools"), list):
        out["pools"] = [
            dict({k: v for k, v in p.items() if k not in drop},
                 **({"entries": [entry(x) for x in p["entries"]]} if isinstance(p.get("entries"), list) else {}))
            if isinstance(p, dict) else p for p in out["pools"]]
    return out


# --- reading both sides the way 26.3 does --------------------------------------------

def _norm_condition(c):
    if isinstance(c, list):
        c = {"type": "minecraft:all_of", "terms": c} if len(c) != 1 else c[0]
    if isinstance(c, dict):
        out = _norm(c, None)
        if out.get("type") == "minecraft:all_of" and isinstance(out.get("terms"), list) and len(out["terms"]) == 1:
            return out["terms"][0]
        return out
    return c


def _norm_modifier(m):
    if isinstance(m, dict) or isinstance(m, str):
        m = [m]
    if isinstance(m, list):
        return [_norm(x, None) for x in m]
    return m


def _norm(v, key):
    if key in ("modifier",) or key == "on_pass" or key == "on_fail":
        return _norm_modifier(v)
    if key in ("condition", "term"):
        return _norm_condition(v)
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k == "type" and isinstance(x, str):
                out[k] = _ns(x)
            elif k == "terms" and isinstance(x, list):
                out[k] = [_norm_condition(t) for t in x]
            else:
                out[k] = _norm(x, k)
        return out
    if isinstance(v, list):
        return [_norm(x, key) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _kind_of(v):
    """A function's or condition's type id, or a reference's name."""
    if isinstance(v, dict) and isinstance(v.get("type"), str):
        return v["type"]
    if isinstance(v, str):
        return v
    return None


def _first_difference(a, b, path: str):
    """``(path, want, have, how)``: ``how`` is ``order`` (same items, another order),
    ``type`` (another function or condition there), or ``value``."""
    if isinstance(a, dict) and isinstance(b, dict):
        ta, tb = a.get("type"), b.get("type")
        if isinstance(ta, str) and isinstance(tb, str) and ta != tb:
            return path, ta, tb, "type"
        for k in sorted(set(a) | set(b)):
            sub = f"{path}.{k}" if path else k
            if k not in a or k not in b:
                return sub, a.get(k, ABSENT), b.get(k, ABSENT), "value"
            d = _first_difference(a[k], b[k], sub)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) == len(b) and a != b and sorted(map(_key, a)) == sorted(map(_key, b)):
            return path, a, b, "order"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        if len(a) != len(b):
            n = min(len(a), len(b))
            return f"{path}[{n}]", (a[n] if len(a) > n else ABSENT), (b[n] if len(b) > n else ABSENT), "value"
        return None
    if a != b:
        return path, a, b, "value"
    return None


def _key(v) -> str:
    return json.dumps(v, sort_keys=True)


def _short_json(v, limit: int = 70) -> str:
    s = json.dumps(v, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit - 3] + "..."


def _explain(want, have, root: str, old_label: str) -> tuple[str, str]:
    """``(path, message)`` for normalised ``want`` (built from the old form) and
    ``have`` (what 26.3 reads)."""
    d = _first_difference(want, have, root)
    where, w, h, how = d if d else (root, want, have, "value")
    if how == "order":
        names = lambda xs: ", ".join(str(_kind_of(x) or _short_json(x, 40)) for x in xs)
        noun = ("items" if not all(_kind_of(x) for x in h) else
                "conditions" if "condition" in old_label else "functions")
        return where, (f"26.3 reads the same {len(h)} {noun} in another order ({names(h)}); the old form's "
                       f"{old_label} runs {names(w)}. They run in order, so the two forms disagree")
    if how == "type":
        return where, (f"26.3 reads a {h} here, where the old form's {old_label} has a {w}: "
                       f"the two forms disagree")
    if h is ABSENT:
        return where, f"26.3 reads nothing here; the old form's {old_label} gives {_short_json(w)}: 26.3 loses it"
    if w is ABSENT:
        return where, (f"26.3 reads {_short_json(h)} here, which the old form's {old_label} does not have: "
                       f"1.21 to 26.2 lose it")
    return where, (f"26.3 reads {_short_json(h)} here, but the old form's {old_label} gives {_short_json(w)}: "
                   f"the two forms disagree")


# --- the comparison ---------------------------------------------------------------------

def disagreements(kind: str, old, new, conv: Converter) -> list[tuple[str, str, str]]:
    """``(path, code, message)`` for every place the old form (as 1.21 to 26.2 read
    ``old``) and the 26.3 form (as 26.3 reads ``new``) differ. ``old`` and ``new``
    are the same object when one file serves both sides."""
    out: list[tuple[str, str, str]] = []
    if kind == "loot_table":
        if isinstance(old, dict) and isinstance(new, dict):
            _table(old, new, "", conv, out)
    elif kind == "item_modifier":
        if isinstance(old, list) and isinstance(new, dict):
            # 1.21 to 26.2 read a list file as a sequence (the converter writes it as one)
            old = {"function": "minecraft:sequence", "functions": old}
        _each(old, new, conv, out, _function_pair, "function")
    elif kind == "predicate":
        if isinstance(old, dict) and isinstance(new, dict):
            _condition_pair(old, new, "", conv, out)
    return out


def _each(old, new, conv, out, pair, what):
    if isinstance(old, dict) and isinstance(new, dict):
        pair(old, new, "", conv, out)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out.append(("", UNPAIRED, f"the old form lists {len(old)} {what}s and the 26.3 copy {len(new)}, so "
                                      f"they cannot be paired; compare them by hand"))
            return
        for i, (o, n) in enumerate(zip(old, new)):
            pair(o, n, f"[{i}]", conv, out)


def _function_pair(o, n, path, conv, out):
    if not (isinstance(o, dict) and "function" in o and isinstance(n, dict) and "type" in n):
        return   # one side has no form of its own here: the version check reports it
    want, have = _norm(conv.function(old_function(o)), None), _norm(new_function(n), None)
    if want != have:
        where, msg = _explain(want, have, path, "`function`")
        out.append((where, DISAGREE, msg))


def _condition_pair(o, n, path, conv, out):
    if not (isinstance(o.get("condition"), str) and isinstance(n.get("type"), str)):
        return
    want, have = _norm_condition(conv.condition(old_condition(o))), _norm_condition(new_condition(n))
    if want != have:
        where, msg = _explain(want, have, path, "`condition`")
        out.append((where, DISAGREE, msg))


def _join(path, k):
    return f"{path}.{k}" if path else k


def _paired(olds, news, path, what, out):
    """Pairs by position, or nothing (and a warning) when the two copies differ in length."""
    olds = olds if isinstance(olds, list) else []
    news = news if isinstance(news, list) else []
    if olds is news:
        return list(enumerate(zip(olds, news)))
    if len(olds) != len(news):
        out.append((path, UNPAIRED, f"the old form has {len(olds)} {what} here and the 26.3 copy {len(news)}, so "
                                    f"their functions and conditions cannot be paired; compare them by hand"))
        return []
    return list(enumerate(zip(olds, news)))


def _table(o: dict, n: dict, path: str, conv: Converter, out) -> None:
    _site(o, n, path, conv, out)
    for i, (op, np_) in _paired(o.get("pools"), n.get("pools"), _join(path, "pools"), "pools", out):
        if not (isinstance(op, dict) and isinstance(np_, dict)):
            continue
        pp = f"{_join(path, 'pools')}[{i}]"
        _site(op, np_, pp, conv, out)
        for j, (oe, ne) in _paired(op.get("entries"), np_.get("entries"), f"{pp}.entries", "entries", out):
            _entry(oe, ne, f"{pp}.entries[{j}]", conv, out)


def _entry(o, n, path: str, conv: Converter, out) -> None:
    if not (isinstance(o, dict) and isinstance(n, dict)):
        return
    _site(o, n, path, conv, out)
    for k, (oc, nc) in _paired(o.get("children"), n.get("children"), f"{path}.children", "children", out):
        _entry(oc, nc, f"{path}.children[{k}]", conv, out)
    if (_short(o.get("type")) == "loot_table" and isinstance(o.get("value"), dict)
            and _short(n.get("type")) == "loot_table" and isinstance(n.get("value"), dict)):
        _table(o["value"], n["value"], f"{path}.value", conv, out)
    if _short(o.get("type")) == "tag" and isinstance(o.get("name"), str) and "items" in n:
        want, have = _tagged(o["name"]), n["items"]
        if not (isinstance(have, str) and _tagged(have) == want):
            out.append((f"{path}.items", DISAGREE, f"26.3 reads `items` = {_short_json(have)}; the old form's "
                                                   f"`name` gives {_short_json(want)}"))


def _site(o: dict, n: dict, path: str, conv: Converter, out) -> None:
    for old_key, new_key, build in (("functions", "modifier", conv.function_list),
                                    ("conditions", "condition", conv.condition_list)):
        if not isinstance(o.get(old_key), list):
            if new_key in n and old_key not in o and new_key not in o and n[new_key] not in (None, [], {}):
                # only the 26.3 copy has it (another file): the old side never reads it
                out.append((_join(path, new_key), DISAGREE,
                            f"26.3 reads `{new_key}` = {_short_json(n[new_key])}, but the old form has no "
                            f"`{old_key}` here: 1.21 to 26.2 lose it"))
            continue
        expected = build(o[old_key])
        if new_key not in n:
            if old_key in n or expected is None:
                continue   # the 26.3 copy is in the old form: the version check reports it
            out.append((_join(path, new_key), DISAGREE,
                        f"26.3 reads no `{new_key}` here; the old form's `{old_key}` gives "
                        f"{_short_json(expected)}: 26.3 loses it"))
            continue
        _compare(new_key, old_key, expected, n[new_key], path, out)


def _compare(new_key: str, old_key: str, expected, actual, path, out) -> None:
    where = _join(path, new_key)
    if expected is None:
        # an empty old form: 26.3 must read nothing either
        if actual in (None, [], {}):
            return
        out.append((where, DISAGREE, f"the old form's `{old_key}` is empty, but 26.3 reads `{new_key}` = "
                                     f"{_short_json(actual)}: 1.21 to 26.2 lose it"))
        return
    a, b = _norm(expected, new_key), _norm(actual, new_key)
    if a == b:
        return
    if actual in (None, [], {}):
        out.append((where, DISAGREE, f"26.3 reads `{new_key}`, which is empty; the old form's `{old_key}` "
                                     f"gives {_short_json(expected)}: 26.3 loses it"))
        return
    at, msg = _explain(a, b, where, f"`{old_key}`")
    out.append((at, DISAGREE, msg))
