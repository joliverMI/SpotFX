"""Regression coverage for the Matrix + overwrite double-background-apply
bug (pixel-brightness-chain report, §3/§9).

`fx/effects/twod.py`'s `Twod.render()` pre-fills the whole 2D canvas with
the background colour BEFORE `draw()` runs, whenever `background_mode` is
"overwrite" — so an unlit (background-only) pixel's own `self.pixels`
already equals `self._bg_color` by the time `get_pixels()` runs. The base
`Effect.get_pixels()`'s own overwrite blend used to run again on top of
that, computing `effect_alpha` from the ALREADY-BACKGROUND pixel value (not
0, since the pixel isn't black) and adding another `(1 - effect_alpha)`
share of the background — `v*(2 - v/255)` instead of `v`. Measured on the
real pipeline in the report: `#000080` at `background_brightness=0.4`
(`_bg_color = (0, 0, 51.2)`) landed at `(0, 0, 92)`, not `(0, 0, 51.2)`.

Fixed by `BG_PREFILLED_ON_OVERWRITE` (fx/effects/__init__.py): a class flag,
False on the base `Effect`, True on `Twod`, that `get_pixels()`'s overwrite
branch checks before blending a second time. The 1D path (no pre-fill, so
`self.pixels` is still the EFFECT's own drawn value, 0 for an unlit pixel)
is unaffected and keeps its single application.
"""
from __future__ import annotations

import threading
from contextlib import nullcontext

import numpy as np

from fx.effects import Effect
from fx.effects.twod import Twod


class _FakeEffect:
    """Carries exactly the attributes `Effect.get_pixels()` reads, so the
    real method can be called directly against pixels shaped the way each
    path (1D vs. 2D-prefilled) actually produces them — no registry, no
    audio, no render thread."""

    def __init__(self, pixels, *, bg_color, background_mode="overwrite",
                brightness=1.0):
        self.lock = nullcontext()
        self.pixels = np.array(pixels, dtype=float)
        self.flip = False
        self.mirror = False
        self.bg_color_use = True
        self.background_mode = background_mode
        self._bg_color = np.array(bg_color, dtype=float)
        self.brightness = brightness
        self._config = {"blur": 0.0}


class _Fake1D(_FakeEffect):
    BG_PREFILLED_ON_OVERWRITE = False


class _Fake2D(_FakeEffect):
    BG_PREFILLED_ON_OVERWRITE = True


def test_class_flag_defaults_and_twod_override():
    assert Effect.BG_PREFILLED_ON_OVERWRITE is False
    assert Twod.BG_PREFILLED_ON_OVERWRITE is True


def test_2d_overwrite_background_applies_once_not_twice():
    """The exact report numbers: #000080 @ background_brightness 0.4 ->
    _bg_color (0, 0, 51.2). A 2D effect's pre-filled unlit pixel (already
    equal to _bg_color, matching Twod.render()'s own pre-fill) must land
    at that value unchanged — never doubled to ~92."""
    bg_color = (0.0, 0.0, 51.2)
    # The pre-filled canvas: an unlit pixel already carries the background,
    # exactly as fx/effects/twod.py's render() leaves it before draw().
    prefilled_pixel = [list(bg_color)]
    fake = _Fake2D(prefilled_pixel, bg_color=bg_color)

    result = Effect.get_pixels(fake)

    assert result is not None
    np.testing.assert_allclose(result[0], bg_color, atol=1e-6)
    # Specifically: must NOT land near the pre-fix doubled value.
    doubled = bg_color[2] * (2 - bg_color[2] / 255.0)
    assert not np.isclose(result[0][2], doubled, atol=1.0)
    assert int(result[0][2]) == 51


def test_1d_overwrite_background_still_applies_once_unlit():
    """The 1D path never pre-fills — an unlit pixel's own drawn value is
    0, and get_pixels() is the ONLY place the background lands. Must be
    byte-identical to before this fix (single application)."""
    bg_color = (0.0, 0.0, 51.2)
    unlit_pixel = [[0.0, 0.0, 0.0]]
    fake = _Fake1D(unlit_pixel, bg_color=bg_color)

    result = Effect.get_pixels(fake)

    np.testing.assert_allclose(result[0], bg_color, atol=1e-6)


def test_2d_overwrite_foreground_pixel_unaffected():
    """A fully-lit foreground pixel reads the same with or without the
    fix: effect_alpha was already ~1, so the (now-skipped) blend would
    have added ~nothing anyway."""
    bg_color = (0.0, 0.0, 51.2)
    foreground_pixel = [[255.0, 120.0, 0.0]]
    fake = _Fake2D(foreground_pixel, bg_color=bg_color)

    result = Effect.get_pixels(fake)

    np.testing.assert_allclose(result[0], foreground_pixel[0], atol=1e-6)


def test_2d_additive_mode_is_unaffected_by_the_flag():
    """BG_PREFILLED_ON_OVERWRITE only gates the "overwrite" branch — a 2D
    additive-mode effect starts its canvas BLACK (fx/effects/twod.py's own
    render() only pre-fills for "overwrite"), so it still needs the single
    additive application in get_pixels(), same as before this fix."""
    bg_color = (0.0, 0.0, 51.2)
    unlit_pixel = [[0.0, 0.0, 0.0]]
    fake = _Fake2D(unlit_pixel, bg_color=bg_color, background_mode="additive")

    result = Effect.get_pixels(fake)

    np.testing.assert_allclose(result[0], bg_color, atol=1e-6)
