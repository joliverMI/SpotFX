"""Squiggles' colour-set accept list widened (owner ask, 2026-08-19: "widen
what squiggles accepts") — the WHY, established from the effect, and the
fix, proven at the render-pipeline level, not asserted from metadata.

WHY the 7-set restriction existed: `fx/effects/squiggles.py::draw()` paints
thin, sparse chains onto a frame that starts as `np.zeros(...)` every frame
— normal operation leaves the vast majority of pixels unlit. The base
render pipeline (`fx/effects/__init__.py::get_pixels()`) composites the
effect's configured `background_color` onto every "dark" pixel whenever
`bg_color_use` is true, so a colour set authoring a bright `bg_color` (the
`Mid - *` family) floods nearly the whole frame — proof 1 below measures
this directly. The seven previously-accepted "Orbit - *" sets all share
`bg_color=#000000`, the one shape that never triggers the flood.

THE ORIGINAL FIX (PR 137) removed the constraint at its source instead of
growing the allowlist: `config/effect_params.json` marked squiggles
`no_background_color: true`, the same registry flag `radial`/`pacman`
carry, blocking every colour-set-driven write path from ever writing a
background onto Squiggles. **That flag is now REMOVED (his ruling,
2026-08-19, PR fm/spectra-squiggles-restore-backgrounds): "keep the
backgrounds, i want to control them with overrides."** He is choosing to
manage the flood himself with colour-group overrides (§10, §86's
group-override-overlay fix — now landed and proven reaching his real
fixtures) rather than have the capability removed outright. Proof 1 still
holds (the flood is real, unmediated by the flag) — proof 2 below now
confirms the OPPOSITE of before: `bg_color_blocked("squiggles")` is
`False` and `compile_scene` DOES write `background_color` for Squiggles
again, same as any other colour-driven effect. Proof 3 (the widened
accept list itself, from `scripts/widen_squiggles_colorset_accept.py`) is
untouched by this reversal and still holds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, headless

VID = headless.DEFAULT_VIRTUAL_ID


def _categories_fixture(tmp_path) -> None:
    """Registers VID as an imported virtual so device_model.resolve_scope
    (used by compile_scene's colour-set entry lookup) can match it —
    mirrors tests/test_spectra_engine.py's own helper."""
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
              "virtuals": [VID], "effects": ["squiggles"], "role": None}}))

ORBIT_BG = {"background_color": "#000000", "background_brightness": 1.0,
           "background_mode": "overwrite"}
MID_BG = {"background_color": "#ff0000", "background_brightness": 0.5,
         "background_mode": "overwrite"}
SQUIGGLES_BASE = {
    "gradient": "linear-gradient(90deg, #ff0000 0%, #ff8f00 75%, #ff0000 100%)",
    "spawn_rate": 6.0,
    "max_blobs": 14,
}


def _render_last_frame(host, virtual, config, n_frames=90):
    with headless.fake_clock() as clock:
        headless.attach_effect(host, virtual, "squiggles", config)
        frames = headless.render_frames(virtual, n_frames, clock=clock, dt=1 / 60)
    virtual._active_effect = None
    return frames[-1]


def _frac_bright(frame, threshold=80):
    """Fraction of pixels visibly bright on ANY channel — the flood metric."""
    return float((frame.max(axis=1) > threshold).mean())


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ── proof 1: the restriction was real — a bright bg genuinely floods ────────

def test_bright_background_floods_squiggles_on_the_real_pipeline(tmp_path):
    """Renders the real vendored squiggles effect (no live storage/hardware
    touched) with the "Orbit" black-bg pattern vs the "Mid" bright-bg
    pattern, background_color WRITTEN as scene_compiler would write it
    pre-fix (bg_color_blocked not yet consulted). Confirms the leading
    hypothesis from the effect's own output, not from set metadata."""
    async def main():
        host = await headless.start_headless_host(str(tmp_path / "flood"))
        virtual = host.virtuals.get(VID)
        try:
            orbit_frame = _render_last_frame(
                host, virtual, {**SQUIGGLES_BASE, **ORBIT_BG})
            mid_frame = _render_last_frame(
                host, virtual, {**SQUIGGLES_BASE, **MID_BG})
        finally:
            await host.shutdown()
        orbit_frac = _frac_bright(orbit_frame)
        mid_frac = _frac_bright(mid_frame)
        # normal squiggles: a small fraction of the frame lit (sparse chains)
        assert orbit_frac < 0.15, orbit_frac
        # a bright authored background floods essentially the whole frame
        assert mid_frac > 0.95, mid_frac
        assert mid_frac > orbit_frac * 5

    _run(main())


# ── proof 2: the flag is gone — squiggles writes backgrounds again ──────────

def test_bg_color_blocked_no_longer_applies_to_squiggles():
    # radial/pacman are untouched by his ruling and still carry the flag.
    assert device_model.bg_color_blocked("squiggles") is False
    assert device_model.bg_color_blocked("radial") is True
    assert device_model.bg_color_blocked("pacman") is True
    # a dense particle effect was never blocked either
    assert device_model.bg_color_blocked("blackhole") is False


def test_compile_scene_writes_background_for_squiggles_again(tmp_path):
    from spectra.models.scene import SceneColorAssignment, SceneDeviceConfig, SceneV2
    from spectra.services import scene_compiler
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Squiggles test", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="squiggles",
        params=dict(SQUIGGLES_BASE), color=SceneColorAssignment(mode="set"))])

    mid_card = ColorSetCard(id="mid-fire", name="Mid - Fire", entries=[
        ColorSetEntry(scope=SetScope(virtual_ids=[VID]),
                      color_value="linear-gradient(90deg, #ff0000 0%, #ff8f00 75%)",
                      bg_color="#ff0000", bg_mode="overwrite",
                      background_brightness=0.5)])
    orbit_card = ColorSetCard(id="orbit-red", name="Orbit - Red", entries=[
        ColorSetEntry(scope=SetScope(virtual_ids=[VID]),
                      color_value="linear-gradient(90deg, #ff0000 0%, #ffbf00 100%)",
                      bg_color="#000000", bg_mode="overwrite",
                      background_brightness=1.0)])

    for card in (mid_card, orbit_card):
        writes = scene_compiler.compile_scene(scene, color_set=card)
        assert len(writes) == 1, card.name
        config = writes[0]["config"]
        # the gradient still rides the fired set's own foreground colour...
        assert config["gradient"] == card.entries[0].color_value, card.name
        # ...and background_color is written again, matching the fired set's
        # own authored value — his ruling: he controls this with overrides.
        assert config["background_color"] == card.entries[0].bg_color, (
            card.name, config)


# ── proof 3: the widened accept list genuinely admits a Mid-family set ──────

def test_squiggles_accepts_mid_family_set_once_widened():
    from spectra.models.scene import SceneV2
    from spectra.services.color_sets import ColorSetCard

    mid_card = ColorSetCard(id="mid-fire", name="Mid - Fire", entries=[])
    orbit_ids = ["35d31a19-851b-5ece-8a36-73abd80f3c1a",
                "7dc5af44-8403-56fa-bc97-6f9f2f3304f7"]

    narrow = SceneV2(name="Squiggles V2", accept_all_sets=False,
                     accepted_set_ids=orbit_ids)
    assert narrow.accepts_color_set(mid_card) is False

    widened = SceneV2(name="Squiggles V2", accept_all_sets=True,
                      accepted_set_ids=[])
    assert widened.accepts_color_set(mid_card) is True


# ── proof 4: a Mid background genuinely floods again, as his own ────────────
# ── override control now expects to be needed for ───────────────────────────

def test_mid_family_gradient_floods_again_now_the_flag_is_removed(tmp_path):
    """He is choosing to manage the flood himself with colour-group
    overrides (§10/§86) rather than have Squiggles' background writes
    suppressed. Confirms the flood he's now controlling is real, not
    already-neutralized by leftover config — a bright authored bg_color
    washes Squiggles exactly like proof 1 showed pre-fix."""
    async def main():
        host = await headless.start_headless_host(str(tmp_path / "flood-again"))
        virtual = host.virtuals.get(VID)
        try:
            orbit_frame = _render_last_frame(
                host, virtual, {**SQUIGGLES_BASE, **ORBIT_BG})
            mid_frame = _render_last_frame(
                host, virtual, {**SQUIGGLES_BASE, **MID_BG})
        finally:
            await host.shutdown()
        orbit_frac = _frac_bright(orbit_frame)
        mid_frac = _frac_bright(mid_frame)
        assert orbit_frac < 0.15, orbit_frac
        assert mid_frac > 0.95, mid_frac
        # something actually drew (not a silent all-black failure)
        assert float(np.abs(mid_frame).sum()) > 0

    _run(main())
