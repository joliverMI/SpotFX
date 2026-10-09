"""THE OTHER FISH AVOID IT — the big fish flare, phase 2.

His approval of the look (PR 386), then the ask: "Big fish looks right:
build step 2 - the other fish steer around the big fish while it crosses."
fx/effects/fish.py's BIG_AVOID block is the binding statement.

Proven on the real vendored pipeline (fx.headless) on his crystal's real
cells with his music Fish entry, measured by scripts/check_fish_big_fish_
avoid.py's own instrument (the light each fish actually lays, not the
steering's own geometry): with a big fish crossing, an ordinary fish never
swims through it where the panel has room beside it, overlap falls sharply,
no fish goes further past the lit edge than before, and no turn ever leaves
the fish's own turn circle. Without a big fish (and with `big_fish_avoid` 0)
every frame is the pinned pre-change module's, bit for bit.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import check_fish_big_fish_avoid as A  # noqa: E402
import check_fish_wall as W  # noqa: E402
from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from test_fish import HIS_MATRIX  # noqa: E402

DT = 1.0 / 60.0
# the merge-base this change was built on (PR 386's big fish, no avoidance),
# pinned: without a big fish — and with big_fish_avoid 0 — the effect is
# exactly this module
PRE_AVOID_REF = "1121ae02adfd681b1b1689c58c4218bc1652a939"


def _run(coro):
    return asyncio.run(coro)


def _load_pre_avoid():
    name = "fish_pre_avoid_test"
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{PRE_AVOID_REF}:fx/effects/fish.py"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout
    except Exception as exc:                       # noqa: BLE001
        pytest.fail(f"cannot read {PRE_AVOID_REF}:fx/effects/fish.py — {exc}")
    assert "big_fish_avoid" not in src, "the pin must predate the avoidance"
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


_TAGS = [0]


async def _frames(tmp_path, effect_type, cfg, script, seed=5, poke=None):
    _TAGS[0] += 1
    tag = f"bigavoid{_TAGS[0]}"
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=72 * 37, rows=37, device_id=tag,
        real_mask=W.crystal_real_mask())
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    try:
        eff = headless.attach_effect(host, virtual, effect_type, dict(cfg))
        eff._rng = np.random.default_rng(seed)
        out = []
        for step, (phase, n) in enumerate(script):
            if phase:
                eff.update_config({"phase": phase, "phase_progress": 0.0})
            if poke is not None and step == 1:
                eff.update_config({"big_fish": poke})
            for i in range(n):
                if phase in ("charge", "lull"):
                    eff.update_config({"phase_progress": (i + 1) / n})
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
                out.append(np.asarray(eff.matrix, dtype=np.uint8).copy())
        return out
    finally:
        cm.__exit__(None, None, None)
        await host.shutdown()


def _same(a, b):
    assert len(a) == len(b)
    for i, (x, y) in enumerate(zip(a, b)):
        assert np.array_equal(x, y), f"frame {i} differs"


# ── nothing changes without a big fish ──────────────────────────────────────

ARC = [(None, 120), ("charge", 120), ("lull", 90), ("drop", 120), (None, 60)]


@pytest.mark.parametrize("label,cfg", [
    # the lull's searching keeper (lull_keep's default, 1) and the drop rush
    ("music", dict(HIS_MATRIX, ripple_amount=0.35)),
    # the fireworks keepers: a lull told to keep three for another effect
    ("keepers", dict(HIS_MATRIX, ripple_amount=0.35, lull_keep=3,
                     lull_next="fireworks")),
    # House Fish with its solo bursts on
    ("house", dict(W.HOUSE_FISH_LIVE)),
])
def test_without_a_big_fish_every_frame_is_the_pre_avoid_modules(
        tmp_path, label, cfg):
    old = _load_pre_avoid()
    a = _run(_frames(tmp_path, old, cfg, ARC))
    b = _run(_frames(tmp_path, "fish", cfg, ARC))
    _same(a, b)


def test_big_fish_avoid_zero_is_the_step_one_crossing_bit_for_bit(tmp_path):
    """The escape hatch: with big_fish_avoid 0 a big fish crosses exactly as
    it did before the other fish learned to avoid it."""
    old = _load_pre_avoid()
    cfg = dict(W.MUSIC_FISH, ripple_amount=0.35)
    script = [(None, 60), (None, 360)]
    a = _run(_frames(tmp_path, old, cfg, script, poke=0.5))
    b = _run(_frames(tmp_path, "fish", dict(cfg, big_fish_avoid=0.0),
                     script, poke=0.5))
    _same(a, b)


# ── with one crossing ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def measured():
    """Before (big_fish_avoid 0) and after (the default), quiet and loud,
    over the instrument's own seeds."""
    out = {}
    for intensity in (0.2, 0.8):
        out[intensity] = (A.summarize(intensity, 0.0),
                          A.summarize(intensity, 1.0))
    return out


@pytest.mark.parametrize("intensity", [0.2, 0.8])
def test_no_fish_swims_through_it_where_the_panel_has_room(measured,
                                                           intensity):
    """In the panel's middle columns — where there is room above and below
    the big fish — no ordinary fish's middle is ever on its lit body. (The
    instrument proves the scene CAN fail this: before, several do.)"""
    before, after = measured[intensity]
    assert before["middles_mid"] >= 20
    assert after["middles_mid"] == 0


@pytest.mark.parametrize("intensity", [0.2, 0.8])
def test_overlap_falls_sharply_and_stays_small(measured, intensity):
    """At the crystal's pointed ends the big fish fills the whole lit
    height, so a fish caught there cannot always get clear without leaving
    the panel (the wall wins): the overlap that is left is small and much
    less than before."""
    before, after = measured[intensity]
    assert after["overlap_px"] <= 0.55 * before["overlap_px"]
    assert after["middles_end"] <= 0.75 * before["middles_end"]
    assert after["overlap_max"] <= 16 < before["overlap_max"]


@pytest.mark.parametrize("intensity", [0.2, 0.8])
def test_never_pushed_further_past_the_wall(measured, intensity):
    before, after = measured[intensity]
    assert after["outside"] <= before["outside"] + 0.25


@pytest.mark.parametrize("intensity", [0.2, 0.8])
def test_every_turn_stays_inside_the_turn_circle(measured, intensity):
    """Natural, never a snap: no heading changes faster than the fish's own
    speed over its turn radius allows."""
    _before, after = measured[intensity]
    assert after["turn_over"] <= 1e-4


def test_a_threatened_fish_darts_and_a_clear_one_does_not(tmp_path):
    """The threat is read for every swimmer each frame: a fish in the big
    fish's path gets urgency (and an escape heading); one well clear of it
    gets none."""
    async def main():
        r = await W.rig("threat", dict(W.MUSIC_FISH, particle_count=2),
                        seed=3)
        try:
            eff = r.effect
            r.step(60)
            eff.update_config({"big_fish": 0.5})
            r.step(2)
            fish = eff._big[0]
            n = eff.n
            # put fish 0 dead ahead of its nose on its line, fish 1 far above
            # and behind it
            nose = fish["x"] + fish["travel"] * (0.5 * fish["length"] + 6.0)
            eff.p_x[0] = (nose - eff.cx + eff.cam_px) / eff.sx
            eff.p_y[0] = (fish["y"] - eff.cy + eff.cam_py) / eff.sy
            eff.p_x[1] = (fish["x"] - fish["travel"] * fish["length"]
                          - eff.cx + eff.cam_px) / eff.sx
            eff.p_y[1] = (2.0 - eff.cy + eff.cam_py) / eff.sy
            eff.p_hd[1] = -np.pi / 2          # ... swimming away from it
            eff.p_mode[:n] = 0
            urg, esc, away = eff._big_fish_threat(
                n, eff.p_mode[:n] < 2, eff.p_hd[:n], 1.0, 0.0)
            assert urg[0] > 0.5 and away[0] != 0.0
            assert urg[1] == 0.0
        finally:
            await W.close(r)
    _run(main())


# ── reach ───────────────────────────────────────────────────────────────────

def test_the_two_settings_are_registered_for_sonic_and_the_editor():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    fish = registry["effects"]["fish"]
    schema = FX.Fish2d.schema()({})
    for key in ("big_fish_avoid", "big_fish_avoid_margin"):
        assert fish["params"][key]["default"] == schema[key]
        assert fish["defaults"][key] == schema[key]
        assert fish["params"][key]["help_topic"] == "fish-big-fish"
    assert schema["big_fish_avoid"] == 1.0
    assert schema["big_fish_avoid_margin"] == 2.0
