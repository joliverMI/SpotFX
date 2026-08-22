"""The reverse flare's 500ms hold, MEASURED — and what "stuck in reverse"
actually was.

His report (2026-08-21), verbatim: "if shape flares are too close together
the momentary reverse gets tripped up and then it gets stuck in Reverse ...
either find a way to prevent this or some kind of watchdog to make sure
parameters are set correctly." The watchdog is PR #186
(spectra/services/param_watchdog.py). This file proves the PREVENTION half
(spectra/services/scene_response.py's module docstring, "RELEASE
OWNERSHIP") on the real vendored pipeline (fx.headless + FacadeExecutor,
values read off the live effect's own config) or the real RecordingExecutor,
under a REAL asyncio clock wherever timing is the claim:

  1. the hold is measured from the SPIKE, not from the end of the fire's
     own serial write burst. His live executor log showed a Black Hole V2
     flare issuing 13 writes at ~30ms each (spike jumps, gain jumps,
     colour-jump glides, ~400ms) and the release landing 1.02s after the
     spike (seq 164 -> seq 181) — the engine only created the hold timer
     after on_event had finished ALL of that, so "sleep 0.5s" started
     ~0.4-0.5s late. That, not a tween, not record_fire, not the lead
     system, was his 967-1905ms measured "500ms" reverse. Both scheduling
     shapes run here side by side against a burst-emulating executor.
  2. a toggle's release is an instant JUMP (the rule sign-control already
     had), never a 1.5s PULSE_RELEASE_S glide — on the executor log AND on
     the scrubbing preview's ruler. The LIGHT never glided a bool (both
     tween engines classify one "instant"); this is the engine no longer
     asking for a tween it cannot have.
  3. two flares "too close together" on the same toggle: the FIRST fire's
     timer no longer releases the SECOND one mid-hold (ownership by fire),
     and the param returns when the LAST hold matures (supersession).
  4. a momentary spike on a param the scene entry never authored — his
     Orbits V2 / Squiggles V2 Strips run `orbits1d`, which registers
     `reverse`, and neither entry sets it — used to land and NEVER release
     (flush skipped a None target), stranded until an effect-TYPE switch
     rebuilt the instance. It now returns to the effect's own resting
     default (fx.device_model.resting_default).
  5. one virtual's failed release write no longer loses the others'.
  6. STAR's data shape — REPORTED, not changed: its PERMANENT "Reverse
     Direction" is attached to the 0.35-0.7 and 0.7-1.0 flare bands and
     the momentary one to 0-0.35 (read live off :8010). Once the permanent
     fires, reversed IS the baseline (conductor.on_surge), and every later
     momentary reverse releases back to reversed — stuck by construction,
     not by a race; the watchdog rightly sees nothing to restore. Shown on
     the real radial effect so the report is executable, not argued.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless  # noqa: E402
from test_spectra_engine import (VID, _categories_fixture, _engine, _fire,  # noqa: E402
                                 _host, _run)

HOLD_MS = 500
HOLD_S = HOLD_MS / 1000.0


class _Wall:
    """A `.now` shim so test_spectra_engine._engine's clock wiring runs on
    the REAL monotonic clock — timing is the claim in this file."""
    @property
    def now(self) -> float:
        return time.monotonic()


def _slow(executor, per_write_s: float) -> None:
    """Emulate his live room's per-write latency (~30ms per facade PUT,
    read off the executor log's seq spacing) on a FacadeExecutor: the sleep
    precedes the real PUT, so the write LANDS at the end of it."""
    orig = executor._put

    async def slow_put(*a, **kw):
        await asyncio.sleep(per_write_s)
        return await orig(*a, **kw)
    executor._put = slow_put


async def _wait_until(pred, timeout_s: float = 5.0) -> float:
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    while not pred():
        if loop.time() - t0 > timeout_s:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.002)
    return loop.time()


# ── the two scheduling shapes, replicated from services/engine.py ────────────
# (importing spectra.services.engine would construct its live bridge/executor
# singletons — the same reason scripts/check_color_rotate.py replicates)

async def _release_group(responder, g):
    await asyncio.sleep(responder.seconds_until(g.due_at))
    await responder.flush_releases(g.hold_s, fire_seq=g.fire_seq, due_by=g.due_at)


async def _fire_new_shape(responder, intensity: float = 0.5) -> list:
    """engine.fire_response_event since 2026-08-21: one task per
    take_release_schedule() group, sleeping until the group's ABSOLUTE
    due time (stamped when its spike write landed)."""
    await responder.on_event("flare", intensity)
    return [asyncio.create_task(_release_group(responder, g))
            for g in responder.take_release_schedule()]


async def _old_release(responder, hold_s):
    await asyncio.sleep(hold_s)
    await responder.flush_releases(hold_s)


async def _fire_old_shape(responder, intensity: float = 0.5) -> list:
    """engine.fire_response_event BEFORE 2026-08-21, verbatim shape: one
    task per distinct hold_s, created only after on_event returned, sleeping
    hold_s from THEN — i.e. from the END of the fire's own write burst."""
    await responder.on_event("flare", intensity)
    return [asyncio.create_task(_old_release(responder, h))
            for h in responder.pending_hold_groups()]


def _reverse_scene(*, author_reverse: bool = True, with_burst: bool = True):
    """A squiggles entry with his exact 'Reverse Momentarily (500ms)' kind
    and, optionally, the kinds that make a real fire a multi-write BURST:
    a permanent smooth-param patch (a glide, issued BEFORE the reverse
    jump) and a momentary gain (a brightness jump issued AFTER it)."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    params = {"spawn_rate": 1.0}
    if author_reverse:
        params["reverse"] = False
    kinds = [FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                       hold_ms=HOLD_MS,
                       params={"reverse": {"mode": "absolute", "value": 1}})]
    band = {"Reverse Momentarily (500ms)": 1.0}
    if with_burst:
        kinds.append(FlareKind(name="Flare patch", type="permanent",
                               params={"spawn_rate": {"mode": "absolute",
                                                      "value": 2.0}}))
        kinds.append(FlareKind(name="Gain pulse", type="momentary",
                               hold_ms=250, gain=1.3))
        band.update({"Flare patch": 1.0, "Gain pulse": 1.0})
    return SceneV2(
        name="Reverse",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="squiggles",
            params=params, brightness=0.5)],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0, kinds=band)])})


# ── 1. the hold, measured on the real effect under real time ────────────────

def test_reverse_reads_false_within_its_hold_on_the_real_effect(tmp_path):
    """ACTUAL time `reverse` reads False after a 500ms hold, on the real
    vendored squiggles effect, with the real FacadeExecutor emulating his
    room's per-write latency and a genuine asyncio timer — measured from
    the instant the live config first reads True to the instant it reads
    False again. Authored 500ms -> within 500ms + one write latency."""
    per_write = 0.03
    scene = _reverse_scene()

    async def main():
        host, virtual = await _host(tmp_path, "hold-real")
        try:
            config = {"spawn_rate": 1.0, "reverse": False, "brightness": 0.5}
            effect = headless.attach_effect(host, virtual, "squiggles", config)
            executor, conductor, responder, _ = _engine(_Wall())
            _slow(executor, per_write)
            _fire(conductor, scene, config)

            fire = asyncio.ensure_future(_fire_new_shape(responder))
            t_true = await _wait_until(lambda: effect._config.get("reverse") is True)
            t_false = await _wait_until(lambda: effect._config.get("reverse") is False)
            for t in await fire:
                await t
            window = t_false - t_true
            print(f"\nreverse window (new shape, {per_write*1000:.0f}ms/write): {window*1000:.0f}ms")
            # never shorter than the authored hold; never more than one
            # write latency + scheduler slack past it
            assert HOLD_S - 0.01 <= window <= HOLD_S + per_write + 0.12, window
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 2. the mechanism: hold-from-spike vs hold-from-end-of-burst, his shape ──

def _recording_engine(executor):
    """Conductor + responder on a caller-supplied executor with an
    in-memory room — the multi-virtual (5, like his room) recording rig."""
    from random import Random
    from spectra.models.sequencer import SequencerConfig
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.scene_response import ResponseEngine
    room_box = [cj.RoomColorState()]
    clock = time.monotonic
    conductor = DriftConductor(
        executor=executor, clock=clock, leg_s=20.0, intensity=lambda: 0.5,
        drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: None, set_cards=lambda: [],
        sequencer_config=lambda: SequencerConfig(),
        gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(3))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(5), clock=clock,
        sequencer_config=lambda: SequencerConfig(), curve_profiles=lambda: {},
        eligible_sets=lambda sc: {}, room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st))
    return conductor, responder


def _five_virtual_scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    vids = [f"v{i}" for i in range(5)]
    return SceneV2(
        name="Five",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=v, effect_type="blackhole1d",
            params={"reverse": False, "beat_burst": 2}, brightness=0.6)
            for v in vids],
        flare_kinds=[
            FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                      hold_ms=HOLD_MS,
                      params={"reverse": {"mode": "absolute", "value": 1}}),
            FlareKind(name="Flare patch", type="permanent",
                      params={"beat_burst": {"mode": "absolute", "value": 6}}),
            FlareKind(name="Gain pulse", type="momentary", hold_ms=250, gain=1.3),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Reverse Momentarily (500ms)": 1.0,
                             "Flare patch": 1.0, "Gain pulse": 1.0})])}), vids


def _seed_five(conductor, scene, vids):
    conductor.on_scene_fire(scene, [{
        "virtual_id": v, "effect_type": "blackhole1d",
        "config": {"reverse": False, "beat_burst": 2, "brightness": 0.6},
        "entry_id": dev.id, "color_mode": dev.color.mode}
        for v, dev in zip(vids, scene.devices)])


def _reverse_windows(writes, vids) -> dict[str, float]:
    """Per virtual: release-write time minus spike-write time, off the
    executor's own log (clock = monotonic) — the same instrument his live
    room's seq 164 -> 181 reading came from."""
    out = {}
    for v in vids:
        spike = next(w["at"] for w in writes
                     if w["virtual_id"] == v and w["params"].get("reverse") is True)
        release = next(w["at"] for w in writes
                       if w["virtual_id"] == v and w["params"].get("reverse") is False)
        out[v] = release - spike
    return out


def test_hold_is_measured_from_the_spike_not_from_the_end_of_the_burst():
    """Five virtuals (his room's count), every write ~30ms (his executor
    log's seq spacing): one flare = 5 spike jumps + 5 gain jumps, ~300ms
    of serial burst — the shape of his live trace. OLD engine shape: every
    virtual's reverse holds ~hold + (burst after its spike) ~ 0.8s. NEW:
    ~hold (+ one write latency). This is the 967-1905ms overrun, and its
    fix, in one number each."""
    from spectra.services.fx_executor import RecordingExecutor
    per_write = 0.03

    class SlowRecording(RecordingExecutor):
        async def jump(self, *a, **kw):
            await asyncio.sleep(per_write)
            return await super().jump(*a, **kw)

        async def glide(self, *a, **kw):
            await asyncio.sleep(per_write)
            return await super().glide(*a, **kw)

    async def run(shape):
        executor = SlowRecording(clock=time.monotonic)
        conductor, responder = _recording_engine(executor)
        scene, vids = _five_virtual_scene()
        _seed_five(conductor, scene, vids)
        for t in await shape(responder):
            await t
        assert responder.pending_hold_groups() == []
        return _reverse_windows(list(executor.writes), vids)

    async def main():
        old = await run(_fire_old_shape)
        new = await run(_fire_new_shape)
        print("\nold shape (hold from end of burst):",
              {v: f"{w*1000:.0f}ms" for v, w in old.items()})
        print("new shape (hold from spike):       ",
              {v: f"{w*1000:.0f}ms" for v, w in new.items()})
        # OLD: sleep(0.5) only started after the whole burst — every virtual
        # overran by roughly the writes still to come after its own spike
        # (the other spikes + 5 gain jumps), ~0.2-0.3s here, ~0.4-0.5s live.
        assert all(w >= HOLD_S + 0.2 for w in old.values()), old
        # NEW: every virtual holds its authored 500ms (+ its own release
        # write's latency), regardless of its position in the burst.
        assert all(HOLD_S - 0.01 <= w <= HOLD_S + per_write + 0.12
                   for w in new.values()), new

    _run(main())


# ── 3. a toggle's release is an instant jump — on the log and on the ruler ──

def test_toggle_release_is_an_instant_jump_never_a_glide(tmp_path):
    from spectra.services import flare_preview
    from spectra.services.fx_executor import JUMP_MS
    from spectra.services.scene_response import PULSE_RELEASE_S
    scene = _reverse_scene(with_burst=False)
    kind = scene.flare_kinds[0]

    async def main():
        host, virtual = await _host(tmp_path, "toggle-jump")
        try:
            config = {"spawn_rate": 1.0, "reverse": False, "brightness": 0.5}
            effect = headless.attach_effect(host, virtual, "squiggles", config)
            executor, conductor, responder, _ = _engine(_Wall())
            _fire(conductor, scene, config)
            await responder.on_event("flare", 0.5)
            assert effect._config["reverse"] is True
            await responder.flush_releases(HOLD_S)
            assert effect._config["reverse"] is False
            release = [w for w in executor.writes
                       if w["params"].get("reverse") is False][-1]
            assert release["kind"] == "jump" and release["duration_ms"] == JUMP_MS, release
            assert not any(w["kind"] == "glide" and "reverse" in w["params"]
                           for w in executor.writes)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())

    # The scrubbing preview's ruler: the toggle kind's animation END is the
    # hold plus the jump's own 1ms — not hold + 1.5s. Before this fix it
    # drew a 2.0s "release glide" the light never performed.
    _categories_fixture(tmp_path)
    tl = _run(flare_preview.build_timeline(scene, kind, 0.5))
    assert len(tl["writes"]) == 2, tl["writes"]
    spike, back = sorted(tl["writes"], key=lambda w: w["at_s"])
    assert back["kind"] == "jump" and back["duration_ms"] == JUMP_MS
    assert tl["animation_end_s"] == pytest.approx(HOLD_S + JUMP_MS / 1000.0)
    assert tl["animation_end_s"] < HOLD_S + PULSE_RELEASE_S


# ── 4. two flares too close together on the same toggle ─────────────────────

def test_two_close_fires_release_once_when_the_last_hold_matures(tmp_path):
    """Fire A, then fire B 250ms later, both his 500ms reverse. OLD: A's
    timer (by hold_s) drained BOTH entries at A+500 — B's spike cut to
    250ms. NEW: A's release is superseded by B's still-pending spike; the
    param returns at B+500 = A+750, never early, and B's entry is never
    drained by A's task."""
    scene = _reverse_scene(with_burst=False)

    async def main():
        host, virtual = await _host(tmp_path, "close-fires")
        try:
            config = {"spawn_rate": 1.0, "reverse": False, "brightness": 0.5}
            effect = headless.attach_effect(host, virtual, "squiggles", config)
            executor, conductor, responder, _ = _engine(_Wall())
            _fire(conductor, scene, config)

            tasks_a = await _fire_new_shape(responder)
            t_true = await _wait_until(lambda: effect._config.get("reverse") is True)
            await asyncio.sleep(0.25)
            tasks_b = await _fire_new_shape(responder)
            assert len(responder.pending_release_keys()) == 1
            assert len(responder._pending_releases) == 2   # both fires' entries
            # A's own timer matured (~A+0.5): reverse still True, B's entry
            # still pending — A's release was superseded, B's not drained.
            await asyncio.sleep(HOLD_S - 0.25 + 0.08)
            for t in tasks_a:
                assert t.done()
            assert effect._config["reverse"] is True
            assert responder.pending_release_keys() == {(VID, "reverse")}
            t_false = await _wait_until(lambda: effect._config.get("reverse") is False)
            for t in tasks_b:
                await t
            window = t_false - t_true
            print(f"\ntwo fires 250ms apart: reverse window {window*1000:.0f}ms")
            assert 0.25 + HOLD_S - 0.02 <= window <= 0.25 + HOLD_S + 0.15, window
            assert responder.pending_release_keys() == set()
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 5. a never-authored param releases to its resting default ───────────────

def test_momentary_spike_on_a_never_authored_param_is_not_stranded(tmp_path):
    """His Orbits V2 / Squiggles V2 Strips shape: the entry authors no
    `reverse`, the effect (orbits1d there, squiggles here — both register
    it, default False) runs at its schema default. Pre-fix: the spike
    landed True and flush_releases found no baseline -> `continue` ->
    stranded True until an effect-type switch. Now: return_to is resolved
    at spike time from fx.device_model.resting_default and the release
    lands it."""
    from fx import device_model
    scene = _reverse_scene(author_reverse=False, with_burst=False)

    async def main():
        host, virtual = await _host(tmp_path, "unauthored")
        try:
            config = {"spawn_rate": 1.0, "brightness": 0.5}   # no reverse
            effect = headless.attach_effect(host, virtual, "squiggles", config)
            assert effect._config["reverse"] is False     # schema default
            executor, conductor, responder, _ = _engine(_Wall())
            _fire(conductor, scene, config)
            assert "reverse" not in conductor.virtuals[VID].param_baseline
            assert responder.release_target(VID, "reverse") is None  # the watchdog's own out-of-scope case

            await responder.on_event("flare", 0.5)
            assert effect._config["reverse"] is True
            (entry,) = responder._pending_releases
            assert entry.return_to is False
            assert device_model.resting_default("squiggles", "reverse") is False
            assert await responder.flush_releases(HOLD_S) == 1
            assert effect._config["reverse"] is False
            assert responder.pending_release_keys() == set()
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── 6. one virtual's failed release write does not lose the others' ─────────

def test_a_failed_release_write_on_one_virtual_does_not_strand_the_rest():
    from spectra.services.fx_executor import RecordingExecutor

    class FlakyRecording(RecordingExecutor):
        async def jump(self, virtual_id, *a, **kw):
            if virtual_id == "v1":
                raise RuntimeError("facade 500 on v1")
            return await super().jump(virtual_id, *a, **kw)

    async def main():
        executor = FlakyRecording(clock=time.monotonic)
        conductor, responder = _recording_engine(executor)
        scene, vids = _five_virtual_scene()
        _seed_five(conductor, scene, vids)
        # v1's SPIKE write raises too — _execute_band surfaces that (the
        # engine's supervisor logs it); the point here is the RELEASE.
        try:
            await responder.on_event("flare", 0.5)
        except RuntimeError:
            pass
        spiked = {e.virtual_id for e in responder._pending_releases if e.param == "reverse"}
        assert spiked == set(vids)
        released = await responder.flush_releases(HOLD_S)
        assert released == 4          # v1's write failed, logged, dropped
        assert responder.pending_release_keys() == set()
        for v in vids:
            if v != "v1":
                assert executor.current[v]["reverse"] is False

    _run(main())


# ── 7. STAR's data shape: permanent then momentary = stuck by construction ──

def test_star_permanent_reverse_makes_every_later_momentary_reverse_stick(tmp_path):
    """Exactly his live STAR attachments (read off :8010, 2026-08-21):
    'Reverse Direction' (PERMANENT, spin_sign 0) on the 0.35-0.7 and
    0.7-1.0 flare bands; 'Reverse Momentarily (500ms)' on 0-0.35. A
    permanent kind's carry moves the baseline (conductor.on_surge), so
    after ONE mid/high flare, reversed IS the baseline: the next low
    flare's momentary reverse lands -0.55 (already there) and releases
    back to -0.55. Not a race, not a lost release — the watchdog's own
    release_target agrees there is nothing to restore. A DATA shape for
    him to decide; nothing here changes it."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    _categories_fixture(tmp_path)
    scene = SceneV2(
        name="STAR",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="radial",
            params={"spin": 0.55})],
        flare_kinds=[
            FlareKind(name="Reverse Direction", type="permanent",
                      params={"spin_sign": {"mode": "absolute", "value": 0.0}}),
            FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                      hold_ms=HOLD_MS,
                      params={"spin_sign": {"mode": "absolute", "value": 0.0}}),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=0.35,
                      kinds={"Reverse Momentarily (500ms)": 1.0}),
            FlareBand(intensity_min=0.35, intensity_max=0.7,
                      kinds={"Reverse Direction": 1.0}),
            FlareBand(intensity_min=0.7, intensity_max=1.0,
                      kinds={"Reverse Direction": 1.0}),
        ])})

    async def main():
        host, virtual = await _host(tmp_path, "star-shape")
        try:
            with headless.fake_clock() as clock:
                config = {"spin": 0.55}
                effect = headless.attach_effect(host, virtual, "radial", config)
                executor, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                # A mid-intensity flare: the PERMANENT kind. Reversed, and
                # reversed is now the baseline.
                rec = await responder.on_event("flare", 0.5)
                assert [k["name"] for k in rec["kinds"]] == ["Reverse Direction"]
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["spin"] == pytest.approx(-0.55)
                assert conductor.virtuals[VID].param_baseline["spin"] == pytest.approx(-0.55)
                assert responder.pending_release_keys() == set()

                # A low-intensity flare: the MOMENTARY kind. Lands -0.55
                # (no visible change), releases to the carried baseline —
                # which is -0.55. Still reversed.
                rec = await responder.on_event("flare", 0.2)
                assert [k["name"] for k in rec["kinds"]] == ["Reverse Momentarily (500ms)"]
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["spin"] == pytest.approx(-0.55)
                assert responder.release_target(VID, "spin") == pytest.approx(-0.55)
                assert await responder.flush_releases(HOLD_S) == 1
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["spin"] == pytest.approx(-0.55)
                assert effect.spin < 0   # stuck in reverse — by his data's construction
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
