import argparse
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from registries.fetcher import fetch_registries


@dataclass
class ValidatorContext:
    namespace: str
    mc_versions: list[str]
    extra_ids_raw: list[str]
    msl: bool
    project_root: Path
    refresh: bool
    extra_ids: set[str] = field(default_factory=set)
    valid_blocks: set[str] = field(default_factory=set)
    valid_items: set[str] = field(default_factory=set)


def resolve_extra_ids(raw: list[str], project_root: Path) -> set[str]:
    result: set[str] = set()
    for entry in raw:
        if entry.startswith("@"):
            ref_path = project_root / entry[1:]
            with ref_path.open() as f:
                ids = json.load(f)
            result.update(ids)
        else:
            result.add(entry)
    return result


def load_config(config_path: Path) -> dict:
    with config_path.open() as f:
        cfg = json.load(f)
    if not isinstance(cfg.get("namespace"), str):
        raise ValueError("config missing required string field 'namespace'")
    if not isinstance(cfg.get("mc_versions"), list) or not cfg["mc_versions"]:
        raise ValueError("config missing required non-empty list field 'mc_versions'")
    return cfg


def run_checks(ctx: ValidatorContext) -> list[str]:
    import checks.nbt_check as nbt_check
    import checks.check_data_integrity as check_data_integrity
    import checks.check_loot_tables as check_loot_tables
    import checks.check_loot_table_schemas as check_loot_table_schemas
    import checks.check_registries as check_registries
    import checks.check_worldgen_schemas as check_worldgen_schemas

    check_modules = [
        ("nbt_check", nbt_check),
        ("check_data_integrity", check_data_integrity),
        ("check_loot_tables", check_loot_tables),
        ("check_loot_table_schemas", check_loot_table_schemas),
        ("check_registries", check_registries),
        ("check_worldgen_schemas", check_worldgen_schemas),
    ]

    failed: list[str] = []
    for name, module in check_modules:
        try:
            passed = module.run(ctx)
            if not passed:
                failed.append(name)
        except Exception:
            print(f"\n[{name}] crashed:")
            traceback.print_exc()
            failed.append(name)

    return failed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)

    ctx = ValidatorContext(
        namespace=cfg["namespace"],
        mc_versions=cfg["mc_versions"],
        extra_ids_raw=cfg.get("extra_ids", []),
        msl=cfg.get("msl", False),
        project_root=args.project_root,
        refresh=args.refresh,
    )

    ctx.extra_ids = resolve_extra_ids(ctx.extra_ids_raw, ctx.project_root)

    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    ctx.valid_items, ctx.valid_blocks = fetch_registries(ctx.mc_versions, cache_dir, ctx.refresh)

    failed = run_checks(ctx)

    if failed:
        print(f"\nvalidation failed — {len(failed)} check(s) did not pass:")
        for name in failed:
            print(f"  - {name}")
        sys.exit(1)
    else:
        print("\nall checks passed")


if __name__ == "__main__":
    main()
