"""Regression test — the live crash that darkened crystal-mapper,
tv-mapper AND radial-dummy simultaneously (his report, 2026-08-20):
`TypeError: unsupported operand type(s) for /: 'NoneType' and 'float'` at
fx/effects/blackhole.py:877 in `_horizon_radius`, raised inside the render
thread (fx/virtuals.py thread_function -> assemble_frame -> Effect._render
-> Twod.render -> Blackhole2d.draw -> _horizon_radius). The dead render
thread then starved the render-plane dead-man watchdog, which SIGABRTed
the whole service — a restart he experienced as his room repeatedly
going dark and coming back (restart counter hit 12 that night).

Root cause: `_phase_step`'s orphan watchdog (`particle_handoff.
phase_release_due` — self-releases a charge/lull whose drop trigger never
arrived, e.g. a lost SpotFX write) sets `self._drop = {"burst_t": None,
"silent": True}` and used to `return` immediately, WITHOUT falling through
into this same method's own "drop" branch that resolves burst_t out of
its None sentinel. Every OTHER path that creates that sentinel (a normal
`_enter_phase("drop")` entry, reached via `_phase_pending`) falls through
into that same resolution within the SAME `_phase_step()` call — so
burst_t is normally never externally observable as None. draw() calls
`_horizon_radius()`/`_phase_halo()` immediately after `_phase_step()`
returns, every single frame, with no opportunity for a next call to
self-heal first — so the one early `return` on the watchdog path was
enough to crash the render thread on the very first frame after any
orphaned charge/lull self-released. blackhole1d.py (`_phase_post`) carries
the byte-for-byte identical bug and the identical fix.

This module drives the REAL orphan-release path on a headless dummy host
(a charge phase whose phase_progress never moves off 0.0, held past the
watchdog's own grace window) rather than hand-constructing a `_drop` dict
— proving the actual trigger mechanism a lost trigger produces live, not
just the guard in isolation. `test_burst_t_resolves_within_the_same_
watchdog_call` additionally pins the exact invariant the fix relies on."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import particle_handoff

DT = 1.0 / 60.0
# particle_handoff.phase_release_due: with phase_progress stuck at 0.0,
# `done_t` arms once t>=3.0, and release is due once (t - done_t) >
# PHASE_GRACE_S. A few seconds of margin past that so the assertion isn't
# balanced on the exact frame boundary.
ORPHAN_RELEASE_S = 3.0 + particle_handoff.PHASE_GRACE_S + 2.0


async def _drive_orphan_release(tmp_path, sub, effect_type, config):
    """Enter phase="charge" and never move phase_progress off 0.0 — the
    real shape of a drop trigger that never arrives. Steps well past the
    watchdog's own release window; returns (frames actually rendered,
    frames attempted). The reproduced crash raises out of assemble_frame()
    partway through, so a short-circuited count is the signal, same as the
    live render thread dying mid-stream."""
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)
    frames_rendered = 0
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, effect_type, config)
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        n_frames = int(ORPHAN_RELEASE_S / DT) + 5
        for _ in range(n_frames):
            clock.advance(DT)
            frame = virtual.assemble_frame()
            if frame is not None:
                virtual.flush(frame)
                frames_rendered += 1
    await host.shutdown()
    return frames_rendered, n_frames


def test_blackhole_orphan_charge_release_survives_without_crashing(tmp_path):
    """The exact live crash on crystal-mapper/radial-dummy (Blackhole2d,
    Matrix category): a stuck phase_progress=0.0 charge, held past the
    watchdog's release window, must render every frame — not raise."""
    frames_rendered, n_frames = asyncio.run(_drive_orphan_release(
        tmp_path, "blackhole-orphan",
        "blackhole", {"reverse": False, "horizon_scale": 0.25}))
    assert frames_rendered == n_frames, (
        f"only {frames_rendered}/{n_frames} frames rendered before the "
        "render thread would have died — same shape as the live crash"
    )


def test_blackhole1d_orphan_charge_release_survives_without_crashing(tmp_path):
    """The exact live crash on tv-mapper (Blackhole1d, Classic/strip
    category — conftest.py's own LIVE_VIRTUALS fixture confirms tv-mapper
    runs blackhole1d): _phase_post reads drop['burst_t'] the same
    unguarded way blackhole.py's _horizon_radius did. Same bug, same fix,
    same proof."""
    frames_rendered, n_frames = asyncio.run(_drive_orphan_release(
        tmp_path, "blackhole1d-orphan",
        "blackhole1d", {"reverse": False, "horizon_scale": 0.25}))
    assert frames_rendered == n_frames, (
        f"only {frames_rendered}/{n_frames} frames rendered before the "
        "render thread would have died — same shape as the live crash"
    )


async def _phase_step_invariant(tmp_path, sub, effect_type, config):
    """Arms the exact orphan-release precondition directly on a real
    attached effect (skipping the ~17s of frame-stepping the tests above
    use) rather than re-deriving phase_release_due's own arithmetic, and
    calls _phase_step() exactly once to pin what state it leaves behind."""
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)
    with headless.fake_clock():
        effect = headless.attach_effect(host, virtual, effect_type, config)
        effect._phase = "charge"
        effect.phase_progress = 0.0
        effect._phase_done_t = 3.0  # "done" already armed, as if since t=3.0
        effect._phase_t = particle_handoff.PHASE_GRACE_S + 3.0 + 1.0
        effect._phase_pending = None
        effect._phase_step(0.0)
    await host.shutdown()
    return effect._phase, effect._drop


def test_burst_t_resolves_within_the_same_watchdog_call(tmp_path):
    """Direct proof of the invariant _horizon_radius's own comment relies
    on: the watchdog release must resolve burst_t out of its None sentinel
    within the SAME _phase_step() call, not defer to the next one — draw()
    reads it before that next call would get a chance to self-heal."""
    phase, drop = asyncio.run(_phase_step_invariant(
        tmp_path, "blackhole-invariant", "blackhole",
        {"reverse": False, "horizon_scale": 0.25}))
    assert phase == "drop"
    assert drop is not None and drop["burst_t"] == 0.0, (
        f"drop={drop!r} — burst_t must already be a real float when "
        "_phase_step() returns, never left as the None sentinel"
    )
