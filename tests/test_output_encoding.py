"""Guards on what the validator can print.

A message containing a character the console codec cannot encode kills the check
that prints it: on Windows, redirected stdout uses the locale encoding (cp1252),
and an unmappable character raises UnicodeEncodeError inside `run_checks`, which
catches it and reports `[crashed]` instead of the finding. `_force_utf8_streams`
fixes that at runtime; keeping the strings themselves encodable stops the problem
being reintroduced for anyone running without it.
"""
from __future__ import annotations

import ast
import io
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("checks", "utils")
CONSOLE_CODEC = "cp1252"


def _source_files() -> list[pathlib.Path]:
    files = [REPO_ROOT / "validator.py"]
    for name in SCANNED_DIRS:
        files.extend(sorted((REPO_ROOT / name).glob("*.py")))
    return files


def _string_literals(path: pathlib.Path):
    """Every string literal in the file, including the constant parts of f-strings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_string_literals_are_console_encodable(path: pathlib.Path) -> None:
    offenders = []
    for lineno, text in _string_literals(path):
        try:
            text.encode(CONSOLE_CODEC)
        except UnicodeEncodeError as exc:
            char = text[exc.start:exc.end]
            offenders.append(
                f"  {path.relative_to(REPO_ROOT)}:{lineno}: {ascii(char)}"
                f" (U+{ord(char[0]):04X}) is not encodable in {CONSOLE_CODEC}"
            )

    assert not offenders, (
        f"{len(offenders)} string literal(s) would crash a redirected Windows console.\n"
        + "\n".join(offenders)
        + f"\nUse an ASCII equivalent ('>=' for U+2265, '->' for U+2192)."
    )


def test_force_utf8_streams_survives_streams_without_reconfigure(monkeypatch) -> None:
    """pytest and other harnesses swap in capture objects that have no reconfigure()."""
    import validator

    monkeypatch.setattr(validator.sys, "stdout", io.StringIO())
    monkeypatch.setattr(validator.sys, "stderr", io.StringIO())
    validator._force_utf8_streams()  # must not raise


def test_force_utf8_streams_sets_utf8_on_a_real_wrapper(monkeypatch) -> None:
    import validator

    wrapper = io.TextIOWrapper(io.BytesIO(), encoding=CONSOLE_CODEC, errors="strict")
    monkeypatch.setattr(validator.sys, "stdout", wrapper)
    monkeypatch.setattr(validator.sys, "stderr", io.StringIO())
    validator._force_utf8_streams()

    assert wrapper.encoding.lower().replace("-", "") == "utf8"
    wrapper.write("min≥1.21.5")  # the character that used to crash the run
    wrapper.flush()
