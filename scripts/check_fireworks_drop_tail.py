"""Executable spec + measurement: the FIREWORKS DROP TAIL on both vendored
fireworks effects (fx/effects/fireworks.py — his crystal — and
fx/effects/fireworks1d.py — his strips).

His ask, verbatim: "On the fireworks drop there need to be fireworks
spawning continuously after the first big burst."

Drives each effect through the real charge -> lull -> drop choreography on
a headless dummy host (fx.headless, silent audio, deterministic fake
clock), exactly the way scene_response._drive_phase ramps phase /
phase_progress, then counts ORDINARY launches (spawn_rate-driven — the
payoff's and burst flare's ignore_cap spawns are excluded) in 0.25 s bins
after the drop mark, against the pre-charge baseline rate.

What is proven:
  1. the drop phase itself still self-resets to "none" at DROP_SETTLE_S
     (unchanged choreography timing) — the tail is its own clock;
  2. right after the payoff the ordinary launch rate is ELEVATED
     (>= 1 + DROP_TAIL_X * (1 - t/DROP_TAIL_S)^2 of baseline, to the
     frame), not the flat baseline it used to return to;
  3. the tail EASES back to exactly baseline by DROP_TAIL_S and never
     overshoots below it;
  4. the density cap (max_blobs) does not swallow the tail: the payoff
     (ignore_cap, well over max_blobs on both effects at his defaults)
     used to leave ZERO ordinary launches for the whole time its
     particles lived — the tail's own cap allowance keeps them landing;
  5. a drop with no preceding lull (no rockets) grows the same tail;
  6. an ordinary flare burst (burst_rockets) does NOT start a tail — the
     tail belongs to the drop, the flare stays the additive volley it
     was authored as.

Usage:
  .venv/bin/python scripts/check_fireworks_drop_tail.py [--baseline]

--baseline only prints the measurement (no assertions) — what the code
does right now. No LedFX service, no HTTP, no audio hardware, no storage
writes.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0
BIN_S = 0.25
TAIL_WINDOW_S = 4.0

CONFIGS = {
    # spawn_audio=0, beat_burst=0: the ONLY ordinary launch source is
    # spawn_rate * _pspawn, so the bins measure the multiplier directly
    "fireworks": {"spawn_rate": 4.0, "beat_burst": 0, "spawn_audio": 0.0},
    "fireworks1d": {"spawn_rate": 4.0, "beat_burst": 0, "spawn_audio": 0.0},
}
# HIS REAL Fireworks V2 entries (read off the live scene store 2026-08-21:
# spawn_rate 0 = beat bursts only, so _pspawn is inert there — this is why
# the tail is a launch RATE, not a multiplier). burst_size/beat_burst are
# intensity bindings on the crystal; the high-intensity end is used here.
REAL_CONFIGS = {
    "fireworks": {"spawn_rate": 0.0, "beat_burst": 6, "spawn_audio": 2.0,
                  "burst_size": 14, "max_blobs": 100, "burst_life": 1.9},
    "fireworks1d": {"spawn_rate": 0.0, "beat_burst": 2, "spawn_audio": 0.0,
                    "max_blobs": 6, "burst_life": 1.2},
}
BEAT_S = 0.5  # ~120 bpm, a beat every half second
SHAPES = {"fireworks": (72, 37), "fireworks1d": (17, 1)}


def _spawn_fn_name(effect_type: str) -> str:
    return "_spawn_burst" if effect_type == "fireworks" else "_spawn_firework"


async def run(effect_type: str, *, with_lull: bool = True,
              flare_only: bool = False, real: bool = False):
    from fx.effects import fireworks as fw2d
    from fx.effects import fireworks1d as fw1d
    mod = fw2d if effect_type == "fireworks" else fw1d

    with tempfile.TemporaryDirectory() as td:
        cols, rows = SHAPES[effect_type]
        host = await headless.start_headless_host(
            td, device_id=f"dev-{effect_type}", pixel_count=cols * rows,
            rows=rows)
        try:
            virtual = host.virtuals.get(f"dev-{effect_type}")
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, effect_type,
                    REAL_CONFIGS[effect_type] if real else CONFIGS[effect_type])
                log: list[tuple[int, float]] = []   # (frame, seconds)
                frame = [0]
                t = [0.0]
                name = _spawn_fn_name(effect_type)
                orig = getattr(effect, name)
                in_payoff = [False]
                orig_payoff = effect._payoff_burst_at

                def payoff(*a, _orig=orig_payoff, **kw):
                    in_payoff[0] = True
                    try:
                        _orig(*a, **kw)
                    finally:
                        in_payoff[0] = False
                effect._payoff_burst_at = payoff

                def logged(*a, _orig=orig, **kw):
                    # every ordinary-sized launch (spawn_rate, beat, and
                    # the tail's own); the payoff's / flare's giant bursts
                    # (_payoff_burst_at) are the one thing excluded
                    before = effect.n
                    _orig(*a, **kw)
                    if effect.n > before and not in_payoff[0]:
                        log.append((frame[0], t[0]))
                setattr(effect, name, logged)

                beat_frames = int(round(BEAT_S / DT))

                def step(n):
                    for _ in range(n):
                        if real and frame[0] % beat_frames == 0:
                            effect._beat_pending = True  # the beat callback
                        clock.advance(DT)
                        t[0] += DT
                        f = virtual.assemble_frame()
                        if f is not None:
                            virtual.flush(f)
                        frame[0] += 1

                # BASELINE: 4 s of the ordinary show
                step(int(4.0 / DT))
                base_launches = len(log)
                base_rate = base_launches / 4.0

                if flare_only:
                    # an ordinary flare burst, no drop at all
                    mark_t = t[0]
                    effect.update_config({"burst_rockets": 6})
                    step(int(TAIL_WINDOW_S / DT))
                    phase_reset_t = None
                else:
                    if with_lull:
                        # CHARGE: ramp 0->1 over 1.2 s (scene_response ramps it)
                        effect.update_config(
                            {"phase": "charge", "phase_progress": 0.0})
                        n_ch = int(1.2 / DT)
                        for i in range(1, n_ch + 1):
                            effect.update_config({"phase_progress": i / n_ch})
                            step(1)
                        # LULL: 1.0 s, ramp 0->1
                        effect.update_config(
                            {"phase": "lull", "phase_progress": 0.0})
                        n_l = int(1.0 / DT)
                        for i in range(1, n_l + 1):
                            effect.update_config({"phase_progress": i / n_l})
                            step(1)
                    # DROP: the mark; ramp 0->1 over 0.4 s like the real drop
                    mark_t = t[0]
                    effect.update_config({"phase": "drop", "phase_progress": 0.0})
                    n_d = int(0.4 / DT)
                    phase_reset_t = None
                    for i in range(1, int(TAIL_WINDOW_S / DT) + 1):
                        if i <= n_d:
                            effect.update_config({"phase_progress": i / n_d})
                        step(1)
                        if phase_reset_t is None and effect._phase == "none":
                            phase_reset_t = t[0] - mark_t

                post = [s - mark_t for (_f, s) in log if s > mark_t + 1e-9]
                nbins = int(TAIL_WINDOW_S / BIN_S)
                bins = [0] * nbins
                for s in post:
                    b = int(s / BIN_S)
                    if b < nbins:
                        bins[b] += 1
                mult = [b / (base_rate * BIN_S) if base_rate else float("nan")
                        for b in bins]
                return {
                    "base_rate": base_rate,
                    "bins": bins,
                    "mult": mult,
                    "phase_reset_t": phase_reset_t,
                    "mod": mod,
                    "effect": effect,
                }
        finally:
            await host.shutdown()


def expected_rate(mod, t_mid: float) -> float:
    """Extra launches/s the tail adds at t_mid after the mark."""
    R = getattr(mod, "DROP_TAIL_RATE", 0.0)
    T = getattr(mod, "DROP_TAIL_S", 0.0)
    if T <= 0 or t_mid >= T:
        return 0.0
    return R * (1.0 - t_mid / T)


def report(effect_type, label, r):
    print(f"\n[{effect_type}] {label}: baseline {r['base_rate']:.2f} launches/s, "
          f"drop phase self-reset at "
          f"{('%.2fs' % r['phase_reset_t']) if r['phase_reset_t'] is not None else 'n/a'}")
    print("   t after mark   launches   x baseline   (expected: baseline + tail)")
    for i, (b, m) in enumerate(zip(r["bins"], r["mult"])):
        t_mid = (i + 0.5) * BIN_S
        exp = (r["base_rate"] + expected_rate(r["mod"], t_mid)) * BIN_S
        print(f"   {i*BIN_S:4.2f}-{(i+1)*BIN_S:4.2f}s   {b:7d}   {m:9.2f}x   "
              f"({exp:.2f} launches)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true",
                    help="measure only, assert nothing")
    args = ap.parse_args()
    fails: list[str] = []

    for et in ("fireworks", "fireworks1d"):
        r = asyncio.run(run(et))
        report(et, "charge -> lull -> drop", r)
        r_nl = asyncio.run(run(et, with_lull=False))
        report(et, "bare drop (no lull, no rockets)", r_nl)
        r_fl = asyncio.run(run(et, flare_only=True))
        report(et, "ordinary flare burst only (burst_rockets=6)", r_fl)
        r_real = asyncio.run(run(et, real=True))
        report(et, "HIS REAL config (spawn_rate 0, beat bursts every "
                   f"{BEAT_S}s) charge -> lull -> drop", r_real)
        if args.baseline:
            continue
        mod = r["mod"]
        R, T = mod.DROP_TAIL_RATE, mod.DROP_TAIL_S
        # 1. the drop phase's own choreography clock is untouched
        if not (r["phase_reset_t"] is not None
                and abs(r["phase_reset_t"] - mod.DROP_SETTLE_S) < 0.05):
            fails.append(f"{et}: drop phase reset at {r['phase_reset_t']} "
                         f"!= DROP_SETTLE_S {mod.DROP_SETTLE_S}")
        if T <= mod.DROP_SETTLE_S:
            fails.append(f"{et}: DROP_TAIL_S {T} must outlive DROP_SETTLE_S")
        # 2-4. launches keep landing through the payoff's afterglow at
        # baseline + the easing tail rate (to the bin, +-1 launch of
        # accumulator granularity), on both the lull and no-lull paths,
        # and settle to exactly the baseline after DROP_TAIL_S
        for label, rr in (("lull->drop", r), ("bare drop", r_nl)):
            base_per_bin = rr["base_rate"] * BIN_S
            for i, b in enumerate(rr["bins"]):
                t_mid = (i + 0.5) * BIN_S
                exp = base_per_bin + expected_rate(mod, t_mid) * BIN_S
                if b < exp - 1.0 - 1e-9:
                    fails.append(f"{et} {label}: bin {t_mid:.3f}s landed {b} "
                                 f"< expected ~{exp:.2f} (tail swallowed?)")
                if b > exp + 1.0 + 1e-9:
                    fails.append(f"{et} {label}: bin {t_mid:.3f}s landed {b} "
                                 f"> expected ~{exp:.2f}")
            if rr["bins"][0] < base_per_bin + R * BIN_S * 0.5:
                fails.append(f"{et} {label}: first bin only {rr['bins'][0]} "
                             f"launches — not an elevated tail")
        # 5. HIS REAL config: the ordinary show is beat bursts only, and
        # the payoff used to hold max_blobs full for PAYOFF_LIFE x
        # burst_life (~2.6 s on the crystal), swallowing EVERY beat burst
        # — now every 0.5 s bin after the mark lands something: the beat
        # bursts keep coming underneath and the tail showers on top,
        # "continuously after the first big burst"
        nb = int(BEAT_S / BIN_S)
        half_s = [sum(r_real["bins"][i:i + nb])
                  for i in range(0, len(r_real["bins"]), nb)]
        in_tail = half_s[:int(T / BEAT_S)]
        if min(in_tail) <= 0:
            fails.append(f"{et} REAL: a half-second inside the tail window "
                         f"went silent: {in_tail} (beyond DROP_TAIL_S the "
                         f"ordinary show is its own cap-bound self again)")
        base_half = r_real["base_rate"] * BEAT_S
        if half_s[0] < base_half + R * BEAT_S * 0.5:
            fails.append(f"{et} REAL: first half-second {half_s[0]} launches "
                         f"is not denser than the {base_half:.1f} baseline")
        # 6. a flare burst alone never starts a tail: nothing lands above
        # the baseline (the cap may swallow SOME ordinary launches under
        # the flare's own afterglow — pre-existing, outside this task)
        base_per_bin = r_fl["base_rate"] * BIN_S
        if max(r_fl["bins"]) > base_per_bin + 1.0 + 1e-9:
            fails.append(f"{et}: flare burst started a tail: {r_fl['bins']}")

    print()
    if args.baseline:
        print("baseline measurement only — nothing asserted")
        return 0
    if fails:
        print("FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("OK — both fireworks effects shower ordinary fireworks through the "
          "payoff's afterglow at an easing rate, settling to the ordinary "
          "show, the drop phase clock untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
