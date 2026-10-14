"""The kiosk view's framing header (song-layout-plan, data/ui-layout-plan/
report.md's kiosk section) — Home Assistant hosts /?kiosk=1 in a dashboard-
tab iframe, which the browser refuses with no frame-ancestors allow-list.
spectra/app.py's middleware sets it on every response; spectra/config.py's
kiosk_frame_ancestors() is the one definition, overridable by env."""
from __future__ import annotations

from fastapi.testclient import TestClient

from spectra import config
from spectra.app import create_app


def _client():
    return TestClient(create_app())


def test_default_origins_are_rivers_two_home_assistant_addresses():
    assert config.kiosk_frame_ancestors() == [
        "http://homeassistant.local:8123", "http://192.168.40.16:8123"]


def test_every_response_carries_the_header():
    body = _client().get("/api/status").json()
    resp = _client().get("/api/status")
    assert body["app"] == "SPECTRA"
    assert resp.headers["content-security-policy"] == (
        "frame-ancestors http://homeassistant.local:8123 http://192.168.40.16:8123")


def test_env_override_replaces_the_default(monkeypatch):
    monkeypatch.setenv("SPECTRA_KIOSK_FRAME_ANCESTORS", "http://other:1234")
    assert config.kiosk_frame_ancestors() == ["http://other:1234"]
    resp = _client().get("/api/status")
    assert resp.headers["content-security-policy"] == "frame-ancestors http://other:1234"


def test_empty_override_means_nobody_may_frame_it(monkeypatch):
    monkeypatch.setenv("SPECTRA_KIOSK_FRAME_ANCESTORS", "")
    assert config.kiosk_frame_ancestors() == []
    resp = _client().get("/api/status")
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
