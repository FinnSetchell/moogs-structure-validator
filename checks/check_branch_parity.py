"""A mod's two datapack branches differ only where Minecraft forces it (warn-only).

A Moog structure mod ships its structures from a 1.20 and a 1.21 datapack branch,
and the same structure should spawn the same way on both. This check compares this
checkout's worldgen JSON with the other branch's, folder by folder: template pools,
structures, structure sets, processor lists. Each file that differs for no version
reason warns, with the values on each side, and the files one branch has and the
other does not are listed.

The other branch is named in ``validator.json`` as ``"compare_branch"`` (or with
``--compare-branch``), and read from git: that branch's last commit, or
``origin/<branch>`` when only that is fetched. Without the setting, or when this
clone does not have the branch (a CI checkout of one branch), it says so and passes.

Left out, as each branch's Minecraft versions force them:

* every ``location`` and ``locations`` in a pool: each branch names its own NBTs
  (a pool with more or fewer elements names its extra pieces by file name);
* a pool's ``name``, which no version reads;
* an item written in the old form (``tag``, ``Count``) on one branch and the 1.20.5
  form (``components``, ``count``) on the other, as in MSL's armour stand processor:
  the two forms are not compared;
* ``override_liquid_settings`` on pool elements, and ``liquid_settings``,
  ``dimension_padding`` and ``pool_aliases`` on structures, which 1.20 does not read
  (pool aliases arrived in 1.20.5, past most of a 1.20 branch);
* processors MSL registers on one side of 1.21 only (``_MSL_TYPE_WINDOWS``: the
  waterlogging fix, trial spawner and vault processors), and a processor list that
  holds nothing else.

Worldgen folders keep the same names on every version, so the plural data folders
of 1.20 do not come into it. The order of a structure set's ``structures`` or a pool's
``elements`` does not count either: both pick by weight.
"""
from __future__ import annotations

import io
import json
import subprocess
import tarfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from checks.check_worldgen_schemas import _MSL_TYPE_WINDOWS
from core.context import services

if TYPE_CHECKING:
    from core.context import ValidatorContext

_FOLDERS = ("template_pool", "structure", "structure_set", "processor_list")
_POOL_FORCED = {"location", "locations", "override_liquid_settings"}
# The item stack keys before 1.20.5 and from it: one on each side is the format change.
_ITEM_FORMS = (("tag", "components"), ("Count", "count"))
_STRUCTURE_FORCED = {"liquid_settings", "dimension_padding", "pool_aliases"}
_MAX_LINES = 6


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    except OSError:
        return None   # no git on this machine


def _resolve(root: Path, branch: str) -> str | None:
    for ref in (branch, f"origin/{branch}"):
        done = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if done is not None and done.returncode == 0:
            return ref
    return None


def _read_branch(worldgen: Path, ref: str) -> dict[str, dict[str, object]] | None:
    """``{folder: {file: data}}`` of the ref's worldgen at this checkout's worldgen
    path; None when the ref has nothing there."""
    done = _git(worldgen, "rev-parse", "--show-toplevel", "--show-prefix")
    if done is None or done.returncode != 0:
        return None
    top, prefix = done.stdout.decode().splitlines()[:2]
    archive = _git(Path(top), "archive", "--format=tar", ref, "--", prefix)
    if archive is None or archive.returncode != 0:
        return None
    out: dict[str, dict[str, object]] = {f: {} for f in _FOLDERS}
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        for member in tar.getmembers():
            if not (member.isfile() and member.name.startswith(prefix) and member.name.endswith(".json")):
                continue
            folder, _, rel = member.name[len(prefix):].partition("/")
            if folder in out and rel:
                try:
                    out[folder][rel] = json.loads(tar.extractfile(member).read().decode("utf-8-sig"))
                except ValueError:
                    continue   # check_data_formats reports JSON that does not parse, on its own branch
    return out


def _strip(value, keys: set[str]):
    if isinstance(value, dict):
        return {k: _strip(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip(v, keys) for v in value]
    return value


def _windowed(proc) -> bool:
    return isinstance(proc, dict) and proc.get("processor_type") in _MSL_TYPE_WINDOWS


def _normalized(folder: str, data):
    """The file without what a branch's versions force on it."""
    if not isinstance(data, dict):
        return data
    if folder == "template_pool":
        return {k: v for k, v in _strip(data, _POOL_FORCED).items() if k != "name"}
    if folder == "structure":
        return {k: v for k, v in data.items() if k not in _STRUCTURE_FORCED}
    if folder == "processor_list" and isinstance(data.get("processors"), list):
        return {**data, "processors": [p for p in data["processors"] if not _windowed(p)]}
    return data


def _forced_alone(folder: str, data) -> bool:
    """A file one branch needs for its versions only: a list of windowed processors."""
    procs = data.get("processors") if folder == "processor_list" and isinstance(data, dict) else None
    return isinstance(procs, list) and bool(procs) and all(_windowed(p) for p in procs)


def _short(value) -> str:
    text = json.dumps(value)
    return text if len(text) <= 70 else text[:67] + "..."


def _diff(a, b, path: str, other: str) -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        skip = {k for old, new in _ITEM_FORMS
                if ((old in a and new in b) or (new in a and old in b))
                and not (old in a and new in a) and not (old in b and new in b) for k in (old, new)}
        for key in [k for k in a if k not in skip] + [k for k in b if k not in a and k not in skip]:
            at = f"{path} > {key}" if path else str(key)
            if key not in b:
                out.append(f"{at}: {_short(a[key])} here, unset on {other}")
            elif key not in a:
                out.append(f"{at}: unset here, {_short(b[key])} on {other}")
            else:
                out += _diff(a[key], b[key], at, other)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path} > {i}" if path else str(i), other)
        return out
    return [] if a == b else [f"{path or '(root)'}: {_short(a)} here, {_short(b)} on {other}"]


def _member(canon: str) -> str:
    entry = json.loads(canon)
    if isinstance(entry, dict) and "structure" in entry:
        return f"{entry['structure']} (weight {entry.get('weight')})"
    return _short(entry)


def _set_diff(a, b, other: str) -> list[str]:
    """A structure set's members as a multiset, then everything else as usual."""
    if not (isinstance(a, dict) and isinstance(b, dict)
            and isinstance(a.get("structures"), list) and isinstance(b.get("structures"), list)):
        return _diff(a, b, "", other)
    here = Counter(map(_canon, a["structures"]))
    there = Counter(map(_canon, b["structures"]))
    out = []
    if here - there:
        out.append(f"structures: only here: {', '.join(_member(e) for e in (here - there).elements())}")
    if there - here:
        out.append(f"structures: only on {other}: {', '.join(_member(e) for e in (there - here).elements())}")
    a, b = ({k: v for k, v in d.items() if k != "structures"} for d in (a, b))
    return out + _diff(a, b, "", other)


def _pieces(raw) -> Counter:
    """The file names of the NBTs a pool's elements name, the same on both branches
    whatever version folders they sit in."""
    out: Counter = Counter()
    for entry in raw.get("elements", []) if isinstance(raw, dict) else []:
        element = entry.get("element") if isinstance(entry, dict) else None
        location = element.get("location") if isinstance(element, dict) else None
        if isinstance(location, str):
            out[location.rsplit("/", 1)[-1].rsplit(":", 1)[-1]] += 1
    return out


def _pool_diff(a, b, raw_a, raw_b, other: str) -> list[str]:
    """A pool's elements as a multiset; position by position only when they line up."""
    ea, eb = (d.get("elements") if isinstance(d, dict) else None for d in (a, b))
    if not (isinstance(ea, list) and isinstance(eb, list)) or len(ea) == len(eb):
        if isinstance(ea, list) and isinstance(eb, list) and Counter(map(_canon, ea)) == Counter(map(_canon, eb)):
            a, b = ({k: v for k, v in d.items() if k != "elements"} for d in (a, b))
        return _diff(a, b, "", other)
    line = f"elements: {len(ea)} here, {len(eb)} on {other}"
    here, there = _pieces(raw_a) - _pieces(raw_b), _pieces(raw_b) - _pieces(raw_a)
    if here:
        line += f"; pieces only here: {', '.join(sorted(here.elements()))}"
    if there:
        line += f"; pieces only on {other}: {', '.join(sorted(there.elements()))}"
    a, b = ({k: v for k, v in d.items() if k != "elements"} for d in (a, b))
    return [line] + _diff(a, b, "", other)


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True)


def _names(files: list[str]) -> str:
    return ", ".join(files[:8]) + (f" (+{len(files) - 8} more)" if len(files) > 8 else "")


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    branch = getattr(ctx, "compare_branch", None)
    if not branch:
        print("  no compare_branch in validator.json: nothing to compare")
        return True, "no other branch named"
    project = services(ctx).project
    worldgen = project.namespace_root / "worldgen"
    ref = _resolve(project.root, branch) if worldgen.is_dir() else None
    theirs = _read_branch(worldgen, ref) if ref else None
    if theirs is None:
        why = "this checkout has no worldgen" if not worldgen.is_dir() else (
            f"this clone has no branch {branch!r}" if ref is None else f"{ref} has no worldgen there")
        print(f"  {why}: nothing compared")
        return True, f"{branch} not compared"

    warnings: list[str] = []
    differ = alone = 0
    for folder in _FOLDERS:
        mine = {p.relative_to(worldgen / folder).as_posix(): data
                for p, data in project.json_dicts(worldgen / folder)} if (worldgen / folder).is_dir() else {}
        other = theirs[folder]
        for side, files, label in ((mine, sorted(set(mine) - set(other)), "here"),
                                   (other, sorted(set(other) - set(mine)), f"on {ref}")):
            files = [f for f in files if not _forced_alone(folder, side[f])]
            if files:
                alone += len(files)
                warnings.append(f"  [WARN] {folder}: {len(files)} file(s) only {label}: {_names(files)}")
        for rel in sorted(set(mine) & set(other)):
            a, b = _normalized(folder, mine[rel]), _normalized(folder, other[rel])
            if folder == "structure_set":
                lines = _set_diff(a, b, ref)
            elif folder == "template_pool":
                lines = _pool_diff(a, b, mine[rel], other[rel], ref)
            else:
                lines = _diff(a, b, "", ref)
            if not lines:
                continue
            differ += 1
            more = [f"(+{len(lines) - _MAX_LINES} more)"] if len(lines) > _MAX_LINES else []
            warnings.append(f"  [WARN] {folder}/{rel} differs from {ref} for no version reason\n"
                            + "\n".join(f"    {line}" for line in lines[:_MAX_LINES] + more))

    for msg in warnings:
        print(msg)
    if not warnings:
        print(f"  worldgen matches {ref} apart from what the versions force")
        return True, f"matches {ref}"
    return True, f"{differ} file(s) differ from {ref}, {alone} on one branch only"
