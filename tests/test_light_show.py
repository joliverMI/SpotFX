"""THE LIGHT SHOW, phase 1 — the action catalogue, sets, End show, the gate,
and room effects as a first-class action (spectra/services/show_actions.py,
show_output.py, show_store.py). The per-fixture output layer itself is
proven at the transport in tests/test_device_output_landing.py; this file
proves what the show DOES with it and with every other action, against the
real stores in a scratch directory. No live access, ever: ownership, the
live host and SpotFX's colour-set API are faked at their seams.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from fx import device_output
from spectra.models.light_show import ActionSet, ShowAction
from spectra.services import (room_controls, scene_store, show_actions,
                              show_output, show_store)


class Registry:
    """The SHAPE of fx's real `Virtuals`/`Devices` registries: iterable ids,
    `.get()`, `.values()` — and deliberately NO `.items()`/`[]`. A plain dict
    here is how a supervisor crash on the live host once passed every test."""

    def __init__(self, objs):
        self._o = dict(objs)

    def __iter__(self):
        return iter(self._o)

    def get(self, *a):
        return self._o.get(*a)

    def values(self):
        return self._o.values()


@pytest.fixture
def room(tmp_path, monkeypatch):
    """A scratch room: stores repointed, reconcilers inert, SPECTRA "owns",
    and a fake live host with three fixtures behind one shared virtual."""
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_EFFECTS_FILE", tmp_path / "room_effects.json")
    calls = []

    async def none(*a, **kw):
        calls.append(kw)
        return None
    for name in ("reconcile_ambient_if_changed", "reconcile_dark_light_if_changed",
                 "reconcile_force_scene_if_changed", "reconcile_force_color_if_changed"):
        monkeypatch.setattr(room_controls, name, none)
    gate = {"reason": None}
    monkeypatch.setattr(show_output, "refusal", lambda: gate["reason"])

    dev = lambda did, name: SimpleNamespace(id=did, name=name, type="dummy", frozen=False)
    host = SimpleNamespace(
        devices=Registry({"tv": dev("tv", "TV backlight"), "sl": dev("sl", "Sconce left"),
                          "cr": dev("cr", "Crystal")}),
        virtuals=Registry({"tv-mapper": SimpleNamespace(active=True, _segments=[
            ["tv", 0, 9, False], ["sl", 0, 9, False]]),
            "crystal-mapper": SimpleNamespace(active=True, _segments=[["cr", 0, 9, False]])}))
    from spectra.services import live_host
    monkeypatch.setattr(live_host.live, "host", host)
    from fx import device_model
    monkeypatch.setattr(device_model, "get_virtuals_for_category",
                        lambda c: {"Strips": ["tv-mapper"], "Matrix": ["crystal-mapper"]}.get(c, []))
    written = {}

    async def color_writer(cid, disabled):
        before = written.get(cid, False)
        written[cid] = disabled
        return before
    monkeypatch.setattr(show_actions, "color_set_writer", color_writer)
    return SimpleNamespace(gate=gate, host=host, calls=calls, color=written)


def A(kind, **params):
    return ShowAction(kind=kind, params=params)


def fire(actions, **kw):
    return asyncio.run(show_actions.fire(actions, name="t", **kw))


# ── the catalogue ──────────────────────────────────────────────────────────

def test_catalogue_carries_his_list_and_the_addons():
    kinds = {k["kind"] for k in show_actions.catalogue()["kinds"]}
    assert {"ambient", "display_mode", "force_scene", "force_color",
            "scene_enabled", "color_set_enabled", "device_state", "level",
            "flash", "drift_gradient", "scene_change_mode", "fire_scene",
            "apply_color_set", "room_effect", "stop_room_effect",
            "pause"} <= kinds


def test_registry_is_the_extension_point():
    async def apply(p, ctx):
        return show_actions.Outcome("applied", f"poked {p['n']:g}")
    show_actions.register(show_actions.ActionKind(
        name="poke", label="Poke", group="control",
        params=[show_actions.Param("n", "number", min=0, max=5, default=1)],
        help="", restore="", apply=apply, needs_room=False))
    try:
        run = fire([A("poke", n=3)])
        assert run["steps"][0]["status"] == "applied"
        assert run["steps"][0]["detail"] == "poked 3"
        assert "poke" in {k["kind"] for k in show_actions.catalogue()["kinds"]}
    finally:
        show_actions.ACTION_KINDS.pop("poke")


def test_validation_names_the_problem():
    with pytest.raises(show_actions.ActionError, match="unknown parameter"):
        show_actions.validate("display_mode", {"mode": "dark", "nonsense": 1})
    with pytest.raises(show_actions.ActionError, match="not one of"):
        show_actions.validate("display_mode", {"mode": "purple"})
    with pytest.raises(show_actions.ActionError, match="above the maximum"):
        show_actions.validate("level", {"target": {"kind": "everything"}, "level": 900})
    with pytest.raises(show_actions.ActionError, match="needs a duration"):
        show_actions.validate("level", {"target": {"kind": "everything"},
                                        "until": "time", "duration_s": 0})


# ── room settings: one write, a baseline, End show ────────────────────────

def test_consecutive_room_settings_coalesce_into_one_save(room, monkeypatch):
    saves = []
    real = room_controls.apply_patch

    async def spy(body, **kw):
        saves.append(dict(body))
        return await real(body, **kw)
    monkeypatch.setattr(room_controls, "apply_patch", spy)
    run = fire([A("display_mode", mode="dark"), A("scene_change_mode", mode="analysed"),
                A("ambient", on=True, speed="snap")])
    assert run["state"] == "done"
    assert saves == [{"display_mode": "dark", "scene_change_mode": "analysed",
                      "ambient_enabled": True}]
    st = room_controls.load_room_controls()
    assert st.display_mode == "dark" and st.ambient_enabled is True


def test_end_show_restores_settings_but_leaves_his_own_changes(room):
    fire([A("display_mode", mode="light"), A("scene_change_mode", mode="transitions")])
    # he changes one of them by hand afterwards
    asyncio.run(room_controls.apply_patch({"scene_change_mode": "analysed"}))
    report = asyncio.run(show_actions.end_show())
    st = room_controls.load_room_controls()
    assert st.display_mode == "default"                 # put back
    assert st.scene_change_mode == "analysed"           # his, left alone
    assert [x["key"] for x in report["left_alone"]] == ["room:scene_change_mode"]
    assert show_store.state().baselines == {}


def test_changing_a_setting_twice_keeps_the_first_original(room):
    fire([A("display_mode", mode="dark")])
    fire([A("display_mode", mode="light")])
    asyncio.run(show_actions.end_show())
    assert room_controls.load_room_controls().display_mode == "default"


def test_scene_toggle_is_a_single_key_raw_patch(room, tmp_path):
    from spectra import config as scfg
    from spectra.models.scene import SceneV2
    s = SceneV2(name="Fish")
    raw = {s.id: {**json.loads(s.model_dump_json()), "legacy_marker": "keep me"}}
    scfg.SCENES_FILE.write_text(json.dumps(raw))
    run = fire([A("scene_enabled", scenes=[s.id], enabled=False)])
    assert run["steps"][0]["status"] == "applied"
    after = json.loads(scfg.SCENES_FILE.read_text())[s.id]
    assert after["disabled"] is True and after["legacy_marker"] == "keep me"
    asyncio.run(show_actions.end_show())
    assert json.loads(scfg.SCENES_FILE.read_text())[s.id]["disabled"] is False


def test_color_set_toggle_goes_through_the_writer_and_is_restored(room, monkeypatch):
    from spectra.services import color_sets
    monkeypatch.setattr(color_sets, "get_by_id",
                        lambda cid: SimpleNamespace(name="Blues", disabled=room.color.get(cid, False)))
    fire([A("color_set_enabled", color_sets=["blues"], enabled=False)])
    assert room.color["blues"] is True
    asyncio.run(show_actions.end_show())
    assert room.color["blues"] is False


# ── the gate ───────────────────────────────────────────────────────────────

def test_every_step_is_refused_with_a_reason_when_the_show_may_not_act(room):
    room.gate["reason"] = "the room is released"
    run = fire([A("display_mode", mode="dark"),
                A("device_state", target={"kind": "everything"}, state="dark")])
    assert run["state"] == "refused"
    assert all(s["status"] == "refused" and "released" in s["detail"] for s in run["steps"])
    assert room_controls.load_room_controls().display_mode == "default"
    assert device_output.snapshot() == {}


def test_standdown_reason_names_a_preview(monkeypatch):
    from spectra.services import preview_pause
    monkeypatch.setattr(preview_pause, "active", lambda: True)
    assert "preview" in show_output.standdown_reason()


def test_the_api_refuses_a_fire_with_409(room, monkeypatch):
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    room.gate["reason"] = "a camera run is measuring the room"
    client = TestClient(create_app())
    r = client.post("/api/light-show/fire",
                    json={"actions": [{"kind": "display_mode", "params": {"mode": "dark"}}]})
    assert r.status_code == 409 and "camera run" in r.json()["detail"]


# ── device actions ─────────────────────────────────────────────────────────

def test_category_resolves_to_its_fixtures_and_one_fixture_alone(room):
    assert show_output.resolve_target({"kind": "category", "id": "Strips"})[0] == ["tv", "sl"]
    assert show_output.resolve_target({"kind": "fixture", "id": "sl"})[0] == ["sl"]
    devices, problems = show_output.resolve_target({"kind": "fixture", "id": "nope"})
    assert devices == [] and "nope" in problems[0]


def test_device_state_steady_defaults_to_the_ambient_colour(room):
    run = fire([A("device_state", target={"kind": "fixture", "id": "sl"}, state="steady")])
    assert run["steps"][0]["status"] == "applied"
    tg = device_output.target("sl")
    assert tg.state == "steady" and tg.color is not None
    assert "sl" in show_store.state().holds


def test_end_show_lets_every_fixture_go(room):
    fire([A("device_state", target={"kind": "category", "id": "Strips"}, state="dark"),
          A("level", target={"kind": "fixture", "id": "cr"}, level=30, until="released")])
    assert set(show_store.state().holds) == {"tv", "sl"}
    report = asyncio.run(show_actions.end_show(fade_ms=0))
    assert set(report["released_devices"]) == {"tv", "sl", "cr"}
    assert show_store.state().holds == {} and show_store.state().levels == []
    device_output.prune()
    assert device_output.snapshot() == {}


def test_levels_stack_and_end_on_their_own(room, monkeypatch):
    t = {"now": 1_000_000}
    monkeypatch.setattr(show_output, "now_ms", lambda: t["now"])
    fire([A("level", target={"kind": "fixture", "id": "cr"}, level=50,
            fade_in_ms=0, duration_s=10),
          A("level", target={"kind": "fixture", "id": "cr"}, level=50,
            fade_in_ms=0, until="scene_change")])
    assert device_output.target("cr").level == pytest.approx(0.25)
    show_output.on_scene_change()
    assert device_output.target("cr").level == pytest.approx(0.5)
    t["now"] += 11_000
    show_output._was_live = True
    show_output.tick()
    assert show_store.state().levels == []


def test_a_release_drops_every_hold_before_the_fade(room):
    fire([A("device_state", target={"kind": "everything"}, state="dark")])
    show_output.on_release()
    assert device_output.snapshot() == {}
    assert show_store.state().holds == {}


def test_holds_survive_a_restart_and_an_expired_level_does_not(room, monkeypatch):
    t = {"now": 5_000_000}
    monkeypatch.setattr(show_output, "now_ms", lambda: t["now"])
    fire([A("device_state", target={"kind": "fixture", "id": "tv"}, state="dark"),
          A("level", target={"kind": "fixture", "id": "cr"}, level=40, duration_s=5)])
    show_store.reset_memory()
    device_output.clear_all()
    t["now"] += 6_000
    result = show_output.repush()
    assert result["holds"] == ["tv"] and result["levels"] == 0
    assert device_output.target("tv").state == "dark"


# ── sets ───────────────────────────────────────────────────────────────────

def test_a_set_with_a_pause_returns_at_the_pause_and_finishes_later(room):
    async def go():
        s = show_store.put_set(ActionSet(name="Intermission", actions=[
            A("display_mode", mode="dark"), A("pause", seconds=0.2),
            A("device_state", target={"kind": "fixture", "id": "cr"}, state="dark")]))
        first = await show_actions.fire_set("intermission")
        assert first["steps"][0]["status"] == "applied"
        assert first["steps"][2]["status"] == "pending"
        await asyncio.sleep(0.4)
        return show_actions.runs()[0], s
    final, s = asyncio.run(go())
    assert final["state"] == "done" and final["set_id"] == s.id
    assert [x["status"] for x in final["steps"]] == ["applied"] * 3


def test_partial_failure_names_the_step_that_did_not_run(room):
    run = fire([A("display_mode", mode="dark"),
                A("device_state", target={"kind": "fixture", "id": "ghost"}, state="dark"),
                A("flash", target={"kind": "fixture", "id": "cr"})])
    assert run["state"] == "partial"
    statuses = [s["status"] for s in run["steps"]]
    assert statuses == ["applied", "failed", "applied"]
    assert "ghost" in run["steps"][1]["detail"]


def test_set_names_are_unique_ignoring_case(room):
    show_store.put_set(ActionSet(name="Blackout"))
    with pytest.raises(show_store.SetNameTaken):
        show_store.put_set(ActionSet(name="blackout"))


def test_conflicts_inside_a_set_are_named_and_later_wins(room):
    acts = [A("display_mode", mode="dark"), A("display_mode", mode="light")]
    assert "step 2 wins" in show_actions.conflicts(acts)[0]
    fire(acts)
    assert room_controls.load_room_controls().display_mode == "light"


def test_preview_writes_nothing(room):
    out = show_actions.preview([A("display_mode", mode="dark")])
    assert "→ 'dark'" in out[0]["change"]
    assert room_controls.load_room_controls().display_mode == "default"


# ── room effects as a first-class action ───────────────────────────────────

class StubRunner(show_actions.RoomEffectRunner):
    """A stub room effect: records what the show asked of room_effects' one
    entry point. A NEW room effect kind ('stub_pulse') — the show needs no
    change to arm or trigger it."""

    def __init__(self, specs):
        self.specs = specs
        self.started = []
        self.stopped = 0
        self.touched = 0

    async def start(self, room, spec):
        self.started.append(spec)
        return {"running": True}

    async def stop(self):
        self.stopped += 1
        return {"stopped": True}

    async def touch(self, window_s):
        self.touched += 1

    def get_room(self, room_id):
        return SimpleNamespace(id=room_id)

    def load_effects(self):
        return self.specs

    def ceiling_s(self):
        return 180.0


def _stub_spec():
    from spectra.services.room_effects import RoomEffectSpec
    return RoomEffectSpec(room_id="living", name="Pulse", kind="stub_pulse",
                          depth=0.5)


def test_a_stub_room_effect_is_triggerable_through_the_one_entry_point(room, monkeypatch):
    stub = StubRunner([_stub_spec()])
    monkeypatch.setattr(show_actions, "room_effect_runner", stub)

    async def go():
        run = await show_actions.fire([A("room_effect", effect="pulse",
                                         params={"depth": 0.9}, duration_s=0.3)],
                                      name="t")
        assert run["steps"][0]["status"] == "applied"
        assert show_store.state().room_effect["name"] == "Pulse"
        await asyncio.sleep(0.6)
        return run
    asyncio.run(go())
    assert stub.started[0].kind == "stub_pulse"
    assert stub.started[0].depth == 0.9               # override, this run only
    assert stub.touched >= 1                          # the hold kept alive
    assert stub.stopped == 1                          # stopped after its time
    assert show_store.state().room_effect is None
    assert "Pulse" in {e["name"] for e in show_actions.catalogue()["room_effects"]}


def test_room_effect_overrides_are_validated_by_the_effects_own_model(room, monkeypatch):
    monkeypatch.setattr(show_actions, "room_effect_runner", StubRunner([_stub_spec()]))
    with pytest.raises(show_actions.ActionError, match="Room effect"):
        show_actions.validate("room_effect", {"effect": "Pulse", "params": {"depth": 5}})
    with pytest.raises(show_actions.ActionError, match="no room effect"):
        show_actions.validate("room_effect", {"effect": "Nope"})


def test_end_show_stops_the_shows_room_effect(room, monkeypatch):
    stub = StubRunner([_stub_spec()])
    monkeypatch.setattr(show_actions, "room_effect_runner", stub)

    async def go():
        await show_actions.fire([A("room_effect", effect="Pulse", duration_s=60)], name="t")
        return await show_actions.end_show()
    report = asyncio.run(go())
    assert report["room_effect_stopped"] and stub.stopped == 1


def test_the_supervisor_suspends_the_layer_before_it_repushes(room):
    """A quiet take / night run brings the stack up with the show forbidden:
    a saved hold may be re-pushed, but the layer is suspended in the SAME
    pass, before anything else, so a held Steady never lights a capture."""
    fire([A("device_state", target={"kind": "fixture", "id": "tv"}, state="steady")])
    show_output._was_live = False
    room.gate["reason"] = "a night run is in progress"
    order = []
    real_suspend, real_repush = device_output.suspend, show_output.repush
    import unittest.mock as m
    with m.patch.object(device_output, "suspend", side_effect=lambda on: (order.append(("suspend", on)), real_suspend(on))), \
         m.patch.object(show_output, "repush", side_effect=lambda: (order.append(("repush",)), real_repush())[1]):
        show_output.tick()
    assert order[0] == ("suspend", True) and ("repush",) in order
    assert device_output.suspended()
