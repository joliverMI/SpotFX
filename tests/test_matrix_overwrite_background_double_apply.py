"""Regression coverage for the Matrix + overwrite double-background-apply
bug (pixel-brightness-chain report, §3/§9), on the REAL render pipeline
(`fx.headless`, a dummy device, no network, no live storage).

`fx/effects/twod.py`'s `Twod.render()` used to pre-fill the whole 2D
canvas with the background colour BEFORE `draw()` runs, whenever
`background_mode` is "overwrite" — so an effect whose own `draw()` paints
onto that canvas rather than replacing it wholesale left an unlit pixel
already equal to `self._bg_color` by the time `get_pixels()` ran. The base
`Effect.get_pixels()`'s own overwrite blend then ran a second time on top
of that, computing `effect_alpha` from the ALREADY-BACKGROUND pixel value
(not 0) and adding another `(1 - effect_alpha)` share of the background —
`v*(2 - v/255)` instead of `v`. Measured on the real pipeline in the
report: `#000080` at `background_brightness=0.4` (`_bg_color = (0, 0,
51.2)`) landed at `(0, 0, 92)`, not `(0, 0, 51.2)`.

THE FIX IS NOT "skip get_pixels()'s blend for 2D effects" — an earlier
draft did exactly that and broke every Matrix effect (Squiggles among
them, see tests/test_squiggles_colorset_widen.py) whose own `draw()`
rebuilds `self.matrix` from a fresh zeroed buffer rather than painting
onto the pre-filled canvas: for those, get_pixels()'s blend was the ONLY
place the background was ever applied, and skipping it left them with no
background at all. The real fix removes the special-cased PRE-FILL in
`Twod.render()` instead — the canvas now always starts black, in every
`background_mode`, exactly like the 1D path (which never pre-fills
either) — so `get_pixels()`'s existing single-application blend is the
ONE place a 2D effect's background ever lands, uniformly, regardless of
whether its own `draw()` paints over the canvas or replaces it.

A direct `singleColor` (1D) probe, and a minimal test-only `Twod`
subclass whose `draw()` is a no-op (so its canvas is pure, untouched
background — the "flat_probe" shape the report's own probe used), both
through the real `fx.headless` pipeline.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest
import voluptuous as vol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects.twod import Twod

VID = headless.DEFAULT_VIRTUAL_ID


class FlatProbe(Twod):
    """A no-op 2D effect: draw() never touches the canvas, so whatever
    get_pixels() receives is exactly what render() left there — a direct
    instrument for the pre-fill-vs-blend interaction, the same shape the
    report's own probe script used."""
    NAME = "Flat Probe"
    CONFIG_SCHEMA = vol.Schema({})

    def draw(self):
        pass


def _run(coro):
    return asyncio.run(coro)


def _render_last_frame(tmp_path, sub, effect_type, config, n_frames=5):
    async def main():
        host = await headless.start_headless_host(str(tmp_path / sub))
        virtual = host.virtuals.get(VID)
        try:
            with headless.fake_clock() as clock:
                headless.attach_effect(host, virtual, effect_type, config)
                frames = headless.render_frames(virtual, n_frames, clock=clock,
                                                dt=1 / 60)
        finally:
            await host.shutdown()
        return frames[-1]
    return _run(main())


# the exact report numbers: #000080 @ background_brightness 0.4
OVERWRITE_BG = {"background_color": "#000080", "background_brightness": 0.4,
                "background_mode": "overwrite"}
ADDITIVE_BG = {"background_color": "#000080", "background_brightness": 0.4,
              "background_mode": "additive"}
DOUBLED_BLUE = 51.2 * (2 - 51.2 / 255.0)   # ~92.12, the pre-fix value


def test_2d_overwrite_background_applies_once_not_twice(tmp_path):
    frame = _render_last_frame(tmp_path, "2d-overwrite", "test_matrix_overwrite_background_double_apply", OVERWRITE_BG)
    blue = frame[:, 2]
    # every pixel is pure background (draw() drew nothing)
    assert np.allclose(frame[:, 0], 0) and np.allclose(frame[:, 1], 0)
    assert int(round(float(blue.mean()))) == 51
    assert not np.any(np.isclose(blue, DOUBLED_BLUE, atol=1.0))


def test_2d_additive_background_is_unaffected_by_the_fix(tmp_path):
    """additive mode never pre-filled either way — byte-identical before
    and after this fix."""
    frame = _render_last_frame(tmp_path, "2d-additive", "test_matrix_overwrite_background_double_apply", ADDITIVE_BG)
    blue = frame[:, 2]
    assert int(round(float(blue.mean()))) == 51


def test_1d_overwrite_background_matches_the_2d_result(tmp_path):
    """The 1D path never pre-filled and was never doubled — single
    overwrite application matches the fixed 2D result exactly."""
    frame = _render_last_frame(tmp_path, "1d-overwrite", "singleColor",
                               {"color": "#000000", **OVERWRITE_BG})
    blue = frame[:, 2]
    assert int(round(float(blue.mean()))) == 51


def test_squiggles_still_receives_its_background_via_get_pixels(tmp_path):
    """Squiggles discards Twod's canvas entirely in its own draw() (a
    fresh np.zeros buffer), so it never saw the pre-fill either way — its
    background has always come from get_pixels()'s single application
    alone, and removing the pre-fill must not take that away. See
    tests/test_squiggles_colorset_widen.py for the full flood proof; this
    is the narrow "still gets a background at all" check."""
    frame = _render_last_frame(
        tmp_path, "squiggles-bg", "squiggles",
        {"gradient": "linear-gradient(90deg, #ff0000 0%, #ff8f00 100%)",
         "spawn_rate": 0.0, "max_blobs": 2, **OVERWRITE_BG},
        n_frames=3)
    blue = frame[:, 2]
    # background-only region (no chains spawned): reaches ~51, not 0
    assert blue.max() > 40
