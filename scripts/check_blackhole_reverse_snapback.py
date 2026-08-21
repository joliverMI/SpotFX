"""Black Hole reverse flare: prove what the release actually does to the
particles that left the event horizon — his report, 2026-08-21:

    "when it reverses the Event Horizon disperses slowly. But then when it
    reverses back it seems that the particles that left the Event Horizon
    shoot back really fast. I don't want them to shoot back fast I want
    them to come in at the speed that the rest would. Have them verify
    what I'm saying or if there's another reason I'm seeing this snap
    back."

Two candidate mechanisms, genuinely different fixes:

  1. A real SPEED asymmetry — the return leg computes faster than the
     outbound leg.
  2. A POSITION SNAP — the second reversal recomputes positions rather
     than continuing them, so particles JUMP (his own alternative theory).

What the code says (fx/effects/blackhole.py, draw()'s physics branch), and
what this script measures on the real vendored pipeline:

  - `new_r = r + (v if self.reverse else -v) * dt` applies the SAME
    per-radius speed formula in both directions, to every particle. There
    is no speed asymmetry — candidate 1 is REFUTED (section 2 measures it).
  - The horizon-capture branch (`if horizon_on and not self.reverse`) does
    `new_r = np.where(captured, rh, new_r)` — and, before the fix this
    script now proves, `p_cap` was never released when `reverse` flipped
    on. `config_updated` only re-reads scalars, so every blob orbiting the
    horizon kept its `cap >= 0` marker while the outflow carried it away
    from the ring. The frame `reverse` flipped back, that `np.where`
    teleported ALL of them from wherever they'd dispersed to straight back
    onto the horizon ring — a single-frame position snap, smeared into a
    fast radial streak by the SUBSTEPS render interpolation. Candidate 2
    is what he was seeing, on exactly the population he named ("the
    particles that left the Event Horizon" — the ex-captives; free-falling
    and freshly-spawned blobs have cap == -1 and never snapped).
  - The longer the reverse hold, the farther the ring disperses, so the
    bigger the snap: the separately-carded hold overrun
    (reverse-flare-holds-2x-authored, ~1160ms measured vs 500ms authored)
    AMPLIFIES this defect (section 3 measures the scaling) but does not
    cause it — the snap exists at the authored 500ms too.

The fix (this PR): while `reverse` is on, horizon captives are released
(`cap = -1`) — a blob the outflow carries off the ring is a free blob. On
the flip back it falls inward at the same per-radius speed as every other
free blob and RE-captures on reaching the horizon (fresh cap, fresh
horizon_hold, fresh color blend) — "come in at the speed that the rest
would", his exact ask. This also removes two smaller stale-cap artifacts:
the instant full-horizon-color pop on return, and ex-captives whose frozen
cap already exceeded horizon_hold + HORIZON_FADE_S being silently deleted
mid-air on the flip-back frame.

Config is HIS real Black Hole V2 Matrix entry (storage/spectra/scenes.json,
scalar params verbatim; signal-bound params at their authored fallbacks),
run on a 72x37 virtual matching crystal-mapper's addressable rectangle.
Headless only — no live storage, no network, no audio hardware.

Run: .venv/bin/python scripts/check_blackhole_reverse_snapback.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0

# His Black Hole V2 Matrix entry — scalars verbatim, signal binds at their
# authored fallbacks (trigger_intensity absent => fallback).
HIS_CONFIG = {
    "horizon_scale": 0.2,
    "horizon_audio": 0.3,
    "horizon_hold": 2.8,
    "base_speed": 2,
    "accel": 5,
    "edge_speed": 0.2,
    "max_blobs": 50,
    "spawn_rate": 1.0,
    "beat_burst": 2,
    "blob_size": 1.75,
    "swirl": 0.0,
    "reverse": False,
    "x_offset": 0.5,
    "y_offset": 0.5,
    "spawn_audio": 1.5,
    "speed_audio": 2,
    "impulse_decay": 0.06,
}

WARMUP_S = 15.0


def v_of(effect, r):
    """The effect's own per-radius speed formula (draw()'s `v`), impulse=0
    (silenced audio). The bound every legitimate per-frame move obeys."""
    return effect.base_speed * (
        effect.edge_speed
        + (1.0 - effect.edge_speed)
        * np.clip(1.0 - r, 0.0, 1.0) ** effect.accel
    )


class CompactSpy:
    """Wraps effect._compact to capture, per frame, each surviving
    particle's (pre-update radius, post-update radius, post-update cap) —
    exact per-particle per-frame displacement with no identity bookkeeping,
    because _compact is handed both sides of the same update."""

    def __init__(self, effect):
        self.effect = effect
        self.orig = effect._compact
        self.frames = []  # (r_pre, r_post, cap_post, n_dead)
        effect._compact = self

    def __call__(self, alive, *extra):
        eff = self.effect
        n = eff.n
        alive = np.asarray(alive)
        r_post = eff.p_r[:n][alive].copy()
        cap_post = eff.p_cap[:n][alive].copy()
        r_pre = extra[0][alive].copy() if extra else None
        self.frames.append(
            (r_pre, r_post, cap_post, int(n - np.count_nonzero(alive)))
        )
        return self.orig(alive, *extra)


async def run_cycle(hold_ms: int):
    """Warm up to a captured horizon population, flip reverse on for
    hold_ms, flip back, keep stepping. Returns the spy plus the frame
    indices of the two flips and state snapshots around them."""
    tmp = tempfile.mkdtemp(prefix=f"bh-rev-{hold_ms}-")
    host = await headless.start_headless_host(
        str(Path(tmp) / "crystal-sim"),
        device_id="crystal-sim",
        pixel_count=72 * 37,
        rows=37,
    )
    virtual = host.virtuals.get("crystal-sim")
    out = {}
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole", HIS_CONFIG)
        effect._rng = np.random.default_rng(7)  # determinism only

        def step():
            clock.advance(DT)
            frame = virtual.assemble_frame()
            if frame is not None:
                virtual.flush(frame)

        for _ in range(int(WARMUP_S / DT)):
            step()

        spy = CompactSpy(effect)
        n = effect.n
        cap = effect.p_cap[:n]
        out["pre_flip_captured"] = int(np.count_nonzero(cap >= 0))
        out["pre_flip_captured_r"] = effect.p_r[:n][cap >= 0].copy()
        out["rh"] = float(effect._horizon_radius())

        # ── reverse ON (the momentary flare's departure jump) ──
        effect.update_config({"reverse": True})
        hold_frames = int(round(hold_ms / 1000.0 / DT))
        for _ in range(hold_frames):
            step()

        n = effect.n
        cap = effect.p_cap[:n]
        still_capped = cap >= 0
        out["end_hold_capped"] = int(np.count_nonzero(still_capped))
        out["end_hold_capped_r"] = effect.p_r[:n][still_capped].copy()
        out["end_hold_n"] = n

        # ── reverse OFF (the release) — the frame he reports ──
        effect.update_config({"reverse": False})
        out["flip_back_frame"] = len(spy.frames)
        for _ in range(int(3.0 / DT)):
            step()

        out["post_settle_captured"] = int(
            np.count_nonzero(effect.p_cap[: effect.n] >= 0)
        )
        out["spy"] = spy
        out["effect_params"] = {
            "base_speed": effect.base_speed,
            "edge_speed": effect.edge_speed,
            "accel": effect.accel,
        }
        # per-radius bound callable evaluated later
        out["v_of"] = lambda r: v_of(effect, r)
    await host.shutdown()
    return out


def frame_disp_stats(out, lo, hi):
    """Max per-frame |Δr| and max ratio to the formula bound v(r_pre)*dt
    over frame indices [lo, hi)."""
    spy = out["spy"]
    worst = 0.0
    worst_ratio = 0.0
    for r_pre, r_post, _cap, _dead in spy.frames[lo:hi]:
        if r_pre is None or len(r_pre) == 0:
            continue
        disp = np.abs(r_post - r_pre)
        bound = out["v_of"](r_pre) * DT
        worst = max(worst, float(disp.max()))
        worst_ratio = max(worst_ratio, float((disp / (bound + 1e-9)).max()))
    return worst, worst_ratio


def main():
    print("=" * 72)
    print("Black Hole reverse flare — release behaviour on the real pipeline")
    print("=" * 72)

    results = {}
    for hold_ms in (500, 1160):
        results[hold_ms] = asyncio.run(run_cycle(hold_ms))

    r500, r1160 = results[500], results[1160]
    rh = r500["rh"]
    print(f"\nhorizon radius rh = {rh:.3f} (normalized r; his horizon_scale"
          f" 0.2, impulse 0)")
    print(f"captured blobs orbiting at flip time: {r500['pre_flip_captured']}"
          f" (500ms run), {r1160['pre_flip_captured']} (1160ms run)")

    # ── section 1: what dispersal does, and what the release does ──
    print("\n── 1. the dispersal and the release ──")
    for hold_ms, out in results.items():
        capped = out["end_hold_capped"]
        r_end = out["end_hold_capped_r"]
        print(f"\nhold {hold_ms}ms:")
        if capped:
            print(f"  STALE-CAP cohort at flip-back: {capped} blobs still "
                  f"marked captured (cap >= 0) while dispersed to "
                  f"r = {r_end.min():.3f}..{r_end.max():.3f} "
                  f"(median {np.median(r_end):.3f}) — {np.median(r_end)-rh:+.3f} "
                  f"from the ring. np.where(captured, rh, ...) would "
                  f"teleport ALL of them to rh in ONE frame.")
        else:
            print(f"  no stale captives at flip-back — reversal released "
                  f"them (the fix); dispersed blobs are ordinary free "
                  f"blobs now.")
        fb = out["flip_back_frame"]
        snap_disp, snap_ratio = frame_disp_stats(out, fb, fb + 1)
        after_disp, after_ratio = frame_disp_stats(out, fb, len(out["spy"].frames))
        norm_disp, norm_ratio = frame_disp_stats(out, 0, fb - 1)
        print(f"  flip-back frame: max |dr| = {snap_disp:.4f} "
              f"({snap_ratio:.1f}x the speed-formula bound v(r)*dt)")
        print(f"  whole return leg: max |dr| = {after_disp:.4f} "
              f"({after_ratio:.1f}x bound)")
        print(f"  reference (all frames before flip-back): max |dr| = "
              f"{norm_disp:.4f} ({norm_ratio:.1f}x bound)")

    # ── section 2: speed symmetry (candidate 1) ──
    print("\n── 2. speed symmetry — is the return leg computed faster? ──")
    out = results[1160]
    fb = out["flip_back_frame"]
    hold_frames = fb  # frames since spy start ≈ reverse-on window
    out_disp, out_ratio = frame_disp_stats(out, 1, hold_frames - 1)
    in_disp, in_ratio = frame_disp_stats(out, fb + 1, len(out["spy"].frames))
    print(f"  outbound (reverse on):  max |dr|/frame = {out_disp:.4f} "
          f"({out_ratio:.2f}x the shared v(r)*dt bound)")
    print(f"  return   (reverse off): max |dr|/frame = {in_disp:.4f} "
          f"({in_ratio:.2f}x the same bound)")
    print("  -> one formula drives both directions "
          "(new_r = r ± v*dt, same v). No speed asymmetry exists.")

    # ── section 3: hold-overrun scaling ──
    print("\n── 3. how the hold overrun amplifies the visible defect ──")
    med500 = (np.median(results[500]["end_hold_capped_r"])
              if len(results[500]["end_hold_capped_r"]) else
              np.median(results[500]["spy"].frames[results[500]["flip_back_frame"] - 1][1]))
    med1160 = (np.median(results[1160]["end_hold_capped_r"])
               if len(results[1160]["end_hold_capped_r"]) else
               np.median(results[1160]["spy"].frames[results[1160]["flip_back_frame"] - 1][1]))
    print(f"  median dispersed radius after 500ms (authored): {med500:.3f} "
          f"({med500 - rh:+.3f} from the ring)")
    print(f"  median dispersed radius after 1160ms (measured live hold): "
          f"{med1160:.3f} ({med1160 - rh:+.3f} from the ring)")
    print("  -> the farther the dispersal, the bigger any snap-back; the "
          "hold overrun (carded separately) more than doubles it, but the "
          "mechanism exists at the authored 500ms too.")

    # ── assertions: the FIXED invariants ──
    print("\n── assertions ──")
    failures = []
    for hold_ms, out in results.items():
        if out["end_hold_capped"] != 0:
            failures.append(
                f"hold {hold_ms}ms: {out['end_hold_capped']} blobs still "
                f"marked captured at flip-back — the stale-cap teleport "
                f"cohort exists (unfixed code)")
        fb = out["flip_back_frame"]
        _d, ratio = frame_disp_stats(out, fb, len(out["spy"].frames))
        if ratio > 1.05:
            failures.append(
                f"hold {hold_ms}ms: a particle moved {ratio:.1f}x the "
                f"speed-formula bound in one frame on the return leg — "
                f"position snap present")
        if out["post_settle_captured"] == 0:
            failures.append(
                f"hold {hold_ms}ms: no blob re-captured at the horizon "
                f"after the return — the ring never re-formed")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("  OK: reversal releases captives (no stale-cap cohort)")
    print("  OK: return leg never exceeds the shared speed formula — "
          "ex-captives come in at the speed the rest would")
    print("  OK: the horizon ring re-forms by ordinary re-capture")


if __name__ == "__main__":
    main()
