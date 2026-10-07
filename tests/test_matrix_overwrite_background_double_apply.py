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

A RESIDUAL CASE of the exact same doubling survived the render()-pre-fill
fix above: `blackhole.py`'s event-horizon disc (`out[inside] = ...`) and
`eye.py`'s eyelid-covered region (`out[covered] = ...`) each explicitly
painted the LITERAL `_bg_color` value into part of their own canvas —
so for those pixels `self.pixels` entering `get_pixels()` was already
non-black, and the single overwrite blend added another share of
background on top of it, same `v*(2 - v/255)` doubling, confined to the
disc/eyelid region. Fixed the same way Squiggles already relied on:
those regions now paint BLACK, letting `get_pixels()` supply the
background exactly once. `test_blackhole_disc_*`/`test_eye_eyelid_*`
below prove it on the real pipeline.

A THIRD sibling, `radial.py`, has a genuinely different shape: its own
`draw()` always pastes a FULL, freshly-computed image over the whole
matrix every frame (never leaving anything for Twod's pre-fill or
get_pixels() to fill in) — but during a lull-implode/drop-bloom warp or a
crossfade handoff, that image itself already blends in `self._bg_color`
scaled by its own `bg_alpha` (0..1, the warp's own fade) wherever the
pattern doesn't cover (`edge < 1`). `get_pixels()` has no notion of
`bg_alpha` — additive mode adds the FULL, unscaled `_bg_color` to every
pixel unconditionally, and overwrite mode adds a full share wherever the
pixel is dark — so it was adding a second, un-scaled copy of the
background on top of radial's own already-complete, already-correctly-
faded pixel, overshooting well past a flat double at partial `bg_alpha`
(additive: `bg*(1+bg_alpha)`; at `bg_alpha=0.5` that is 1.5x, not 2x, but
still wrong). Because the warp's own background contribution is a
PER-PIXEL, EDGE-SHAPED value (not the single scalar `self._bg_color`
`get_pixels()` can apply), it can't be expressed as "let get_pixels()
apply it once" the way the disc/lid fix above does — radial's own
already-blended array IS the complete, final pixel for that frame, so
the fix is to stop `get_pixels()` from touching it at all for that frame
(`self.bg_color_use = False`, the same per-effect override `pulse.py`
already uses to opt a whole effect out of the background layer, here
scoped to just the frames where `draw()` has already supplied one).
`test_radial_warp_background_*` below proves it on the real pipeline,
at a partial `bg_alpha` (not just the pre-fix formula's one flat-double
case the disc/lid residual above hits).

The `bg_color_use = False` override above is only correct if something
also puts it back once the warp ends — `self.bg_color_use` is normally
refreshed every frame by the base class's own `_advance_bg_fade()`, but
that call is a complete no-op once the background colour has settled
(the common case: no fade in progress), so a radial instance that had
EVER run a warp frame stayed permanently background-less afterward, on
every later ordinary frame, until an unrelated config write happened to
touch `background_color`/`background_brightness` again. Fixed by having
`draw()` call `self._refresh_bg_render_state()` itself, unconditionally,
every frame, before the warp logic runs — the warp branch's own override
still applies on top of that for the one frame it's active.
`test_radial_background_recovers_after_a_warp_ends` below renders a warp
frame followed by several ordinary ones and proves both `bg_color_use`
and the rendered background return to normal.
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


def _render_with_effect(tmp_path, sub, effect_type, config, n_frames=5,
                         setup=None, rng_seed=None):
    """Like _render_last_frame, but also returns the live effect instance
    (so a caller can read its own geometry, e.g. grid_r) and runs an
    optional `setup(effect)` hook right after attach, before any frame is
    rendered — the seam that lets a test force a specific phase/lid state
    the way tests/test_blackhole_horizon_color.py already does."""
    async def main():
        host = await headless.start_headless_host(str(tmp_path / sub))
        virtual = host.virtuals.get(VID)
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, effect_type, config
                )
                if rng_seed is not None:
                    effect._rng = np.random.default_rng(rng_seed)
                if setup is not None:
                    setup(effect)
                frames = headless.render_frames(virtual, n_frames, clock=clock,
                                                dt=1 / 60)
        finally:
            await host.shutdown()
        return effect, frames[-1]
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


# ── Residual case: blackhole/eye painting _bg_color directly ────────────────

def test_blackhole_disc_region_applies_background_once_not_twice(tmp_path):
    """No particles spawned (spawn_rate=0) and no charge/lull/drop phase, so
    the only thing blackhole's own draw() paints is its event-horizon disc
    (col is None, horizon_on True by default via horizon_scale>0) — every
    disc-interior pixel should be exactly the single-applied background,
    never the doubled v*(2 - v/255) value."""
    effect, frame = _render_with_effect(
        tmp_path, "blackhole-disc", "blackhole",
        {"spawn_rate": 0.0, "reverse": False, **OVERWRITE_BG},
        n_frames=3,
    )
    rh = effect._horizon_radius()
    inside = (effect.grid_r < (effect._disc_radius(rh) - 0.01)).reshape(-1)
    assert inside.any(), "test config produced no disc interior to probe"

    inside_pixels = frame[inside]
    blue = inside_pixels[:, 2]
    assert np.allclose(inside_pixels[:, 0], 0) and np.allclose(
        inside_pixels[:, 1], 0
    )
    assert int(round(float(blue.mean()))) == 51
    assert not np.any(np.isclose(blue, DOUBLED_BLUE, atol=1.0))


def test_blackhole_disc_covers_trail_once_while_trail_still_visible_outside(tmp_path):
    """A fuller scene: real particles fall and leave a trail. The disc must
    still paint exactly single-applied background over its own interior
    (covering the trail there, per its own docstring) — never doubled —
    while pixels OUTSIDE the disc keep showing real, non-background trail
    colour, proving the fix only changed the disc's own colour, not the
    effect's other rendering."""
    config = dict(
        OVERWRITE_BG, reverse=False, horizon_scale=0.25, spawn_rate=40.0,
        color_mode="wheel", base_speed=2.0, edge_speed=1.0,
        gradient_spin=0.0,
    )
    effect, frame = _render_with_effect(
        tmp_path, "blackhole-trail", "blackhole", config,
        n_frames=40, rng_seed=1234,
    )
    rh = effect._horizon_radius()
    inside = (effect.grid_r < (effect._disc_radius(rh) - 0.01)).reshape(-1)
    assert inside.any(), "test config produced no disc interior to probe"

    inside_blue = frame[inside, 2]
    assert np.allclose(inside_blue, 51.2, atol=1.0), (
        "disc interior is not pure, single-applied background"
    )
    assert not np.any(np.isclose(inside_blue, DOUBLED_BLUE, atol=1.0))

    outside = frame[~inside]
    non_bg_outside = outside[np.abs(outside[:, 2] - 51.2) > 1.0]
    assert len(non_bg_outside) > 0, (
        "no trail pixel survived outside the disc — the fix must not "
        "suppress the effect's own trail rendering"
    )


def test_eye_eyelid_covered_region_applies_background_once_not_twice(tmp_path):
    """A fully-closed eyelid (lull phase at progress 1.0) paints its
    covered region directly; the panel's far top row sits well clear of
    both lid edges and their colour-fringe lines, so it must be exactly
    the single-applied background — never doubled."""
    def force_closed_lid(effect):
        effect._phase = "lull"
        effect.phase_progress = 1.0

    effect, frame = _render_with_effect(
        tmp_path, "eye-lid", "eye", dict(OVERWRITE_BG),
        n_frames=3, setup=force_closed_lid,
    )
    assert effect._lid > 0.99, "test setup failed to close the eyelid"
    grid = frame.reshape(effect.r_height, effect.r_width, 3)
    top_row = grid[0]
    assert np.allclose(top_row[:, 0], 0) and np.allclose(top_row[:, 1], 0)
    assert np.allclose(top_row[:, 2], 51.2, atol=1.0)
    assert not np.any(np.isclose(top_row[:, 2], DOUBLED_BLUE, atol=1.0))

    # the rest of the effect's own rendering (iris/pupil peeking through the
    # not-yet-fully-met lid gap, lid edge colour fringe) is untouched by
    # this fix — some non-background colour must still be visible.
    non_bg = frame[np.abs(frame[:, 2] - 51.2) > 1.0]
    assert len(non_bg) > 0, (
        "no non-background pixel survived — the fix must not suppress the "
        "eye's own iris/lid-edge rendering"
    )


# ── Third sibling: radial.py's warp/crossfade background fade ───────────────

class _FakeRadialSource:
    """Stands in for the real `radial-dummy` source virtual radial.py reads
    `assembled_frame` from — a plain object with that one attribute."""

    def __init__(self, n=64, rgb=(255.0, 0.0, 0.0)):
        self.assembled_frame = np.tile(
            np.array(rgb, dtype=np.float32), (n, 1)
        )


def _render_radial_warp(tmp_path, sub, config, *, phase, phase_progress,
                         pattern_rgb=(255.0, 0.0, 0.0), n_frames=1):
    """Attaches radial with a fake pattern source registered under its
    default `source_virtual` id, forces a charge/lull/drop phase directly
    (the tests/test_blackhole_horizon_color.py precedent for poking phase
    state without a full trigger-engine round trip), renders, and returns
    (effect, last_frame).

    `sub` must be UNIQUE per call and is used as BOTH the device id and
    the fake source's virtual id — `headless.DEFAULT_VIRTUAL_ID` is a
    fixed constant, and `particle_handoff`'s snapshot store is keyed by
    virtual id and lives for the whole test process (not reset per host),
    so reusing it lets an unrelated earlier test's incoming-bloom snapshot
    get silently adopted here (`test_blackhole_horizon_color.py`'s own
    docstring already names this hazard; it bit this exact test during
    authoring — `_adopt_handoff` picked up a stale `{"mode": "timed"}`
    reveal left by an earlier test on the shared default id, overriding
    the standalone lull/drop warp this test means to drive). A unique
    source-virtual id per call (`f"{sub}-source"`) sidesteps the same
    hazard for the fake source's own registry slot.

    The fake source is removed from the host's virtual registry before
    shutdown — it has none of a real Virtual's attributes, and
    FxHost.shutdown() iterates every registered virtual."""
    source_id = f"{sub}-source"
    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / sub), device_id=sub
        )
        virtual = host.virtuals.get(sub)
        host.virtuals._virtuals[source_id] = _FakeRadialSource(
            rgb=pattern_rgb
        )
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "radial",
                    dict(config, source_virtual=source_id),
                )
                effect._phase = phase
                effect.phase_progress = phase_progress
                frames = headless.render_frames(virtual, n_frames,
                                                clock=clock, dt=1 / 60)
        finally:
            host.virtuals._virtuals.pop(source_id, None)
            await host.shutdown()
        return effect, frames[-1]
    return _run(main())


def test_radial_warp_background_applies_once_not_twice(tmp_path):
    """Mid-lull (phase_progress=0.5, an ordinary standalone implode with no
    crossfade sibling involved) is a deterministic point on the ramp where
    the warp has opened a real "outside the pattern" region AND bg_alpha is
    a genuine fraction (neither 0 nor 1) — exactly the partial-alpha case
    the pre-fix formula overshot hardest (not a flat double: additive mode
    added the FULL background unconditionally on top of radial's own
    already bg_alpha-scaled copy, landing near bg*(1+bg_alpha) rather than
    bg*bg_alpha). The farthest panel corner (0, 0) sits outside the pattern
    at this progress in both modes."""
    for mode in ("additive", "overwrite"):
        config = dict(OVERWRITE_BG if mode == "overwrite" else ADDITIVE_BG,
                      reverse=False)
        effect, frame = _render_radial_warp(
            tmp_path, f"radial-warp-{mode}", config,
            phase="lull", phase_progress=0.5,
        )
        warp_and_alpha = effect._phase_warp()
        assert warp_and_alpha is not None
        _, bg_alpha = warp_and_alpha
        expected_blue = float(effect._bg_color[2]) * bg_alpha

        grid = frame.reshape(effect.r_height, effect.r_width, 3)
        corner = grid[0, 0]
        assert corner[0] == 0 and corner[1] == 0
        assert abs(float(corner[2]) - expected_blue) <= 1.0, (
            f"{mode}: corner pixel {corner[2]} does not match the single, "
            f"bg_alpha-scaled application ({expected_blue})"
        )
        # the pre-fix overshoot at this exact progress (measured against
        # the unfixed module): far above either the correct value or even
        # a flat double of it — a real regression would land near there,
        # not within 1.0 of the correct value asserted above.
        assert float(corner[2]) < expected_blue * 1.5 + 5.0


def test_radial_pattern_rendering_unaffected_during_warp(tmp_path):
    """The same mid-lull frame must still show the pattern essentially
    undimmed wherever the warp hasn't pushed it out of [0, 1] — the fix
    must not suppress radial's own rendering, only get_pixels()'s second
    application of the background on top of it."""
    effect, frame = _render_radial_warp(
        tmp_path, "radial-warp-pattern", dict(OVERWRITE_BG, reverse=False),
        phase="lull", phase_progress=0.5,
    )
    red = frame[:, 0]
    assert red.max() > 200, (
        "no near-full-strength pattern pixel survived the warp frame"
    )


def test_radial_ordinary_background_unaffected_by_the_fix(tmp_path):
    """With no charge/lull/drop phase and no crossfade (warp stays None
    all frame), draw() never touches bg_color_use — ordinary background
    behaviour (get_pixels()'s single application) must be exactly as
    before this fix. A BLACK pattern source (rather than the other two
    tests' saturated red) so overwrite mode's "fills dark areas" blend
    also lands on the expected pure-background value, matching this
    file's other background-only sanity checks."""
    for mode in ("additive", "overwrite"):
        config = dict(OVERWRITE_BG if mode == "overwrite" else ADDITIVE_BG,
                      reverse=False)
        effect, frame = _render_radial_warp(
            tmp_path, f"radial-ordinary-{mode}", config,
            phase="none", phase_progress=0.0, pattern_rgb=(0.0, 0.0, 0.0),
        )
        assert effect.bg_color_use is True
        blue = frame[:, 2]
        assert int(round(float(blue.mean()))) == 51


def test_radial_background_recovers_after_a_warp_ends(tmp_path):
    """`self.bg_color_use = False` (set by the warp branch for the one
    frame it's active) is only correct if something puts it back once the
    warp ends. `_advance_bg_fade()` — the base class's own per-frame
    refresh — is a no-op once the background colour has settled (the
    common case, no fade in progress), so without draw() restoring it
    itself an instance that ever ran a single warp frame would stay
    background-less on every later ORDINARY frame. This renders one
    mid-lull warp frame, then switches the SAME effect instance back to
    phase="none" for several more frames, and proves both bg_color_use
    and the rendered background recover — the sequence the other
    "ordinary" test above (a fresh, never-warped instance) does not
    exercise."""
    async def main():
        sub = "radial-recovers"
        source_id = f"{sub}-source"
        host = await headless.start_headless_host(
            str(tmp_path / sub), device_id=sub
        )
        virtual = host.virtuals.get(sub)
        host.virtuals._virtuals[source_id] = _FakeRadialSource(
            rgb=(0.0, 0.0, 0.0)
        )
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "radial",
                    dict(OVERWRITE_BG, reverse=False,
                         source_virtual=source_id),
                )
                effect._phase = "lull"
                effect.phase_progress = 0.5
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect.bg_color_use is False, (
                    "warp frame did not set bg_color_use False as expected"
                )

                effect._phase = "none"
                effect.phase_progress = 0.0
                frames = headless.render_frames(virtual, 5, clock=clock,
                                                dt=1 / 60)
        finally:
            host.virtuals._virtuals.pop(source_id, None)
            await host.shutdown()
        return effect, frames[-1]

    effect, frame = _run(main())
    assert effect.bg_color_use is True, (
        "bg_color_use stayed False after the warp ended — the background "
        "is permanently suppressed on every later ordinary frame"
    )
    blue = frame[:, 2]
    assert int(round(float(blue.mean()))) == 51
