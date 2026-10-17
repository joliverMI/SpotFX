"""Black Hole: infall through the transition (bh-infall-plan, option D).

The Admiral, 2026-10-17: "When the scene changes to black hole, it doesn't
seem to generate infalling particles during the transition, which leads to
a lull in activity, even during highly active music." He reviewed the plan
(data/bh-infall-plan/report.md) and answered "just do option D".

D — the one change this test covers — is `Blackhole2d._spawn`'s density
accounting: `max_blobs` used to count every ambient (non-no-cap) blob,
HORIZON CAPTIVES INCLUDED, so under busy music the captive queue alone
(spawn rate x its ~3.6s hold+fade) filled the cap and fresh infall stalled
to zero for seconds — worst right after a scene transition INTO Black
Hole, which lands the whole outgoing cloud onto the ring as captives in
one frame. `_spawn` now counts only blobs still falling (`p_cap < 0`, not
`p_nocap`) against `max_blobs`; a captured blob no longer blocks new
infall. The ring runs denser under busy music as a result (more captives)
— accepted as part of D, not fixed here.

Frame-level, on the real vendored pipeline (fx.headless, dummy Matrix
host, a fake clock) — the plan's own rig recipe, replayed as a pytest
regression:

  1. `test_scene_transition_into_black_hole_keeps_infall_flowing` —
     Orbits -> Black Hole via the real INFALL transition program, under a
     deterministic busy-music feed. Asserts infalling blobs stay > 0 for
     the whole 1.8s-4.3s-after-the-switch window the plan measured as
     EMPTY before this fix ("today 0"), then re-runs the identical
     scenario with the PRE-FIX accounting restored and asserts THAT run
     does go empty in the same window — a bar that cannot fail on the
     defect it was written for is decoration.
  2. `test_running_black_hole_keeps_infall_from_stalling_under_busy_music`
     — the plan's own steady-state finding ("the cap fix alone... the
     steady state is healthier too"): a Black Hole that was never
     transitioned into, just running from a cold start under the same busy
     feed, never has zero infalling blobs once past its own warm-up —
     again with the pre-fix accounting as the red control.

Both reuse the plan's own busy-feed shape (lows 0.55 +/- 0.30 with a lift
on each beat, a beat every 28 frames / ~128bpm — the same order of
magnitude as the plan's rig, which measured the impulse settling near
0.77 under it) and his real Black Hole V2 Matrix entry, with `spawn_rate`
raised from his scene's bound 1.0 to 3.0 so this synthetic feed (which,
unlike his live room, has no scene-bound audio pipeline to drive the
impulse to the plan's own levels) reliably saturates `max_blobs` within
the same ~1.5s the plan measured, rather than relying on this test
reproducing his exact live bindings.

Offline throughout: tmp_path dummy hosts, no live storage or network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import blackhole as bh  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402
from fx.host import FxHost  # noqa: E402

PIXELS, ROWS = 72 * 37, 37
DT = 1.0 / 60.0
CAP = bh.CAP
GRADIENT = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"

# His real Black Hole V2 Matrix entry (tests/test_blackhole_charge_target.py's
# own CFG), with spawn_rate raised — see the module docstring for why.
BH_CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "x_offset": 0.5, "y_offset": 0.5, "horizon_audio": 0.3, "base_speed": 2.0,
    "accel": 5.0, "spawn_rate": 3.0, "beat_burst": 0, "spawn_audio": 1.5,
    "speed_audio": 2.0, "impulse_decay": 0.06, "max_blobs": 50,
    "edge_speed": 0.2, "horizon_hold": 2.8,
}


class _BusyAudio:
    """A deterministic busy-music feed: lows 0.55 +/- 0.30 with a 0.35
    lift on each beat, a beat every 28 frames (~128bpm) — the same shape
    the plan's own rig fed into `audio_data_updated`."""

    def __init__(self, i: int):
        self.i = i

    def _lift(self) -> float:
        return 0.35 if (self.i % 28) < 4 else 0.0

    def lows_power(self, filtered: bool = True) -> float:
        v = 0.55 + 0.30 * np.sin(self.i / 5.0) + self._lift()
        return float(np.clip(v, 0.0, 1.5))

    def beat_power(self, filtered: bool = True) -> float:
        return self.lows_power(filtered)

    def bass_power(self, filtered: bool = True) -> float:
        return self.lows_power(filtered)

    def mids_power(self, filtered: bool = True) -> float:
        return 0.30 + 0.12 * np.sin(self.i / 7.0)

    def high_power(self, filtered: bool = True) -> float:
        return 0.20 + 0.10 * np.sin(self.i / 9.0)

    def bpm_beat_now(self) -> bool:
        return self.i % 28 == 0


def _install_pre_fix_spawn(effect) -> None:
    """Restore the PRE-D accounting on one instance: `max_blobs` counted
    every ambient (non-no-cap) blob, horizon captives included — the exact
    formula `_spawn` carried before 2026-10-17. Used only as the red
    control; production code is untouched."""

    def old_spawn(count, beat_count, *, theta=None, ignore_cap=False):
        ambient_n = effect.n - int(
            np.count_nonzero(effect.p_nocap[: effect.n])
        )
        room = (CAP - effect.n) if ignore_cap else min(
            effect.max_blobs - ambient_n, CAP - effect.n)
        count = int(min(count, room))
        if count <= 0:
            return
        s = slice(effect.n, effect.n + count)
        rng = effect._rng
        effect.p_is_burst[s] = False
        effect.p_nocap[s] = ignore_cap
        theta = (
            rng.uniform(0.0, 2 * np.pi, count).astype(np.float32)
            if theta is None
            else np.asarray(theta, dtype=np.float32)[:count]
        )
        if effect.reverse:
            inner = (
                effect._horizon_radius()
                if effect.horizon_scale > 0
                else effect.kill_radius
            )
            effect.p_r[s] = rng.uniform(inner, inner + 0.06, count)
        else:
            edge_r = bh._hex_spawn_edge_radius(theta)
            effect.p_r[s] = edge_r + rng.uniform(
                bh.SPAWN_EDGE_MARGIN_MIN, bh.SPAWN_EDGE_MARGIN_MAX, count
            ).astype(np.float32)
        effect.p_theta[s] = theta
        effect.p_age[s] = 0.0
        effect.p_cap[s] = -1.0
        effect.p_out[s] = 0.0
        effect.p_turn[s] = False
        effect.p_vr[s] = 0.0
        effect.p_ivx[s] = np.nan
        effect.p_ivy[s] = np.nan
        if effect.color_mode == "band":
            weights = effect.band_powers + 0.05
            weights = weights / weights.sum()
            bands = rng.choice(3, size=count, p=weights)
            effect.p_band[s] = bands
            effect.p_grad[s] = (
                bh.BAND_ANCHORS[bands]
                + rng.uniform(
                    -bh.BAND_JITTER, bh.BAND_JITTER, count
                ).astype(np.float32)
            ) % 1.0
        elif effect.color_mode == "random":
            effect.p_grad[s] = rng.uniform(0.0, 1.0, count).astype(
                np.float32
            )
        else:
            spin = effect.spin_total if effect.gradient_spin != 0 else 0.0
            effect.p_grad[s] = (theta / (2 * np.pi) + spin) % 1.0
        effect.p_bright[s] = 1.0
        effect.n += count

    effect._spawn = old_spawn


def _infalling(effect) -> int:
    """Blobs still falling toward the horizon — p_cap < 0 (not yet
    captured) and not tagged no-cap (a forced/burst blob, which was never
    gated by max_blobs either before or after D)."""
    n = effect.n
    if n == 0:
        return 0
    free = effect.p_cap[:n] < 0.0
    return int((free & ~effect.p_nocap[:n]).sum())


async def _host(tmp_path, sub):
    d = str(tmp_path / sub)
    headless.write_headless_config(d, pixel_count=PIXELS, rows=ROWS)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    v._config["transition_mode"] = "Add"
    v._config["transition_time"] = 0.5
    return host, v


async def _run_transition(tmp_path, sub, *, pre_fix: bool, seconds=6.0):
    host, v = await _host(tmp_path, sub)
    try:
        with headless.fake_clock() as clk:
            outgoing = headless.attach_effect(
                host, v, "orbits", {"gradient": GRADIENT, "particle_count": 16}
            )
            outgoing._rng = np.random.default_rng(1)
            for i in range(120):
                outgoing.audio_data_updated(_BusyAudio(i))
                clk.advance(DT)
                f = v.assemble_frame()
                if f is not None:
                    v.flush(f)

            new = host.effects.create(
                ledfx=host, type="blackhole", config=BH_CFG)
            new._rng = np.random.default_rng(2)
            if pre_fix:
                _install_pre_fix_spawn(new)
            prog = tp.build("orbits", "blackhole", {"seed": 7})
            v.set_effect(new, activate=False, program=prog)

            series = []
            n_frames = int(seconds / DT)
            for i in range(n_frames):
                new.audio_data_updated(_BusyAudio(i))
                clk.advance(DT)
                f = v.assemble_frame()
                if f is not None:
                    v.flush(f)
                series.append(_infalling(new))
    finally:
        await host.shutdown()
    return series


async def _run_steady(tmp_path, sub, *, pre_fix: bool, seconds=10.0):
    host, v = await _host(tmp_path, sub)
    try:
        with headless.fake_clock() as clk:
            effect = headless.attach_effect(host, v, "blackhole", BH_CFG)
            effect._rng = np.random.default_rng(3)
            if pre_fix:
                _install_pre_fix_spawn(effect)
            series = []
            n_frames = int(seconds / DT)
            for i in range(n_frames):
                effect.audio_data_updated(_BusyAudio(i))
                clk.advance(DT)
                f = v.assemble_frame()
                if f is not None:
                    v.flush(f)
                series.append(_infalling(effect))
    finally:
        await host.shutdown()
    return series


def _run(coro):
    return asyncio.run(coro)


def _frames_in(series, lo_s, hi_s):
    t = np.arange(len(series)) * DT
    mask = (t >= lo_s) & (t < hi_s)
    return np.asarray(series)[mask]


# ── 1. the transition itself ────────────────────────────────────────────

def test_scene_transition_into_black_hole_keeps_infall_flowing(tmp_path):
    fixed = _run(_run_transition(tmp_path, "fixed", pre_fix=False))
    window = _frames_in(fixed, 1.8, 4.3)
    assert window.size > 0
    assert window.min() > 0, (
        "infalling blobs touched zero inside the 1.8s-4.3s window the "
        f"plan measured as empty before D; series={window.tolist()}"
    )

    # the red control: the SAME scenario, with the pre-D accounting
    # restored, must reproduce the plan's own empty-field window — a bar
    # that cannot fail on the defect it was written for proves nothing.
    broken = _run(_run_transition(tmp_path, "broken", pre_fix=True))
    broken_window = _frames_in(broken, 1.8, 4.3)
    assert broken_window.size > 0
    assert broken_window.min() == 0, (
        "the pre-fix accounting was expected to stall infall to zero "
        f"somewhere in 1.8s-4.3s; series={broken_window.tolist()}"
    )
    zero_run = 0
    longest = 0
    for v in broken_window:
        zero_run = zero_run + 1 if v == 0 else 0
        longest = max(longest, zero_run)
    assert longest * DT >= 1.0, (
        "the red control's empty run inside the window was too short to "
        f"be the defect the plan measured: {longest * DT:.2f}s"
    )


# ── 2. steady state (no transition at all) ──────────────────────────────

def test_running_black_hole_keeps_infall_from_stalling_under_busy_music(
    tmp_path,
):
    fixed = _run(_run_steady(tmp_path, "fixed", pre_fix=False))
    # skip the cold-start ramp (no captives exist yet to saturate anything)
    steady = np.asarray(fixed[int(2.0 / DT):])
    assert steady.min() >= 3, (
        "a running Black Hole's infall sagged toward zero under busy "
        f"music after warm-up; series={steady.tolist()}"
    )

    # the red control: the pre-D accounting, same feed/seed/duration,
    # must demonstrably choke the steady-state floor the fix raises — a
    # single run's exact minimum is seed/window-sensitive (the captive
    # queue dips on the beat), so this compares the two runs rather than
    # asserting a literal zero.
    broken = _run(_run_steady(tmp_path, "broken", pre_fix=True))
    broken_steady = np.asarray(broken[int(2.0 / DT):])
    assert broken_steady.min() <= 1, (
        "the pre-fix accounting was expected to let the steady-state "
        "captive queue choke infall near zero under busy music; "
        f"series={broken_steady.tolist()}"
    )
    assert steady.min() - broken_steady.min() >= 2, (
        "D was expected to measurably raise the steady-state infall "
        f"floor: fixed min={steady.min()}, pre-fix min={broken_steady.min()}"
    )
