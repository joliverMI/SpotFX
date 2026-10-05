"""Sonic's Light Show authority, phase 3 (spectra/services/show_console.py).
Reuses the `room` fixture from test_light_show (store isolation, gate open,
a fake live host) and show_arms' `_play_uri` pattern from test_light_show_arms.
No live access: every write goes through the exact functions the human UI
and the Build view already call.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.light_show import ActionSet
from spectra.services import show_arms, show_console, show_cues, show_output, show_store
from tests.test_light_show import A, room  # noqa: F401  (fixture)


def _run(coro):
    return asyncio.run(coro)


def _set(name="Crystal Steady", actions=None):
    return show_store.put_set(ActionSet(name=name, actions=actions or [
        A("device_state", target={"kind": "category", "id": "Matrix"},
          state="steady", fade_ms=0)]))


@pytest.fixture
def cues_file(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SHOW_CUES_FILE", tmp_path / "show_cues.json")
    yield


def _play_uri(uri):
    show_arms.current_uri = lambda: uri


# ── name resolution never guesses ──────────────────────────────────────────

def test_fire_show_set_refuses_an_unknown_name_with_close_matches(room):
    _set("Crystal Steady")
    result = _run(show_console._op_fire_show_set("Cristal Steady"))
    assert result["status"] == "rejected"
    assert "Crystal Steady" in result["close_matches"]
    assert "Crystal Steady" in result["known_sets"]


def test_disarm_show_refuses_an_unknown_arm_with_close_matches(room):
    s = _set()
    show_arms.arm(set_id=s.id, on="scene_change")
    result = show_console._op_disarm_show("Crystall Steady")
    assert result["status"] == "rejected"
    assert "Crystal Steady" in result["close_matches"]


def test_hold_device_refuses_an_unknown_target_with_close_matches(room):
    result = _run(show_console._op_hold_device(state="dark", target_kind="category",
                                               target_name="Strip"))
    assert result["status"] == "rejected"
    assert "Strips" in result["close_matches"]


# ── every write says what ran ───────────────────────────────────────────────

def test_fire_show_set_by_id_or_exact_name_says_what_ran(room):
    s = _set("Crystal Steady")
    result = _run(show_console._op_fire_show_set(s.id))
    assert result["status"] == "applied"
    assert "Crystal Steady" in result["summary"]
    result = _run(show_console._op_fire_show_set("crystal steady"))
    assert result["status"] == "applied"


def test_create_show_set_never_overwrites_a_same_named_set(room):
    first = show_console._op_create_show_set("Encore")
    assert first["status"] == "applied"
    second = show_console._op_create_show_set("Encore")
    assert second["status"] == "rejected"
    assert len(show_store.list_sets()) == 1


def test_arm_disarm_and_disarm_all_roundtrip(room):
    s = _set()
    armed = _run(show_console._op_arm_show_set(s.id, on="high"))
    assert armed["status"] == "applied"
    assert armed["arm"]["on"] == "high"
    board = show_console._op_show_status()
    assert len(board["arms"]["armed"]) == 1

    result = show_console._op_disarm_show(armed["arm"]["label"])
    assert result["status"] == "applied"
    assert show_console._op_show_status()["arms"]["armed"] == []

    _run(show_console._op_arm_show_set(s.id, on="low"))
    _run(show_console._op_arm_show_set(s.id, on="high"))
    cleared = show_console._op_disarm_all_show()
    assert len(cleared["disarmed"]) == 2
    assert show_console._op_show_status()["arms"]["armed"] == []


def test_arm_show_set_refuses_an_unknown_trigger(room):
    s = _set()
    result = _run(show_console._op_arm_show_set(s.id, on="sometime"))
    assert result["status"] == "rejected"


def test_hold_and_dim_device_fire_the_real_action_kinds(room):
    held = _run(show_console._op_hold_device(state="dark", target_kind="everything"))
    assert held["status"] == "applied"
    assert "dark" in held["summary"]
    status = show_output.status()
    assert len(status["holds"]) > 0

    dimmed = _run(show_console._op_dim_device(level=40, target_kind="category",
                                              target_name="Matrix", duration_s=5))
    assert dimmed["status"] == "applied"
    status = show_output.status()
    assert any(lv["level"] == pytest.approx(0.4) for lv in status["levels"])


def test_hold_device_refuses_while_the_show_stands_down(room):
    room.gate["reason"] = "a preview holds the room"
    result = _run(show_console._op_hold_device(state="dark"))
    assert result["status"] == "refused"
    assert "standing down" in result["summary"]


def test_move_high_low_needs_a_playing_song(room, cues_file):
    show_arms.current_uri = show_arms._bridge_uri
    result = _run(show_console._op_move_high_low("high", 30.0))
    assert result["status"] == "rejected"
    assert "nothing is playing" in result["reason"]


def test_move_high_low_writes_the_override_for_the_playing_song(room, cues_file):
    _play_uri("spotify:track:sonic-move")
    result = _run(show_console._op_move_high_low("high", 42.5))
    assert result["status"] == "applied"
    saved = show_cues.overrides_for("spotify:track:sonic-move")
    assert saved["high"]["timestamp_ms"] == 42_500


def test_move_high_low_refuses_a_bad_level(room, cues_file):
    _play_uri("spotify:track:sonic-move")
    result = _run(show_console._op_move_high_low("medium", 1.0))
    assert result["status"] == "rejected"


def test_end_show_reports_and_puts_the_room_back(room):
    _run(show_console._op_hold_device(state="dark"))
    result = _run(show_console._op_end_show())
    assert result["status"] == "applied"
    assert "report" in result
    assert show_output.status()["holds"] == []


def test_list_and_create_show_set_round_trip(room):
    _set("First")
    _set("Second")
    out = show_console._op_list_show_sets()
    names = {s["name"] for s in out["sets"]}
    assert {"First", "Second"} <= names


def test_a_room_effect_set_arms_and_fires_through_the_same_operations(room, monkeypatch):
    """Captain's intent: future room-effect actions are reachable from Sonic
    exactly like any lighting set -- no special-cased operation."""
    started = {}

    async def start(room_obj, spec):
        started["spec"] = spec
        return {"status": "applied"}

    async def stop():
        started["stopped"] = True
        return {"status": "applied"}

    from spectra.services import room_effects
    monkeypatch.setattr(show_console.show_actions.room_effect_runner, "start", start)
    monkeypatch.setattr(show_console.show_actions.room_effect_runner, "stop", stop)
    monkeypatch.setattr(show_console.show_actions.room_effect_runner, "load_effects",
                        lambda: [room_effects.RoomEffectSpec(room_id="r1", name="Dim Wave")])
    monkeypatch.setattr(show_console.show_actions.room_effect_runner, "get_room",
                        lambda rid: object())
    monkeypatch.setattr(show_console.show_actions.room_effect_runner, "ceiling_s",
                        lambda: 180.0)
    monkeypatch.setattr(show_console.show_actions.room_effect_runner, "touch",
                        lambda *a: asyncio.sleep(0))

    s = _set("Wave On", actions=[A("room_effect", effect="Dim Wave")])
    armed = _run(show_console._op_arm_show_set(s.id, on="scene_change"))
    assert armed["status"] == "applied"
    fired = _run(show_console._op_fire_show_set(s.id))
    assert fired["status"] == "applied"
    assert started.get("spec") is not None
