"""NO EFFECT'S ORPHAN WATCHDOG RELEASES A PRE-DROP LULL BEFORE ITS DROP
(predrop plan step 5's acceptance; plan §5's named risk: "a pre-drop
member's lull ramp ends up to 4 s earlier").

A member's lull is measured to its pre-drop (fx/effects/pre_drop.py), so
its phase_progress ramp finishes at 90% of the time to the PRE-DROP and
then hangs at 1.0 through the pre-drop's gap — up to the vocal intro's
4.5 s bound — before the drop arrives. Every phase effect judges an
orphaned lull through the one shared rule, particle_handoff.
phase_release_due (12 s after the build completed): this proves that rule
never fires before the drop over every legal lull and pre-drop, and then
drives EVERY effect in fx.device_model.PRE_DROP_EFFECTS' possible future
membership — all of PHASE_EFFECTS, as stub members — through a 20 s lull
with the longest pre-drop on the real render pipeline (fx.headless + the
production ResponseEngine on the FacadeExecutor), recording every call to
the watchdog: none releases, and every effect is still in its lull when the
drop is due. `test_the_instrument_sees_a_real_release` is the red control:
the same rig, a lull whose drop never comes, and the watchdog is seen to
fire.
"""
from __future__ import annotations

import asyncio
import json
import os
from random import Random

import pytest

from fx import device_model, facade, headless
from fx.effects import particle_handoff
from spectra.services import pre_drop_play
from spectra.services import room_controls as rc
from spectra.services.scene_response import PHASE_RAMP_HANG_FRACTION, _phase_ramp_ms

FPS = 60
DT = 1.0 / FPS
COLS, ROWS = 72, 37
STRIP = 120
STRIP_EFFECTS = {"blackhole1d", "orbits1d", "fireworks1d"}
ONE_LIGHT = {"pulse"}
EXTRA_CFG = {"pulse": {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5}}
INTRO_MAX_BOUND_MS = 4500         # PreDropIntroWindow's own `le`
PARTNER_REACH_MS = 60_000         # the longest lull a build ever runs to


def test_the_shared_rule_never_releases_a_pre_drop_lull_before_its_drop():
    """Every lull length to the effects' own cap, every pre-drop gap to the
    vocal intro's bound: progress ramps over 90% of the time to the
    pre-drop and hangs; the watchdog stays quiet until the drop."""
    assert INTRO_MAX_BOUND_MS >= _intro_bound()
    for lull_ms in range(1_000, PARTNER_REACH_MS + 1, 1_000):
        for gap_ms in range(350, INTRO_MAX_BOUND_MS + 1, 250):
            at_ms = lull_ms - gap_ms
            if at_ms < pre_drop_play.MIN_AFTER_LULL_MS:
                continue
            ramp_s = _phase_ramp_ms("lull", at_ms) / 1000.0
            done_t = None
            t = 0.0
            while t < lull_ms / 1000.0:
                progress = min(1.0, t / ramp_s)
                due, done_t = particle_handoff.phase_release_due(
                    "lull", progress, t, done_t)
                assert not due, (lull_ms, gap_ms, t)
                t += 0.05
    # and the headroom it leaves, stated: the longest hang is the 10% of the
    # longest lull's approach plus the longest gap — under the 12 s grace
    longest = (PARTNER_REACH_MS - INTRO_MAX_BOUND_MS) * PHASE_RAMP_HANG_FRACTION \
        + INTRO_MAX_BOUND_MS
    assert longest < particle_handoff.PHASE_GRACE_S * 1000


def _intro_bound():
    from spectra.models.scene import PreDropIntroWindow
    return next(c.le for c in PreDropIntroWindow.model_fields["max_ms"].metadata
                if hasattr(c, "le"))


def _shape(effect_type):
    if effect_type in ONE_LIGHT:
        return 1, 1
    if effect_type in STRIP_EFFECTS:
        return STRIP, 1
    return COLS * ROWS, ROWS


def _config(config_dir, effects):
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    devices, virtuals = [], []
    for et in effects:
        n, rows = _shape(et)
        vid = f"{et}-v"
        devices.append({"id": f"{vid}-dev", "type": "dummy",
                        "config": {"name": f"{vid}-dev", "pixel_count": n}})
        virtuals.append({"id": vid, "is_device": False, "auto_generated": False,
                         "config": {"name": vid, "mapping": "span", "rows": rows},
                         "segments": [[f"{vid}-dev", 0, n - 1, False]]})
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


def _phase_of(effect):
    if hasattr(effect, "_cld_phase"):
        return effect._cld_phase
    if getattr(effect, "_strip_phase", False):
        return effect._sp_phase
    return getattr(effect, "_phase", None)


def _run(tmp_path, effects, *, lull_gap_ms, pre_gap_ms, render_s):
    """A pre-drop lull on every effect (each a stub member), rendered for
    `render_s`. Returns ({effect: phase at the end}, [every watchdog call
    that said release], the lull record)."""
    from spectra.models.scene import SceneV2
    from spectra.services import color_journey as cj
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine
    releases: list = []
    real_due = particle_handoff.phase_release_due

    def watched(phase, progress, t, done_t):
        due, done = real_due(phase, progress, t, done_t)
        if due:
            releases.append((phase, round(float(t), 3)))
        return due, done

    async def main():
        config_dir = str(tmp_path / "fx-room")
        _config(config_dir, effects)
        headless.silence_audio()
        from fx.host import FxHost
        host = FxHost(config_dir)
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        facade.set_host(host)
        try:
            with headless.fake_clock() as clock:
                vs = {et: host.virtuals.get(f"{et}-v") for et in effects}
                fx_ = {et: headless.attach_effect(host, vs[et], et,
                                                  dict(EXTRA_CFG.get(et, {})))
                       for et in effects}
                room = [cj.RoomColorState()]
                controls = rc.RoomControlState()
                ex = FacadeExecutor(clock=lambda: clock.now,
                                    room_controls_load=lambda: controls)
                conductor = DriftConductor(
                    executor=ex, clock=lambda: clock.now,
                    drift_profiles=lambda: {}, curve_profiles=lambda: {},
                    room_load=lambda: room[0],
                    room_save=lambda st: room.__setitem__(0, st),
                    set_cards=lambda: [], gradient_profiles=lambda: {},
                    room_controls=lambda: controls, rng=Random(3))
                responder = ResponseEngine(
                    conductor=conductor, executor=ex, rng=Random(5),
                    clock=lambda: clock.now, curve_profiles=lambda: {},
                    room_load=lambda: room[0],
                    room_save=lambda st: room.__setitem__(0, st),
                    room_controls=lambda: controls)
                scene = SceneV2(name="room", pre_drop_intro={
                    "enabled": True, "min_ms": 350, "max_ms": INTRO_MAX_BOUND_MS})
                conductor.on_scene_fire(scene, [
                    {"virtual_id": f"{et}-v", "effect_type": et, "config": {},
                     "entry_id": "", "color_mode": "set"} for et in effects])

                def step(n):
                    for _ in range(n):
                        clock.advance(DT)
                        for v in vs.values():
                            f = v.assemble_frame()
                            if f is not None:
                                v.flush(f)

                step(FPS)
                cand = pre_drop_play.PreDropCandidate(
                    at_ms=lull_gap_ms - pre_gap_ms, gap_ms=pre_gap_ms,
                    kind="intro", key="seq")
                rec = await responder.on_event("lull", 0.5, gap_ms=lull_gap_ms,
                                               pre_drop=cand)
                step(int(render_s * FPS))
                return {et: _phase_of(e) for et, e in fx_.items()}, rec
        finally:
            facade.set_host(None)
            await host.shutdown()

    real = particle_handoff.phase_release_due
    particle_handoff.phase_release_due = watched
    try:
        phases, rec = asyncio.run(main())
    finally:
        particle_handoff.phase_release_due = real
    return phases, releases, rec


ALL_PHASE_EFFECTS = sorted(device_model.PHASE_EFFECTS)


@pytest.fixture(scope="module")
def every_effect(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(device_model, "PRE_DROP_EFFECTS", frozenset(ALL_PHASE_EFFECTS))
    try:
        # a 20 s lull, the pre-drop 4.5 s before its drop: every member's
        # ramp ends at 0.9 x 15.5 s = 13.95 s and hangs 6 s to the drop
        return _run(tmp_path_factory.mktemp("pre-drop-watchdog"),
                    ALL_PHASE_EFFECTS, lull_gap_ms=20_000,
                    pre_gap_ms=INTRO_MAX_BOUND_MS, render_s=19.9)
    finally:
        mp.undo()


def test_every_member_was_told_the_longest_pre_drop(every_effect):
    _phases, _releases, rec = every_effect
    pd = rec["phase"]["pre_drop"]
    assert pd["plays"], pd
    assert sorted(pd["told"]) == sorted(f"{et}-v" for et in ALL_PHASE_EFFECTS)
    assert pd["member_lull"]["ramp_ms"] == round(15_500 * 0.9)


def test_no_watchdog_releases_before_the_drop(every_effect):
    _phases, releases, _rec = every_effect
    assert releases == []


@pytest.mark.parametrize("effect_type", ALL_PHASE_EFFECTS)
def test_every_effect_is_still_in_its_lull_when_the_drop_is_due(every_effect,
                                                                  effect_type):
    phases, _releases, _rec = every_effect
    assert phases[effect_type] == "lull", (effect_type, phases[effect_type])


def test_the_instrument_sees_a_real_release(tmp_path, monkeypatch):
    """Red control: a member's lull whose drop never arrives — 15 s past the
    ramp's end — IS released by the watchdog, and the recorder sees it."""
    monkeypatch.setattr(device_model, "PRE_DROP_EFFECTS", frozenset({"blackhole"}))
    phases, releases, _rec = _run(tmp_path, ["blackhole"], lull_gap_ms=3_000,
                                  pre_gap_ms=800, render_s=16.0)
    assert releases, "the watchdog fired on the orphaned lull"
    assert phases["blackhole"] != "lull"
