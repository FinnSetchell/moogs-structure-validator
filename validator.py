import argparse
import contextlib
import io
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
    orphan_nbts: set[Path] = field(default_factory=set)
    nbt_cache: dict = field(default_factory=dict)


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

def _check_modules():
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
    import checks.check_jigsaw_pools as check_jigsaw_pools
    import checks.check_processor_rules as check_processor_rules
    import checks.check_item_format as check_item_format

    return [
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
        ("check_jigsaw_pools", check_jigsaw_pools),
        ("check_processor_rules", check_processor_rules),
        ("check_item_format", check_item_format),
    ]


def _filter_modules(modules, only: list[str] | None, skip: list[str] | None):
    names = [n for n, _ in modules]
    requested = (only or []) + (skip or [])
    unknown = [n for n in requested if n not in names]
    if unknown:
        raise SystemExit(
            f"unknown check name(s): {', '.join(unknown)}\n"
            f"available: {', '.join(names)}"
        )
    result = modules
    if only:
        result = [(n, m) for n, m in result if n in only]
    if skip:
        result = [(n, m) for n, m in result if n not in skip]
    return result


def run_checks(
    ctx: ValidatorContext,
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[tuple[str, bool, str, str]]:
    check_modules = _filter_modules(_check_modules(), only, skip)

    results: list[tuple[str, bool, str, str]] = []
    for name, module in check_modules:
        _banner(name)
        buf = io.StringIO()
        with contextlib.redirect_stdout(_TeeStream(sys.stdout, buf)):
            try:
                passed, summary = module.run(ctx)
            except Exception:
                print("  [crashed]")
                traceback.print_exc()
                passed, summary = False, "crashed with exception"
            print(f"  {'PASS' if passed else 'FAIL'}")
        results.append((name, passed, summary, buf.getvalue()))

    return results


class _TeeStream:
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)
        return len(data)

    def flush(self):
        for s in self._streams:
            s.flush()


def _print_summary(results: list[tuple[str, bool, str, str]]) -> None:
    print(f"\n{'=' * _W}")
    print("  SUMMARY")
    print("=" * _W)
    name_w = max(len(n) for n, _, _, _ in results) + 2
    for name, passed, summary, _ in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {name:<{name_w}} {summary}")
    n_passed = sum(1 for _, p, _, _ in results if p)
    n_failed = len(results) - n_passed
    parts = []
    if n_passed:
        parts.append(f"{n_passed} passed")
    if n_failed:
        parts.append(f"{n_failed} failed")
    print(f"\n  {', '.join(parts)}")
    print("=" * _W)


def _emit_json(
    ctx: ValidatorContext, results: list[tuple[str, bool, str, str]], stream
) -> None:
    payload = {
        "schema_version": 1,
        "namespace": ctx.namespace,
        "mc_versions": ctx.mc_versions,
        "overall_pass": all(p for _, p, _, _ in results),
        "checks": [
            {"name": n, "passed": p, "summary": s, "output": out}
            for n, p, s, out in results
        ],
    }
    json.dump(payload, stream, indent=2)
    stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="NAME",
        help="run only the named check (may be repeated)",
    )
    parser.add_argument(
        "--skip-check",
        action="append",
        default=[],
        metavar="NAME",
        help="skip the named check (may be repeated)",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help="emit machine-readable JSON report (path or - for stdout)",
    )
    args = parser.parse_args()

    json_mode = args.json_out is not None
    human_stream = sys.stderr if json_mode else sys.stdout
    real_stdout = sys.stdout
    if json_mode:
        sys.stdout = human_stream

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

    from checks.check_data_integrity import _check_orphaned_nbt
    from utils.paths import data_dir
    namespace_root = ctx.project_root / "src" / "main" / "resources" / "data" / ctx.namespace
    structures_dir = data_dir(namespace_root, "structure")
    template_pool_dir = namespace_root / "worldgen" / "template_pool"
    if structures_dir.exists() and template_pool_dir.exists():
        ctx.orphan_nbts = {
            (structures_dir / rel).resolve()
            for rel in _check_orphaned_nbt(template_pool_dir, structures_dir, ctx.namespace)
        }

    results = run_checks(ctx, only=args.check or None, skip=args.skip_check or None)
    _print_summary(results)

    if json_mode:
        if args.json_out == "-":
            _emit_json(ctx, results, real_stdout)
        else:
            with open(args.json_out, "w", encoding="utf-8") as f:
                _emit_json(ctx, results, f)

    if any(not passed for _, passed, _, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
