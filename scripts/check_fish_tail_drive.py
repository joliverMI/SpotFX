"""Measure THE TAIL DRIVE (fx/effects/fish.py `tail_drive`; the TAIL DRIVE
block): his ask and the plan he approved, in numbers (data/fish-swim-plan/
report.md, part 2 and PR 2).

His ask: "I think the fish could get more realism if their velocity bursts
were more directly tied to their swimming motion, so a slow moving fish, or
barely moving fish, would show it's tail swimming and that motion would
visually propel the fish ... show an indicator of when a "beat" hits at a
couple different initial velocities, so we still get the good reactive
movement, but also a more realistic swim." The plan he approved: "tail-
driven swimming with beats as strong as today".

Everything runs through the real vendored pipeline (fx.headless). Each
section is one of the plan's acceptance bars:

  1. TODAY IS ONE SETTING AWAY — at `tail_drive = 0` the kinematics AND the
     frames are byte-identical to the pinned pre-change module, through two
     arcs of his real audio on his crystal (a busy one through a charge, a
     lull, a drop, a big fish and a swim burst; a calm one).
  2. THE SAME SPEED — the steady mean speed within 1% of today at normal and
     loud music (one fish, a long plain tank), and over 60 s of his real
     Contra on his crystal within 2% (three seeds).
  3. BEATS AS STRONG AS TODAY — one fish at three music levels, the same
     beat: the distance swum in the next second within +-10% of today, the
     peak within +25%, and the tail's activity (its drawn size x stroke
     rate) reaching half its rise at least 60 ms before the speed does.
  4. BURST AND GLIDE — at an effort of 0.5 cruise or less a fish glides
     (body straight, no stroke) at least 40% of the time, and no speed rise
     starts while it glides. (The ordinary target never asks for less than
     cruise, so the effort is set on the controller's own input here.)
  5. THE SWIM BURST — the flare's 300 ms dash covers within +-15% of
     today's distance and still starts on the trigger.
  6. THE GUARDS, TAIL DRIVE ON — his music Fish with `tail_drive = 1`: no
     middle past the lit edge and no more pivoting than the old edge
     (check_fish_wall's own scene measure), repeated bursts held on screen
     (check_fish_burst_bounds' own run), mutual avoidance still cutting
     overlap (check_fish_avoidance's own measure), and no ordinary fish's
     middle on the big fish where the panel has room
     (check_fish_big_fish_avoid's own measure).

Read-only, offline. No live access.

    .venv/bin/python scripts/check_fish_tail_drive.py
    .venv/bin/python scripts/check_fish_tail_drive.py --write-fixtures \
        [--shapes-dir /home/javi/SpotFX/storage/audio_shapes]
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_fish_wake_blend as WB  # noqa: E402
import check_fish_wall as W  # noqa: E402
from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

DT = 1.0 / 60.0
FPS = 60
FIXTURES = REPO / "tests" / "fixtures" / "fish_swim"
SONG = {"stem": "Pixel Terror, Sara Skinner - Contra", "t0_s": 40.0,
        "seconds": 60.0}

# This PR's merge-base: the fish just before the tail drive (with PR 1's
# wake colour and blend). PINNED, never a moving ref.
TAIL_BASELINE_REF = "84c01f33afc0fa755f73bd49ba0ee92a79696f1f"
ON = {"tail_drive": 1.0}

FAILURES: list[str] = []


def check(cond, label):
    print(f"   {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILURES.append(label)


# ── fixtures ────────────────────────────────────────────────────────────
def record_song(shapes_dir):
    lows, beats = asyncio.run(WB._record(SONG["stem"], shapes_dir))
    i0 = int(SONG["t0_s"] * FPS)
    n = int(SONG["seconds"] * FPS)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / "contra_40-100s.npz"
    np.savez_compressed(path, lows=lows[i0:i0 + n], beat=beats[i0:i0 + n],
                        stem=np.array(SONG["stem"]),
                        t0_s=np.array(SONG["t0_s"]))
    print(f"wrote {path.relative_to(REPO)}: {int(beats[i0:i0 + n].sum())} "
          "beats")


def load_song():
    with np.load(FIXTURES / "contra_40-100s.npz", allow_pickle=False) as d:
        return d["lows"], d["beat"]


def load_baseline(name="fish_tail_pinned"):
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{TAIL_BASELINE_REF}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except Exception as exc:                        # noqa: BLE001
        raise SystemExit(
            f"cannot read {TAIL_BASELINE_REF}:fx/effects/fish.py out of "
            f"git: {exc}"
        )
    if "wake_blend" not in src or "tail_drive" in src:
        raise SystemExit(f"TAIL_BASELINE_REF {TAIL_BASELINE_REF} is not the "
                         "fish just before the tail drive")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


# ── 1. tail_drive 0 is today ────────────────────────────────────────────
def _kinematics(rows):
    def keep(eff):
        own = eff._composite

        def composite(body, wake, big):
            n = eff.n
            rows.append(tuple(
                np.array(getattr(eff, k)[:n], copy=True)
                for k in ("p_x", "p_y", "p_hd", "p_spd", "p_flap", "p_mode")
            ))
            return own(body, wake, big)
        eff._composite = composite
    return keep


def section_identity():
    print("\n1  TODAY, ONE SETTING AWAY — tail_drive 0 against the pinned "
          f"pre-change module ({TAIL_BASELINE_REF[:8]})")
    pinned = load_baseline()
    for arc in WB.ARCS:
        old_k, new_k = [], []
        old = asyncio.run(WB.run_arc(arc, pinned,
                                     on_attach=_kinematics(old_k)))
        new = asyncio.run(WB.run_arc(arc, "fish", {"tail_drive": 0.0},
                                     on_attach=_kinematics(new_k)))
        frames = old.shape == new.shape and np.array_equal(old, new)
        kin = len(old_k) == len(new_k) and all(
            all(np.array_equal(a, b) for a, b in zip(ra, rb))
            for ra, rb in zip(old_k, new_k)
        )
        print(f"   {arc}: {old.shape[0]} frames — frames "
              f"{'identical' if frames else 'DIFFERENT'}, kinematics "
              f"{'identical' if kin else 'DIFFERENT'}")
        check(frames and kin, f"{arc}: tail_drive 0 is the pre-change fish, "
              "bit for bit")
    on = asyncio.run(WB.run_arc("busy", "fish", ON))
    off = asyncio.run(WB.run_arc("busy", "fish", {"tail_drive": 0.0}))
    check(not np.array_equal(on, off),
          "control: tail_drive 1 renders a different arc (the identity is "
          "not vacuous)")


# ── the plain tank: one fish, swimming straight ─────────────────────────
TANK_COLS, TANK_ROWS = 420, 161
RADIUS_TALL = 32.4 / 80.0   # s_min (cruise, turn radius, size) = the 37-row
                            # panel's
LEVELS = {"quiet": 0.03, "normal": 0.12, "loud": 0.55}
SOLID = "linear-gradient(90deg, #00c8ff 0%, #00c8ff 100%)"
QUIET_STEER = ("WANDER_SWING", "WANDER_SWING_JIGGLE", "HOME_W", "BOUND_W")


class _Audio:
    def __init__(self):
        self.lows = 0.0
        self.beat = False

    def lows_power(self, filtered=True):
        return self.lows

    def bpm_beat_now(self):
        return self.beat


_RUN = [0]


async def tank(lows, extra=None, *, seconds=8.0, beats=(), pokes=None,
               effort=None, seed=11):
    """One fish of his music Fish's own size, speed and tail, swimming right
    along a long plain tank with the wander, home and pond steering off and
    the beat's TURN kick cleared each frame (its speed kick stays), so the
    swim itself is all there is. Per frame: position, speed (x cruise), the
    drawn tail's size (x its cruise size) and stroke rate, and whether the
    tail drive is stroking. `effort` (x cruise) replaces the tail drive's
    target on its own input; `pokes` maps a frame to a config write."""
    _RUN[0] += 1
    dev = f"fish-tail-tank-{_RUN[0]}"
    cfg = dict(W.MUSIC_FISH, particle_count=1, jiggle=0.0, spin=0.0,
               avoid_strength=0.0, camera_follow=0.0, wall_lookahead=0.0,
               horizon_scale=0.0, gradient=SOLID, color_shift=0,
               radius_scale=RADIUS_TALL, **(extra or {}))
    saved = {k: getattr(FX, k) for k in QUIET_STEER}
    for k in QUIET_STEER:
        setattr(FX, k, 0.0)
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / dev), pixel_count=TANK_COLS * TANK_ROWS,
        rows=TANK_ROWS, device_id=dev,
    )
    virtual = host.virtuals.get(dev)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    rec = []
    try:
        eff = headless.attach_effect(host, virtual, "fish", cfg)
        eff._rng = np.random.default_rng(seed)
        audio = _Audio()
        audio.lows = lows
        clock.advance(DT)
        eff.audio_data_updated(audio)
        virtual.assemble_frame()
        eff.p_mode[0] = 0
        eff.p_enter[0] = 1.0
        eff.p_x[0] = (24.0 - eff.cx) / eff.sx
        eff.p_y[0] = 0.0
        eff.p_hd[0] = 0.0
        eff.p_spd[0] = eff.cruise_px
        eff.p_trail_x[0, 0] = np.nan
        cruise = eff.cruise_px
        drawn = {}
        own_draw = eff._draw_bodies

        def draw_bodies(frame, visible, x, y, hd, bright, half_w, flap_amp,
                        *rest, **kw):
            drawn["size"] = float(
                flap_amp[0] / (eff.flap_amount * half_w[0] * eff.body_aspect)
            )
            return own_draw(frame, visible, x, y, hd, bright, half_w,
                            flap_amp, *rest, **kw)
        eff._draw_bodies = draw_bodies
        if effort is not None:
            own_step = eff._tail_drive_step

            def forced(eligible, want_tail, *a, **k):
                want_tail = np.where(eligible, effort * eff.cruise_px,
                                     want_tail)
                return own_step(eligible, want_tail, *a, **k)
            eff._tail_drive_step = forced
        beat_frames = {int(b * FPS) for b in beats}
        flap_prev = float(eff.p_flap[0])
        with np.errstate(invalid="ignore", divide="ignore"):
            for i in range(int(seconds * FPS)):
                hit = any(0 <= i - bf < 3 for bf in beat_frames)
                audio.lows = 0.95 if hit else lows
                audio.beat = i in beat_frames
                if pokes and i in pokes:
                    eff.update_config(pokes[i])
                clock.advance(DT)
                eff.audio_data_updated(audio)
                frame = virtual.assemble_frame()
                virtual.flush(frame)
                eff.p_jog[:eff.n] = 0.0
                flap = float(eff.p_flap[0])
                rate = ((flap - flap_prev) % (2 * np.pi * 64)) / (
                    2 * np.pi * DT)
                flap_prev = flap
                rec.append((
                    float(eff.cx + eff.p_x[0] * eff.sx),
                    float(eff.cy + eff.p_y[0] * eff.sy),
                    float(eff.p_spd[0]) / cruise,
                    drawn.get("size", float("nan")), rate,
                    float(eff.p_tst[0]),
                ))
    finally:
        for k, v in saved.items():
            setattr(FX, k, v)
        cm.__exit__(None, None, None)
        await host.shutdown()
    return np.array(rec, dtype=np.float64)


def _path(rec):
    return np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(rec[:, 0]),
                                                     np.diff(rec[:, 1])))])


def _half_rise(sig, b, pre_n=60, post_n=60):
    pre = float(sig[b - pre_n:b].mean())
    post = sig[b:b + post_n]
    peak = float(post.max())
    above = np.flatnonzero(post >= pre + 0.5 * (peak - pre))
    return (float(above[0]) / FPS) if above.size else float("nan")


# ── 2. the same speed ───────────────────────────────────────────────────
async def _song_speed(extra, seed):
    lows, beats = load_song()
    _RUN[0] += 1
    dev = f"fish-tail-song-{_RUN[0]}"
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / dev), pixel_count=W.ROWS * W.COLS, rows=W.ROWS,
        device_id=dev, real_mask=WB.REAL,
    )
    virtual = host.virtuals.get(dev)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    speeds, worst = [], -1e9
    try:
        eff = headless.attach_effect(host, virtual, "fish",
                                     dict(W.MUSIC_FISH, **(extra or {})))
        eff._rng = np.random.default_rng(seed)
        audio = _Audio()
        for i in range(lows.size):
            audio.lows, audio.beat = float(lows[i]), bool(beats[i])
            clock.advance(DT)
            eff.audio_data_updated(audio)
            frame = virtual.assemble_frame()
            virtual.flush(frame)
            sw = np.flatnonzero(eff.p_mode[:eff.n] == 0)
            if sw.size:
                speeds.append(float(eff.p_spd[sw].mean() / eff.cruise_px))
                x = eff.cx + eff.p_x[sw] * eff.sx - eff.cam_px
                y = eff.cy + eff.p_y[sw] * eff.sy - eff.cam_py
                worst = max(worst, float(-W.edge_distance(x, y).min()))
    finally:
        cm.__exit__(None, None, None)
        await host.shutdown()
    return float(np.mean(speeds)), worst


_SONG_TAIL: dict = {}


def section_speed():
    print("\n2  THE SAME SPEED — steady music, and 60 s of his real Contra")
    for level in ("normal", "loud"):
        a = asyncio.run(tank(LEVELS[level], seconds=10.0))
        b = asyncio.run(tank(LEVELS[level], ON, seconds=10.0))
        ma, mb = a[120:, 2].mean(), b[120:, 2].mean()
        print(f"   {level:6s} steady: today {ma:5.3f}x  tail {mb:5.3f}x  "
              f"({100 * (mb / ma - 1):+.2f}%)")
        check(abs(mb / ma - 1.0) <= 0.01,
              f"{level}: the steady mean speed within 1% of today")
    today, tail = [], []
    for seed in (1, 2, 3):
        today.append(asyncio.run(_song_speed({}, seed))[0])
        _SONG_TAIL[seed] = asyncio.run(_song_speed(ON, seed))
        tail.append(_SONG_TAIL[seed][0])
    mt, mn = float(np.mean(today)), float(np.mean(tail))
    print(f"   Contra 40-100 s, his Fish, 3 seeds: today {mt:5.3f}x  tail "
          f"{mn:5.3f}x cruise ({100 * (mn / mt - 1):+.2f}%)")
    check(abs(mn / mt - 1.0) <= 0.02,
          "a 60 s real song: the mean speed within 2% of today")


# ── 3. beats ────────────────────────────────────────────────────────────
def section_beats():
    print("\n3  BEATS AS STRONG AS TODAY — one fish, three levels, a beat at "
          "2.5 s")
    b = int(2.5 * FPS)
    for level, lows in LEVELS.items():
        rows = {}
        for label, extra in (("today", None), ("tail", ON)):
            rec = asyncio.run(tank(lows, extra, beats=(2.5, 5.5)))
            path = _path(rec)
            activity = rec[:, 3] * rec[:, 4]
            rows[label] = {
                "pre": rec[b - 60:b, 2].mean(),
                "peak": rec[b:b + 60, 2].max(),
                "t_peak": np.argmax(rec[b:b + 60, 2]) / FPS,
                "dist": path[b + 60] - path[b],
                "lead_ms": 1000.0 * (_half_rise(rec[:, 2], b)
                                     - _half_rise(activity, b)),
            }
        for label, m in rows.items():
            print(f"   {level:6s} {label:5s} before {m['pre']:4.2f}x  peak "
                  f"{m['peak']:4.2f}x at +{m['t_peak']:4.2f} s  next 1 s "
                  f"{m['dist']:5.1f} px  tail leads the speed by "
                  f"{m['lead_ms']:4.0f} ms")
        t, n = rows["today"], rows["tail"]
        check(abs(n["dist"] / t["dist"] - 1.0) <= 0.10,
              f"{level}: the distance swum in the next second within 10% "
              f"of today ({100 * (n['dist'] / t['dist'] - 1):+.1f}%)")
        check(n["peak"] <= 1.25 * t["peak"],
              f"{level}: the peak within +25% of today "
              f"({100 * (n['peak'] / t['peak'] - 1):+.1f}%)")
        check(n["lead_ms"] >= 60.0,
              f"{level}: the tail reaches half its rise "
              f"{n['lead_ms']:.0f} ms before the speed (bar 60)")


# ── 4. burst and glide ──────────────────────────────────────────────────
def section_glide():
    print("\n4  BURST AND GLIDE — the controller at an effort it is given")
    for effort in (0.5, 0.25):
        rec = asyncio.run(tank(LEVELS["quiet"], ON, seconds=20.0,
                               effort=effort))[120:]
        speed, stroking = rec[:, 2], rec[:, 5] > 0.5
        glide = 100.0 * float(np.mean(~stroking))
        dv = np.diff(speed)
        # a rise STARTS where the speed turns from falling (or flat) to
        # rising; the state that frame's push came from is that frame's own
        onset = np.flatnonzero((dv[1:] > 1e-6) & (dv[:-1] <= 1e-6)) + 2
        gliding_onsets = int(np.count_nonzero(~stroking[onset]))
        print(f"   effort {effort:4.2f}: gliding {glide:4.1f}% of the time, "
              f"mean speed {speed.mean():4.2f}x, {onset.size} speed rises, "
              f"{gliding_onsets} of them starting while gliding")
        check(glide >= 40.0, f"effort {effort}: glides at least 40% of the "
              "time")
        check(gliding_onsets == 0, f"effort {effort}: no speed rise starts "
              "while gliding")


# ── 5. the swim burst ───────────────────────────────────────────────────
def section_burst():
    print("\n5  THE SWIM BURST — the flare's 300 ms dash, normal music")
    on_at = int(3.0 * FPS)
    off_at = on_at + int(0.3 * FPS)
    pokes = {on_at: {"swim_burst": True}, off_at: {"swim_burst": False}}
    rows = {}
    for label, extra in (("today", None), ("tail", ON)):
        rec = asyncio.run(tank(LEVELS["normal"], extra, pokes=pokes,
                               seconds=6.0))
        path = _path(rec)
        pre = rec[on_at - 30:on_at, 2].mean()
        rising = np.flatnonzero(rec[on_at:, 2] >= 1.05 * pre)
        rows[label] = {
            "dash": path[off_at] - path[on_at],
            "second": path[on_at + 60] - path[on_at],
            "onset_ms": 1000.0 * (rising[0] if rising.size else np.nan) / FPS,
        }
        m = rows[label]
        print(f"   {label:5s} during the 300 ms {m['dash']:5.1f} px  first "
              f"second {m['second']:5.1f} px  speed up 5% "
              f"{m['onset_ms']:4.0f} ms after the trigger")
    t, n = rows["today"], rows["tail"]
    check(abs(n["dash"] / t["dash"] - 1.0) <= 0.15,
          "the 300 ms dash covers within 15% of today's distance "
          f"({100 * (n['dash'] / t['dash'] - 1):+.1f}%)")
    check(n["onset_ms"] <= t["onset_ms"] + 1000.0 / FPS,
          "it still starts on the trigger (no later than today's, give or "
          "take a frame)")


# ── 6. the guards, tail drive on ────────────────────────────────────────
def section_guards():
    print("\n6  THE GUARDS, TAIL DRIVE ON — his music Fish at tail_drive 1")
    seeds, seconds = (0, 1, 2), 30.0
    off = W.measure_scene(W.MUSIC_FISH, "fish", seeds, seconds)
    on = W.measure_scene(dict(W.MUSIC_FISH, **ON), "fish", seeds, seconds)
    old = W.measure_scene(dict(W.MUSIC_FISH, **W.OLD), "fish", seeds,
                          seconds)
    print(W._row("off", off))
    print(W._row("on", on))
    check(on["off"] <= 0.1, "the wall: no middle leaves the panel")
    check(on["tightest"] <= old["tightest"],
          "the wall: no more pivoting than the old edge")
    check(on["cover"] >= off["cover"] - 8.0,
          "the wall: about as much of its pond used as at tail_drive 0")
    worst = [(_SONG_TAIL.get(s) or asyncio.run(_song_speed(ON, s)))[1]
             for s in (1, 2, 3)]
    print(f"   60 s of Contra: the worst middle {max(worst):+.2f} px past "
          "the lit edge (negative = inside)")
    check(max(worst) <= 0.0, "a real song: no middle past the lit edge")

    import check_fish_burst_bounds as BB
    worst_b = worst_0 = -1e9
    for seed in range(4):
        for count in (3, 6):
            for period in (0.4, 1.0):
                off_b, _ = asyncio.run(BB._run(
                    {"particle_count": count, **ON}, seed, burst_ms=300,
                    period=period, seconds=12.0))
                worst_b = max(worst_b, off_b)
            off_0, _ = asyncio.run(BB._run(
                {"particle_count": count, **ON}, seed, burst_ms=0,
                period=1.0, seconds=12.0))
            worst_0 = max(worst_0, off_0)
    print(f"   repeated bursts: worst {worst_b:.2f} px past the panel edge "
          f"(no-burst baseline {worst_0:.2f} px)")
    check(worst_b <= worst_0 + 3.0,
          "the swim burst still stays on screen")

    import check_fish_avoidance as AV
    saved = AV.HIS
    try:
        AV.HIS = dict(saved, **ON)
        none = asyncio.run(AV._measure(0.0, 10))[1]
        his = asyncio.run(AV._measure(0.45, 10))[1]
    finally:
        AV.HIS = saved
    print(f"   mutual avoidance, 10 fish: overlap {none:.2%} at strength 0, "
          f"{his:.2%} at his 0.45")
    check(his < none, "mutual avoidance still cuts the overlap")

    import check_fish_big_fish_avoid as BF
    for intensity in (0.2, 0.8):
        m = BF.summarize(intensity, 1.0, **ON)
        print(f"   big fish at {intensity}: {m['middles_mid']} middles on "
              "its body in the middle columns")
        check(m["middles_mid"] == 0, f"big fish at {intensity}: no ordinary "
              "fish swims through it where the panel has room")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-fixtures", action="store_true")
    ap.add_argument("--shapes-dir", default=WB.LIVE_SHAPES)
    ap.add_argument("--record", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.record:
        record_song(args.shapes_dir)
        return
    if args.write_fixtures:
        # one song per interpreter (check_fish_wake_blend.py says why)
        subprocess.run([sys.executable, __file__, "--record",
                        "--shapes-dir", args.shapes_dir], cwd=REPO,
                       check=True)
    print("FISH TAIL DRIVE — the tail's own stroke pushes the fish")
    section_identity()
    section_speed()
    section_beats()
    section_glide()
    section_burst()
    section_guards()
    if FAILURES:
        print("\nFAILED:")
        for f in FAILURES:
            print("   " + f)
        raise SystemExit(1)
    print("\nALL TAIL DRIVE CHECKS PASS")


if __name__ == "__main__":
    main()
