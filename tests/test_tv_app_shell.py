"""The TV app shell's mount (data/tv-display-plan/plan.html PR 1.1) — the
one correctness property that matters most here: an explicit route
registered earlier (the probe page, PR 0.1) must keep answering once the
later `/tv` static mount for the built app exists, never swallowed by it
(spectra/app.py's own comment on why registration order is load-bearing).
Uses a throwaway TV_DIST (a hand-written index.html) rather than depending
on a real `npx vite build` having run — the real-browser proof that the
actual build renders and stays under the size budget is
scripts/check_tv_app_shell.py, a developer-run check like
scripts/check_song_strip_fps.py, not a pytest test."""
from __future__ import annotations

import pytest


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


@pytest.fixture
def fake_tv_dist(tmp_path, monkeypatch):
    from spectra import config as scfg
    dist = tmp_path / "tv-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>fake tv shell</title>")
    monkeypatch.setattr(scfg, "TV_DIST", dist)
    return dist


def test_probe_route_still_answers_once_the_tv_mount_exists(fake_tv_dist):
    c = _client()
    resp = c.get("/tv/probe")
    assert resp.status_code == 200
    assert "SPECTRA TV probe" in resp.text


def test_tv_mount_serves_its_own_index_for_everything_else(fake_tv_dist):
    c = _client()
    resp = c.get("/tv/")
    assert resp.status_code == 200
    assert "fake tv shell" in resp.text

    # An unknown client-side route under /tv/ falls back to the SPA shell
    # (html=True, same convention SPAStaticFiles already uses elsewhere),
    # not a 404 — a deep link into the TV app's own router (once it has
    # one) must still resolve to the shell.
    resp2 = c.get("/tv/some/unknown/route")
    assert resp2.status_code == 200
    assert "fake tv shell" in resp2.text


def test_no_tv_mount_when_the_build_is_absent(monkeypatch):
    """With no TV build on disk, no `/tv` mount is added at all — the
    request falls through to the main SPA's own catch-all (its
    html=True fallback), not a dedicated TV shell. The probe route is
    unaffected either way, since it's an explicit route, not a mount."""
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "TV_DIST", scfg.REPO_ROOT / "does" / "not" / "exist")
    c = _client()
    resp = c.get("/tv/")
    assert resp.status_code == 200
    assert "fake tv shell" not in resp.text

    resp2 = c.get("/tv/probe")
    assert resp2.status_code == 200
    assert "SPECTRA TV probe" in resp2.text
