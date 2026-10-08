"""The Light Show's FLARES ON / OFF and PULSE actions, end to end
(spectra/services/show_mods.py; the Admiral, 2026-10-08: "Ability to turn
flares on and off for devices and device categories. This is specifically
important that we be able to turn flares off for the hues", and "turning off
flares should also turn off drop effect. so it shouldn't get dark on a drop,
or burst").

THE MUST-HAVE, on the real render pipeline (fx.headless, the real Pulse
effect, the real FacadeExecutor, the real ResponseEngine wired to the real
show switches exactly as engine.py wires them): a "flares off" step fired
through show_actions.fire at ONE Hue fixture takes the whole `hues` virtual
out of every flare kind AND the charge/lull/drop sequence — the Hue light
neither flashes, nor climbs, nor goes dark in the lull, nor bursts on the
drop — while the porch rail beside it, untouched, does all four. "Flares on"
puts the Hues back. A red control drops the gate (flare_blocked unwired) and
the Hues flash and burst like the porch.

Plus the action layer: target resolution (category / fixture / everything,
and the fixtures a shared virtual takes along), the holds' lifecycle (until,
scene change, End show, release, restart re-push), and the Pulse
modulation actions reaching fx/pulse_modulation.py.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless, pulse_modulation  # noqa: E402
from spectra.models.light_show import ShowAction  # noqa: E402
from spectra.services import (show_actions, show_mods, show_output,  # noqa: E402
                              show_store)

HUES, PORCH = "hues", "porch"


def _run(coro):
    return asyncio.run(coro)


def A(kind, **params):
    return ShowAction(kind=kind, params=params)


@pytest.fixture
def show(monkeypatch):
    """Gate open, nothing else: stores are isolated by conftest."""
    monkeypatch.setattr(show_output, "refusal", lambda: None)
    show_mods.reset()
    yield
    show_mods.reset()


def _write_config(config_dir: Path) -> None:
    """Two Hue fixtures behind ONE `hues` virtual (his real shape), and the
    porch rail on its own virtual."""
    config_dir.mkdir(parents=True, exist_ok=True)
    version = headless._current_config_version()
    dev = lambda did: {"id": did, "type": "dummy",
                       "config": {"name": did, "pixel_count": 1}}
    config = {
        "configuration_version": version,
        "devices": [dev("hue-living"), dev("hue-dining"), dev(PORCH)],
        "virtuals": [
            {"id": HUES, "is_device": None, "auto_generated": False,
             "config": {"name": HUES, "mapping": "span", "rows": 1},
             "segments": [["hue-living", 0, 0, False], ["hue-dining", 0, 0, False]]},
            {"id": PORCH, "is_device": PORCH, "auto_generated": False,
             "config": {"name": PORCH, "mapping": "span", "rows": 1},
             "segments": [[PORCH, 0, 0, False]]},
        ],
    }
    (config_dir / "config.json").write_text(json.dumps(config))


def _scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Pulse Flash", type="pulse_flash"),
             FlareKind(name="Brighten", type="momentary", gain=1.5)]
    return SceneV2(
        name="Singles",
        devices=[SceneDeviceConfig(target_kind="virtual", target=HUES,
                                   effect_type="pulse", brightness=0.5),
                 SceneDeviceConfig(target_kind="virtual", target=PORCH,
                                   effect_type="pulse", brightness=0.5)],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0,
            kinds={k.name: 1.0 for k in kinds})])})


def _engine(clock, *, wired=True):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine
    executor = FacadeExecutor(clock=lambda: clock.now,
                              room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 0.5, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(3))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(5),
        clock=lambda: clock.now, curve_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(),
        flare_blocked=show_mods.blocked_virtuals if wired else None)
    return executor, conductor, responder


class Room:
    """The two Pulse virtuals rendering on the real pipeline."""

    def __init__(self, host, clock, wired=True):
        self.host, self.clock = host, clock
        cfg = {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5,
               "brightness": 0.5}
        self.v = {vid: host.virtuals.get(vid) for vid in (HUES, PORCH)}
        self.e = {vid: headless.attach_effect(host, self.v[vid], "pulse", dict(cfg))
                  for vid in self.v}
        self.executor, self.conductor, self.responder = _engine(clock, wired=wired)
        scene = _scene()
        self.conductor.on_scene_fire(scene, [
            {"virtual_id": vid, "effect_type": "pulse", "config": dict(cfg),
             "entry_id": dev.id, "color_mode": "set"}
            for vid, dev in ((HUES, scene.devices[0]), (PORCH, scene.devices[1]))])
        self.trace: dict[str, list[float]] = {HUES: [], PORCH: []}

    def frames(self, n):
        for _ in range(n):
            for vid, v in self.v.items():
                headless.render_frames(v, 1, clock=self.clock, dt=1 / 60)
                self.trace[vid].append(self.e[vid].level)

    def mark(self):
        return {vid: len(t) for vid, t in self.trace.items()}

    def since(self, mark, vid):
        return self.trace[vid][mark[vid]:]


async def _with_room(tmp_path, monkeypatch, body, *, wired=True):
    from spectra.services import live_host
    from fx import device_model
    _write_config(tmp_path / "fx")
    headless.silence_audio()
    from fx.host import FxHost
    host = FxHost(str(tmp_path / "fx"))
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    monkeypatch.setattr(live_host.live, "host", host)
    monkeypatch.setattr(device_model, "get_virtuals_for_category",
                        lambda c: {"Singles": [HUES, PORCH]}.get(c, []))
    try:
        with headless.fake_clock() as clock:
            room = Room(host, clock, wired=wired)
            room.frames(120)
            await body(room)
    finally:
        facade.set_host(None)
        await host.shutdown()


async def _flare_and_sequence(room: Room):
    """A flare, then charge -> lull -> drop, the engine's own way. Returns
    the marks each phase began at."""
    marks = {"flare": room.mark()}
    await room.responder.on_event("flare", 0.9)
    room.frames(30)
    await room.responder.flush_releases()
    room.frames(150)
    marks["charge"] = room.mark()
    await room.responder.on_event("charge", 0.9, gap_ms=1500)
    room.frames(90)
    marks["lull"] = room.mark()
    await room.responder.on_event("lull", 0.9, gap_ms=1500)
    room.frames(100)
    marks["drop"] = room.mark()
    await room.responder.on_event("drop", 0.9)
    room.frames(20)
    marks["end"] = room.mark()
    return marks


def _assert_porch_did_everything(room, marks):
    rest = room.trace[PORCH][marks["flare"][PORCH] - 1]
    flare = room.since(marks["flare"], PORCH)[:30]
    assert max(flare) > rest + 0.2                       # it flashed
    charge = room.trace[PORCH][marks["charge"][PORCH]:marks["lull"][PORCH]]
    assert max(charge) > rest + 0.1                      # it climbed
    lull = room.trace[PORCH][marks["lull"][PORCH]:marks["drop"][PORCH]]
    assert min(lull) < 0.02                              # it went dark
    drop = room.trace[PORCH][marks["drop"][PORCH]:marks["end"][PORCH]]
    assert max(drop) > 0.95                              # it burst


# ── the must-have: flares off for the Hues ─────────────────────────────────

def test_flares_off_for_one_hue_fixture_keeps_the_hues_out_of_flares_and_drops(
        tmp_path, monkeypatch, show):
    async def body(room: Room):
        run = await show_actions.fire(
            [A("flares", target={"kind": "fixture", "id": "hue-living"},
               flares="off")], name="Hues quiet")
        step = run["steps"][0]
        assert step["status"] == "applied", step
        assert HUES in step["virtuals"]
        assert "hue-dining" in step["shared_with"]     # named, not silent
        assert HUES in show_mods.blocked_virtuals()
        assert PORCH not in show_mods.blocked_virtuals()

        rest = room.trace[HUES][-1]
        marks = await _flare_and_sequence(room)
        hues = room.since(marks["flare"], HUES)
        # no flash, no gain spike, no climb, no lull darkness, no burst:
        # the Hue light just keeps its normal resting look throughout
        assert max(hues) == pytest.approx(rest, abs=1e-6)
        assert min(hues) == pytest.approx(rest, abs=1e-6)
        assert room.e[HUES]._phase == "none" and room.e[HUES]._burst == 0.0
        assert room.e[HUES]._config["brightness"] == pytest.approx(0.5)
        _assert_porch_did_everything(room, marks)

        # Flares ON puts the Hues back in
        run = await show_actions.fire(
            [A("flares", target={"kind": "category", "id": "Singles"},
               flares="on")], name="Hues back")
        assert run["steps"][0]["status"] == "applied"
        assert show_mods.blocked_virtuals() == frozenset()
        m = room.mark()
        await room.responder.on_event("flare", 0.9)
        room.frames(30)
        assert max(room.since(m, HUES)) > rest + 0.2
    _run(_with_room(tmp_path, monkeypatch, body))


def test_red_control_unwired_gate_lets_flares_and_drops_reach_the_hues(
        tmp_path, monkeypatch, show):
    """The same room with the engine NOT wired to the show's switches: the
    switch is recorded but the Hues flash, go dark and burst like the porch
    — the harness fails on the defect it was written for."""
    async def body(room: Room):
        await show_actions.fire(
            [A("flares", target={"kind": "fixture", "id": "hue-living"},
               flares="off")], name="Hues quiet")
        marks = await _flare_and_sequence(room)
        rest = room.trace[HUES][marks["flare"][HUES] - 1]
        hues = room.since(marks["flare"], HUES)
        assert max(hues) > rest + 0.2
        assert min(hues) < 0.02
    _run(_with_room(tmp_path, monkeypatch, body, wired=False))


def test_flares_off_mid_lull_lets_the_hues_go_back_to_their_look(
        tmp_path, monkeypatch, show):
    async def body(room: Room):
        rest = room.trace[HUES][-1]
        await room.responder.on_event("lull", 0.9, gap_ms=2000)
        room.frames(40)
        assert room.e[HUES]._phase == "lull"
        monkeypatch.setattr(show_actions, "phase_releaser",
                            room.responder.release_phase_on)
        run = await show_actions.fire(
            [A("flares", target={"kind": "category", "id": "Singles"},
               flares="off")], name="quiet")
        assert set(run["steps"][0]["phase_released"]) == {HUES, PORCH}
        room.frames(120)                                  # past EXIT_BLEND_S
        assert room.e[HUES]._phase == "none"
        assert room.trace[HUES][-1] == pytest.approx(rest, abs=0.02)
    _run(_with_room(tmp_path, monkeypatch, body))


def test_pulse_actions_reach_the_rendering_effect(tmp_path, monkeypatch, show):
    async def body(room: Room):
        run = await show_actions.fire(
            [A("pulse_brightness", target={"kind": "fixture", "id": "hue-dining"},
               floor=0.0, ceiling=0.3, fade_in_ms=0),
             A("pulse_reactivity", target={"kind": "category", "id": "Singles"},
               reactivity=0.0, fade_in_ms=0)], name="calm")
        assert [s["status"] for s in run["steps"]] == ["applied", "applied"]
        assert "Pulse on" in run["steps"][1]["detail"]
        room.frames(5)
        assert max(room.trace[HUES][-3:]) <= 0.3 + 1e-9
        m = room.mark()
        await room.responder.on_event("drop", 0.9)
        room.frames(20)
        assert max(room.since(m, HUES)) <= 0.3 + 1e-9     # ceiling holds a drop
        assert max(room.since(m, PORCH)) > 0.95           # no ceiling there
        # End show lets both go and fades them back out of the fx module
        report = await show_actions.end_show(fade_ms=0)
        assert report["ended_pulse_mods"] == 2
        assert pulse_modulation.get(HUES).is_identity()
        show_mods.tick()
        assert pulse_modulation.get(HUES) is None
    _run(_with_room(tmp_path, monkeypatch, body))


# ── the action layer (a fake live host, no rendering) ──────────────────────

class Registry(dict):
    def __iter__(self):
        return iter(list(self.keys()))


@pytest.fixture
def fake_host(monkeypatch, show):
    from fx import device_model
    from spectra.services import live_host
    dev = lambda did: SimpleNamespace(id=did, name=did.replace("-", " ").title(),
                                      type="dummy", frozen=False)
    host = SimpleNamespace(
        devices=Registry({d: dev(d) for d in ("hue-living", "hue-dining", PORCH, "crystal")}),
        virtuals=Registry({
            HUES: SimpleNamespace(active=True, _segments=[["hue-living", 0, 0, False],
                                                          ["hue-dining", 0, 0, False]]),
            PORCH: SimpleNamespace(active=True, _segments=[[PORCH, 0, 0, False]]),
            "crystal-mapper": SimpleNamespace(active=True, _segments=[["crystal", 0, 9, False]]),
        }))
    monkeypatch.setattr(live_host.live, "host", host)
    monkeypatch.setattr(device_model, "get_virtuals_for_category",
                        lambda c: {"Singles": [HUES, PORCH],
                                   "Matrix": ["crystal-mapper"]}.get(c, []))
    monkeypatch.setattr(device_model, "list_categories",
                        lambda: [{"name": "Singles"}, {"name": "Matrix"}])
    return host


def test_targets_resolve_to_virtuals_and_name_who_comes_along(fake_host):
    assert show_mods.resolve_virtuals({"kind": "category", "id": "Singles"})[0] == [HUES, PORCH]
    vids, label, shared, problems = show_mods.resolve_virtuals(
        {"kind": "fixture", "id": "hue-living"})
    assert vids == [HUES] and shared == ["Hue Dining"] and not problems
    assert set(show_mods.resolve_virtuals({"kind": "everything", "id": None})[0]) == {
        HUES, PORCH, "crystal-mapper"}
    assert show_mods.resolve_virtuals({"kind": "category", "id": "Nope"})[3]
    assert show_mods.resolve_virtuals({"kind": "fixture", "id": "ghost"})[3]


def test_validation_refuses_a_pointless_or_crossed_floor_and_ceiling(fake_host):
    with pytest.raises(show_actions.ActionError):
        show_actions.validate("pulse_brightness", {
            "target": {"kind": "everything"}, "floor": 0.0, "ceiling": 1.0})
    with pytest.raises(show_actions.ActionError):
        show_actions.validate("pulse_brightness", {
            "target": {"kind": "everything"}, "floor": 0.6, "ceiling": 0.4})
    with pytest.raises(show_actions.ActionError):
        show_actions.validate("pulse_reactivity", {
            "target": {"kind": "everything"}, "reactivity": 1.5})
    with pytest.raises(show_actions.ActionError):
        show_actions.validate("flares", {"target": {"kind": "everything"},
                                         "flares": "off", "until": "time",
                                         "duration_s": 0})


def test_holds_end_by_scene_change_time_release_and_survive_a_restart(fake_host):
    run = _run(show_actions.fire([
        A("flares", target={"kind": "category", "id": "Singles"}, flares="off",
          until="scene_change"),
        A("pulse_reactivity", target={"kind": "category", "id": "Singles"},
          reactivity=0.25, fade_in_ms=0, until="time", duration_s=5)],
        name="t"))
    assert [s["status"] for s in run["steps"]] == ["applied", "applied"]
    st = show_store.state()
    assert len(st.flare_blocks) == 1 and len(st.pulse_mods) == 1
    assert show_actions.brief()["flare_blocks"] == 1
    assert pulse_modulation.get(HUES).reactivity == pytest.approx(0.25)

    # a restart: the in-memory fx side is gone, the store re-pushes it
    pulse_modulation.clear()
    show_output.repush()
    assert pulse_modulation.get(PORCH).reactivity == pytest.approx(0.25)

    show_output.on_scene_change()
    assert show_mods.blocked_virtuals() == frozenset()
    st.pulse_mods[0].ends_at_ms = 1                     # its time has come
    show_mods.tick()
    assert show_store.state().pulse_mods == []

    _run(show_actions.fire([A("flares", target={"kind": "everything"},
                              flares="off")], name="t2"))
    assert show_mods.blocked_virtuals()
    show_output.on_release()                            # the room is released
    assert show_mods.blocked_virtuals() == frozenset()
    assert pulse_modulation.get(HUES) is None


def test_flares_on_with_nothing_off_says_so(fake_host):
    run = _run(show_actions.fire([A("flares", target={"kind": "everything"},
                                    flares="on")], name="t"))
    assert run["steps"][0]["status"] == "skipped"


def test_preview_names_the_target_and_who_comes_along(fake_host):
    rows = show_actions.preview([A("flares", target={"kind": "fixture", "id": "hue-living"},
                                   flares="off")])
    assert "Hue Dining" in rows[0]["change"]


def test_engine_is_wired_to_the_show_switches():
    from spectra.services import engine
    assert engine.responses._flare_blocked is engine._show_flare_blocked


# ── Sonic (show_console) reaches all three, through the same fire() ────────

def test_sonic_switches_hue_flares_off_by_fixture_name_and_back_on(fake_host):
    from spectra.services import show_console
    r = _run(show_console._op_set_flares("off", target_kind="fixture",
                                         target_name="hue living"))
    assert r["status"] == "applied", r
    assert "Hue Dining" in r["summary"]                 # who came along, said
    assert HUES in show_mods.blocked_virtuals()
    held = show_console._op_show_status()["output"]["flare_blocks"]
    assert len(held) == 1
    r = _run(show_console._op_set_flares("on", target_kind="category",
                                         target_name="Singles"))
    assert r["status"] == "applied" and not show_mods.blocked_virtuals()
    # a near-miss name is refused with close matches, never guessed
    r = _run(show_console._op_set_flares("off", target_kind="fixture",
                                         target_name="Hue Kitchen"))
    assert r["status"] == "rejected" and r["close_matches"]
    assert not show_mods.blocked_virtuals()


def test_sonic_sets_pulse_reactivity_and_brightness_and_ends_a_hold(fake_host):
    from spectra.services import show_console
    r = _run(show_console._op_set_pulse_reactivity(0.3, target_kind="category",
                                                   target_name="Singles",
                                                   fade_in_ms=0))
    assert r["status"] == "applied", r
    assert pulse_modulation.get(HUES).reactivity == pytest.approx(0.3)
    r = _run(show_console._op_set_pulse_brightness(floor=0.2, ceiling=0.7,
                                                   target_kind="category",
                                                   target_name="Singles",
                                                   fade_in_ms=0))
    assert r["status"] == "applied"
    m = pulse_modulation.get(PORCH)
    assert (m.floor, m.ceiling) == pytest.approx((0.2, 0.7))
    # refused, nothing written
    before = len(show_store.state().pulse_mods)
    for bad in (show_console._op_set_pulse_reactivity(2.0),
                show_console._op_set_pulse_brightness(floor=0.9, ceiling=0.1),
                show_console._op_set_pulse_brightness()):
        assert _run(bad)["status"] == "rejected"
    assert len(show_store.state().pulse_mods) == before
    hold_id = show_mods.status()["pulse_mods"][0]["id"]
    assert show_console._op_end_effect_hold(hold_id)["status"] == "applied"
    assert show_console._op_end_effect_hold("nope")["status"] == "rejected"


def test_the_new_sonic_operations_are_declared_and_discoverable():
    from spectra.services import settings_agent
    for name in ("set_pulse_reactivity", "set_pulse_brightness", "set_flares",
                 "end_effect_hold"):
        op = settings_agent.ALL_OPERATIONS[name]
        assert op.domain == "show" and op.kind == "write"
