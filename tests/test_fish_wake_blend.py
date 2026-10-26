"""THE WAKE'S COLOUR AND BLEND (fx/effects/fish.py's WAKE COLOUR block):
his 2026-10-26 report — "the fish scene gains a lot of white color,
especially in rainbow effects when there is a lot going on" — and his
answer to the plan, "I approve option A for the wake": the wake in the
fish's own colour (`wake_hue = own`), lightened onto the bodies
(`wake_blend = lighten`), the old look one setting away.

The measured proof is scripts/check_fish_wake_blend.py: two arcs of his real
audio on his crystal's real cells (a busy rainbow arc through a charge, a
lull, a drop, a big fish and a swim burst; a calm one), `opposite + add`
byte-identical to the pinned pre-change module, the plan's white-light bars
at the new defaults, the wake still visible, and the mix's cost. It runs as
a subprocess, like every fish check script here.

Pinned in-process below: the blend's own arithmetic, that every path
writing the matrix goes through it, the registry, and Sonic's reach.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import device_model, headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72


def test_the_measured_wake_blend_proof_passes():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_fish_wake_blend.py")],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
    )
    out = proc.stdout + proc.stderr
    if "cannot read" in out and "out of git" in out:
        pytest.skip(out.strip().splitlines()[-1])
    assert proc.returncode == 0, out[-4000:]
    assert "ALL WAKE BLEND CHECKS PASS" in proc.stdout, out[-4000:]
    # both arcs were actually compared against the pinned module
    assert proc.stdout.count("-> IDENTICAL") == 2, out[-4000:]


# ── the blend's own arithmetic, on one real effect ──────────────────────
async def _effect(tmp_path, tag, **cfg):
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, "fish", dict(cfg))
    clock.advance(DT)
    virtual.assemble_frame()        # one frame: do_once has run
    return host, cm, eff


def _mix(tmp_path, tag, blend, body, wake, big):
    """`_composite` on a black canvas; the matrix it leaves, as floats."""
    async def main():
        host, cm, eff = await _effect(tmp_path, tag, wake_blend=blend)
        try:
            eff.matrix = Image.new("RGB", (COLS, ROWS))
            eff._composite(body, wake, big)
            return np.asarray(eff.matrix, dtype=np.float32)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    return asyncio.run(main())


def _layers(seed=3):
    rng = np.random.default_rng(seed)
    shape = (ROWS, COLS, 3)
    body = (rng.random(shape) * 300.0).astype(np.float32)
    wake = (rng.random(shape) * 260.0).astype(np.float32)
    big = (rng.random(shape) * 120.0).astype(np.float32)
    return body, wake, big


def test_add_is_the_old_mix_operation_for_operation(tmp_path):
    body, wake, big = _layers()
    out = _mix(tmp_path, "mix-add", "add", body, wake, big)
    old = np.clip(np.zeros_like(body) + body + wake + big, 0, 255)
    assert np.array_equal(out, old.astype(np.uint8).astype(np.float32))


def test_lighten_is_the_brighter_of_the_fish_and_the_hue_clipped_water(
        tmp_path):
    body, wake, big = _layers()
    # one pixel each: a fish over its own-colour wake, and water too bright
    # to show as it is (its colour must survive the clip)
    body[5, 5], wake[5, 5], big[5, 5] = (200, 40, 0), (100, 20, 0), (0, 0, 0)
    body[6, 6], wake[6, 6], big[6, 6] = (0, 0, 0), (400, 200, 0), (110, 55, 0)
    out = _mix(tmp_path, "mix-lighten", "lighten", body, wake, big)
    water = wake + big
    peak = water.max(axis=2, keepdims=True)
    clipped = np.where(peak > 255.0, water * (255.0 / peak), water)
    want = np.clip(np.maximum(body, clipped), 0, 255)
    assert np.array_equal(out, want.astype(np.uint8).astype(np.float32))
    assert tuple(out[5, 5]) == (200, 40, 0), "the fish shows, never brighter"
    assert tuple(out[6, 6]) == (255, 127, 0), "the water keeps its colour"
    # no channel is ever brighter than the brighter layer
    assert (out <= np.maximum(np.minimum(body, 255), clipped) + 1e-3).all()


def test_under_hides_the_water_behind_a_lit_fish(tmp_path):
    body = np.zeros((ROWS, COLS, 3), np.float32)
    wake = np.zeros_like(body)
    wake[...] = (0, 100, 50)
    body[2, 2] = (255, 0, 0)        # a fully lit fish: no water behind it
    body[3, 3] = (127.5, 0, 0)      # a half-lit one: half the water
    out = _mix(tmp_path, "mix-under", "under", body, wake, None)
    assert tuple(out[2, 2]) == (255, 0, 0)
    assert tuple(out[3, 3]) == (127, 50, 25)
    assert tuple(out[9, 9]) == (0, 100, 50), "where no fish is, the water"


def test_with_no_water_every_blend_is_the_bodies(tmp_path):
    body, _, _ = _layers(seed=5)
    outs = [_mix(tmp_path, f"mix-dry-{b}", b, body, None, None)
            for b in FX.WAKE_BLENDS]
    for out in outs[1:]:
        assert np.array_equal(out, outs[0])


class _Audio:
    """What the fish reads from the audio source, real methods, a steady
    level under our own control."""
    def __init__(self):
        self.lows = 0.35
        self.beat = False

    def lows_power(self, filtered=True):
        return self.lows

    def bpm_beat_now(self):
        return self.beat


MUSIC_FISH = {
    "particle_count": 3, "horizon_scale": 0.3, "radius_scale": 1.8,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.5, "tether_scatter": 0,
    "reactivity_scale": 1, "speed_jump": 1, "speed_jog": 1,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "flap_amount": 0.45, "school_variation": 0.08, "roam_scale": 0.75,
    "reverse": False,
}


def _spy_composite(effect):
    """Shadow `effect._composite` with a wrapper that captures every
    (body, wake, big) it is handed while letting the real blend run —
    the same capture shape scripts/check_fish_wake_blend.py's own cost
    section uses."""
    orig = effect._composite
    calls = []

    def composite(body, wake, big):
        calls.append((
            np.asarray(body, dtype=np.float32).copy(),
            None if wake is None else np.asarray(wake, dtype=np.float32).copy(),
            None if big is None else np.asarray(big, dtype=np.float32).copy(),
        ))
        return orig(body, wake, big)

    effect._composite = composite
    return calls


def _expected_mix(body, wake, big, blend):
    """`_composite`'s own arithmetic, re-derived independently here (the
    same formulas test_add_is_the_old_mix_operation_for_operation/
    test_lighten_is_.../test_under_hides_... above already prove against
    synthetic layers) — against a canvas that is always black, because
    `Twod.render()` resets `self.matrix` before every `draw()` and none
    of the three call sites below ever paints onto it before `_composite`
    runs."""
    fish = body.astype(np.float32)
    if blend == "add":
        out = fish
        if wake is not None:
            out = out + wake
        if big is not None:
            out = out + big
        return np.clip(out, 0, 255).astype(np.uint8).astype(np.float32)
    water = None
    for layer in (wake, big):
        if layer is not None:
            water = layer if water is None else water + layer
    if water is None:
        out = fish
    else:
        peak = water.max(axis=2, keepdims=True)
        clipped = np.where(
            peak > 255.0, water * (255.0 / np.maximum(peak, 1e-6)), water
        )
        if blend == "lighten":
            out = np.maximum(fish, clipped)
        else:  # under
            fish = np.clip(fish, 0, 255)
            alpha = fish.max(axis=2, keepdims=True) / 255.0
            out = fish + clipped * (1.0 - alpha)
    return np.clip(out, 0, 255).astype(np.uint8).astype(np.float32)


def _assert_blend_matches(calls, blend, matrix):
    assert len(calls) == 1, calls
    body, wake, big = calls[0]
    expected = _expected_mix(body, wake, big, blend)
    actual = np.asarray(matrix, dtype=np.float32)
    assert np.array_equal(actual, expected)


async def _warmed_up_fish(tmp_path, tag, blend, frames=180):
    """A real fish, swum for `frames` real frames under a real audio
    signal, so its trail and wake carry genuine (not synthetic) data by
    the time a path is driven against it. A big-fish poke partway through
    (frame 100) means `big` is ALSO genuinely non-None by the time we
    capture — without it `_draw_collapse` (which never lays a wake) would
    composite with no water at all, where every `wake_blend` renders
    identically and a call site that silently ignored the setting would
    go undetected."""
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(
        host, virtual, "fish", dict(MUSIC_FISH, wake_blend=blend)
    )
    eff._rng = np.random.default_rng(11)
    audio = _Audio()
    for i in range(frames):
        audio.lows = 0.3 + 0.25 * ((i // 12) % 2)
        audio.beat = (i % 18 == 0)
        if i == 100:
            eff.update_config({"big_fish": 0.9})
        clock.advance(DT)
        eff.audio_data_updated(audio)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)
    return host, cm, virtual, clock, eff, audio


@pytest.mark.parametrize("blend", FX.WAKE_BLENDS)
def test_the_ordinary_draw_applies_the_configured_blend(tmp_path, blend):
    """draw()'s own last statement, `self._composite(body_out, self.wake,
    big)`, on a real swimming fish — not a synthetic layer, and not an
    AST walk over the source."""
    async def main():
        host, cm, virtual, clock, eff, audio = await _warmed_up_fish(
            tmp_path, f"draw-{blend}", blend
        )
        try:
            calls = _spy_composite(eff)
            audio.lows, audio.beat = 0.6, True
            clock.advance(DT)
            eff.audio_data_updated(audio)
            virtual.assemble_frame()
            _assert_blend_matches(calls, blend, eff.matrix)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(main())


@pytest.mark.parametrize("blend", FX.WAKE_BLENDS)
def test_the_held_transition_fade_only_applies_the_configured_blend(
        tmp_path, blend):
    """`_fade_only`'s own last statement — the held-transition path, with
    the exact precondition it always runs under in production (a matrix
    `Twod.render()` has just reset to black)."""
    async def main():
        host, cm, virtual, clock, eff, audio = await _warmed_up_fish(
            tmp_path, f"fade-{blend}", blend
        )
        try:
            eff.matrix = Image.new("RGB", (COLS, ROWS))
            calls = _spy_composite(eff)
            eff._fade_only(DT)
            _assert_blend_matches(calls, blend, eff.matrix)
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(main())


@pytest.mark.parametrize("blend", FX.WAKE_BLENDS)
def test_the_outgoing_collapse_toward_an_incoming_radial_applies_the_configured_blend(
        tmp_path, blend):
    """draw() dispatching to `_draw_collapse` for real — a genuine incoming
    Radial attached as `_active_effect` while our fish is
    `_transition_effect`, so `particle_handoff.incoming_sibling` reports
    it and `draw()`'s own collapse-latch logic takes the branch, exactly
    as it would in a live crossfade."""
    async def main():
        host, cm, virtual, clock, eff, audio = await _warmed_up_fish(
            tmp_path, f"collapse-{blend}", blend
        )
        try:
            headless.attach_effect(host, virtual, "radial", {})
            virtual._transition_effect = eff
            virtual._config["transition_mode"] = "Add"
            virtual.frame_transitions = virtual.transitions["Add"]
            virtual.transition_frame_total = int(
                round(virtual.refresh_rate * 0.5)
            )
            virtual.transition_frame_counter = 0

            calls = _spy_composite(eff)
            clock.advance(DT)
            eff.audio_data_updated(audio)
            virtual.assemble_frame()
            assert eff._collapse is not None, (
                "draw() did not take the collapse branch"
            )
            _assert_blend_matches(calls, blend, eff.matrix)
            assert calls[0][1] is None, "the collapse composites no wake"
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()
    asyncio.run(main())


# ── the defaults, the registry, Sonic ───────────────────────────────────
def test_the_defaults_are_his_option_a():
    schema = FX.Fish2d.schema()({})
    assert schema["wake_hue"] == "own"
    assert schema["wake_blend"] == "lighten"
    assert FX.WAKE_HUE_OFFSETS == {"own": 0.0, "neighbour": 0.125,
                                   "opposite": 0.5}


def test_the_two_settings_are_registered_for_the_editor_and_sonic():
    registry = json.loads((REPO / "config" / "effect_params.json").read_text())
    fish = registry["effects"]["fish"]
    schema = FX.Fish2d.schema()({})
    for key, options in (("wake_hue", list(FX.WAKE_HUE_OFFSETS)),
                         ("wake_blend", list(FX.WAKE_BLENDS))):
        meta = fish["params"][key]
        assert meta["type"] == "enum" and meta["options"] == options, key
        assert meta["default"] == schema[key] == fish["defaults"][key], key
        assert meta["help_topic"] == "fish-wake-colour", key


ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"
HELP_TOPIC_SCRIPT = REPO / "scripts" / "check_fish_wake_help_topic.mjs"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_the_help_topic_is_a_real_help_sections_entry():
    """`fish-wake-colour` must be a real id inside helpContent.ts's own
    HELP_SECTIONS tree, evaluated by transpiling the real module with
    esbuild (scripts/check_fish_wake_help_topic.mjs) — never a raw
    substring match over the file, which a commented-out or differently
    formatted id would still satisfy."""
    result = subprocess.run(
        ["node", str(HELP_TOPIC_SCRIPT)],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_fish_wake_help_topic.mjs failed:\n{result.stdout}\n"
        f"{result.stderr}"
    )
    assert "ALL OK" in result.stdout


def test_sonic_can_set_them_and_is_refused_a_made_up_one():
    from spectra.services import scene_console
    meta = device_model.effect_params("fish")
    assert scene_console._validate_param_value(
        "wake_hue", meta["wake_hue"], "neighbour") == "neighbour"
    assert scene_console._validate_param_value(
        "wake_blend", meta["wake_blend"], "add") == "add"
    with pytest.raises(scene_console.SceneOpError):
        scene_console._validate_param_value(
            "wake_hue", meta["wake_hue"], "rainbow")
