"""Which Minecraft versions a mod says it works on.

Every check reads ``mc_versions`` from ``validator.json``, but that is not where
a mod's support is promised to players. The promise is made in three other
places, and each of them is read here:

* ``.github/moogs-publish.yml`` -- the release pipeline publishes each branch for
  the ``mc: { start, end }`` window of its ``targets`` entry. The manifest lives
  on the default branch only; a checkout of another branch may not have it.
* ``pack.mcmeta`` -- a declared format range (``supported_formats``, or
  ``min_format`` / ``max_format``) is the range the pack itself says it loads on.
  A bare ``pack_format`` names the format the pack was written for, not a range,
  and is not read as a claim.
* ``--claim START-END`` on the command line, for a caller (the release pipeline)
  that knows exactly which window it is about to publish.

A version claimed by any of these and missing from ``mc_versions`` is a version
no check has looked at. That is how 26.3 shipped unchecked: every 1.21 branch
published 1.21-26.3 while its ``validator.json`` stopped at 26.2.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from core.mcversions import VersionIndex, parse_version, try_parse_version


@dataclass
class Claim:
    source: str            # where the claim was read, for messages
    low: str
    high: str
    versions: list[str]    # stable releases in the window, oldest first


# --- pack.mcmeta -------------------------------------------------------------------

def _format(value) -> tuple[int, int] | None:
    """A pack format as (major, minor): ``48``, ``121.0``, ``[107, 1]``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return (value, 0)
    if isinstance(value, float):
        # The game reads the number as an integer major format: 121.0 is 121.
        return (int(value), 0)
    if isinstance(value, list) and value and all(isinstance(x, int) and not isinstance(x, bool) for x in value):
        return (value[0], value[1] if len(value) > 1 else 0)
    return None


def format_range(block: dict, *, new_fields: bool) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The format range a pack (or overlay) block declares.

    ``new_fields`` picks which spelling a version reads: from 1.21.9 (data pack
    format 82) the game reads ``min_format`` / ``max_format``; before it,
    ``supported_formats`` (``formats`` on an overlay). When the spelling a
    version reads is absent the other one is used, so a pack that writes only
    one of them is still understood.
    """
    def new():
        lo, hi = _format(block.get("min_format")), _format(block.get("max_format"))
        if lo is not None and hi is not None:
            return lo, hi
        return None

    def old():
        sf = block.get("supported_formats", block.get("formats"))
        if isinstance(sf, int) and not isinstance(sf, bool):
            return (sf, 0), (sf, 99)
        if isinstance(sf, list) and len(sf) == 2 and all(isinstance(x, int) for x in sf):
            return (sf[0], 0), (sf[1], 99)
        if isinstance(sf, dict):
            lo, hi = sf.get("min_inclusive"), sf.get("max_inclusive")
            if isinstance(lo, int) and isinstance(hi, int):
                return (lo, 0), (hi, 99)
        return None

    first, second = (new, old) if new_fields else (old, new)
    got = first() or second()
    if got is None:
        return None
    lo, hi = got
    # An integer upper bound covers every minor revision of that major format.
    if hi[1] == 0 and not isinstance(block.get("max_format"), list):
        hi = (hi[0], 99)
    return lo, hi


NEW_FORMAT_FIELDS = (82, 0)   # 25w31a: min_format / max_format replace the old fields


# --- the publish manifest ------------------------------------------------------------

_COMMENT = re.compile(r"\s+#.*$")


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def manifest_targets(text: str) -> list[dict]:
    """``[{"branch": ..., "start": ..., "end": ...}]`` from a publish manifest.

    PyYAML is used when it is installed. Otherwise a reader for the manifest's
    own shape (``targets:`` list items with ``branch`` and an ``mc`` mapping,
    flow or block style) is enough: the validator does not depend on PyYAML.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            doc = yaml.safe_load(text)
        except Exception:
            doc = None
        if isinstance(doc, dict):
            out = []
            for t in doc.get("targets") or []:
                if isinstance(t, dict) and isinstance(t.get("mc"), dict):
                    out.append({"branch": str(t.get("branch", "")),
                                "start": str(t["mc"].get("start", "")), "end": str(t["mc"].get("end", ""))})
            return out
    targets: list[dict] = []
    cur: dict | None = None
    in_targets = False
    in_mc = False
    mc_indent = 0
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if indent == 0:
            in_targets = body.startswith("targets:")
            in_mc = False
            continue
        if not in_targets:
            continue
        if body.startswith("- "):
            cur = {"branch": "", "start": "", "end": ""}
            targets.append(cur)
            body = body[2:].strip()
            indent += 2
            in_mc = False
        if cur is None:
            continue
        if in_mc and indent <= mc_indent:
            in_mc = False
        key, _, val = body.partition(":")
        key, val = key.strip(), val.strip()
        if key == "branch":
            cur["branch"] = _unquote(val)
        elif key == "mc":
            if val.startswith("{"):
                for part in val.strip("{} ").split(","):
                    k, _, v = part.partition(":")
                    if k.strip() in ("start", "end"):
                        cur[k.strip()] = _unquote(v)
            else:
                in_mc, mc_indent = True, indent
        elif in_mc and key in ("start", "end"):
            cur[key] = _unquote(val)
    return [t for t in targets if t["start"] and t["end"]]


def current_branch(root: Path) -> str | None:
    """The branch being validated: the CI's ref name, else the checkout's HEAD."""
    for var in ("GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        v = os.environ.get(var)
        if v:
            return v
    git = root / ".git"
    try:
        if git.is_file():
            gitdir = git.read_text(encoding="utf-8").strip()
            if gitdir.startswith("gitdir:"):
                git = (root / gitdir[len("gitdir:"):].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return None


# --- putting it together -------------------------------------------------------------------

def parse_claim(text: str) -> tuple[str, str] | None:
    """``"1.21-26.3"`` or ``"26.3"`` -> (low, high)."""
    lo, sep, hi = text.strip().partition("-")
    if not sep:
        hi = lo
    if try_parse_version(lo) is None or try_parse_version(hi) is None:
        return None
    return lo, hi


def read_claims(project_root: Path, mc_versions: list[str], cli_claims: list[str],
                index: VersionIndex, pack_meta: dict | None,
                unknown: list[str] | None = None) -> tuple[list[Claim], list[str]]:
    """Every claim this project makes, and any problems reading them.

    ``unknown`` collects what the version index cannot place: a range end that
    is not a release it knows, or a pack format newer than any release. A stale
    index would otherwise shrink a 1.21-26.3 claim to 1.21-26.2 without a word.
    """
    claims: list[Claim] = []
    problems: list[str] = []
    unknown = unknown if unknown is not None else []

    def window(source, lo, hi):
        if try_parse_version(lo) is None or try_parse_version(hi) is None:
            problems.append(f"{source}: `{lo}`-`{hi}` is not a version range")
            return
        if parse_version(lo) > parse_version(hi):
            problems.append(f"{source}: `{lo}`-`{hi}` is inverted")
            return
        for end in (lo, hi):
            if end not in index.data_version:
                unknown.append(f"{source} names {end}")
        claims.append(Claim(source, lo, hi, index.stable_between(lo, hi)))

    if mc_versions:
        good = [v for v in mc_versions if try_parse_version(v) is not None]
        if good:
            lo = min(good, key=parse_version)
            hi = max(good, key=parse_version)
            claims.append(Claim("validator.json", lo, hi, sorted(good, key=parse_version)))

    manifest = project_root / ".github" / "moogs-publish.yml"
    if manifest.is_file():
        try:
            targets = manifest_targets(manifest.read_text(encoding="utf-8"))
        except OSError:
            targets = []
        branch = current_branch(project_root)
        chosen = [t for t in targets if branch and t["branch"] == branch]
        if not chosen and mc_versions:
            floor = min((v for v in mc_versions if try_parse_version(v)), key=parse_version, default=None)
            if floor is not None:
                chosen = [t for t in targets
                          if try_parse_version(t["start"]) and try_parse_version(t["end"])
                          and parse_version(t["start"]) <= parse_version(floor) <= parse_version(t["end"])]
        for t in chosen[:1]:
            window(f".github/moogs-publish.yml (target {t['branch'] or '?'})", t["start"], t["end"])

    if isinstance(pack_meta, dict) and isinstance(pack_meta.get("pack"), dict):
        pack = pack_meta["pack"]
        declares = any(k in pack for k in ("supported_formats", "min_format", "max_format"))
        if declares:
            # Each version reads the spelling of its own era; take the widest reading.
            found = []
            for new_fields in (False, True):
                rng = format_range(pack, new_fields=new_fields)
                if rng is not None:
                    found.append(rng)
            if found:
                lo = min(r[0] for r in found)
                hi = max(r[1] for r in found)
                newest = max(index.pack_format.values(), default=(0, 0))
                if (hi[0], 0) > newest:
                    unknown.append(f"pack.mcmeta declares format {hi[0]}, newer than any release")
                versions = index.with_pack_formats(lo, hi)
                if versions:
                    claims.append(Claim("pack.mcmeta", versions[0], versions[-1], versions))

    for raw in cli_claims or []:
        parsed = parse_claim(raw)
        if parsed is None:
            problems.append(f"--claim `{raw}` is not a version or a START-END range")
            continue
        window("--claim", *parsed)

    return claims, problems


def resolve_claims(mcmeta, project_root: Path, mc_versions: list[str], cli_claims: list[str],
                   pack_meta: dict | None) -> tuple[list[Claim], list[str], VersionIndex]:
    """:func:`read_claims` against a version index that knows every claimed
    release: refetched once if it does not, and a problem if it still does not."""
    index = mcmeta.versions_knowing(list(mc_versions))
    unknown: list[str] = []
    claims, problems = read_claims(project_root, mc_versions, cli_claims, index, pack_meta, unknown)
    if unknown:
        index = mcmeta.versions_knowing(["(refetch)"])
        unknown = []
        claims, problems = read_claims(project_root, mc_versions, cli_claims, index, pack_meta, unknown)
        for u in unknown:
            problems.append(f"{u}, which the version index does not know; it cannot be checked")
    return claims, problems, index


def claimed_versions(claims: list[Claim]) -> list[str]:
    """Every version any claim names, oldest first."""
    out = {v for c in claims for v in c.versions}
    return sorted(out, key=parse_version)
