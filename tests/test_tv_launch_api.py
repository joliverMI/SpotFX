"""The "one tap" API routes (data/tv-display-plan/plan.html PR 1.6,
spectra/api/tv_launch.py) over FastAPI's real TestClient. No real Home
Assistant call — `tv_launch.put_on_tv` is monkeypatched for the
`/api/tv/put-on-tv` tests, the same "no TV call in any test" posture as
every other test touching this feature."""
from __future__ import annotations

from dataclasses import dataclass

from spectra.services import tv_launch


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_get_launch_config_defaults():
    r = _client().get("/api/tv/launch-config")
    assert r.status_code == 200
    assert r.json() == {"auto_open_enabled": False, "script_entity": None}


def test_put_launch_config_is_a_partial_update():
    c = _client()
    r = c.put("/api/tv/launch-config", json={"auto_open_enabled": True})
    assert r.status_code == 200
    assert r.json() == {"auto_open_enabled": True, "script_entity": None}

    r2 = c.put("/api/tv/launch-config", json={"script_entity": "script.my_tv"})
    assert r2.status_code == 200
    assert r2.json() == {"auto_open_enabled": True, "script_entity": "script.my_tv"}

    # a GET afterward reflects the same persisted state
    assert c.get("/api/tv/launch-config").json() == r2.json()


def test_put_launch_config_the_json_string_false_resolves_to_false_not_true():
    c = _client()
    c.put("/api/tv/launch-config", json={"auto_open_enabled": True})
    r = c.put("/api/tv/launch-config", json={"auto_open_enabled": "false"})
    assert r.status_code == 200
    assert r.json()["auto_open_enabled"] is False
    assert c.get("/api/tv/launch-config").json()["auto_open_enabled"] is False


def test_put_launch_config_refuses_a_malformed_auto_open_value_with_422():
    c = _client()
    r = c.put("/api/tv/launch-config", json={"auto_open_enabled": "yes"})
    assert r.status_code == 422
    # the refused write must not have landed
    assert c.get("/api/tv/launch-config").json()["auto_open_enabled"] is False


@dataclass
class _FakeHAResult:
    status: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "http_status": None, "detail": self.detail}


def test_post_put_on_tv_calls_through_and_reports_the_result(monkeypatch):
    calls = []

    async def fake_put_on_tv(script_entity=None):
        calls.append(script_entity)
        return _FakeHAResult("sent", "Home Assistant: script.turn_on called")

    monkeypatch.setattr(tv_launch, "put_on_tv", fake_put_on_tv)

    r = _client().post("/api/tv/put-on-tv", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "sent"
    assert calls == [None]


def test_post_put_on_tv_passes_through_an_explicit_script_entity(monkeypatch):
    calls = []

    async def fake_put_on_tv(script_entity=None):
        calls.append(script_entity)
        return _FakeHAResult("sent")

    monkeypatch.setattr(tv_launch, "put_on_tv", fake_put_on_tv)

    _client().post("/api/tv/put-on-tv", json={"script_entity": "script.explicit"})
    assert calls == ["script.explicit"]


def test_post_put_on_tv_reports_unconfigured_without_crashing(monkeypatch):
    async def fake_put_on_tv(script_entity=None):
        return _FakeHAResult("unconfigured", "Home Assistant is not configured on this host")

    monkeypatch.setattr(tv_launch, "put_on_tv", fake_put_on_tv)

    r = _client().post("/api/tv/put-on-tv", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "unconfigured"
