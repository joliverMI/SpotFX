"""Measured proof: FISH NEVER FADE OUT — they disperse off the screen — and
the swim-burst flare fires on the trigger and lasts 300 ms.

HIS WORDS (2026-09-16, the Admiral's card fish-effect-disperse-off-screen-
instead--wyxr): "the fish just fade out in the lull before the drop or
during some transitions ... when there isnt a blob, have them disperse to
black, rather than fade ... when we reach the lull, have them go from their
ordered school to a chaotic swirl, and as they swirl, have them leak out and
off the screen so that by half way through the lull, they are all gone ...
add a flare at all levels that can run instead of other shape flares that
makes the fish swim fast for a burst, and have a dramatic change in the
frequency of their fin strokes. time it so that the burst starts 100ms
before the trigger and lasts 300ms total". He then corrected the timing
himself — "no, dont pull the band forward, just dont add the 100ms
pre-fire" — so the burst ships with NO pre-fire: 300 ms starting ON the
trigger (section 5).

Everything here runs on the REAL vendored render pipeline (fx.headless, his
crystal-mapper's 72x37 shape, audio silenced) or on SPECTRA's real flare
machinery (flare_preview.build_timeline over scene_response). Every section
that claims a behaviour CHANGED also runs the PRE-CHANGE module, read out of
git at BASELINE_REF and registered beside the current one, and requires it
to FAIL the same bar — an instrument that cannot go red on the defect it was
written for proves nothing.

With the audio silenced every fish's brightness is one constant, so "never
fades" is measured as: while a fish is on the panel, its brightness never
drops below that constant. Section 2 (the additive crossfade) is measured on
RENDERED PIXELS instead, because the virtual's own blend sits between the
effect and the light — and it reports the one limit that blend imposes.

    .venv/bin/python scripts/check_fish_disperse.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

# the commit this change was built on: the pre-change fish, for the red
# controls. Pinned, never a moving ref (scripts/check_fish_camera.py records
# what a moving reference silently does to an instrument).
BASELINE_REF = "4795fd3a69391e0577bdfc8a2bc8e597e4fd1910"
DT = 1.0 / 60.0
ROWS, COLS = 37, 72

HIS = {
    "particle_count": 6, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.15, "tether_scatter": 0.0,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "reverse": False, "camera_follow": 0.8,
}

FAILURES: list[str] = []


def check(cond, label):
    print(f"   {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILURES.append(label)


# ── harness ─────────────────────────────────────────────────────────────
class Room:
    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm

    def step(self, frames=1, watch=None):
        for _ in range(frames):
            self.clock.advance(DT)
            f = self.virtual.assemble_frame()
            if f is not None:
                self.virtual.flush(f)
            if watch is not None:
                watch()

    def ramp(self, phase, seconds, beats_every=None, watch=None, hang=0.0):
        eff = self.effect
        eff.update_config({"phase": phase, "phase_progress": 0.0})
        frames = max(int(seconds / DT), 1)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if beats_every and i % beats_every == 0:
                eff._beat_pending = True
            self.step(1, watch)
        self.step(int(hang / DT), watch)


async def room(tag, effect_type, config=None, seed=5):
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, effect_type,
                                 dict(config or HIS))
    eff._rng = np.random.default_rng(seed)
    return Room(host, virtual, clock, eff, cm)


async def close(r):
    r._cm.__exit__(None, None, None)
    await r.host.shutdown()


def load_baseline(ref=BASELINE_REF, name="fish_predisperse"):
    if name in sys.modules:
        return name
    src = subprocess.run(
        ["git", "show", f"{ref}:fx/effects/fish.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


def screen(eff):
    n = eff.n
    px = eff.cx + eff.p_x[:n] * eff.sx - eff.cam_px
    py = eff.cy + eff.p_y[:n] * eff.sy - eff.cam_py
    return px, py


def on_panel(eff):
    """Indices of fish ANY part of whose body can still be on the panel —
    the generous test, so "gone" means genuinely gone."""
    px, py = screen(eff)
    m = eff._body_len_px()
    inside = (
        (px >= -m) & (px <= eff.r_width - 1 + m)
        & (py >= -m) & (py <= eff.r_height - 1 + m)
    )
    return np.flatnonzero(inside)


# ── 1. the lull ─────────────────────────────────────────────────────────
async def lull_run(effect_type, gap_s, seed):
    r = await room(f"lull{seed}{effect_type[-3:]}", effect_type, seed=seed)
    eff = r.effect
    r.step(240)
    r.ramp("charge", 4.0, beats_every=12)
    rec = {"f": [], "vis": [], "minb": [], "tang": [], "order": []}
    B = float(np.max(eff.p_bright[: eff.n]))
    # the charge's own ordering, as a heading coherence (1 = all one way)
    live = on_panel(eff)
    rec["charge_order"] = float(np.abs(np.exp(1j * eff.p_hd[live]).mean()))

    def watch():
        vis = on_panel(eff)
        rec["f"].append(eff.phase_progress)
        rec["vis"].append(vis.size)
        rec["minb"].append(
            float(eff.p_bright[vis].min()) / B if vis.size else 1.0
        )
        if vis.size >= 2:
            px, py = screen(eff)
            rx, ry = px[vis] - eff.cx, py[vis] - eff.cy
            rr = np.maximum(np.hypot(rx, ry), 1e-3)
            hx, hy = np.cos(eff.p_hd[vis]), np.sin(eff.p_hd[vis])
            rec["tang"].append(float(np.mean((rx * hy - ry * hx) / rr)))
            rec["order"].append(
                float(np.abs(np.exp(1j * eff.p_hd[vis]).mean()))
            )
        else:
            rec["tang"].append(np.nan)
            rec["order"].append(np.nan)

    ramp_s = 0.9 * gap_s
    r.ramp("lull", ramp_s, watch=watch, hang=0.1 * gap_s)
    rec["B"] = B
    await close(r)
    return {k: (np.array(v) if isinstance(v, list) else v)
            for k, v in rec.items()}


def section_lull(base):
    print("\n1. THE LULL — school -> chaotic swirl -> leak off screen, "
          "never a fade, all gone by the third")
    third = FX.LULL_GONE_AT
    for gap in (0.9, 2.5, 6.04):
        for seed in (3, 11):
            rec = asyncio.run(lull_run("fish", gap, seed))
            f, vis, minb = rec["f"], rec["vis"], rec["minb"]
            before = f < third
            last_before = int(vis[before][-1]) if before.any() else -1
            # the swirl, read in the last stretch before the first leak (it
            # takes real time to form from a school)
            swirl = (f > third * FX.LULL_LEAK_FROM * 0.6) & (
                f < third * FX.LULL_LEAK_FROM)
            tang = np.nanmean(rec["tang"][swirl]) if swirl.any() else np.nan
            order = np.nanmean(rec["order"][swirl]) if swirl.any() else np.nan
            print(f"   gap {gap:>4}s seed {seed:>2}: start {int(vis[0])} fish  "
                  f"on panel at the third's last frame {last_before}  "
                  f"min brightness while on panel {minb.min():.3f}  "
                  f"swirl tangential {tang:+.2f}  heading order "
                  f"{rec['charge_order']:.2f} -> {order:.2f}")
            check(vis[0] > 0, f"gap {gap}s seed {seed}: the lull starts "
                  "with fish in it")
            check(minb.min() >= 0.99, f"gap {gap}s seed {seed}: no fish "
                  "dims while it is on the panel")
            check(last_before == 0, f"gap {gap}s seed {seed}: every fish is "
                  "OFF the panel before the third's backstop runs")
            check(int(vis[f >= third].max(initial=0)) == 0,
                  f"gap {gap}s seed {seed}: none after the third")
            # the swirl needs real time to wheel a school round (every turn
            # is bounded by the turn radius): asserted on his long lull, and
            # printed for the shorter ones, where it is honestly partial
            if gap >= 6.0:
                check(abs(tang) >= 0.5, f"gap {gap}s seed {seed}: the "
                      "school breaks into a SWIRL (mean |tangential| >= 0.5)")
            if gap >= 2.5:
                check(order < rec["charge_order"], f"gap {gap}s seed {seed}: "
                      "the swirl is less ordered than the charge's school")
    if base:
        rec = asyncio.run(lull_run(base, 2.5, 11))
        print(f"   RED CONTROL (pre-change {BASELINE_REF[:10]}): min "
              f"brightness while on panel {rec['minb'].min():.3f}")
        check(rec["minb"].min() < 0.5, "red control: the pre-change lull "
              "DOES fade fish out on the panel (the instrument can see it)")


# ── 2. the outgoing crossfade ───────────────────────────────────────────
def body_on_panel(eff):
    """Indices of fish any part of whose DRAWN body can reach a panel pixel:
    the spine's half length from its centre, the widest splat's radius, and
    this frame's own smear back along its travel."""
    px, py = screen(eff)
    reach = (
        0.5 * eff._body_len_px() + eff._half_width_px()
        + np.abs(eff.p_spd[: eff.n]) * DT + 1.0
    )
    inside = (
        (px >= -reach) & (px <= eff.r_width - 1 + reach)
        & (py >= -reach) & (py <= eff.r_height - 1 + reach)
    )
    return np.flatnonzero(inside)


def body_peaks(frame, eff):
    """Each on-panel fish's RENDERED body peak: the brightest channel in the
    3x3 of rendered pixels at its screen position (only fish whose centre
    is on the panel — a centre past the edge has no window to read)."""
    img = np.asarray(frame, dtype=np.float32).reshape(ROWS, COLS, 3).max(axis=2)
    px, py = screen(eff)
    out = []
    for x, y in zip(px, py):
        xi, yi = int(round(float(x))), int(round(float(y)))
        if 0 <= xi < COLS and 0 <= yi < ROWS:
            out.append(float(
                img[max(yi - 1, 0):yi + 2, max(xi - 1, 0):xi + 2].max()
            ))
    return out


async def crossfade_run(effect_type, seed, seconds=0.5):
    """Crossfade Fish into a black singleColor — an incoming effect with no
    blobs to merge into, so the fish must disperse — at his crystal-mapper's
    Add 0.5 s, and read the RENDERED frame the blend produces."""
    r = await room(f"xf{seed}{effect_type[-3:]}", effect_type, seed=seed)
    fish = r.effect
    v = r.virtual
    r.step(240)
    ref = []
    for _ in range(60):
        r.clock.advance(DT)
        f = v.assemble_frame()
        v.flush(f)
        ref.extend(body_peaks(f, fish))
    reference = float(np.median(ref))
    headless.attach_effect(r.host, v, "singleColor",
                           {"color": "#000000", "brightness": 0.0})
    v._transition_effect = fish
    v._config["transition_mode"] = "Add"
    v.frame_transitions = v.transitions["Add"]
    v.transition_frame_total = int(round(v.refresh_rate * seconds))
    v.transition_frame_counter = 0
    rows = []
    while v._transition_effect is fish:
        r.clock.advance(DT)
        f = v.assemble_frame()
        v.flush(f)
        w = v.transition_frame_counter / max(v.transition_frame_total, 1)
        peaks = body_peaks(f, fish)
        rows.append((
            w, body_on_panel(fish).size,
            float(np.median(peaks)) / reference if peaks else None,
            min(peaks) / reference if peaks else None,
        ))
    await close(r)
    return reference, rows


def section_crossfade(base):
    print("\n2. THE OUTGOING CROSSFADE into an effect with no blobs (his "
          "crystal-mapper: Add, 0.5 s), RENDERED PIXELS — fish swim off; the "
          "blend's own clip still dims their cores (a named limit)")
    for seed in (3, 5, 11, 17):
        reference, rows = asyncio.run(crossfade_run("fish", seed))
        start = rows[0][1]
        gone_w = next((w for w, n, _m, _l in rows if n == 0), None)
        print(f"   seed {seed:>2}: {start} fish at the switch, reference "
              f"body peak {reference:.0f}")
        for w, n, med, low in rows:
            if n == 0 and w > (gone_w or 0.0):
                break
            print(f"      weight {w:.3f}: {n} fish on the panel, on-panel "
                  "body peak / reference "
                  + (f"median {med:.2f} min {low:.2f}" if med is not None
                     else "(no centre on the panel)"))
        print(f"      every fish body off the panel by weight {gone_w}")
        early = [med for w, _n, med, _l in rows
                 if w <= 0.2 and med is not None]
        check(start > 0, f"seed {seed}: fish on the panel at the switch")
        check(gone_w is not None and gone_w <= FX.TRANSITION_EXIT_BY,
              f"seed {seed}: every fish off the panel by "
              f"{FX.TRANSITION_EXIT_BY:.0%} of the crossfade, well before "
              "it ends")
        # Bar RE-MEASURED 2026-09-16 (the trail-gain hotfix, same night):
        # this reading used to include the residual brightness of the very
        # defect that hotfix removed — the persistent trail was ALSO
        # carrying the gained value from earlier frames, so a fish reading
        # here could still be lit by its own over-bright, slow-to-decay
        # smear a few frames after the instant that produced it, not by
        # this frame's compensation alone. With the trail fed the fish's
        # TRUE brightness (see fx/effects/fish.py's own render-block
        # comment), this number is now the compensation's honest floor,
        # not the memory's.
        # 0.65 sits under the worst of four seeds measured post-fix (0.73)
        # with margin, comfortably above the RED CONTROL below (0.13) —
        # never touched TRANSITION_GAIN_FLOOR or the wake half-life to get
        # here, per the standing order not to mask this reading by tuning
        # either.
        check(bool(early) and min(early) >= 0.65,
              f"seed {seed}: the median on-panel body peak stays >= 0.65 of "
              "its pre-switch value through weight 0.2")
    if base:
        reference, rows = asyncio.run(crossfade_run(base, 11))
        late = [(w, n, med) for w, n, med, _l in rows if w >= 0.85]
        on_late = max((n for _w, n, _m in late), default=0)
        dim = max((m for _w, n, m in late if n and m is not None),
                  default=0.0)
        print(f"   RED CONTROL: at weight >= 0.85, {on_late} fish still on "
              f"the panel, brightest median body peak {dim:.2f} of reference")
        check(on_late > 0 and dim < 0.2, "red control: the pre-change fish "
              "sit on the panel and DIM away under the blend")


# ── 2b. the colour of a scattering fish ─────────────────────────────────
# A fish has to reach the 255 ceiling for any clip to act, so the colour is a
# saturated non-primary orange like his real palettes' (#ff7800-style): an
# #c86432 body at his blob size never reaches it and would pass under either
# clip. Only fish with no other fish near them are read — two bodies summing
# on one pixel saturate in ORDINARY swimming too, which this change leaves
# exactly as it was.
HUE_GRADIENT = "#ff8040"
HUE_TOLERANCE = 0.04


def body_chroma(frame, eff):
    """Chromaticity (every channel over the brightest) of the brightest
    RENDERED pixel at each lone fish: a 3x3 at a centre on the panel, or a
    half-body window at the nearest edge for one whose centre has left but
    whose body can still reach it."""
    img = np.asarray(frame, dtype=np.float32).reshape(ROWS, COLS, 3)
    px, py = screen(eff)
    apart = 2.0 * eff._body_len_px() + 2.0 * eff._half_width_px()
    reach = int(np.ceil(0.5 * eff._body_len_px()))
    out = []
    for k, (x, y) in enumerate(zip(px, py)):
        gaps = np.hypot(px - x, py - y)
        gaps[k] = np.inf
        if gaps.size and gaps.min() < apart:
            continue
        xi, yi = int(round(float(x))), int(round(float(y)))
        cx, cy = min(max(xi, 0), COLS - 1), min(max(yi, 0), ROWS - 1)
        inside = (cx, cy) == (xi, yi)
        if not inside and max(abs(xi - cx), abs(yi - cy)) > reach:
            continue
        r = 1 if inside else reach
        win = img[max(cy - r, 0):cy + r + 1,
                  max(cx - r, 0):cx + r + 1].reshape(-1, 3)
        pix = win[int(np.argmax(win.max(axis=1)))]
        if pix.max() >= 24.0:
            out.append(pix / pix.max())
    return out


async def hue_run(seed, per_channel_clip, seconds=0.5):
    """The worst departure of a lone fish's rendered colour from its own
    pre-switch colour, through his Add 0.5 s crossfade into black.
    `per_channel_clip` puts back the clip this change replaced (each channel
    clipped on its own) — the red control."""
    r = await room(f"hue{seed}{int(per_channel_clip)}", "fish",
                   dict(HIS, gradient=HUE_GRADIENT), seed=seed)
    fish = r.effect
    v = r.virtual
    if per_channel_clip:
        fish._clip_body_layer = lambda frame: np.minimum(frame, 255.0)
    r.step(240)
    ref = []
    for _ in range(60):
        r.clock.advance(DT)
        f = v.assemble_frame()
        v.flush(f)
        ref.extend(body_chroma(f, fish))
    ref = np.median(np.array(ref), axis=0) if ref else None
    headless.attach_effect(r.host, v, "singleColor",
                           {"color": "#000000", "brightness": 0.0})
    v._transition_effect = fish
    v._config["transition_mode"] = "Add"
    v.frame_transitions = v.transitions["Add"]
    v.transition_frame_total = int(round(v.refresh_rate * seconds))
    v.transition_frame_counter = 0
    worst, samples = 0.0, 0
    while v._transition_effect is fish:
        r.clock.advance(DT)
        f = v.assemble_frame()
        v.flush(f)
        if ref is None:
            continue
        for c in body_chroma(f, fish):
            worst = max(worst, float(np.max(np.abs(c - ref))))
            samples += 1
    await close(r)
    return ref, worst, samples


def section_crossfade_hue():
    print("\n2b. THE COLOUR OF A SCATTERING FISH (Add 0.5 s into black, "
          f"{HUE_GRADIENT}) — a gained body keeps its hue at the rendered "
          "pixel; clipping each channel on its own washes it toward "
          "yellow-white")
    for seed in (3, 5, 11):
        ref, worst, samples = asyncio.run(hue_run(seed, False))
        _ref, red, red_samples = asyncio.run(hue_run(seed, True))
        chroma = "none" if ref is None else "/".join(f"{c:.3f}" for c in ref)
        print(f"   seed {seed:>2}: pre-switch chromaticity {chroma}, worst "
              f"departure through the crossfade {worst:.3f} over {samples} "
              f"readings; RED CONTROL (per-channel clip) {red:.3f} over "
              f"{red_samples}")
        print(f"   HUE seed={seed} hue_clip_worst={worst:.4f} "
              f"per_channel_worst={red:.4f} tolerance={HUE_TOLERANCE}")
        check(ref is not None and samples > 0 and red_samples > 0,
              f"seed {seed}: lone fish were read before and during the "
              "crossfade")
        check(worst <= HUE_TOLERANCE, f"seed {seed}: a scattering fish's "
              f"rendered colour stays within {HUE_TOLERANCE} of its own")
        check(red > HUE_TOLERANCE, f"seed {seed}: red control — the "
              "per-channel clip FAILS the same bar (the wash is visible)")


# ── 3. an ordinary population trim ──────────────────────────────────────
async def trim_run(effect_type, seed):
    r = await room(f"trim{seed}{effect_type[-3:]}", effect_type,
                   dict(HIS, particle_count=8), seed=seed)
    eff = r.effect
    r.step(400)
    B = float(np.max(eff.p_bright[: eff.n]))
    eff.update_config({"particle_count": 2})
    t0 = eff.t
    out = {"minb": 1.0, "gone_at": None}
    for _ in range(int(3.0 / DT)):
        r.step(1)
        n = eff.n
        leaving = np.flatnonzero(eff.p_mode[:n] >= 2)
        vis = np.intersect1d(leaving, on_panel(eff))
        if vis.size:
            out["minb"] = min(out["minb"],
                              float(eff.p_bright[vis].min()) / B)
        elif out["gone_at"] is None:
            out["gone_at"] = eff.t - t0
    await close(r)
    return out


def section_trim(base):
    print("\n3. AN ORDINARY TRIM (particle_count 8 -> 2) — the departing "
          "fish swim out inside the old 1.2 s horizon, at full brightness")
    for seed in (3, 11):
        out = asyncio.run(trim_run("fish", seed))
        print(f"   seed {seed:>2}: departing fish off the panel after "
              f"{out['gone_at']:.2f}s, min brightness {out['minb']:.3f}")
        check(out["gone_at"] is not None
              and out["gone_at"] <= FX.DEPART_S + 0.15,
              f"seed {seed}: gone within DEPART_S")
        check(out["minb"] >= 0.99, f"seed {seed}: never dimmed")
    if base:
        out = asyncio.run(trim_run(base, 11))
        print(f"   RED CONTROL: min brightness {out['minb']:.3f}")
        check(out["minb"] < 0.5, "red control: the pre-change trim fades")


# ── 4. the swim burst, at the effect ────────────────────────────────────
async def burst_run(hold_s=0.3):
    r = await room("burst", "fish", dict(HIS, particle_count=6), seed=7)
    eff = r.effect
    r.step(400)
    rows = []

    def sample():
        n = eff.n
        sw = np.flatnonzero(eff.p_mode[:n] == 0)
        rows.append((eff.t, float(eff.p_spd[sw].mean()),
                     eff.p_flap[sw].astype(np.float64).copy(), sw.copy()))

    r.step(int(0.5 / DT), sample)
    t_on = eff.t
    eff.update_config({"swim_burst": True})
    r.step(int(round(hold_s / DT)), sample)
    t_off = eff.t
    eff.update_config({"swim_burst": False})
    r.step(int(0.8 / DT), sample)
    await close(r)
    return rows, t_on, t_off


def _window(rows, lo, hi):
    sel = [x for x in rows if lo <= x[0] <= hi]
    speed = float(np.mean([s for _t, s, _f, _i in sel]))
    # flap phase rate, from consecutive samples over the same fish
    rates = []
    for (t0, _s0, f0, i0), (t1, _s1, f1, i1) in zip(sel, sel[1:]):
        if i0.size == i1.size and np.array_equal(i0, i1) and t1 > t0:
            d = (f1 - f0) % (2 * np.pi * 64)
            rates.append(float(np.mean(d)) / (t1 - t0) / (2 * np.pi))
    return speed, float(np.mean(rates)) if rates else float("nan")


def section_burst():
    print("\n4. THE SWIM BURST at the effect — fast dash, dramatic fin-stroke "
          "change, over when the flare lets go")
    rows, t_on, t_off = asyncio.run(burst_run())
    sp0, fl0 = _window(rows, t_on - 0.45, t_on - 0.02)
    sp1, fl1 = _window(rows, t_on + 0.1, t_off)
    sp2, fl2 = _window(rows, t_off + 0.25, t_off + 0.7)
    print(f"   before: {sp0:6.1f} px/s  {fl0:5.2f} strokes/s")
    print(f"   burst : {sp1:6.1f} px/s  {fl1:5.2f} strokes/s  "
          f"(x{sp1 / sp0:.2f} speed, x{fl1 / fl0:.2f} strokes)")
    print(f"   after : {sp2:6.1f} px/s  {fl2:5.2f} strokes/s")
    check(sp1 >= 2.0 * sp0, "the burst at least doubles the swim speed")
    check(fl1 >= 3.0 * fl0, "the fin-stroke frequency at least triples")
    check(sp2 <= 1.25 * sp0, "speed is back near cruise within 250 ms of "
          "the flare letting go (the dash ends with the hold)")


# ── 5. the flare, on SPECTRA's real machinery ───────────────────────────
def section_flare():
    print("\n5. THE FLARE — momentary swim_burst, hold 300 ms, offset "
          "0 ms (on the trigger), on scene_response + flare_preview")
    td = Path(tempfile.mkdtemp(prefix="fish-burst-flare-"))
    from fx import device_model
    device_model.CATEGORIES_FILE = td / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    from spectra import config as scfg
    scfg.SPECTRA_STORAGE = td / "spectra"
    for attr, fname in (
        ("SCENES_FILE", "scenes.json"), ("SEQUENCER_FILE", "sequencer.json"),
        ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
        ("ROOM_COLOR_FILE", "room_color.json"),
        ("ROOM_CONTROLS_FILE", "room_controls.json"),
        ("GRADIENT2D_FILE", "gradients2d.json"),
        ("FIRE_HISTORY_FILE", "fire_history.json"),
        ("SHOW_LOG_FILE", "show_log.json"),
    ):
        setattr(scfg, attr, scfg.SPECTRA_STORAGE / fname)
    scfg.COLOR_SETS_FILE = td / "color_sets.json"

    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig,
                                      SceneV2)
    from spectra.services import flare_preview, scene_response

    sys.path.insert(0, str(REPO / "scripts"))
    import add_fish_swim_burst_flare as mig   # the kind the migration writes
    kind = FlareKind(**mig.NEW_KIND)
    patch = FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                      hold_ms=500,
                      params={"reverse": ParamTarget(mode="absolute",
                                                     value=1.0)})
    scene = SceneV2(
        name="Fish burst check",
        devices=[SceneDeviceConfig(id="m", target_kind="virtual",
                                   target="crystal-mapper",
                                   effect_type="fish", params={})],
        flare_kinds=[kind, patch],
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0,
            kinds={kind.name: 1.0, patch.name: 1.0},
            kind_lanes={kind.name: mig.LANE_NAME, patch.name: mig.LANE_NAME},
        )])},
    )
    tl = asyncio.run(flare_preview.build_timeline(scene, kind, 0.8))
    writes = sorted(tl["writes"], key=lambda w: w["at_s"])
    for w in writes:
        print(f"   write at {w['at_s']:.3f}s {w['kind']:<5} {w['params']} "
              f"({w['duration_ms']} ms)")
    print(f"   lead {tl['lead_ms']} ms, trigger mark {tl['trigger_mark_s']}s, "
          f"fire at {tl['fire_at_s']}s")
    check(len(writes) == 2, "one spike write and one release write")
    if len(writes) == 2:
        on, off = writes
        check(on["params"].get("swim_burst") is True and on["at_s"] == 0.0,
              "the spike lands swim_burst=True, as a real bool")
        check(off["params"].get("swim_burst") is False
              and abs(off["at_s"] - 0.300) < 1e-6,
              "the release lands swim_burst=False exactly 300 ms later")
        check(on["duration_ms"] <= scene_response.DICE_REROLL_GLIDE_MS
              and on["kind"] == "jump" and off["kind"] == "jump",
              "both edges are instant jumps (a toggle never glides)")
    check(kind.trigger_offset_ms == 0 and kind.hold_ms == 300,
          "the migration's kind is authored hold 300 ms, offset 0 ms")
    check(tl["lead_ms"] == 0, "no automatic lead (nothing glides)")
    check(abs(tl["trigger_mark_s"] - tl["fire_at_s"]) < 1e-6,
          "the burst STARTS on the trigger mark — no pre-fire")
    off_ms = scene_response.band_trigger_offset_ms(scene, "flare", 0.8)
    print(f"   band_trigger_offset_ms for the band it is pooled into: {off_ms}")
    check(off_ms == 0, "the firing path leaves that band on its trigger mark")


def main():
    base = None
    try:
        base = load_baseline()
    except Exception as exc:                       # noqa: BLE001
        print(f"(red controls SKIPPED: cannot read {BASELINE_REF}: {exc})")
    section_lull(base)
    section_crossfade(base)
    section_crossfade_hue()
    section_trim(base)
    section_burst()
    section_flare()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        status = main()
    except BaseException:                          # noqa: BLE001
        import traceback
        traceback.print_exc()
        status = 2
    sys.stdout.flush()
    # fx's TemporalEffect threads are never joined by the frame-stepped
    # harness (AGENTS.md): a plain return would hang the interpreter
    os._exit(status)
