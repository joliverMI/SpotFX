"""A LULL THAT FOLLOWS A COMPLETED CHARGE STARTS FROM ITS BEGINNING — on
every phase effect, through the shared arm write, not per effect.

The defect (found building PR #365, fixed here at its root): scene_response.
_drive_phase arms a phase with a jump (a 1 ms tween) to phase_progress 0.0
and immediately glides it to 1.0. The tween engine (fx/effects/__init__.py
start_param_transitions) retargeted the glide from the jump tween's CURRENT
value — and the jump had not rendered a frame yet, so its current value was
still the finished charge's 1.0. The lull glided 1.0 -> 1.0: it sat at its
end state from its first frame, and the shared orphan watchdog
(particle_handoff.phase_release_due) saw a "completed" build and released
the lull PHASE_GRACE_S (12 s) in — before a 20 s lull's drop could arrive.
The drop arm after a completed lull had the same shape.

What is proven here, for EVERY effect in fx.device_model.PHASE_EFFECTS, on
the real render pipeline (fx.headless + the real ResponseEngine on the
FacadeExecutor, one fake clock): a completed charge, then a 20 s lull —
  - the lull's phase_progress starts near 0, climbs, and only reaches 1.0
    at the end of SpotFX's ramp (90% of the gap), never on its first frame;
  - nothing releases the lull before its drop arrives (the effect is still
    in its lull at 19.9 s);
and the drop that follows the lull starts from 0 too.

`test_the_harness_goes_red_on_the_defect` re-creates the pre-fix retarget
and proves the same measurement reports the defect, so a green run here is
evidence, not decoration.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, facade, headless  # noqa: E402
from fx.effects import Effect  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402

FPS = 60
DT = 1.0 / FPS
COLS, ROWS = 72, 37
STRIP = 120
LULL_GAP_MS = 20_000

# 1-D phase effects render to a strip, Pulse to one light, the rest to a
# crystal-sized matrix.
STRIP_EFFECTS = {"blackhole1d", "orbits1d", "fireworks1d"}
ONE_LIGHT = {"pulse"}

EXTRA_CFG = {
    "pulse": {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5},
}


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
        virtuals.append({"id": vid, "is_device": False,
                         "auto_generated": False,
                         "config": {"name": vid, "mapping": "span",
                                    "rows": rows},
                         "segments": [[f"{vid}-dev", 0, n - 1, False]]})
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


def _run(tmp_path, effects, *, lull_gap_ms=LULL_GAP_MS, then_drop=False):
    """A completed charge, then a lull of `lull_gap_ms` (and optionally the
    drop that ends it), driven by the production ResponseEngine on the
    FacadeExecutor. Returns {effect_type: [(t, progress, phase), ...]} per
    lull frame, and the same for the drop's first frames under "drop"."""
    from spectra.models.scene import SceneV2
    from spectra.services import color_journey as cj
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    async def main():
        config_dir = str(tmp_path / "fx-room")
        _config(config_dir, effects)
        headless.silence_audio()
        from fx.host import FxHost
        host = FxHost(config_dir)
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        facade.set_host(host)
        lull = {et: [] for et in effects}
        drop = {et: [] for et in effects}
        try:
            with headless.fake_clock() as clock:
                vs = {et: host.virtuals.get(f"{et}-v") for et in effects}
                fx_ = {et: headless.attach_effect(
                    host, vs[et], et, dict(EXTRA_CFG.get(et, {})))
                    for et in effects}
                room = [cj.RoomColorState()]
                ex = FacadeExecutor(
                    clock=lambda: clock.now,
                    room_controls_load=lambda: rc.RoomControlState())
                conductor = DriftConductor(
                    executor=ex, clock=lambda: clock.now,
                    drift_profiles=lambda: {}, curve_profiles=lambda: {},
                    room_load=lambda: room[0],
                    room_save=lambda st: room.__setitem__(0, st),
                    set_cards=lambda: [], gradient_profiles=lambda: {},
                    room_controls=lambda: rc.RoomControlState(),
                    rng=Random(3))
                responder = ResponseEngine(
                    conductor=conductor, executor=ex, rng=Random(5),
                    clock=lambda: clock.now, curve_profiles=lambda: {},
                    room_load=lambda: room[0],
                    room_save=lambda st: room.__setitem__(0, st),
                    room_controls=lambda: rc.RoomControlState())
                conductor.on_scene_fire(SceneV2(name="room"), [
                    {"virtual_id": f"{et}-v", "effect_type": et,
                     "config": {}, "entry_id": "", "color_mode": "set"}
                    for et in effects])

                def step(n=1):
                    for _ in range(n):
                        clock.advance(DT)
                        for v in vs.values():
                            f = v.assemble_frame()
                            if f is not None:
                                v.flush(f)

                def sample(into, t):
                    for et, e in fx_.items():
                        into[et].append((
                            t, float(e._config.get("phase_progress", 0.0)),
                            _phase_of(e)))

                step(2 * FPS)
                await responder.on_event("charge", 0.7, gap_ms=3_000)
                step(3 * FPS)                       # the charge COMPLETES
                for et, e in fx_.items():
                    assert e._config["phase_progress"] == 1.0, et
                rec = await responder.on_event("lull", 0.5,
                                               gap_ms=lull_gap_ms)
                assert len(rec["phase"]["targets"]) == len(effects)
                for i in range(1, int(lull_gap_ms / 1000 * FPS)):
                    step()
                    sample(lull, i * DT)
                if then_drop:
                    await responder.on_event("drop", 0.9)
                    for i in range(1, 6):
                        step()
                        sample(drop, i * DT)
        finally:
            facade.set_host(None)
            await host.shutdown()
        return lull, drop

    return asyncio.run(main())


def _phase_of(effect):
    """The phase an effect believes it is in (Dancer keeps its beat clock in
    `_phase` and its charge/lull/drop in `_cld_phase`)."""
    if hasattr(effect, "_cld_phase"):
        return effect._cld_phase
    return getattr(effect, "_phase", None)


def _at(rows, t):
    return min(rows, key=lambda r: abs(r[0] - t))


ALL_PHASE_EFFECTS = sorted(device_model.PHASE_EFFECTS)


@pytest.fixture(scope="module")
def room(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("lull-after-charge"),
                ALL_PHASE_EFFECTS, then_drop=True)


@pytest.mark.parametrize("effect_type", ALL_PHASE_EFFECTS)
def test_a_lull_after_a_completed_charge_starts_from_its_beginning(
        room, effect_type):
    rows = room[0][effect_type]
    first_t, first_p, _ph = rows[0]
    # one frame into an 18 s ramp: progress has barely moved off 0
    assert first_p < 0.01, (effect_type, first_p)
    # it climbs with the ramp (90% of the 20 s gap = 18 s) ...
    assert _at(rows, 9.0)[1] == pytest.approx(0.5, abs=0.02), effect_type
    assert _at(rows, 17.0)[1] < 0.98, effect_type
    # ... and only completes at the ramp's end
    done = next(t for t, p, _ in rows if p >= 0.99)
    assert 17.5 <= done <= 18.2, (effect_type, done)


@pytest.mark.parametrize("effect_type", ALL_PHASE_EFFECTS)
def test_nothing_releases_a_long_lull_before_its_drop(room, effect_type):
    rows = room[0][effect_type]
    phases = {ph for _t, _p, ph in rows}
    assert phases == {"lull"}, (effect_type, phases)


@pytest.mark.parametrize("effect_type", ALL_PHASE_EFFECTS)
def test_the_drop_after_a_completed_lull_starts_from_its_beginning(
        room, effect_type):
    rows = room[1][effect_type]
    # the drop ramp is 400 ms: one frame in is ~4%, never the lull's 1.0
    assert rows[0][1] < 0.1, (effect_type, rows[0])


# ── the harness goes red on the defect ─────────────────────────────────────

def _pre_fix_start_param_transitions(self, targets, duration_ms,
                                     easing="linear", blend="rgb"):
    """The retarget as it was before the fix: a mid-tween key ALWAYS
    restarts from the prior tween's current value, even a jump that has not
    rendered a frame (numeric keys only — all this harness needs)."""
    with self.lock:
        if duration_ms is None or duration_ms <= 0:
            self._apply_config(dict(targets), validate=True, fire_event=True)
            return
        tweens = dict(self._tweens) if self._tweens else {}
        instant = {}
        for key, target in targets.items():
            kind = self._classify_param(key, target)
            if kind != "numeric":
                instant[key] = target
                tweens.pop(key, None)
                continue
            prior = tweens.get(key)
            start = float(prior["current"] if prior
                          else self._config.get(key))
            tweens[key] = {"elapsed": 0.0, "duration": duration_ms / 1000.0,
                           "easing": easing, "kind": "numeric",
                           "start": start, "target": float(target),
                           "current": start,
                           "integer": key in self._integer_param_keys()}
        if instant:
            self._apply_config(instant, validate=True, fire_event=True)
        self._tweens = tweens or None


def test_the_harness_goes_red_on_the_defect(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(Effect, "start_param_transitions",
                        _pre_fix_start_param_transitions)
    caplog.set_level(logging.INFO)
    lull, _drop = _run(tmp_path, ["orbits"])
    rows = lull["orbits"]
    # the lull sits at its end state from its first frame ...
    assert rows[0][1] == 1.0
    # ... and the watchdog releases it PHASE_GRACE_S in, before the drop
    released = [t for t, _p, ph in rows if ph != "lull"]
    assert released and 11.5 <= released[0] <= 12.5, released[:1]
    assert any("watchdog release" in r.getMessage() for r in caplog.records)


def test_a_glide_still_retargets_a_real_glide_without_a_snap():
    """The fix only treats a tween that would land by the very next frame as
    landed. A glide interrupted mid-way still continues from where it is."""
    from fx.effects import blackhole as bh
    from types import SimpleNamespace
    e = bh.Blackhole2d.__new__(bh.Blackhole2d)
    import threading
    e.lock = threading.RLock()
    e._config = {"phase_progress": 0.0}
    e._tweens = None
    e._virtual = SimpleNamespace(refresh_rate=60)
    e.passed = DT
    e._apply_config = lambda cfg, **_kw: e._config.update(cfg)
    e.start_param_transitions({"phase_progress": 1.0}, 1000)
    e._tweens["phase_progress"]["elapsed"] = 0.4
    e._tweens["phase_progress"]["current"] = 0.4
    e.start_param_transitions({"phase_progress": 0.0}, 1000)
    assert e._tweens["phase_progress"]["start"] == pytest.approx(0.4)
    # a 1 ms jump has not rendered: the glide after it starts from its target
    e._tweens = None
    e._config["phase_progress"] = 1.0
    e.start_param_transitions({"phase_progress": 0.0}, 1)
    e.start_param_transitions({"phase_progress": 1.0}, 1000)
    assert e._tweens["phase_progress"]["start"] == 0.0
    assert np.isclose(e._tweens["phase_progress"]["current"], 0.0)
