import argparse
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from registries.fetcher import fetch_registries

_W = 70


@dataclass
class ValidatorContext:
    namespace: str
    mc_versions: list[str]
    extra_ids_raw: list[str]
    project_root: Path
    refresh: bool
    extra_ids: set[str] = field(default_factory=set)
    valid_blocks: set[str] = field(default_factory=set)
    valid_items: set[str] = field(default_factory=set)
    valid_entities: set[str] = field(default_factory=set)


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


def _banner(title: str) -> None:
    tail = "-" * max(0, _W - len(title) - 5)
    print(f"\n--- {title} {tail}")


def _strip_bom_files(project_root: Path) -> int:
    data_root = project_root / "src" / "main" / "resources" / "data"
    if not data_root.exists():
        return 0
    fixed = 0
    for json_path in data_root.rglob("*.json"):
        raw = json_path.read_bytes()
        if raw[:3] == b"\xef\xbb\xbf":
            json_path.write_bytes(raw[3:])
            fixed += 1
    return fixed

def run_checks(ctx: ValidatorContext) -> list[tuple[str, bool, str]]:
    import checks.check_directory_names as check_directory_names
    import checks.nbt_check as nbt_check
    import checks.check_data_integrity as check_data_integrity
    import checks.check_loot_tables as check_loot_tables
    import checks.check_loot_table_schemas as check_loot_table_schemas
    import checks.check_registries as check_registries
    import checks.check_worldgen_schemas as check_worldgen_schemas
    import checks.check_entity_nbt as check_entity_nbt
    import checks.check_sign_nbt as check_sign_nbt
    import checks.check_biome_tags as check_biome_tags
    import checks.check_containers as check_containers

    check_modules = [
        ("check_directory_names", check_directory_names),
        ("nbt_check", nbt_check),
        ("check_data_integrity", check_data_integrity),
        ("check_loot_tables", check_loot_tables),
        ("check_loot_table_schemas", check_loot_table_schemas),
        ("check_registries", check_registries),
        ("check_worldgen_schemas", check_worldgen_schemas),
        ("check_entity_nbt", check_entity_nbt),
        ("check_sign_nbt", check_sign_nbt),
        ("check_biome_tags", check_biome_tags),
        ("check_containers", check_containers),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, module in check_modules:
        _banner(name)
        try:
            passed, summary = module.run(ctx)
        except Exception:
            print("  [crashed]")
            traceback.print_exc()
            passed, summary = False, "crashed with exception"
        print(f"  {'PASS' if passed else 'FAIL'}")
        results.append((name, passed, summary))

    return results


def _print_summary(results: list[tuple[str, bool, str]]) -> None:
    print(f"\n{'=' * _W}")
    print("  SUMMARY")
    print("=" * _W)
    name_w = max(len(n) for n, _, _ in results) + 2
    for name, passed, summary in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {name:<{name_w}} {summary}")
    n_passed = sum(1 for _, p, _ in results if p)
    n_failed = len(results) - n_passed
    parts = []
    if n_passed:
        parts.append(f"{n_passed} passed")
    if n_failed:
        parts.append(f"{n_failed} failed")
    print(f"\n  {', '.join(parts)}")
    print("=" * _W)


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
        project_root=Path(str(args.project_root).strip('"')),
        refresh=args.refresh,
    )

    ctx.extra_ids = resolve_extra_ids(ctx.extra_ids_raw, ctx.project_root)

    versions_str = ", ".join(ctx.mc_versions)
    print(f"Project: {ctx.namespace}  (versions: {versions_str})")

    cache_dir = Path(__file__).parent / "cache"
    cache_dir.mkdir(exist_ok=True)

    print(f"Loading registries ({versions_str})...")
    ctx.valid_items, ctx.valid_blocks, ctx.valid_entities = fetch_registries(ctx.mc_versions, cache_dir, ctx.refresh)
    print(f"  {len(ctx.valid_items)} items, {len(ctx.valid_blocks)} blocks, {len(ctx.valid_entities)} entities")

    bom_fixed = _strip_bom_files(ctx.project_root)
    if bom_fixed:
        print(f"  [pre-pass] stripped UTF-8 BOM from {bom_fixed} file(s)")

    results = run_checks(ctx)
    _print_summary(results)

    if any(not passed for _, passed, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
