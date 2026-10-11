"""THE OUTBOUND HOME ASSISTANT CLIENT (spectra/services/ha_client.py) —
NO NETWORK, NO LIVE HOME ASSISTANT anywhere in this file: `httpx.
MockTransport` stands in for Home Assistant exactly as `tests/
test_pretake_ping.py` does for River's own endpoint. `SPECTRA_HA_URL`/
`SPECTRA_HA_TOKEN` are DELETED rather than set by the autouse fixture, so
the inert/unconfigured path is the default here exactly as it is on an
unprovisioned host.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from spectra.services import ha_client


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SPECTRA_HA_URL", raising=False)
    monkeypatch.delenv("SPECTRA_HA_TOKEN", raising=False)
    yield


def _configured(monkeypatch, *, url="http://ha.invalid", token="not-the-real-one"):
    monkeypatch.setenv("SPECTRA_HA_URL", url)
    if token is not None:
        monkeypatch.setenv("SPECTRA_HA_TOKEN", token)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(seen=None, code=200, body=None):
    def handler(request):
        if seen is not None:
            import json as _json
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = _json.loads(request.content.decode())
        return httpx.Response(code, json=body if body is not None else [])
    return handler


# ── unconfigured == inert ───────────────────────────────────────────────────

def test_unconfigured_sends_nothing():
    assert ha_client.configured() is False
    result = _run(ha_client.call_service("script", "music_volume_set", {"volume": 50}))
    assert result.status == ha_client.STATUS_UNCONFIGURED
    assert "not configured" in result.detail.lower()
    assert result.http_status is None


# ── the wire ─────────────────────────────────────────────────────────────

def test_the_wire_shape(monkeypatch):
    _configured(monkeypatch, url="http://ha.invalid:8123", token="letmein")
    seen = {}
    result = _run(ha_client.call_service(
        "script", "music_volume_set", {"volume": 52}, client=_client(_ok(seen))))
    assert result.status == ha_client.STATUS_SENT
    assert seen["url"] == "http://ha.invalid:8123/api/services/script/music_volume_set"
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer letmein"
    assert seen["body"] == {"volume": 52}


def test_a_trailing_slash_on_the_url_is_stripped(monkeypatch):
    _configured(monkeypatch, url="http://ha.invalid:8123/")
    seen = {}
    _run(ha_client.call_service("scene", "turn_on", {"entity_id": "scene.music_mode"},
                               client=_client(_ok(seen))))
    assert seen["url"] == "http://ha.invalid:8123/api/services/scene/turn_on"


# ── missing token still sends, with no Authorization header ────────────────

def test_missing_token_still_sends_but_with_no_auth_header(monkeypatch):
    _configured(monkeypatch, token=None)
    seen = {}
    result = _run(ha_client.call_service("scene", "turn_on", {"entity_id": "scene.music_mode"},
                                        client=_client(_ok(seen))))
    assert result.status == ha_client.STATUS_SENT
    assert "auth" not in seen or seen["auth"] is None


def test_a_401_with_no_token_names_the_missing_token(monkeypatch):
    _configured(monkeypatch, token=None)
    result = _run(ha_client.call_service("scene", "turn_on", {"entity_id": "scene.music_mode"},
                                        client=_client(_ok(code=401))))
    assert result.status == ha_client.STATUS_FAILED
    assert result.http_status == 401
    assert "SPECTRA_HA_TOKEN" in result.detail


# ── non-2xx, and a transport exception — both fail-soft, never raise ──────

def test_a_non_2xx_answer_fails_soft(monkeypatch):
    _configured(monkeypatch)
    result = _run(ha_client.call_service("script", "music_volume_set", {"volume": 50},
                                        client=_client(_ok(code=500))))
    assert result.status == ha_client.STATUS_FAILED
    assert result.http_status == 500
    assert "500" in result.detail


def test_an_unreachable_host_fails_soft_never_raises(monkeypatch):
    _configured(monkeypatch)

    def boom(request):
        raise httpx.ConnectError("connection refused")

    result = _run(ha_client.call_service("script", "music_volume_set", {"volume": 50},
                                        client=_client(boom)))
    assert result.status == ha_client.STATUS_FAILED
    assert "ConnectError" in result.detail
    # the exception CLASS only — never the configured URL's own credentials
    assert "letmein" not in result.detail


def test_201_is_also_success(monkeypatch):
    _configured(monkeypatch)
    result = _run(ha_client.call_service("scene", "turn_on", {"entity_id": "scene.music_mode"},
                                        client=_client(_ok(code=201))))
    assert result.status == ha_client.STATUS_SENT


# ── list_scenes — the "any scene he makes" picker's data source ────────────

def _states_handler(entries, seen=None, code=200):
    def handler(request):
        if seen is not None:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["auth"] = request.headers.get("authorization")
        return httpx.Response(code, json=entries)
    return handler


def test_list_scenes_unconfigured_sends_nothing():
    result = _run(ha_client.list_scenes())
    assert result.status == ha_client.STATUS_UNCONFIGURED
    assert result.scenes == []


def test_list_scenes_filters_to_the_scene_domain_and_uses_friendly_name(monkeypatch):
    _configured(monkeypatch)
    seen = {}
    entries = [
        {"entity_id": "light.kitchen", "attributes": {"friendly_name": "Kitchen"}},
        {"entity_id": "scene.music_mode", "attributes": {"friendly_name": "Music Mode"}},
        {"entity_id": "scene.party_mode", "attributes": {}},
    ]
    result = _run(ha_client.list_scenes(client=_client(_states_handler(entries, seen))))
    assert result.status == ha_client.STATUS_SENT
    assert seen["url"] == "http://ha.invalid/api/states"
    assert seen["method"] == "GET"
    assert seen["auth"] == "Bearer not-the-real-one"
    assert result.scenes == [
        {"id": "scene.music_mode", "name": "Music Mode"},
        # no friendly_name attribute -> falls back to the object_id, as words
        {"id": "scene.party_mode", "name": "party mode"},
    ]


def test_list_scenes_a_non_2xx_fails_soft_with_an_empty_list(monkeypatch):
    _configured(monkeypatch)
    result = _run(ha_client.list_scenes(client=_client(_states_handler([], code=500))))
    assert result.status == ha_client.STATUS_FAILED
    assert result.scenes == []


def test_list_scenes_an_unreachable_host_fails_soft_never_raises(monkeypatch):
    _configured(monkeypatch)

    def boom(request):
        raise httpx.ConnectError("connection refused")
    result = _run(ha_client.list_scenes(client=_client(boom)))
    assert result.status == ha_client.STATUS_FAILED
    assert result.scenes == []
    assert "ConnectError" in result.detail
