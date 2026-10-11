"""A Spotify context's friendly name (spectra/services/spotify_context.py)
— the bridge-first/HTTP-fallback resolution `name_for()` does, its
MISS_RETRY_S cache, and the SPECTRA-side route that serves it
(`GET /api/light-show/context-name`). No live access: the bridge is the
real singleton with its context accessors monkeypatched, and the HTTP
fallback is a fake `httpx.get`."""
from __future__ import annotations

import pytest

from spectra.services import spotify_context

CTX = "spotify:playlist:forty"
OTHER = "spotify:playlist:other"
THIRD = "spotify:playlist:third"


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _not_playing(monkeypatch):
    """The bridge is live but not on the context under test."""
    from spectra.services import engine
    monkeypatch.setattr(engine.bridge, "context_uri", lambda: OTHER)
    monkeypatch.setattr(engine.bridge, "context_name", lambda: "Other Playlist")


def test_the_bridge_wins_when_it_is_playing_this_context(monkeypatch):
    from spectra.services import engine
    monkeypatch.setattr(engine.bridge, "context_uri", lambda: CTX)
    monkeypatch.setattr(engine.bridge, "context_name", lambda: "40! Lightshow")
    calls = []
    monkeypatch.setattr(spotify_context.httpx, "get",
                        lambda *a, **k: calls.append(1) or _FakeResponse(200, {"name": "x"}))
    assert spotify_context.name_for(CTX) == "40! Lightshow"
    assert calls == []   # never asked SpotFX — the bridge already knew


def test_it_asks_spotfx_when_the_bridge_is_on_a_different_context(monkeypatch):
    _not_playing(monkeypatch)
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["uri"])
        return _FakeResponse(200, {"name": "Liked Songs"})
    monkeypatch.setattr(spotify_context.httpx, "get", fake_get)
    assert spotify_context.name_for(CTX) == "Liked Songs"
    assert calls == [CTX]


def test_a_resolved_name_is_cached_and_not_re_asked(monkeypatch):
    _not_playing(monkeypatch)
    calls = []
    monkeypatch.setattr(spotify_context.httpx, "get",
                        lambda *a, **k: calls.append(1) or _FakeResponse(200, {"name": "Liked Songs"}))
    assert spotify_context.name_for(CTX) == "Liked Songs"
    assert spotify_context.name_for(CTX) == "Liked Songs"
    assert len(calls) == 1


def test_an_unresolved_name_is_retried_only_after_miss_retry_s(monkeypatch):
    _not_playing(monkeypatch)
    calls = []
    monkeypatch.setattr(spotify_context.httpx, "get",
                        lambda *a, **k: calls.append(1) or _FakeResponse(200, {"name": ""}))
    now = {"t": 1000.0}
    monkeypatch.setattr(spotify_context.time, "monotonic", lambda: now["t"])

    assert spotify_context.name_for(CTX) == ""
    assert len(calls) == 1

    now["t"] += spotify_context.MISS_RETRY_S - 1
    assert spotify_context.name_for(CTX) == ""
    assert len(calls) == 1          # still within the retry window — not re-asked

    now["t"] += 2
    assert spotify_context.name_for(CTX) == ""
    assert len(calls) == 2          # the window lapsed — asked again


def test_a_bad_response_or_unreachable_spotfx_resolves_to_empty(monkeypatch):
    _not_playing(monkeypatch)
    monkeypatch.setattr(spotify_context.httpx, "get", lambda *a, **k: _FakeResponse(500, {}))
    assert spotify_context.name_for(CTX) == ""

    def raises(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(spotify_context.httpx, "get", raises)
    assert spotify_context.name_for(THIRD) == ""


@pytest.mark.parametrize("uri", ["", "   ", None])
def test_a_blank_uri_resolves_to_empty_without_asking_anything(monkeypatch, uri):
    from spectra.services import engine

    def boom(*a, **k):
        raise AssertionError("must not be called for a blank uri")
    monkeypatch.setattr(engine.bridge, "context_uri", boom)
    monkeypatch.setattr(spotify_context.httpx, "get", boom)
    assert spotify_context.name_for(uri) == ""


def test_reset_clears_the_cache(monkeypatch):
    _not_playing(monkeypatch)
    calls = []
    monkeypatch.setattr(spotify_context.httpx, "get",
                        lambda *a, **k: calls.append(1) or _FakeResponse(200, {"name": "Liked Songs"}))
    assert spotify_context.name_for(CTX) == "Liked Songs"
    assert len(calls) == 1
    spotify_context.reset()
    assert spotify_context.name_for(CTX) == "Liked Songs"
    assert len(calls) == 2          # the cache was cleared — asked again


def test_the_spectra_route_serves_it(monkeypatch):
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    _not_playing(monkeypatch)
    monkeypatch.setattr(spotify_context.httpx, "get",
                        lambda *a, **k: _FakeResponse(200, {"name": "Liked Songs"}))
    client = TestClient(create_app())
    r = client.get("/api/light-show/context-name", params={"uri": CTX})
    assert r.status_code == 200
    assert r.json() == {"uri": CTX, "name": "Liked Songs"}
