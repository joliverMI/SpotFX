"""Black Hole: the momentary reverse flare's RELEASE turns blobs around,
it never flips them (his ask, 2026-08-24, item 3).

    "On Black hole, I like how on reverse, the event horizon immediately
    ejects blobs, but when it reverses back to normal, currently the blobs
    immediately change direction. I want them to accelerate back to the
    black hole, but not immediately change direction. Just start falling
    back using the acceleration value we have... The current setting is too
    jerky"

What this measures, on the REAL vendored pipeline (fx.headless, a dummy
Matrix device at crystal-mapper's own 72x37 shape, his real Black Hole V2
Matrix params, audio silenced so every number is deterministic):

  1. the per-frame radial velocity of a tracked ejected blob across the
     release, before and after the fix (the pre-fix number is computed from
     the module's own unchanged infall formula, not re-derived by hand);
  2. that the fixed velocity trace has NO sign discontinuity — it passes
     continuously through zero rather than jumping from +v to -v in a frame;
  3. that deceleration is monotonic through the turn and that the merge
     back into ordinary infall lands exactly on the speed curve's own
     value for that radius (no step at the seam either);
  4. that a horizon captive the outflow never carried off the ring KEEPS
     its capture across the release — the population PR #179 evicted on
     every single flare, and the reason this fix is not that one relanded.

Read-only: touches no storage, no network, no live process."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402
from fx.effects import blackhole as bh  # noqa: E402

DT = 1.0 / 60.0
HOLD_S = 0.5          # his authored "Reverse Momentarily (500ms)"
WARMUP_S = 4.0        # populate the horizon before the flare
SETTLE_S = 1.5        # watch the fall-back play out

# His real Black Hole V2 Matrix entry (storage/spectra/scenes.json, read
# read-only while writing this; the two bound params — blob_size/swirl —
# resolved to their own fallbacks, which is what a fire with no binding
# context lands).
HIS_MATRIX = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "x_offset": 0.5, "y_offset": 0.5, "horizon_audio": 0.3, "base_speed": 2.0,
    "accel": 5.0, "spawn_rate": 6.0, "beat_burst": 0, "spawn_audio": 1.5,
    "speed_audio": 2.0, "impulse_decay": 0.06, "max_blobs": 50,
    "edge_speed": 0.2, "horizon_hold": 2.8,
}


def _infall_speed(effect, r):
    """The module's OWN speed curve, read off the live effect's config —
    the value draw() applies as `-v` in ordinary infall."""
    return effect.base_speed * (
        effect.edge_speed
        + (1.0 - effect.edge_speed) * np.clip(1.0 - r, 0.0, 1.0) ** effect.accel
    )


async def _run(tmp):
    host = await headless.start_headless_host(str(tmp), device_id="crystal",
                                              pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get("crystal")
    trace = []
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole", dict(HIS_MATRIX))

        def step(n):
            for _ in range(n):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)

        step(int(WARMUP_S / DT))
        captives_before = int(np.count_nonzero(effect.p_cap[: effect.n] >= 0.0))
        # Freeze the population: no spawns, no beat bursts, so compaction
        # order is stable and index 0 is the same blob every frame.
        effect.update_config({"spawn_rate": 0.0, "beat_burst": 0})
        step(int(0.2 / DT))

        # ── the flare: reverse ON (eject), hold, reverse OFF (release) ──
        effect.update_config({"reverse": True})
        step(int(HOLD_S / DT))
        n_ejected = effect.n
        r_at_release = float(effect.p_r[0])
        v_at_release = float(_infall_speed(effect, r_at_release))
        cap_on_ring = int(np.count_nonzero(
            (effect.p_cap[: effect.n] >= 0.0)
            & (effect.p_r[: effect.n] <= effect._horizon_radius()
               + bh.REVERSE_FALLBACK_RING_TOL)))

        r_all_before = effect.p_r[: effect.n].copy()
        effect.update_config({"reverse": False})
        prev_r = float(effect.p_r[0])
        step(1)
        # same population (spawning is off, nothing dies in one frame at
        # these speeds), same order — compaction preserves order
        release_jump = float(np.max(np.abs(
            effect.p_r[: len(r_all_before)] - r_all_before)))
        prev_r = float(effect.p_r[0])
        for _ in range(int(SETTLE_S / DT)):
            clock.advance(DT)
            frame = virtual.assemble_frame()
            if frame is not None:
                virtual.flush(frame)
            if effect.n == 0:
                break
            r_now = float(effect.p_r[0])
            trace.append({
                "r": r_now,
                "v": (r_now - prev_r) / DT,
                "turning": bool(effect.p_turn[0]),
                "captured": bool(effect.p_cap[0] >= 0.0),
                "curve_v": float(_infall_speed(effect, r_now)),
            })
            prev_r = r_now
        captives_after = int(np.count_nonzero(effect.p_cap[: effect.n] >= 0.0))
    await host.shutdown()
    return {
        "trace": trace, "n_ejected": n_ejected,
        "r_at_release": r_at_release, "v_at_release": v_at_release,
        "captives_before": captives_before, "cap_on_ring": cap_on_ring,
        "captives_after": captives_after,
        "release_jump": release_jump,
        "short_blip": await _short_blip(tmp),
    }


async def _short_blip(tmp):
    """A reverse blip SHORT enough that horizon captives never leave the
    ring: they must keep their capture (their hold clock and colour blend
    continue) — the population PR #179's blanket per-frame release evicted
    on every flare regardless of whether it had moved them."""
    host = await headless.start_headless_host(str(Path(tmp) / "blip"),
                                              device_id="blip",
                                              pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get("blip")
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole", dict(HIS_MATRIX))

        def step(n):
            for _ in range(n):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)

        step(int(WARMUP_S / DT))
        effect.update_config({"spawn_rate": 0.0, "beat_burst": 0})
        step(int(0.2 / DT))
        cap_ages_before = effect.p_cap[: effect.n][
            effect.p_cap[: effect.n] >= 0.0].copy()
        effect.update_config({"reverse": True})
        step(2)                      # ~33 ms — under the ring tolerance
        effect.update_config({"reverse": False})
        step(1)
        kept = int(np.count_nonzero(effect.p_cap[: effect.n] >= 0.0))
        ages_after = effect.p_cap[: effect.n][effect.p_cap[: effect.n] >= 0.0]
    await host.shutdown()
    return {"before": int(cap_ages_before.size), "kept": kept,
            "aged_on": bool(ages_after.size and cap_ages_before.size
                            and float(ages_after.max())
                            > float(cap_ages_before.max()))}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        res = asyncio.run(_run(tmp))
    trace = res["trace"]
    failures = []

    def check(ok, label):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    print(f"REVERSE_FALLBACK_TURN_S = {bh.REVERSE_FALLBACK_TURN_S}s   "
          f"REVERSE_FALLBACK_RING_TOL = {bh.REVERSE_FALLBACK_RING_TOL}")
    print(f"\n{res['n_ejected']} blobs in flight at the release; tracked blob "
          f"at r={res['r_at_release']:.3f}, curve speed {res['v_at_release']:.3f} r/s")

    print("\n── §1 the velocity trace across the release ─────────────────")
    print(f"{'t (ms)':>7} {'r':>7} {'v (r/s)':>9} {'state':>10}")
    for i, s in enumerate(trace[:60]):
        if i % 4 and i > 8:
            continue
        state = "turning" if s["turning"] else (
            "captured" if s["captured"] else "infall")
        print(f"{i * DT * 1000:>7.0f} {s['r']:>7.3f} {s['v']:>9.3f} {state:>10}")

    vs = [s["v"] for s in trace]
    # PRE-FIX behaviour, from the module's own unchanged infall formula: the
    # frame before the release the blob moved at +v, the frame after at -v.
    pre_step = 2.0 * res["v_at_release"]
    post_step = max(abs(vs[i + 1] - vs[i]) for i in range(min(len(vs), 40) - 1))
    print(f"\n  pre-fix one-frame velocity step at the release: "
          f"{pre_step:+.3f} r/s (a full sign flip, +v -> -v)")
    print(f"  fixed:  largest one-frame velocity step: {post_step:.4f} r/s")

    print("\n── §2 no sign discontinuity ─────────────────────────────────")
    # every zero crossing must be a genuine crossing: the step across it is
    # bounded by one frame of the turn's own deceleration, not a flip.
    crossings = [i for i in range(len(vs) - 1) if vs[i] > 0 >= vs[i + 1]]
    check(len(crossings) == 1, f"velocity crosses zero exactly once ({len(crossings)})")
    if crossings:
        i = crossings[0]
        # deceleration bound: 2*v/TURN_S * dt, with margin for v's own drift
        bound = 2.0 * res["v_at_release"] / bh.REVERSE_FALLBACK_TURN_S * DT * 1.5
        check(abs(vs[i + 1] - vs[i]) <= bound,
              f"the crossing step {abs(vs[i+1]-vs[i]):.4f} <= one frame of "
              f"deceleration {bound:.4f} r/s (pre-fix: {pre_step:.3f})")
    check(post_step < pre_step / 4.0,
          f"largest step {post_step:.4f} is far under the pre-fix flip {pre_step:.3f}")

    print("\n── §3 monotonic deceleration, then a seamless merge ─────────")
    turning = [s for s in trace if s["turning"]]
    tv = [s["v"] for s in turning]
    check(len(turning) > 10, f"the turn lasts {len(turning)} frames "
                             f"({len(turning) * DT * 1000:.0f} ms)")
    check(all(tv[i + 1] <= tv[i] + 1e-6 for i in range(len(tv) - 1)),
          "velocity decreases monotonically for every frame of the turn")
    check(tv and tv[0] > 0 and tv[-1] < 0,
          f"the turn starts outward ({tv[0]:+.3f}) and ends inward ({tv[-1]:+.3f})")
    # the first frame after the turn ends — the tracked blob may well be an
    # ex-ring captive (it keeps its capture the whole way, by design), and
    # an off-ring captive moves at the ordinary curve speed like any other
    merge = next((s for s in trace if not s["turning"]), None)
    if merge is not None:
        check(abs(abs(merge["v"]) - merge["curve_v"]) < 0.05 * merge["curve_v"] + 1e-3,
              f"the first post-turn frame moves at the curve's own speed "
              f"({merge['v']:+.3f} vs -{merge['curve_v']:.3f})")
    else:
        check(False, "the blob merged back into ordinary infall")

    print("\n── §4 nothing teleports at the release ──────────────────────")
    v_frame = res["v_at_release"] * DT
    print(f"  largest one-frame radius move by ANY blob across the release: "
          f"{res['release_jump']:.4f} (one frame of travel at the curve "
          f"speed: {v_frame:.4f})")
    check(res["release_jump"] <= v_frame * 1.5 + 1e-4,
          "no blob moves more than one frame of ordinary travel at the "
          "release (the stale-capture teleport PR #179 measured at 0.300)")

    print("\n── §5 the ring keeps EVERY captive across the flare ─────────")
    print(f"  captives before the flare: {res['captives_before']}, "
          f"still ON the ring at the release: {res['cap_on_ring']}, "
          f"captured after: {res['captives_after']}")
    check(res["captives_before"] > 0, "the horizon had a population to protect")
    check(res["captives_after"] >= res["captives_before"],
          "the 500 ms flare evicted nobody either: every pre-flare captive "
          "still carries its capture after the release")
    blip = res["short_blip"]
    print(f"  short blip (33 ms of reverse): {blip['before']} captured "
          f"before -> {blip['kept']} after")
    check(blip["before"] > 0 and blip["kept"] >= blip["before"],
          "EVERY captive keeps its capture across a reverse flare (PR #179 "
          "released all of them, on every frame of every flare)")
    check(blip["aged_on"],
          "their hold clocks kept running — not restarted from zero, so "
          "the ring still turns over")

    print("\n" + ("ALL CHECKS PASSED" if not failures
                  else f"{len(failures)} FAILED: " + "; ".join(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
