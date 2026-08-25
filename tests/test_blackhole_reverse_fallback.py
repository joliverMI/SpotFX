"""The momentary reverse flare's RELEASE turns blobs around; it never flips
them (his ask, 2026-08-24: "I want them to accelerate back to the black
hole, but not immediately change direction... The current setting is too
jerky").

Frame-level, on the real vendored pipeline (fx.headless dummy Matrix host,
audio silenced). scripts/check_blackhole_reverse_fallback.py is the
measured, printed version of the same run — this file pins the properties.

The captive question is deliberately covered here too: PR #179 fixed the
same reported snap by RELEASING every horizon captive on every frame while
reversed, and was reverted the same day (#181, no reason recorded). This
mechanism releases nobody — see Blackhole2d._arm_reverse_fallback's
docstring — so `test_reverse_flare_never_evicts_a_horizon_captive` is the
guard against relanding that shape by accident."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import blackhole as bh

DT = 1.0 / 60.0
HOLD_S = 0.5     # his authored "Reverse Momentarily (500ms)"

# his real Black Hole V2 Matrix entry (bound params at their own fallbacks)
HIS_MATRIX = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "x_offset": 0.5, "y_offset": 0.5, "horizon_audio": 0.3, "base_speed": 2.0,
    "accel": 5.0, "spawn_rate": 6.0, "beat_burst": 0, "spawn_audio": 1.5,
    "speed_audio": 2.0, "impulse_decay": 0.06, "max_blobs": 50,
    "edge_speed": 0.2, "horizon_hold": 2.8,
}


async def _flare(tmp_path, sub, *, hold_s=HOLD_S, warmup_s=4.0, settle_s=1.5):
    """Populate, freeze spawning, run one reverse flare, watch the release.
    Returns the tracked blob's per-frame radial velocity plus the captive
    census either side of the flare."""
    host = await headless.start_headless_host(
        str(tmp_path / sub), device_id=sub, pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get(sub)
    trace = []
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole", dict(HIS_MATRIX))

        def step(n):
            for _ in range(n):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)

        step(int(warmup_s / DT))
        # freeze the population: stable compaction order, so index 0 is the
        # same blob on every frame of the measurement
        effect.update_config({"spawn_rate": 0.0, "beat_burst": 0})
        step(int(0.2 / DT))
        caps_before = int(np.count_nonzero(effect.p_cap[: effect.n] >= 0.0))
        cap_age_before = float(np.max(effect.p_cap[: effect.n]))

        effect.update_config({"reverse": True})
        step(max(int(hold_s / DT), 1))
        r_release = float(effect.p_r[0])
        v_release = float(effect.base_speed * (
            effect.edge_speed + (1.0 - effect.edge_speed)
            * np.clip(1.0 - r_release, 0.0, 1.0) ** effect.accel))
        r_all = effect.p_r[: effect.n].copy()

        effect.update_config({"reverse": False})
        step(1)
        release_jump = float(np.max(np.abs(effect.p_r[: len(r_all)] - r_all)))
        prev_r = float(effect.p_r[0])
        for _ in range(int(settle_s / DT)):
            clock.advance(DT)
            frame = virtual.assemble_frame()
            if frame is not None:
                virtual.flush(frame)
            if effect.n == 0:
                break
            r_now = float(effect.p_r[0])
            trace.append({
                "r": r_now, "v": (r_now - prev_r) / DT,
                "turning": bool(effect.p_turn[0]),
                "curve_v": float(effect.base_speed * (
                    effect.edge_speed + (1.0 - effect.edge_speed)
                    * np.clip(1.0 - r_now, 0.0, 1.0) ** effect.accel)),
            })
            prev_r = r_now
        caps_after = int(np.count_nonzero(effect.p_cap[: effect.n] >= 0.0))
        cap_age_after = float(np.max(effect.p_cap[: effect.n]))
    await host.shutdown()
    return {
        "trace": trace, "v_release": v_release, "release_jump": release_jump,
        "caps_before": caps_before, "caps_after": caps_after,
        "cap_age_before": cap_age_before, "cap_age_after": cap_age_after,
    }


def test_release_velocity_is_continuous_through_zero(tmp_path):
    """The blob keeps moving outward, decelerates, passes through zero and
    falls back — never a one-frame sign flip (which at his config would be
    a 2*v = ~0.9 r/s step)."""
    res = asyncio.run(_flare(tmp_path, "cont"))
    vs = [s["v"] for s in res["trace"]]
    assert vs, "no frames captured"
    crossings = [i for i in range(len(vs) - 1) if vs[i] > 0 >= vs[i + 1]]
    assert len(crossings) == 1, f"expected one zero crossing, got {len(crossings)}"
    i = crossings[0]
    # bound: one frame of the turn's own deceleration (2*v/TURN_S * dt),
    # with margin for v's drift as the blob moves — vs the pre-fix 2*v flip
    bound = 2.0 * res["v_release"] / bh.REVERSE_FALLBACK_TURN_S * DT * 1.5
    assert abs(vs[i + 1] - vs[i]) <= bound
    assert abs(vs[i + 1] - vs[i]) < (2.0 * res["v_release"]) / 4.0


def test_deceleration_is_monotonic_and_merges_onto_the_speed_curve(tmp_path):
    """Monotonic through the turn, and the first frame after it moves at the
    infall curve's own speed for that radius — no step at the seam either
    (the trap p_out's own expiry falls into: stall to zero, then full speed
    inward on the next frame)."""
    res = asyncio.run(_flare(tmp_path, "merge"))
    trace = res["trace"]
    turning = [s for s in trace if s["turning"]]
    assert len(turning) > 10, "the turn should span many frames"
    tv = [s["v"] for s in turning]
    assert all(tv[i + 1] <= tv[i] + 1e-6 for i in range(len(tv) - 1))
    assert tv[0] > 0 and tv[-1] < 0
    # the turn takes about REVERSE_FALLBACK_TURN_S, whatever base_speed is
    assert 0.6 * bh.REVERSE_FALLBACK_TURN_S <= len(turning) * DT <= 1.6 * bh.REVERSE_FALLBACK_TURN_S
    merged = next(s for s in trace if not s["turning"])
    assert merged["v"] < 0
    assert abs(abs(merged["v"]) - merged["curve_v"]) < 0.05 * merged["curve_v"] + 1e-3


def test_nothing_teleports_at_the_release(tmp_path):
    """No blob — captive or free — moves more than one ordinary frame of
    travel on the release frame. This is the stale-capture snap PR #179
    measured at 0.300 normalized-r in one frame."""
    res = asyncio.run(_flare(tmp_path, "snap"))
    assert res["release_jump"] <= res["v_release"] * DT * 1.5 + 1e-4


def test_reverse_flare_never_evicts_a_horizon_captive(tmp_path):
    """Every captive keeps its capture across the flare, and its hold clock
    keeps running — so the ring's population still turns over. PR #179
    cleared `p_cap` for every captive on every reversed frame, which also
    made evicted blobs immortal (the infall alive-test retires captives by
    their hold clock and never free-fallers) and gave them a fresh full
    hold on re-capture."""
    res = asyncio.run(_flare(tmp_path, "captive"))
    assert res["caps_before"] > 0, "warm-up should have populated the ring"
    assert res["caps_after"] >= res["caps_before"]
    assert res["cap_age_after"] > res["cap_age_before"]


def test_a_short_blip_keeps_every_captive_on_the_ring(tmp_path):
    """Two frames of reverse: at his speeds that is already enough to carry
    an orbiter off the ring, so this is the case a release-on-edge rule
    would still have evicted. Nothing is released here at all."""
    res = asyncio.run(_flare(tmp_path, "blip", hold_s=2 * DT, settle_s=0.2))
    assert res["caps_before"] > 0
    assert res["caps_after"] >= res["caps_before"]


def test_the_outward_eject_is_still_instant(tmp_path):
    """His liked half is untouched: reverse turning ON ejects immediately —
    no easing in, no turn state left over."""
    async def run():
        host = await headless.start_headless_host(
            str(tmp_path / "eject"), device_id="eject",
            pixel_count=72 * 37, rows=37)
        virtual = host.virtuals.get("eject")
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(
                host, virtual, "blackhole", dict(HIS_MATRIX))

            def step(n):
                for _ in range(n):
                    clock.advance(DT)
                    frame = virtual.assemble_frame()
                    if frame is not None:
                        virtual.flush(frame)

            step(int(3.0 / DT))
            effect.update_config({"spawn_rate": 0.0, "beat_burst": 0})
            step(int(0.2 / DT))
            # mid-turn when the next eject arrives: the turn is abandoned
            effect.update_config({"reverse": True})
            step(int(0.3 / DT))
            effect.update_config({"reverse": False})
            step(int(0.1 / DT))
            turning_mid = bool(effect.p_turn[: effect.n].any())
            before = effect.p_r[: effect.n].copy()
            effect.update_config({"reverse": True})
            step(1)
            after = effect.p_r[: len(before)]
            moved_out = bool(np.all(after >= before - 1e-6))
            still_turning = bool(effect.p_turn[: effect.n].any())
        await host.shutdown()
        return turning_mid, moved_out, still_turning

    turning_mid, moved_out, still_turning = asyncio.run(run())
    assert turning_mid, "the release should have armed a turn to interrupt"
    assert moved_out, "every blob moves outward on the very first ejected frame"
    assert not still_turning, "the eject abandons the turn, it never eases"
