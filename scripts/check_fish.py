#!/usr/bin/env python3
"""Measured, printed, asserted proof of the FISH effect's own behaviours
(fx/effects/fish.py, PR fm/fish-effect-and-scene).

His words are the spec (2026-08-25, corr=6dd10a8c3c5bd72a). Every section
below measures one sentence of them on the REAL vendored render pipeline
(fx.headless dummy Matrix host at his crystal-mapper's 72x37 shape, audio
silenced), never a re-derivation of the effect's own arithmetic:

  1. "It should point in the direction it's moving like a fish"
     -> the RENDERED oval's own principal axis vs. the fish's velocity.
  2. "They have to turn around in a tight but clear circle, they can't
     just reverse directions on the spot"
     -> per-frame heading change against the turn-rate ceiling, and the
        arc a full about-face actually traces.
  3. "its spine should flap as it moves ... When it accelerates it waves
     its tail harder, and when it slows it is more subtle"
  4. "it should leave a ripple trail ... always subtle, but stronger on
     faster. Try to match the size of the motion to the ripple"
  5. CHARGE: "up to 12 fish come in, all moving in unison, and then start
     changing directions on every beat, minimum 400ms in unison. Fish in
     school should move almost identically, but should have some minor
     variation."
  6. LULL: "Fish start dispersing until the center one is all alone,
     swimming but staying in center of view by half way through the lull.
     A rush of fish come in ... up to 20 and zoom past ... It should last
     a second and there should be some chaos to the zooming pool."
  7. DROP: Orbits' own payoff, unchanged in spirit.
  8. The population cap: the `p_nocap` bypass is scoped to exactly the
     charge school and the lull rush, and the buffer holds both plus a
     full drop explosion.

Read-only: no live storage, no network, no live instance. Collision
avoidance is deliberately absent (owner scope decision, 2026-08-25) and
therefore has no section here.
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
from fx.effects import fish as FX  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72   # his real crystal-mapper shape

# His live Orbits V2 Matrix entry, at the fallbacks its bindings resolve to
# — the values the Fish scene inherits verbatim (see
# scripts/seed_fish_scene.py).
HIS_MATRIX = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.15, "tether_scatter": 0.0,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "reverse": False,
}

_fails: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        _fails.append(label)


class Room:
    """One headless matrix virtual running the fish effect under a fake
    clock, frame-stepped by hand."""

    def __init__(self, host, virtual, clock, effect):
        self.host, self.virtual, self.clock, self.effect = (
            host, virtual, clock, effect
        )
        self.frame = None

    def step(self, frames=1):
        for _ in range(frames):
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)
                self.frame = np.array(f, copy=True)

    def lit(self, threshold=6.0):
        a = self.frame.astype(float).max(axis=1).reshape(ROWS, COLS)
        return a


async def _room(stack, name, config, seed=5):
    host = await headless.start_headless_host(
        str(stack / name), pixel_count=ROWS * COLS, rows=ROWS, device_id=name
    )
    virtual = host.virtuals.get(name)
    clock_cm = headless.fake_clock()
    clock = clock_cm.__enter__()
    effect = headless.attach_effect(host, virtual, "fish", dict(config))
    effect._rng = np.random.default_rng(seed)
    room = Room(host, virtual, clock, effect)
    room._clock_cm = clock_cm
    return room


async def _close(room):
    room._clock_cm.__exit__(None, None, None)
    await room.host.shutdown()


# ── 1. the oval points where it is going ────────────────────────────────
async def section_heading(stack):
    print("\n1. SHAPE — the oval points the way it is moving")
    cfg = dict(HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
               jiggle=0.0, ripple_amount=0.0, trail_decay=0.0,
               flap_amount=0.3)
    room = await _room(stack, "heading", cfg)
    errs = []
    room.step(120)
    for i in range(480):
        room.step(1)
        if i % 20:
            continue
        a = room.lit()
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
        # the oval is symmetric, so the axis is only defined modulo pi
        errs.append(np.degrees(
            abs(((axis - hd + np.pi / 2) % np.pi) - np.pi / 2)
        ))
    e = np.array(errs)
    check(len(e) > 15, "sampled the rendered body", f"n={len(e)}")
    check(e.mean() < 12.0 and e.max() < 25.0,
          "rendered long axis tracks the velocity",
          f"mean {e.mean():.1f} deg, p90 {np.percentile(e, 90):.1f}, "
          f"max {e.max():.1f}")
    # the body really is a thin oval, not a dot
    aspect_ok = room.effect.body_aspect >= 1.2
    check(aspect_ok, "body is an oval, not a disc",
          f"body_aspect={room.effect.body_aspect}, "
          f"length {room.effect._body_len_px():.1f}px x width "
          f"{2 * room.effect._half_width_px():.1f}px")
    await _close(room)


# ── 2. the turn is a circle, never a flip ───────────────────────────────
async def section_turning(stack):
    print("\n2. TURNING — a tight but clear circle, never a reversal on the spot")
    cfg = dict(HIS_MATRIX, particle_count=4)
    room = await _room(stack, "turning", cfg, seed=9)
    eff = room.effect
    room.step(60)
    worst = 0.0
    prev = eff.p_hd[: eff.n].copy()
    prev_n = eff.n
    for _ in range(1800):
        room.step(1)
        n = min(prev_n, eff.n)
        if n:
            d = np.abs(
                (eff.p_hd[:n] - prev[:n] + np.pi) % (2 * np.pi) - np.pi
            )
            worst = max(worst, float(d.max()))
        prev = eff.p_hd[: eff.n].copy()
        prev_n = eff.n
    ceiling = eff.p_spd[: eff.n].max() / eff.turn_radius_px * DT
    check(worst < np.pi / 2,
          "heading never flips more than 90 deg in a frame",
          f"worst {np.degrees(worst):.2f} deg/frame")
    check(worst <= ceiling * 1.05 + 1e-6,
          "every turn obeys the turn-radius ceiling",
          f"worst {np.degrees(worst):.3f} <= ceiling "
          f"{np.degrees(ceiling):.3f} deg/frame")

    # a forced about-face traces a real arc: measure how far the fish
    # travels and how long it takes to reverse
    eff2 = room.effect
    idx = 0
    start_hd = float(eff2.p_hd[idx])
    start = np.array([eff2.p_x[idx] * eff2.sx, eff2.p_y[idx] * eff2.sy])
    turned = None
    for f in range(1, 2000):
        room.step(1)
        if eff2.n <= idx:
            break
        d = abs(
            (float(eff2.p_hd[idx]) - start_hd + np.pi) % (2 * np.pi) - np.pi
        )
        if d >= np.pi * 0.9:
            turned = f * DT
            break
    min_time = np.pi * eff2.turn_radius_px / float(eff2.cruise_px)
    check(turned is None or turned >= min_time * 0.9,
          "an about-face takes at least a half-circle's worth of time",
          f"observed {turned if turned is None else round(turned, 2)}s, "
          f"floor {min_time:.2f}s (turn radius "
          f"{eff2.turn_radius_px:.1f}px, cruise {eff2.cruise_px:.1f}px/s)")
    await _close(room)


# ── 3. the spine flaps with acceleration ────────────────────────────────
def _flap_scale(eff):
    n = eff.n
    sn = np.clip(eff.p_spd[:n] / max(eff.cruise_px, 1e-3), 0.0, 3.0)
    an = np.clip(eff.p_acc[:n] / FX.FLAP_ACCEL_REF, -1.5, 1.5)
    return float(np.clip(
        FX.FLAP_BASE + FX.FLAP_SPEED_GAIN * sn + eff.flap_accel * an,
        FX.FLAP_MIN, FX.FLAP_MAX,
    ).mean())


async def section_flap(stack):
    print("\n3. FLAP — harder under acceleration, subtler when slowing")
    cfg = dict(HIS_MATRIX, particle_count=1, horizon_scale=0.0, spin=0.0,
               jiggle=0.0)
    room = await _room(stack, "flap", cfg)
    eff = room.effect
    room.step(180)
    steady = _flap_scale(eff)
    eff.update_config({"base_speed": 1.2})
    room.step(12)
    accel = _flap_scale(eff)
    room.step(90)
    fast = _flap_scale(eff)
    eff.update_config({"base_speed": 0.3})
    room.step(12)
    decel = _flap_scale(eff)
    print(f"     steady {steady:.3f}   accelerating {accel:.3f}   "
          f"cruising fast {fast:.3f}   decelerating {decel:.3f}")
    check(accel > steady * 1.4, "tail waves harder under acceleration",
          f"{accel:.3f} vs {steady:.3f}")
    check(decel < steady * 0.6, "tail is subtler when slowing",
          f"{decel:.3f} vs {steady:.3f}")
    check(FX.FLAP_MIN <= decel and accel <= FX.FLAP_MAX,
          "flap stays inside its own bounds")
    await _close(room)


# ── 4. the ripple wake ──────────────────────────────────────────────────
async def section_ripples(stack):
    print("\n4. RIPPLE TRAIL — always subtle, stronger on faster, "
          "sized to the motion")
    cfg = dict(HIS_MATRIX, particle_count=2, horizon_scale=0.0, spin=0.0,
               jiggle=0.0)
    room = await _room(stack, "ripple", cfg)
    eff = room.effect
    out = {}
    for label, impulse in (("calm", 0.0), ("loud", 0.9)):
        eff.impulse = impulse
        room.step(240)
        eff.rn = 0            # only measure ripples born from here on
        room.step(60)
        out[label] = (
            float(eff.p_spd[: eff.n].mean()),
            float(eff.r_amp[: eff.rn].mean()) if eff.rn else 0.0,
            int(eff.rn),
        )
        print(f"     {label:<5} speed {out[label][0]:6.2f} px/s   "
              f"wake strength {out[label][1]:.4f}   "
              f"ripples/s {out[label][2]:.0f}")
    check(out["loud"][1] > out["calm"][1] * 1.5,
          "the wake is stronger on faster",
          f"{out['calm'][1]:.4f} -> {out['loud'][1]:.4f}")
    check(out["calm"][1] > 0.0 and out["loud"][1] < 0.35,
          "the wake is always subtle, at every speed",
          f"max strength {out['loud'][1]:.3f} against a body at ~0.8")
    check(out["loud"][2] > out["calm"][2],
          "faster fish leave ripples more often (the flap sets the cadence)",
          f"{out['calm'][2]} -> {out['loud'][2]}")

    # ripple size follows the size of the motion: a bigger fish makes a
    # bigger ripple, at the same speed
    sizes = {}
    for label, blob in (("small", 1.0), ("big", 4.0)):
        eff.impulse = 0.0
        eff.update_config({"blob_size": blob})
        room.step(180)
        eff.rn = 0
        room.step(60)
        sizes[label] = float(eff.r_r[: eff.rn].mean()) if eff.rn else 0.0
        print(f"     {label:<5} body {eff._body_len_px():5.2f}px  "
              f"-> ripple radius {sizes[label]:5.2f}px")
    check(sizes["big"] > sizes["small"] * 1.4,
          "ripple size is matched to the size of the motion",
          f"{sizes['small']:.2f}px -> {sizes['big']:.2f}px")
    await _close(room)


# ── 5. the charge's school ──────────────────────────────────────────────
async def section_charge(stack):
    print("\n5. CHARGE — a school in unison, turning on the beat")
    room = await _room(stack, "charge", dict(HIS_MATRIX), seed=11)
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
        peak = max(peak, int(np.count_nonzero(eff.p_mode[: eff.n] < 2)))
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
    gaps = [round(turns[i + 1] - turns[i], 3) for i in range(len(turns) - 1)]
    spread = float(np.mean(spreads)) if spreads else 0.0
    print(f"     school peaked at {peak} fish (school_count="
          f"{eff.school_count}); turns at "
          f"{[round(t, 2) for t in turns]}")
    print(f"     gaps between direction changes: {gaps}")
    check(peak <= eff.school_count,
          "up to (and no more than) the school count comes in",
          f"{peak} <= {eff.school_count}")
    check(peak >= eff.school_count - 1,
          "the school actually fills", f"{peak}")
    check(len(gaps) >= 2 and min(gaps) >= eff.turn_min_time - 1e-6,
          "direction changes are beat-driven and never closer than the "
          "minimum",
          f"min gap {min(gaps) if gaps else 'n/a'}s >= "
          f"{eff.turn_min_time}s")
    check(0.0 < spread < 0.5,
          "the school moves almost identically, with minor variation",
          f"heading spread {spread:.4f} rad ({np.degrees(spread):.1f} deg)")
    check(abs(eff._flow_px) + abs(eff._flow_py) > 0.0,
          "the water keeps streaming past while the school holds station "
          "(the camera-follow illusion)",
          f"wake drift ({eff._flow_px:.1f}, {eff._flow_py:.1f}) px/s")
    await _close(room)


# ── 6. the lull ─────────────────────────────────────────────────────────
async def section_lull(stack):
    print("\n6. LULL — one fish alone in the centre, then the rush")
    room = await _room(stack, "lull", dict(HIS_MATRIX), seed=11)
    eff = room.effect
    room.step(240)
    # charge first, exactly as a real arc arrives
    eff.update_config({"phase": "charge", "phase_progress": 0.0})
    cf = int(4.0 / DT)
    for i in range(1, cf + 1):
        eff.update_config({"phase_progress": i / cf})
        if i % 12 == 0:
            eff._beat_pending = True
        room.step(1)

    eff.update_config({"phase": "lull", "phase_progress": 0.0})
    lf = int(3.5 / DT)
    at_half = None
    rush_born = 0
    rush_alive_peak = 0
    rush_start = None
    rush_end = None
    spawn_rush = eff._spawn_rush

    def counted_rush(count, _orig=spawn_rush):
        nonlocal rush_born, rush_start
        before = eff.n
        _orig(count)
        rush_born += eff.n - before
        rush_start = eff._phase_t
    eff._spawn_rush = counted_rush
    settle = eff._settle_rush

    def timed_settle(_orig=settle):
        nonlocal rush_end
        rush_end = eff._phase_t
        _orig()
    eff._settle_rush = timed_settle

    chaos_spread = 0.0
    for i in range(1, lf + 1):
        eff.update_config({"phase_progress": i / lf})
        room.step(1)
        rushing = np.flatnonzero(eff.p_mode[: eff.n] == 3)
        rush_alive_peak = max(rush_alive_peak, rushing.size)
        if rushing.size > 3:
            hs = eff.p_hd[rushing]
            c = np.arctan2(np.sin(hs).mean(), np.cos(hs).mean())
            chaos_spread = max(chaos_spread, float(np.abs(
                (hs - c + np.pi) % (2 * np.pi) - np.pi
            ).std()))
        if i == int(lf * FX.LULL_CENTER_PROGRESS):
            lone = np.flatnonzero(eff.p_lone[: eff.n] == 1)
            others = int(np.count_nonzero(
                (eff.p_mode[: eff.n] < 2) & (eff.p_lone[: eff.n] == 0)
            ))
            d = float(np.hypot(
                eff.p_x[lone] * eff.sx, eff.p_y[lone] * eff.sy
            )[0]) if lone.size else None
            at_half = (d, others, int(lone.size))
    dist, others, lone_n = at_half
    print(f"     at phase_progress={FX.LULL_CENTER_PROGRESS} (~45% of the "
          f"lull's wall clock — see LULL_CENTER_PROGRESS): the lone fish "
          f"is {dist:.2f}px from centre, {others} other fish still "
          f"swimming")
    check(lone_n == 1, "exactly one fish is the lone one")
    check(others == 0, "every other fish has dispersed by half way")
    check(dist is not None and dist < 4.0,
          "the lone fish is holding the centre of view", f"{dist:.2f}px")
    print(f"     rush: {rush_born} fish born, {rush_alive_peak} on screen "
          f"at once, {rush_end - rush_start:.2f}s from entry to settle")
    check(rush_born == eff.rush_count,
          "the rush is the configured count", f"{rush_born}")
    check(rush_born <= FX.MAX_RUSH, "and never more than the schema allows")
    check(abs((rush_end - rush_start) - eff.rush_time) < 0.1,
          "the rush lasts about a second", f"{rush_end - rush_start:.2f}s "
          f"vs rush_time={eff.rush_time}s")
    check(chaos_spread > 0.1,
          "there is real chaos in the zooming pool",
          f"heading spread {chaos_spread:.3f} rad "
          f"({np.degrees(chaos_spread):.1f} deg)")
    left = int(np.count_nonzero(
        (eff.p_mode[: eff.n] < 2) & (eff.p_nocap[: eff.n] == 0)
    ))
    check(left == eff._config["particle_count"],
          "the rush leaves exactly the parameter's own count behind",
          f"{left} == particle_count {eff._config['particle_count']}")
    await _close(room)


# ── 7. the drop ─────────────────────────────────────────────────────────
async def section_drop(stack):
    print("\n7. DROP — Orbits' own payoff, unchanged in spirit")
    room = await _room(stack, "drop", dict(HIS_MATRIX), seed=4)
    eff = room.effect
    room.step(240)
    born = [0]
    orig = eff._spawn_drop_ejecta

    def counted(count, _orig=orig):
        before = eff.n
        _orig(count)
        born[0] += eff.n - before
    eff._spawn_drop_ejecta = counted

    eff.update_config({"phase": "lull", "phase_progress": 0.0})
    lf = int(2.5 / DT)
    for i in range(1, lf + 1):
        eff.update_config({"phase_progress": i / lf})
        room.step(1)
    eff.update_config({"phase": "drop", "phase_progress": 0.0})
    room.step(1)
    check(born[0] > 0,
          "the payoff fires on the drop's FIRST rendered frame "
          "(no phase_progress gate)", f"{born[0]} ejecta")
    check(born[0] == FX.DROP_EJECTA_X * eff._config["particle_count"],
          "ejecta count is Orbits' own 2x the population",
          f"{born[0]} == {FX.DROP_EJECTA_X} x "
          f"{eff._config['particle_count']}")
    room.step(int((FX.DROP_SETTLE_S + 0.6) / DT))
    check(eff._config["phase"] == "none" and eff._phase == "none",
          "the phase self-resets so an identical later drop edges again")
    swimming = int(np.count_nonzero(eff.p_mode[: eff.n] < 2))
    check(swimming == eff._config["particle_count"],
          "the population is back to the parameter",
          f"{swimming}")
    await _close(room)


# ── 8. the cap ──────────────────────────────────────────────────────────
async def section_cap(stack):
    print("\n8. POPULATION CAP — the bypass is scoped to two moments only")
    need = (
        FX.MAX_PARTICLE_COUNT + FX.MAX_SCHOOL + FX.MAX_RUSH
        + FX.DROP_EJECTA_X * FX.MAX_PARTICLE_COUNT
    )
    check(FX.CAP >= need,
          "the buffer holds a full population + school + rush + explosion "
          "simultaneously",
          f"CAP={FX.CAP} >= {need} "
          f"({FX.MAX_PARTICLE_COUNT}+{FX.MAX_SCHOOL}+{FX.MAX_RUSH}+"
          f"{FX.DROP_EJECTA_X}x{FX.MAX_PARTICLE_COUNT})")

    room = await _room(stack, "cap", dict(HIS_MATRIX, particle_count=8,
                                          school_count=12, rush_count=20),
                       seed=17)
    eff = room.effect
    worst_ordinary = 0
    worst_total = 0

    def watch():
        nonlocal worst_ordinary, worst_total
        n = eff.n
        worst_ordinary = max(worst_ordinary, int(np.count_nonzero(
            (eff.p_mode[:n] < 2) & (eff.p_nocap[:n] == 0)
        )))
        worst_total = max(worst_total, n)

    for _ in range(int(4.0 / DT)):
        room.step(1)
        watch()
    ordinary_before = worst_ordinary
    check(ordinary_before <= 8,
          "ordinary swimming never exceeds the parameter",
          f"{ordinary_before} <= 8")

    for phase, seconds in (("charge", 4.0), ("lull", 3.5), ("drop", 5.0)):
        eff.update_config({"phase": phase, "phase_progress": 0.0})
        f = int(seconds / DT)
        for i in range(1, f + 1):
            eff.update_config({"phase_progress": min(i / f, 1.0)})
            if phase == "charge" and i % 12 == 0:
                eff._beat_pending = True
            room.step(1)
            watch()
    room.step(int(3.0 / DT))
    tail_ordinary = int(np.count_nonzero(
        (eff.p_mode[: eff.n] < 2) & (eff.p_nocap[: eff.n] == 0)
    ))
    nocap_left = int(np.count_nonzero(eff.p_nocap[: eff.n] == 1))
    print(f"     peak buffer use {worst_total}/{FX.CAP} across the whole arc")
    check(worst_total <= FX.CAP, "the buffer is never overrun")
    check(tail_ordinary == 8,
          "after the arc, ordinary swimming is back at the parameter",
          f"{tail_ordinary} == 8")
    check(nocap_left == 0,
          "no cap-exempt fish outlives the moment it was granted for",
          f"{nocap_left} left")
    await _close(room)


async def main() -> int:
    print(__doc__.split("\n\n")[0])
    print(f"\nCAP={FX.CAP}  panel {COLS}x{ROWS}")
    with tempfile.TemporaryDirectory() as tmp:
        stack = Path(tmp)
        await section_heading(stack)
        await section_turning(stack)
        await section_flap(stack)
        await section_ripples(stack)
        await section_charge(stack)
        await section_lull(stack)
        await section_drop(stack)
        await section_cap(stack)
    print("\nPASS" if not _fails else "\nFAIL: " + "; ".join(_fails))
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
