from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from validator import ValidatorContext

# Directories renamed from plural (pre-1.21) to singular (1.21+)
_RENAMED = [
    ("structure",    "structures"),
    ("loot_table",   "loot_tables"),
    ("advancement",  "advancements"),
    ("recipe",       "recipes"),
    ("predicate",    "predicates"),
    ("item_modifier","item_modifiers"),
    ("function",     "functions"),
]

_MC_1_21 = (1, 21)


def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def run(ctx: ValidatorContext) -> tuple[bool, str]:
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace

    parsed = [_parse_version(v) for v in ctx.mc_versions]
    all_pre_121  = all(v[:2] <  _MC_1_21 for v in parsed)
    all_121_plus = all(v[:2] >= _MC_1_21 for v in parsed)

    if not all_pre_121 and not all_121_plus:
        print("  version range spans 1.21 boundary — skipping directory name check")
        return True, "skipped (mixed version range)"

    expect_singular = all_121_plus
    expected_form   = "singular (1.21+)" if expect_singular else "plural (pre-1.21)"
    errors: list[str] = []

    for singular, plural in _RENAMED:
        singular_path = namespace_root / singular
        plural_path   = namespace_root / plural
        singular_exists = singular_path.exists()
        plural_exists   = plural_path.exists()

        if not singular_exists and not plural_exists:
            continue  # directory not used by this project

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

    present = [s if expect_singular else p for s, p in _RENAMED
               if (namespace_root / (s if expect_singular else p)).exists()]
    print(f"  directory names correct ({expected_form}): {', '.join(present)}")
    return True, f"correct for {expected_form}"
