"""THE BLACK HOLE STRIP ON THE STRIP PHASE LAYER (fx/effects/blackhole1d.py;
strip phase plan phase 2, revision 3). The Admiral, 2026-10-11: the strips
should "increase in brightness and activity during charge, dim and relax
into black for most lulls, and big explosion of brightness and activity on
the [drop]" — binding: "i don't want to raise the white in the charge, or
on the drop". His calls: the Black Hole strip's charge is a TINTED PALETTE
GLOW (the white flood goes); every lull is black at the room's dark point;
a flare in the lull's dark punches through.

What is proven here, on the real code it names:

- BEFORE/AFTER on his own Black Hole V2 strip entry (scripts/
  check_blackhole_strip_phase.py, run whole): the charge builds in the
  set's colours with no pixel whiter than the set; the lull is black from
  the room's dark point to the drop with no phosphor dot; the drop is lit
  on its first frame, peaks as its shockwave reaches the ends and
  out-shines the charge; more blobs on the charge and the drop; off-phase
  frames byte-identical to the module before this phase. Each defect is
  shown on the pinned BEFORE module too, so every measure can fail.
- THE PRODUCTION PATH (tests/strip_phase_harness.py: the real
  ResponseEngine on the FacadeExecutor, a fake clock): the strip goes dark
  on the same frame as the crystal's Black Hole and the Pulse single; the
  drop's burst grows with the drop's intensity; a flare in the dark sends
  a ring burst of the strip's own blobs and the dark returns after hold +
  release, while "Flare punch" 0 lets the dark win with no burst; the
  forced formation tapers to nothing at the dark point; the saved
  `reverse` is put back after the drop; and a house mode holds the strip's
  phases back.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx.effects import blackhole1d as bh1d  # noqa: E402
from fx.effects import lull_dark  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response  # noqa: E402
from strip_phase_harness import (FPS, PALETTE, STRIP_PX, Room,  # noqa: E402
                                 lum, run, scene_for)

import scripts.check_blackhole_strip_phase as check  # noqa: E402

STRIP = "strip"
HIS = dict(check.HIS_STRIP, gradient=PALETTE)


# ── before / after, his own entry ───────────────────────────────────────────

def test_the_measured_before_and_after_passes():
    """The whole measurement script — his rule now, every retired defect
    shown on the pinned before module, off-phase frames byte-identical."""
    check._failures.clear()
    assert check.main() == 0, check._failures


def test_the_drop_burst_is_sized_by_the_drops_intensity():
    eff = SimpleNamespace(_config={})
    count = bh1d.Blackhole1d._phase_burst_count
    eff._config = {"drop_intensity": 0.01}
    assert count(eff) == bh1d.PHASE_BURST_N
    eff._config = {"drop_intensity": 0.85}
    assert count(eff) == 32
    eff._config = {"drop_intensity": 1.0}
    assert count(eff) == bh1d.PHASE_BURST_N_MAX
    eff._config = {}   # untold: the layer's own untold size (full)
    assert count(eff) == bh1d.PHASE_BURST_N_MAX


# ── on the production path ──────────────────────────────────────────────────

BH_CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "horizon_audio": 0.3, "base_speed": 2.0, "accel": 5.0, "spawn_rate": 30.0,
    "beat_burst": 0, "spawn_audio": 1.5, "speed_audio": 2.0,
    "max_blobs": 50, "edge_speed": 0.2, "horizon_hold": 2.8,
}


def _real_mask():
    import json
    prof = json.loads((ROOT / "storage/device_profiles/crystal-mapper.json")
                      .read_text(encoding="utf-8"))
    mask, v = [], False
    for run_len in prof["mask_rle"]:
        mask.extend([v] * run_len)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


def test_the_strip_goes_dark_on_the_same_frame_as_the_crystal_and_the_single(tmp_path):
    """One room, one lull arm (6 s, the 3 s cap): the Black Hole strip goes
    black exactly at the shared dark point on the same frame the Pulse
    single does, the crystal's Black Hole is dark from that frame on too,
    and the strip's forced formation has stopped there."""
    async def main():
        effects = {STRIP: ("blackhole1d", STRIP_PX, 1, dict(HIS)),
                   "bh": ("blackhole", 72 * 37, 37, dict(BH_CFG)),
                   "p": ("pulse", 1, 1, {"gradient": "#ff0000",
                                          "beat_ms": 500.0, "energy": 0.5})}
        async with Room(str(tmp_path), effects) as r:
            r.step(4 * FPS)
            await r.phase("charge", gap_ms=3000)
            r.step(3 * FPS)
            rec = await r.phase("lull", gap_ms=6000)
            assert set(rec["phase"]["targets"]) == {STRIP, "bh", "p"}
            eff = r.effects[STRIP]
            rates = []
            n0 = len(r.frames[STRIP])
            for _ in range(6 * FPS):
                rates.append(eff._phase_spawn_rate())
                r.step()
            mask = _real_mask()
            return (r.frames[STRIP][n0:], r.frames["p"][n0:],
                    [f.reshape(37, 72, -1)[mask] for f in r.frames["bh"][n0:]],
                    rates)
    strip, pulse, bh, rates = run(main())
    first_strip = next(i for i, f in enumerate(strip) if f.max() == 0)
    first_pulse = next(i for i, f in enumerate(pulse) if f.max() == 0)
    assert first_strip == first_pulse == 3 * FPS - 1
    assert all(f.max() == 0 for f in strip[first_strip:])
    assert all(f.max() == 0 for f in bh[first_strip:])
    assert strip[first_strip - 15].max() > 0      # a fade, not a cut
    # the forced formation tapers through the approach and stops at the point
    assert rates[1] > rates[FPS] > rates[2 * FPS] > 0.0
    assert all(r == 0.0 for r in rates[first_strip + 1:])


def _drop_burst(tmp_path, intensity):
    async def main():
        async with Room(str(tmp_path), {STRIP: ("blackhole1d", STRIP_PX, 1,
                                                dict(HIS))}) as r:
            eff = r.effects[STRIP]
            sizes = []
            orig = eff._phase_burst

            def logged(ring, count=None, _o=orig):
                before = eff.n
                _o(ring, count)
                sizes.append(eff.n - before)

            eff._phase_burst = logged
            r.step(60)
            await r.phase("charge", gap_ms=2000)
            r.step(2 * FPS)
            await r.phase("drop", intensity=intensity)
            r.step(FPS)
            return sizes, eff.reverse
    return run(main())


def test_a_bigger_drop_bursts_more_blobs_and_reverse_comes_back(tmp_path):
    small, rev_small = _drop_burst(tmp_path / "s", 0.2)
    big, rev_big = _drop_burst(tmp_path / "b", 0.85)
    assert small == [round(bh1d.PHASE_BURST_N + 24 * 0.2)]
    assert big == [32]
    # the charge's infall override is put back after the drop
    assert rev_small is True and rev_big is True


def _punch_scene():
    from spectra.models.scene import FlareKind
    gain = FlareKind(name="Flare gain 0.7-1", type="permanent", gain=0.9)
    return scene_for({STRIP: "blackhole1d"}, [gain])


def _punch(tmp_path, cfg_extra=None):
    async def main():
        cfg = {**HIS, **(cfg_extra or {})}
        async with Room(str(tmp_path), {STRIP: ("blackhole1d", STRIP_PX, 1,
                                                cfg)},
                        scene=_punch_scene()) as r:
            eff = r.effects[STRIP]
            bursts = []
            orig = eff._phase_burst

            def logged(ring, count=None, _o=orig):
                bursts.append(count)
                _o(ring, count)

            eff._phase_burst = logged
            r.step(60)
            await r.phase("lull", gap_ms=4000)
            r.step(3 * FPS)                 # dark (dark point 2 s in)
            dark_before = r.frames[STRIP][-1].max()
            n0 = len(r.frames[STRIP])
            await r.flare()
            r.step(int(2.5 * FPS))
            return dark_before, r.frames[STRIP][n0:], bursts
    return run(main())


def test_a_flare_in_the_dark_sends_a_ring_burst_and_the_dark_returns(tmp_path):
    dark_before, after, bursts = _punch(tmp_path / "p")
    assert dark_before == 0.0
    assert bursts == [bh1d.PUNCH_BURST_N]           # its own blobs, not a glow
    assert max(lum(f) for f in after[2:int(0.5 * FPS)]) > 0.005
    back = int(lull_dark.punch_length_s(0.25) * FPS) + 2
    assert all(f.max() == 0.0 for f in after[back:])


def test_flare_punch_zero_lets_the_dark_win_with_no_burst(tmp_path):
    dark_before, after, bursts = _punch(tmp_path / "d",
                                        {"flare_punch_strength": 0.0})
    assert dark_before == 0.0
    assert bursts == []
    assert all(f.max() == 0.0 for f in after)


class _Exec:
    def __init__(self):
        self.jumps, self.glides = [], []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        self.glides.append((vid, et, dict(params), ms))


def test_a_house_mode_holds_the_strip_phases_back(monkeypatch):
    """His call 4 covers the Black Hole strip too: while a house mode owns
    the look, the strip is withheld from the phase write and named."""
    ex = _Exec()
    conductor = SimpleNamespace(virtuals={
        STRIP: SimpleNamespace(effect_type="blackhole1d")})
    eng = scene_response.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState())
    monkeypatch.setattr(scene_response, "_house_owns_the_look",
                        lambda: "a house mode rests")
    rec = asyncio.run(eng._drive_phase("charge", gap_ms=4000))
    assert not ex.jumps and not ex.glides
    assert rec["withheld"]["virtuals"] == [STRIP]
