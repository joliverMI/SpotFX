"""THE STRIP STAR READS LEAVES THE LULL TO STAR (fx/effects/strip_phase.py's
module docstring is the binding statement; the Admiral, 2026-10-14: "The
strip used by the radial effect shouldn't do the lull, let the crystal
mapping handle the lull, but the charge and drop should still happen").

Measured on the real render pipeline through tests/star_harness.py (a real
Melt `radial-dummy` under a real Radial, every phase from the PRODUCTION
ResponseEngine):

  1. while Star reads it, the strip never fades in a lull — and Star's own
     lull B still reaches black ON the shared dark point by itself;
  2. the strip's charge and drop still run (brighter colours on the charge,
     the drop's shockwave);
  3. a strip no Radial reads still fades exactly as before (the same Melt,
     the same lull) — and so does the strip Star read once Star has gone;
  4. a strip leaving a charge into a skipped lull eases back, never jumps;
  5. Star's "implode" lull reaches black on the dark point by itself too.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.effects import strip_phase  # noqa: E402
from star_harness import STRIP, lit_cells, star_room  # noqa: E402
from strip_phase_harness import PALETTE, STRIP_PX, Room, lum, run  # noqa: E402

GAP_MS = 5000          # a 5 s lull: dark point at 2.5 s
DARK_S = 2.5


def _fade(eff):
    f = eff._sp_frame
    return 1.0 if f is None else float(f.fade)


async def _star_lull(tmp, *, radial=None, layer=True):
    """Star over its strip through a whole lull: the strip's frames and its
    layer's fade, and Star's lit cells, every 0.1 s."""
    async with star_room(tmp, layer=layer, radial=radial) as room:
        room.step(room.secs(1.0))
        await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
        eff = room.effects[STRIP]
        n0 = len(room.frames[STRIP])
        fades, star = [], []
        for _ in range(int(round(3.2 / 0.1))):
            for _ in range(room.secs(0.1)):
                room.step(1)
                fades.append(_fade(eff))
            star.append(lit_cells(room.matrix()))
        return {
            "frames": np.array(room.frames[STRIP][n0:]),
            "fades": fades, "star": star,
            "serving": strip_phase.serving_radial(eff._virtual),
            "phase": eff._sp_phase, "seen": eff._sp_seen,
            "timing": eff._strip_phase_lull()}


def test_the_strip_star_reads_never_fades_and_star_still_goes_black(tmp_path):
    on = run(_star_lull(str(tmp_path / "on")))
    off = run(_star_lull(str(tmp_path / "off"), layer=False))
    assert on["serving"]
    # the strip's layer never fades it, dark point included ...
    assert min(on["fades"]) == 1.0
    # ... its effect was told "none" (no lull content), the key kept ...
    assert on["phase"] == "none" and on["seen"] == "lull"
    assert on["timing"] is None
    # ... so through the whole lull the strip is byte for byte the same
    # strip with no phase layer at all
    assert np.array_equal(on["frames"], off["frames"])
    # and Star's own lull B is black from the dark point on, by itself
    for i, lit in enumerate(on["star"]):
        if 0.1 * (i + 1) >= DARK_S:
            assert lit == 0, (0.1 * (i + 1), lit)
    assert on["star"][0] > 1000


def test_star_implode_lull_goes_black_on_the_dark_point_by_itself(tmp_path):
    out = run(_star_lull(str(tmp_path), radial={"lull_mode": "implode"}))
    assert min(out["fades"]) == 1.0
    assert out["star"][0] > 0
    for i, lit in enumerate(out["star"]):
        if 0.1 * (i + 1) >= DARK_S:
            assert lit == 0, (0.1 * (i + 1), lit)


async def _charge_then_drop(tmp, layer=True):
    async with star_room(tmp, layer=layer) as room:
        room.step(room.secs(1.0))
        await room.phase("charge", gap_ms=3000, intensity=0.8)
        room.step(room.secs(2.9))
        eff = room.effects[STRIP]
        charged = (eff._sp_phase, eff._sp_frame)
        await room.phase("drop", intensity=0.9)
        room.step(room.secs(0.1))
        drop = (eff._sp_phase, eff._sp_frame, eff._sp_drop_t)
        return charged, drop


def test_the_strip_star_reads_still_charges_and_drops(tmp_path):
    charged, drop = run(_charge_then_drop(str(tmp_path)))
    phase, frame = charged
    assert phase == "charge"
    assert frame is not None and frame.gain > 1.2 and frame.activity > 1.5
    phase, frame, drop_t = drop
    assert phase == "drop" and drop_t is not None
    assert frame is not None and frame.wave > 0.0 and frame.gain > 1.2


async def _plain_strip_lull(tmp):
    cfg = {"gradient": PALETTE, "speed": 0.08, "reactivity": 0.3,
           "blur": 1.0, "brightness": 1.0, "background_brightness": 0.0}
    async with Room(tmp, {"strip": ("melt", STRIP_PX, 1, cfg)}) as room:
        room.step(60)
        await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
        room.step(int(round((DARK_S + 0.2) * 60)))
        eff = room.effects["strip"]
        return (_fade(eff), lum(room.frames["strip"][-1]),
                strip_phase.serving_radial(eff._virtual), eff._sp_phase)


def test_a_strip_no_radial_reads_still_fades_to_black(tmp_path):
    fade, dark, serving, phase = run(_plain_strip_lull(str(tmp_path)))
    assert not serving
    assert phase == "lull"
    assert fade == 0.0 and dark == 0.0, (fade, dark)


async def _star_gone_then_lull(tmp):
    async with star_room(tmp, layer=True) as room:
        room.step(room.secs(1.0))
        strip_v = room.virtuals[STRIP]
        assert strip_phase.serving_radial(strip_v)
        # Star leaves the crystal: its strip goes back to its own lull
        room.star.deactivate()
        gone = strip_phase.serving_radial(strip_v)
        await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
        eff = room.effects[STRIP]
        # step the strip alone (the crystal's Star is no longer drawing)
        for _ in range(int(round((DARK_S + 0.2) * 60))):
            room.clock.advance(1.0 / 60)
            f = strip_v.assemble_frame()
            if f is not None:
                room.frames[STRIP].append(np.array(f, dtype=np.float64))
        return gone, _fade(eff), lum(room.frames[STRIP][-1]), eff._sp_phase


def test_the_strip_fades_again_once_star_has_gone(tmp_path):
    gone, fade, dark, phase = run(_star_gone_then_lull(str(tmp_path)))
    assert gone is False
    assert phase == "lull"
    assert fade == 0.0 and dark == 0.0, (fade, dark)


async def _charge_into_lull(tmp):
    async with star_room(tmp, layer=True) as room:
        room.step(room.secs(1.0))
        eff = room.effects[STRIP]
        await room.phase("charge", gap_ms=3000, intensity=0.8)
        room.step(room.secs(2.9))
        gains = [eff._sp_frame.gain]
        await room.phase("lull", gap_ms=GAP_MS, intensity=0.7)
        for _ in range(int(round(DARK_S * 60))):
            room.step(1)
            f = eff._sp_frame
            gains.append(1.0 if f is None else f.gain)
        return gains


def test_a_skipped_lull_eases_the_charge_back_never_jumps(tmp_path):
    gains = run(_charge_into_lull(str(tmp_path)))
    assert gains[0] > 1.3
    steps = np.abs(np.diff(gains))
    assert steps.max() < 0.05, steps.max()
    assert abs(gains[-1] - 1.0) < 1e-6
