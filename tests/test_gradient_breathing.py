"""THE BREATH KEEPS ITS PHASE THROUGH A GLIDE (fx/VENDOR.md #49).

House lighting's porch rail and dining table breathe with the vendored
`gradient` effect (modulate + "sine"). Effect._apply_config runs every
base's config_updated on every write AND on every frame of a numeric or
colour param tween, and ModulateEffect.config_updated used to reset the
breathing counter — so the breath froze at one level for as long as any
glide ran (a house mode's 90 s clock change, a colour landing, the motion
hook). These drive the REAL effect class through the same lock-free
_apply_config path _advance_tweens uses per frame.
"""
from __future__ import annotations

import numpy as np


def _breath(config: dict, frames: int, *, tween=True, swap_effect_at=None):
    from fx.effects.gradient import TemporalGradientEffect
    e = TemporalGradientEffect(None, config)
    e.pixels = np.zeros((1, 3))          # a one-pixel fixture (the porch rail)
    out = []
    for i in range(frames):
        if tween:
            # One frame of a numeric glide, exactly as _advance_tweens lands it.
            e._apply_config({"brightness": 1.0 - i * 0.001}, validate=False,
                            fire_event=False)
        if swap_effect_at is not None and i == swap_effect_at:
            e._apply_config({"modulation_effect": "breath"}, validate=False,
                            fire_event=False)
        e.effect_loop()
        out.append(float(e.pixels[0][0]))
    return out


CFG = {"modulate": True, "modulation_effect": "sine", "modulation_speed": 1.0,
       "gradient": "#ff0000"}


def test_the_breath_runs_its_full_range_while_a_glide_runs():
    vals = _breath(CFG, 300)
    # sine modulation spans 10%..70% of the colour (0.3*sin + 0.4).
    assert min(vals) < 0.15 * 255 and max(vals) > 0.65 * 255, (min(vals), max(vals))


def test_the_harness_goes_red_on_the_old_reset(monkeypatch):
    """The pre-fix behaviour, restored for this test only: reset on every
    config update. The same drive then sits at ONE level — the defect."""
    from fx.effects import modulate

    def old_config_updated(self, config):
        self._counter = 0
        self._breath_cycle = np.linspace(0, 9, 9 * modulate._rate)

    monkeypatch.setattr(modulate.ModulateEffect, "config_updated", old_config_updated)
    vals = _breath(CFG, 300)
    assert max(vals) - min(vals) < 1.0, "the old reset freezes the breath during a glide"


def test_without_a_glide_the_breath_is_byte_identical_to_before(monkeypatch):
    """No config update in flight = exactly the fork's own breath."""
    new = _breath(CFG, 400, tween=False)
    from fx.effects import modulate
    fixed = modulate.ModulateEffect.config_updated

    def old_config_updated(self, config):
        fixed(self, config)
        self._counter = 0

    monkeypatch.setattr(modulate.ModulateEffect, "config_updated", old_config_updated)
    assert _breath(CFG, 400, tween=False) == new


def test_changing_the_animation_still_restarts_the_counter():
    """sine counts radians, breath counts table steps: switching must reset."""
    from fx.effects.gradient import TemporalGradientEffect
    e = TemporalGradientEffect(None, CFG)
    e.pixels = np.zeros((1, 3))
    for _ in range(50):
        e.effect_loop()
    assert e._counter > 0
    e._apply_config({"modulation_effect": "breath"}, validate=False, fire_event=False)
    assert e._counter == 0 and e._counter_mode == "breath"
