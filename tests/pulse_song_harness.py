"""Drive the REAL Pulse effect over his captured songs, and measure what the
light does (single-led-power plan, phase 1).

Shared by two callers that must never measure different things:

- tests/test_pulse_effect.py drives the effect from the committed fixtures
  (tests/fixtures/pulse/<slug>.npz + .json) on every pytest run;
- scripts/check_pulse_effect.py runs the WHOLE pipeline from his captured
  WAVs (fx.headless host + fx.audio_ingest.HubMelbankSource, one-pixel copy
  virtual listening 20-1000 Hz — the Singles' real shape), writes those
  fixtures, and proves the fixture-driven run lands on the same light.

A FIXTURE IS THE EFFECT'S OWN AUDIO INPUT, not audio: per audio frame, the
lows power and the mean of the virtual's own melbank (the two inputs the
original "bass weighted"/"bass only" sources need), PLUS the beat/bass/
mids/high band powers the "kick and bass" default needs (2026-10-06 tuning
feedback — see fx/effects/pulse.py's module docstring), exactly as the real
pipeline handed them to the effect (plus whether that audio frame reached
the effect at all — the resampler swallows the priming chunk). The rest is
the song's stored analysis and his own authored marks, which stand in for
what the engine will push in phase 2: the section intensity (`energy`,
min-max normalised energy_rms x the song's scale, written at each section
start), the tempo (`beat_ms`), and charge/lull/drop on the engine's own rule
(a charge/lull ramps over 90% of the gap to the next authored response,
flat 4000/2500 ms when there is none; a drop ramps over 400 ms and begins on
its mark). Every time here is in the captured WAV's own frame.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(REPO, "tests", "fixtures", "pulse")
FPS = 60.0
DT = 1.0 / FPS
COLOUR = "#ffd37d"  # his Calm Singles colour; max channel 255, so max/255 = lin

# slug -> stem in storage/audio_shapes, and the intensity scale the plan used
# (Let It Be at half: the calm case).
SONGS = {
    "dopamine": dict(stem="Wooli, Tape B - Dopamine", scale=1.0),
    "contra": dict(stem="Pixel Terror, Sara Skinner - Contra", scale=1.0),
    "letitbe": dict(stem="The Beatles - Let It Be - Remastered 2009", scale=0.5),
    "soypeor": dict(stem="Bad Bunny - Soy Peor", scale=1.0),
}

PHASE_CLASSES = ("charge", "lull", "drop")
DROP_RAMP_S = 0.4
FLAT_RAMP_S = {"charge": 4.0, "lull": 2.5}


# ── building a song's meta from his live storage (read-only) ────────────────

def build_meta(stem: str, shapes_dir: str, triggers_path: str) -> tuple[dict, np.ndarray]:
    """The song's analysis + his authored responses, in WAV time. Returns
    (json-able meta, analysed onset times in seconds)."""
    with open(os.path.join(shapes_dir, stem + ".librosa.json")) as f:
        an = json.load(f)
    shape = np.load(os.path.join(shapes_dir, stem + ".npz"))
    wav_t0 = float(shape["timestamps_ms"][0])  # song time of WAV sample 0
    with open(triggers_path) as f:
        trig = json.load(f).get(an["spotify_uri"], [])
    trig = trig if isinstance(trig, list) else trig.get("triggers", [])
    events = sorted(
        (
            round((t["timestamp_ms"] - wav_t0) / 1000.0, 4),
            t["action"]["event_class"],
            float(t["action"].get("intensity") or 0.5),
        )
        for t in trig
        if t.get("action", {}).get("kind") == "fire_response"
        and t.get("source") == "authored"
    )
    secs = an["sections"]
    e = np.array([s["energy_rms"] for s in secs], dtype=float)
    lo, hi = float(e.min()), float(e.max())
    sections = [
        [s["start_ms"] / 1000.0, s["end_ms"] / 1000.0,
         round((s["energy_rms"] - lo) / max(1e-6, hi - lo), 5)]
        for s in secs
    ]
    onsets = sorted({
        round(o["ms"] / 1000.0, 3)
        for k in ("bass_onsets", "snare_onsets", "onsets")
        for o in an.get(k, [])
    })
    meta = dict(
        stem=stem,
        uri=an["spotify_uri"],
        tempo_bpm=float(an["tempo_bpm"]),
        wav_t0_ms=wav_t0,
        sections=sections,
        events=[list(ev) for ev in events],
    )
    return meta, np.asarray(onsets, dtype=np.float32)


def write_fixture(slug: str, meta: dict, onsets: np.ndarray, lows: np.ndarray,
                  bmean: np.ndarray, fired: np.ndarray, out_dir: str = FIXTURE_DIR,
                  beat: np.ndarray | None = None, bass: np.ndarray | None = None,
                  mids: np.ndarray | None = None, high: np.ndarray | None = None) -> None:
    os.makedirs(out_dir, exist_ok=True)
    arrays = dict(
        lows=lows.astype(np.float32),
        bmean=bmean.astype(np.float32),
        fired=fired.astype(bool),
        onsets=onsets.astype(np.float32),
    )
    # beat/bass/mids/high: the band powers "kick and bass" needs. Optional
    # for callers that only ever drive "bass weighted"/"bass only".
    for name, arr in (("beat", beat), ("bass", bass), ("mids", mids), ("high", high)):
        if arr is not None:
            arrays[name] = arr.astype(np.float32)
    np.savez_compressed(os.path.join(out_dir, slug + ".npz"), **arrays)
    with open(os.path.join(out_dir, slug + ".json"), "w") as f:
        json.dump(meta, f, indent=1)


def load_fixture(slug: str, fixture_dir: str = FIXTURE_DIR) -> tuple[dict, dict]:
    with open(os.path.join(fixture_dir, slug + ".json")) as f:
        meta = json.load(f)
    z = np.load(os.path.join(fixture_dir, slug + ".npz"))
    arrays = {k: z[k] for k in z.files}
    return meta, arrays


def hit_signal(arrays: dict, source: str = "kick and bass") -> np.ndarray:
    """The detector's input, built exactly as PulseAudioEffect._hit_signal
    builds it (in float64, as the live callback does)."""
    if source == "bass only":
        return arrays["lows"].astype(np.float64)
    if source == "bass weighted":
        lows = arrays["lows"].astype(np.float64)
        return lows + 2.0 * arrays["bmean"].astype(np.float64)
    from fx.effects.pulse import (BASS_BAND_WEIGHT, HIGH_BAND_WEIGHT,
                                   KICK_BAND_WEIGHT, MIDS_BAND_WEIGHT)
    return (
        KICK_BAND_WEIGHT * arrays["beat"].astype(np.float64)
        + BASS_BAND_WEIGHT * arrays["bass"].astype(np.float64)
        + MIDS_BAND_WEIGHT * arrays["mids"].astype(np.float64)
        + HIGH_BAND_WEIGHT * arrays["high"].astype(np.float64)
    )


# ── the engine stand-in ─────────────────────────────────────────────────────

def energy_at(meta: dict, t: float, scale: float) -> float:
    for s, e, v in meta["sections"]:
        if s <= t < e:
            return float(min(1.0, max(0.0, v * scale)))
    secs = meta["sections"]
    v = secs[0][2] if t < secs[0][0] else secs[-1][2]
    return float(min(1.0, max(0.0, v * scale)))


def phase_plan(meta: dict) -> list[tuple[float, str, float]]:
    """(start_s, class, ramp_s) per authored charge/lull/drop, on the
    engine's rule (scene_response._phase_ramp_ms)."""
    ev = meta["events"]
    out = []
    for i, (ts, cls, _it) in enumerate(ev):
        if cls not in PHASE_CLASSES:
            continue
        if cls == "drop":
            out.append((ts, cls, DROP_RAMP_S))
            continue
        nxt = ev[i + 1][0] if i + 1 < len(ev) else None
        ramp = max(0.2, 0.9 * (nxt - ts)) if nxt is not None else FLAT_RAMP_S[cls]
        out.append((ts, cls, ramp))
    return out


@dataclass
class Trace:
    t: np.ndarray
    level: np.ndarray          # eye scale, as the effect composed it
    out: np.ndarray            # max channel of the output frame / 255
    rest: np.ndarray           # the resting component the effect used
    energy: np.ndarray         # the effect's eased energy
    phase: list
    hits: list                 # (audio_t, strength, sharp, rise_ms, want, target)
    plan: list = field(default_factory=list)
    colour: np.ndarray | None = None     # (n, 3) the colour shown, before level
    hue_offset: np.ndarray | None = None  # a colour flip's offset (degrees)
    walk: np.ndarray | None = None       # the rainbow walk's position (unwrapped)
    steps: list = field(default_factory=list)   # (audio_t, walk target)
    flashes: list = field(default_factory=list)  # (render_t, wanted, landed)


def new_effect(config: dict):
    """A standalone PulseAudioEffect with one pixel, ready to step (the class
    the registry creates for type "pulse")."""
    from fx.effects.pulse import PulseAudioEffect
    e = PulseAudioEffect(None, config)
    e.pixels = np.zeros((1, 3))
    e._active = True
    return e


def base_config(meta: dict, scale: float, config: dict | None = None) -> dict:
    cfg = {
        "gradient": COLOUR,
        "beat_ms": 60000.0 / meta["tempo_bpm"],
        "energy": energy_at(meta, 0.0, scale),
    }
    cfg.update(config or {})
    return cfg


class EngineStandIn:
    """Pushes energy at section starts and charge/lull/drop on the engine's
    ramp rule, frame by frame, the way the engine's writes land: a phase
    jump is an ordinary validated write; a progress frame is a lock-free
    _apply_config, exactly as _advance_tweens lands one."""

    def __init__(self, meta: dict, scale: float):
        self.meta = meta
        self.scale = scale
        self.plan = phase_plan(meta)
        self._next_phase = 0
        self._active = None  # (start, cls, ramp)
        self._energy = None

    def before_frame(self, effect, t: float) -> None:
        e = energy_at(self.meta, t, self.scale)
        if e != self._energy:
            self._energy = e
            with effect.lock:
                effect._apply_config({"energy": e}, validate=False, fire_event=False)
        while self._next_phase < len(self.plan) and self.plan[self._next_phase][0] <= t:
            ts, cls, ramp = self.plan[self._next_phase]
            self._next_phase += 1
            self._active = (ts, cls, ramp)
            effect.update_config({"phase": cls, "phase_progress": 0.0})
        if self._active is not None:
            ts, cls, ramp = self._active
            p = min(1.0, (t - ts) / ramp)
            with effect.lock:
                effect._apply_config({"phase_progress": p}, validate=False,
                                     fire_event=False)
            if p >= 1.0:
                self._active = None


def run(meta: dict, arrays: dict, *, scale: float, config: dict | None = None,
        hook=None) -> Trace:
    """Step the real effect over a recorded song: per frame, the engine's
    writes (plus `hook(effect, t)`, e.g. flare pokes), then the audio frame
    (when it reached the effect), then render."""
    from fx import headless

    cfg = base_config(meta, scale, config)
    x = hit_signal(arrays, cfg.get("hit_source", "kick and bass"))
    fired = arrays["fired"]
    n = len(x)
    level = np.zeros(n)
    out = np.zeros(n)
    rest = np.zeros(n)
    energy = np.zeros(n)
    colour = np.zeros((n, 3))
    hue_offset = np.zeros(n)
    walk = np.zeros(n)
    phase = []
    with headless.fake_clock() as clock:
        e = new_effect(cfg)
        eng = EngineStandIn(meta, scale)
        for i in range(n):
            t = (i + 1) * DT
            eng.before_frame(e, t)
            if hook is not None:
                hook(e, t)
            if fired[i]:
                e.ingest_signal(float(x[i]), DT)
            clock.advance(DT)
            e._render()
            px = e.get_pixels()
            level[i] = e.level
            out[i] = float(np.max(px[0])) / 255.0
            rest[i] = e._rest
            energy[i] = e._energy_live
            colour[i] = e.shown_colour
            hue_offset[i] = e.hue_offset
            walk[i] = e._walk_pos
            phase.append(e._phase)
    return Trace(
        t=(np.arange(n) + 1) * DT, level=level, out=out, rest=rest,
        energy=energy, phase=phase, hits=list(e.hits), plan=eng.plan,
        colour=colour, hue_offset=hue_offset, walk=walk,
        steps=list(e.steps), flashes=list(e.flashes),
    )


# ── measuring the light ─────────────────────────────────────────────────────

def max_rise_per_second(out: np.ndarray, window_s: float = 1.0) -> float:
    """The most the delivered light rose, summed, in any window: the flash
    budget as the OUTPUT shows it (independent of the effect's bookkeeping)."""
    up = np.clip(np.diff(out), 0.0, None)
    w = int(round(window_s * FPS))
    c = np.concatenate([[0.0], np.cumsum(up)])
    if len(c) <= w:
        return float(c[-1])
    return float(np.max(c[w:] - c[:-w]))


def _frame_of(t: float) -> int:
    return int(round(t * FPS)) - 1


def isolated_hits(tr: Trace, gap_s: float) -> list:
    """Hits with no other hit within gap_s after them, outside any phase."""
    ts = [h[0] for h in tr.hits]
    out = []
    for k, h in enumerate(tr.hits):
        nxt = ts[k + 1] if k + 1 < len(ts) else 1e9
        i = _frame_of(h[0])
        if nxt - h[0] < gap_s or i < 1 or i >= len(tr.t) - 2:
            continue
        if tr.phase[i] != "none" or tr.phase[min(len(tr.phase) - 1, i + int(gap_s * FPS))] != "none":
            continue
        out.append((k, h, i))
    return out


def rise_times_ms(tr: Trace) -> np.ndarray:
    """From the OUTPUT: frames from the hit until the level stops rising.
    Scans the PULSE above rest (level - rest), the same convention
    fade_times() already uses — raw level can keep creeping for a few
    frames after the pulse itself has peaked and started to fade, from
    `rest` easing toward a new `energy` over its own ENERGY_SLEW_S; with
    the longer fades (task 2, 2026-10-06) that creep can transiently
    outrun the envelope's own gentler decay and read as "still rising" if
    measured on raw level."""
    pulse = tr.level - tr.rest
    res = []
    for _k, h, i in isolated_hits(tr, 0.3):
        if pulse[i] <= pulse[i - 1] + 1e-6:
            continue  # no visible rise (light already high, or budget spent)
        j = i
        # 1e-4, not 1e-9: a residual sub-frame tick from rest/energy easing
        # can otherwise read as "still rising" for one more frame right at
        # the attack's own completion, past what the real attack covers.
        while j + 1 < len(pulse) and pulse[j + 1] > pulse[j] + 1e-4:
            j += 1
        res.append((j - i + 1) * 1000.0 * DT)
    return np.asarray(res)


def fade_times(tr: Trace, beat_s: float, cfg: dict) -> list:
    """From the OUTPUT: for isolated hits, the time from the peak until the
    pulse above rest is back to a tenth, against the nominal fade (beats from
    the effect's own eased energy x the beat). The isolation window scales
    with the CONFIGURED calm fade (not a hardcoded old default) — a longer
    fade needs more room before a later hit can interrupt it."""
    res = []
    for _k, h, i in isolated_hits(tr, cfg["fade_beats_calm"] * beat_s * 1.5):
        j = i
        while j + 1 < len(tr.level) and tr.level[j + 1] > tr.level[j] + 1e-9:
            j += 1
        peak = tr.level[j] - tr.rest[j]
        if peak < 0.08:
            continue  # too small to time against 8-bit-ish steps
        k = j
        while k + 1 < len(tr.level) and (tr.level[k] - tr.rest[k]) > 0.1 * peak:
            k += 1
        e = tr.energy[j]
        nominal = (cfg["fade_beats_calm"] + (cfg["fade_beats_intense"] - cfg["fade_beats_calm"]) * e) * beat_s
        res.append((e, (k - j) * DT, nominal))
    return res


def swing(tr: Trace, mask: np.ndarray) -> float | None:
    if not mask.any():
        return None
    v = tr.level[mask]
    return float(np.percentile(v, 95) - np.percentile(v, 5))


def phase_checks(tr: Trace) -> list[dict]:
    """Per authored phase event: what the light did."""
    res = []
    plan = tr.plan
    for n, (ts, cls, ramp) in enumerate(plan):
        i0 = max(0, _frame_of(ts))
        nxt = plan[n + 1][0] if n + 1 < len(plan) else None
        if cls == "lull" and nxt is not None and plan[n + 1][1] == "drop":
            i1 = _frame_of(nxt) - 1  # the frame before the drop lands
            res.append(dict(cls=cls, t=ts, ramp=ramp, before_drop=float(tr.level[i1])))
        elif cls == "drop":
            res.append(dict(cls=cls, t=ts, peak_100ms=float(tr.level[i0:i0 + 7].max()),
                            first_frame=float(tr.level[i0 + 1] if i0 + 1 < len(tr.level) else 0)))
        elif cls == "charge":
            end = _frame_of(nxt) - 1 if nxt is not None else i0 + int(ramp * FPS)
            res.append(dict(cls=cls, t=ts, start_rest=float(tr.rest[i0 + 1]),
                            end_rest=float(tr.rest[max(i0 + 1, end)]),
                            end_min_level=float(tr.level[max(i0 + 1, end - 30):end + 1].min())))
    return res


def onset_agreement_pct(tr: Trace, onsets: np.ndarray, within_s: float = 0.07) -> float | None:
    if not len(onsets) or not tr.hits:
        return None
    on = np.sort(onsets.astype(np.float64))
    near = 0
    for h in tr.hits:
        k = np.searchsorted(on, h[0])
        d = min(abs(on[k - 1] - h[0]) if k > 0 else 9, abs(on[k] - h[0]) if k < len(on) else 9)
        near += d < within_s
    return 100.0 * near / len(tr.hits)


def measure(tr: Trace, meta: dict, arrays: dict, cfg_full: dict) -> dict:
    beat_s = 60.0 / meta["tempo_bpm"]
    minutes = tr.t[-1] / 60.0
    planned = np.asarray([h[3] for h in tr.hits]) if tr.hits else np.zeros(1)
    rises = rise_times_ms(tr)
    fades = fade_times(tr, beat_s, cfg_full)
    hi = np.array([f for f in fades if f[0] >= 0.6])
    lo = np.array([f for f in fades if f[0] <= 0.35])
    none = np.array([p == "none" for p in tr.phase])
    return dict(
        minutes=round(minutes, 2),
        hits=len(tr.hits),
        hits_per_min=round(len(tr.hits) / minutes, 1),
        limited_hits=sum(1 for h in tr.hits if h[5] < h[4] - 1e-6),
        planned_rise_ms=[round(float(np.percentile(planned, q))) for q in (10, 50, 90)],
        measured_rise_ms=[round(float(np.percentile(rises, q))) for q in (10, 50, 90)] if len(rises) else None,
        rises_measured=len(rises),
        fade_hi=(round(float(np.median(hi[:, 1] / hi[:, 2])), 2), len(hi)) if len(hi) else None,
        fade_lo=(round(float(np.median(lo[:, 1] / lo[:, 2])), 2), len(lo)) if len(lo) else None,
        fade_hi_s=round(float(np.median(hi[:, 1])), 3) if len(hi) else None,
        fade_lo_s=round(float(np.median(lo[:, 1])), 3) if len(lo) else None,
        swing_hi=swing(tr, none & (tr.energy >= 0.6)),
        swing_lo=swing(tr, none & (tr.energy <= 0.35)),
        level_p5=round(float(np.percentile(tr.level, 5)), 3),
        level_p95=round(float(np.percentile(tr.level, 95)), 3),
        max_rise_per_s=round(max_rise_per_second(tr.out), 3),
        phases=phase_checks(tr),
        onset_agreement_pct=onset_agreement_pct(tr, arrays.get("onsets", np.zeros(0))),
        beat_ms=round(beat_s * 1000),
    )


def full_config(cfg: dict) -> dict:
    """The effect's schema defaults with `cfg` over them."""
    from fx.effects.pulse import PulseAudioEffect
    full = PulseAudioEffect.schema()({})
    full.update(cfg)
    return full
