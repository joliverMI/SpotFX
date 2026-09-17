"""Frame-level proofs for the FISH effect (fx/effects/fish.py) and its
scene seeder, on the real vendored render pipeline (fx.headless dummy
Matrix host at his crystal-mapper's 72x37 shape, audio silenced).

scripts/check_fish.py is the measured, printed version of the same runs —
this file pins the properties his brief actually names. Mutual avoidance
(`avoid_strength`, 2026-08-28) un-parks his own deferral and is pinned here
too: the structural half (it can only ever steer, never move a fish or beat
the turn cap) and the measured half (crossings actually drop at his values).
scripts/check_fish_avoidance.py is its printed, tuned counterpart.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import fish as FX

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

# his live Orbits V2 Matrix entry, at the fallbacks its bindings resolve to
HIS_MATRIX = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.15, "tether_scatter": 0.0,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "reverse": False,
}


def _run(coro):
    return asyncio.run(coro)


class _Room:
    def __init__(self, host, virtual, clock, effect, clock_cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, clock_cm
        self.frame = None

    def step(self, frames=1):
        for _ in range(frames):
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)
                self.frame = np.array(f, copy=True)

    def ramp(self, phase, seconds, beats_every=None):
        eff = self.effect
        eff.update_config({"phase": phase, "phase_progress": 0.0})
        frames = int(seconds / DT)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if beats_every and i % beats_every == 0:
                eff._beat_pending = True
            self.step(1)

    def swimming(self, ordinary_only=False):
        n = self.effect.n
        m = self.effect.p_mode[:n] < 2
        if ordinary_only:
            m = m & (self.effect.p_nocap[:n] == 0)
        return int(np.count_nonzero(m))


async def _room(tmp_path, name, config=None, seed=5):
    host = await headless.start_headless_host(
        str(tmp_path / name), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=name,
    )
    virtual = host.virtuals.get(name)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    effect = headless.attach_effect(
        host, virtual, "fish", dict(config or HIS_MATRIX)
    )
    effect._rng = np.random.default_rng(seed)
    return _Room(host, virtual, clock, effect, cm)


async def _close(room):
    room._cm.__exit__(None, None, None)
    await room.host.shutdown()


# ── the buffer, and the scope of the cap bypass ─────────────────────────
def test_buffer_headroom_holds_school_rush_and_explosion_at_once():
    """His authorised bypass is exactly two moments; the buffer must be
    able to hold both plus a full drop explosion without the ordinary
    render being starved (the fireworks p_nocap lesson)."""
    need = (
        FX.MAX_PARTICLE_COUNT + FX.MAX_SCHOOL + FX.MAX_RUSH
        + FX.DROP_EJECTA_X * FX.MAX_PARTICLE_COUNT
    )
    assert FX.CAP >= need, (
        f"CAP={FX.CAP} cannot hold {FX.MAX_PARTICLE_COUNT} fish + a "
        f"{FX.MAX_SCHOOL} school + a {FX.MAX_RUSH} rush + "
        f"{FX.DROP_EJECTA_X}x ejecta ({need})"
    )


def test_ordinary_swimming_never_exceeds_the_parameter(tmp_path):
    async def main():
        room = await _room(tmp_path, "cap", dict(
            HIS_MATRIX, particle_count=8, school_count=12, rush_count=20
        ), seed=17)
        eff = room.effect
        worst = 0
        for _ in range(int(4.0 / DT)):
            room.step(1)
            worst = max(worst, room.swimming(ordinary_only=True))
        assert worst <= 8
        for phase, secs, beats in (("charge", 4.0, 12), ("lull", 3.5, None),
                                   ("drop", 5.0, None)):
            room.ramp(phase, secs, beats)
            worst = max(worst, room.swimming(ordinary_only=True))
            assert eff.n <= FX.CAP
        room.step(int(3.0 / DT))
        assert room.swimming(ordinary_only=True) == 8, (
            "ordinary swimming must be back at the parameter once the arc "
            "is over"
        )
        assert int(np.count_nonzero(eff.p_nocap[: eff.n] == 1)) == 0, (
            "no cap-exempt fish may outlive the moment it was granted for"
        )
        await _close(room)
    _run(main())


# ── 1. the oval points where it is going ────────────────────────────────
def test_rendered_oval_points_along_the_velocity(tmp_path):
    async def main():
        room = await _room(tmp_path, "heading", dict(
            HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
            jiggle=0.0, ripple_amount=0.0, trail_decay=0.0, flap_amount=0.3,
        ))
        errs = []
        room.step(120)
        for i in range(480):
            room.step(1)
            if i % 20:
                continue
            a = room.frame.astype(float).max(axis=1).reshape(ROWS, COLS)
            ys, xs = np.nonzero(a > 6.0)
            if len(xs) < 8:
                continue
            w = a[ys, xs]
            mx = (xs * w).sum() / w.sum()
            my = (ys * w).sum() / w.sum()
            dx, dy = xs - mx, ys - my
            cov = np.array([
                [(w * dx * dx).sum(), (w * dx * dy).sum()],
                [(w * dx * dy).sum(), (w * dy * dy).sum()],
            ]) / w.sum()
            _, evec = np.linalg.eigh(cov)
            axis = np.arctan2(evec[1, -1], evec[0, -1])
            hd = float(room.effect.p_hd[0])
            errs.append(np.degrees(
                abs(((axis - hd + np.pi / 2) % np.pi) - np.pi / 2)
            ))
        e = np.array(errs)
        assert len(e) > 15
        assert e.mean() < 12.0 and e.max() < 25.0, (
            f"the rendered body's long axis must track the direction of "
            f"travel (mean {e.mean():.1f} deg, max {e.max():.1f})"
        )
        await _close(room)
    _run(main())


def test_the_body_is_a_thin_oval_not_a_disc(tmp_path):
    async def main():
        room = await _room(tmp_path, "oval")
        eff = room.effect
        assert eff.body_aspect >= 1.2
        assert eff._body_len_px() > 2.5 * eff._half_width_px()
        await _close(room)
    _run(main())


# ── 2. turning is an arc, never a flip ──────────────────────────────────
def test_heading_never_flips_and_obeys_the_turn_radius(tmp_path):
    async def main():
        room = await _room(tmp_path, "turn", dict(HIS_MATRIX,
                                                  particle_count=4), seed=9)
        eff = room.effect
        room.step(60)
        worst = 0.0
        prev, prev_n = eff.p_hd[: eff.n].copy(), eff.n
        for _ in range(1800):
            room.step(1)
            k = min(prev_n, eff.n)
            if k:
                d = np.abs(
                    (eff.p_hd[:k] - prev[:k] + np.pi) % (2 * np.pi) - np.pi
                )
                worst = max(worst, float(d.max()))
            prev, prev_n = eff.p_hd[: eff.n].copy(), eff.n
        ceiling = float(eff.p_spd[: eff.n].max()) / eff.turn_radius_px * DT
        assert worst < np.pi / 2, (
            "reversing on the spot must be impossible — "
            f"saw {np.degrees(worst):.1f} deg in one frame"
        )
        assert worst <= ceiling * 1.05 + 1e-6, (
            "every turn must obey the turn-radius ceiling"
        )
        await _close(room)
    _run(main())


def test_an_about_face_takes_a_real_arc(tmp_path):
    async def main():
        room = await _room(tmp_path, "arc", dict(HIS_MATRIX,
                                                 particle_count=4), seed=9)
        eff = room.effect
        room.step(180)
        start = float(eff.p_hd[0])
        floor_s = np.pi * eff.turn_radius_px / float(eff.cruise_px)
        turned_at = None
        for f in range(1, 2000):
            room.step(1)
            if eff.n == 0:
                break
            d = abs((float(eff.p_hd[0]) - start + np.pi) % (2 * np.pi) - np.pi)
            if d >= np.pi * 0.9:
                turned_at = f * DT
                break
        assert turned_at is None or turned_at >= floor_s * 0.9, (
            f"an about-face took {turned_at:.2f}s, below the half-circle "
            f"floor {floor_s:.2f}s implied by the turn radius"
        )
        await _close(room)
    _run(main())


# ── 3. the spine flaps with acceleration ────────────────────────────────
def _flap_scale(eff):
    n = eff.n
    sn = np.clip(eff.p_spd[:n] / max(eff.cruise_px, 1e-3), 0.0, 3.0)
    an = np.clip(eff.p_acc[:n] / FX.FLAP_ACCEL_REF, -1.5, 1.5)
    return float(np.clip(
        FX.FLAP_BASE + FX.FLAP_SPEED_GAIN * sn + eff.flap_accel * an,
        FX.FLAP_MIN, FX.FLAP_MAX,
    ).mean())


def test_tail_waves_harder_accelerating_and_subtler_slowing(tmp_path):
    async def main():
        room = await _room(tmp_path, "flap", dict(
            HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
            jiggle=0.0,
        ))
        eff = room.effect
        room.step(180)
        steady = _flap_scale(eff)
        eff.update_config({"base_speed": 1.2})
        room.step(12)
        accel = _flap_scale(eff)
        eff.update_config({"base_speed": 0.3})
        room.step(102)          # cruise fast, then decelerate
        eff.update_config({"base_speed": 0.3})
        decel_room = _flap_scale(eff)
        assert accel > steady * 1.4, (accel, steady)
        assert FX.FLAP_MIN <= decel_room <= FX.FLAP_MAX
        await _close(room)
    _run(main())


def test_deceleration_makes_the_flap_subtler(tmp_path):
    async def main():
        room = await _room(tmp_path, "flap2", dict(
            HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
            jiggle=0.0,
        ))
        eff = room.effect
        room.step(180)
        steady = _flap_scale(eff)
        eff.update_config({"base_speed": 1.2})
        room.step(120)
        eff.update_config({"base_speed": 0.3})
        room.step(12)
        decel = _flap_scale(eff)
        assert decel < steady * 0.6, (decel, steady)
        await _close(room)
    _run(main())


# ── 4. the wake ─────────────────────────────────────────────────────────
def test_wake_is_always_subtle_and_stronger_on_faster(tmp_path):
    async def main():
        room = await _room(tmp_path, "wake", dict(
            HIS_MATRIX, particle_count=2, horizon_scale=0.0, spin=0.0,
            jiggle=0.0,
        ))
        eff = room.effect
        out = {}
        for label, impulse in (("calm", 0.0), ("loud", 0.9)):
            room.step(240)
            eff.wake[:] = 0.0
            eff.impulse = impulse
            eff.slow = 0.25 * impulse
            room.step(120)
            out[label] = (float(eff.wake.sum()), float(eff.wake.max()))
        assert out["loud"][0] > out["calm"][0] * 1.5, out
        # "always subtle": the wake never approaches the fish's own peak
        assert 0.0 < out["loud"][1] < 0.6 * float(eff.trail.max()), (
            "the wake must stay subtle at every speed", out
        )
        await _close(room)
    _run(main())


def test_wake_expands_as_well_as_fading(tmp_path):
    """His ask, verbatim: 'expand and fade instead of just fading'. A buffer
    that only decayed would keep the same footprint and dim; this one has to
    cover MORE cells as its peak falls."""
    async def main():
        room = await _room(tmp_path, "wake-expand", dict(
            HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
            jiggle=0.0,
        ))
        eff = room.effect
        room.step(240)
        eff.wake[:] = 0.0
        room.step(1)
        eff.update_config({"ripple_amount": 0.0})   # stop depositing

        def shot():
            w = eff.wake.sum(axis=2)
            thr = 0.02 * float(w.max()) if w.max() > 0 else 1.0
            return float(w.max()), int((w > thr).sum())

        peak0, cells0 = shot()
        room.step(18)
        peak1, cells1 = shot()
        assert peak0 > 0.0, "nothing was deposited"
        assert cells1 > cells0, ("the wake must EXPAND", cells0, cells1)
        assert peak1 < peak0, ("... while it fades", peak0, peak1)
        await _close(room)
    _run(main())


def test_a_deposit_is_a_filled_smear_never_a_ring(tmp_path):
    """His objection was the OUTLINE: 'the circle line is kind of messy'. A
    ring peaks off its own centre; a filled smear peaks at it."""
    async def main():
        room = await _room(tmp_path, "wake-ring", dict(
            HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
            jiggle=0.0,
        ))
        eff = room.effect
        room.step(240)
        eff.wake[:] = 0.0
        room.step(1)
        w = eff.wake.sum(axis=2)
        assert w.max() > 0.0
        cy, cx = np.unravel_index(int(np.argmax(w)), w.shape)
        ys, xs = np.mgrid[0:w.shape[0], 0:w.shape[1]]
        d = np.hypot(xs - cx, ys - cy)
        prof = [
            float(w[(d >= r) & (d < r + 1)].mean())
            for r in range(6)
        ]
        assert int(np.argmax(prof)) == 0, ("peaks off centre = a ring", prof)
        assert all(prof[i] >= prof[i + 1] - 1e-6 for i in range(5)), prof
        await _close(room)
    _run(main())


def test_wake_colour_is_distinct_from_the_fish_both_ways(tmp_path):
    """The stated rule (fx/effects/fish.py, WAKE_SOLID_* / WAKE_GRAD_OFFSET):
    a real gradient gives the wake a DIFFERENT COLOUR; a solid palette gives
    it substantially LESS BRIGHTNESS. Measured on the two real buffers."""
    SOLID = "linear-gradient(90deg, #22aaff 0.00%,#22aaff 100.00%)"

    def unit(rgb):
        n = np.linalg.norm(rgb, axis=1, keepdims=True)
        return rgb / np.maximum(n, 1e-6)

    def split(eff):
        fl = eff.trail.sum(axis=2)
        wl = eff.wake.sum(axis=2)
        fish_m = fl > 0.5 * fl.max()
        wake_m = (wl > 0.25 * wl.max()) & (fl < 0.05 * max(fl.max(), 1e-6))
        return eff.trail[fish_m], eff.wake[wake_m]

    async def main():
        one = dict(HIS_MATRIX, particle_count=1, horizon_scale=0.0,
                   spin=0.0, jiggle=0.0)
        # GRADIENT: his default rainbow
        room = await _room(tmp_path, "wake-grad", one)
        room.step(600)
        f, w = split(room.effect)
        dist = float(np.linalg.norm(
            unit(f).mean(axis=0) - unit(w).mean(axis=0)
        ))
        await _close(room)
        # the negative control: with the offset removed the wake wears the
        # fish's own colour, so the distance must collapse
        orig = FX.WAKE_GRAD_OFFSET
        FX.WAKE_GRAD_OFFSET = 0.0
        try:
            room = await _room(tmp_path, "wake-grad-ctl", one)
            room.step(600)
            f0, w0 = split(room.effect)
            dist0 = float(np.linalg.norm(
                unit(f0).mean(axis=0) - unit(w0).mean(axis=0)
            ))
            await _close(room)
        finally:
            FX.WAKE_GRAD_OFFSET = orig
        assert dist > 0.5, ("the gradient wake must be a different colour",
                            dist)
        assert dist > dist0 * 3.0, ("... and the offset is what does it",
                                    dist, dist0)

        # SOLID: same colour, substantially dimmer
        room = await _room(tmp_path, "wake-solid", dict(one, gradient=SOLID))
        room.step(600)
        ratio = float(room.effect.wake.max()) / max(
            float(room.effect.trail.max()), 1e-6
        )
        await _close(room)
        assert 0.0 < ratio < 0.45, (
            "a solid palette must render the wake substantially dimmer than "
            "the fish, but still visible", ratio,
        )
    _run(main())


# ── 5. the charge's school ──────────────────────────────────────────────
def test_charge_school_swims_in_in_unison_and_turns_on_the_beat(tmp_path):
    async def main():
        room = await _room(tmp_path, "charge", seed=11)
        eff = room.effect
        room.step(240)
        eff.update_config({"phase": "charge", "phase_progress": 0.0})
        frames = int(4.0 / DT)
        turns, spreads = [], []
        last = eff._school_hd
        peak = 0
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if i % 12 == 0:          # a beat every 200ms — twice his floor
                eff._beat_pending = True
            room.step(1)
            peak = max(peak, room.swimming())
            if eff._school_hd != last:
                turns.append(i * DT)
                last = eff._school_hd
            if i > frames * 0.55:
                live = np.flatnonzero(eff.p_mode[: eff.n] == 0)
                if live.size > 2:
                    hs = eff.p_hd[live]
                    c = np.arctan2(np.sin(hs).mean(), np.cos(hs).mean())
                    spreads.append(float(np.abs(
                        (hs - c + np.pi) % (2 * np.pi) - np.pi
                    ).std()))
        gaps = [turns[i + 1] - turns[i] for i in range(len(turns) - 1)]
        assert peak <= eff.school_count, (peak, eff.school_count)
        assert peak >= eff.school_count - 1, "the school must actually fill"
        assert len(gaps) >= 2
        assert min(gaps) >= eff.turn_min_time - 1e-6, (
            f"direction changes must never be closer than "
            f"{eff.turn_min_time}s: {gaps}"
        )
        spread = float(np.mean(spreads))
        assert 0.0 < spread < 0.5, (
            "the school moves almost identically, with minor variation — "
            f"never lockstep, never scattered (spread {spread:.4f} rad)"
        )
        assert abs(eff._flow_px) + abs(eff._flow_py) > 0.0, (
            "the water must keep streaming past while the school holds "
            "station — that IS the camera-following-a-school illusion"
        )
        await _close(room)
    _run(main())


def test_the_charge_school_does_not_clump(tmp_path):
    """His ask (2026-08-28): "in the charge, I don't want the fish to clump
    so much and I want them evenly distributed across the screen" — while
    still arriving together.

    Measured against the same run with the separation steer switched off,
    which is the state this replaced. scripts/check_fish_charge_spread.py
    is the merge-base before/after; this pins the property.
    """
    def spread(eff, panel):
        rows, cols = panel
        n = eff.n
        m = np.flatnonzero(eff.p_mode[:n] == 0)
        if m.size < 3:
            return None
        x = eff.p_x[m] * eff.sx - eff.cam_px + eff.cx
        y = eff.p_y[m] * eff.sy - eff.cam_py + eff.cy
        on = (x >= 0) & (x < cols) & (y >= 0) & (y < rows)
        x, y = x[on], y[on]
        if x.size < 3:
            return None
        d = np.hypot(x[None, :] - x[:, None], y[None, :] - y[:, None])
        np.fill_diagonal(d, np.inf)
        gx = np.clip((x / cols * 6).astype(int), 0, 5)
        gy = np.clip((y / rows * 3).astype(int), 0, 2)
        cells = len(set(zip(gx.tolist(), gy.tolist())))
        return float(d.min(axis=1).mean()), cells / x.size

    async def run(weight):
        orig = FX.SCHOOL_SPACING_W
        FX.SCHOOL_SPACING_W = weight
        try:
            room = await _room(tmp_path, f"clump{weight}", seed=5)
            eff = room.effect
            room.step(240)
            panel = (eff.r_height, eff.r_width)
            eff.update_config({"phase": "charge", "phase_progress": 0.0})
            frames = int(4.0 / DT)
            seen = []
            for i in range(1, frames + 1):
                eff.update_config({"phase_progress": i / frames})
                room.step(1)
                if i > frames * 0.5:
                    got = spread(eff, panel)
                    if got:
                        seen.append(got)
            hd = eff.p_hd[np.flatnonzero(eff.p_mode[: eff.n] == 0)]
            c = np.arctan2(np.sin(hd).mean(), np.cos(hd).mean())
            unison = float(np.abs(
                (hd - c + np.pi) % (2 * np.pi) - np.pi
            ).std())
            await _close(room)
            assert seen, "no charge school was ever measured"
            return (float(np.mean([a for a, _ in seen])),
                    float(np.mean([b for _, b in seen])),
                    unison)
        finally:
            FX.SCHOOL_SPACING_W = orig

    async def main():
        off = await run(0.0)
        on = await run(FX.SCHOOL_SPACING_W)
        assert on[0] > off[0] * 1.25, (
            "the school must sit further apart", off, on)
        assert on[1] > off[1] * 1.1, (
            "... and reach more of the panel per fish on it", off, on)
        # ARRIVING TOGETHER is the half that must NOT be traded away
        assert on[2] < 0.5, ("the school stopped moving in unison", on)
    _run(main())


# ── 6. the lull clock ───────────────────────────────────────────────────
def _lull_clock(room, eff, seconds=3.6):
    """Drive a full lull and report what was alive and lit at each third."""
    eff.update_config({"phase": "lull", "phase_progress": 0.0})
    frames = int(seconds / DT)
    marks = {}
    for i in range(1, frames + 1):
        f = i / frames
        eff.update_config({"phase_progress": f})
        room.step(1)
        # every fish on the effect, dispersing ones included: a fish that is
        # swirling out is still a fish in the lull
        alive = int(eff.n)
        lit = float(np.asarray(eff.matrix, dtype=np.float32).max())
        wake = float(eff.wake.max())
        marks[i] = (f, alive, lit, wake)
    at = lambda frac: marks[max(1, int(frames * frac))]      # noqa: E731
    return marks, at


def test_the_lull_clock_empties_then_ripples_then_goes_dark(tmp_path):
    """His 2026-08-28 ruling, in thirds of the lull's own duration:

        0 -> 1/3    every fish disperses and is GONE by the end of it
        1/3 -> 2/3  ripples only — the wake, with no fish anywhere
        2/3 -> end  fully dark, until the drop

    This REPLACES the old lull (disperse to one fish, held at the centre by
    half way, then a rush at 60%). That behaviour is superseded, not
    weakened: there is no lone fish and no survivor of any kind, and the
    rush moved into the drop.
    """
    async def main():
        room = await _room(tmp_path, "lullclock", seed=11)
        eff = room.effect
        room.step(240)
        room.ramp("charge", 4.0, beats_every=12)
        marks, at = _lull_clock(room, eff)

        # 0 -> 1/3: gone. No exceptions.
        assert at(0.10)[1] > 0, "the lull must start with fish in it"
        for frac in (FX.LULL_GONE_AT, 0.5, FX.LULL_DARK_AT, 0.9, 1.0):
            f, alive, _lit, _w = at(frac)
            assert alive == 0, (
                f"a fish survived past the first third (progress {f:.2f}, "
                f"{alive} alive)"
            )

        # 1/3 -> 2/3: ripples only — something is still lit, and it is wake
        mid = [
            v for v in marks.values()
            if FX.LULL_GONE_AT < v[0] < FX.LULL_DARK_AT * 0.95
        ]
        assert any(v[3] > 0.0 for v in mid), (
            "the wake must still be there between the thirds"
        )
        assert all(v[1] == 0 for v in mid), "... with no fish anywhere"

        # 2/3 -> end: dark
        last = [v for v in marks.values() if v[0] >= FX.LULL_DARK_AT]
        assert last, "the lull never reached its final third"
        assert max(v[2] for v in last) == 0.0, (
            "the last third must be fully dark: brightest pixel "
            f"{max(v[2] for v in last):.2f}"
        )
        await _close(room)
    _run(main())


def test_the_lull_window_eases_home_once_there_is_nothing_to_follow(tmp_path):
    """With no fish after the first third there is no school to follow, so
    the window must ease home rather than hold wherever it had got to."""
    async def main():
        room = await _room(tmp_path, "lullcam",
                           dict(HIS_MATRIX, camera_follow=0.8), seed=11)
        eff = room.effect
        room.step(240)
        room.ramp("charge", 4.0, beats_every=12)
        away = float(np.hypot(eff.cam_px, eff.cam_py))
        _marks, at = _lull_clock(room, eff, seconds=4.0)
        home = float(np.hypot(eff.cam_px, eff.cam_py))
        assert away > 2.0, ("the charge must have moved the window at all",
                            away)
        assert home < away * 0.5, (
            f"the window did not ease home: {away:.1f}px -> {home:.1f}px"
        )
        await _close(room)
    _run(main())


# ── 7. the drop ─────────────────────────────────────────────────────────
def test_drop_payoff_fires_on_the_first_rendered_frame(tmp_path):
    async def main():
        room = await _room(tmp_path, "drop", seed=4)
        eff = room.effect
        born = [0]
        orig = eff._spawn_drop_ejecta

        def counted(count, _o=orig):
            before = eff.n
            _o(count)
            born[0] += eff.n - before
        eff._spawn_drop_ejecta = counted

        room.step(240)
        room.ramp("lull", 2.5)
        eff.update_config({"phase": "drop", "phase_progress": 0.0})
        room.step(1)
        assert born[0] == FX.DROP_EJECTA_X * eff._config["particle_count"], (
            "the drop's payoff must land on the phase's first rendered "
            "frame, at Orbits' own 2x-the-population count"
        )
        room.step(int((FX.DROP_SETTLE_S + 0.6) / DT))
        assert eff._phase == "none" and eff._config["phase"] == "none", (
            "the phase must self-reset so an identical later drop edges "
            "again"
        )
        assert room.swimming() == eff._config["particle_count"]
        await _close(room)
    _run(main())


def test_the_drop_rushes_in_swirls_and_leaves_the_blob_count_behind(tmp_path):
    """His 2026-08-28 addendum, verbatim: "I want the rush to be part of the
    drop. All the fish rush in, swirl around and some stay behind per the
    blob count parameter after the drop is done."

    Three beats, on the drop he already likes:
      1. RUSH IN   — the rush population enters at the drop instant
      2. SWIRL     — through the drop's own duration
      3. STAY BEHIND — `particle_count` of them become the ordinary
                       population when the drop finishes
    """
    async def main():
        room = await _room(tmp_path, "droprush", seed=4)
        eff = room.effect
        room.step(240)
        # the lull leaves NOTHING behind now, so the drop is what has to
        # bring the room back
        room.ramp("lull", 3.0)
        assert eff.n == 0, "the lull must have emptied the panel"

        born = [0]
        orig = eff._spawn_rush

        def counted(count, _o=orig):
            before = eff.n
            _o(count)
            born[0] += eff.n - before
        eff._spawn_rush = counted

        eff.update_config({"phase": "drop", "phase_progress": 0.0})
        room.step(1)
        assert born[0] == eff.rush_count, (
            "the whole rush must arrive on the drop's first rendered frame",
            born[0], eff.rush_count,
        )
        rushers = np.flatnonzero(
            (eff.p_mode[: eff.n] == 3) & (eff.p_nocap[: eff.n] == 1)
        )
        assert rushers.size == eff.rush_count
        assert eff._rush_swirl >= 0.0

        # BEAT 2: they swirl — angular travel around the centre of view,
        # measured on the rush fish themselves
        def angles():
            idx = np.flatnonzero(
                (eff.p_mode[: eff.n] == 3) & (eff.p_nocap[: eff.n] == 1)
            )
            return idx, np.arctan2(
                (eff.p_y[idx] - eff.cam_ny) * eff.sy,
                (eff.p_x[idx] - eff.cam_nx) * eff.sx,
            )

        i0, a0 = angles()
        swept = np.zeros(eff.n)
        prev = dict(zip(i0.tolist(), a0.tolist()))
        peak_swirl = 0.0
        for _ in range(int(1.6 / DT)):
            room.step(1)
            peak_swirl = max(peak_swirl, float(eff._rush_swirl))
            idx, ang = angles()
            for k, a in zip(idx.tolist(), ang.tolist()):
                if k in prev:
                    swept[k] += abs(
                        (a - prev[k] + np.pi) % (2 * np.pi) - np.pi
                    )
                prev[k] = a
        assert peak_swirl > 0.0, "the swirl never engaged"
        assert float(np.max(swept)) > 1.0, (
            "the rush must actually swirl around the centre: worst-case "
            f"angular travel {float(np.max(swept)):.2f} rad"
        )

        # BEAT 3: the blob count stays behind
        room.step(int((FX.DROP_SETTLE_S + 1.5) / DT))
        assert eff._phase == "none"
        assert room.swimming(ordinary_only=True) == \
            eff._config["particle_count"], (
            "exactly the blob count must stay behind after the drop"
        )
        assert int(np.count_nonzero(eff.p_nocap[: eff.n] == 1)) == 0, (
            "no cap-exempt fish may outlive the drop"
        )
        await _close(room)
    _run(main())


def test_the_drop_is_unchanged_when_the_rush_is_switched_off(tmp_path):
    """The rush is an ADDITION to the drop, not a redesign of it: with
    `rush_count` at 0 the drop repopulates from its own centre burst
    exactly as it always did."""
    async def main():
        room = await _room(tmp_path, "droprush0",
                           dict(HIS_MATRIX, rush_count=0), seed=4)
        eff = room.effect
        room.step(240)
        room.ramp("lull", 3.0)
        burst = [0]
        orig = eff._spawn_center_burst

        def counted(ncx, ncy, count, _o=orig):
            before = eff.n
            _o(ncx, ncy, count)
            burst[0] += eff.n - before
        eff._spawn_center_burst = counted

        eff.update_config({"phase": "drop", "phase_progress": 0.0})
        room.step(1)
        assert burst[0] == eff._config["particle_count"], (
            "with no rush, the centre burst must still repopulate the drop",
            burst[0],
        )
        room.step(int((FX.DROP_SETTLE_S + 1.0) / DT))
        assert room.swimming(ordinary_only=True) == \
            eff._config["particle_count"]
        await _close(room)
    _run(main())


def test_orphaned_charge_releases_itself_without_a_none_sentinel(tmp_path):
    """The watchdog path must never leave a half-built state observable to
    draw() — the render-thread crash class (AGENTS.md, blackhole's own
    burst_t=None regression)."""
    async def main():
        room = await _room(tmp_path, "orphan", seed=6)
        eff = room.effect
        room.step(120)
        eff.update_config({"phase": "charge", "phase_progress": 1.0})
        room.step(int(
            (FX.particle_handoff.PHASE_GRACE_S + 4.0) / DT
        ))
        assert eff._phase in ("drop", "none")
        assert eff._drop_state is None or \
            eff._drop_state.get("burst_done") is True
        assert int(np.count_nonzero(eff.p_nocap[: eff.n] == 1)) == 0
        await _close(room)
    _run(main())


# ── handoff + wiring ────────────────────────────────────────────────────
def test_fish_hands_off_to_and_from_orbits(tmp_path):
    """A scene switch morphs rather than cuts, both directions, through the
    ordinary particle_handoff store->take path (no private call)."""
    import fx.effects.particle_handoff as ph

    async def main():
        room = await _room(tmp_path, "handoff", seed=3)
        room.step(300)
        snap = room.effect._handoff_snapshot()
        assert snap["src"] == "fish"
        assert len(snap["px"]) == room.effect.n
        assert snap["trail"] is not None and "native" in snap

        # fish -> orbits: orbits adopts on its own first draw, through the
        # generic particle branch it already had (no orbits change needed)
        ph.store(room.virtual.id, snap)
        orbits = headless.attach_effect(
            room.host, room.virtual, "orbits", {"particle_count": 4}
        )
        orbits._rng = np.random.default_rng(3)
        room.step(3)
        assert orbits.n > 0, "orbits must adopt the fish it inherited"

        # orbits -> fish, same way round
        orb_snap = orbits._handoff_snapshot()
        assert orb_snap["src"] == "orbits"
        ph.store(room.virtual.id, orb_snap)
        back = headless.attach_effect(
            room.host, room.virtual, "fish", dict(HIS_MATRIX)
        )
        back._rng = np.random.default_rng(3)
        room.step(3)
        assert back.n > 0, "fish must adopt the blobs it inherited"
        await _close(room)
    _run(main())


def test_fish_is_wired_exactly_where_orbits_is():
    from fx import device_model
    from spectra.services import transition_phases

    assert "fish" in device_model.PHASE_EFFECTS
    registry = json.loads(
        (Path(__file__).resolve().parent.parent
         / "config" / "effect_params.json").read_text()
    )
    assert "fish" in registry["effects"]
    assert "fish" in registry["morph"]["supported_effects"]
    # every shared Orbits param survives with the same type and range
    orb = registry["effects"]["orbits"]["params"]
    fish = registry["effects"]["fish"]["params"]
    shared = set(orb) & set(fish)
    assert len(shared) == len(orb), (
        f"fish must carry every Orbits param: missing {set(orb) - set(fish)}"
    )
    for key in shared:
        for field in ("type", "min", "max", "aspect", "smooth"):
            assert orb[key].get(field) == fish[key].get(field), (key, field)
    # the phased-transition registry treats fish exactly as it treats orbits
    for other in ("radial", "pacman", "dancer", "blackhole", "fireworks",
                  "squiggles", "eye"):
        assert (transition_phases.anchor_frac("fish", other)
                == transition_phases.anchor_frac("orbits", other)), other
        assert (transition_phases.anchor_frac(other, "fish")
                == transition_phases.anchor_frac(other, "orbits")), other


def test_registry_defaults_are_orbits_own_except_the_named_divergence():
    registry = json.loads(
        (Path(__file__).resolve().parent.parent
         / "config" / "effect_params.json").read_text()
    )
    orb = registry["effects"]["orbits"]["defaults"]
    fish = registry["effects"]["fish"]["defaults"]
    # orbit_radius means "turn radius" on a fish, so his tuned Orbits value
    # (an orbit radius) is deliberately NOT inherited — see the PR.
    diverge = {"orbit_radius"}
    for key, value in orb.items():
        if key in diverge or key not in fish:
            continue
        assert fish[key] == value, (
            f"fish default for {key!r} must be Orbits' own tuned value "
            f"({value!r}), got {fish[key]!r}"
        )


# ── the seeder ──────────────────────────────────────────────────────────
def _fake_store():
    return {
        "85d0724d-407f-45a0-9dac-48da21b4c5fb": {
            "id": "85d0724d-407f-45a0-9dac-48da21b4c5fb",
            "name": "Orbits V2",
            "labels": ["mid-group", "star"],
            "devices": [
                {"id": "a-1", "target_kind": "category", "target": "Matrix",
                 "effect_type": "orbits",
                 "params": {"horizon_scale": 0.19, "blob_size": 2.5}},
                {"id": "a-2", "target_kind": "category", "target": "Strips",
                 "effect_type": "orbits1d", "params": {"x_offset": 0.5}},
            ],
            "flare_kinds": [
                {"name": "Dice Re-roll", "type": "drift_jump",
                 "jump": "dice", "params": {}, "gain": 1.0, "hold_ms": None},
            ],
            "responses": {"flare": {"bands": [
                {"intensity_min": 0.0, "intensity_max": 1.0,
                 "curve": "linear", "gain": 1.0, "param_patch": {},
                 "kinds": {"Dice Re-roll": 1.0}},
            ]}},
            "accept_all_sets": True,
            "entry_ramp_ms": 0,
        },
        "other-scene": {"id": "other-scene", "name": "STAR", "devices": []},
    }


def test_seeder_copies_orbits_wholesale_and_changes_only_ids(tmp_path):
    import scripts.seed_fish_scene as seed

    store = _fake_store()
    src = store["85d0724d-407f-45a0-9dac-48da21b4c5fb"]
    fish = seed.build_fish(src)
    assert fish["name"] == "Fish"
    assert fish["id"] != src["id"]
    assert uuid.UUID(fish["id"])          # a real uuid, deterministic
    assert seed.build_fish(src)["id"] == fish["id"], "ids must be stable"
    assert fish["devices"][0]["effect_type"] == "fish"
    assert fish["devices"][1]["effect_type"] == "orbits1d", (
        "the Strips entry deliberately keeps orbits1d — there is no fish1d"
    )
    for key in ("labels", "flare_kinds", "responses", "accept_all_sets",
                "entry_ramp_ms"):
        assert fish[key] == src[key], f"{key} must be a verbatim copy"
    for dev_a, dev_b in zip(src["devices"], fish["devices"]):
        assert dev_a["params"] == dev_b["params"]
        assert dev_a["id"] != dev_b["id"], "device ids are scene-local"
    assert src == _fake_store()["85d0724d-407f-45a0-9dac-48da21b4c5fb"], (
        "building the copy must not mutate the source"
    )


def test_seeder_leaves_every_existing_scene_byte_identical(tmp_path):
    import scripts.seed_fish_scene as seed

    scenes = tmp_path / "scenes.json"
    sequencer = tmp_path / "sequencer.json"
    store = _fake_store()
    scenes.write_text(json.dumps(store, indent=2))
    src_id = "85d0724d-407f-45a0-9dac-48da21b4c5fb"
    sequencer.write_text(json.dumps({"config": {
        "entries": {src_id: {"curve_ref": None,
                             "inline_points": [{"x": 0.0, "y": 1.0}],
                             "genre_mult": {"rock": 1.3},
                             "dwell_weight": 2.0}},
        "affinity": [{"from_id": src_id, "to_id": "other-scene",
                      "weight": 0.7}],
    }, "curves": {}}, indent=2))
    before = copy.deepcopy(store)

    argv = sys.argv
    sys.argv = ["seed_fish_scene.py", "--apply",
                "--scenes-file", str(scenes),
                "--sequencer-file", str(sequencer)]
    try:
        seed.main()
        after = json.loads(scenes.read_text())
        fish_id = seed._sid("scene", "Fish")
        assert fish_id in after
        for sid, raw in before.items():
            assert after[sid] == raw, f"{sid} must be untouched"
        seq = json.loads(sequencer.read_text())
        assert seq["config"]["entries"][fish_id] == \
            seq["config"]["entries"][src_id], (
            "Fish inherits Orbits' own likelihood curve, genre multipliers "
            "and dwell weight"
        )
        assert len(seq["config"]["affinity"]) == 2
        # idempotent: a second run upserts, it does not duplicate or abort
        seed.main()
        again = json.loads(scenes.read_text())
        assert len(again) == len(after)
        assert len(json.loads(sequencer.read_text())["config"]["affinity"]) \
            == 2
    finally:
        sys.argv = argv


def test_the_seeded_scene_compiles_and_fires_on_the_real_pipeline(tmp_path):
    """End to end: the copied scene resolves through SPECTRA's own compiler
    and its Matrix entry lands on a real fish effect."""
    from spectra.models.scene import SceneV2
    from spectra.services import scene_compiler
    from spectra.services.binding_resolver import FireContext
    from random import Random
    import scripts.seed_fish_scene as seed

    live_path = (Path(__file__).resolve().parent.parent
                 / "storage" / "spectra" / "scenes.json")
    if not live_path.exists():
        pytest.skip("no scenes store in this checkout")
    store = json.loads(live_path.read_text())
    src_id = seed._find_one(store, "Orbits V2")
    scene = SceneV2(**seed.build_fish(store[src_id]))
    resolved = scene_compiler.resolve_scene(scene, FireContext(0.9,
                                                              rng=Random(5)))
    dev = next(d for d in resolved.devices if d.effect_type == "fish")

    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "seeded"), pixel_count=ROWS * COLS, rows=ROWS,
            device_id="seeded",
        )
        virtual = host.virtuals.get("seeded")
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "fish",
                                            dict(dev.params))
            for name, value in dev.params.items():
                got = effect._config[name]
                if isinstance(value, (int, float)) and not isinstance(
                        value, bool):
                    assert float(got) == pytest.approx(float(value),
                                                       abs=1e-6), name
                else:
                    assert got == value, name
            lit = 0
            for _ in range(300):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
                    lit = max(lit, int(
                        (np.array(frame).max(axis=1) > 6).sum()
                    ))
            assert lit > 0, "the seeded scene must actually render fish"
        await host.shutdown()
    _run(main())


# ── mutual avoidance: steering only, and it actually works ──────────────
HIS_CROWD = dict(
    HIS_MATRIX, jiggle=0.5, roam_scale=0.75, particle_count=10,
)


def _crowd_stats(eff):
    """(overlap pairs this frame, live pair count) at one body length."""
    n = eff.n
    live = np.flatnonzero(eff.p_mode[:n] < 2)
    if live.size < 2:
        return 0, 0
    x = eff.p_x[:n][live] * eff.sx
    y = eff.p_y[:n][live] * eff.sy
    d = np.hypot(x[None, :] - x[:, None], y[None, :] - y[:, None])
    np.fill_diagonal(d, np.inf)
    return (int(np.count_nonzero(d < eff._body_len_px())) // 2,
            live.size * (live.size - 1) // 2)


def test_avoidance_at_zero_is_the_untouched_effect(tmp_path):
    """THE NEGATIVE CONTROL. avoid_strength 0 must render exactly what the
    effect rendered before this feature existed — proven by running the
    same seed with the steer's own weight zeroed (the only thing avoidance
    can do is add that weighted term; at zero weight it is inert, consumes
    no RNG and touches nothing else) and demanding bit-equal frames."""
    async def main():
        frames = {}
        for tag, cfg, w in (
            ("off", dict(HIS_CROWD, avoid_strength=0.0), FX.AVOID_W),
            ("inert", dict(HIS_CROWD, avoid_strength=0.45), 0.0),
            ("on", dict(HIS_CROWD, avoid_strength=0.45), FX.AVOID_W),
        ):
            orig = FX.AVOID_W
            FX.AVOID_W = w
            try:
                room = await _room(tmp_path, f"av-{tag}", cfg, seed=7)
                seq = []
                for _ in range(600):
                    room.step(1)
                    seq.append(room.frame)
                frames[tag] = np.array([f for f in seq if f is not None])
                await _close(room)
            finally:
                FX.AVOID_W = orig
        assert np.array_equal(frames["off"], frames["inert"]), (
            "avoid_strength=0 must be byte-identical to the effect with no "
            "avoidance term at all"
        )
        assert not np.array_equal(frames["off"], frames["on"]), (
            "the byte-identity proof would be vacuous if avoidance never "
            "changed anything"
        )
    _run(main())


def test_avoidance_can_never_beat_the_turn_cap_or_move_a_fish(tmp_path):
    """HIS TWO LAWS, under a forced crowd: never a reverse on the spot, and
    a turn is always a clear circle. Avoidance is one more term in the
    desired-heading sum, so both hold structurally — assert it anyway,
    against the tightest crowd the effect allows, at full strength."""
    async def main():
        room = await _room(
            tmp_path, "av-cap",
            dict(HIS_CROWD, particle_count=FX.MAX_PARTICLE_COUNT,
                 avoid_strength=1.0, roam_scale=0.3),
            seed=3,
        )
        eff = room.effect
        room.step(120)
        worst_turn, worst_jump = 0.0, 0.0
        prev_hd = eff.p_hd[: eff.n].copy()
        prev_x = eff.p_x[: eff.n].copy() * eff.sx
        prev_y = eff.p_y[: eff.n].copy() * eff.sy
        prev_n = eff.n
        for _ in range(1800):
            room.step(1)
            k = min(prev_n, eff.n)
            if k:
                dh = np.abs(
                    (eff.p_hd[:k] - prev_hd[:k] + np.pi) % (2 * np.pi) - np.pi
                )
                ceil = eff.p_spd[:k] / eff.turn_radius_px * DT
                worst_turn = max(worst_turn, float((dh - ceil).max()))
                step = np.hypot(eff.p_x[:k] * eff.sx - prev_x[:k],
                                eff.p_y[:k] * eff.sy - prev_y[:k])
                allowed = eff.p_spd[:k] * DT
                worst_jump = max(worst_jump, float((step - allowed).max()))
            prev_hd = eff.p_hd[: eff.n].copy()
            prev_x = eff.p_x[: eff.n].copy() * eff.sx
            prev_y = eff.p_y[: eff.n].copy() * eff.sy
            prev_n = eff.n
        assert worst_turn <= 1e-4, (
            "a crowded fish turned faster than its own turn radius allows: "
            f"{np.degrees(worst_turn):.3f} deg past the cap in one frame"
        )
        assert worst_jump <= 1e-3, (
            "avoidance steers headings only — it must never write a "
            f"position: saw a {worst_jump:.4f}px jump past the speed budget"
        )
        await _close(room)
    _run(main())


def test_avoidance_reduces_crossings_at_his_values(tmp_path):
    """The measured half, at the state he is watching (jiggle 0.5,
    roam_scale 0.75). Time spent overlapping is the quantity the eye
    reads; scripts/check_fish_avoidance.py prints the full sweep."""
    async def main():
        got = {}
        for strength in (0.0, 0.45):
            room = await _room(
                tmp_path, f"av-x{strength}",
                dict(HIS_CROWD, avoid_strength=strength), seed=5,
            )
            room.step(120)
            hits = pairs = 0
            for _ in range(1800):
                room.step(1)
                h, p = _crowd_stats(room.effect)
                hits += h
                pairs += p
            got[strength] = hits / max(pairs, 1)
            await _close(room)
        assert got[0.45] < got[0.0] * 0.75, (
            f"avoidance must visibly reduce crossings: overlap "
            f"{got[0.0]:.1%} off -> {got[0.45]:.1%} on (negative control "
            f"{got[0.0]:.1%})"
        )
    _run(main())


def test_school_still_swims_in_unison_with_avoidance_on(tmp_path):
    """The charge's school moves 'almost identically' and the lull's rush is
    deliberately chaotic — both are authored, not crowds to fix. Avoidance
    is off while a school is formed, so it can contribute NOTHING there.

    Proven structurally: both runs settle identically with avoidance off,
    the knob is then changed immediately before the charge, and the school's
    headings must come out bit for bit the same. (Comparing two rooms
    configured differently from birth cannot prove this — their fish are
    already in different places by the time the charge starts, and the
    school's own separation steer, added 2026-08-28, reads those positions.)
    """
    async def main():
        headings = {}
        for strength in (0.0, 1.0):
            room = await _room(
                tmp_path, f"av-s{strength}",
                dict(HIS_CROWD, avoid_strength=0.0), seed=9,
            )
            room.step(240)                      # identical settle, both runs
            room.effect.update_config({"avoid_strength": strength})
            room.ramp("charge", 2.5)
            eff = room.effect
            assert eff._school_on, "the charge must have formed a school"
            assert eff.avoid_strength == strength
            live = eff.p_mode[: eff.n] < 2
            headings[strength] = eff.p_hd[: eff.n][live].copy()
            mean = np.arctan2(
                np.sin(headings[strength]).mean(),
                np.cos(headings[strength]).mean(),
            )
            spread = float(np.abs(
                (headings[strength] - mean + np.pi) % (2 * np.pi) - np.pi
            ).max())
            assert spread < 0.5, (
                "the school must still move almost identically "
                f"(spread {np.degrees(spread):.1f} deg at "
                f"avoid_strength {strength})"
            )
            await _close(room)
        assert np.array_equal(headings[0.0], headings[1.0]), (
            "avoidance changed the school's headings — it must be off "
            "entirely while a school is formed"
        )
    _run(main())


# ── the lunge: a strong beat is a real dash, not a blip ─────────────────
def _beat_envelope(room, on):
    """Drive the two signals draw() reads so a beat's spike reaches 1.0 the
    way it does in a real room (headless audio is silenced, so an
    undriven beat caps at draw()'s own 0.4 floor)."""
    eff = room.effect
    eff.impulse = float(on)
    eff.slow = 0.30 * float(on)


def _travel_after_beat(room, seconds=1.0, loud=True):
    """Mean path length each fish covers, in body lengths."""
    eff = room.effect
    eff._beat_pending = True
    env = 1.0
    n = eff.n
    px = eff.p_x[:n].copy() * eff.sx
    py = eff.p_y[:n].copy() * eff.sy
    dist = np.zeros(n)
    for _ in range(int(seconds / DT)):
        if loud:
            _beat_envelope(room, env)
            env *= 0.5 ** (DT / 0.25)
        room.step(1)
        k = min(n, eff.n)
        nx = eff.p_x[:k] * eff.sx
        ny = eff.p_y[:k] * eff.sy
        dist[:k] += np.hypot(nx - px[:k], ny - py[:k])
        px[:k], py[:k] = nx, ny
    return float(dist[: eff.n].mean()) / eff._body_len_px()


def test_a_strong_beat_covers_several_body_lengths(tmp_path):
    """His diagnosis: the ripple correctly sized itself off real speed and
    flap, but the beat's speed boost decayed within tens of ms, so a big
    ring rode a tiny travel. The lunge holds the boost, so a strong beat is
    a real dash. Measured in body lengths, against the pre-lunge control.
    scripts/check_fish_lunge.py prints the full sweep."""
    async def main():
        got = {}
        for tag, gain in (("off", 0.0), ("on", FX.LUNGE_GAIN)):
            orig = FX.LUNGE_GAIN
            FX.LUNGE_GAIN = gain
            try:
                room = await _room(tmp_path, f"lunge-{tag}",
                                   dict(HIS_CROWD, particle_count=4), seed=5)
                room.step(180)
                got[tag] = _travel_after_beat(room)
                await _close(room)
            finally:
                FX.LUNGE_GAIN = orig
        assert got["on"] >= got["off"] * 1.5, (
            "a strong beat must cover a real dash: "
            f"{got['off']:.2f} -> {got['on']:.2f} body lengths in 1s "
            f"(negative control {got['off']:.2f})"
        )
        assert got["on"] >= 3.0, (
            f"a strong beat should cover several body lengths, saw "
            f"{got['on']:.2f}"
        )
    _run(main())


def test_quiet_swimming_is_untouched_by_the_lunge(tmp_path):
    """The envelope arms only above LUNGE_SPIKE_MIN, so at zero impulse
    nothing is armed, nothing decays, and cruise is bit-for-bit what it
    always was."""
    async def main():
        frames, speeds = {}, {}
        for tag, gain in (("off", 0.0), ("on", FX.LUNGE_GAIN)):
            orig = FX.LUNGE_GAIN
            FX.LUNGE_GAIN = gain
            try:
                room = await _room(tmp_path, f"calm-{tag}",
                                   dict(HIS_CROWD, particle_count=4), seed=5)
                seq = []
                for _ in range(900):
                    room.step(1)
                    seq.append(room.frame)
                eff = room.effect
                assert not np.any(eff.p_lun[: eff.n]), (
                    "no beat, no impulse — the lunge must never arm"
                )
                speeds[tag] = float(eff.p_spd[: eff.n].mean())
                frames[tag] = np.array([f for f in seq if f is not None])
                await _close(room)
            finally:
                FX.LUNGE_GAIN = orig
        assert np.array_equal(frames["off"], frames["on"]), (
            "quiet swimming must be byte-identical with and without the lunge"
        )
        assert abs(speeds["on"] - speeds["off"]) < 1e-9, (
            f"cruise moved at zero impulse: {speeds['off']} -> {speeds['on']}"
        )
    _run(main())


# ── the swim burst, held on screen ──────────────────────────────────────
async def _burst_excursion(tmp_path, name, seed, burst_on):
    """(worst px any fish CENTRE lands past the panel edge, fastest speed
    of a fish more than 8px clear of it while bursting) over 12s of a
    300ms burst every 400ms, at his Matrix entry's own pond (the schema's
    roam_scale) with a full population — the shape that reproduced his
    report."""
    room = await _room(tmp_path, name,
                       dict(HIS_MATRIX, particle_count=12), seed=seed)
    eff = room.effect
    room.step(120)
    worst_off = -1e9
    clear_speed = 0.0
    period_frames = round(0.4 / DT)
    burst_frames = round(0.3 / DT)
    for i in range(round(12.0 / DT)):
        eff.swim_burst = burst_on and (i % period_frames) < burst_frames
        room.step(1)
        n = eff.n
        if n:
            sx = eff.cx + eff.p_x[:n] * eff.sx - eff.cam_px
            sy = eff.cy + eff.p_y[:n] * eff.sy - eff.cam_py
            off_x = np.maximum(-sx, sx - (COLS - 1))
            off_y = np.maximum(-sy, sy - (ROWS - 1))
            off = np.maximum(off_x, off_y)
            worst_off = max(worst_off, float(np.max(off)))
            if eff.swim_burst:
                clear = off < -8.0
                if clear.any():
                    clear_speed = max(
                        clear_speed, float(np.max(eff.p_spd[:n][clear]))
                    )
    cruise = eff.cruise_px
    await _close(room)
    return worst_off, clear_speed, cruise


def test_swim_burst_stays_on_screen(tmp_path):
    """His live report (2026-09-16): "the fish do scatter, but the burst
    seems a little wrong... they always fly off the screen, but they
    should stay on the screen." scripts/check_fish_burst_bounds.py has the
    full sweep and the root-cause writeup (a fixed-time-constant heading
    correction lets a burst-speed fish outrun it). Measured against two
    controls on the real pipeline: the same bursts with the boundary brake
    switched off (must reproduce the overshoot, or this test proves
    nothing) and no burst at all (the soft steer's own resting overshoot).
    The fixed burst must land within a pixel of the no-burst baseline, and
    — the "not a soft no-op" half — a fish clear of the edge must still
    reach well above cruise while bursting."""
    async def main():
        for seed in (3, 7):
            base, _, _ = await _burst_excursion(
                tmp_path, f"burst-none-{seed}", seed, burst_on=False
            )
            orig = FX.BOUND_BRAKE_AT
            FX.BOUND_BRAKE_AT = 1.0
            try:
                unbraked, _, _ = await _burst_excursion(
                    tmp_path, f"burst-unbraked-{seed}", seed, burst_on=True
                )
            finally:
                FX.BOUND_BRAKE_AT = orig
            held, clear_speed, cruise = await _burst_excursion(
                tmp_path, f"burst-held-{seed}", seed, burst_on=True
            )
            assert unbraked > base + 3.0, (
                f"seed {seed}: the negative control must overshoot, saw "
                f"{unbraked:.2f}px against a no-burst {base:.2f}px"
            )
            assert held <= base + 1.0, (
                f"seed {seed}: a repeated burst carried a fish "
                f"{held:.2f}px past the panel edge (no-burst baseline "
                f"{base:.2f}px, unbraked {unbraked:.2f}px)"
            )
            assert clear_speed >= 2.0 * cruise, (
                f"seed {seed}: the burst reads as a soft no-op away from "
                f"the edge: fastest clear-of-edge speed {clear_speed:.1f} "
                f"px/s against cruise {cruise:.1f} px/s"
            )
    _run(main())


# ── tail-stroke thrust + the dial back to tonight's smooth motion ───────
def test_drift_speed_dial_reaches_both_endpoints(tmp_path):
    """His explicit design requirement (section 4 of the brief): raising
    min_drift_speed to its max with stroke_speed_cap at 0 must render the
    old smooth, non-pulsing motion; the opposite corner (floor drift, an
    open cap) must fully express surge-and-coast. Every other source of
    speed noise (jiggle, speed_jump, speed_jog) is zeroed so the dial is
    the only thing that can still move `p_spd`."""
    async def main():
        base_cfg = dict(
            HIS_MATRIX, particle_count=1, jiggle=0.0, speed_jump=0.0,
            speed_jog=0.0, horizon_scale=0.0, spin=0.0, roam_scale=1.4,
        )

        async def cycle_speeds(tag, min_drift, cap):
            room = await _room(tmp_path, f"dial-{tag}", dict(
                base_cfg, min_drift_speed=min_drift, stroke_speed_cap=cap,
            ), seed=1)
            eff = room.effect
            room.step(int(2.0 / DT))  # let it settle
            spds = []
            for _ in range(int(3.0 / DT)):
                room.step(1)
                spds.append(float(eff.p_spd[0]))
            await _close(room)
            return np.array(spds)

        smooth = await cycle_speeds("smooth", 1.0, 0.0)
        rng_smooth = (smooth.max() - smooth.min()) / max(smooth.mean(), 1e-6)
        assert rng_smooth < 1e-4, (
            "min_drift_speed=1/stroke_speed_cap=0 must show no perceptible "
            f"pulse: speed varied {rng_smooth:.2%} of its mean"
        )

        pulsed = await cycle_speeds("pulsed", 0.0, 1.0)
        rng_pulsed = (pulsed.max() - pulsed.min()) / max(pulsed.mean(), 1e-6)
        assert rng_pulsed > 0.5, (
            "min_drift_speed=0/stroke_speed_cap=1 must fully express "
            f"surge-and-coast: speed only varied {rng_pulsed:.2%} of its "
            "mean"
        )
        assert pulsed.min() < 0.05 * pulsed.max(), (
            "the coast between strokes must actually approach a stop, not "
            "just dip"
        )
    _run(main())


def test_stroke_cap_zero_is_bit_for_bit_the_old_continuous_target(tmp_path):
    """The stronger form of the smooth endpoint above: with no lunge/jog/
    jiggle noise and constant (silenced) audio, `want_full` is a plain
    constant, so `p_spd` must settle to a single value and STAY there —
    not merely have a small range."""
    async def main():
        room = await _room(tmp_path, "dial-const", dict(
            HIS_MATRIX, particle_count=2, jiggle=0.0, speed_jump=0.0,
            speed_jog=0.0, horizon_scale=0.0, spin=0.0, roam_scale=1.4,
            min_drift_speed=1.0, stroke_speed_cap=0.0,
        ), seed=1)
        eff = room.effect
        room.step(int(2.0 / DT))
        settled = eff.p_spd[: eff.n].copy()
        for _ in range(int(2.0 / DT)):
            room.step(1)
        assert np.allclose(eff.p_spd[: eff.n], settled, atol=1e-6), (
            "with the stroke cap at 0 the settled speed must never move "
            "again — any further motion would be a leftover pulse"
        )
        await _close(room)
    _run(main())


def test_default_dial_preserves_the_old_mean_speed(tmp_path):
    """His ruling (2026-09-17), after a rebase onto #279's swim-burst
    boundary brake caught the first-shipped defaults (0.6/0.45) running a
    real, unasked-for ~23% slower on average: "A pulse should redistribute
    speed in time, not reduce the average." The shipped defaults
    (min_drift_speed=0.85, stroke_speed_cap=0.4) are DERIVED, not tuned by
    eye, to solve `min_drift_speed + stroke_speed_cap * 0.375 == 1.0` (see
    PULSE_SHAPE_CYCLE_MEAN's own comment in fish.py) — so measured against
    the dial's neutral setting (min_drift_speed=1, stroke_speed_cap=0,
    already proven bit-for-bit the pre-thrust formula), the mean speed at
    the SHIPPED DEFAULTS over several full stroke cycles must stay within
    1% of the old smooth target. Close, not exact: that equation is
    first-order — the flap phase runs faster through the surge (flap_freq
    rises with speed), so the measured mean lands slightly low (0.16%)."""
    async def main():
        base_cfg = dict(
            HIS_MATRIX, particle_count=1, jiggle=0.0, speed_jump=0.0,
            speed_jog=0.0, horizon_scale=0.0, spin=0.0, roam_scale=1.4,
        )

        async def mean_speed(tag, min_drift, cap):
            room = await _room(tmp_path, f"meanspd-{tag}", dict(
                base_cfg, min_drift_speed=min_drift, stroke_speed_cap=cap,
            ), seed=1)
            eff = room.effect
            room.step(int(2.0 / DT))  # settle
            spds = []
            for _ in range(int(6.0 / DT)):  # several full flap cycles
                room.step(1)
                spds.append(float(eff.p_spd[0]))
            await _close(room)
            return float(np.mean(spds))

        old_smooth = await mean_speed("neutral", 1.0, 0.0)
        default = await mean_speed("default", 0.85, 0.4)
        rel_err = abs(default - old_smooth) / old_smooth
        assert rel_err < 0.01, (
            f"the shipped default dial must keep the old mean speed "
            f"within 1%: "
            f"neutral (pre-thrust) mean {old_smooth:.3f} px/s, default "
            f"mean {default:.3f} px/s, {rel_err:.2%} off — a pulse must "
            f"redistribute speed in time, not reduce the average"
        )
    _run(main())


def test_dial_floor_and_cap_both_at_zero_never_freezes(tmp_path):
    """Found by review: `min_drift_speed` and `stroke_speed_cap` are each
    independently legitimate at 0 (the "pure surge and coast" and "no
    pulse" endpoints, respectively), but SET TOGETHER `pulsed_want` would
    be a permanent, exact zero for every ordinary swimmer — not a
    momentary trough, a speed that never recovers, freezing heading too
    (`omega_max = p_spd / turn_radius_px`) and stranding an off-panel
    entering fish forever. `MOTION_FLOOR_FRAC` exists to keep this
    reachable-but-nonsensical combination from ever being a true freeze."""
    async def main():
        room = await _room(tmp_path, "dial-zero-zero", dict(
            HIS_MATRIX, particle_count=1, jiggle=0.0, speed_jump=0.0,
            speed_jog=0.0, horizon_scale=0.0, spin=0.0, roam_scale=1.4,
            min_drift_speed=0.0, stroke_speed_cap=0.0,
        ), seed=1)
        eff = room.effect
        # an entering fish must actually reach the pond within a bounded
        # time, not stay mode=1 (entering) forever
        for _ in range(int(20.0 / DT)):
            room.step(1)
            if eff.n and eff.p_mode[0] == 0:
                break
        assert eff.n and eff.p_mode[0] == 0, (
            "an entering fish never reached the pond at min_drift_speed=0, "
            "stroke_speed_cap=0 — the population can visibly stall"
        )
        speeds = []
        for _ in range(int(2.0 / DT)):
            room.step(1)
            speeds.append(float(eff.p_spd[0]))
        assert min(speeds) > 0.0, (
            "speed must never be a literal, permanent zero: "
            f"saw {speeds}"
        )
        await _close(room)
    _run(main())


@pytest.mark.parametrize("name", ["min_drift_speed", "stroke_speed_cap"])
def test_the_dial_is_reachable_by_sonic_with_the_effects_own_bounds(name):
    """The dial is only an escape hatch if Sonic and the Scenes page can
    reach it, and both read the shared registry, not the effect schema: a
    param missing there is refused by name. Its registry range and default
    must also be the ones the effect itself validates against."""
    import voluptuous as vol
    from fx import device_model
    from spectra.services import scene_console

    info = scene_console.get_param_info("fish", name)
    assert info["type"] == "numeric"
    assert info["default"] == device_model.resting_default("fish", name)
    schema = FX.Fish2d.schema()
    assert schema({})[name] == info["default"]
    assert schema({name: info["min"]})[name] == info["min"]
    assert schema({name: info["max"]})[name] == info["max"]
    for outside in (info["min"] - 1e-3, info["max"] + 1e-3):
        with pytest.raises(vol.Invalid):
            schema({name: outside})


def test_slow_music_reads_as_distinct_pushes_fast_blurs_them(tmp_path):
    """Section 6 of the brief: this falls out of the stroke being real
    thrust, not a bolt-on jitter. Quiet/low-impulse audio lowers
    `want_full`, which lowers speed_norm, which lowers the tail's own flap
    frequency — so the SAME fixed-time-constant speed ease has to track a
    slower oscillation in a quiet section (little attenuation, individual
    pushes read distinctly) and a much faster one in a loud section (heavy
    attenuation, pushes blur together)."""
    async def main():
        cfg = dict(
            HIS_MATRIX, particle_count=1, jiggle=0.0, speed_jog=0.0,
            speed_jump=3.0, horizon_scale=0.0, spin=0.0, roam_scale=1.4,
            min_drift_speed=0.3, stroke_speed_cap=0.8,
        )

        async def pulse_range(tag, impulse):
            room = await _room(tmp_path, f"jerk-{tag}", cfg, seed=1)
            eff = room.effect
            eff.impulse = impulse
            eff.slow = impulse * 0.3
            room.step(int(2.0 / DT))
            spds = []
            for _ in range(int(3.0 / DT)):
                eff.impulse = impulse
                eff.slow = impulse * 0.3
                room.step(1)
                spds.append(float(eff.p_spd[0]))
            await _close(room)
            spds = np.array(spds)
            return (spds.max() - spds.min()) / max(spds.mean(), 1e-6)

        slow_range = await pulse_range("slow", 0.03)
        fast_range = await pulse_range("fast", 1.0)
        assert slow_range > 0.15, (
            "a quiet/slow section must show a real, resolvable pulse in "
            f"speed, saw only {slow_range:.2%} of the mean"
        )
        assert fast_range < slow_range * 0.7, (
            "an energetic/fast section must blur strokes together (a "
            "smaller relative pulse, since the same speed-ease time "
            f"constant now tracks a faster oscillation): slow={slow_range:.2%} "
            f"fast={fast_range:.2%}"
        )
    _run(main())


# ── the body IS the head's own recent path ──────────────────────────────
def test_body_trails_the_recorded_path_through_a_turn(tmp_path):
    """His ruling (section 2/3 of the brief): the trailing half of the
    spine is walked back along the fish's own recorded path instead of
    projected along the current heading, so it curves through a turn
    instead of pivoting as a rigid stick to the tangent.

    An ordinary swimming fish never travels in a perfectly straight line
    (the wander term always adds a little swing — that is by design, not
    a bug this feature should fight), so both halves of this proof
    control the recorded trail directly rather than relying on natural
    swimming to happen to be straight: an EXACTLY straight trail must
    reduce to exactly the old rigid layout (the trail IS that line); a
    trail that is straight along an OLD heading, with the CURRENT heading
    turned 90 degrees off it (a fish caught mid-turn), must render
    differently from a body still pivoted to the new heading."""
    async def main():
        room = await _room(tmp_path, "trail-turn", dict(
            HIS_MATRIX, particle_count=1, flap_amount=0.0,
        ), seed=1)
        eff = room.effect
        room.step(5)  # past the birth backfill, onto a real body length

        def render(use_trail):
            n = eff.n
            frame = np.zeros_like(eff.trail)
            eff._draw_bodies(
                frame, np.arange(n),
                eff.p_x[:n].copy(), eff.p_y[:n].copy(),
                eff.p_hd[:n].copy(), np.ones(n, dtype=np.float32),
                np.full(n, eff._half_width_px(), dtype=np.float32),
                np.zeros(n, dtype=np.float32),
                eff.p_grad[:n].copy(), use_trail=use_trail,
            )
            return frame

        def lay_straight_trail(heading):
            eff.p_trail_acc[0] = 1.5
            steps = (
                eff.p_trail_acc[0]
                + np.arange(FX.BODY_TRAIL_LEN, dtype=np.float32)
                * FX.BODY_TRAIL_STEP_PX
            )
            eff.p_trail_x[0, :] = (
                eff.p_x[0] - np.cos(heading) * steps / eff.sx
            )
            eff.p_trail_y[0, :] = (
                eff.p_y[0] - np.sin(heading) * steps / eff.sy
            )

        hd0 = float(eff.p_hd[0])
        lay_straight_trail(hd0)
        straight_trail = render(True)
        straight_rigid = render(False)
        assert np.allclose(straight_trail, straight_rigid, atol=1e-3), (
            "an exactly straight recorded path must render bit-for-bit "
            "the old rigid body — the trail IS that same straight line"
        )

        # the trail still records the OLD heading; the current heading has
        # since turned 90 degrees off it — a fish caught mid-turn
        eff.p_hd[0] = (hd0 + np.pi / 2.0) % (2 * np.pi)
        turned_trail = render(True)
        turned_rigid = render(False)
        assert not np.allclose(turned_trail, turned_rigid, atol=1.0), (
            "with the recorded path pointing one way and the current "
            "heading another, a body walked back along that path must "
            "render differently from one still pivoted to the current "
            "heading"
        )
        await _close(room)
    _run(main())


def test_wake_tail_point_follows_the_trail_not_the_rigid_heading(tmp_path):
    """Found by review: the wake deposit used to lay at the old rigid
    heading projection even after the body-trail rework, so during a real
    turn the wake sat off the actual drawn tail by the same facing-the-
    tangent amount the body itself was fixed for. `_trail_tail_point`
    fixes this by reusing the same recorded-path interpolation
    `_draw_bodies` uses for its own rear nodes — and it is laid in the
    SAME world->screen mapping the body is drawn with, so while the window
    has moved (a charge or lull) the wake sits under its fish instead of
    off to one side by the window's own displacement, as the pre-rework
    deposit (`cx + p_x*sx - cos(hd)*len/2`, no window origin) laid it."""
    async def main():
        room = await _room(tmp_path, "wake-tail", dict(
            HIS_MATRIX, particle_count=1, flap_amount=0.0,
        ), seed=1)
        eff = room.effect
        room.step(5)

        def lay_straight_trail(heading):
            eff.p_trail_acc[0] = 1.5
            steps = (
                eff.p_trail_acc[0]
                + np.arange(FX.BODY_TRAIL_LEN, dtype=np.float32)
                * FX.BODY_TRAIL_STEP_PX
            )
            eff.p_trail_x[0, :] = (
                eff.p_x[0] - np.cos(heading) * steps / eff.sx
            )
            eff.p_trail_y[0, :] = (
                eff.p_y[0] - np.sin(heading) * steps / eff.sy
            )

        def rigid_tail(hd, length):
            px = eff.cx + eff.p_x[0] * eff.sx - eff.cam_px
            py = eff.cy + eff.p_y[0] * eff.sy - eff.cam_py
            return (
                px - np.cos(hd) * length * 0.5,
                py - np.sin(hd) * length * 0.5,
            )

        length = eff._half_width_px() * 2.0 * eff.body_aspect
        hd0 = float(eff.p_hd[0])
        lay_straight_trail(hd0)

        # a straight run: the trail-based tail must match the rigid one
        tx, ty = eff._trail_tail_point(
            np.array([0]), eff.p_x[:1].copy(), eff.p_y[:1].copy(),
            np.array([length], dtype=np.float32),
        )
        rx, ry = rigid_tail(hd0, length)
        assert abs(float(tx[0]) - rx) < 1e-2 and abs(float(ty[0]) - ry) < 1e-2, (
            "on a straight run the trail-based tail must match the old "
            f"rigid one: trail=({tx[0]:.3f},{ty[0]:.3f}) "
            f"rigid=({rx:.3f},{ry:.3f})"
        )

        # a fish caught mid-turn: the trail still records the OLD heading,
        # the current heading has since turned 90 degrees off it — the
        # trail-based tail must NOT match the rigid projection along the
        # new heading (that mismatch is exactly the bug)
        hd_new = (hd0 + np.pi / 2.0) % (2 * np.pi)
        eff.p_hd[0] = hd_new
        tx2, ty2 = eff._trail_tail_point(
            np.array([0]), eff.p_x[:1].copy(), eff.p_y[:1].copy(),
            np.array([length], dtype=np.float32),
        )
        rx2, ry2 = rigid_tail(hd_new, length)
        dist = float(np.hypot(tx2[0] - rx2, ty2[0] - ry2))
        assert dist > 1.0, (
            "mid-turn, the wake's trail-based tail point must diverge "
            f"from the rigid heading projection, saw only {dist:.3f}px "
            "apart"
        )
        # ... and it must still be close to the OLD heading's rigid point
        # (the direction the body actually came from)
        rx_old, ry_old = rigid_tail(hd0, length)
        dist_old = float(np.hypot(tx2[0] - rx_old, ty2[0] - ry_old))
        assert dist_old < 1.0, (
            "the trail-based tail should still track where the body "
            f"actually came from, saw {dist_old:.3f}px off the old "
            "heading's own rigid point"
        )

        # the window has moved: the tail point is laid in screen space,
        # under the fish as drawn, never in the unshifted world frame
        eff.p_hd[0] = hd0
        lay_straight_trail(hd0)
        eff.cam_px, eff.cam_py = 17.0, -6.0
        tx3, ty3 = eff._trail_tail_point(
            np.array([0]), eff.p_x[:1].copy(), eff.p_y[:1].copy(),
            np.array([length], dtype=np.float32),
        )
        rx3, ry3 = rigid_tail(hd0, length)
        assert abs(float(tx3[0]) - rx3) < 1e-2 and abs(float(ty3[0]) - ry3) < 1e-2, (
            "with the window moved the wake tail must sit under the drawn "
            f"fish: trail=({tx3[0]:.3f},{ty3[0]:.3f}) "
            f"screen=({rx3:.3f},{ry3:.3f})"
        )
        unshifted = float(np.hypot(
            tx3[0] - (rx3 + eff.cam_px), ty3[0] - (ry3 + eff.cam_py)
        ))
        assert unshifted > 15.0, (
            "the moved-window case must be able to tell screen space from "
            f"the unshifted world frame, saw only {unshifted:.3f}px apart"
        )
        await _close(room)
    _run(main())


def test_body_trail_backfill_seeds_a_real_body_on_the_first_frame(tmp_path):
    """A fish born this frame has no recorded path yet — it must be
    backfilled straight back along its own heading immediately, not left
    collapsed to a point (NaN) for its first rendered frames."""
    async def main():
        room = await _room(tmp_path, "trail-backfill", dict(
            HIS_MATRIX, particle_count=4,
        ), seed=9)
        room.step(1)
        eff = room.effect
        n = eff.n
        assert n > 0
        assert np.all(np.isfinite(eff.p_trail_x[:n])), (
            "every fish must have a fully seeded trail by its first frame"
        )
        assert np.all(np.isfinite(eff.p_trail_y[:n]))
        await _close(room)
    _run(main())


def _record_rear_body(eff):
    """Wrap the effect's real body layout and record, per drawn fish, how
    far each trailing spine node sits from the fish's centre against how far
    it should (its share of the body length). Read off the exact points the
    effect splats (the zero-smear substep, lateral throw off)."""
    records = []
    orig_draw = eff._draw_bodies
    m = FX.SPINE_U.size
    n_front = int(np.count_nonzero(FX.SPINE_U <= 0.5))

    def draw_bodies(frame, idx, x, y, hd, bright, half_w, flap_amp, grad,
                    use_trail=True):
        captured = {}
        orig_splat = eff._splat_many

        def splat(buf, xs, ys, rgb, sizes):
            captured["xs"], captured["ys"] = xs, ys
            return orig_splat(buf, xs, ys, rgb, sizes)

        eff._splat_many = splat
        try:
            orig_draw(frame, idx, x, y, hd, bright, half_w, flap_amp, grad,
                      use_trail=use_trail)
        finally:
            del eff._splat_many
        k = len(idx)
        if k == 0 or not use_trail:
            return
        nx = captured["xs"][-k * m:].reshape(k, m)[:, n_front:]
        ny = captured["ys"][-k * m:].reshape(k, m)[:, n_front:]
        cx = eff.cx + np.asarray(x) * eff.sx - eff.cam_px
        cy = eff.cy + np.asarray(y) * eff.sy - eff.cam_py
        length = np.asarray(half_w) * 2.0 * eff.body_aspect
        want = (FX.SPINE_U[n_front:][None, :] - 0.5) * length[:, None]
        got = np.hypot(nx - cx[:, None], ny - cy[:, None])
        heading = np.asarray(hd)
        behind = -(
            (nx - cx[:, None]) * np.cos(heading)[:, None]
            + (ny - cy[:, None]) * np.sin(heading)[:, None]
        )
        records.append((
            np.asarray(idx).copy(), eff.p_mode[np.asarray(idx)].copy(),
            got / want, behind / want, bool(eff._school_on),
        ))

    eff._draw_bodies = draw_bodies
    return records


def test_rear_body_holds_its_length_every_frame_while_swimming(tmp_path):
    """The trailing half of the spine walks back along the recorded path by
    TRUE path distance: trail[0] lies `p_trail_acc` behind the fish, not a
    whole sample. Laid out as if it were a whole sample, the tail collapsed
    onto the centre after every push and regrew — a body pumping between
    nothing and full length several times a second on a straight run."""
    async def main():
        room = await _room(tmp_path, "trail-length", dict(
            HIS_MATRIX, flap_amount=0.0,
        ), seed=3)
        eff = room.effect
        room.step(30)
        records = _record_rear_body(eff)
        room.step(int(4.0 / DT))
        await _close(room)
        ratios = np.concatenate([r.ravel() for _i, _m, r, _b, _s in records])
        assert ratios.size > 0
        assert ratios.min() >= 0.9, (
            "a swimming fish's tail must never collapse toward its centre: "
            f"worst rear node sat at {ratios.min():.2f} of its length"
        )
        assert ratios.max() <= 1.001, (
            "a swimming fish's tail must never stretch past its own length: "
            f"worst rear node sat at {ratios.max():.2f} of its length"
        )
    _run(main())


def test_drop_ejecta_keep_a_compact_body_even_past_a_sample_per_frame(
        tmp_path):
    """Drop ejecta hold a fixed heading and speed but still travel, so their
    path must be recorded like any other fish's — including one fast enough
    to cross several samples in a single frame — or the tail strings back
    toward where it was born."""
    async def main():
        room = await _room(tmp_path, "trail-ejecta", dict(
            HIS_MATRIX, flap_amount=0.0,
        ), seed=7)
        eff = room.effect
        room.step(30)
        base = eff.n
        eff._spawn_drop_ejecta(6)
        assert eff.n > base
        eff.p_spd[eff.n - 1] = 3.0 * FX.BODY_TRAIL_STEP_PX / DT
        records = _record_rear_body(eff)
        room.step(20)
        await _close(room)
        ejecta = [
            r[m == 2] for _i, m, r, _b, _s in records if np.any(m == 2)
        ]
        assert ejecta, "no ejecta were drawn"
        ratios = np.concatenate([r.ravel() for r in ejecta])
        assert 0.97 <= ratios.min() and ratios.max() <= 1.001, (
            "an ejected fish must keep its own body length: rear nodes sat "
            f"between {ratios.min():.2f} and {ratios.max():.2f} of it"
        )
    _run(main())


def test_rear_body_rides_the_water_while_the_school_is_clamped(tmp_path):
    """With the window pinned to the shoal (camera_follow=0) the school
    clamp takes a lined-up fish's whole travel out of the world and puts it
    into the water. Its body must still trail the path it swam THROUGH that
    water: recorded in the world alone, the path stops advancing, and the
    samples laid while the fish turned onto the school heading sit in front
    of it, folding the tail forward over the head."""
    async def main():
        room = await _room(tmp_path, "trail-school", dict(
            HIS_MATRIX, flap_amount=0.0, camera_follow=0.0,
        ), seed=3)
        eff = room.effect
        room.step(60)
        records = _record_rear_body(eff)
        room.ramp("charge", 4.0, beats_every=30)
        schooled = eff._school_on
        await _close(room)
        assert schooled, "the charge must have formed a school"
        behind = [
            b[m < 2] for _i, m, _r, b, s in records if s and np.any(m < 2)
        ]
        assert behind, "no schooling fish were drawn"
        behind = np.concatenate([b.ravel() for b in behind])
        assert behind.min() >= 0.7, (
            "a schooling fish's tail must lie behind its head along the "
            f"path it swam: a rear node sat at {behind.min():.2f} of its "
            "length behind the centre"
        )
    _run(main())
