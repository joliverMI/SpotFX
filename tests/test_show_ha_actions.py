"""THE LIGHT SHOW'S HOME ASSISTANT ACTIONS (ha_volume_absolute,
ha_volume_relative, ha_activate_scene — spectra/services/show_actions.py's
"ha" group) and the Sonic ad-hoc ops that fire them
(spectra/services/show_console.py). NO NETWORK anywhere in this file:
`ha_client.call_service`/`list_scenes` are monkeypatched to recording
fakes, the same posture `tests/test_ha_client.py` proves the real
transport layer with separately.

THE SCENE PICKER IS GENERIC, NOT AN ALLOW-LIST (the Admiral, 2026-10-11:
"I just want that button to run the sequence... I want to be able to
customize the scene in HA and trigger it as part of the light show") —
any scene.* entity, by its full id or by a name fetched live from Home
Assistant; there is nothing stored on SPECTRA's own side to restrict it.

THE HOUSE LAYER MUST NEVER GATE AN HA ACTION (the same message, part 2:
"it acts in HA ... so the resting house mode must not block or defer it
- the step always calls HA when it runs, whatever the house layer is
doing") — proven below by making the house layer actively resting/
driving and firing anyway.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.services import ha_client, room_controls, show_actions, show_console
from tests.test_light_show import A, fire, room  # noqa: F401  (fixture)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def ha_calls(monkeypatch):
    """Replaces the real outbound call with a recorder; defaults to
    reporting success for every call, like a healthy, configured HA."""
    calls = []
    result = {"status": ha_client.STATUS_SENT, "http_status": 200, "detail": "ok"}

    async def fake_call_service(domain, service, data=None, *, client=None):
        calls.append({"domain": domain, "service": service, "data": data})
        return ha_client.HAResult(status=result["status"],
                                  http_status=result["http_status"],
                                  detail=result["detail"])
    monkeypatch.setattr(ha_client, "call_service", fake_call_service)
    return calls, result


@pytest.fixture
def ha_scenes(monkeypatch):
    """Replaces the live scene lookup with a fixed, fake Home Assistant
    scene list — his two real scenes, by the names fetching would give.
    Also sets SPECTRA_HA_URL, since this simulates a reachable, configured
    Home Assistant (configured() reads the env, not the fetch)."""
    monkeypatch.setenv("SPECTRA_HA_URL", "http://ha.invalid")
    scenes = [{"id": "scene.music_mode", "name": "Music Mode"},
              {"id": "scene.party_mode", "name": "Party Mode"}]

    async def fake_list_scenes(*, client=None):
        return ha_client.HAStates(status=ha_client.STATUS_SENT,
                                  http_status=200, scenes=list(scenes))
    monkeypatch.setattr(ha_client, "list_scenes", fake_list_scenes)
    return scenes


def _house_actively_resting(monkeypatch):
    """Simulates a house mode genuinely driving the room right now — the
    shape `response_deferral()`/`scene_deferral()` report when a resting
    mode owns the show. Used only to prove the HA actions ignore it."""
    from spectra.services import house
    monkeypatch.setattr(house, "layer_active", lambda: True)
    monkeypatch.setattr(house, "scene_deferral", lambda: "a house mode owns the room")
    monkeypatch.setattr(house, "response_deferral", lambda: "a house mode owns the room")
    monkeypatch.setattr(house, "house_overrides_display", lambda: True)


# ── ha_volume_absolute ──────────────────────────────────────────────────────

def test_volume_absolute_calls_the_fixed_script_with_volume(room, ha_calls):
    calls, _ = ha_calls
    run = fire([A("ha_volume_absolute", volume=52)])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "script", "service": "music_volume_set",
                      "data": {"volume": 52}}]


def test_volume_absolute_needs_no_room(room, ha_calls):
    room.gate["reason"] = "the room is released"
    run = fire([A("ha_volume_absolute", volume=52)])
    assert run["steps"][0]["status"] == "applied", \
        "an HA action must run even while the show may not touch the lights"


def test_volume_absolute_ignores_an_actively_resting_house_mode(room, ha_calls, monkeypatch):
    _house_actively_resting(monkeypatch)
    calls, _ = ha_calls
    run = fire([A("ha_volume_absolute", volume=52)])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "script", "service": "music_volume_set",
                      "data": {"volume": 52}}]


def test_volume_absolute_unconfigured_reports_not_configured(room, monkeypatch):
    async def unconfigured(domain, service, data=None, *, client=None):
        return ha_client.HAResult(status=ha_client.STATUS_UNCONFIGURED,
                                  detail="Home Assistant is not configured "
                                        "on this host (SPECTRA_HA_URL is unset)")
    monkeypatch.setattr(ha_client, "call_service", unconfigured)
    run = fire([A("ha_volume_absolute", volume=52)])
    assert run["steps"][0]["status"] == "failed"
    assert "not configured" in run["steps"][0]["detail"].lower()


def test_volume_absolute_range_is_enforced():
    with pytest.raises(show_actions.ActionError, match="maximum"):
        show_actions.validate("ha_volume_absolute", {"volume": 101})
    with pytest.raises(show_actions.ActionError, match="minimum"):
        show_actions.validate("ha_volume_absolute", {"volume": -1})


# ── ha_volume_relative ──────────────────────────────────────────────────────

def test_volume_relative_calls_the_configured_entity_split_into_domain_service(
        room, ha_calls):
    calls, _ = ha_calls
    run = fire([A("ha_volume_relative", delta=8, ease_s=0)])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "script", "service": "music_volume_step",
                      "data": {"delta": 8}}]


def test_volume_relative_reads_a_changed_entity_setting(room, ha_calls):
    calls, _ = ha_calls
    _run(room_controls.apply_patch({"ha_volume_relative_entity": "script.other_step"}))
    fire([A("ha_volume_relative", delta=-8, ease_s=0)])
    assert calls == [{"domain": "script", "service": "other_step",
                      "data": {"delta": -8}}]


def test_volume_relative_refuses_a_malformed_entity_without_raising(room, monkeypatch, ha_calls):
    _run(room_controls.apply_patch({"ha_volume_relative_entity": "not-an-entity"}))
    run = fire([A("ha_volume_relative", delta=8)])
    assert run["steps"][0]["status"] == "failed"
    assert "not a valid entity id" in run["steps"][0]["detail"]


# ── ha_activate_scene: any scene.* entity, no allow-list ───────────────────

def test_activate_scene_calls_scene_turn_on_with_the_entity(room, ha_calls):
    calls, _ = ha_calls
    run = fire([A("ha_activate_scene", scene="scene.music_mode")])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "scene", "service": "turn_on",
                      "data": {"entity_id": "scene.music_mode"}}]


def test_activate_scene_accepts_any_scene_entity_he_has_just_made(room, ha_calls):
    """No allow-list anywhere — a scene he made in HA ten seconds ago is
    reachable immediately, with no SPECTRA-side list to update first."""
    calls, _ = ha_calls
    run = fire([A("ha_activate_scene", scene="scene.brand_new_scene_he_just_made")])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "scene", "service": "turn_on",
                      "data": {"entity_id": "scene.brand_new_scene_he_just_made"}}]


def test_activate_scene_ignores_an_actively_resting_house_mode(room, ha_calls, monkeypatch):
    """THE EXACT CASE NAMED BY THE ADMIRAL: scene.turn_on must reach Home
    Assistant whatever the house layer is doing — a resting house mode
    must never block or defer it."""
    _house_actively_resting(monkeypatch)
    calls, _ = ha_calls
    run = fire([A("ha_activate_scene", scene="scene.music_mode")])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "scene", "service": "turn_on",
                      "data": {"entity_id": "scene.music_mode"}}]


def test_activate_scene_refuses_a_non_scene_entity(room):
    with pytest.raises(show_actions.ActionError, match="not a scene entity"):
        show_actions.validate("ha_activate_scene", {"scene": "light.kitchen"})


def test_activate_scene_refuses_a_malformed_entity(room):
    with pytest.raises(show_actions.ActionError, match="not a valid entity id"):
        show_actions.validate("ha_activate_scene", {"scene": "not-an-entity"})


def test_activate_scene_default_is_music_mode():
    params = show_actions.validate("ha_activate_scene", {})
    assert params["scene"] == "scene.music_mode"


# ── ha_put_on_tv: "one tap" (data/tv-display-plan/plan.html PR 1.6) ────────
# — it calls `tv_launch.put_on_tv()` in-process, which itself calls
# `ha_client.call_service` the SAME way `ha_activate_scene` does, so the
# `ha_calls` fixture's existing monkeypatch of that one function already
# covers it — no second transport to fake.

def test_put_on_tv_calls_the_configured_script_by_default(room, ha_calls):
    calls, _ = ha_calls
    run = fire([A("ha_put_on_tv")])
    assert run["steps"][0]["status"] == "applied"
    from spectra.services import tv_launch
    assert calls == [{"domain": "script", "service": "turn_on",
                      "data": {"entity_id": tv_launch.DEFAULT_SCRIPT_ENTITY}}]


def test_put_on_tv_an_explicit_script_param_wins(room, ha_calls):
    calls, _ = ha_calls
    run = fire([A("ha_put_on_tv", script="script.some_other_tv")])
    assert run["steps"][0]["status"] == "applied"
    assert calls == [{"domain": "script", "service": "turn_on",
                      "data": {"entity_id": "script.some_other_tv"}}]


def test_put_on_tv_needs_no_room(room, ha_calls):
    room.gate["reason"] = "the room is released"
    run = fire([A("ha_put_on_tv")])
    assert run["steps"][0]["status"] == "applied", \
        "opening the TV app must run even while the show may not touch the lights"


def test_put_on_tv_ignores_an_actively_resting_house_mode(room, ha_calls, monkeypatch):
    _house_actively_resting(monkeypatch)
    calls, _ = ha_calls
    run = fire([A("ha_put_on_tv")])
    assert run["steps"][0]["status"] == "applied"
    assert len(calls) == 1


def test_put_on_tv_reports_unconfigured_as_failed_not_a_crash(room, ha_calls):
    _, result = ha_calls
    result["status"] = ha_client.STATUS_UNCONFIGURED
    result["detail"] = "Home Assistant is not configured on this host"
    run = fire([A("ha_put_on_tv")])
    assert run["steps"][0]["status"] == "failed"


# ── Sonic ad-hoc ops ─────────────────────────────────────────────────────────

def test_sonic_can_fire_ha_volume_absolute(room, ha_calls):
    calls, _ = ha_calls
    result = _run(show_console._op_set_ha_volume_absolute(volume=40))
    assert result["status"] == "applied"
    assert calls == [{"domain": "script", "service": "music_volume_set",
                      "data": {"volume": 40}}]


def test_sonic_ad_hoc_ha_action_needs_no_room(room, ha_calls):
    """The same guarantee as test_volume_absolute_needs_no_room, proven
    through Sonic's own ad-hoc path (_fire_one), not just the direct
    show_actions.fire() path — the two must never disagree about which
    action kinds require the room."""
    room.gate["reason"] = "the room is released"
    calls, _ = ha_calls
    result = _run(show_console._op_set_ha_volume_absolute(volume=40))
    assert result["status"] == "applied", \
        "a Sonic-issued HA action must run even while the show may not touch the lights"
    assert calls == [{"domain": "script", "service": "music_volume_set",
                      "data": {"volume": 40}}]


def test_sonic_can_fire_ha_volume_relative(room, ha_calls):
    calls, _ = ha_calls
    result = _run(show_console._op_set_ha_volume_relative(delta=-8, ease_s=0))
    assert result["status"] == "applied"
    assert calls == [{"domain": "script", "service": "music_volume_step",
                      "data": {"delta": -8}}]


def test_sonic_activates_a_scene_given_as_a_full_entity_id_with_no_fetch(room, ha_calls, monkeypatch):
    """A full entity id never needs to fetch HA's live list at all — so
    it works even while that fetch would fail."""
    calls, _ = ha_calls

    async def fetch_would_fail(*, client=None):
        raise AssertionError("list_scenes must not be called for a full entity id")
    monkeypatch.setattr(ha_client, "list_scenes", fetch_would_fail)
    result = _run(show_console._op_activate_ha_scene(scene_name="scene.brand_new"))
    assert result["status"] == "applied"
    assert calls[-1]["data"] == {"entity_id": "scene.brand_new"}


def test_sonic_resolves_a_bare_name_against_the_live_ha_list(room, ha_calls, ha_scenes):
    result = _run(show_console._op_activate_ha_scene(scene_name="Party Mode"))
    assert result["status"] == "applied"
    assert ha_calls[0][-1]["data"] == {"entity_id": "scene.party_mode"}


def test_sonic_defaults_to_music_mode_with_no_live_fetch_needed(room, ha_calls, monkeypatch):
    calls, _ = ha_calls

    async def fetch_would_fail(*, client=None):
        raise AssertionError("list_scenes must not be called for the default")
    monkeypatch.setattr(ha_client, "list_scenes", fetch_would_fail)
    result = _run(show_console._op_activate_ha_scene())
    assert result["status"] == "applied"
    assert calls[-1]["data"] == {"entity_id": "scene.music_mode"}


def test_sonic_refuses_an_unknown_bare_name_with_close_matches(room, ha_scenes):
    result = _run(show_console._op_activate_ha_scene(scene_name="Muzik Mode"))
    assert result["status"] == "rejected"
    assert any("music mode" in m.lower() for m in result["close_matches"])


def test_sonic_refuses_a_bare_name_when_ha_is_unreachable(room, monkeypatch):
    async def unreachable(*, client=None):
        return ha_client.HAStates(status=ha_client.STATUS_FAILED,
                                  detail="Home Assistant could not be reached (ConnectError)")
    monkeypatch.setattr(ha_client, "list_scenes", unreachable)
    result = _run(show_console._op_activate_ha_scene(scene_name="Party Mode"))
    assert result["status"] == "rejected"
    assert "full entity id" in result["reason"]


def test_sonic_activate_scene_ignores_an_actively_resting_house_mode(room, ha_calls, monkeypatch):
    _house_actively_resting(monkeypatch)
    result = _run(show_console._op_activate_ha_scene(scene_name="scene.music_mode"))
    assert result["status"] == "applied"
    assert ha_calls[0][-1]["data"] == {"entity_id": "scene.music_mode"}


# ── the picker's live-fetch route ───────────────────────────────────────────

def test_ha_scenes_route_serves_the_live_list(room, ha_scenes):
    from fastapi.testclient import TestClient
    from spectra.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/light-show/ha-scenes")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert {"id": "scene.music_mode", "name": "Music Mode"} in body["scenes"]


def test_ha_scenes_route_reports_unconfigured_without_raising(room, monkeypatch):
    monkeypatch.delenv("SPECTRA_HA_URL", raising=False)
    from fastapi.testclient import TestClient
    from spectra.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/light-show/ha-scenes")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["scenes"] == []
