"""The param orphan watchdog (spectra/services/param_watchdog.py) — owner
ask 2026-08-21, "some kind of watchdog system to make sure that parameters
are set correctly like that", after an effect was left stuck running
backwards with no way back.

Two halves, both on the REAL vendored pipeline (fx.headless + fx.facade,
the same `_engine()` rig tests/test_spectra_engine.py uses — a real
DriftConductor + ResponseEngine on a FacadeExecutor, values read back off
the live effect's own config, never a RecordingExecutor's write log):

  1. a deliberately ORPHANED momentary spike (its release dropped, the
     exact shape of the stuck-reverse defect) IS restored, loudly, after
     the grace;
  2. a legitimate PERMANENT move, an IN-FLIGHT momentary hold (however
     long the loop takes to release it), and a release GLIDE in flight are
     all LEFT ALONE — the three holders and the permanent/momentary
     discriminator the module docstring states.

Then fake-deps proofs of the pure rules (drift-mechanism ownership, the
gate, the brightness-multiplier history, the give-up after
RESTORE_ATTEMPT_LIMIT, the out-of-scope keys) and the observability
surfaces (engine status, the liveness endpoint's additive key, the
fire_history "watchdog" bucket).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, facade, headless
from spectra.services import param_watchdog as pw

VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _engine(clock, *, brightness_multiplier=1.0):
    """Conductor + response engine on the FacadeExecutor with an in-memory
    room — the production wiring with the executor swapped (the S3 delta),
    copied from tests/test_spectra_engine.py's own rig."""
    from spectra.models.sequencer import SequencerConfig
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    room_box = [cj.RoomColorState()]
    seq_config = SequencerConfig(color_set_entries={})
    controls = rc.RoomControlState(brightness_multiplier=brightness_multiplier)
    executor = FacadeExecutor(clock=lambda: clock.now,
                              room_controls_load=lambda: controls)
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0,
        drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: None, set_cards=lambda: [],
        sequencer_config=lambda: seq_config,
        gradient_profiles=lambda: {},
        room_controls=lambda: controls, rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now, sequencer_config=lambda: seq_config,
        curve_profiles=lambda: {}, eligible_sets=lambda sc: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st))
    return executor, conductor, responder, controls


def _fire(conductor, scene, config):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id,
        "color_mode": dev.color.mode}])


def _live_reader(host):
    def read(vid):
        virtual = host.virtuals.get(vid)
        effect = getattr(virtual, "active_effect", None) if virtual else None
        if effect is None:
            return None
        return pw.snapshot_effect(effect)
    return read


def _deps(clock, host, conductor, responder, executor, controls, gate=None):
    return pw.Deps(conductor=conductor, responses=responder,
                   executor=lambda: executor, live_effect=_live_reader(host),
                   room_controls=lambda: controls,
                   gate=gate or (lambda: None), clock=lambda: clock.now)


def _squiggles_scene(kinds, band_kinds, params=None):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    return SceneV2(
        name="Watchdog",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="squiggles",
            params=dict(params or {"reverse": False}))],
        flare_kinds=[FlareKind(**k) for k in kinds],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds=dict(band_kinds))])})


# ── 1. an orphaned momentary spike IS restored, loudly ────────────────────

def test_orphaned_momentary_spike_is_restored_after_grace(tmp_path, caplog):
    """The stuck-reverse shape, deliberately reproduced: a real momentary
    `reverse` flare spikes the real vendored squiggles effect to True, then
    its pending release is DROPPED (the exact state a lost/skipped release
    leaves behind — live says True, baseline says False, nothing holding
    it). The watchdog must: suspect it on first sight WITHOUT acting,
    still not act inside ORPHAN_GRACE_S, then restore it — and the
    restore must be visible on the effect's own config, logged at WARNING
    naming virtual/param/found/restored-to/age, counted in status(), and
    recorded to fire_history's "watchdog" bucket."""
    from spectra.services import fire_history
    _categories_fixture(tmp_path)
    scene = _squiggles_scene(
        [dict(name="Reverse Momentarily (500ms)", type="momentary", hold_ms=500,
              params={"reverse": {"mode": "absolute", "value": 1}})],
        {"Reverse Momentarily (500ms)": 1.0})

    async def main():
        host, virtual = await _host(tmp_path, "orphan")
        try:
            with headless.fake_clock() as clock:
                config = {"reverse": False}
                effect = headless.attach_effect(host, virtual, "squiggles", config)
                executor, conductor, responder, controls = _engine(clock)
                _fire(conductor, scene, config)
                deps = _deps(clock, host, conductor, responder, executor, controls)

                await responder.on_event("flare", 0.5)
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                assert effect._config["reverse"] is True
                assert responder.pending_release_keys() == {(VID, "reverse")}

                # ORPHAN IT: the release that should have come never does.
                responder._pending_releases.clear()
                assert responder.release_target(VID, "reverse") is False

                first = await pw.sweep_once(deps)
                assert first["suspected"] == 1 and first["restored"] == 0
                assert effect._config["reverse"] is True
                assert len(pw.status()["suspected"]) == 1

                clock.advance(pw.ORPHAN_GRACE_S - 1.0)
                second = await pw.sweep_once(deps)
                assert second["suspected"] == 1 and second["restored"] == 0
                assert effect._config["reverse"] is True, \
                    "acted inside the grace window"

                clock.advance(2.0)
                with caplog.at_level(logging.WARNING, logger="spectra.services.param_watchdog"):
                    third = await pw.sweep_once(deps)
                assert third["restored"] == 1
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                assert effect._config["reverse"] is False, \
                    "the restore never reached the live effect"

                st = pw.status()
                assert st["restores_total"] == 1
                entry = st["recent_restores"][-1]
                assert entry["virtual_id"] == VID and entry["param"] == "reverse"
                assert entry["found"] is True and entry["restored_to"] is False
                assert entry["method"] == "jump"
                assert entry["orphaned_for_s"] >= pw.ORPHAN_GRACE_S
                assert st["suspected"] == []
                summary = pw.liveness_summary()
                assert summary["restores_total"] == 1
                assert summary["last_restore"]["param"] == "reverse"

                loud = [r for r in caplog.records
                        if "PARAM ORPHAN RESTORED" in r.getMessage()]
                assert len(loud) == 1 and loud[0].levelno == logging.WARNING
                msg = loud[0].getMessage()
                for needle in (VID, "reverse", "squiggles", "True", "False",
                               "jump", "nothing holding it"):
                    assert needle in msg, needle

                log = fire_history.load_show_log()
                wd = [e for e in log if e.get("bucket") == "watchdog"]
                assert len(wd) == 1
                assert wd[0]["key"] == f"{VID}.reverse"
                assert wd[0]["detail"]["restored_to"] is False
                assert fire_history.load_all()["watchdog"][f"{VID}.reverse"]["count"] == 1

                # Restored and confirmed: the next sweep sees it matched,
                # attempt bookkeeping clears, nothing is given up on.
                clock.advance(pw.SWEEP_INTERVAL_S)
                fourth = await pw.sweep_once(deps)
                assert fourth["ok"] >= 1 and fourth["restored"] == 0
                assert pw.status()["given_up"] == []
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 2. legitimate moves are left alone ───────────────────────────────────

def test_permanent_move_and_permanent_gain_are_the_baseline_and_left_alone(tmp_path):
    """A PERMANENT `reverse: True` move looks identical on the lights to the
    stuck defect — the effect IS running backwards — but it is authored and
    carried: on_surge moved param_baseline to True, so live == baseline and
    the watchdog has nothing to restore. Same for a permanent gain: the
    landed brightness is carried into brightness_baseline. Sweeps across a
    full minute must never suspect or touch either."""
    _categories_fixture(tmp_path)
    scene = _squiggles_scene(
        [dict(name="Reverse Permanently", type="permanent",
              params={"reverse": {"mode": "absolute", "value": 1}}),
         dict(name="Dim", type="permanent", gain=0.5)],
        {"Reverse Permanently": 1.0, "Dim": 1.0},
        params={"reverse": False, "brightness": 0.8})

    async def main():
        host, virtual = await _host(tmp_path, "permanent")
        try:
            with headless.fake_clock() as clock:
                config = {"reverse": False, "brightness": 0.8}
                effect = headless.attach_effect(host, virtual, "squiggles", config)
                executor, conductor, responder, controls = _engine(clock)
                _fire(conductor, scene, config)
                deps = _deps(clock, host, conductor, responder, executor, controls)

                await responder.on_event("flare", 0.5)
                # the gain glides over GAIN_GLIDE_S (0.8s) — land it
                headless.render_frames(virtual, 70, clock=clock, dt=1 / 60)
                assert effect._config["reverse"] is True
                assert effect._config["brightness"] == pytest.approx(0.4)
                state = conductor.virtuals[VID]
                assert state.param_baseline["reverse"] is True
                assert state.brightness_baseline == pytest.approx(0.4)
                assert responder.pending_release_keys() == set()

                for _ in range(8):
                    rec = await pw.sweep_once(deps)
                    assert rec["restored"] == 0 and rec["suspected"] == 0, rec
                    clock.advance(pw.SWEEP_INTERVAL_S)
                assert effect._config["reverse"] is True
                assert effect._config["brightness"] == pytest.approx(0.4)
                assert pw.status()["restores_total"] == 0
                assert pw.status()["suspected"] == []
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_in_flight_momentary_hold_is_left_alone_however_long_it_takes(tmp_path):
    """Holder #1: a momentary spike whose release is still PENDING is
    legitimately away from baseline for as long as that entry exists — a
    stalled event loop delaying the flush by two minutes must not read as
    an orphan. Then the real release lands and the watchdog sees it
    matched; at no point does it write."""
    _categories_fixture(tmp_path)
    scene = _squiggles_scene(
        [dict(name="Reverse Momentarily (500ms)", type="momentary", hold_ms=500,
              params={"reverse": {"mode": "absolute", "value": 1}})],
        {"Reverse Momentarily (500ms)": 1.0})

    async def main():
        host, virtual = await _host(tmp_path, "held")
        try:
            with headless.fake_clock() as clock:
                config = {"reverse": False}
                effect = headless.attach_effect(host, virtual, "squiggles", config)
                executor, conductor, responder, controls = _engine(clock)
                _fire(conductor, scene, config)
                deps = _deps(clock, host, conductor, responder, executor, controls)
                writes_before = len(executor.writes)

                await responder.on_event("flare", 0.5)
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                assert effect._config["reverse"] is True
                spike_writes = len(executor.writes)

                for _ in range(13):          # 120s of sweeps, release never flushed
                    clock.advance(pw.SWEEP_INTERVAL_S)
                    rec = await pw.sweep_once(deps)
                    assert rec["held"] >= 1 and rec["suspected"] == 0 \
                        and rec["restored"] == 0, rec
                assert effect._config["reverse"] is True
                assert len(executor.writes) == spike_writes, \
                    "the watchdog wrote while a release was pending"

                released = await responder.flush_releases(0.5)
                assert released == 1
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                assert effect._config["reverse"] is False
                rec = await pw.sweep_once(deps)
                assert rec["ok"] >= 1 and rec["restored"] == 0
                assert pw.status()["restores_total"] == 0
                assert writes_before < len(executor.writes)  # sanity: the engine did write
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_release_glide_in_flight_is_a_holder_then_lands(tmp_path):
    """Holder #3: a momentary NUMERIC kind on a registry-smooth param
    (squiggles `blob_size`) releases as a PULSE_RELEASE_S glide. With the
    pending entry flushed but the glide mid-flight (tween key present on
    the live effect), the param is away from baseline and NOT pending —
    only the tween says it's being driven. The watchdog must treat that
    as held no matter how long the wall clock claims has passed (the
    tween advances per rendered frame, not per second), and see it
    matched once the glide lands."""
    _categories_fixture(tmp_path)
    scene = _squiggles_scene(
        [dict(name="Fat Momentarily", type="momentary",
              params={"blob_size": {"mode": "absolute", "value": 3.0}})],
        {"Fat Momentarily": 1.0},
        params={"reverse": False, "blob_size": 1.0})

    async def main():
        host, virtual = await _host(tmp_path, "glide")
        try:
            with headless.fake_clock() as clock:
                config = {"reverse": False, "blob_size": 1.0}
                effect = headless.attach_effect(host, virtual, "squiggles", config)
                executor, conductor, responder, controls = _engine(clock)
                _fire(conductor, scene, config)
                deps = _deps(clock, host, conductor, responder, executor, controls)

                await responder.on_event("flare", 0.5)
                headless.render_frames(virtual, 20, clock=clock, dt=1 / 60)  # spike glide lands (220ms)
                assert effect._config["blob_size"] == pytest.approx(3.0)
                assert await responder.flush_releases(None) == 1
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)  # release glide started
                assert 1.0 < effect._config["blob_size"] < 3.0
                assert "blob_size" in (effect._tweens or {})

                clock.advance(pw.ORPHAN_GRACE_S * 3)   # wall clock races ahead, frames don't
                rec = await pw.sweep_once(deps)
                assert rec["held"] >= 1 and rec["restored"] == 0 \
                    and rec["suspected"] == 0, rec

                headless.render_frames(virtual, 120, clock=clock, dt=1 / 60)  # 2s: glide lands
                assert effect._config["blob_size"] == pytest.approx(1.0)
                assert effect._tweens is None
                rec = await pw.sweep_once(deps)
                assert rec["ok"] >= 1 and rec["restored"] == 0
                assert pw.status()["restores_total"] == 0
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 3. the pure rules, on fakes ──────────────────────────────────────────

class _FakeState:
    def __init__(self, effect_type, baseline, brightness=1.0):
        self.effect_type = effect_type
        self.param_baseline = dict(baseline)
        self.brightness_baseline = brightness


class _FakeConductor:
    def __init__(self, states, mechanisms=()):
        self.virtuals = dict(states)
        self.mechanisms = list(mechanisms)


class _FakeResponses:
    """release_target mirrors ResponseEngine's: creep position first,
    brightness's own baseline, else the tracked param baseline."""
    def __init__(self, conductor, pending=()):
        self.conductor = conductor
        self._pending = set(pending)

    def pending_release_keys(self):
        return set(self._pending)

    def release_target(self, vid, pname):
        state = self.conductor.virtuals[vid]
        if pname == "brightness":
            return state.brightness_baseline
        for m in self.conductor.mechanisms:
            if m.vid == vid and m.param == pname and m.kind == "creep":
                return m.position
        return state.param_baseline.get(pname)


class _FakeExecutor:
    def __init__(self, live=None):
        self.calls = []
        self.live = live   # when given, a write lands on this dict

    async def glide(self, vid, effect_type, params, duration_ms):
        self.calls.append(("glide", vid, dict(params), duration_ms))
        if self.live is not None:
            self.live[vid].update(params)

    async def jump(self, vid, effect_type, params):
        self.calls.append(("jump", vid, dict(params)))
        if self.live is not None:
            self.live[vid].update(params)


class _Controls:
    def __init__(self, brightness_multiplier=1.0, display_mode="default"):
        self.brightness_multiplier = brightness_multiplier
        self.display_mode = display_mode


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _fake_rig(states, live, *, mechanisms=(), pending=(), multiplier=1.0,
              gate=None, land_writes=True, effect_types=None):
    conductor = _FakeConductor(states, mechanisms)
    responses = _FakeResponses(conductor, pending)
    executor = _FakeExecutor(live if land_writes else None)
    controls = _Controls(multiplier)
    clock = _Clock()
    types = effect_types or {}

    def live_effect(vid):
        if vid not in live:
            return None
        return pw.LiveEffect(
            effect_type=types.get(vid, states[vid].effect_type),
            config=dict(live[vid]), tweening=frozenset())

    deps = pw.Deps(conductor=conductor, responses=responses,
                   executor=lambda: executor, live_effect=live_effect,
                   room_controls=lambda: controls, gate=gate or (lambda: None),
                   clock=clock)
    return deps, executor, clock, controls, conductor, responses


def _sweep_past_grace(deps, clock, sweeps=5):
    records = []
    for _ in range(sweeps):
        records.append(_run(pw.sweep_once(deps)))
        clock.now += pw.SWEEP_INTERVAL_S
    return records


def test_drift_mechanism_owned_param_is_left_alone():
    """Holder #2: a creep on `blob_size` means its live value is legitimately
    gliding toward the next leg's target — away from the mechanism's own
    position and from the scene baseline alike. Never suspected."""
    from spectra.models.scene import DriftSpec
    from spectra.services.drift_conductor import Mechanism
    mech = Mechanism("v1", "blob_size",
                     DriftSpec(kind="creep", lo=0.5, hi=6.0, rate_per_min=3.0),
                     baseline=1.0, effect_type="squiggles")
    states = {"v1": _FakeState("squiggles", {"blob_size": 1.0, "reverse": False})}
    live = {"v1": {"blob_size": 4.2, "reverse": False}}
    deps, executor, clock, *_ = _fake_rig(states, live, mechanisms=[mech])
    for rec in _sweep_past_grace(deps, clock, sweeps=6):
        assert rec["held"] == 1 and rec["suspected"] == 0 and rec["restored"] == 0
    assert executor.calls == []
    assert live["v1"]["blob_size"] == 4.2


def test_gate_stands_down_and_forgets_suspicions():
    """While a preview holds the room (or the engine is dark) the sweep is
    skipped entirely, and whatever it was suspecting is void: when the
    gate lifts, the clock starts over — a preview's own writes are never
    mistaken for an orphan that aged during the hold."""
    states = {"v1": _FakeState("squiggles", {"reverse": False})}
    live = {"v1": {"reverse": True}}
    gate_reason = [None]
    deps, executor, clock, *_ = _fake_rig(states, live,
                                          gate=lambda: gate_reason[0])
    first = _run(pw.sweep_once(deps))
    assert first["suspected"] == 1
    gate_reason[0] = "preview active"
    clock.now += pw.ORPHAN_GRACE_S * 2
    skipped = _run(pw.sweep_once(deps))
    assert skipped["skipped"] == "preview active" and skipped["restored"] == 0
    assert pw.status()["suspected"] == []
    assert pw.liveness_summary()["last_sweep_skipped"] == "preview active"
    gate_reason[0] = None
    again = _run(pw.sweep_once(deps))
    assert again["suspected"] == 1 and again["restored"] == 0, \
        "a suspicion aged through a gated window must not fire on the first sweep back"
    assert executor.calls == []


def test_brightness_multiplier_change_is_not_an_orphan():
    """brightness is scaled at the write seam: baseline 0.8 under a 0.5
    multiplier legitimately reads 0.4. A later multiplier change does NOT
    rewrite live brightness until the next brightness write (pre-existing)
    — the watchdog must recognise a value explained by any multiplier it
    has seen since the last scene fire, never act on the dimmer's behalf."""
    states = {"v1": _FakeState("squiggles", {"brightness": 0.8}, brightness=0.8)}
    live = {"v1": {"brightness": 0.4}}
    deps, executor, clock, controls, *_ = _fake_rig(states, live, multiplier=0.5)
    for rec in _sweep_past_grace(deps, clock, sweeps=2):
        assert rec["ok"] == 1 and rec["suspected"] == 0
    controls.brightness_multiplier = 1.0          # dimmer moved, no write yet
    for rec in _sweep_past_grace(deps, clock, sweeps=6):
        assert rec["ok"] == 1 and rec["suspected"] == 0 and rec["restored"] == 0, rec
    assert executor.calls == []
    # ...but a brightness genuinely away from EVERY multiplier seen IS one.
    live["v1"]["brightness"] = 0.97
    records = _sweep_past_grace(deps, clock, sweeps=6)
    assert any(r["restored"] == 1 for r in records)
    assert executor.calls and executor.calls[0][0] == "glide"
    assert executor.calls[0][2] == {"brightness": 0.8}   # the UNSCALED baseline; the seam scales
    assert executor.calls[0][3] == pw.RESTORE_GLIDE_MS


def test_restore_that_does_not_take_gives_up_loudly(caplog):
    """A restore the next sweep still sees un-landed (something keeps
    re-moving the param, or the schema rejects the write) is retried on
    the same grace at most RESTORE_ATTEMPT_LIMIT times, then given up on
    at CRITICAL — named in status() — never an every-sweep fight."""
    states = {"v1": _FakeState("squiggles", {"reverse": False})}
    live = {"v1": {"reverse": True}}
    deps, executor, clock, *_ = _fake_rig(states, live, land_writes=False)
    with caplog.at_level(logging.WARNING, logger="spectra.services.param_watchdog"):
        records = _sweep_past_grace(deps, clock, sweeps=40)
    restores = sum(r["restored"] for r in records)
    assert restores == pw.RESTORE_ATTEMPT_LIMIT
    assert len(executor.calls) == pw.RESTORE_ATTEMPT_LIMIT
    given = pw.status()["given_up"]
    assert len(given) == 1 and given[0]["param"] == "reverse"
    assert records[-1]["given_up"] == 1 and records[-1]["restored"] == 0
    crit = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(crit) == 1 and "PARAM ORPHAN NOT TAKING" in crit[0].getMessage()
    assert pw.liveness_summary()["given_up"] == 1
    # a scene fire (new VirtualState dict) clears the give-up
    deps.conductor.virtuals = dict(deps.conductor.virtuals)
    rec = _run(pw.sweep_once(deps))
    assert rec["given_up"] == 0 and rec["suspected"] == 1
    assert pw.status()["given_up"] == []


def test_out_of_scope_keys_and_type_mismatch_are_never_touched():
    """background_brightness has three legitimate writers outside engine
    bookkeeping (colour-set landings, dark_lock, Light mode) — excluded by
    name. A live effect whose TYPE differs from the conductor's picture
    (something outside the engine switched it) is counted, never acted
    on. A baseline the live effect doesn't carry is skipped."""
    states = {
        "bg": _FakeState("squiggles", {"background_brightness": 0.3, "reverse": False}),
        "other": _FakeState("squiggles", {"reverse": False}),
        "missing": _FakeState("squiggles", {"reverse": False, "ghost": 1.0}),
    }
    live = {"bg": {"background_brightness": 0.0, "reverse": False},
            "other": {"reverse": True},
            "missing": {"reverse": False}}
    deps, executor, clock, *_ = _fake_rig(states, live,
                                          effect_types={"other": "blackhole"})
    records = _sweep_past_grace(deps, clock, sweeps=6)
    assert executor.calls == []
    assert all(r["restored"] == 0 and r["suspected"] == 0 for r in records)
    assert records[0]["type_mismatch"] == 1
    assert records[0]["checked"] == 2   # bg.reverse + missing.reverse (ghost has no live value)
    assert pw.status()["suspected"] == []


def test_bool_against_number_is_not_judged():
    """A registry/effect disagreement (a bool baseline against a numeric
    live value, or vice versa) is nobody's business to 'fix' — never
    suspected."""
    states = {"v1": _FakeState("squiggles", {"reverse": False, "blob_size": 1.0})}
    live = {"v1": {"reverse": 0.0, "blob_size": True}}
    deps, executor, clock, *_ = _fake_rig(states, live)
    for rec in _sweep_past_grace(deps, clock, sweeps=5):
        assert rec["suspected"] == 0 and rec["restored"] == 0
    assert executor.calls == []


def test_baseline_moving_mid_suspicion_restarts_the_clock():
    """A permanent move landing while a param is under suspicion changes
    the expected value: the clock restarts against the NEW baseline (the
    live value is about to follow via the engine's own write). The
    watchdog never restores to a baseline it only just stopped comparing
    against."""
    states = {"v1": _FakeState("squiggles", {"blob_size": 1.0})}
    live = {"v1": {"blob_size": 2.5}}
    deps, executor, clock, _c, conductor, _r = _fake_rig(states, live)
    _run(pw.sweep_once(deps))
    clock.now += pw.ORPHAN_GRACE_S - 1
    _run(pw.sweep_once(deps))
    conductor.virtuals["v1"].param_baseline["blob_size"] = 4.0   # a permanent move carried
    clock.now += 5
    rec = _run(pw.sweep_once(deps))
    assert rec["suspected"] == 1 and rec["restored"] == 0
    assert executor.calls == []
    live["v1"]["blob_size"] = 4.0                                # its glide landed
    clock.now += 5
    rec = _run(pw.sweep_once(deps))
    assert rec["ok"] == 1 and rec["restored"] == 0


# ── 4. observability surfaces ────────────────────────────────────────────

def test_engine_status_and_liveness_endpoint_carry_the_watchdog(tmp_path, monkeypatch):
    """The count is on GET /api/liveness (additive key, informational —
    `healthy` is untouched) and the full record on engine.status()."""
    from fastapi.testclient import TestClient
    from fx import light_ownership as lo
    from spectra.app import create_app
    from spectra.services import engine
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")

    states = {"v1": _FakeState("squiggles", {"reverse": False})}
    live = {"v1": {"reverse": True}}
    deps, *_ = _fake_rig(states, live)
    _run(pw.sweep_once(deps))

    st = engine.status()["param_watchdog"]
    assert st["orphan_grace_s"] == pw.ORPHAN_GRACE_S
    assert st["sweep_interval_s"] == pw.SWEEP_INTERVAL_S
    assert st["restores_total"] == 0
    assert [s["param"] for s in st["suspected"]] == ["reverse"]

    client = TestClient(create_app())
    body = client.get("/api/liveness").json()
    assert body["contract"] == "spectra-liveness-v1"
    wd = body["param_watchdog"]
    assert wd["restores_total"] == 0 and wd["suspected"] == 1 \
        and wd["given_up"] == 0 and wd["last_restore"] is None
    # the key is additive: a spot-effects-owned, dark SPECTRA is healthy as before
    assert body["healthy"] is True and body["state"] == "dark"


def test_threshold_constants_are_the_stated_ones():
    """The module docstring states and justifies these; a silent edit must
    fail here so the justification gets rewritten alongside it."""
    assert pw.ORPHAN_GRACE_S == 30.0
    assert pw.SWEEP_INTERVAL_S == 10.0
    assert pw.RESTORE_ATTEMPT_LIMIT == 3
    assert pw.RESTORE_GLIDE_MS == 1500
    assert pw.EXCLUDED_PARAMS >= {"background_brightness", "background_color"}
    from spectra.services import fire_history
    assert "watchdog" in fire_history.BUCKETS


def test_production_gate_stands_down_while_dark():
    """On a fresh, dark process the production gate must refuse to sweep:
    the recording executor means there is no live config to read and no
    light of ours to restore."""
    from spectra.services import engine
    assert engine.executor.mode == "recording"
    assert pw._production_gate() == "engine dark (recording executor)"
    rec = _run(pw.sweep_once())
    assert rec["skipped"] == "engine dark (recording executor)"
