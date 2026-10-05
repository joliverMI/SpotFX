"""HOUSE LIGHTING phase 2 — Serenity's voice colours (spectra/services/
house_voice.py + show_output's voice overlay), on the REAL output layers
(show_output, fx/device_output) with a fake host.

  1. listening / processing / responding paint Home Assistant's exact
     colours on the crystal and both sconces at the voice level; idle puts
     back what each fixture should show NOW (base state and level)
  2. skipped if busy: a Light Show hold or Level, a lent / switched-off
     fixture, no mode, standby — and a hold landing mid-utterance wins
  3. a base change mid-utterance does not clobber the voice; it applies
     on idle
  4. a stuck overlay expires; one whose mode stopped is let go
  5. the call never waits: synchronous, and it never touches the network
"""
from __future__ import annotations

import inspect

import pytest

from fx import device_output
from spectra.models.house_mode import HouseMode

VOICE = ("crystal", "sconce-kitchen-left", "sconce-kitchen-right")


class FakeDev:
    def __init__(self, did, kind="wled"):
        self.id = did
        self.name = did
        self.type = kind
        self.frozen = False


class FakeHost:
    def __init__(self):
        self.devices = {d: FakeDev(d) for d in VOICE + ("tv-backlight", "porch-rail")}
        self.virtuals = {}

    def scope_device_ids(self):
        return None


class Clock:
    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now


@pytest.fixture
def voice(monkeypatch):
    from spectra.services import house, house_fixtures, house_store, house_voice, show_output
    host = FakeHost()
    gate = [(None, None)]
    monkeypatch.setattr(show_output, "_host", lambda: host)
    monkeypatch.setattr(house, "gate", lambda: gate[0])
    house_fixtures.deps = house_fixtures.Deps(host=lambda: host)
    clock = Clock()
    house_voice.clock = clock
    mode = house_store.put_mode(HouseMode(name="Standard"))
    st = house_store.state()
    st.mode_id = mode.id
    house_store.save_state()

    class W:
        pass
    w = W()
    w.v, w.so, w.gate, w.clock, w.store, w.hf = (house_voice, show_output, gate,
                                                 clock, house_store, house_fixtures)
    return w


def _state(did):
    tg = device_output.target(did)
    return (tg.state, tg.color, tg.level) if tg is not None else None


def test_listening_paints_has_exact_colour_and_idle_restores_the_base(voice):
    voice.so.set_base({"crystal": 0.03}, {"sconce-kitchen-right": "dark"})
    res = voice.v.set_voice("listening")
    assert res["status"] == "painted"
    assert res["fixtures"] == list(VOICE)
    for did in VOICE:
        assert _state(did) == ("steady", (0.0, 0.0, 255.0), 1.0)
    res = voice.v.set_voice("processing")
    assert _state("crystal") == ("steady", (38.0, 162.0, 105.0), 1.0)
    voice.v.set_voice("responding")
    assert _state("crystal")[1] == (97.0, 53.0, 131.0)
    res = voice.v.set_voice("idle")
    assert res["status"] == "cleared"
    assert _state("crystal") == ("show", None, 0.03), "back to the mode's 3%"
    assert _state("sconce-kitchen-right")[0] == "dark", "back to the mode's off"
    assert _state("sconce-kitchen-left")[0] == "show"
    assert voice.so.overlay_snapshot() == {}


def test_a_fixture_the_light_show_holds_is_skipped(voice):
    voice.so.set_state(["crystal"], "steady", color=(255, 0, 0))
    voice.so.add_level(["sconce-kitchen-left"], 0.5, until="released")
    res = voice.v.set_voice("listening")
    assert res["fixtures"] == ["sconce-kitchen-right"]
    reasons = {s["fixture"]: s["reason"] for s in res["skipped"]}
    assert "Light Show holds it" in reasons["crystal"]
    assert "Level" in reasons["sconce-kitchen-left"]
    assert _state("crystal")[1] == (255.0, 0.0, 0.0), "the show's hold untouched"


def test_a_hold_landing_mid_utterance_wins_and_survives_idle(voice):
    voice.v.set_voice("listening")
    voice.so.set_state(["crystal"], "steady", color=(0, 255, 0))
    assert _state("crystal")[1] == (0.0, 255.0, 0.0)
    assert "crystal" not in voice.so.overlay_snapshot()
    voice.v.set_voice("idle")
    assert _state("crystal")[:2] == ("steady", (0.0, 255.0, 0.0))


def test_a_base_change_mid_utterance_waits_for_idle(voice):
    voice.v.set_voice("listening")
    voice.so.set_base({"crystal": 0.13}, {"crystal": "dark"})
    assert _state("crystal") == ("steady", (0.0, 0.0, 255.0), 1.0)
    voice.v.set_voice("idle")
    assert _state("crystal") == ("dark", None, 0.13)


def test_lent_and_switched_off_fixtures_are_skipped(voice):
    st = voice.store.state()
    from spectra.models.house_mode import FixtureOverride
    st.fixtures["crystal"] = FixtureOverride(power="off")
    device_output.set_withheld({"sconce-kitchen-left": "lent: x"})
    res = voice.v.set_voice("listening")
    assert res["fixtures"] == ["sconce-kitchen-right"]


def test_no_mode_or_standby_skips_and_leaves_nothing_behind(voice):
    st = voice.store.state()
    st.mode_id = None
    res = voice.v.set_voice("listening")
    assert res["status"] == "skipped" and "no house mode" in res["reason"]
    assert voice.so.overlay_snapshot() == {}
    mode = voice.store.list_modes()[0]
    st.mode_id = mode.id
    voice.gate[0] = ("standby", "a camera run is measuring the room")
    res = voice.v.set_voice("listening")
    assert res["status"] == "skipped" and "standing by" in res["reason"]


def test_a_stuck_overlay_expires(voice):
    voice.v.set_voice("listening")
    voice.clock.now += voice.v.VOICE_MAX_S - 1
    assert voice.v.expire() is None
    voice.clock.now += 2
    res = voice.v.expire()
    assert res["status"] == "expired"
    assert voice.so.overlay_snapshot() == {}
    assert voice.v.status()["state"] == "idle"


def test_an_overlay_is_let_go_when_the_mode_stops(voice):
    voice.v.set_voice("responding")
    voice.store.state().mode_id = None
    res = voice.v.expire()
    assert res["status"] == "expired"
    assert _state("crystal")[0] == "show"


def test_the_call_never_waits():
    """Structural, over the module's CODE (its prose discusses waiting):
    no coroutine, no await, no network client anywhere in it."""
    import ast

    from spectra.services import house_voice
    assert not inspect.iscoroutinefunction(house_voice.set_voice)
    tree = ast.parse(inspect.getsource(house_voice))
    awaits = [n for n in ast.walk(tree)
              if isinstance(n, (ast.Await, ast.AsyncFunctionDef))]
    assert awaits == []
    imported = {a.name.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"requests", "httpx", "socket", "urllib"}


def test_an_invalid_state_is_refused(voice):
    assert voice.v.set_voice("shouting")["status"] == "invalid"
