"""Do the two loot forms in one file say the same thing?

A loot table written for 1.21 to 26.3 in one file carries both forms side by
side: ``functions`` / ``conditions`` (1.21 to 26.2) and ``modifier`` /
``condition`` (26.3). Each version reads only its own, so the file works on every
version only if the two agree. A ``modifier`` missing a function the old form has
is the issue-93 loss on 26.3 again, with both keys present.

This builds the 26.3 form from the old one, the way MFR's ``scripts/loot_26_3.py``
writes it (Moog's Structure Lib's renames plus ``functions`` -> ``modifier`` and
26.3's deeper renames), and compares it with what the file has, wherever a table,
pool or entry carries both. The comparison reads both sides the way 26.3 does:

* a single ``modifier`` object and a one-item list are the same, as are one
  condition and an ``all_of`` of just that condition, and a condition list and
  an ``all_of`` of its items;
* a type id with no namespace is ``minecraft:``; ``1.0`` is ``1``;
* key order does not matter.
"""
from __future__ import annotations

from typing import Iterable

LOOT_RENAME = (26, 3)   # the first version that reads `modifier` / `condition` instead

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


# --- reading both sides the way 26.3 does --------------------------------------------

def _norm_condition(c):
    if isinstance(c, list):
        c = {"type": "minecraft:all_of", "terms": c} if len(c) != 1 else c[0]
    if isinstance(c, dict):
        out = {k: _norm(v, k) for k, v in c.items()}
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


def _first_difference(a, b, path: str) -> tuple[str, object, object] | None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            sub = f"{path}.{k}" if path else k
            if k not in a or k not in b:
                return sub, a.get(k, "(absent)"), b.get(k, "(absent)")
            d = _first_difference(a[k], b[k], sub)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        if len(a) != len(b):
            return f"{path}[{min(len(a), len(b))}]", (a[len(b)] if len(a) > len(b) else "(absent)"), \
                (b[len(a)] if len(b) > len(a) else "(absent)")
        return None
    if a != b:
        return path, a, b
    return None


def _short_json(v, limit: int = 70) -> str:
    import json
    s = v if isinstance(v, str) and v in ("(absent)",) else json.dumps(v, separators=(",", ":"))
    return s if len(s) <= limit else s[:limit - 3] + "..."


# --- the comparison ---------------------------------------------------------------------

def disagreements(table, conv: Converter) -> list[tuple[str, str]]:
    """``(path, message)`` for every place a table carries both forms that differ."""
    out: list[tuple[str, str]] = []
    if isinstance(table, dict):
        _table(table, "", conv, out)
    return out


def _table(t: dict, path: str, conv: Converter, out) -> None:
    _site(t, path, conv, out)
    for i, p in enumerate(t.get("pools") or [] if isinstance(t.get("pools"), list) else []):
        if not isinstance(p, dict):
            continue
        pp = f"{path}.pools[{i}]" if path else f"pools[{i}]"
        _site(p, pp, conv, out)
        for j, e in enumerate(p.get("entries") or [] if isinstance(p.get("entries"), list) else []):
            _entry(e, f"{pp}.entries[{j}]", conv, out)


def _entry(e, path: str, conv: Converter, out) -> None:
    if not isinstance(e, dict):
        return
    _site(e, path, conv, out)
    for k, c in enumerate(e.get("children") or [] if isinstance(e.get("children"), list) else []):
        _entry(c, f"{path}.children[{k}]", conv, out)
    if _short(e.get("type")) == "loot_table" and isinstance(e.get("value"), dict):
        _table(e["value"], f"{path}.value", conv, out)
    if _short(e.get("type")) == "tag" and isinstance(e.get("name"), str) and "items" in e:
        want, have = _tagged(e["name"]), e["items"]
        if not (isinstance(have, str) and _tagged(have) == want):
            out.append((f"{path}.items", f"26.3 reads `items` = {_short_json(have)}; the old form's "
                                          f"`name` gives {_short_json(want)}"))


def _site(obj: dict, path: str, conv: Converter, out) -> None:
    join = (lambda k: f"{path}.{k}" if path else k)
    if "functions" in obj and "modifier" in obj and isinstance(obj["functions"], list):
        _compare("modifier", "functions", conv.function_list(obj["functions"]), obj["modifier"], join, out)
    if isinstance(obj.get("conditions"), list) and "condition" in obj:
        _compare("condition", "conditions", conv.condition_list(obj["conditions"]), obj["condition"], join, out)


def _compare(new_key: str, old_key: str, expected, actual, join, out) -> None:
    if expected is None:
        # an empty old form: 26.3 must read nothing either
        if actual in (None, [], {}):
            return
        out.append((join(new_key), f"the old form's `{old_key}` is empty, but 26.3 reads `{new_key}` = "
                                   f"{_short_json(actual)}: 1.21 to 26.2 lose it"))
        return
    a, b = _norm(expected, new_key), _norm(actual, new_key)
    if a == b:
        return
    if actual in (None, [], {}):
        out.append((join(new_key), f"26.3 reads `{new_key}`, which is empty; the old form's `{old_key}` "
                                   f"gives {_short_json(expected)}: 26.3 loses it"))
        return
    d = _first_difference(a, b, new_key)
    where, want, have = d if d else (new_key, a, b)
    out.append((join(where), f"26.3 reads {_short_json(have)} here, but the old form's `{old_key}` "
                             f"gives {_short_json(want)}: the two forms disagree"))
