from __future__ import annotations

from typing import TYPE_CHECKING

from utils.nbt_versions import (
    _parse_range,
    _parse_version,
    _version_in_range,
    collect_versioned_elements,
)

if TYPE_CHECKING:
    from validator import ValidatorContext


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    from utils.paths import data_dir
    structures_dir = data_dir(namespace_root, "structure")

    if not template_pool_dir.exists() or not structures_dir.exists():
        return True, "no template_pool/structures directory"

    elements = collect_versioned_elements(template_pool_dir, structures_dir, ctx.namespace)
    if not elements:
        return True, "no versioned_single_pool_element entries"

    fail_msgs: list[str] = []
    warn_msgs: list[str] = []
    elements_checked = 0

    for cov in elements:
        elements_checked += 1
        loc_desc = f"{cov.pool_rel}[element {cov.element_index}]"

        malformed: list[str] = []
        inverted: list[str] = []
        parsed_ranges: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
        for r in cov.ranges:
            parsed = _parse_range(r.range_key)
            if parsed is None:
                malformed.append(r.range_key)
                continue
            low, high = parsed
            if low > high:
                inverted.append(r.range_key)
                continue
            parsed_ranges.append((r.range_key, low, high))

        for key in malformed:
            fail_msgs.append(f"[ERROR] {loc_desc}: unparseable range key '{key}'")
        for key in inverted:
            fail_msgs.append(f"[ERROR] {loc_desc}: inverted range '{key}' (lower > upper)")

        # Overlap detection (WARN): first-match-wins hides mistakes.
        for i in range(len(parsed_ranges)):
            for j in range(i + 1, len(parsed_ranges)):
                k1, l1, h1 = parsed_ranges[i]
                k2, l2, h2 = parsed_ranges[j]
                if l1 <= h2 and l2 <= h1:
                    warn_msgs.append(f"[WARN] {loc_desc}: overlapping ranges '{k1}' and '{k2}'")

        # Coverage check: every mc_version must be in some range. Falling through
        # to the default `location` is (per the plan) almost always the wrong format.
        uncovered = [
            v for v in ctx.mc_versions
            if not any(_version_in_range(v, k) for k, _, _ in parsed_ranges)
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
        print(f"  {elements_checked} versioned element(s) checked -- coverage OK")

    if fail_msgs:
        return False, f"{len(fail_msgs)} coverage error(s), {len(warn_msgs)} warning(s)"
    if warn_msgs:
        return True, f"0 errors, {len(warn_msgs)} overlap warning(s)"
    return True, f"{elements_checked} versioned element(s) OK"
