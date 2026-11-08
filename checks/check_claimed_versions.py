"""Every version the mod says it supports is a version the validator checks.

Each check reads ``mc_versions`` from ``validator.json``. The versions players
are promised come from elsewhere: the publish manifest's window for this branch,
the range ``pack.mcmeta`` declares, and ``--claim`` from the release pipeline
(``core/claims.py``). A version promised there and missing from ``mc_versions``
has never been looked at by any check, so this fails until ``validator.json``
lists it. Every Moog 1.21 branch published 1.21-26.3 with ``mc_versions``
ending at 26.2, which is how 26.3 shipped unchecked.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from core.claims import resolve_claims
from core.context import services
from core.formats import Pack

if TYPE_CHECKING:
    from core.context import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    svc = services(ctx)
    project = svc.project
    raw_claims = list(getattr(ctx, "claims", []) or [])
    pack = Pack.read(project.data_root.parent, project.try_json)
    claims, problems, index = resolve_claims(svc.mcmeta, project.root, list(ctx.mc_versions), raw_claims, pack.meta)
    for p in problems:
        print(f"  [ERROR] {p}")

    listed = set(ctx.mc_versions)
    unknown = sorted(v for v in listed if v not in index.data_version)
    for v in unknown:
        print(f"  [ERROR] validator.json lists {v}, which is not a release the version index knows")

    missing_total: set[str] = set()
    for c in claims:
        if c.source == "validator.json":
            continue
        missing = [v for v in c.versions if v not in listed]
        print(f"  {c.source}: {c.low}-{c.high}" + (f" -- not in validator.json: {', '.join(missing)}" if missing else ""))
        if missing:
            missing_total.update(missing)
    if missing_total:
        order = index.stable_ascending
        ms = sorted(missing_total, key=order.index)
        print(f"  [ERROR] claimed but never checked: {', '.join(ms)}. Add them to mc_versions in "
              f"validator.json so every check covers them.")
    no_claim = not any(c.source != "validator.json" for c in claims)
    # In CI (and with --require-claim) a run must know the published window: a
    # 1.20 branch's checkout has no manifest and only a bare pack_format, so
    # without --claim nothing would compare validator.json with what ships.
    require = bool(getattr(ctx, "require_claim", False)) or bool(os.environ.get("GITHUB_ACTIONS"))
    if no_claim:
        what = "no claim beyond validator.json (no publish manifest target, declared pack range or --claim)"
        if require:
            why = "--require-claim" if getattr(ctx, "require_claim", False) else "GITHUB_ACTIONS is set"
            print(f"  [ERROR] {what}, and one is required ({why}): pass --claim START-END from the "
                  f"publish manifest's target for this branch")
        else:
            print(f"  {what}")

    failed = bool(missing_total or problems or unknown or (no_claim and require))
    if failed:
        n = len(missing_total)
        if n:
            return False, f"{n} claimed version(s) not in validator.json"
        return False, "no published window to check against" if no_claim and require else "claims unreadable"
    return True, f"{len(listed)} version(s), every claim covered"
