#!/usr/bin/env python3
"""Read-only evidence script for the Black Hole drop-burst count + post-burst
ambient-spawn gap fix (fx/effects/blackhole.py, PR
fm/spectra-blackhole-explosion-and-gap).

His two asks, verbatim, in one breath:
  "the explosion after the collapse should be more at least 2 times more
  intense in terms of count. Also, after the big explosion, there seems to
  be a gap between it and when new blobs come in. the music related blobs
  should still come through during the drop so there isn't this odd gap."

Scout report (data/charge-lull-drop-timing-blends-and-a-sus-7fm2/report.md
§5.1) found the two asks fight under the pre-fix logic: PHASE_BURST_N=24
bypasses max_blobs on the drop payoff, but the ordinary ambient/beat spawn
in `_spawn` was gated on TOTAL live population (`max_blobs - self.n`) —
so a bigger burst pushes population further past max_blobs and makes the
post-explosion gap *worse*, not better. The fix (this PR) tags burst
particles (`p_is_burst`) and has `_spawn`'s cap check count only ambient
(non-burst) population, decoupling the two — see blackhole.py's own
docstrings on `_phase_burst`/`_spawn`.

This script drives the real charge->lull->drop state machine through the
production code path (Effect.update_config, same call shape
scene_response.py's `_drive_phase` uses) on a headless dummy host, across
four variants:

  A. OLD BASELINE  — the pre-fix cap formula (population-gated, restated
     here since it no longer exists in blackhole.py — same "regression
     check" convention as scripts/check_blackhole_hex_spawn.py's own
     restated historical annuli) with PHASE_BURST_N patched back to its
     pre-fix value of 24.
  B. NAIVE DOUBLE   — the SAME pre-fix cap formula, but PHASE_BURST_N left
     at the current (2x) value of 48 — this is what "just double the
     constant" would have shipped, and is expected to be *worse* than A,
     proving the scout's warning.
  C. FIXED          — the actual current blackhole.py: PHASE_BURST_N=48,
     ambient-only cap.
  D. CONTROL        — the actual current blackhole.py with max_blobs
     effectively uncapped (1024), PHASE_BURST_N=48 — never starved by
     population, so its post-burst gap is purely the natural spawn/beat
     scheduling cadence. This is the target C should match: "no gap" does
     not mean literally 0.0s, it means no MORE than what plain scheduling
     already implies.

Every burst is measured directly off `_phase_burst`'s own particle count
(instrumented, not asserted), and every "next ambient/beat blob" off
`_spawn`'s own particle count — this is the same engine the drop payoff
and the ambient trickle actually run on, not a re-derivation.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402
from fx.effects import blackhole  # noqa: E402
from fx.effects.blackhole import Blackhole2d  # noqa: E402

DT = 1.0 / 60.0
OLD_PHASE_BURST_N = 24  # the pre-fix constant; blackhole.py's own is now 48


class _OldCapBlackhole2d(Blackhole2d):
    """Reproduces the PRE-FIX ambient-spawn cap: gated on total live
    population (self.n), burst particles included — the formula no longer
    exists in blackhole.py, restated here only for this regression
    comparison. Achieved by zeroing the no-cap tag before delegating to the
    real (fixed) `_spawn`, so its `ambient_n = self.n -
    count_nonzero(p_nocap)` collapses to `ambient_n == self.n`, exactly
    the old `max_blobs - self.n` arithmetic."""

    def _spawn(self, count, beat_count, **kw):
        # p_nocap is the flag the cap arithmetic reads (since 2026-08-24 it
        # is split from p_is_burst, which now means specifically "a
        # drop-payoff particle"); zeroing it collapses `ambient_n` back to
        # `self.n`, which is the old formula.
        self.p_nocap[: self.n] = False
        super()._spawn(count, beat_count, **kw)


def _attach_custom_effect(host, virtual, effect_cls, config):
    """headless.attach_effect, parameterized by effect CLASS instead of a
    registry type string, so this script can attach the restated OLD-cap
    class above alongside the real one."""
    validated = effect_cls.schema()(config)
    effect = effect_cls(ledfx=host, config=validated)
    effect._id = effect_cls.__name__
    effect._type = "blackhole"
    # host.effects.create() (the normal path) registers the object here too
    # — without it, host.shutdown()'s cleanup can't find the id to destroy
    # and logs a (harmless but noisy) AttributeError from an asyncio callback.
    host.effects._objects[effect._id] = effect
    effect.activate(virtual)
    virtual._active_effect = effect
    virtual.transitions = type(virtual.transitions)(virtual.effective_pixel_count)
    virtual.frame_transitions = virtual.transitions[
        virtual._config["transition_mode"]
    ]
    virtual.activate_segments(virtual._segments)
    virtual._active = True
    return effect


BASE_CONFIG = {
    "reverse": False,       # infall — matches his real Black Hole V2 scene
    "horizon_scale": 0.25,  # schema default
    "spawn_rate": 4.0,      # ambient blobs/sec — the "music related" trickle
    "beat_burst": 4,        # extra blobs per beat
    "max_blobs": 50,        # his real Black Hole V2 scene's live value
    "base_speed": 1.0,
    "edge_speed": 0.25,
    "accel": 2.5,
}


async def _run_variant(tmp_path: Path, sub: str, effect_cls, *, max_blobs=50):
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)

    spawn_log: list[tuple[int, int]] = []
    burst_log: list[tuple[int, int]] = []
    frame_idx = [0]

    with headless.fake_clock() as clock:
        config = dict(BASE_CONFIG, max_blobs=max_blobs)
        effect = _attach_custom_effect(host, virtual, effect_cls, config)
        effect._rng = np.random.default_rng(20260820)

        orig_spawn = effect._spawn

        def logged_spawn(count, beat_count, _orig=orig_spawn, **kw):
            # AMBIENT spawns only: since 2026-08-24 the charge/lull also
            # force blobs into being through this same function with
            # ignore_cap=True (fx/effects/blackhole.py's _phase_spawn_rate),
            # and this measurement is about the music-driven population the
            # cap governs — counting the forced ones would silently change
            # what this script reports.
            before = effect.n
            _orig(count, beat_count, **kw)
            added = effect.n - before
            if added > 0 and not kw.get("ignore_cap"):
                spawn_log.append((frame_idx[0], added))

        effect._spawn = logged_spawn

        orig_burst = effect._phase_burst

        def logged_burst(_orig=orig_burst):
            before = effect.n
            _orig()
            added = effect.n - before
            burst_log.append((frame_idx[0], added))

        effect._phase_burst = logged_burst

        beat_interval_frames = int(0.4 / DT)

        def step(n_frames: int):
            for _ in range(n_frames):
                if frame_idx[0] % beat_interval_frames == 0:
                    effect._beat_pending = True
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
                frame_idx[0] += 1

        # CHARGE: ramp phase_progress 0->1 over 1.2s
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        charge_frames = int(1.2 / DT)
        for i in range(1, charge_frames + 1):
            effect.update_config({"phase_progress": i / charge_frames})
            step(1)

        # LULL: hold for 1.0s (population persists, spawn paused)
        effect.update_config({"phase": "lull", "phase_progress": 0.0})
        step(int(1.0 / DT))

        # DROP: ramp phase_progress 0->1 over 0.3s -> triggers the burst
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        drop_frames = int(0.3 / DT)
        for i in range(1, drop_frames + 1):
            effect.update_config({"phase_progress": i / drop_frames})
            step(1)

        # POST: measure ambient/beat spawn continuation for 3s
        step(int(3.0 / DT))

        n_at_end = effect.n

    await host.shutdown()

    assert burst_log, f"{sub}: drop burst never fired"
    burst_frame, burst_count = burst_log[0]
    after = [t for t, _ in spawn_log if t > burst_frame]
    gap_s = (after[0] - burst_frame) * DT if after else None
    return {
        "burst_frame_s": burst_frame * DT,
        "burst_count": burst_count,
        "gap_s": gap_s,
        "n_at_end": n_at_end,
        "spawns_after_burst_3s": len(after),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        orig_phase_burst_n = blackhole.PHASE_BURST_N
        try:
            blackhole.PHASE_BURST_N = OLD_PHASE_BURST_N
            a = asyncio.run(_run_variant(tmp_path, "a_old_baseline", _OldCapBlackhole2d))
        finally:
            blackhole.PHASE_BURST_N = orig_phase_burst_n

        b = asyncio.run(_run_variant(tmp_path, "b_naive_double", _OldCapBlackhole2d))
        c = asyncio.run(_run_variant(tmp_path, "c_fixed", Blackhole2d))
        d = asyncio.run(
            _run_variant(tmp_path, "d_control_uncapped", Blackhole2d, max_blobs=1024)
        )

    def fmt_gap(g):
        return f"{g:.3f}s" if g is not None else "NO SPAWN within 3s (gap unbounded)"

    print("Variant                         burst_count  burst_t   post-burst gap   spawns/3s")
    print(f"A OLD BASELINE (burst=24, pop-gated cap)  {a['burst_count']:>4}   "
          f"{a['burst_frame_s']:.2f}s   {fmt_gap(a['gap_s']):>28}   {a['spawns_after_burst_3s']}")
    print(f"B NAIVE DOUBLE (burst=48, pop-gated cap)  {b['burst_count']:>4}   "
          f"{b['burst_frame_s']:.2f}s   {fmt_gap(b['gap_s']):>28}   {b['spawns_after_burst_3s']}")
    print(f"C FIXED        (burst=48, ambient-only)   {c['burst_count']:>4}   "
          f"{c['burst_frame_s']:.2f}s   {fmt_gap(c['gap_s']):>28}   {c['spawns_after_burst_3s']}")
    print(f"D CONTROL      (burst=48, max_blobs=1024) {d['burst_count']:>4}   "
          f"{d['burst_frame_s']:.2f}s   {fmt_gap(d['gap_s']):>28}   {d['spawns_after_burst_3s']}")

    ok = True

    if a["burst_count"] != OLD_PHASE_BURST_N:
        print(f"\nFAIL: variant A burst count {a['burst_count']} != {OLD_PHASE_BURST_N}")
        ok = False
    if b["burst_count"] != 48 or c["burst_count"] != 48:
        print(f"\nFAIL: variant B/C burst count is not 48 (2x his original 24): "
              f"B={b['burst_count']} C={c['burst_count']}")
        ok = False
    if not (b["burst_count"] >= 2 * a["burst_count"]):
        print("\nFAIL: doubled variant does not carry at least 2x the burst count")
        ok = False

    # The tension the scout report predicted: naively doubling the burst
    # under the OLD cap formula makes the gap worse, not better.
    b_gap = b["gap_s"] if b["gap_s"] is not None else float("inf")
    a_gap = a["gap_s"] if a["gap_s"] is not None else float("inf")
    if not (b_gap >= a_gap):
        print(f"\nFAIL: naive double (B, gap={fmt_gap(b['gap_s'])}) is not >= "
              f"the old baseline (A, gap={fmt_gap(a['gap_s'])}) — expected doubling "
              f"the burst under the old cap to make the gap the same or worse")
        ok = False

    # The fix: with the decoupled cap, the post-burst gap collapses back to
    # the control's natural scheduling cadence, not the starved B number.
    d_gap = d["gap_s"] if d["gap_s"] is not None else float("inf")
    c_gap = c["gap_s"] if c["gap_s"] is not None else float("inf")
    if c["gap_s"] is None:
        print("\nFAIL: fixed variant (C) never spawns an ambient/beat blob within 3s of the burst")
        ok = False
    elif not (c_gap <= d_gap + DT + 1e-9):
        print(f"\nFAIL: fixed variant (C) gap {fmt_gap(c['gap_s'])} exceeds the "
              f"uncapped control (D) gap {fmt_gap(d['gap_s'])} by more than one frame — "
              f"the burst is still starving the ambient spawn")
        ok = False
    if not (c_gap < b_gap):
        print(f"\nFAIL: fixed variant (C) gap {fmt_gap(c['gap_s'])} is not shorter than "
              f"the naive-double variant (B) gap {fmt_gap(b['gap_s'])}")
        ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
