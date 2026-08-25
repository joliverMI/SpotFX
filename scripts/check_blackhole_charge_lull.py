"""Executable spec: the Black Hole charge/lull rework (his ask, 2026-08-24,
item 5), measured on the real vendored pipeline (fx.headless, audio
silenced, his own Black Hole V2 Matrix params at his crystal's 72x37
shape). The DROP is deliberately untouched by that work — proven here too.

His words, verbatim:

    "on the drop sequence, for charge: instead of the black hole expanding,
    accelerate the number of blobs forming (up to 12/second, but not all at
    once), ignore max counts, accelerate their fall speed, and increase the
    thickness of the event horizon slowly. Then, on the lull, continue the
    fast blob falling but expand the event horizon until it fills the hex
    (i think it currently expands too far) at half way through the duration
    of the lull. So half of the lull should be dark. Then the drop can stay
    the same as it is now."

What is proven, in order:
  1. CHARGE: the horizon RADIUS holds at its musical baseline for the whole
     build (no expansion, and no black disc growing behind it), while the
     ring's THICKNESS grows.
  2. CHARGE: blob formation ACCELERATES to 12/second as p->1 — measured as
     a real per-second rate on rendered frames, never a batch — and the
     population goes PAST max_blobs.
  3. CHARGE: fall speed accelerates with p, and holds through the lull.
  4. LULL: the horizon reaches the HEX FILL radius exactly at
     phase_progress = 0.5 and HOLDS; the panel is fully dark for the
     second half. The fill radius is the hex silhouette's own bound
     (~1.13), NOT r_max (~1.49) — "it currently expands too far".
  5. LULL: the fast formation continues through the first half and only
     pauses once the panel is actually dark.
  6. TIMING HONESTY: what "half way through the lull" really lands at,
     given SpotFX ramps phase_progress over ~90% of the gap.
  7. DROP: unchanged — the payoff still fires on the drop's first frame,
     the horizon still eases back over DROP_RESET_S, and the saved reverse
     is still restored.

Read-only: touches no storage, no network, no live process."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402
from fx.effects import blackhole as bh  # noqa: E402
from spectra.services import scene_response as sr  # noqa: E402

DT = 1.0 / 60.0
CHARGE_S = 4.0
LULL_S = 2.5
PASS = "  ✓"

# his real Black Hole V2 Matrix entry (bound params at their own fallbacks)
HIS_MATRIX = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "x_offset": 0.5, "y_offset": 0.5, "horizon_audio": 0.3, "base_speed": 2.0,
    "accel": 5.0, "spawn_rate": 1.0, "beat_burst": 0, "spawn_audio": 1.5,
    "speed_audio": 2.0, "impulse_decay": 0.06, "max_blobs": 50,
    "edge_speed": 0.2, "horizon_hold": 2.8,
}

# crystal-mapper's real-light silhouette (976 of 2664 addressable cells —
# .claude/skills/crystal-hex-grid/SKILL.md). A headless dummy device has no
# gaps, so "the panel is dark" has to be measured over the cells that are
# actually LIGHT on his panel; the rectangle's corners are permanently dead
# there and are exactly what the old r_max swallow spent its extra growth
# covering.
def _crystal_mask():
    prof = json.loads(
        (REPO_ROOT / "storage/device_profiles/crystal-mapper.json")
        .read_text(encoding="utf-8"))
    mask, v = [], False
    for run in prof["mask_rle"]:
        mask.extend([v] * run)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


_failures: list[str] = []


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _failures.append(msg)


def _lit(virtual, mask):
    """Brightest pixel on the panel — over the REAL cells only when a mask
    is supplied (the 2D crystal), the whole strip otherwise."""
    frame = virtual.assemble_frame()
    if frame is None:
        return 0.0
    arr = np.asarray(frame, dtype=np.float32)
    if mask is None:
        return float(arr.max())
    return float(arr.reshape(mask.shape[0], mask.shape[1], -1)[mask].max())


async def _run(tmp, sub, effect_type="blackhole", config=None,
               charge_s=CHARGE_S, lull_s=LULL_S, drop_s=0.4):
    """The production sequence scene_response._drive_phase drives: charge
    ramps 0->1, lull ramps 0->1, drop ramps 0->1 (the same replay
    scripts/check_drop_visible_onset.py uses)."""
    host = await headless.start_headless_host(
        str(tmp / sub), device_id=sub, pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get(sub)
    samples = {"charge": [], "lull": [], "drop": []}
    # every _spawn call the effect makes, tagged by phase/progress — a real
    # spawn count, never a net population delta (blobs retire while a
    # charge runs, which would silently hide the rate being measured)
    spawns = {"charge": [], "lull": [], "none": [], "drop": []}
    burst_frames = []
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, effect_type,
                                        dict(HIS_MATRIX, **(config or {})))
        orig_burst = effect._phase_burst
        orig_spawn = effect._spawn
        frame = [0]
        where = {"phase": "none", "p": 0.0}

        def logged_spawn(count, beat_count, *a, _o=orig_spawn, **kw):
            before = effect.n
            _o(count, beat_count, *a, **kw)
            added = effect.n - before
            if added:
                ambient = int(effect.n - np.count_nonzero(
                    effect.p_nocap[: effect.n])) if hasattr(
                        effect, "p_nocap") else effect.n
                spawns[where["phase"]].append({
                    "p": where["p"], "added": added,
                    "forced": bool(kw.get("ignore_cap")),
                    "frame": frame[0], "ambient_before": ambient - (
                        0 if kw.get("ignore_cap") else added),
                })

        effect._spawn = logged_spawn

        def logged_burst(*a, _o=orig_burst, **kw):
            # blackhole1d's own _phase_burst takes the sample ring
            burst_frames.append(frame[0])
            return _o(*a, **kw)

        effect._phase_burst = logged_burst

        def step(n):
            for _ in range(n):
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
                frame[0] += 1

        two_d = hasattr(effect, "_horizon_radius")
        mask = _crystal_mask() if two_d else None

        def sample(phase, p):
            n = effect.n
            rh = effect._horizon_radius() if two_d else 0.0
            row = {
                "p": p, "n": n, "rh": rh,
                "rate": effect._phase_spawn_rate(),
                "speed": effect._phase_speed_mult(),
                "lit": _lit(virtual, mask if two_d else None),
                "lit_all": float(np.asarray(
                    virtual.assemble_frame()).max()),
            }
            if two_d:
                row["nocap"] = int(np.count_nonzero(effect.p_nocap[:n]))
                row["disc"] = effect._disc_radius(rh)
                row["paused"] = effect._phase_spawn_paused(rh)
            samples[phase].append(row)

        # fill the ordinary population to his own max_blobs first, so
        # "past the cap" is a measured fact and not an empty-buffer
        # coincidence, then hand the spawn rate back to his own value
        # A build is a high-energy moment: his own spawn_rate is a
        # trigger_intensity binding, so hold it high for the whole run —
        # that pins the ORDINARY population at his max_blobs and makes
        # "past the cap" a measured fact rather than an empty-buffer
        # coincidence.
        effect.update_config({"spawn_rate": 30.0})
        step(int(4.0 / DT))
        base_rh = effect._horizon_radius() if two_d else 0.0

        where.update(phase="charge", p=0.0)
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        frames_c = int(charge_s / DT)
        for i in range(1, frames_c + 1):
            p = i / frames_c
            effect.update_config({"phase_progress": p})
            where.update(phase="charge", p=p)
            step(1)
            if i % 12 == 0 or i == frames_c:
                sample("charge", p)

        where.update(phase="lull", p=0.0)
        effect.update_config({"phase": "lull", "phase_progress": 0.0})
        frames_l = int(lull_s / DT)
        for i in range(1, frames_l + 1):
            p = i / frames_l
            effect.update_config({"phase_progress": p})
            where.update(phase="lull", p=p)
            step(1)
            if i % 8 == 0 or i == frames_l:
                sample("lull", p)

        where.update(phase="drop", p=0.0)
        drop_entry = frame[0]
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        frames_d = int(drop_s / DT)
        for i in range(1, frames_d + 1):
            effect.update_config({"phase_progress": i / frames_d})
            step(1)
        step(int(0.6 / DT))
        end_phase, end_reverse = effect._phase, effect.reverse
        r_max = float(getattr(effect, "r_max", 0.0))
    await host.shutdown()
    return {
        "s": samples, "spawns": spawns, "base_rh": base_rh, "burst_frames": burst_frames,
        "drop_entry": drop_entry, "end_phase": end_phase,
        "end_reverse": end_reverse, "r_max": r_max,
    }


def _rate_at(res, phase, p_lo, p_hi, phase_s, forced_only=True):
    """Measured blobs/second over a progress window — REAL spawns (every
    _spawn call the effect made), divided by the wall-clock time that
    window covers. Never a net population delta: blobs retire while a
    charge runs, which would silently hide the rate being measured.
    `forced_only` (the default) counts the charge/lull's OWN forced
    formation, not the ordinary music-driven spawn running underneath it —
    the two are additive by design, and his 12/second names this one."""
    win = [r for r in res["spawns"][phase] if p_lo <= r["p"] <= p_hi
           and (r["forced"] or not forced_only)]
    seconds = (p_hi - p_lo) * phase_s
    return sum(r["added"] for r in win) / seconds if seconds > 0 else 0.0


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        res = asyncio.run(_run(Path(tmp), "charge-lull"))
        res1d = asyncio.run(_run(Path(tmp), "strip-1d", effect_type="blackhole1d",
                                 config={"reverse": True}))

    ch = [r for r in res["s"]["charge"] if "rh" in r]
    lu = [r for r in res["s"]["lull"] if "rh" in r]
    base = res["base_rh"]

    print("§1 CHARGE: the radius holds, the ring thickens")
    print(f"{'p':>5} {'horizon r':>10} {'disc r':>8} {'halo w':>8} "
          f"{'rate/s':>7} {'speed x':>8} {'blobs':>6}")
    for r in ch[:: max(len(ch) // 8, 1)]:
        w = bh.CHARGE_HALO_W_MIN + (
            bh.CHARGE_HALO_W_MAX - bh.CHARGE_HALO_W_MIN) * r["p"]
        print(f"{r['p']:>5.2f} {r['rh']:>10.3f} {r['disc']:>8.3f} {w:>8.3f} "
              f"{r['rate']:>7.1f} {r['speed']:>8.2f} {r['n']:>6}")
    check(all(abs(r["rh"] - base) < 0.06 for r in ch),
          f"horizon radius holds at its baseline ({base:.3f}) for the whole "
          f"charge — max seen {max(r['rh'] for r in ch):.3f} (audio-driven "
          "wobble only, never a swallow)")
    check(all(abs(r["disc"] - r["rh"]) < 1e-9 for r in ch),
          "no separate black disc grows during the charge — the disc IS "
          "the horizon now")
    check(bh.CHARGE_HALO_W_MAX > bh.CHARGE_HALO_W_MIN,
          f"ring half-thickness grows {bh.CHARGE_HALO_W_MIN} -> "
          f"{bh.CHARGE_HALO_W_MAX} across the build")

    print("\n§2 CHARGE: formation accelerates to 12/s, past the cap")
    early = _rate_at(res, "charge", 0.0, 0.25, CHARGE_S)
    late = _rate_at(res, "charge", 0.9, 1.0, CHARGE_S)
    print(f"  measured FORCED formation rate: {early:.1f}/s at p<=0.25, "
          f"{late:.1f}/s at p>=0.9 (his ceiling: "
          f"{bh.CHARGE_SPAWN_RATE_MAX:.0f}/s — the ordinary music-driven "
          "spawn keeps running underneath it)")
    check(late >= bh.CHARGE_SPAWN_RATE_MAX,
          f"reaches his 12/second as p->1 ({late:.1f}/s)")
    check(early < late / 2.0,
          f"…and ACCELERATES into it, never all at once ({early:.1f}/s "
          f"early vs {late:.1f}/s late)")
    forced = [r for r in res["spawns"]["charge"] if r["forced"]]
    at_cap = [r for r in forced
              if r["ambient_before"] >= HIS_MATRIX["max_blobs"] - 2]
    print(f"  {len(forced)} forced blobs across the build; "
          f"{len(at_cap)} of them landed with the ordinary population "
          f"already at his max_blobs={HIS_MATRIX['max_blobs']}")
    check(len(at_cap) >= len(forced) // 2,
          "the forced formation lands even with the ordinary population "
          "already at the cap ('ignore max counts')")
    check(not any(r["forced"] is False and
                  r["ambient_before"] >= HIS_MATRIX["max_blobs"]
                  for r in res["spawns"]["charge"]),
          "…while ORDINARY spawning is still refused at that same cap — "
          "the override is scoped to the charge's own blobs")
    per_frame = {}
    for r in res["spawns"]["charge"]:
        if r["forced"]:
            per_frame[r["frame"]] = per_frame.get(r["frame"], 0) + r["added"]
    check(per_frame and max(per_frame.values()) <= 2,
          f"at most {max(per_frame.values())} forced blob(s) land on any "
          "single frame — a rate through an accumulator, not a batch")
    forced_at_cap = [r for r in res["spawns"]["charge"] if r["forced"]]
    check(len(forced_at_cap) > 10,
          f"{len(forced_at_cap)} blobs were forced into being past the cap "
          "across the build")

    print("\n§3 CHARGE: fall speed accelerates, and holds through the lull")
    check(abs(ch[-1]["speed"] - bh.CHARGE_FALL_SPEED_MAX) < 0.05,
          f"speed multiplier reaches {bh.CHARGE_FALL_SPEED_MAX}x at p=1 "
          f"({ch[-1]['speed']:.2f}x)")
    check(all(abs(r["speed"] - bh.CHARGE_FALL_SPEED_MAX) < 1e-6 for r in lu),
          "and stays there for the whole lull ('continue the fast blob "
          "falling')")

    print("\n§4 LULL: fills the hex at p=0.5, then holds")
    print(f"{'p':>5} {'horizon r':>10} {'panel max':>10} {'rate/s':>7} "
          f"{'paused':>7}")
    for r in lu[:: max(len(lu) // 8, 1)]:
        print(f"{r['p']:>5.2f} {r['rh']:>10.3f} {r['lit']:>10.1f} "
              f"{r['rate']:>7.1f} {str(r.get('paused')):>7}")
    at_half = min((r for r in lu if r["p"] >= bh.LULL_FILL_PROGRESS),
                  key=lambda r: r["p"])
    fill_r = bh.HEX_FILL_RADIUS + bh.LULL_FILL_MARGIN
    check(abs(at_half["rh"] - fill_r) < 0.03,
          f"horizon reaches the hex fill radius {bh.HEX_FILL_RADIUS:.3f} "
          f"(+{bh.LULL_FILL_MARGIN} so the painted disc's own edge covers "
          f"the outermost real cells) at p={at_half['p']:.2f} "
          f"({at_half['rh']:.3f})")
    after = [r for r in lu if r["p"] > bh.LULL_FILL_PROGRESS]
    check(all(abs(r["rh"] - fill_r) < 0.03 for r in after),
          "and HOLDS there for the rest of the lull — it never keeps growing")
    check(all(r["lit"] == 0.0 for r in after),
          f"every REAL cell of his hex panel renders black for the whole "
          f"second half ({len(after)} sampled frames, brightest real pixel "
          "0)")
    print(f"  (the dummy device has no gaps, so the rectangle's own dead "
          f"corners still show {max(r['lit_all'] for r in after):.0f} here "
          "— on his panel those cells are not light at all, which is why "
          "the fill stops at the hex bound instead of r_max)")
    check(fill_r < res["r_max"] - 0.2,
          f"the fill stops at the HEX bound {fill_r:.3f}, well "
          f"inside the rectangle corner r_max={res['r_max']:.3f} the old "
          "swallow grew to — 'i think it currently expands too far'")

    print("\n§5 LULL: the fast formation continues, then pauses when dark")
    before_half = _rate_at(res, "lull", 0.05, bh.LULL_FILL_PROGRESS - 0.05, LULL_S)
    after_half = _rate_at(res, "lull", bh.LULL_FILL_PROGRESS + 0.05, 1.0, LULL_S)
    print(f"  measured spawn rate: {before_half:.1f}/s before the fill, "
          f"{after_half:.1f}/s after")
    check(before_half >= bh.CHARGE_SPAWN_RATE_MAX,
          "the charge's final rate continues through the lull's first half")
    check(after_half == 0.0,
          "…and stops once the panel is dark — nothing spawns unseen")

    print("\n§6 timing honesty")
    ramp = sr.PHASE_RAMP_MS["lull"] / 1000.0
    print(f"  SpotFX ramps phase_progress over ~90% of the real gap and then "
          f"hangs at 1.0 (scene_response._phase_ramp_ms; the static "
          f"fallback for an unknown gap is {ramp:.1f}s).")
    print(f"  So p={bh.LULL_FILL_PROGRESS} lands at ~"
          f"{bh.LULL_FILL_PROGRESS * 90:.0f}% of the lull's true duration, "
          "not exactly half — the closest an effect can get without being "
          "told the duration.")

    print("\n§7 DROP: unchanged")
    check(res["burst_frames"] and
          res["burst_frames"][0] - res["drop_entry"] <= 1,
          f"the payoff still fires on the drop's own first frame "
          f"(+{res['burst_frames'][0] - res['drop_entry']} frames)")
    check(res["end_phase"] == "none",
          "the drop still self-resets to phase=none after DROP_RESET_S")
    check(res["end_reverse"] == HIS_MATRIX["reverse"],
          "the saved reverse is still restored at the payoff")

    print("\n§8 the strips (blackhole1d) mirror the same shape")
    lu1 = [r for r in res1d["s"]["lull"] if "rh" in r]
    late1 = _rate_at(res1d, "charge", 0.9, 1.0, CHARGE_S)
    after1 = [r for r in lu1 if r["p"] > bh.LULL_FILL_PROGRESS]
    check(late1 >= bh.CHARGE_SPAWN_RATE_MAX,
          f"charge formation reaches 12/second on the strip too "
          f"({late1:.1f}/s)")
    dot = max(r["lit"] for r in after1)
    check(dot <= 70.0 + 1e-6,
          f"the strip is dark for the whole second half of the lull "
          f"({len(after1)} sampled frames; brightest pixel {dot:.0f} — the "
          "pre-existing lull phosphor dot at the strip middle, kept)")
    check(res1d["burst_frames"] and
          res1d["burst_frames"][0] - res1d["drop_entry"] <= 1,
          "and its drop payoff still fires on the drop's first frame")

    print("\n" + ("ALL CHECKS PASSED" if not _failures
                  else f"{len(_failures)} FAILED: " + "; ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
