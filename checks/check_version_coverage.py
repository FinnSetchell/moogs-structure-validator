"""Every MSL versioned pool element covers the whole targeted version range.

A version no range covers falls back to the element's default ``location``,
which is almost always a file in the wrong format for that version. Malformed
and inverted range keys are errors; overlapping ranges warn, because first
match wins and the second range silently never fires.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.mcversions import parse_range, version_in_range
from core.ranges import collect_versioned_elements

if TYPE_CHECKING:
    from core.context import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    project = services(ctx).project
    if not project.template_pool_dir.exists() or not project.structures_dir.exists():
        return True, "no template_pool/structures directory"

    elements = collect_versioned_elements(project)
    if not elements:
        return True, "no versioned_single_pool_element entries"

    fail_msgs: list[str] = []
    warn_msgs: list[str] = []

    for cov in elements:
        loc_desc = f"{cov.pool_rel}[element {cov.element_index}]"

        parsed_ranges: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
        for r in cov.ranges:
            parsed = parse_range(r.range_key)
            if parsed is None:
                fail_msgs.append(f"[ERROR] {loc_desc}: unparseable range key '{r.range_key}'")
                continue
            low, high = parsed
            if low > high:
                fail_msgs.append(f"[ERROR] {loc_desc}: inverted range '{r.range_key}' (lower > upper)")
                continue
            parsed_ranges.append((r.range_key, low, high))

        for i in range(len(parsed_ranges)):
            for j in range(i + 1, len(parsed_ranges)):
                k1, l1, h1 = parsed_ranges[i]
                k2, l2, h2 = parsed_ranges[j]
                if l1 <= h2 and l2 <= h1:
                    warn_msgs.append(f"[WARN] {loc_desc}: overlapping ranges '{k1}' and '{k2}'")

        uncovered = [
            v for v in ctx.mc_versions
            if not any(version_in_range(v, k) for k, _, _ in parsed_ranges)
        ]
        if uncovered:
            hint = (
                f" (would fall back to default `location` '{cov.default_location}',"
                f" usually the wrong format)"
                if cov.default_location
                else " (no default `location` either)"
            )
            fail_msgs.append(
                f"[ERROR] {loc_desc}: versions not covered by any range:"
                f" {', '.join(uncovered)}{hint}"
            )

    for msg in fail_msgs:
        print(f"  {msg}")
    for msg in warn_msgs:
        print(f"  {msg}")

    if not fail_msgs and not warn_msgs:
        print(f"  {len(elements)} versioned element(s) checked -- coverage OK")

    if fail_msgs:
        return False, f"{len(fail_msgs)} coverage error(s), {len(warn_msgs)} warning(s)"
    if warn_msgs:
        return True, f"0 errors, {len(warn_msgs)} overlap warning(s)"
    return True, f"{len(elements)} versioned element(s) OK"
