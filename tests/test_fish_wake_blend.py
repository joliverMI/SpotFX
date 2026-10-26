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

import ast
import asyncio
import json
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


def test_every_path_that_writes_the_matrix_goes_through_the_blend():
    """The draw, the held-transition `_fade_only` and the outgoing
    `_draw_collapse` may not mix the layers three different ways: the
    matrix has exactly ONE writer, `_composite`, and all three call it."""
    tree = ast.parse((REPO / "fx" / "effects" / "fish.py").read_text())
    writers, callers = [], set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "matrix"
                and isinstance(t.value, ast.Name) and t.value.id == "self"
                for t in node.targets
            ):
                writers.append(fn.name)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_composite"):
                callers.add(fn.name)
    assert writers == ["_composite"], writers
    assert {"draw", "_fade_only", "_draw_collapse"} <= callers, callers


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
    help_ts = (REPO / "spectra" / "web" / "src" / "help"
               / "helpContent.ts").read_text()
    assert "id: 'fish-wake-colour'" in help_ts


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
