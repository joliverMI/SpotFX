"""Black Hole reverse flare release: ex-captives must fall back in at the
shared per-radius speed, never teleport (his report, 2026-08-21: "the
particles that left the Event Horizon shoot back really fast... or if
there's another reason I'm seeing this snap back").

Root cause proven in scripts/check_blackhole_reverse_snapback.py (run
against his real Black Hole V2 config): there was never a speed asymmetry —
draw()'s `new_r = r ± v*dt` uses one formula both directions — but `p_cap`
was never released when `reverse` flipped on, so every blob orbiting the
horizon kept its captured marker while the outflow carried it off the ring,
and on the flip back `np.where(captured, rh, new_r)` teleported the whole
cohort onto the horizon in a single frame (86x the legitimate per-frame
movement at his real measured 1160ms hold; 40x at the authored 500ms). The
fix releases captives while reversed; the return is ordinary free-fall plus
re-capture. Proven red against the pre-fix module, green after.

blackhole1d has no capture mechanism at all (pure sign-flip, symmetric) —
no 1d sibling test needed; this is a 2D-only defect.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless

DT = 1.0 / 60.0

CONFIG = {
    # his Black Hole V2 Matrix scalars, spawn_rate raised for a fast test
    "horizon_scale": 0.2,
    "horizon_audio": 0.3,
    "horizon_hold": 2.8,
    "base_speed": 2,
    "accel": 5,
    "edge_speed": 0.2,
    "max_blobs": 50,
    "spawn_rate": 3.0,
    "reverse": False,
    "swirl": 0.0,
}


def _speed_bound(effect, r):
    """draw()'s own per-radius speed formula at impulse=0 — the ceiling any
    legitimate single-frame radial move obeys."""
    return effect.base_speed * (
        effect.edge_speed
        + (1.0 - effect.edge_speed)
        * np.clip(1.0 - r, 0.0, 1.0) ** effect.accel
    )


async def _reverse_cycle(tmp_path, hold_s=0.5, settle_s=3.0):
    """Warm up to a captured horizon ring, flip reverse on for hold_s, flip
    back, settle. Instruments _compact to capture every surviving
    particle's pre/post-update radius per frame (both sides of the same
    update, so per-particle displacement needs no identity tracking)."""
    host = await headless.start_headless_host(
        str(Path(tmp_path) / "bh-rev"), device_id="bh-rev"
    )
    virtual = host.virtuals.get("bh-rev")
    frames = []  # (r_pre, r_post, cap_post, n_dead) per physics frame
    out = {}
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole", CONFIG)
        effect._rng = np.random.default_rng(11)

        orig_compact = effect._compact

        def spy(alive, *extra):
            n = effect.n
            alive_ = np.asarray(alive)
            frames.append((
                extra[0][alive_].copy() if extra else None,
                effect.p_r[:n][alive_].copy(),
                effect.p_cap[:n][alive_].copy(),
                int(n - np.count_nonzero(alive_)),
            ))
            return orig_compact(alive, *extra)

        effect._compact = spy

        def step():
            clock.advance(DT)
            frame = virtual.assemble_frame()
            if frame is not None:
                virtual.flush(frame)

        for _ in range(int(6.0 / DT)):
            step()
        cap = effect.p_cap[: effect.n]
        out["captured_before_flip"] = int(np.count_nonzero(cap >= 0))

        effect.update_config({"reverse": True})
        out["hold_start"] = len(frames)
        for _ in range(int(hold_s / DT)):
            step()
        cap = effect.p_cap[: effect.n]
        out["capped_during_hold"] = int(np.count_nonzero(cap >= 0))

        effect.update_config({"reverse": False})
        out["flip_back"] = len(frames)
        for _ in range(int(settle_s / DT)):
            step()

        n = effect.n
        cap = effect.p_cap[:n]
        out["recaptured"] = int(np.count_nonzero(cap >= 0))
        out["recaptured_r"] = effect.p_r[:n][cap >= 0].copy()
        out["rh"] = float(effect._horizon_radius())
        out["frames"] = frames
        out["bound"] = lambda r: _speed_bound(effect, r)
    await host.shutdown()
    return out


def test_reverse_release_never_teleports_ex_captives(tmp_path):
    """The frame reverse flips back — and every frame after — no particle
    moves farther than the shared speed formula allows. Pre-fix, the
    stale-cap cohort jumped from its dispersed radius straight onto the
    horizon ring in this one frame (40-86x the bound)."""
    out = asyncio.run(_reverse_cycle(tmp_path))
    assert out["captured_before_flip"] > 0, (
        "harness never built a captured horizon ring — test is vacuous"
    )
    # the fix itself: a reversal releases captives, so nothing carries a
    # stale captured marker into the flip back
    assert out["capped_during_hold"] == 0
    worst_ratio = 0.0
    for r_pre, r_post, _cap, _dead in out["frames"][out["flip_back"]:]:
        if r_pre is None or not len(r_pre):
            continue
        ratio = (np.abs(r_post - r_pre) / (out["bound"](r_pre) * DT + 1e-9)).max()
        worst_ratio = max(worst_ratio, float(ratio))
    assert worst_ratio <= 1.05, (
        f"a particle moved {worst_ratio:.1f}x the speed-formula bound in a "
        f"single frame after the reverse released — position snap"
    )


def test_flip_back_frame_kills_nothing(tmp_path):
    """Second face of the same stale-cap bug: an ex-captive whose frozen cap
    already exceeded horizon_hold + HORIZON_FADE_S was silently deleted
    mid-air on the flip-back frame (alive = cap < hold + fade). Released
    captives have cap == -1, so the flip-back frame retires nothing."""
    out = asyncio.run(_reverse_cycle(tmp_path))
    _r_pre, _r_post, _cap, dead = out["frames"][out["flip_back"]]
    assert dead == 0


def test_ex_captives_recapture_and_the_ring_reforms(tmp_path):
    """After the return leg, the horizon ring re-forms by ordinary
    re-capture — dispersed blobs fall back and are captured fresh at rh,
    not restored by teleport."""
    out = asyncio.run(_reverse_cycle(tmp_path))
    assert out["recaptured"] > 0
    assert np.allclose(out["recaptured_r"], out["rh"], atol=1e-4)
