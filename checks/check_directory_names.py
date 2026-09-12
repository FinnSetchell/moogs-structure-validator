"""Registry folders use the right name for the targeted versions: singular
(``structure``, ``loot_table``) from 1.21, plural before it. A project spanning
the rename is skipped, since no single name is right for all of its versions."""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.context import services
from core.mcversions import try_parse_version

if TYPE_CHECKING:
    from core.context import ValidatorContext

# (singular 1.21+, plural pre-1.21)
_RENAMED = [
    ("structure",     "structures"),
    ("loot_table",    "loot_tables"),
    ("advancement",   "advancements"),
    ("recipe",        "recipes"),
    ("predicate",     "predicates"),
    ("item_modifier", "item_modifiers"),
    ("function",      "functions"),
]

_MC_1_21 = (1, 21)


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = services(ctx).project.namespace_root

    parsed = [try_parse_version(v) or (0,) for v in ctx.mc_versions]
    all_pre_121 = all(v[:2] < _MC_1_21 for v in parsed)
    all_121_plus = all(v[:2] >= _MC_1_21 for v in parsed)

    if not all_pre_121 and not all_121_plus:
        print("  version range spans 1.21 boundary — skipping directory name check")
        return True, "skipped (mixed version range)"

    expect_singular = all_121_plus
    expected_form = "singular (1.21+)" if expect_singular else "plural (pre-1.21)"
    errors: list[str] = []

    for singular, plural in _RENAMED:
        singular_exists = (namespace_root / singular).exists()
        plural_exists = (namespace_root / plural).exists()
        if not singular_exists and not plural_exists:
            continue
        if singular_exists and plural_exists:
            errors.append(f"both {singular}/ and {plural}/ exist — remove the wrong one")
        elif expect_singular and plural_exists:
            errors.append(f"{plural}/ should be {singular}/ for 1.21+")
        elif not expect_singular and singular_exists:
            errors.append(f"{singular}/ should be {plural}/ for pre-1.21")

    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        return False, f"{len(errors)} directory naming error(s)"

    present = [
        s if expect_singular else p
        for s, p in _RENAMED
        if (namespace_root / (s if expect_singular else p)).exists()
    ]
    print(f"  directory names correct ({expected_form}): {', '.join(present)}")
    return True, f"correct for {expected_form}"
