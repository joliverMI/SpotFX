"""Measure the FISH WAKE's colour and blend: his 2026-10-26 white wash-out
report and the fix he approved, in numbers (data/fish-swim-plan/report.md,
part 1 and PR 1).

His report: "address why the fish scene gains a lot of white color,
especially in rainbow effects when there is a lot going on. My guess is
that the trails/ripples overlap and add to white. Perhaps add options to
mix differently." His answer to the plan: "I approve option A for the
wake": the wake in the fish's own colour (`wake_hue = own`), lightened onto
the bodies (`wake_blend = lighten`), both the new defaults.

Two arcs on his crystal's REAL 976 cells (fx.headless with the device
profile's mask), through the real vendored pipeline, driven per frame by
his real audio: the fish's own two inputs (its lows power and the beat
tracker), recorded through HubMelbankSource from his captured WAVs into
tests/fixtures/fish_wake/ (`--write-fixtures` re-records them, one song per
interpreter, which is the only way the analysis reproduces itself):

  BUSY  his Fish at its 0.35-0.7 flare state (4 fish, blob 2.5) on the
        default rainbow, Contra 66-88 s: a charge, a lull, a drop, a big
        fish and a swim burst. Seed 7.
  CALM  his Fish (3 fish, blob 2.5) on the rainbow, Let It Be 80-102 s.

  1. TODAY IS ONE SETTING AWAY: `wake_hue = opposite, wake_blend = add`
     renders both arcs exactly like the pinned pre-change module, every
     frame, every channel.
  2. LESS WHITE, the plan's acceptance bars: white light (each lit cell's
     dimmest channel over its brightest, summed over the cells — the share
     of the light that is white rather than coloured) and near-white cells
     in the drop's swirl (p90), measured exactly as the plan measured them.
  3. THE WAKE IS STILL THERE: lit cells against today's.
  4. COST: the final mix's own time per frame, lighten against add, on the
     busy arc's real layers.

Read-only, offline. No live access.

    .venv/bin/python scripts/check_fish_wake_blend.py
    .venv/bin/python scripts/check_fish_wake_blend.py --write-fixtures \
        [--shapes-dir /home/javi/SpotFX/storage/audio_shapes]
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_fish_wall as W  # noqa: E402
from fx import headless  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72
REAL = W.crystal_real_mask()
FIXTURES = REPO / "tests" / "fixtures" / "fish_wake"
LIVE_SHAPES = "/home/javi/SpotFX/storage/audio_shapes"

# This PR's merge-base: the fish exactly as it was before the wake settings
# existed. PINNED, never a moving ref (tests/test_fish_camera.py records how
# a moving ref once retired a proof into a silent skip).
WAKE_BASELINE_REF = "e302f05c57479fc65282f0383e98e81c51ca7391"
TODAY = {"wake_hue": "opposite", "wake_blend": "add"}

# the plan's acceptance list (PR 1)
BUSY_WHITE_MAX = 14.0           # % of the light; today 27.6
BUSY_DROP_NEAR_WHITE_P90_MAX = 6  # cells; today 30
LIT_SHARE_MIN = 0.85            # of today's lit cells
CALM_WHITE_MAX = 10.0           # %; today 26.5
COST_MAX_MS = 0.2               # extra per frame, lighten over add

DARK = {"background_color": "#000000", "background_brightness": 0.0}
ARCS = {
    "busy": {
        "stem": "Pixel Terror, Sara Skinner - Contra",
        "t0_s": 66.0,
        "cfg": dict(W.MUSIC_FISH, particle_count=4, blob_size=2.5, **DARK),
        "phases": [(5.0, "charge", 4.0), (9.0, "lull", 2.0),
                   (11.0, "drop", 0.4)],
        "pokes": [(16.5, {"big_fish": 0.9}), (17.5, {"swim_burst": True}),
                  (17.8, {"swim_burst": False})],
        "drop_window_s": (10.6, 14.6),
    },
    "calm": {
        "stem": "The Beatles - Let It Be - Remastered 2009",
        "t0_s": 80.0,
        "cfg": dict(W.MUSIC_FISH, **DARK),
        "phases": [],
        "pokes": [],
        "drop_window_s": None,
    },
}
SECONDS = 22.0
SEED = 7


# ── the fixtures: the fish's own audio inputs, per frame ────────────────
async def _record(stem, shapes_dir, volume=False):
    """The WHOLE WAV through the real analysis (HubMelbankSource: resampler,
    phase vocoder, melbank with its auto-gain, aubio's tempo tracker),
    reading per accepted 60 fps frame exactly what the fish reads: its lows
    power and `bpm_beat_now()`, each once (the tempo tracker is stateful,
    so a second read would be a second frame of audio), and with `volume`
    the absolute `volume()` the pond rest hears (a plain read). Returns
    (lows, beats) or (lows, beats, volumes)."""
    import soundfile as sf

    from fx.audio_ingest import HubMelbankSource

    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(str(Path(td) / "fx"))
    lows, beats, vols = [], [], []
    try:
        src = HubMelbankSource(host)

        def cb():
            lows.append(src.lows_power())
            beats.append(bool(src.bpm_beat_now()))
            if volume:
                vols.append(src.volume())

        src.subscribe(cb)
        pcm, sr = sf.read(os.path.join(shapes_dir, stem + ".wav"),
                          dtype="float32", always_2d=False)
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1)
        if sr != 44100:
            raise SystemExit(f"{stem}: expected 44100 Hz, got {sr}")
        for s in range(0, len(pcm), 512):
            src.ingest(pcm[s:s + 512])
    finally:
        await host.shutdown()
    out = (np.array(lows, dtype=np.float32), np.array(beats, dtype=bool))
    if volume:
        out += (np.array(vols, dtype=np.float32),)
    return out


def record_one(arc, shapes_dir):
    spec = ARCS[arc]
    lows, beats = asyncio.run(_record(spec["stem"], shapes_dir))
    i0 = int(spec["t0_s"] * 60)
    n = int(SECONDS * 60)
    if lows.size < i0 + n:
        raise SystemExit(f"{spec['stem']}: only {lows.size} frames")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"{arc}.npz"
    np.savez_compressed(
        path, lows=lows[i0:i0 + n], beat=beats[i0:i0 + n],
        stem=np.array(spec["stem"]), t0_s=np.array(spec["t0_s"]),
    )
    print(f"wrote {path.relative_to(REPO)}: {spec['stem']} "
          f"{spec['t0_s']:.0f}-{spec['t0_s'] + SECONDS:.0f} s, "
          f"{int(beats[i0:i0 + n].sum())} beats")


def write_fixtures(shapes_dir):
    # one song per interpreter: the analysis carries process-wide state, and
    # a song analysed after another was measured not to reproduce itself
    for arc in ARCS:
        subprocess.run(
            [sys.executable, __file__, "--record", arc,
             "--shapes-dir", shapes_dir],
            cwd=REPO, check=True,
        )


def load_fixture(arc):
    path = FIXTURES / f"{arc}.npz"
    with np.load(path, allow_pickle=False) as d:
        return d["lows"], d["beat"]


# ── the pinned pre-change module, registered beside the current fish ────
def load_baseline(name="fish_wake_pinned"):
    """Register WAKE_BASELINE_REF's fish.py as a second effect type: an
    Effect subclass registers under its module's last name segment, so
    `attach_effect(..., name, ...)` reaches it beside `fish`."""
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(
            ["git", "show", f"{WAKE_BASELINE_REF}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except Exception as exc:                        # noqa: BLE001
        # a genuinely missing input (a shallow clone): named, never a pass
        raise SystemExit(
            f"cannot read {WAKE_BASELINE_REF}:fx/effects/fish.py out of "
            f"git: {exc}"
        )
    # the pin must be the fish just before this change: it carries the big
    # fish (so the busy arc means the same thing on both sides) and not the
    # wake settings. Either failing means the pin slipped: say so loudly.
    if "_big_fish_layer" not in src or "wake_blend" in src:
        raise SystemExit(
            f"WAKE_BASELINE_REF {WAKE_BASELINE_REF} is not the fish just "
            "before the wake settings"
        )
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


# ── one arc ─────────────────────────────────────────────────────────────
class _Audio:
    """What the fish reads from the audio source, set per frame."""
    def __init__(self):
        self.lows = 0.0
        self.beat = False

    def lows_power(self, filtered=True):
        return self.lows

    def bpm_beat_now(self):
        return self.beat


_RUN = [0]


async def run_arc(arc, effect_type="fish", extra=None, on_attach=None,
                  spy=None, audio=None):
    """Render one arc; return the assembled frames (n, 2664, 3) float32.
    `on_attach(effect)` runs once it exists, `spy(effect)` just before the
    room closes. `audio` replaces the audio stub (its lows and beat are set
    per frame; anything else it answers is its own)."""
    spec = ARCS[arc]
    lows, beats = load_fixture(arc)
    _RUN[0] += 1
    # a UNIQUE device id per run: particle_handoff keeps its snapshot keyed
    # by device, and a reused name would hand one run's fish to the next
    dev = f"fish-wake-blend-{arc}-{_RUN[0]}"
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / dev), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=dev, real_mask=REAL,
    )
    virtual = host.virtuals.get(dev)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    try:
        eff = headless.attach_effect(
            host, virtual, effect_type, dict(spec["cfg"], **(extra or {}))
        )
        eff._rng = np.random.default_rng(SEED)
        if on_attach is not None:
            on_attach(eff)
        audio = audio if audio is not None else _Audio()
        sched = {int(t * 60): (ph, dur) for t, ph, dur in spec["phases"]}
        pokes = {int(t * 60): p for t, p in spec["pokes"]}
        ramp = None
        frames = []
        for i in range(lows.size):
            audio.lows, audio.beat = float(lows[i]), bool(beats[i])
            if i in sched:
                ph, dur = sched[i]
                arm = {"phase": ph, "phase_progress": 0.0}
                if ph == "drop":
                    arm.update({"drop_shock_on": False,
                                "drop_intensity": 0.9})
                eff.update_config(arm)
                ramp = (i, int(dur * 60))
            elif ramp is not None and i - ramp[0] <= ramp[1]:
                eff.update_config(
                    {"phase_progress": min((i - ramp[0]) / ramp[1], 1.0)}
                )
            if i in pokes:
                eff.update_config(pokes[i])
            clock.advance(DT)
            eff.audio_data_updated(audio)
            frame = virtual.assemble_frame()
            virtual.flush(frame)
            frames.append(np.array(frame, dtype=np.float32).reshape(-1, 3))
        if spy is not None:
            spy(eff)
    finally:
        cm.__exit__(None, None, None)
        await host.shutdown()
    return np.array(frames)


# ── the measures, exactly as the plan's rig took them ───────────────────
def _light(frame):
    """(white light share, near-white cells) over the real cells, on the
    frame as the device receives it (uint8)."""
    px = frame.astype(np.uint8).astype(np.float32)[REAL]
    mx = px.max(axis=1)
    mn = px.min(axis=1)
    lit = mx >= 12.0
    tot = mx[lit].sum()
    sat = np.where(mx > 0, 1.0 - mn / np.maximum(mx, 1e-6), 0.0)
    white = float(mn[lit].sum() / tot) if tot else 0.0
    near_white = int((lit & (sat < 0.35) & (mx > 140)).sum())
    return white, near_white


def measure(arc, frames):
    out = {
        "white": 100.0 * float(np.mean([_light(f)[0] for f in frames[::3]])),
        "lit": float(np.mean([(f[REAL].max(axis=1) >= 40.0).sum()
                              for f in frames])),
    }
    window = ARCS[arc]["drop_window_s"]
    if window is not None:
        a, b = (int(t * 60) for t in window)
        out["drop_near_white_p90"] = float(np.percentile(
            [_light(f)[1] for f in frames[a:b]], 90
        ))
    return out


def _fmt(m):
    s = f"white light {m['white']:5.1f}%   lit cells {m['lit']:6.1f}"
    if "drop_near_white_p90" in m:
        s += f"   near-white in the drop (p90) {m['drop_near_white_p90']:4.0f}"
    return s


# ── 1 + 2 + 3 ───────────────────────────────────────────────────────────
def section_arcs():
    print("\n1  TODAY, ONE SETTING AWAY — opposite + add against the pinned "
          f"pre-change module ({WAKE_BASELINE_REF[:8]})")
    pinned = load_baseline()
    problems = []
    results = {}
    for arc in ARCS:
        old = asyncio.run(run_arc(arc, pinned))
        today = asyncio.run(run_arc(arc, "fish", TODAY))
        same = old.shape == today.shape and np.array_equal(old, today)
        differ = int((old != today).any(axis=(1, 2)).sum()) if (
            old.shape == today.shape) else -1
        print(f"   {arc}: {old.shape[0]} frames, frames that differ: "
              f"{differ}  -> {'IDENTICAL' if same else 'DIFFERENT'}")
        if not same:
            problems.append(f"{arc}: opposite + add is not today's render")
        new = asyncio.run(run_arc(arc))
        results[arc] = {"today": measure(arc, today),
                        "default": measure(arc, new)}

    print("\n2  LESS WHITE — the default (own colour + lighten) against today")
    for arc, r in results.items():
        print(f"   {arc} today    {_fmt(r['today'])}")
        print(f"   {arc} default  {_fmt(r['default'])}")
    busy, calm = results["busy"]["default"], results["calm"]["default"]
    if busy["white"] > BUSY_WHITE_MAX:
        problems.append(f"busy white light {busy['white']:.1f}% > "
                        f"{BUSY_WHITE_MAX}%")
    if busy["drop_near_white_p90"] > BUSY_DROP_NEAR_WHITE_P90_MAX:
        problems.append("busy near-white drop cells "
                        f"{busy['drop_near_white_p90']:.0f} > "
                        f"{BUSY_DROP_NEAR_WHITE_P90_MAX}")
    if calm["white"] > CALM_WHITE_MAX:
        problems.append(f"calm white light {calm['white']:.1f}% > "
                        f"{CALM_WHITE_MAX}%")

    print("\n3  THE WAKE IS STILL THERE — lit cells against today")
    for arc, r in results.items():
        share = r["default"]["lit"] / max(r["today"]["lit"], 1e-6)
        print(f"   {arc}: {share * 100:5.1f}% of today's lit cells "
              f"(bar {LIT_SHARE_MIN * 100:.0f}%)")
        if share < LIT_SHARE_MIN:
            problems.append(f"{arc}: the wake lost too much light "
                            f"({share * 100:.1f}% of today's lit cells)")
    return problems


# ── 4. cost ─────────────────────────────────────────────────────────────
def section_cost():
    print("\n4  COST — the final mix per frame, on the busy arc's real layers")
    captured, calls, times = [], [0], {}

    def keep_layers(eff):
        own = eff._composite

        def composite(body, wake, big):
            if calls[0] % 10 == 0:
                captured.append((
                    body.copy(),
                    None if wake is None else wake.copy(),
                    None if big is None else np.array(big, copy=True),
                ))
            calls[0] += 1
            return own(body, wake, big)
        eff._composite = composite

    def time_blends(eff):
        del eff._composite              # the class's own method again
        for blend in ("add", "lighten", "under"):
            eff.wake_blend = blend
            best = float("inf")
            for _ in range(7):
                t = time.perf_counter()
                for body, wake, big in captured:
                    eff._composite(body, wake, big)
                best = min(best, (time.perf_counter() - t) / len(captured))
            times[blend] = best * 1e3

    asyncio.run(run_arc("busy", on_attach=keep_layers, spy=time_blends))
    extra = times["lighten"] - times["add"]
    for blend, ms in times.items():
        print(f"   {blend:8s} {ms:6.3f} ms a frame ({len(captured)} frames)")
    print(f"   lighten over add: {extra:+.3f} ms (bar {COST_MAX_MS} ms)")
    if extra >= COST_MAX_MS:
        return [f"lighten costs {extra:.3f} ms a frame over add"]
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-fixtures", action="store_true")
    ap.add_argument("--shapes-dir", default=LIVE_SHAPES)
    ap.add_argument("--record", choices=sorted(ARCS), help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.record:
        record_one(args.record, args.shapes_dir)
        return
    if args.write_fixtures:
        write_fixtures(args.shapes_dir)
    print("FISH WAKE — colour and blend, his option A against today")
    print(f"({ROWS}x{COLS} crystal-mapper, {int(REAL.sum())} real cells, "
          f"seed {SEED}, {SECONDS:.0f} s arcs)")
    problems = section_arcs() + section_cost()
    if problems:
        print("\nFAILED:")
        for p in problems:
            print("   " + p)
        raise SystemExit(1)
    print("\nALL WAKE BLEND CHECKS PASS")


if __name__ == "__main__":
    main()
