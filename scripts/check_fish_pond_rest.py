"""Measure THE POND REST (fx/effects/fish.py `quiet_rest`; the POND REST
block): his ask and the plan he approved, in numbers (data/fish-swim-plan/
report.md, part 2b and PR 3).

His ask: "at really low music levels, like when it's almost or completely
quiet, the fish should almost come to a rest, with very sporadic short
motions, like real fish in a pond". The plan he approved: "a quiet pond rest
with occasional darts", with the defaults "the pond rest is for the music
Fish scene only; 'quiet' means the music's own level".

Everything runs through the real vendored pipeline (fx.headless) on his
crystal, his music Fish at its binding fallbacks. Each section is one of the
plan's acceptance bars:

  1. TODAY IS ONE SETTING AWAY — at `quiet_rest = 0` the kinematics AND the
     frames are byte-identical to the pinned pre-change module through both
     arcs of his real audio (check_fish_wake_blend's busy and calm), at
     `tail_drive` 0 and 1, fed a deeply quiet level the whole way, and
     `volume()` is never read.
  2. BETWEEN TWO SONGS — his real Contra outro and fade, GAP_S with no audio
     at all, then Dopamine's opening, with the tail drive and the rest on:
     the mean speed through the end of the fade and the gap at most 0.25x
     cruise, at least one dart over the three seeds, back above 2x cruise
     within 0.5 s of Dopamine's first hit, the music before the fade
     unchanged, and no middle past the lit edge (three seeds). Today's run
     beside it, for scale.
  3. THE DARTS — 90 s of deep quiet: a resting fish darts on its own clock
     (mean `dart_every_s`, never sooner than DART_MIN_S), each dart a short
     push that moves and turns it, resting between, never past the lit
     edge.
  4. THE MOMENTS KEEP THEIR STRENGTH AT REST — a swim burst fired at full
     rest still dashes, and a big fish crossing a resting shoal still finds
     no fish's middle on it (check_fish_big_fish_avoid's own bar); each with
     the red control of the rest applied to the whole target.
  5. A DRUMLESS QUIET PASSAGE — the beat tracker's ticks with no onset under
     them lunge no resting fish (and do lunge the same shoal at
     `quiet_rest = 0`, the control); a real onset still lunges it, and it
     bursts above 2x cruise.
  6. NEVER DURING A MOMENT — fed deep quiet throughout, the rest level is 0
     and no fish darts on every frame of a charge, a lull, a drop and its
     rush, a formed school and an outgoing crossfade; and the rest is back
     between them.
  7. AN AUDIO PAUSE — no audio callback for more than REST_SILENCE_S (the
     audio hub's own pause) rests the shoal; an effect that has never heard
     anything does not.
  8. HIS LIBRARY — the same detector (`rest_step`) over 125 of his captured
     songs (tests/fixtures/fish_swim/library_volume.npz: volume() computed
     the pipeline's way from his WAVs, checked here against the real
     pipeline's own reading of Contra's outro): at rest at most 1% of song
     time, and a rest inside the music (beyond its first and last 15 s) in
     at most 3% of the songs. The detector alone is the upper bound: in the
     effect a strong hit also cuts the rest (the startle).

Read-only, offline. No live access.

    .venv/bin/python scripts/check_fish_pond_rest.py
    .venv/bin/python scripts/check_fish_pond_rest.py --write-fixtures \\
        [--shapes-dir /home/javi/SpotFX/storage/audio_shapes]
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_fish_big_fish_avoid as BA  # noqa: E402
import check_fish_tail_drive as TD  # noqa: E402
import check_fish_wake_blend as WB  # noqa: E402
import check_fish_wall as W  # noqa: E402
import fx.effects.particle_handoff as particle_handoff  # noqa: E402
from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

DT = 1.0 / 60.0
FPS = 60
FIXTURES = REPO / "tests" / "fixtures" / "fish_swim"

# the between-songs timeline: Contra's soft outro and fade, GAP_S with no
# audio at all (the hub pauses), then Dopamine's opening
SONGS = {
    "contra": {"stem": "Pixel Terror, Sara Skinner - Contra",
               "from_s": 226.0, "to_s": None, "file": "contra_outro.npz"},
    "dopamine": {"stem": "Wooli, Tape B - Dopamine",
                 "from_s": 0.0, "to_s": 9.0, "file": "dopamine_opening.npz"},
}
LIBRARY_FILE = "library_volume.npz"
LIBRARY_EVERY = 4           # every 4th of his captured songs: 125 of 500

# This PR's merge-base: the fish just before the pond rest (with PR 2's tail
# drive). PINNED, never a moving ref.
REST_BASELINE_REF = "66d1630cce7c1372b6bc2e3f8a2a9da27386097a"
ON = {"tail_drive": 1.0, "quiet_rest": 1.0}       # his music Fish, PR 2 + 3
TAIL_ONLY = {"tail_drive": 1.0, "quiet_rest": 0.0}
REST_ONLY = {"tail_drive": 0.0, "quiet_rest": 1.0}
TODAY = {"tail_drive": 0.0, "quiet_rest": 0.0}
QUIET = 0.40                # volume(): -60 dB, below full rest
LOUD = 0.80                 # volume(): -20 dB, an ordinary playing level
GAP_S = 5.0                 # between the songs, no audio callback at all
SETTLE_S = 4.0              # the outro's first seconds, unmeasured
SEEDS = (5, 7, 11)

# the bars (the plan's PR 3 acceptance)
GAP_SPEED_MAX = 0.25        # x cruise, mean from 1 s after the outro ends
DARTS_MIN = 1
WAKE_SPEED_X = 2.0          # x cruise ...
WAKE_WITHIN_S = 0.5         # ... within this of the next song's first hit
OUTRO_SHARE = 0.05          # the music before the fade: within 5% of the
                            # tail drive alone
LIBRARY_REST_MAX = 1.0      # % of song time at rest
LIBRARY_MID_MAX = 3.0       # % of songs with a rest inside the music
EDGE_S = 15.0               # "inside the music": beyond its first/last 15 s
AT_REST = 0.8               # a rest level this high is "at rest"
PIPELINE_DIFF_MAX = 0.01    # the library's volume against the pipeline's

FAILURES: list[str] = []


def check(cond, label):
    print(f"   {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILURES.append(label)


# ── fixtures ────────────────────────────────────────────────────────────
def record_song(name, shapes_dir):
    """One song through the real analysis (check_fish_wake_blend._record):
    per accepted 60 fps frame its lows power, `bpm_beat_now()` and
    `volume()`, cut to the timeline's window."""
    spec = SONGS[name]
    lows, beats, vols = asyncio.run(
        WB._record(spec["stem"], shapes_dir, volume=True)
    )
    i0 = int(spec["from_s"] * FPS)
    i1 = lows.size if spec["to_s"] is None else int(spec["to_s"] * FPS)
    if lows.size < i1 or i1 <= i0:
        raise SystemExit(f"{spec['stem']}: only {lows.size} frames")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / spec["file"]
    np.savez_compressed(
        path, lows=lows[i0:i1], beat=beats[i0:i1], vol=vols[i0:i1],
        stem=np.array(spec["stem"]), from_s=np.array(spec["from_s"]),
    )
    print(f"wrote {path.relative_to(REPO)}: {(i1 - i0) / FPS:.1f} s, "
          f"{int(beats[i0:i1].sum())} beats, volume "
          f"{float(vols[i0:i1].min()):.2f}-{float(vols[i0:i1].max()):.2f}")


def load_song(name):
    with np.load(FIXTURES / SONGS[name]["file"], allow_pickle=False) as d:
        return d["vol"], d["lows"], d["beat"]


def wav_volume(path):
    """volume() the pipeline's way (fx/effects/audio.py pre_process_audio):
    1 + dB SPL / 100 over each 1/60 s of the mono signal, clipped to [0, 1].
    The analysis filters it at alpha 0.99, so the filtered value volume()
    returns is this to within a hundredth (section 8 checks it)."""
    import soundfile as sf

    pcm, sr = sf.read(path, dtype="float32", always_2d=False)
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    hop = int(sr) // FPS
    n = pcm.size // hop
    power = np.mean(
        np.square(pcm[: n * hop].reshape(n, hop), dtype=np.float64), axis=1
    )
    with np.errstate(divide="ignore"):
        vol = 1.0 + 10.0 * np.log10(power) / 100.0
    return np.clip(np.nan_to_num(vol, neginf=0.0), 0.0, 1.0)


def record_library(shapes_dir):
    """Every LIBRARY_EVERY-th of his captured songs (Contra always among
    them, for section 8's cross-check), volume() per frame quantised to
    1/255."""
    files = sorted(glob.glob(os.path.join(shapes_dir, "*.wav")))
    if not files:
        raise SystemExit(f"no captured songs in {shapes_dir}")
    pick = files[::LIBRARY_EVERY]
    contra = os.path.join(shapes_dir, SONGS["contra"]["stem"] + ".wav")
    if contra in files and contra not in pick:
        pick.append(contra)
    traces, stems = [], []
    for k, f in enumerate(pick):
        traces.append(np.round(wav_volume(f) * 255.0).astype(np.uint8))
        stems.append(Path(f).stem)
        if (k + 1) % 25 == 0:
            print(f"   {k + 1}/{len(pick)} songs", flush=True)
    starts = np.cumsum([0] + [t.size for t in traces])
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / LIBRARY_FILE
    np.savez_compressed(path, vol=np.concatenate(traces), starts=starts,
                        stems=np.array(stems))
    print(f"wrote {path.relative_to(REPO)}: {len(traces)} songs, "
          f"{starts[-1] / FPS / 3600:.1f} h")


def load_library():
    with np.load(FIXTURES / LIBRARY_FILE, allow_pickle=False) as d:
        vol = d["vol"].astype(np.float64) / 255.0
        starts, stems = d["starts"], d["stems"]
    return [(str(stems[k]), vol[starts[k]:starts[k + 1]])
            for k in range(len(stems))]


def write_fixtures(shapes_dir):
    # one song per interpreter: the analysis carries process-wide state, and
    # a song analysed after another was measured not to reproduce itself
    for name in SONGS:
        subprocess.run(
            [sys.executable, __file__, "--record", name,
             "--shapes-dir", shapes_dir],
            cwd=REPO, check=True,
        )
    record_library(shapes_dir)


def load_baseline(name="fish_rest_pinned"):
    """Register REST_BASELINE_REF's fish.py as a second effect type (an
    Effect registers under its module's last name segment)."""
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{REST_BASELINE_REF}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except Exception as exc:                        # noqa: BLE001
        # a genuinely missing input (a shallow clone): named, never a pass
        raise SystemExit(
            f"cannot read {REST_BASELINE_REF}:fx/effects/fish.py out of "
            f"git: {exc}"
        )
    if "tail_drive" not in src or "quiet_rest" in src:
        raise SystemExit(f"REST_BASELINE_REF {REST_BASELINE_REF} is not the "
                         "fish just before the pond rest")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


# ── the rig ─────────────────────────────────────────────────────────────
class _Audio:
    """What the fish reads from the audio source, set per frame: its lows
    power, the beat tracker, and the absolute level the pond rest hears
    (every read counted)."""

    def __init__(self, vol=LOUD):
        self.lows = 0.0
        self.beat = False
        self.vol = vol
        self.reads = 0

    def lows_power(self, filtered=True):
        return self.lows

    def bpm_beat_now(self):
        return self.beat

    def volume(self, filtered=True):
        self.reads += 1
        return self.vol


_RUN = [0]


class Crystal:
    """His music Fish (`extra` on top) on his crystal, one frame at a time:
    `frame(...)` advances the clock, hands the fish this frame's audio
    (unless `heard` is False: no callback at all, the hub's own pause) and
    renders. Counts the darts begun and keeps each frame's spike."""

    @classmethod
    async def open(cls, extra=None, seed=5):
        self = cls()
        _RUN[0] += 1
        # a UNIQUE device per run: particle_handoff keys its snapshot by
        # device, and a reused name would hand one run's fish to the next
        dev = f"fish-pond-rest-{_RUN[0]}"
        td = tempfile.mkdtemp()
        self.host = await headless.start_headless_host(
            str(Path(td) / dev), pixel_count=W.ROWS * W.COLS, rows=W.ROWS,
            device_id=dev, real_mask=WB.REAL,
        )
        self.virtual = self.host.virtuals.get(dev)
        self._cm = headless.fake_clock()
        self.clock = self._cm.__enter__()
        self.fish = headless.attach_effect(
            self.host, self.virtual, "fish",
            dict(W.MUSIC_FISH, **(extra or {})),
        )
        self.fish._rng = np.random.default_rng(seed)
        self.audio = _Audio()
        self.darts = 0
        self.spike = 0.0
        fish = self.fish
        own_darts = fish._dart_step
        own_rest = fish._pond_rest_step

        def darts(n, dt, eligible, rest):
            before = fish.p_dart[:n].copy()
            out = own_darts(n, dt, eligible, rest)
            # a dart's clock only counts down (below 0 through its glide),
            # except where a dart begins: then it turns positive
            after = fish.p_dart[:n]
            self.darts += int(np.count_nonzero((after > 0.0)
                                               & (after > before)))
            return out

        def rest_step(n, dt, eligible, want, want_tail, cruise, spike,
                      jump_eff):
            self.spike = float(spike)
            return own_rest(n, dt, eligible, want, want_tail, cruise,
                            spike, jump_eff)
        fish._dart_step = darts
        fish._pond_rest_step = rest_step
        return self

    def frame(self, vol=LOUD, lows=0.1, beat=False, heard=True):
        self.spike = 0.0
        self.clock.advance(DT)
        if heard:
            a = self.audio
            a.vol, a.lows, a.beat = float(vol), float(lows), bool(beat)
            self.fish.audio_data_updated(a)
        f = self.virtual.assemble_frame()
        if f is not None:
            self.virtual.flush(f)

    def speed(self):
        """The ordinary swimmers' mean speed, x cruise (NaN with none)."""
        eff = self.fish
        sw = np.flatnonzero(eff.p_mode[:eff.n] < 2)
        if not sw.size:
            return float("nan")
        return float(eff.p_spd[sw].mean() / eff.cruise_px)

    def past_edge(self):
        """How far the worst swimming fish's middle is past his crystal's
        lit edge, px (negative = inside; check_fish_wall's own measure)."""
        eff = self.fish
        sw = np.flatnonzero(eff.p_mode[:eff.n] < 2)
        if not sw.size:
            return -1e9
        x = eff.cx + eff.p_x[sw] * eff.sx - eff.cam_px
        y = eff.cy + eff.p_y[sw] * eff.sy - eff.cam_py
        return float(-W.edge_distance(x, y).min())

    def lunged(self):
        """A lunge armed this frame (it sets the hold, which then counts
        down by one frame)."""
        eff = self.fish
        n = eff.n
        return bool(n) and float(eff.p_lun_t[:n].max()) >= (
            FX.LUNGE_HOLD_S - DT - 1e-6)

    async def close(self):
        self._cm.__exit__(None, None, None)
        await self.host.shutdown()


def _first(mask, start=0):
    hits = np.flatnonzero(np.asarray(mask[start:], dtype=bool))
    return start + int(hits[0]) if hits.size else None


# ── 1. quiet_rest 0 is today ────────────────────────────────────────────
def section_identity():
    print("\n1  TODAY, ONE SETTING AWAY — quiet_rest 0 against the pinned "
          f"pre-change module ({REST_BASELINE_REF[:8]}), fed volume() "
          f"{QUIET} (deep quiet) the whole way")
    pinned = load_baseline()
    for tail in (0.0, 1.0):
        for arc in WB.ARCS:
            old_k, new_k = [], []
            heard = _Audio(vol=QUIET)
            old = asyncio.run(WB.run_arc(
                arc, pinned, {"tail_drive": tail},
                on_attach=TD._kinematics(old_k)))
            new = asyncio.run(WB.run_arc(
                arc, "fish", {"tail_drive": tail, "quiet_rest": 0.0},
                on_attach=TD._kinematics(new_k), audio=heard))
            frames = old.shape == new.shape and np.array_equal(old, new)
            kin = len(old_k) == len(new_k) and all(
                all(np.array_equal(a, b) for a, b in zip(ra, rb))
                for ra, rb in zip(old_k, new_k)
            )
            print(f"   {arc}, tail_drive {tail:g}: {old.shape[0]} frames — "
                  f"frames {'identical' if frames else 'DIFFERENT'}, "
                  f"kinematics {'identical' if kin else 'DIFFERENT'}, "
                  f"volume() read {heard.reads} times")
            check(frames and kin and heard.reads == 0,
                  f"{arc}, tail_drive {tail:g}: quiet_rest 0 is the "
                  "pre-change fish, bit for bit, and never reads volume()")
    heard = _Audio(vol=QUIET)
    on = asyncio.run(WB.run_arc("calm", "fish", ON, audio=heard))
    off = asyncio.run(WB.run_arc("calm", "fish", TAIL_ONLY,
                                 audio=_Audio(vol=QUIET)))
    check(not np.array_equal(on, off) and heard.reads > 0,
          "control: quiet_rest 1 hears the level and renders a different "
          "arc (the identity is not vacuous)")


# ── 2. between two songs ────────────────────────────────────────────────
def timeline():
    """Per frame (volume, lows, beat, heard) — Contra's outro, GAP_S with no
    audio callback at all, then Dopamine's opening — and the frames the
    outro ends and the opening starts on."""
    cv, cl, cb = load_song("contra")
    dv, dl, db = load_song("dopamine")
    feed = [(v, lo, b, True) for v, lo, b in zip(cv, cl, cb)]
    feed += [(0.0, 0.0, False, False)] * int(GAP_S * FPS)
    opening = len(feed)
    feed += [(v, lo, b, True) for v, lo, b in zip(dv, dl, db)]
    return feed, cv.size, opening


async def _between(extra, seed):
    feed, end, opening = timeline()
    r = await Crystal.open(extra, seed=seed)
    rows = []
    try:
        for vol, lows, beat, heard in feed:
            r.frame(vol, lows, beat, heard)
            rows.append((r.speed(), float(r.fish._rest_level), r.darts,
                         r.spike, r.past_edge()))
    finally:
        await r.close()
    return np.array(rows), end, opening


def section_between_songs():
    print(f"\n2  BETWEEN TWO SONGS — Contra's outro and fade, {GAP_S:g} s "
          "with no audio, Dopamine's opening; his music Fish on his crystal")
    runs = {}
    for label, extra in (("today", TODAY), ("tail drive", TAIL_ONLY),
                         ("rest, no tail drive", REST_ONLY),
                         ("tail drive + rest", ON)):
        runs[label] = [asyncio.run(_between(extra, seed)) for seed in SEEDS]
    rows, end, opening = runs["tail drive + rest"][0]
    # the next song's first hit: the first frame of its opening whose own
    # spike (the tracker's share removed by the rest) lunges
    hit = _first(rows[:, 3] >= FX.LUNGE_SPIKE_MIN, opening)
    print(f"   the outro ends at {end / FPS:.1f} s, the opening starts at "
          f"{opening / FPS:.1f} s, its first hit "
          f"{(hit - opening) / FPS:.2f} s in")
    settle = int(SETTLE_S * FPS)
    before_fade = end - int(3.0 * FPS)
    gap0 = end + int(1.0 * FPS)
    outro, darted = {}, []
    for label, seeds in runs.items():
        for seed, (rows, _e, _o) in zip(SEEDS, seeds):
            sp = rows[:, 0]
            gap = float(np.nanmean(sp[gap0:opening]))
            darts = int(rows[hit, 2]) if hit is not None else 0
            rise = _first(sp >= WAKE_SPEED_X, hit) if hit is not None else None
            wake_s = (rise - hit) / FPS if rise is not None else float("inf")
            peak = float(np.nanmax(sp[hit:hit + FPS]))
            outro[(label, seed)] = float(np.nanmean(sp[settle:before_fade]))
            print(f"   {label:>19}, seed {seed:>2}: outro "
                  f"{outro[(label, seed)]:.2f}x | end of fade + gap "
                  f"{gap:.2f}x (rest {np.mean(rows[gap0:opening, 1]):.2f}) "
                  f"| darts {darts} | {WAKE_SPEED_X:g}x cruise "
                  f"{wake_s:.2f} s after the hit, peak {peak:.1f}x")
            if label.startswith("rest") or label == "tail drive + rest":
                check(gap <= GAP_SPEED_MAX,
                      f"{label}, seed {seed}: the gap's mean speed "
                      f"{gap:.2f}x <= {GAP_SPEED_MAX}x cruise")
                check(wake_s <= WAKE_WITHIN_S,
                      f"{label}, seed {seed}: above {WAKE_SPEED_X:g}x "
                      f"cruise {wake_s:.2f} s after the next song's hit "
                      f"(<= {WAKE_WITHIN_S} s)")
            if label == "tail drive + rest":
                darted.append(darts)
                own = outro[("tail drive", seed)]
                check(abs(outro[(label, seed)] / own - 1.0) <= OUTRO_SHARE,
                      f"seed {seed}: the music before the fade is not "
                      f"slowed ({outro[(label, seed)]:.3f}x vs the tail "
                      f"drive alone {own:.3f}x, within "
                      f"{OUTRO_SHARE:.0%})")
    worst = max(float(np.max(rows[:, 4])) for seeds in runs.values()
                for rows, _e, _o in seeds)
    print(f"   the worst middle {worst:+.2f} px past the lit edge, every run "
          "(negative = inside)")
    check(worst <= 0.0, "no middle leaves the lit panel, resting or waking")
    # a dart is due a few seconds after the rest settles (section 3 pins the
    # clock), and this rest is only ~6 s long: count the three runs together
    check(sum(darted) >= DARTS_MIN,
          f"the resting shoal darts between the songs ({sum(darted)} darts "
          f"over the {len(SEEDS)} seeds, >= {DARTS_MIN})")
    return (hit - opening) / FPS


# ── 3. the darts ────────────────────────────────────────────────────────
async def _darts(seed=5, seconds=90.0):
    r = await Crystal.open(ON, seed=seed)
    eff = r.fish
    rows = []
    try:
        for _ in range(int(seconds * FPS)):
            r.frame(QUIET, 0.03)
            n = eff.n
            rows.append((
                n, eff.p_spd[:n] / eff.cruise_px, eff.p_hd[:n].copy(),
                eff.p_dart[:n].copy(), np.isfinite(eff.p_dhd[:n]),
                eff.p_x[:n] * eff.sx, eff.p_y[:n] * eff.sy, r.past_edge(),
            ))
        body = float(np.median(eff._body_len_px()))
    finally:
        await r.close()
    return rows, body


def section_darts():
    every = FX.Fish2d.schema()({})["dart_every_s"]
    print("\n3  THE DARTS — 90 s of deep quiet: each resting fish's own dart "
          f"clock (mean {every:g} s, never sooner than {FX.DART_MIN_S:g} s)")
    rows, body = asyncio.run(_darts())
    n = rows[0][0]
    check(all(row[0] == n for row in rows),
          f"the shoal holds its {n} fish (so a fish keeps its index)")
    speed = np.array([row[1] for row in rows])
    hd = np.unwrap(np.array([row[2] for row in rows]), axis=0)
    dart = np.array([row[3] for row in rows])
    flying = np.array([row[4] for row in rows])
    x, y = np.array([row[5] for row in rows]), np.array([row[6] for row in rows])
    # a dart begins where its clock turns positive (it counts down through
    # the push, below 0 through the glide, and back to 0 when it lets go)
    start = np.zeros_like(dart, dtype=bool)
    start[1:] = (dart[1:] > 0.0) & (dart[1:] > dart[:-1] + 1e-6)
    start[0] = dart[0] > 0.0
    gaps, pushes, peaks, paths, turns = [], [], [], [], []
    for i in range(n):
        at = np.flatnonzero(start[:, i])
        gaps += list(np.diff(at) / FPS)
        for a in at:
            push = _first(dart[:, i] <= 0.0, a)
            gone = _first(~flying[:, i], a)
            push = push if push is not None else dart.shape[0] - 1
            gone = gone if gone is not None else dart.shape[0] - 1
            pushes.append((push - a) / FPS)
            peaks.append(float(speed[a:gone + 1, i].max()))
            paths.append(float(np.hypot(np.diff(x[a:gone + 1, i]),
                                        np.diff(y[a:gone + 1, i])).sum())
                         / body)
            turns.append(abs(float(hd[gone, i] - hd[a, i])))
    expect = FX.DART_MIN_S + max(every - FX.DART_MIN_S, 0.1)
    rest = speed[int(10 * FPS):][~flying[int(10 * FPS):]]
    mean_gap = float(np.mean(gaps)) if gaps else float("inf")
    lo, hi = (np.degrees(v) for v in FX.DART_TURN)
    print(f"   {int(start.sum())} darts: every {mean_gap:.1f} s on average "
          f"per fish (shortest {min(gaps, default=0.0):.1f} s) | a "
          f"{np.median(pushes):.2f} s push to {np.median(peaks):.2f}x "
          f"cruise, {np.median(paths):.2f} body lengths, turning "
          f"{np.degrees(np.median(turns)):.0f} deg (aimed {lo:.0f}-{hi:.0f};"
          f" the turn radius caps the turn by the path swum) | between "
          f"darts {np.median(rest):.2f}x (median)")
    check(abs(mean_gap / expect - 1.0) <= 0.3,
          f"a fish darts every {mean_gap:.1f} s on average (the clock's "
          f"{expect:g} s, within 30%)")
    check(min(gaps, default=0.0) >= FX.DART_MIN_S - 1.5 / FPS,
          f"never sooner than {FX.DART_MIN_S:g} s after its last")
    check(max(pushes, default=1.0) <= FX.DART_S * 1.4 + 2.0 / FPS,
          f"a dart is short (its push at most {max(pushes, default=0):.2f} "
          "s)")
    check(float(np.median(peaks)) >= 0.5 and float(np.median(paths)) >= 0.5,
          f"a dart moves the fish (median {np.median(peaks):.2f}x cruise, "
          f"{np.median(paths):.2f} body lengths)")
    check(float(np.degrees(np.median(turns))) >= 20.0,
          f"a dart turns the fish ({np.degrees(np.median(turns)):.0f} deg, "
          "median, >= 20)")
    check(float(np.median(rest)) <= 0.15,
          f"between darts it rests ({np.median(rest):.2f}x cruise, median)")
    worst = max(row[7] for row in rows)
    check(worst <= 0.0, f"no dart takes a middle past the lit edge (worst "
          f"{worst:+.2f} px)")


# ── 4. the moments keep their strength at rest ──────────────────────────
def _old_rule(eff):
    """The red control: rest the WHOLE target, a moment's share included
    (what the rest would do if it ran before the flee and the burst)."""
    own = eff._pond_rest_step

    def whole(n, dt, eligible, ordinary, target, *a):
        return own(n, dt, eligible, target, target, *a)
    eff._pond_rest_step = whole


async def _burst(extra, old=False, seed=5):
    r = await Crystal.open(extra, seed=seed)
    eff = r.fish
    if old:
        _old_rule(eff)
    try:
        for _ in range(int(8 * FPS)):                 # it comes to rest
            r.frame(QUIET, 0.03)
        rest = float(eff._rest_level)
        sel = np.flatnonzero(eff.p_mode[:eff.n] < 2)
        px, py = eff.p_x[sel] * eff.sx, eff.p_y[sel] * eff.sy
        dash, peak = np.zeros(sel.size), 0.0
        for i in range(int(0.8 * FPS)):               # the 300 ms flare
            if i == 0:
                eff.update_config({"swim_burst": True})
            if i == int(0.3 * FPS):
                eff.update_config({"swim_burst": False})
            r.frame(QUIET, 0.03)
            nx, ny = eff.p_x[sel] * eff.sx, eff.p_y[sel] * eff.sy
            if i < int(0.3 * FPS):
                dash += np.hypot(nx - px, ny - py)
            px, py = nx, ny
            peak = max(peak, r.speed())
        return rest, float(dash.mean()) / eff.cruise_px, peak
    finally:
        await r.close()


async def _big_fish(extra, intensity, seed, old=False):
    r = await Crystal.open(dict(extra, gradient=BA.RED, ripple_amount=0.0),
                           seed=seed)
    eff = r.fish
    if old:
        _old_rule(eff)
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    middles = 0
    try:
        for _ in range(int(8 * FPS)):                 # it comes to rest
            r.frame(QUIET, 0.03)
        rest = float(eff._rest_level)
        eff.update_config({"big_fish": max(intensity,
                                           FX.BIG_FISH_POKE_FLOOR)})
        for i in range(int(14 * FPS)):
            r.frame(QUIET, 0.03)
            if not eff._big:
                if i > 5:
                    break
                continue
            # check_fish_big_fish_avoid's own measure: an ordinary fish's
            # middle on the big fish's body, in the panel's middle columns
            big = BA.big_body(eff) >= BA.OVERLAP_BIG * 255.0
            sel = np.flatnonzero(eff.p_mode[:eff.n] < 2)
            x = eff.cx + eff.p_x[sel] * eff.sx - eff.cam_px
            y = eff.cy + eff.p_y[sel] * eff.sy - eff.cam_py
            xi, yi = np.round(x).astype(int), np.round(y).astype(int)
            on = (xi >= 0) & (xi < W.COLS) & (yi >= 0) & (yi < W.ROWS)
            for a, b in zip(xi[on], yi[on]):
                if (real[b, a] and big[b, a]
                        and BA.MID_COLS[0] <= a < BA.MID_COLS[1]):
                    middles += 1
    finally:
        await r.close()
    return rest, middles


def section_moments_at_rest():
    print("\n4  THE MOMENTS KEEP THEIR STRENGTH AT REST — a swim burst and a "
          "big fish, fired at full rest (red control: the whole target "
          "rested, the moment's share too)")
    awake = asyncio.run(_burst(TAIL_ONLY))
    rested = asyncio.run(_burst(ON))
    old = asyncio.run(_burst(ON, old=True))
    for label, (rest, dash, peak) in (("awake", awake), ("at rest", rested),
                                      ("old rule", old)):
        print(f"   swim burst, {label:>8}: rest {rest:.2f} | the 300 ms dash "
              f"{dash:.2f} cruise-seconds, peak {peak:.2f}x cruise")
    check(rested[0] >= AT_REST and rested[2] >= WAKE_SPEED_X
          and rested[1] >= 0.5 * awake[1],
          f"a swim burst at rest still dashes ({rested[1]:.2f} of the "
          f"awake {awake[1]:.2f} cruise-seconds, peak {rested[2]:.2f}x)")
    check(old[1] < 0.2 * awake[1], "control: resting the burst's share "
          f"too loses the dash ({old[1]:.2f} cruise-seconds)")
    for intensity in (0.2, 0.8):
        runs = {label: [asyncio.run(_big_fish(ON, intensity, seed, old))
                        for seed in BA.SEEDS]
                for label, old in (("at rest", False), ("old rule", True))}
        new = sum(m for _r, m in runs["at rest"])
        was = sum(m for _r, m in runs["old rule"])
        rest = min(r for r, _m in runs["at rest"])
        print(f"   big fish {intensity}: a resting fish's middle on it "
              f"mid-panel {new} frames (old rule {was}), over "
              f"{len(BA.SEEDS)} seeds, rest at least {rest:.2f}")
        check(rest >= AT_REST and new == 0,
              f"big fish {intensity}: a resting fish still gets out of its "
              "way (check_fish_big_fish_avoid's own bar)")
        check(was > 0, f"control: big fish {intensity} catches resting "
              "fish under the old rule")


# ── 5. a drumless quiet passage ─────────────────────────────────────────
async def _drumless(extra, seed=5):
    r = await Crystal.open(extra, seed=seed)
    ticks, tick_lunges, rows = [], 0, []
    onset_lunge = False
    try:
        for _ in range(int(6 * FPS)):                 # it comes to rest
            r.frame(QUIET, 0.03)
            rows.append((r.speed(), float(r.fish._rest_level)))
        t0 = len(rows)
        for i in range(int(8 * FPS)):                 # 120 bpm, no onset
            tick = i % 30 == 0
            r.frame(QUIET, 0.03, beat=tick)
            rows.append((r.speed(), float(r.fish._rest_level)))
            if tick:
                ticks.append(len(rows) - 1)
                tick_lunges += int(r.lunged())
        onset = len(rows)
        for k in range(3):                            # one real hit
            r.frame(LOUD, 0.95, beat=(k == 0))
            onset_lunge = onset_lunge or r.lunged()
            rows.append((r.speed(), float(r.fish._rest_level)))
        for _ in range(int(2 * FPS)):
            r.frame(QUIET, 0.03)
            rows.append((r.speed(), float(r.fish._rest_level)))
    finally:
        await r.close()
    return np.array(rows), t0, onset, len(ticks), tick_lunges, onset_lunge


def section_drumless():
    print("\n5  A DRUMLESS QUIET PASSAGE — the tracker ticks at 120 bpm "
          f"with no onset under them (volume() {QUIET}), then one real hit")
    for label, extra in (("tail drive + rest", ON),
                         ("tail drive, no rest", TAIL_ONLY)):
        rows, t0, onset, n_ticks, lunges, hit_lunge = asyncio.run(
            _drumless(extra))
        rest = float(np.mean(rows[t0:onset, 1]))
        speed = float(np.nanmean(rows[t0:onset, 0]))
        rise = _first(rows[:, 0] >= WAKE_SPEED_X, onset)
        wake_s = (rise - onset) / FPS if rise is not None else float("inf")
        print(f"   {label:>19}: {lunges} of {n_ticks} ticks lunged, mean "
              f"speed {speed:.2f}x (rest {rest:.2f}) | the hit lunged: "
              f"{hit_lunge}, {WAKE_SPEED_X:g}x cruise {wake_s:.2f} s after")
        if extra is ON:
            check(rest >= AT_REST, f"the shoal was at rest through the "
                  f"ticks (rest {rest:.2f} >= {AT_REST})")
            check(lunges == 0, f"no tick lunged a resting fish ({lunges} "
                  f"of {n_ticks})")
            check(hit_lunge and wake_s <= WAKE_WITHIN_S,
                  f"the real hit lunged it, above {WAKE_SPEED_X:g}x cruise "
                  f"in {wake_s:.2f} s (<= {WAKE_WITHIN_S} s)")
        else:
            check(lunges >= n_ticks - 1, f"control: at quiet_rest 0 the "
                  f"same ticks lunge ({lunges} of {n_ticks})")


# ── 6. never during a moment ────────────────────────────────────────────
MOMENT_KINDS = ("charge", "lull", "drop", "school", "rush", "crossfade")


def _moment(r):
    eff = r.fish
    n = eff.n
    kinds = set()
    if eff._phase != "none":
        kinds.add(eff._phase)
    if eff._school_on:
        kinds.add("school")
    if bool((eff.p_mode[:n] == 3).any()):
        kinds.add("rush")
    if (particle_handoff.transition_progress(r.virtual) is not None
            or getattr(eff, "_transition_program", None) is not None):
        kinds.add("crossfade")
    return kinds


async def _moments(seed=5):
    r = await Crystal.open(ON, seed=seed)
    rows, marks = [], {}
    eff = r.fish

    def step(beat=False):
        d0 = r.darts
        r.frame(QUIET, 0.05, beat=beat)
        n = eff.n
        rows.append((_moment(r), float(eff._rest_level),
                     bool(n) and bool((eff.p_dart[:n] > 0.0).any()),
                     r.darts - d0))

    def ramp(phase, seconds, beats_every=None, **arm):
        eff.update_config({"phase": phase, "phase_progress": 0.0, **arm})
        frames = max(int(seconds * FPS), 1)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            step(beat=bool(beats_every) and i % beats_every == 0)

    try:
        for _ in range(int(8 * FPS)):                 # it comes to rest
            step()
        marks["before"] = len(rows) - 1
        ramp("charge", 4.0, beats_every=12)
        ramp("lull", 3.0)
        ramp("drop", 0.4, drop_shock_on=False, drop_intensity=0.9)
        for _ in range(int(10 * FPS)):                # until it settles
            if eff._phase == "none":
                break
            step()
        for _ in range(int(6 * FPS)):                 # the rest comes back
            step()
        marks["after"] = len(rows) - 1
        # an outgoing crossfade into an effect with no blobs (his
        # crystal-mapper's Add, 0.5 s): every fish scatters
        v = r.virtual
        headless.attach_effect(r.host, v, "singleColor",
                               {"color": "#000000", "brightness": 0.0})
        v._transition_effect = eff
        v._config["transition_mode"] = "Add"
        v.frame_transitions = v.transitions["Add"]
        v.transition_frame_total = int(round(v.refresh_rate * 0.5))
        v.transition_frame_counter = 0
        while v._transition_effect is eff and len(rows) < 60 * FPS:
            step()
    finally:
        await r.close()
    return rows, marks


def section_moments():
    print("\n6  NEVER DURING A MOMENT — deep quiet throughout: a charge, a "
          "lull, a drop and its rush, then an outgoing crossfade")
    rows, marks = asyncio.run(_moments())
    held = [row for row in rows if row[0]]
    counts = {k: sum(1 for row in held if k in row[0]) for k in MOMENT_KINDS}
    worst = max((row[1] for row in held), default=0.0)
    darting = sum(1 for row in held if row[2] or row[3])
    before, after = rows[marks["before"]][1], rows[marks["after"]][1]
    print("   frames: " + ", ".join(f"{k} {v}" for k, v in counts.items())
          + f" | rest before {before:.2f}, after the drop {after:.2f}")
    check(all(counts[k] > 0 for k in MOMENT_KINDS),
          "every kind of moment was reached (the check is not vacuous)")
    check(before >= AT_REST and after >= AT_REST,
          f"the shoal was at rest before and again after (>= {AT_REST})")
    check(worst == 0.0, f"the rest level is 0 on every moment frame "
          f"(worst {worst:.3f})")
    check(darting == 0, f"no fish darts during a moment ({darting} frames)")


# ── 7. an audio pause ───────────────────────────────────────────────────
async def _pause(extra, never_heard=False, seed=5):
    r = await Crystal.open(extra, seed=seed)
    rows = []
    try:
        if never_heard:
            for _ in range(int(10 * FPS)):
                r.frame(heard=False)
                rows.append((r.speed(), float(r.fish._rest_level)))
            return np.array(rows), None, None
        for _ in range(int(5 * FPS)):                 # the music plays
            r.frame(LOUD, 0.1)
            rows.append((r.speed(), float(r.fish._rest_level)))
        stop = len(rows)
        for _ in range(int(8 * FPS)):                 # the hub pauses
            r.frame(heard=False)
            rows.append((r.speed(), float(r.fish._rest_level)))
        back = len(rows)
        for _ in range(int(2 * FPS)):                 # the music comes back
            r.frame(LOUD, 0.1)
            rows.append((r.speed(), float(r.fish._rest_level)))
    finally:
        await r.close()
    return np.array(rows), stop, back


def section_pause():
    print(f"\n7  AN AUDIO PAUSE — no audio callback for 8 s (silence after "
          f"{FX.REST_SILENCE_S:g} s), then the music again")
    for label, extra in (("tail drive + rest", ON),
                         ("tail drive, no rest", TAIL_ONLY)):
        rows, stop, back = asyncio.run(_pause(extra))
        late = slice(back - 2 * FPS, back)
        rest = float(np.mean(rows[late, 1]))
        speed = float(np.nanmean(rows[late, 0]))
        playing = float(np.nanmean(rows[stop - 2 * FPS:stop, 0]))
        woke = _first(rows[:, 1] < 0.05, back)
        woke_s = (woke - back) / FPS if woke is not None else float("inf")
        print(f"   {label:>19}: playing {playing:.2f}x | the pause's last "
              f"2 s {speed:.2f}x (rest {rest:.2f}) | rest under 0.05 "
              f"{woke_s:.2f} s after the music returns")
        if extra is ON:
            check(rest >= AT_REST and speed <= GAP_SPEED_MAX,
                  f"the pause rests the shoal (rest {rest:.2f}, "
                  f"{speed:.2f}x cruise)")
            check(woke_s <= 1.0, f"the music back wakes it in {woke_s:.2f} "
                  "s (<= 1 s, with no hit to startle it)")
        else:
            check(speed >= 0.8, f"control: at quiet_rest 0 the pause "
                  f"changes nothing ({speed:.2f}x cruise)")
    rows, _s, _b = asyncio.run(_pause(ON, never_heard=True))
    worst = float(np.max(rows[:, 1]))
    speed = float(np.nanmean(rows[-2 * FPS:, 0]))
    print(f"   never heard anything: rest at most {worst:.2f}, "
          f"{speed:.2f}x cruise")
    check(worst == 0.0, "an effect that has never heard anything does not "
          "rest")


# ── 8. his library ──────────────────────────────────────────────────────
def _rest_levels(vol, calm, full):
    state = (float(vol[0]), float(vol[0]), 0.0)
    out = np.empty(vol.size)
    for i, v in enumerate(vol.tolist()):
        state = FX.rest_step(state, v, DT, calm, full)
        out[i] = state[2]
    return out


def section_library():
    defaults = FX.Fish2d.schema()({})
    calm, full = defaults["rest_calm_level"], defaults["rest_full_level"]
    songs = load_library()
    print(f"\n8  HIS LIBRARY — the detector over {len(songs)} of his "
          f"captured songs ({sum(v.size for _s, v in songs) / FPS / 3600:.1f}"
          " h)")
    # the library's volume against the real pipeline's own reading
    cv, _cl, _cb = load_song("contra")
    own = dict(songs).get(SONGS["contra"]["stem"])
    if own is None:
        check(False, "Contra is in the library fixture (the cross-check)")
    else:
        i0 = int(SONGS["contra"]["from_s"] * FPS)
        diffs = []
        for shift in range(-5, 6):
            seg = own[i0 + shift:i0 + shift + cv.size]
            if seg.size == cv.size:
                diffs.append(float(np.mean(np.abs(seg - np.clip(cv, 0, 1)))))
        diff = min(diffs)
        print(f"   volume() computed from the WAV against the pipeline's "
              f"own on Contra's outro: mean |diff| {diff:.4f}")
        check(diff <= PIPELINE_DIFF_MAX, f"the library's volume is the "
              f"pipeline's (mean |diff| {diff:.4f} <= {PIPELINE_DIFF_MAX})")
    edge = int(EDGE_S * FPS)
    for c, f in ((0.70, 0.58), (calm, full), (0.62, 0.48)):
        total = rest = part = 0
        mid_songs = []
        for stem, vol in songs:
            lv = _rest_levels(vol, c, f)
            total += lv.size
            rest += int(np.count_nonzero(lv > AT_REST))
            part += int(np.count_nonzero((lv > 0.2) & (lv <= AT_REST)))
            if lv.size > 2 * edge and (lv[edge:-edge] > AT_REST).any():
                mid_songs.append(stem)
        rest_pct = 100.0 * rest / total
        mid_pct = 100.0 * len(mid_songs) / len(songs)
        tag = " (the default)" if (c, f) == (calm, full) else ""
        print(f"   calm {c:.2f} / full {f:.2f}{tag}: at rest {rest_pct:.2f}% "
              f"of song time, partly calmed {100.0 * part / total:.2f}% | a "
              f"rest inside the music in {len(mid_songs)} song(s) "
              f"({mid_pct:.1f}%)")
        if (c, f) == (calm, full):
            for stem in mid_songs:
                print(f"      inside the music: {stem}")
            check(rest_pct <= LIBRARY_REST_MAX, f"at rest {rest_pct:.2f}% "
                  f"of song time (<= {LIBRARY_REST_MAX}%)")
            check(mid_pct <= LIBRARY_MID_MAX, f"a rest inside the music in "
                  f"{mid_pct:.1f}% of songs (<= {LIBRARY_MID_MAX}%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-fixtures", action="store_true")
    ap.add_argument("--record", choices=sorted(SONGS))
    ap.add_argument("--library", action="store_true",
                    help="record only the library fixture")
    ap.add_argument("--shapes-dir", default=WB.LIVE_SHAPES)
    args = ap.parse_args()
    if args.record:
        record_song(args.record, args.shapes_dir)
        return 0
    if args.library:
        record_library(args.shapes_dir)
        return 0
    if args.write_fixtures:
        write_fixtures(args.shapes_dir)
        return 0
    with np.errstate(invalid="ignore", divide="ignore"):
        section_identity()
        hit = section_between_songs()
        section_darts()
        section_moments_at_rest()
        section_drumless()
        section_moments()
        section_pause()
        section_library()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} POND REST CHECK(S) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"ALL POND REST CHECKS PASS (the next song's hit at {hit:.2f} s "
          "into its opening)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
