"""Validate a Minecraft structure mod's data pack before release.

Usage::

    python validator.py --config <project>/validator.json --project-root <project>

Exits 0 when every check passes and 1 otherwise. ``--json`` writes a
machine-readable report (schema_version 1) alongside the human output.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import sys
import traceback
from pathlib import Path

from core.context import ValidatorContext, services

_W = 70

# Run order. The first column is the name used with --check / --skip-check.
CHECK_NAMES = [
    "check_directory_names",
    "nbt_check",
    "check_data_integrity",
    "check_version_coverage",
    "check_loot_tables",
    "check_loot_table_schemas",
    "check_registries",
    "check_worldgen_schemas",
    "check_entity_nbt",
    "check_sign_nbt",
    "check_block_entity_components",
    "check_text_components",
    "check_biome_tags",
    "check_containers",
    "check_jigsaw_pools",
    "check_processor_rules",
    "check_spawn_counts",
    "check_msl_structure_tags",
    "check_msl_replace_vanilla",
    "check_msl_placements_and_processors",
    "check_item_format",
    "check_book_contents",
    "check_potion_effects",
    "check_entity_equipment_shape",
    "check_attribute_ids",
    "check_entity_nbt_keys",
    "check_no_spawn_eggs",
    "check_no_enchanted_books",
    "check_no_particles",
]


def resolve_extra_ids(raw: list[str], project_root: Path) -> set[str]:
    result: set[str] = set()
    for entry in raw:
        if entry.startswith("@"):
            with (project_root / entry[1:]).open(encoding="utf-8-sig") as f:
                result.update(json.load(f))
        else:
            result.add(entry)
    return result


def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8-sig") as f:
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
    """Remove a UTF-8 BOM from every JSON file under ``data/``: the game's
    parser rejects it, and the count is reported so the fix is visible."""
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


def _check_modules() -> list[tuple[str, object]]:
    return [(name, importlib.import_module(f"checks.{name}")) for name in CHECK_NAMES]


def _filter_modules(modules, only: list[str] | None, skip: list[str] | None):
    names = [n for n, _ in modules]
    unknown = [n for n in (only or []) + (skip or []) if n not in names]
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


def run_checks(
    ctx: ValidatorContext,
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[tuple[str, bool, str, str]]:
    results: list[tuple[str, bool, str, str]] = []
    for name, module in _filter_modules(_check_modules(), only, skip):
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


def _print_summary(results: list[tuple[str, bool, str, str]]) -> None:
    print(f"\n{'=' * _W}")
    print("  SUMMARY")
    print("=" * _W)
    name_w = max(len(n) for n, _, _, _ in results) + 2
    for name, passed, summary, _ in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name:<{name_w}} {summary}")
    n_passed = sum(1 for _, p, _, _ in results if p)
    n_failed = len(results) - n_passed
    parts = []
    if n_passed:
        parts.append(f"{n_passed} passed")
    if n_failed:
        parts.append(f"{n_failed} failed")
    print(f"\n  {', '.join(parts)}")
    print("=" * _W)


def _emit_json(ctx: ValidatorContext, results: list[tuple[str, bool, str, str]], stream) -> None:
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


def _force_utf8_streams() -> None:
    """Make stdout/stderr able to carry any character a check prints.

    On Windows, redirected output falls back to the locale encoding (cp1252),
    whose ``surrogateescape`` handler cannot rescue a character with no cp1252
    mapping; one such character in a message would raise inside the check and
    turn a finding into ``[crashed]``. Messages are kept ASCII-safe as well
    (tests/test_output_encoding.py); this is the second line of defence.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # a capture object (pytest) or a plain file-like
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> None:
    _force_utf8_streams()

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--refresh", action="store_true", help="re-fetch cached registries and schemas")
    parser.add_argument("--check", action="append", default=[], metavar="NAME",
                        help="run only the named check (may be repeated)")
    parser.add_argument("--skip-check", action="append", default=[], metavar="NAME",
                        help="skip the named check (may be repeated)")
    parser.add_argument("--json", dest="json_out", nargs="?", const="-", default=None, metavar="PATH",
                        help="emit machine-readable JSON report (path or - for stdout)")
    args = parser.parse_args()

    json_mode = args.json_out is not None
    real_stdout = sys.stdout
    if json_mode:
        sys.stdout = sys.stderr

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

    svc = services(ctx)
    svc.mcmeta.cache_dir.mkdir(exist_ok=True)

    print(f"Loading registries ({versions_str})...")
    svc.mcmeta.prefetch()
    ctx.valid_items = svc.mcmeta.union("item")
    ctx.valid_blocks = svc.mcmeta.union("block")
    ctx.valid_entities = svc.mcmeta.union("entity_type")
    print(f"  {len(ctx.valid_items)} items, {len(ctx.valid_blocks)} blocks, {len(ctx.valid_entities)} entities")

    bom_fixed = _strip_bom_files(ctx.project_root)
    if bom_fixed:
        print(f"  [pre-pass] stripped UTF-8 BOM from {bom_fixed} file(s)")

    project = svc.project
    if project.structures_dir.exists() and project.template_pool_dir.exists():
        from checks.check_data_integrity import _check_orphaned_nbt
        ctx.orphan_nbts = {
            (project.structures_dir / rel).resolve() for rel in _check_orphaned_nbt(project)
        }
        svc.structures.set_orphans(ctx.orphan_nbts)

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
