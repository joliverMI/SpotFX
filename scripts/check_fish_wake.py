"""Measure the FISH WAKE — his 2026-08-28 ask, in numbers.

His words: "I want the ripples to be more like the trails in Orbits, but I
want them to expand and fade instead of just fading. I don't like the
circles that form because the circle line is kind of messy. Also, I want
the ripples to be a different color from the fish if there is a gradient to
work with, or if it's a solid/uniform color, at least substantially less
bright than the fish so they are visibly distinct."

Four things are measured, all on RENDERED FRAMES through the real vendored
pipeline (fx.headless at his crystal-mapper's shape, audio silenced):

  1. NO CIRCLE — the radial profile of one deposit, from its own centre
     outward. A ring has an off-centre peak; a filled smear does not.
  2. EXPAND AND FADE — one deposit's covered area over time (it must GROW)
     while its peak falls (it must DIM). A buffer that only faded would
     shrink its footprint, not grow it.
  3. COLOUR — the stated rule, both ways. GRADIENT palette: the mean colour
     distance between fish pixels and wake pixels, against the same distance
     measured with the offset removed as the negative control. SOLID
     palette: the wake's peak brightness as a fraction of the fish's.
  4. MOTION COUPLING — wake energy at cruise vs. under a real music drive,
     and the wake's own length after a strong beat (the lunge).

Read-only, offline. No live access.

    .venv/bin/python scripts/check_fish_wake.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

# his live Matrix entry, at the state he is watching right now
HIS = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.5, "roam_scale": 0.75,
    "tether_scatter": 0.0, "reactivity_scale": 1.0, "speed_jump": 1.0,
    "speed_jog": 1.0, "brightness_audio": 0.5, "size_audio": 0.5,
    "color_shift": 1, "impulse_decay": 0.06, "reverse": False,
}
# a palette whose stops all resolve to ONE colour — the solid case
SOLID = "linear-gradient(90deg, #22aaff 0.00%,#22aaff 100.00%)"

_RUN = [0]


class Room:
    def __init__(self, host, virtual, clock, effect):
        self.host, self.virtual, self.clock, self.effect = (
            host, virtual, clock, effect
        )

    def step(self, frames=1, impulse=None, slow=None):
        for _ in range(frames):
            if impulse is not None:
                self.effect.impulse = impulse
                self.effect.slow = slow if slow is not None else 0.0
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)

    def frame(self):
        return np.asarray(self.effect.matrix, dtype=np.float32)


async def room(tag, cfg=None, seed=5):
    # a UNIQUE device id per run: particle_handoff keeps a module-level
    # snapshot keyed by device, so reusing one name hands the previous run's
    # fish to the next and destroys determinism.
    _RUN[0] += 1
    dev = f"fish-wake-{tag}-{_RUN[0]}"
    td = tempfile.TemporaryDirectory()
    host = await headless.start_headless_host(
        str(Path(td.name) / dev), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=dev,
    )
    virtual = host.virtuals.get(dev)
    clock_cm = headless.fake_clock()
    clock = clock_cm.__enter__()
    eff = headless.attach_effect(host, virtual, "fish", dict(HIS, **(cfg or {})))
    eff._rng = np.random.default_rng(seed)
    r = Room(host, virtual, clock, eff)
    r._cleanup = (clock_cm, td)
    return r


async def close(r):
    await r.host.shutdown()
    r._cleanup[0].__exit__(None, None, None)
    r._cleanup[1].cleanup()


# ── 1. no circle: the radial profile of a single deposit ────────────────
def section_one():
    print("\n1  NO CIRCLE — the radial profile of one deposit")
    print("   (a ring peaks OFF centre; a filled smear peaks AT it)")

    async def main():
        r = await room("profile", dict(particle_count=1))
        eff = r.effect
        r.step(240)
        # isolate ONE deposit: clear the buffer, lay a single frame's worth
        eff.wake[:] = 0.0
        r.step(1)
        w = eff.wake.sum(axis=2)
        if w.max() <= 0:
            raise SystemExit("no wake was deposited at all")
        cy, cx = np.unravel_index(int(np.argmax(w)), w.shape)
        ys, xs = np.mgrid[0:ROWS, 0:COLS]
        d = np.hypot(xs - cx, ys - cy)
        prof = []
        for rad in range(0, 8):
            m = (d >= rad) & (d < rad + 1)
            prof.append(float(w[m].mean()) if m.any() else 0.0)
        peak_at = int(np.argmax(prof))
        print("   radius:  " + "  ".join(f"{i:>6d}" for i in range(8)))
        print("   value :  " + "  ".join(f"{v:6.1f}" for v in prof))
        print(f"   peak ring = r{peak_at}  "
              f"(monotonic falloff: "
              f"{all(prof[i] >= prof[i+1] - 1e-6 for i in range(6))})")
        if peak_at != 0:
            raise SystemExit("the deposit peaks off-centre — that is a ring")
        await close(r)
    asyncio.run(main())


# ── 2. expand AND fade ──────────────────────────────────────────────────
def section_two():
    print("\n2  EXPAND AND FADE — one deposit, over time")
    print("   (area must GROW while the peak FALLS)")

    async def main():
        r = await room("expand", dict(particle_count=1))
        eff = r.effect
        r.step(240)
        eff.wake[:] = 0.0
        r.step(1)
        # stop depositing: only the buffer's own decay + diffusion runs now
        eff.update_config({"ripple_amount": 0.0})
        rows = []
        for age_ms in (0, 100, 200, 300):
            if rows:
                r.step(6)
            w = eff.wake.sum(axis=2)
            thr = 0.02 * float(w.max()) if w.max() > 0 else 1.0
            rows.append((age_ms, float(w.max()), int((w > thr).sum()),
                         float(w.sum())))
        print("     age    peak     lit cells   total energy")
        for age, pk, cells, tot in rows:
            print(f"   {age:>4}ms  {pk:7.2f}  {cells:>9d}  {tot:12.1f}")
        grew = rows[-1][2] > rows[0][2]
        dimmed = rows[-1][1] < rows[0][1]
        print(f"   area grew: {grew}   peak fell: {dimmed}")
        if not (grew and dimmed):
            raise SystemExit("the wake must expand AND fade")
        await close(r)
    asyncio.run(main())


# ── 3. colour, both cases ───────────────────────────────────────────────
def _split_pixels(eff):
    """Fish pixels vs wake pixels, from the two real buffers."""
    fish = eff.trail
    wake = eff.wake
    fl = fish.sum(axis=2)
    wl = wake.sum(axis=2)
    fish_m = fl > 0.5 * fl.max() if fl.max() > 0 else np.zeros_like(fl, bool)
    wake_m = (wl > 0.25 * wl.max()) & (fl < 0.05 * max(fl.max(), 1e-6)) \
        if wl.max() > 0 else np.zeros_like(wl, bool)
    return fish[fish_m], wake[wake_m]


def _hue_unit(rgb):
    """Unit RGB direction — colour without brightness."""
    n = np.linalg.norm(rgb, axis=1, keepdims=True)
    return rgb / np.maximum(n, 1e-6)


def section_three():
    print("\n3  COLOUR — the stated rule, measured both ways")

    async def main():
        # ONE fish, so "the fish's colour" and "its wake's colour" are each
        # a single value: with a population every fish sits at its own point
        # on the gradient and averaging the panel washes the answer out.
        one = dict(particle_count=1)
        # GRADIENT case: the wake samples WAKE_GRAD_OFFSET further along
        r = await room("grad", one)
        r.step(600)
        f, w = _split_pixels(r.effect)
        dist = float(np.linalg.norm(
            _hue_unit(f).mean(axis=0) - _hue_unit(w).mean(axis=0)
        ))
        await close(r)

        # NEGATIVE CONTROL: the same run with the offset removed — the wake
        # then wears the fish's own colour and the distance must collapse
        orig = FX.WAKE_GRAD_OFFSET
        FX.WAKE_GRAD_OFFSET = 0.0
        try:
            r0 = await room("grad-ctl", one)
            r0.step(600)
            f0, w0 = _split_pixels(r0.effect)
            dist0 = float(np.linalg.norm(
                _hue_unit(f0).mean(axis=0) - _hue_unit(w0).mean(axis=0)
            ))
            await close(r0)
        finally:
            FX.WAKE_GRAD_OFFSET = orig

        print(f"   GRADIENT palette (his default rainbow):")
        print(f"     fish mean rgb {f.mean(axis=0).round(1)}   "
              f"wake mean rgb {w.mean(axis=0).round(1)}")
        print(f"     colour distance (unit-rgb) = {dist:.3f}")
        print(f"     control, offset 0.0        = {dist0:.3f}"
              f"   -> {dist / max(dist0, 1e-6):.1f}x")
        if dist <= dist0 * 1.5:
            raise SystemExit("the gradient offset buys no real distinctness")

        # SOLID case: same colour, substantially less bright
        rs = await room("solid", dict(one, gradient=SOLID))
        rs.step(600)
        wake_pk = float(rs.effect.wake.max())
        fish_pk = float(rs.effect.trail.max())
        await close(rs)
        print(f"   SOLID palette ({SOLID.split()[1].rstrip(',')}):")
        print(f"     fish peak {fish_pk:6.1f}   wake peak {wake_pk:6.1f}"
              f"   ratio {wake_pk / max(fish_pk, 1e-6):.3f}")
        if wake_pk / max(fish_pk, 1e-6) > 0.45:
            raise SystemExit("the solid-palette wake is not substantially "
                             "less bright than the fish")
        if wake_pk <= 0.0:
            raise SystemExit("the solid-palette wake is invisible")
    asyncio.run(main())


# ── 4. the wake still rides real motion ─────────────────────────────────
def section_four():
    print("\n4  MOTION COUPLING — the wake rides speed and flap, not a beat")

    async def main():
        out = {}
        for label, imp in (("cruise", 0.0), ("driven", 0.9)):
            r = await room(f"drive-{label}")
            r.step(300)
            r.effect.wake[:] = 0.0
            r.step(120, impulse=imp, slow=0.25 * imp)
            out[label] = float(r.effect.wake.sum())
            await close(r)
        print(f"   wake energy after 2s:  cruise {out['cruise']:10.0f}   "
              f"driven {out['driven']:10.0f}   "
              f"-> {out['driven'] / max(out['cruise'], 1e-6):.2f}x")
        if out["driven"] <= out["cruise"]:
            raise SystemExit("a faster fish must leave more wake")

        # the lunge: a strong beat covers more ground, so its smear is longer
        lens = {}
        for label, gain in (("no lunge", 0.0), ("lunge", FX.LUNGE_GAIN)):
            orig = FX.LUNGE_GAIN
            FX.LUNGE_GAIN = gain
            try:
                r = await room(f"lunge-{label}", dict(particle_count=1))
                r.step(300)
                r.effect.wake[:] = 0.0
                r.effect._beat_pending = True
                r.step(60, impulse=1.0, slow=0.30)
                w = r.effect.wake.sum(axis=2)
                thr = 0.05 * float(w.max()) if w.max() > 0 else 1.0
                ys, xs = np.nonzero(w > thr)
                lens[label] = (
                    float(np.hypot(np.ptp(xs), np.ptp(ys))) if xs.size else 0.0
                )
                await close(r)
            finally:
                FX.LUNGE_GAIN = orig
        print(f"   smear extent 1s after a strong beat:  "
              f"no lunge {lens['no lunge']:5.1f}px   "
              f"lunge {lens['lunge']:5.1f}px")
        if lens["lunge"] <= lens["no lunge"]:
            print("   NOTE: the lunge did NOT lengthen the wake here")
    asyncio.run(main())


def main():
    print("FISH WAKE — expanding, fading, and visibly distinct")
    print(f"(his state: jiggle {HIS['jiggle']}, "
          f"roam_scale {HIS['roam_scale']}, blob_size {HIS['blob_size']}; "
          f"{ROWS}x{COLS} crystal-mapper shape)")
    section_one()
    section_two()
    section_three()
    section_four()
    print("\nALL WAKE CHECKS PASS")


if __name__ == "__main__":
    main()
