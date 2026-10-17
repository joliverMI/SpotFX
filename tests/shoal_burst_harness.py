"""THE SHOAL-BURST RIG — the shoaling family measured on the real vendored
pipeline (the shoal-burst plan, /home/javi/fleet-spotfx/data/
shoal-burst-plan/report.md §4/§7; fx/effects/transition_cloud.py's
HostFormer is the binding statement for what it measures).

`fx.headless`, a 72x37 dummy matrix, silent audio, a fake clock at 60 fps:
every frame it records each cloud piece's (x, y, vx, vy) straight off the
program's own arrays, where each piece's HOST is, and — from a CONTROL run
with the identical seed in which the switch never happens — what the
outgoing object itself would have done. The control is the ground truth for
"what the parent was doing"; nothing here asks the release what it published
about itself.

TWO DETERMINISM TRAPS, both recorded in the plan and both fixed here rather
than worked around:

  1. every particle effect builds `np.random.default_rng()` UNSEEDED at
     construction, so two runs of the same thing differ;
  2. `particle_handoff._store` is module-level, keyed by virtual id, and its
     staleness check is REAL wall-clock — so a snapshot left by the PREVIOUS
     run is adopted by the next run's first effect.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import particle_handoff as ph  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402
from fx.host import FxHost  # noqa: E402

PIXELS, ROWS, COLS = 72 * 37, 37, 72
WARM = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"
# a silent rig gives Squiggles no beats to spawn on
WARM_UP = {"squiggles": {"spawn_rate": 4.0}, "fireworks": {"spawn_rate": 6.0}}
WARM_FRAMES = 120
# the panel's own diagonal, the scale every distance here is read against
DIAGONAL_PX = float(np.hypot(COLS, ROWS))

# the eight TIER-A pairs (the plan §3a) plus the pair the Admiral named,
# which gains the burst by his D1 (the plan §3b)
TIER_A = (
    ("fish", "orbits"),
    ("fish", "squiggles"),
    ("orbits", "squiggles"),
    ("squiggles", "orbits"),
    ("squiggles", "fish"),
    ("blackhole", "orbits"),
    ("blackhole", "fish"),
    ("blackhole", "squiggles"),
)
SHOALING_PAIR = ("orbits", "fish")


@contextlib.contextmanager
def pinned_rng(seed: int):
    """Pin every UNSEEDED np.random.default_rng() for the duration of a
    run, so the same rig twice is the same run twice."""
    orig = np.random.default_rng
    box = {"k": 0}

    def fake(*a, **k):
        if a or k:
            return orig(*a, **k)
        box["k"] += 1
        return orig(seed * 1000 + box["k"])

    np.random.default_rng = fake
    try:
        yield
    finally:
        np.random.default_rng = orig


async def _host(tmp_path, sub):
    d = str(Path(tmp_path) / sub)
    headless.write_headless_config(d, pixel_count=PIXELS, rows=ROWS)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    v._config["transition_mode"] = "Add"
    v._config["transition_time"] = 0.5
    return host, v


def _out_cfg(out_type, extra=None):
    cfg = {"gradient": WARM, **WARM_UP.get(out_type, {})}
    cfg.update(extra or {})
    return cfg


def _snap_points(effect):
    """An outgoing form's objects right now (pixel positions)."""
    try:
        snap = effect._handoff_snapshot()
    except Exception:
        return None
    if not snap or snap.get("px") is None:
        return None
    px = np.asarray(snap["px"], np.float32)
    py = np.asarray(snap["py"], np.float32)
    br = np.clip(np.asarray(snap["bright"], np.float32), 0.0, 1.0)
    keep = np.isfinite(px) & np.isfinite(py) & (br > 0.03)
    return px[keep], py[keep]


async def control_run(tmp_path, out_type, *, seed=3, frames=120,
                      out_cfg=None, sub=None):
    """The SAME warm-up, and then the switch never happens: the outgoing
    form's own objects, frame by frame. Parents are tracked by nearest
    neighbour from one frame to the next."""
    ph._store.clear()
    host, v = await _host(tmp_path, sub or f"ctl-{out_type}-{seed}")
    tracks = []
    try:
        with pinned_rng(seed), headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, _out_cfg(out_type, out_cfg))
            headless.render_frames(v, WARM_FRAMES, clock=clk)
            for _ in range(frames):
                headless.render_frames(v, 1, clock=clk)
                pts = _snap_points(v.active_effect)
                tracks.append(None if pts is None else (pts[0].copy(),
                                                        pts[1].copy()))
    finally:
        await host.shutdown()
    return tracks


async def program_run(tmp_path, out_type, in_type, *, seed=3, request=None,
                      out_cfg=None, in_cfg=None, after=0, sub=None,
                      keep_frames=False):
    """Switch out_type -> in_type through the registered program, recording
    the cloud, its hosts and the incoming form's own objects every frame
    (and the rendered frames themselves on request)."""
    ph._store.clear()
    host, v = await _host(tmp_path, sub or f"prog-{out_type}-{in_type}-{seed}")
    rec = {"cloud": [], "hosts": [], "form": [], "count": [], "px": []}
    try:
        with pinned_rng(seed), headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, _out_cfg(out_type, out_cfg))
            headless.render_frames(v, WARM_FRAMES, clock=clk)
            outgoing = v.active_effect
            rec["released"] = _snap_points(outgoing)
            rec["out_snap"] = outgoing._handoff_snapshot()
            cfg = {"gradient": WARM}
            cfg.update(in_cfg or {})
            new = host.effects.create(ledfx=host, type=in_type, config=cfg)
            rec["authored"] = getattr(new, "particle_count", None)
            prog = tp.build(out_type, in_type, {"seed": seed, **(request or {})})
            assert prog is not None, (out_type, in_type)
            v.set_effect(new, activate=False, program=prog)
            frames = 0
            while not prog.done and frames < 400:
                f = headless.render_frames(v, 1, clock=clk)[0]
                if keep_frames:
                    rec["px"].append(np.asarray(f, np.uint8).copy())
                frames += 1
                rec["cloud"].append(_cloud(prog))
                rec["hosts"].append(_hosts(prog, new))
                rec["form"].append(_form(new))
                rec["count"].append(getattr(new, "particle_count", None))
            rec["prog"] = prog
            rec["new"] = new
            rec["frames"] = frames
            rec["cls"] = type(prog).__name__
            rec["former"] = type(getattr(prog, "former", None)).__name__
            if after:
                headless.render_frames(v, after, clock=clk)
                rec["count_after"] = getattr(new, "particle_count", None)
    finally:
        await host.shutdown()
    return rec


def _cloud(prog):
    """The cloud's own arrays — a CloudProgram's `x/y/vx/vy`, or the
    eruption's own `ex/ey/evx/evy` (it predates the cloud program and keeps
    its contraction and bloom)."""
    if getattr(prog, "x", None) is not None:
        return (np.asarray(prog.x, np.float32).copy(),
                np.asarray(prog.y, np.float32).copy(),
                np.asarray(prog.vx, np.float32).copy(),
                np.asarray(prog.vy, np.float32).copy())
    if getattr(prog, "ejecta", False) and getattr(prog, "ex", None) is not None:
        return (np.asarray(prog.ex, np.float32).copy(),
                np.asarray(prog.ey, np.float32).copy(),
                np.asarray(prog.evx, np.float32).copy(),
                np.asarray(prog.evy, np.float32).copy())
    return None


def piece_of_object(prog):
    """piece -> released-object index, whichever program shape this is."""
    o = getattr(prog, "obj_of", None)
    if o is None:
        o = getattr(prog, "e_obj", None)
    return None if o is None else np.asarray(o, dtype=np.int64)


def _hosts(prog, inc):
    pids = getattr(prog, "host_pids", None)
    if pids is None or not hasattr(inc, "_program_hosts"):
        return None
    try:
        qx, qy = inc._program_hosts(pids)
    except Exception:
        return None
    return np.asarray(qx, np.float32).copy(), np.asarray(qy, np.float32).copy()


def _form(inc):
    fn = getattr(inc, "_formation_points", None)
    if fn is None:
        return None
    try:
        qx, qy = fn()
    except Exception:
        return None
    return np.asarray(qx, np.float32).copy(), np.asarray(qy, np.float32).copy()


def run(coro):
    return asyncio.run(coro)


# ── the metrics (the plan §4's own definitions) ───────────────────────────

def birth_distance(rec):
    """How far the incoming form's objects are born from the released ones
    (median over the incoming objects, px) on the program's first frame."""
    rel = rec.get("released")
    form = rec["form"][0] if rec["form"] else None
    if rel is None or form is None or form[0].size == 0:
        return None
    d = np.hypot(form[0][:, None] - rel[0][None, :],
                 form[1][:, None] - rel[1][None, :])
    return float(np.median(d.min(axis=1)))


def random_baseline(rec, trials=400, seed=11):
    """The same statistic for two independent random point sets on this
    panel — what "born at random" measures."""
    rel = rec.get("released")
    form = rec["form"][0] if rec["form"] else None
    if rel is None or form is None or form[0].size == 0:
        return None
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(trials):
        ax = rng.uniform(0, COLS, form[0].size)
        ay = rng.uniform(0, ROWS, form[0].size)
        bx = rng.uniform(0, COLS, rel[0].size)
        by = rng.uniform(0, ROWS, rel[0].size)
        d = np.hypot(ax[:, None] - bx[None, :], ay[:, None] - by[None, :])
        out.append(np.median(d.min(axis=1)))
    return float(np.mean(out))


def relative_speed(rec, frac=0.5, start=0.0):
    """Each piece's speed against the object it joins, median over the
    pieces, measured over [start, frac] of the program (the assignment is
    INHERITED here, so there is no per-frame nearest lookup to flip)."""
    prog = rec["prog"]
    obj_of = piece_of_object(prog)
    if obj_of is None:
        return None
    k = int(len(rec["cloud"]) * frac)
    if k < 2:
        return None
    out = []
    for i in range(max(1, int(len(rec["cloud"]) * start)), k):
        c0, c1 = rec["cloud"][i - 1], rec["cloud"][i]
        h0, h1 = rec["hosts"][i - 1], rec["hosts"][i]
        if c1 is None or h0 is None or h1 is None:
            continue
        dt = 1.0 / 60.0
        hvx = (h1[0] - h0[0]) / dt
        hvy = (h1[1] - h0[1]) / dt
        ok = np.isfinite(hvx) & np.isfinite(hvy)
        if not ok.any():
            continue
        sel = ok[obj_of]
        rel = np.hypot(c1[2][sel] - hvx[obj_of][sel],
                       c1[3][sel] - hvy[obj_of][sel])
        if rel.size:
            out.append(float(np.median(rel)))
    return float(np.median(out)) if out else None


def relative_speed_locked(rec, start_frac):
    """Each piece's speed against the incoming object it is joining, with
    the assignment LOCKED on the first FORM frame (the plan's own method: a
    per-frame nearest lookup flips when two objects cross and invents a huge
    relative velocity). Works for a cloud with no inherited assignment —
    which is what today's FORM is."""
    n = len(rec["cloud"])
    i0 = max(1, int(n * start_frac))
    c = rec["cloud"][i0] if i0 < n else None
    f = rec["form"][i0] if i0 < len(rec["form"]) else None
    if c is None or f is None or f[0].size == 0:
        return None
    j = np.argmin(np.hypot(c[0][:, None] - f[0][None, :],
                           c[1][:, None] - f[1][None, :]), axis=1)
    # where the assignment is INHERITED, the object a piece joins is its own
    # host — measuring it against whichever object happens to be nearest
    # would compare it with one it was never going to
    hosts = rec["hosts"][i0] if i0 < len(rec["hosts"]) else None
    obj_of = piece_of_object(rec["prog"])
    if hosts is not None and obj_of is not None and obj_of.size == c[0].size:
        hx, hy = hosts[0][obj_of], hosts[1][obj_of]
        ok = np.isfinite(hx) & np.isfinite(hy)
        if ok.any():
            jh = np.argmin(np.hypot(hx[:, None] - f[0][None, :],
                                    hy[:, None] - f[1][None, :]), axis=1)
            j = np.where(ok, jh, j)
    out = []
    for i in range(i0 + 1, n):
        c0, c1 = rec["cloud"][i - 1], rec["cloud"][i]
        f0, f1 = rec["form"][i - 1], rec["form"][i]
        if (c0 is None or c1 is None or f0 is None or f1 is None
                or f0[0].size != f1[0].size or c0[0].size != c1[0].size
                or c1[0].size != j.size or f1[0].size <= int(j.max())):
            continue
        dt = 1.0 / 60.0
        pvx = (c1[0] - c0[0]) / dt
        pvy = (c1[1] - c0[1]) / dt
        tvx = (f1[0] - f0[0]) / dt
        tvy = (f1[1] - f0[1]) / dt
        out.append(float(np.median(np.hypot(pvx - tvx[j], pvy - tvy[j]))))
    return float(np.median(out)) if out else None


def host_relative_profile(rec):
    """Every piece's speed against its OWN host, frame by frame (median and
    max per frame, px/s) — the whole program, so a jump anywhere in it is
    visible rather than averaged away."""
    prog = rec["prog"]
    obj_of = piece_of_object(prog)
    if obj_of is None:
        return None
    med, mx = [], []
    for i in range(1, len(rec["cloud"])):
        c0, c1 = rec["cloud"][i - 1], rec["cloud"][i]
        h0, h1 = rec["hosts"][i - 1], rec["hosts"][i]
        if c0 is None or c1 is None or h0 is None or h1 is None:
            continue
        if c0[0].size != c1[0].size:
            continue
        ok = np.isfinite(h0[0]) & np.isfinite(h1[0]) \
            & np.isfinite(h0[1]) & np.isfinite(h1[1])
        sel = ok[obj_of]
        if not sel.any():
            continue
        dt = 1.0 / 60.0
        rx = ((c1[0] - c0[0]) - (h1[0] - h0[0])[obj_of])[sel] / dt
        ry = ((c1[1] - c0[1]) - (h1[1] - h0[1])[obj_of])[sel] / dt
        sp = np.hypot(rx, ry)
        med.append(float(np.median(sp)))
        mx.append(float(np.max(sp)))
    if not med:
        return None
    return np.array(med), np.array(mx)


def form_peak_speed(rec, start_frac):
    """The cloud's own PEAK speed over the FORM stage — the "zoom": a
    Hermite to a stranger has to cross whatever distance that stranger
    happened to be at, and its peak speed scales with it."""
    n = len(rec["cloud"])
    i0 = max(1, int(n * start_frac))
    peak = 0.0
    for i in range(i0, n):
        c0, c1 = rec["cloud"][i - 1], rec["cloud"][i]
        if c0 is None or c1 is None or c0[0].size != c1[0].size:
            continue
        sp = np.hypot(c1[0] - c0[0], c1[1] - c0[1]) * 60.0
        if sp.size:
            peak = max(peak, float(np.median(sp)))
    return peak


def nearest_form_distance(rec, frame):
    """Median distance from each piece to the nearest incoming object on a
    given frame — how far the FORM still has to travel."""
    c = rec["cloud"][frame] if frame < len(rec["cloud"]) else None
    f = rec["form"][frame] if frame < len(rec["form"]) else None
    if c is None or f is None or f[0].size == 0:
        return None
    d = np.hypot(c[0][:, None] - f[0][None, :], c[1][:, None] - f[1][None, :])
    return float(np.median(d.min(axis=1)))


def _tracked(tracks, n_frames):
    """Parent trajectories: nearest-neighbour tracking through the control
    run, dropped as soon as the count changes (never a silent re-pairing)."""
    first = tracks[0]
    if first is None or first[0].size == 0:
        return None
    m = first[0].size
    xs = [first[0].copy()]
    ys = [first[1].copy()]
    cur = (first[0].copy(), first[1].copy())
    for t in range(1, min(n_frames, len(tracks))):
        nxt = tracks[t]
        if nxt is None or nxt[0].size == 0:
            break
        d = np.hypot(cur[0][:, None] - nxt[0][None, :],
                     cur[1][:, None] - nxt[1][None, :])
        j = np.argmin(d, axis=1)
        cur = (nxt[0][j].copy(), nxt[1][j].copy())
        xs.append(cur[0])
        ys.append(cur[1])
    if len(xs) < 3:
        return None
    return np.array(xs), np.array(ys), m


def parent_heading(tracks, frames=3):
    """Each parent's heading at the switch instant, from its own travel in
    the control run (never from what the release published)."""
    tr = _tracked(tracks, frames + 1)
    if tr is None:
        return None
    xs, ys, _ = tr
    k = min(frames, xs.shape[0] - 1)
    dx = xs[k] - xs[0]
    dy = ys[k] - ys[0]
    d = np.hypot(dx, dy)
    ok = d > 1e-3
    return np.where(ok, dx / np.maximum(d, 1e-6), 0.0), \
        np.where(ok, dy / np.maximum(d, 1e-6), 0.0), ok


def heading_change_deg(xs, ys, smooth=5):
    """Total heading change over a track, headings smoothed over `smooth`
    frames (the plan's own definition)."""
    if xs.shape[0] <= smooth + 1:
        return None
    h = np.arctan2(ys[smooth:] - ys[:-smooth], xs[smooth:] - xs[:-smooth])
    d = np.angle(np.exp(1j * np.diff(h, axis=0)))
    return np.degrees(np.abs(d).sum(axis=0))


def cloud_turn_deg(rec, upto=None):
    """The cloud's own heading change over the flight (per piece)."""
    n = upto or len(rec["cloud"])
    xs, ys = [], []
    for c in rec["cloud"][:n]:
        if c is None:
            return None
        xs.append(c[0])
        ys.append(c[1])
    if len(xs) < 7 or not xs:
        return None
    sz = min(a.size for a in xs)
    xs = np.array([a[:sz] for a in xs])
    ys = np.array([a[:sz] for a in ys])
    return heading_change_deg(xs, ys)


def parent_turn_deg(tracks, upto):
    tr = _tracked(tracks, upto)
    if tr is None:
        return None
    xs, ys, _ = tr
    return heading_change_deg(xs, ys)


def initial_cosines(rec, tracks):
    """Per piece: the cosine between the cloud's own INITIAL velocity and
    the way its parent was heading (the control run's own travel). The host
    frame makes this 1 by construction at t=0 — a piece's velocity there IS
    its host's, and its host was born on the parent's."""
    prog = rec["prog"]
    obj_of = piece_of_object(prog)
    rel = rec.get("released")
    if obj_of is None or rel is None or len(rec["cloud"]) < 2:
        return None
    ph_ = parent_heading(tracks)
    if ph_ is None:
        return None
    hx, hy, ok = ph_
    # parents <-> released objects: the same seed and the same warm-up, so
    # frame 0 of the control IS the release
    first = tracks[0]
    d = np.hypot(first[0][:, None] - rel[0][None, :],
                 first[1][:, None] - rel[1][None, :])
    par = np.argmin(d, axis=0)          # released object -> parent
    # the first TWO frames on which the cloud exists at all (the eruption
    # has no pieces until its bloom)
    pair = [c for c in rec["cloud"] if c is not None][:2]
    if len(pair) < 2 or pair[0][0].size != pair[1][0].size:
        return None
    c0, c1 = pair
    vx = (c1[0] - c0[0]) * 60.0
    vy = (c1[1] - c0[1]) * 60.0
    sp = np.hypot(vx, vy)
    pi = par[np.clip(obj_of, 0, par.size - 1)]
    good = (sp > 1e-3) & ok[pi]
    if not good.any():
        return None
    cos = (vx[good] * hx[pi][good] + vy[good] * hy[pi][good]) / sp[good]
    return cos
