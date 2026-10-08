"""The Light Show's Pulse modulation (fx/pulse_modulation.py, read by
fx/effects/pulse.py; the Admiral, 2026-10-08): reactivity 0..1 and a
brightness floor / ceiling, held per virtual.

Proven on the REAL effect class, frame-stepped, measured on what it renders:
  * idle (no entry for the virtual) is byte-identical to an effect that never
    heard of the module;
  * reactivity scales the live-audio hit pulse linearly (1 = today, 0 = the
    resting glow) and the rainbow walk's hit step (option A) — and NOT the
    flash flare, the drop burst or the resting level;
  * floor and ceiling clamp the eye-scale level, through hits, a lull's
    darkness and a drop;
  * ramps, suspension and pruning of the fx module itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pulse_song_harness as h  # noqa: E402
from fx import pulse_modulation as pm  # noqa: E402

DT = h.DT
FPS = h.FPS
VID = "hues"
RAINBOW = ("linear-gradient(90deg, #ff0000 0%, #ffff00 17%, #00ff00 33%, "
           "#00ffff 50%, #0000ff 67%, #ff00ff 83%, #ff0000 100%)")


@pytest.fixture(autouse=True)
def _clean():
    pm.clear()
    pm.suspend(False)
    pm.set_clock(lambda: 0.0)
    yield
    pm.clear()
    pm.suspend(False)
    import time
    pm.set_clock(time.monotonic)


class Rig:
    def __init__(self, vid=VID, **config):
        cfg = {"gradient": "#ff0000", "beat_ms": 500.0}
        cfg.update(config)
        self.e = h.new_effect(cfg)
        self.e._virtual_id = lambda: vid

        def log_sec():
            self.e.now += DT
            self.e.passed = DT
        self.e.log_sec = log_sec
        self.levels: list[float] = []
        self.out: list[np.ndarray] = []

    def frame(self, x=None):
        if x is not None:
            self.e.ingest_signal(x, DT)
        self.e._render()
        px = self.e.get_pixels()
        self.levels.append(self.e.level)
        self.out.append(px[0].copy())

    def settle(self, s=2.0, x=0.1):
        for _ in range(int(s * FPS)):
            self.frame(x)

    def hits(self, n=6, gap_s=0.6):
        for _ in range(n):
            self.frame(1.0)
            self.settle(gap_s)


def _peak_over_rest(r: Rig, n=6):
    r.settle(3.0)
    rest = r.levels[-1]
    start = len(r.levels)
    r.hits(n)
    return max(r.levels[start:]) - rest, rest


# ── the fx module ──────────────────────────────────────────────────────────

def test_no_entry_reads_none_and_ramps_land_linearly():
    t = {"now": 0.0}
    pm.set_clock(lambda: t["now"])
    assert pm.get(VID) is None
    pm.set_mod(VID, reactivity=0.0, floor=0.2, ceiling=0.8, fade_s=2.0)
    t["now"] = 1.0
    m = pm.get(VID)
    assert (m.reactivity, m.floor, m.ceiling) == pytest.approx((0.5, 0.1, 0.9))
    t["now"] = 2.5
    assert pm.get(VID) == pm.Mod(0.0, 0.2, 0.8)
    # a new target ramps from where the old one got to, never jumps
    pm.set_mod(VID, fade_s=1.0)
    t["now"] = 3.0
    assert pm.get(VID).reactivity == pytest.approx(0.5)
    t["now"] = 4.0
    assert pm.prune() == [VID]
    assert pm.get(VID) is None


def test_suspension_reads_untouched_and_keeps_targets():
    pm.set_mod(VID, reactivity=0.0)
    pm.suspend(True)
    assert pm.get(VID) is None
    pm.suspend(False)
    assert pm.get(VID).reactivity == 0.0


# ── the effect: idle is byte-identical ─────────────────────────────────────

def test_idle_and_identity_render_byte_identical_to_no_module():
    plain, idle, other = Rig(energy=0.6), Rig(energy=0.6), Rig(vid="crystal", energy=0.6)
    plain.e._virtual_id = lambda: None
    pm.set_mod("crystal-elsewhere", reactivity=0.0)     # someone else's entry
    for r in (plain, idle, other):
        r.settle(1.0)
        r.hits(5, 0.4)
    assert np.array_equal(np.asarray(plain.out), np.asarray(idle.out))
    assert np.array_equal(np.asarray(plain.out), np.asarray(other.out))
    # an entry AT identity (reactivity 1, floor 0, ceiling 1) changes nothing
    ident = Rig(energy=0.6)
    pm.set_mod(VID)
    ident.settle(1.0)
    ident.hits(5, 0.4)
    assert np.array_equal(np.asarray(plain.out), np.asarray(ident.out))


# ── reactivity ─────────────────────────────────────────────────────────────

def test_reactivity_scales_the_hit_pulse_linearly():
    full, _rest = _peak_over_rest(Rig(energy=1.0))
    assert full > 0.3
    pm.set_mod(VID, reactivity=0.5)
    half, rest_half = _peak_over_rest(Rig(energy=1.0))
    pm.set_mod(VID, reactivity=0.0)
    none, rest_none = _peak_over_rest(Rig(energy=1.0))
    assert none == pytest.approx(0.0, abs=1e-9)
    # the resting level is NOT reactivity: same glow at every setting
    assert rest_half == pytest.approx(_rest, abs=1e-6)
    assert rest_none == pytest.approx(_rest, abs=1e-6)
    # half reactivity lifts half as far (budget untouched at this spacing)
    assert half == pytest.approx(0.5 * full, rel=0.05)


def test_reactivity_scales_the_rainbow_hit_step_not_the_drift():
    pm.set_mod(VID, reactivity=0.5)
    r = Rig(gradient=RAINBOW, energy=1.0, rainbow_drift=0.0)
    r.settle(2.0)
    r.hits(4, 0.5)
    targets = [t for _a, t in r.e.steps]
    assert np.diff(targets) == pytest.approx([0.5 / 7] * 3, abs=1e-5)
    pm.set_mod(VID, reactivity=0.0)
    r0 = Rig(gradient=RAINBOW, energy=1.0, rainbow_drift=0.02)
    r0.settle(1.0)
    r0.hits(4, 0.5)
    # no hit moves it; only the slow per-bar drift does
    seconds = len(r0.levels) * DT
    assert r0.e._walk_target == pytest.approx(0.02 * seconds / 2.0, rel=1e-3)


def test_reactivity_leaves_the_flash_flare_and_the_drop_burst_alone():
    pm.set_mod(VID, reactivity=0.0)
    r = Rig(energy=0.5)
    r.settle(2.0)
    rest = r.levels[-1]
    r.e.update_config({"flash": 1.0})
    r.frame()
    assert r.levels[-1] - rest == pytest.approx(r.e._config["flash_size"], abs=0.02)
    r.settle(2.0)
    r.e.update_config({"phase": "drop", "phase_progress": 0.0})
    r.frame()
    assert r.levels[-1] == pytest.approx(r.e._config["drop_burst"], abs=1e-6)


# ── floor and ceiling ──────────────────────────────────────────────────────

def test_ceiling_caps_hits_flash_and_drop_and_floor_holds_a_lull():
    pm.set_mod(VID, floor=0.3, ceiling=0.6)
    r = Rig(energy=1.0)
    r.settle(2.0)
    r.hits(6, 0.4)
    r.e.update_config({"flash": 1.0})
    r.settle(0.5)
    r.e.update_config({"phase": "drop", "phase_progress": 0.0})
    r.settle(1.0)
    assert max(r.levels) <= 0.6 + 1e-9
    # a lull fades the light to black — the floor holds it at 0.3
    r.e.update_config({"phase": "lull", "phase_progress": 0.0})
    for i in range(1, 121):
        r.e._apply_config({"phase_progress": min(1.0, i / 100)},
                          validate=False, fire_event=False)
        r.frame(0.1)
    assert min(r.levels[-60:]) >= 0.3 - 1e-9
    assert r.levels[-1] == pytest.approx(0.3, abs=1e-6)
    # the output is the colour at the clamped level through the bulb curve
    g = r.e._config["gamma"]
    assert r.out[-1][0] == pytest.approx(255.0 * 0.3 ** g, abs=1e-6)


def test_crossed_floor_and_ceiling_the_ceiling_wins():
    pm.set_mod(VID, floor=0.8, ceiling=0.4)
    r = Rig(energy=0.0)
    r.settle(2.0)
    r.hits(3, 0.5)
    assert max(r.levels[-60:]) <= 0.4 + 1e-9
