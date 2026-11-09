"""Do the two loot forms a pack carries say the same thing?

A loot table written for 1.21 to 26.3 carries both forms: ``functions`` /
``conditions`` (1.21 to 26.2) and ``modifier`` / ``condition`` (26.3). Each
version reads only its own, so the pack works on every version only if the two
agree. A ``modifier`` missing a function the old form has is the issue-93 loss
on 26.3 again, with both keys present.

The two forms can sit side by side in one file, or in two files: a base file and
a pack overlay that only one side loads. Either way, what the old side reads is
compared with what 26.3 reads. In one file everything but the loot forms is shared,
so only those are compared; across two files the whole table is: the old table is
converted to the 26.3 form and must equal the overlay's, every field, every pool
and entry. Pools, and the entries of a pool, are paired by content, since their
order does not change what a chest rolls; one left without a partner is an error. Item modifier and predicate files carry both
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
* an id with no namespace is ``minecraft:``, as the game reads it (any string in
  id form: item and entry names, tags, references, type ids); ``1.0`` is ``1``;
* key order does not matter.
"""
from __future__ import annotations

import json
import re
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
BLANK_MAP = "blank-map"       # a 26.3 exploration_map on a plain minecraft:map: ERROR

# 26.3: exploration_map writes the map data onto whatever item it is given
# (MapItem.applyNewSavedData on the input stack, no item check) and no longer turns
# minecraft:map into a filled map, so a plain map stays blank. Vanilla names each
# map's own item instead and then keeps only filled ones; the entry's name is shared
# by both forms and those items do not exist before 26.3, so a map entry written for
# both keeps minecraft:map and its 26.3 form sets the item first. Which item goes with
# which destination, from vanilla 26.3's chests and cartographer trades:
MAP_ITEMS = {
    "minecraft:on_treasure_maps": "minecraft:buried_treasure_map",
    "minecraft:on_ancient_city_maps": "minecraft:buried_ancient_city_map",
    "minecraft:on_buried_trial_chambers_maps": "minecraft:buried_trial_chambers_map",
    "minecraft:on_mineshaft_maps": "minecraft:buried_mineshaft_map",
    "minecraft:on_desert_pyramid_maps": "minecraft:desert_pyramid_map",
    "minecraft:on_jungle_pyramid_maps": "minecraft:jungle_pyramid_map",
    "minecraft:on_ocean_ruin_warm_maps": "minecraft:warm_ocean_ruins_map",
    "minecraft:on_woodland_mansion_maps": "minecraft:woodland_mansion_map",
    "minecraft:on_ocean_monument_maps": "minecraft:ocean_monument_map",
    "minecraft:on_swamp_hut_maps": "minecraft:swamp_hut_map",
    "minecraft:on_desert_village_maps": "minecraft:desert_village_map",
    "minecraft:on_plains_village_maps": "minecraft:plains_village_map",
    "minecraft:on_savanna_village_maps": "minecraft:savanna_village_map",
    "minecraft:on_snowy_village_maps": "minecraft:snowy_village_map",
    "minecraft:on_taiga_village_maps": "minecraft:taiga_village_map",
}
ANY_MAP_ITEM = "<any 26.3 map item>"   # a destination vanilla has no map item for: any one will do
KEEP_FILLED = {"type": "minecraft:filtered", "item_filter": {"predicates": {"minecraft:map_id": {}}},
               "on_fail": {"type": "minecraft:discard"}}


def map_item_for(destination) -> str | None:
    """The 26.3 map item vanilla uses for an exploration_map destination."""
    if not isinstance(destination, str):
        return None
    tag = destination.lstrip("#")
    tag = tag if ":" in tag else "minecraft:" + tag
    if tag.startswith("minecraft:on_abandoned_camp_"):
        return "minecraft:abandoned_camp_map"
    return MAP_ITEMS.get(tag)


def is_map_item(item) -> bool:
    """An item 26.3 can write a map onto and show as one (not the blank minecraft:map)."""
    if not isinstance(item, str):
        return False
    item = item if ":" in item else "minecraft:" + item
    return item.endswith("_map") and item not in ("minecraft:map", "minecraft:exploration_map")


def _plain_map_entry(e) -> bool:
    return (isinstance(e, dict) and _short(e.get("type")) == "item"
            and isinstance(e.get("name"), str) and _short(_ns(e["name"])) == "map")


def _steps(m) -> list:
    return m if isinstance(m, list) else [] if m is None else [m]


def _kind(f) -> str | None:
    return _short(_ns(f.get("type", f.get("function")))) if isinstance(f, dict) else None


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


_BARE_ID = re.compile(r"^#?[a-z0-9_.\-/]+$")


def _ns_id(v):
    """A string in id form with no namespace, as the game reads it: ``minecraft:``.
    Both sides are normalised alike, so a string that only looks like an id (a word
    such as ``this``) gets the same prefix on each and still compares equal."""
    if isinstance(v, str) and _BARE_ID.match(v):
        return "#minecraft:" + v[1:] if v.startswith("#") else "minecraft:" + v
    return v


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

    def entry_function_list(self, e: dict, funcs):
        """An entry's ``functions`` in 26.3 form. On a plain ``minecraft:map`` each
        exploration_map gets the map item set before it (the one vanilla uses for that
        destination, or any map item where vanilla has none) and only filled maps kept
        after it, as vanilla 26.3 writes its maps."""
        m = self.function_list(funcs)
        if not _plain_map_entry(e) or m is None:
            return m
        out, has_item = [], False
        for f in _steps(m):
            kind = _kind(f)
            if kind == "set_item" and is_map_item(f.get("item")):
                has_item = True
            if kind == "exploration_map" and not has_item:
                out += [{"type": "minecraft:set_item", "item": map_item_for(f.get("destination")) or ANY_MAP_ITEM},
                         f, json.loads(json.dumps(KEEP_FILLED))]
                has_item = True
                continue
            out.append(f)
        return out if len(out) != 1 else out[0]

    def _site_new_only(self, o: dict, entry: bool = False) -> dict:
        """``functions`` / ``conditions`` replaced by the 26.3 keys built from them
        (the script's ``with_new_keys`` then dropping the old keys)."""
        if "functions" in o:
            v = o.pop("functions")
            o.pop("modifier", None)
            m = (self.entry_function_list(o, v) if entry else self.function_list(v)) if isinstance(v, list) else None
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
        e = self._site_new_only(e, entry=True)
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
    return _ns_id(c)


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
    return _ns_id(v)


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
    if a != b and not _any_map(a, b):
        return path, a, b, "value"
    return None


def _key(v) -> str:
    return json.dumps(v, sort_keys=True)


def _short_json(v, limit: int = 70) -> str:
    s = json.dumps(v, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit - 3] + "..."


def _explain(want, have, root: str, old_label: str | None) -> tuple[str, str]:
    """``(path, message)`` for the first difference between normalised ``want``
    (built from the old form) and ``have`` (what 26.3 reads)."""
    d = _first_difference(want, have, root)
    if d is None:
        return root, None
    where, w, h, how = d
    return where, _say(w, h, how, old_label, where)


def _say(w, h, how: str, old_label: str | None, where: str) -> str:
    src = f"the old form's {old_label}" if old_label else "the old form"
    if how == "order":
        names = lambda xs: ", ".join(_describe(x) for x in xs)
        return (f"26.3 reads the same {len(h)} {_noun(where, len(h), old_label)} in another order "
                f"({names(h)}); {src} runs {names(w)}. They run in order, so the two forms disagree")
    if how in ("shape", "unpaired"):
        if how == "shape":
            (nw, lost), (nh, extra) = (len(w), _minus(w, h)), (len(h), _minus(h, w))
        else:
            (nw, lost), (nh, extra) = w, h
        parts = ([f"26.3 lacks {'; '.join(_describe(x) for x in lost)}"] if lost else []) + \
                ([f"only 26.3 has {'; '.join(_describe(x) for x in extra)}"] if extra else [])
        end = ("26.3 loses it" if lost and not extra else "1.21 to 26.2 lose it" if extra and not lost
               else "the two forms disagree")
        return (f"26.3 reads {nh} {_noun(where, nh, old_label)} here, where {src} has {nw} "
                f"({', '.join(parts)}): {end}")
    if how == "type":
        return f"26.3 reads a {h} here, where {src} has a {w}: the two forms disagree"
    if h is ABSENT:
        return f"26.3 reads nothing here; {src} gives {_short_json(w)}: 26.3 loses it"
    if w is ABSENT:
        return f"26.3 reads {_short_json(h)} here, which {src} does not have: 1.21 to 26.2 lose it"
    return f"26.3 reads {_short_json(h)} here, but {src} gives {_short_json(w)}: the two forms disagree"


_NOUNS = {"pools": ("pool", "pools"), "entries": ("entry", "entries"), "children": ("child", "children"),
          "functions": ("function", "functions"), "conditions": ("condition", "conditions"),
          "items": ("item", "items")}


def _noun(where: str, count: int, old_label: str | None) -> str:
    last = where.rsplit(".", 1)[-1].split("[", 1)[0]
    if last in ("pools", "entries", "children"):
        kind = last
    elif last in ("modifier", "functions") or (old_label and "function" in old_label):
        kind = "functions"
    elif last in ("condition", "terms") or (old_label and "condition" in old_label):
        kind = "conditions"
    else:
        kind = "items"
    return _NOUNS[kind][0 if count == 1 else 1]


def _describe(v) -> str:
    """A short name for a pool, entry, function or condition."""
    if isinstance(v, dict):
        if isinstance(v.get("entries"), list):
            names = [_describe(e) for e in v["entries"][:3]]
            return "a pool of " + ", ".join(names) + (" ..." if len(v["entries"]) > 3 else "")
        if isinstance(v.get("name"), str):
            return v["name"]
        if isinstance(v.get("type"), str):
            return v["type"]
    if isinstance(v, str):
        return v
    return _short_json(v, 40)


def _minus(a: list, b: list) -> list:
    """The items of ``a`` that ``b`` lacks, counting repeats."""
    left = [_key(x) for x in b]
    out = []
    for x in a:
        k = _key(x)
        if k in left:
            left.remove(k)
        else:
            out.append(x)
    return out


def _differences(a, b, path: str, found: list) -> None:
    """Every difference, not only the first: ``(path, want, have, how)``. Lists of
    another length are one ``shape`` difference (nothing below them pairs up)."""
    if isinstance(a, dict) and isinstance(b, dict):
        ta, tb = a.get("type"), b.get("type")
        if isinstance(ta, str) and isinstance(tb, str) and ta != tb:
            found.append((path, ta, tb, "type"))
            return
        for k in sorted(set(a) | set(b)):
            sub = f"{path}.{k}" if path else k
            if k not in a or k not in b:
                found.append((sub, a.get(k, ABSENT), b.get(k, ABSENT), "value"))
            else:
                _differences(a[k], b[k], sub, found)
        return
    if isinstance(a, list) and isinstance(b, list):
        if a == b:
            return
        if _unordered(path):
            _pair_unordered(a, b, path, found)
        elif len(a) != len(b):
            found.append((path, a, b, "shape"))
        elif sorted(map(_key, a)) == sorted(map(_key, b)):
            found.append((path, a, b, "order"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                _differences(x, y, f"{path}[{i}]", found)
        return
    if a != b and not _any_map(a, b):
        found.append((path, a, b, "value"))


def _any_map(want, have) -> bool:
    return want == ANY_MAP_ITEM and is_map_item(have)


def _unordered(path: str) -> bool:
    """Pools, and the entries of a pool: their order does not change what a chest
    rolls. (A set_contents list, and an entry's children, keep their order.)"""
    head, _, last = path.rpartition(".")
    if last == "pools":
        return True
    return last == "entries" and head.rpartition(".")[2].startswith("pools[")


def _ident(v):
    """What makes a pool or entry the same one, changed: an entry's type and name, a
    pool's entries."""
    if isinstance(v, dict):
        if isinstance(v.get("entries"), list):
            return ("pool",) + tuple(sorted(str(_ident(e)) for e in v["entries"]))
        name = v.get("name", v.get("value"))
        return (v.get("type"), name if isinstance(name, str) else None)
    return (_key(v),)


def _pair_unordered(a: list, b: list, path: str, found: list) -> None:
    """Pairs by content: the same item, then the same pool or entry changed, then
    what is left in order when as many are left on each side. The rest is unpaired."""
    rest_a, rest_b = list(range(len(a))), list(range(len(b)))
    for i in list(rest_a):
        j = next((j for j in rest_b if _key(b[j]) == _key(a[i])), None)
        if j is not None:
            rest_a.remove(i)
            rest_b.remove(j)
    pairs = []
    for i in list(rest_a):
        j = next((j for j in rest_b if _ident(b[j]) == _ident(a[i])), None)
        if j is not None:
            pairs.append((i, j))
            rest_a.remove(i)
            rest_b.remove(j)
    if len(rest_a) == len(rest_b):
        pairs += list(zip(rest_a, rest_b))
        rest_a, rest_b = [], []
    for i, j in sorted(pairs, key=lambda ij: ij[1]):
        _differences(a[i], b[j], f"{path}[{j}]", found)   # the 26.3 copy's position
    if rest_a or rest_b:
        found.append((path, (len(a), [a[i] for i in rest_a]), (len(b), [b[j] for j in rest_b]), "unpaired"))


# --- the comparison ---------------------------------------------------------------------

def disagreements(kind: str, old, new, conv: Converter) -> list[tuple[str, str, str]]:
    """``(path, code, message)`` for every place the old form (as 1.21 to 26.2 read
    ``old``) and the 26.3 form (as 26.3 reads ``new``) differ. ``old`` and ``new``
    are the same object when one file serves both sides."""
    out: list[tuple[str, str, str]] = []
    if kind == "loot_table":
        if isinstance(old, dict) and isinstance(new, dict):
            if old is new:
                _table(old, "", conv, out)
            else:
                _whole_table(old, new, conv, out)
    elif kind == "item_modifier":
        if isinstance(old, list) and isinstance(new, dict):
            # 1.21 to 26.2 read a list file as a sequence (the converter writes it as one)
            old = {"function": "minecraft:sequence", "functions": old}
        _each(old, new, conv, out, _function_pair)
    elif kind == "predicate":
        if isinstance(old, dict) and isinstance(new, dict):
            _condition_pair(old, new, "", conv, out)
    return out


def _whole_table(old: dict, new: dict, conv: Converter, out) -> None:
    """A base file and an overlay: the old table, converted to the 26.3 form the way
    the converter writes it, must be the table 26.3 reads, every field of it."""
    want = _norm(conv.table_new_only(_table_view(old, old_entry, ("modifier", "condition"))), None)
    have = _norm(_table_view(new, new_entry, ("functions", "conditions")), None)
    found: list = []
    _differences(want, have, "", found)
    for where, w, h, how in found:
        out.append((where, DISAGREE, _say(w, h, how, None, where)))


def _each(old, new, conv, out, pair):
    if isinstance(old, dict) and isinstance(new, dict):
        pair(old, new, "", conv, out)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out.append(("", DISAGREE, _say(old, new, "shape", None, "functions")))
            return
        for i, (o, n) in enumerate(zip(old, new)):
            pair(o, n, f"[{i}]", conv, out)


def _function_pair(o, n, path, conv, out):
    if not (isinstance(o, dict) and "function" in o and isinstance(n, dict) and "type" in n):
        return   # one side has no form of its own here: the version check reports it
    want, have = _norm(conv.function(old_function(o)), None), _norm(new_function(n), None)
    if want != have:
        where, msg = _explain(want, have, path, "`function`")
        if msg:
            out.append((where, DISAGREE, msg))


def _condition_pair(o, n, path, conv, out):
    if not (isinstance(o.get("condition"), str) and isinstance(n.get("type"), str)):
        return
    want, have = _norm_condition(conv.condition(old_condition(o))), _norm_condition(new_condition(n))
    if want != have:
        where, msg = _explain(want, have, path, "`condition`")
        if msg:
            out.append((where, DISAGREE, msg))


def _join(path, k):
    return f"{path}.{k}" if path else k


def _list(v) -> list:
    return v if isinstance(v, list) else []


# One file: everything but the loot forms is shared, so only the places that carry
# both forms are compared.

def _table(t: dict, path: str, conv: Converter, out) -> None:
    _site(t, path, conv, out)
    for i, p in enumerate(_list(t.get("pools"))):
        if not isinstance(p, dict):
            continue
        pp = f"{_join(path, 'pools')}[{i}]"
        _site(p, pp, conv, out)
        for j, e in enumerate(_list(p.get("entries"))):
            _entry(e, f"{pp}.entries[{j}]", conv, out)


def _entry(e, path: str, conv: Converter, out) -> None:
    if not isinstance(e, dict):
        return
    _site(e, path, conv, out, entry=True)
    for k, c in enumerate(_list(e.get("children"))):
        _entry(c, f"{path}.children[{k}]", conv, out)
    if _short(e.get("type")) == "loot_table" and isinstance(e.get("value"), dict):
        _table(e["value"], f"{path}.value", conv, out)
    if _short(e.get("type")) == "tag" and isinstance(e.get("name"), str) and "items" in e:
        want, have = _tagged(e["name"]), e["items"]
        if not (isinstance(have, str) and _ns_id(_tagged(have)) == _ns_id(want)):
            out.append((f"{path}.items", DISAGREE, f"26.3 reads `items` = {_short_json(have)}; the old form's "
                                                   f"`name` gives {_short_json(want)}"))


def _site(obj: dict, path: str, conv: Converter, out, entry: bool = False) -> None:
    if isinstance(obj.get("functions"), list) and "modifier" in obj:
        expected = conv.entry_function_list(obj, obj["functions"]) if entry else conv.function_list(obj["functions"])
        _compare("modifier", "functions", expected, obj["modifier"], path, out)
    if isinstance(obj.get("conditions"), list) and "condition" in obj:
        _compare("condition", "conditions", conv.condition_list(obj["conditions"]), obj["condition"], path, out)


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
    if msg:
        out.append((at, DISAGREE, msg))


# --- 26.3 map entries -----------------------------------------------------------------------

def blank_maps(table) -> list[tuple[str, str]]:
    """``(path, message)`` for each 26.3 ``exploration_map`` that runs on a plain
    ``minecraft:map``, wherever it sits (on the entry, its pool or the table): a blank
    map on 26.3. And for one with a condition on a map the 26.3 form gave its map item
    first: a failed condition there no longer leaves the plain map 26.2 gave.

    The items are followed as the game runs the steps: an entry's own modifier, then its
    pool's, then the table's. ``plain`` are the entries whose item is still a plain map,
    ``was`` those a ``set_item`` turned from one into a map item."""
    out: list[tuple[str, str]] = []

    def run(steps, plain, was, where, own):
        for i, f in enumerate(steps):
            kind = _kind(f)
            if kind == "set_item" and isinstance(f.get("item"), str):
                item = _ns(f["item"])
                if is_map_item(item):
                    plain, was = [], was + plain
                else:
                    plain, was = ([own] if item == "minecraft:map" else []), []
            elif kind == "exploration_map":
                if plain:
                    out.append((where, _blank_message(f, plain, own)))
                elif was and f.get("condition") is not None:
                    filtered = any(_kind(g) == "filtered" for g in steps[i + 1:])
                    out.append((where, _chance_message(filtered)))
                plain, was = [], []   # said once, where the map function runs
        return plain, was

    def entry(e, path):
        """(plain, was) for what this entry hands its pool."""
        if not isinstance(e, dict):
            return [], []
        plain: list[str] = []
        was: list[str] = []
        for k, c in enumerate(_list(e.get("children"))):
            p, w = entry(c, f"{path}.children[{k}]")
            plain, was = plain + p, was + w
        kind = _short(_ns(e.get("type")))
        if kind == "item" and isinstance(e.get("name"), str) and _ns(e["name"]) == "minecraft:map":
            plain = [path]
        elif kind == "loot_table" and isinstance(e.get("value"), dict):
            plain, was = table_(e["value"], f"{path}.value")
        steps = _steps(e.get("modifier"))
        for i, f in enumerate(steps):
            if _kind(f) == "set_contents":
                for j, x in enumerate(_list(f.get("entries"))):
                    entry(x, f"{path}.modifier[{i}].entries[{j}]")   # inside a container
        if kind in ("item", "loot_table"):
            plain, was = run(steps, plain, was, f"{path}.modifier", path)
        return plain, was

    def table_(t, path):
        plain: list[str] = []
        was: list[str] = []
        for i, p in enumerate(_list(t.get("pools"))):
            if not isinstance(p, dict):
                continue
            pp = f"{_join(path, 'pools')}[{i}]"
            pl: list[str] = []
            pw: list[str] = []
            for j, e in enumerate(_list(p.get("entries"))):
                a, b = entry(e, f"{pp}.entries[{j}]")
                pl, pw = pl + a, pw + b
            a, b = run(_steps(p.get("modifier")), pl, pw, f"{pp}.modifier", pp)
            plain, was = plain + a, was + b
        return run(_steps(t.get("modifier")), plain, was, _join(path, "modifier"), path or "the table")

    if isinstance(table, dict):
        table_(table, "")
    return out


def _blank_message(f, plain: list[str], own: str) -> str:
    dest = f.get("destination")
    item = map_item_for(dest)
    steps = (f"set the item first (set_item {item or 'a map item'}"
             f"{', the one vanilla uses for ' + str(dest) if item else ''}) and keep only filled maps after it "
             "(filtered on minecraft:map_id, on_fail discard), as vanilla 26.3 does")
    why = "exploration_map writes the map onto the item it is given and no longer turns minecraft:map into a filled map"
    if plain == [own]:
        return f"{why}, so this gives a blank map. In the 26.3 form, {steps}"
    which = ", ".join(plain[:3]) + (f" and {len(plain) - 3} more" if len(plain) > 3 else "")
    return (f"this exploration_map runs on the plain minecraft:map from {which}, and {why[len('exploration_map '):]}, "
            f"so that gives a blank map. Move it onto the map entry and, in its 26.3 form, {steps}")


def _chance_message(filtered: bool) -> str:
    lost = ("nothing: the filter after it throws the unfilled map away" if filtered
            else "a map item with no map on it")
    return ("this exploration_map has a condition. Before 26.3 a failed condition leaves the plain minecraft:map "
            f"as an empty map, but the 26.3 form sets the map item first, so there a failed condition gives {lost}. "
            "Put the condition on the entry instead, in both forms, so both give a filled map or nothing")
