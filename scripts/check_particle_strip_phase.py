#!/usr/bin/env python3
"""THE ORBITS AND FIREWORKS STRIPS ON THE STRIP PHASE LAYER, measured
(fx/effects/orbits1d.py, fireworks1d.py; strip phase plan phase 3,
revision 3) — and the fold of the particle strips' phase plumbing into the
layer (fx/effects/strip_phase.py, THE PARTICLE STRIPS' PLUMBING).

The Admiral, 2026-10-11: charge/lull/drop on the strips should "increase in
brightness and activity during charge, dim and relax into black for most
lulls, and big explosion of brightness and activity on the [drop]" — and,
binding, "i don't want to raise the white in the charge, or on the drop.
What I mean by increasing/decreasing brightness in this case is adding more
color, increasing the brightness of the colors, and having more baseline
effects, like more orbiting blobs, more fireworks, etc". His call 2: the
Orbits strip's charge SWELLS AND HOLDS. His call 3: every lull is black at
the room's dark point, except the Fireworks strip's rockets, which cross it
as faint embers.

Runs his real Orbits V2 and Fireworks V2 strip entries (live scenes.json,
read once and copied in below — the Orbits entry's two intensity bindings
at their middle) through one cycle on the real render pipeline
(fx.headless, a fake clock, deterministic audio fed to the effect's own
audio callback, numpy and the effect's own generator seeded) — 2.5 s
normal, a 4 s charge, a 7 s lull (told the room's dark point: 4 s in, 3 s
of dark), a drop at intensity 0.85 — written the way spectra
scene_response._drive_phase writes it (the arm, then the progress ramp over
90% of the gap). Twice each: the module as it was BEFORE this phase (pinned
at BEFORE_REF, loaded beside the current one as a second registered effect)
and as it is now. Prints brightness (mean perceived luminance), the worst
frame's count of pixels whiter than the set on the charge and the drop's
first 1.5 s (code that shares nothing with the layer — tests/
strip_phase_harness.py), and the counts that are "more going on".

Asserts the new runs follow his rule AND that the old runs show each defect
this phase retires (so every measure here can fail): the Orbits strip
shedding its build to ONE blob by the charge's end, its drop below its
charge; the Fireworks strip's charge clipped to 3 fireworks in flight by
his density cap and making them shorter-lived. Off-phase, both strips are
byte-identical to before.

THE FOLD: the Black Hole strip's choreography did not change in this phase,
only where its plumbing lives — so at the room's strip phase strength 0
(no activity scaling) it renders the SAME BYTES as before through a whole
cycle and through an orphaned lull's watchdog release. (At strength 1 the
charge's first frame now gets that frame's activity; the old in-render
edge reset its scaled counts for that one frame — a fix, measured here.)

Offline only; touches no storage, no network, no live process.

    .venv/bin/python scripts/check_particle_strip_phase.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fx import headless  # noqa: E402
from fx.effects import fireworks1d as fw1  # noqa: E402
from fx.effects import lull_dark, orbits1d as ob1  # noqa: E402
from fx.effects import particle_handoff  # noqa: E402
from fx.effects import strip_phase as sp  # noqa: E402
from strip_phase_harness import (PALETTE, _AudioFrame, lum,  # noqa: E402
                                 palette_of, whiter_than_set)

# The last commit before this phase (plan phase 2 merged: the Orbits and
# Fireworks strips still drew their own phases, every particle strip kept
# its own phase plumbing).
BEFORE_REF = "09f8c5baa6b3c72a13ba7533b9bd2492d955df90"

FPS = 60
DT = 1.0 / FPS
PX = 560
NORMAL_S, CHARGE_S, LULL_S, DROP_S = 2.5, 4.0, 7.0, 4.0
MAX_DARK_S = 3.0
DROP_INTENSITY = 0.85
DROP_RAMP_S = 0.4
WHITE_DROP_S = 1.5

# his live Orbits V2 strip entry (storage/spectra/scenes.json, read-only);
# particle_count and blob_size are intensity bindings there (2..6, 3..1) —
# their middles here
HIS_ORBITS = {
    "particle_count": 4, "blob_size": 2.0, "x_offset": 0.5, "spin": 0.15,
    "base_speed": 0.5, "jiggle": 0.2, "tether_scatter": 0.1,
    "reactivity_scale": 0.5, "speed_jump": 1, "speed_jog": 0.3,
    "brightness_audio": 0.8, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "overlap_blend": 1, "bounce_chance": 0.2,
    "implode_fade": 0.5, "implode_reach": 0.4,
}
# his live Fireworks V2 strip entry (the Fish scene's strip is the same)
HIS_FIREWORKS = {
    "blob_size": 3.03, "reverse": False, "spawn_rate": 0.5, "beat_burst": 2,
    "spawn_audio": 2, "burst_speed": 0.5, "burst_life": 1.2,
    "speed_audio": 2.5, "brightness_audio": 2, "max_blobs": 6, "drag": 0.85,
    "impulse_decay": 0.06, "trail_decay": 0.24,
}
# the Black Hole strip (the fold's proof) — his Black Hole V2 entry
HIS_BLACKHOLE = {
    "swirl": 3.1, "radius_scale": 1, "blob_size": 0.5, "reverse": True,
    "x_offset": 0.5, "base_speed": 1, "accel": 5, "spawn_rate": 1,
    "beat_burst": 2, "spawn_audio": 1, "speed_audio": 2.3,
    "impulse_decay": 0.06, "max_blobs": 50, "edge_speed": 1,
    "approach_width": 0.16,
}


def load_before(module: str):
    """BEFORE_REF's fx/effects/<module>.py as a SECOND registered effect
    named <module>_p3before (an Effect registers under its module's last name
    segment). None — a stated skip, never a silent pass — when git cannot
    produce the ref."""
    name = f"{module}_p3before"   # distinct from other checks' pinned copies
                                  # (one process may load several refs)
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{BEFORE_REF}:fx/effects/{module}.py"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                                  # noqa: BLE001
        print(f"  (skipped the before run of {module}: cannot read "
              f"{BEFORE_REF} — {exc})")
        return None
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return name


def _count(effect_type: str, eff) -> float:
    """What "more going on" counts: blobs on the Orbits strip (tracked —
    not the ones fading out), fireworks in flight (particle pairs) on the
    Fireworks strip, blobs on the Black Hole strip."""
    if effect_type.startswith("orbits1d"):
        return float(np.count_nonzero(eff.p_mode[:eff.n] < 2))
    if effect_type.startswith("fireworks1d"):
        return eff.n / 2.0
    return float(eff.n)


async def cycle(tmp: str, effect_type: str, config: dict, *,
                strength: float = 1.0, orphan: bool = False):
    """One normal/charge/lull/drop cycle (or, `orphan`, a charge and a lull
    whose drop never comes, run past the watchdog). Returns the frames, the
    palette, the count per frame and the life factor of every ordinary
    firework launched (Fireworks strip only: [(t, life / burst_life)])."""
    np.random.seed(7)
    host = await headless.start_headless_host(
        str(Path(tmp) / effect_type), device_id="strip", pixel_count=PX)
    virtual = host.virtuals.get("strip")
    frames, counts, lives = [], [], []
    i = [0]
    with headless.fake_clock() as clock:
        eff = headless.attach_effect(host, virtual, effect_type,
                                     dict(config, gradient=PALETTE))
        eff._rng = np.random.default_rng(11)
        if effect_type.startswith("fireworks1d"):
            orig = eff._spawn_firework

            def logged(*a, _o=orig, **kw):
                before = eff.n
                _o(*a, **kw)
                if eff.n > before and not kw.get("ignore_cap"):
                    lives.append((i[0] * DT, float(np.mean(
                        eff.f_life[before:eff.n])) / float(eff.burst_life)))

            eff._spawn_firework = logged

        def step(n=1):
            for _ in range(n):
                clock.advance(DT)
                i[0] += 1
                with eff.lock:
                    eff.audio_data_updated(_AudioFrame(i[0]))
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
                    frames.append(np.array(f, dtype=np.float64, copy=True))
                    counts.append(_count(effect_type, eff))

        def ramp(seconds, ramp_s):
            n = int(round(seconds * FPS))
            n_ramp = max(1, int(round(ramp_s * FPS)))
            for k in range(1, n + 1):
                if k <= n_ramp:
                    eff.update_config({"phase_progress": k / n_ramp})
                step()

        step(int(NORMAL_S * FPS))
        eff.update_config({"phase": "charge", "phase_progress": 0.0,
                           sp.STRENGTH_KEY: strength})
        ramp(CHARGE_S, 0.9 * CHARGE_S)
        eff.update_config({"phase": "lull", "phase_progress": 0.0,
                           sp.STRENGTH_KEY: strength,
                           **lull_dark.keys_for(LULL_S, 0.9 * LULL_S,
                                                MAX_DARK_S)})
        if orphan:
            # the drop never comes: past the watchdog's grace, then on
            ramp(0.9 * LULL_S + particle_handoff.PHASE_GRACE_S + 3.0,
                 0.9 * LULL_S)
        else:
            ramp(LULL_S, 0.9 * LULL_S)
            eff.update_config({"phase": "drop", "phase_progress": 0.0,
                               sp.STRENGTH_KEY: strength,
                               "drop_intensity": DROP_INTENSITY})
            ramp(DROP_S, DROP_RAMP_S)
        pal = palette_of(eff, PX)
        final_count = int(getattr(eff, "particle_count", 0) or 0)
    await host.shutdown()
    return frames, pal, counts, lives, final_count


def windows():
    c0 = int(NORMAL_S * FPS)
    l0 = c0 + int(CHARGE_S * FPS)
    d0 = l0 + int(LULL_S * FPS)
    return c0, l0, d0, d0 + int(DROP_S * FPS)


def measure(frames, pal, counts, lives, final_count):
    c0, l0, d0, end = windows()
    L = [lum(f) for f in frames]
    lull = frames[l0:d0]
    dark = [k for k, f in enumerate(lull) if f.max() == 0.0]
    span = lull[len(lull) - int(MAX_DARK_S * FPS) + 1:]
    wd = int(WHITE_DROP_S * FPS)
    late = [lf for t, lf in lives
            if (c0 + 0.75 * CHARGE_S * FPS) * DT <= t < l0 * DT]
    normal_life = [lf for t, lf in lives if t < c0 * DT]
    return {
        "normal": float(np.mean(L[:c0])),
        "charge_peak": max(L[c0:l0]),
        "charge_end": L[l0 - 1],
        "dark_s": len(dark) / FPS,
        "dark_from": dark[0] if dark else None,
        "dark_solid": bool(dark) and dark == list(range(dark[0], len(lull))),
        "dark_max": max(float(f.max()) for f in span),
        "drop_first": L[d0],
        "drop_peak": max(L[d0:d0 + wd]),
        "white_charge": max(whiter_than_set(frames[k], pal)
                            for k in range(c0, l0, 4)),
        "white_drop": max(whiter_than_set(frames[k], pal)
                          for k in range(d0, d0 + wd, 2)),
        "n_normal": float(np.mean(counts[:c0])),
        "n_charge_peak": max(counts[c0:l0]),
        "n_charge_end": counts[l0 - 1],
        "n_drop_peak": max(counts[d0:d0 + wd]),
        "n_end": counts[end - 1],
        "life_normal": float(np.mean(normal_life)) if normal_life else None,
        "life_charge_late": float(np.mean(late)) if late else None,
        "final_count": final_count,
    }


_failures: list[str] = []


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _failures.append(msg)


def _table(title, runs):
    cols = ("normal", "charge_peak", "charge_end", "dark_s", "drop_first",
            "drop_peak")
    print(f"\n{title} — brightness (mean perceived luminance)")
    print(f"{'':7}" + "".join(f"{c:>12}" for c in cols))
    for name, m in runs.items():
        print(f"{name:7}" + "".join(f"{m[c]:12.3f}" for c in cols))
    cols2 = ("white_charge", "white_drop", "n_normal", "n_charge_peak",
             "n_charge_end", "n_drop_peak", "n_end")
    print("whiter than the set (worst frame, pixels) / counts")
    print(f"{'':7}" + "".join(f"{c:>14}" for c in cols2))
    for name, m in runs.items():
        print(f"{name:7}" + "".join(f"{float(m[c]):14.1f}" for c in cols2))


def _both(tmp, module, config):
    runs, frames = {}, {}
    before = load_before(module)
    if before:
        out = asyncio.run(cycle(tmp, before, config))
        frames["before"] = out[0]
        runs["before"] = measure(*out)
    out = asyncio.run(cycle(tmp, module, config))
    frames["now"] = out[0]
    runs["now"] = measure(*out)
    return runs, frames


def _shared(now, label):
    """His rule, the parts both strips share."""
    check(now["charge_peak"] > 2.0 * now["normal"],
          f"{label}: the charge builds ({now['normal']:.3f} -> peak "
          f"{now['charge_peak']:.3f}) in the set's colours")
    check(now["white_charge"] == 0,
          f"{label}: no charge frame is whiter than the set")
    check(now["drop_first"] > 0.2 * now["drop_peak"],
          f"{label}: the drop is lit on its very first frame")
    check(now["drop_peak"] > now["charge_peak"],
          f"{label}: the drop out-shines the charge ({now['drop_peak']:.3f} > "
          f"{now['charge_peak']:.3f})")
    check(now["white_drop"] == 0,
          f"{label}: no drop frame is whiter than the set")


def _off_phase_identical(frames, label):
    if "before" not in frames:
        return
    c0 = windows()[0]
    check(all(np.array_equal(x, y) for x, y in
              zip(frames["before"][:c0], frames["now"][:c0])),
          f"{label}: off-phase the strip is byte-identical to before (all "
          f"{c0} normal frames, same seeds) — joining the layer changes "
          "nothing outside a phase")


def orbits(tmp):
    runs, frames = _both(tmp, "orbits1d", HIS_ORBITS)
    _table("ORBITS STRIP", runs)
    now = runs["now"]
    print("\nOrbits strip now — his rule")
    _shared(now, "orbits")
    check(now["n_charge_peak"] == ob1.CHARGE_PEAK_N
          and now["n_charge_end"] == ob1.CHARGE_PEAK_N,
          f"orbits: the charge swells to {ob1.CHARGE_PEAK_N} blobs and HOLDS "
          f"them to the drop (end of charge: {now['n_charge_end']:.0f})")
    want_from = int(round((LULL_S - MAX_DARK_S) * FPS)) - 1
    check(now["dark_solid"] and now["dark_from"] == want_from,
          f"orbits: the lull is black from the room's dark point (frame "
          f"{now['dark_from']} of the lull) to the drop")
    check(now["n_drop_peak"] == ob1.CHARGE_PEAK_N,
          f"orbits: the drop re-adds all {ob1.CHARGE_PEAK_N} blobs "
          f"(drop peak {now['n_drop_peak']:.0f})")
    check(now["n_end"] == HIS_ORBITS["particle_count"]
          and now["final_count"] == HIS_ORBITS["particle_count"],
          f"orbits: and sheds back to his own count "
          f"({HIS_ORBITS['particle_count']}) once the drop settles")
    _off_phase_identical(frames, "orbits")
    if "before" in runs:
        b = runs["before"]
        print("\nOrbits strip before — the defects this phase retires")
        check(b["n_charge_end"] <= 1,
              f"the old charge shed its build to one blob by its end "
              f"({b['n_charge_end']:.0f})")
        check(b["drop_peak"] < b["charge_peak"],
              f"…and its drop was below its charge ({b['drop_peak']:.3f} vs "
              f"{b['charge_peak']:.3f})")
        check(now["n_charge_peak"] > b["n_charge_peak"],
              f"more blobs now: charge peak {b['n_charge_peak']:.0f} -> "
              f"{now['n_charge_peak']:.0f}")


def fireworks(tmp):
    runs, frames = _both(tmp, "fireworks1d", HIS_FIREWORKS)
    _table("FIREWORKS STRIP", runs)
    now = runs["now"]
    ember = fw1.LULL_EMBER * 255.0
    print("\nFireworks strip now — his rule")
    _shared(now, "fireworks")
    check(now["n_charge_peak"] >= 8,
          f"fireworks: more fireworks on the charge past his density cap "
          f"({now['n_charge_peak']:.1f} in flight at its peak)")
    check(now["life_charge_late"] is not None
          and now["life_charge_late"] >= 0.9 * now["life_normal"],
          f"fireworks: the charge no longer shortens them (late-charge "
          f"life {now['life_charge_late']:.2f} x burst_life, normal "
          f"{now['life_normal']:.2f})")
    check(0.0 < now["dark_max"] <= ember + 1e-6,
          f"fireworks: through the lull's dark the rockets stay as faint "
          f"embers (brightest channel {now['dark_max']:.1f} of at most "
          f"{ember:.1f}, never black)")
    check(now["n_drop_peak"] > now["n_charge_peak"],
          f"fireworks: the drop's payoff and heavier shower out-number the "
          f"charge ({now['n_drop_peak']:.1f} in flight)")
    _off_phase_identical(frames, "fireworks")
    if "before" in runs:
        b = runs["before"]
        print("\nFireworks strip before — the defects this phase retires")
        check(b["n_charge_peak"] <= 3.0,
              f"the old charge was clipped by his density cap to 3 fireworks "
              f"in flight ({b['n_charge_peak']:.1f})")
        check(b["life_charge_late"] is not None
              and b["life_charge_late"] < 0.8 * b["life_normal"],
              f"…and made them shorter-lived ({b['life_charge_late']:.2f} vs "
              f"{b['life_normal']:.2f})")
        check(now["n_drop_peak"] > b["n_drop_peak"],
              f"a bigger drop now: {b['n_drop_peak']:.1f} -> "
              f"{now['n_drop_peak']:.1f} in flight")


def fold(tmp):
    print("\nTHE FOLD — the Black Hole strip at strength 0, before vs now")
    before = load_before("blackhole1d")
    if not before:
        return
    for orphan in (False, True):
        label = "an orphaned lull's watchdog release" if orphan else "a whole cycle"
        a = asyncio.run(cycle(tmp, before, HIS_BLACKHOLE, strength=0.0,
                              orphan=orphan))
        b = asyncio.run(cycle(tmp, "blackhole1d", HIS_BLACKHOLE, strength=0.0,
                              orphan=orphan))
        same = (len(a[0]) == len(b[0])
                and all(np.array_equal(x, y) for x, y in zip(a[0], b[0])))
        check(same, f"blackhole1d: byte-identical to before through {label} "
              f"({len(b[0])} frames) — the plumbing moved, the choreography "
              "did not")
    a = asyncio.run(cycle(tmp, before, HIS_BLACKHOLE))
    b = asyncio.run(cycle(tmp, "blackhole1d", HIS_BLACKHOLE))
    c0 = windows()[0]
    diff = [k for k, (x, y) in enumerate(zip(a[0], b[0]))
            if not np.array_equal(x, y)]
    worst = max((float(np.abs(a[0][k] - b[0][k]).max()) for k in diff),
                default=0.0)
    check(not diff or (diff[0] == c0 and diff[-1] < windows()[1]),
          f"at strength 1 the only change is from the charge's first frame "
          f"(its activity now applies there), dying out within the charge "
          f"({len(diff)} frames, largest step {worst:.2f} of 255)")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        orbits(tmp)
        fireworks(tmp)
        fold(tmp)
    print(f"\nconstants: Orbits swell {ob1.CHARGE_PEAK_N}; Fireworks charge "
          f"launches up to {fw1.CHARGE_LAUNCH_RATE_MAX:.0f}/s uncapped, "
          f"CHARGE_SLOW {fw1.CHARGE_SLOW}, CHARGE_SHORT {fw1.CHARGE_SHORT}, "
          f"drop shower {fw1.DROP_TAIL_RATE:.0f}/s, lull ember "
          f"{fw1.LULL_EMBER:.2f}")
    print("\n" + ("ALL CHECKS PASSED" if not _failures
                  else f"{len(_failures)} FAILED: " + "; ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
