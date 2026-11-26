"""The version index is cached on disk, and a copy older than a targeted release cannot name it."""
from __future__ import annotations

import json

from core import mcmeta
from tests.nbt_helpers import version_entries

CACHED = {"1.21": 3953, "26.2": 4903}
ONLINE = {**CACHED, "26.3": 5023}


def _cache_and_network(tmp_path, monkeypatch, online: dict | None) -> list[str]:
    """Write ``CACHED`` to disk and serve ``online`` (None: unreachable); returns the URLs asked for."""
    (tmp_path / "versions.json").write_text(json.dumps(version_entries(CACHED)), encoding="utf-8")
    asked: list[str] = []

    def http_json(url, headers=None):
        asked.append(url)
        if online is None:
            raise OSError("offline")
        return version_entries(online)

    monkeypatch.setattr(mcmeta, "_http_json", http_json)
    return asked


def _index(tmp_path, versions: list[str], refresh: bool = False):
    run = mcmeta.Mcmeta(versions, tmp_path, refresh)
    assert run.versions is run.versions
    return run.versions


def test_a_release_newer_than_the_cached_list_is_fetched(tmp_path, monkeypatch):
    asked = _cache_and_network(tmp_path, monkeypatch, ONLINE)
    assert _index(tmp_path, ["1.21", "26.3"]).get("26.3") == 5023
    assert len(asked) == 1
    assert "26.3" in (tmp_path / "versions.json").read_text(encoding="utf-8")


def test_a_cached_list_that_knows_every_target_is_not_refetched(tmp_path, monkeypatch):
    asked = _cache_and_network(tmp_path, monkeypatch, ONLINE)
    assert _index(tmp_path, ["1.21", "26.2"]).get("26.2") == 4903
    assert asked == []


def test_the_cached_list_stands_when_the_refetch_fails(tmp_path, monkeypatch, capsys):
    asked = _cache_and_network(tmp_path, monkeypatch, None)
    index = _index(tmp_path, ["1.21", "26.3"])
    assert index.get("26.2") == 4903 and index.get("26.3") is None
    assert len(asked) == 1
    assert "could not fetch versions.json" in capsys.readouterr().out


def test_refresh_fetches_once(tmp_path, monkeypatch):
    asked = _cache_and_network(tmp_path, monkeypatch, ONLINE)
    _index(tmp_path, ["26.4"], refresh=True)
    assert len(asked) == 1
