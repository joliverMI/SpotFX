"""Sonic's lock domain (spectra/services/lock_console.py) — the whole-song
check's settings, reached through the root process's own route. The fake
`http` here answers from the REAL root router (routers/lock_history_router.py)
in-process, so Sonic is proven against the same validator and store a human
edit on the Timing page uses. No live process is touched."""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.services import lock_console
from services import whole_song_check as wsc


@pytest.fixture
def root(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from config import settings
    from routers import lock_history_router, settings_router
    monkeypatch.setattr(settings_router, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(wsc, "_STORE_PATH", tmp_path / "whole_song_checks.json")
    for k in wsc.SETTINGS:
        monkeypatch.setattr(settings, k, getattr(settings, k))
    app = FastAPI()
    app.include_router(lock_history_router.router)
    client = TestClient(app)

    async def fake_http(method, path, *, params=None, json=None):
        return client.request(method, path, params=params, json=json)

    monkeypatch.setattr(lock_console, "http", fake_http)
    return settings, tmp_path


def _run(coro):
    return asyncio.run(coro)


def test_the_keys_mirror_the_root_settings_exactly():
    assert tuple(lock_console.KEYS) == tuple(wsc.SETTINGS)


def test_read_then_write_round_trip(root):
    settings, tmp = root
    got = _run(lock_console._op_get_whole_song_check())
    assert got["status"] == "ok"
    assert got["settings"]["xcorr_whole_song_enabled"] is True
    assert got["spec"]["xcorr_whole_song_min_r"]["max"] == 0.99
    assert got["entries"] == []

    out = _run(lock_console._op_set_whole_song_check_setting("xcorr_whole_song_enabled", False))
    assert out["status"] == "applied" and (out["old"], out["new"]) == (True, False)
    assert settings.xcorr_whole_song_enabled is False
    assert json.loads((tmp / "settings.json").read_text())["xcorr_whole_song_enabled"] is False
    assert _run(lock_console._op_get_whole_song_check())["settings"][
        "xcorr_whole_song_enabled"] is False


def test_entries_are_the_root_log(root):
    vote = wsc.VoteResult(n_windows=29, winner_bin_ms=11750, winner_offset_ms=11750, wins=27,
                          vote_fraction=27 / 29, median_r_winner=0.95, runner_up_bin_ms=None,
                          runner_up_wins=0, saved_offset_ms=325, median_r_saved=0.56,
                          n_saved_windows=29)
    wsc.record(uri="u", title="El Efecto", artist="x", locked=False, vote=vote,
               decision=wsc.Decision(wsc.CORRECTED, 11750, "325 → 11750"), saved=True)
    got = _run(lock_console._op_get_whole_song_check())
    assert got["entries"][0]["new_offset_ms"] == 11750


@pytest.mark.parametrize("key,value", [
    ("xcorr_whole_song_min_r", 2.0),
    ("xcorr_whole_song_enabled", "yes"),
    ("xcorr_whole_song_locked_every", -3),
])
def test_out_of_range_is_refused_with_the_roots_own_reason(root, key, value):
    settings, tmp = root
    before = settings.__dict__.get(key, getattr(settings, key))
    out = _run(lock_console._op_set_whole_song_check_setting(key, value))
    assert out["status"] == "rejected" and key in out["reason"]
    assert getattr(settings, key) == before
    assert not (tmp / "settings.json").exists()


def test_unknown_key_is_refused_before_any_request(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no request for an unknown key")
    monkeypatch.setattr(lock_console, "http", boom)
    out = _run(lock_console._op_set_whole_song_check_setting("xcorr_lock_q", 0.5))
    assert out["status"] == "rejected" and "unknown setting" in out["reason"]


def test_an_unreachable_root_is_a_stated_rejection(monkeypatch):
    async def down(*a, **k):
        raise ConnectionError("connection refused")
    monkeypatch.setattr(lock_console, "http", down)
    for coro in (lock_console._op_get_whole_song_check(),
                 lock_console._op_set_whole_song_check_setting("xcorr_whole_song_enabled", True)):
        out = _run(coro)
        assert out["status"] == "rejected" and "did not answer" in out["reason"]


def test_discoverable_through_list_operations():
    from spectra.services import settings_agent as sa
    assert {"get_whole_song_check", "set_whole_song_check_setting"} <= set(sa.ALL_OPERATIONS)
    idx = _run(sa._dispatch("list_operations", {"domain": "lock"}))
    names = {o["name"] for o in idx.get("operations", [])}
    assert names == {"get_whole_song_check", "set_whole_song_check_setting"}
