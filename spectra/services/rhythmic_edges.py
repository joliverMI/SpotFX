"""Rhythmic-edge detection for the music-analysis test bed's tuning loop
(data/transition-alignment-plan/report.md section 4, ship task 2). A pure
signal-processing module over the per-beat `rms_bass` already stored in a
song's `.librosa.json` — NEVER a WAV re-analysis (the report's own §2.3
finding: a kick-band re-analysis of the raw audio was tried alongside the
stored sidecar signal and was not better on 3 of 4 songs, so the sidecar
signal is what ships).

Three event families, matching the report's own §2.3 methodology
(`edges_from_energy` in `data/transition-alignment-plan/evidence/
score_rules.py`, cleaned up and parameterized here):

  bass_up    — a beat whose rms_bass jumps up more than `sensitivity`
               times the local median (bass coming IN).
  bass_down  — the mirror (bass going OUT).
  gap_stop   — the first beat of a run of `window_beats` or more
               consecutive beats under a fixed "quiet" fraction of the
               local median (the beat stops).
  gap_resume — the first beat at/above a fixed "loud" fraction of the
               local median after such a run (the beat resumes).

TWO KNOBS, ONE EACH — do not conflate them:

  sensitivity  — "how big a jump counts" (report's own words). Maps
                 directly to the up/down step threshold (`step` in
                 score_rules.py's edges_from_energy — same name, same
                 default 0.5). This is the ONLY knob that governs bass_up/
                 bass_down, and the local-median lookback they compare
                 against is FIXED at MEDIAN_LOOKBACK_BEATS (16, the report
                 evidence script's own rolling_median default) — NOT
                 exposed as `window_beats`. This is deliberate: exposing
                 the lookback as a tunable defaulting to a different value
                 than 16 would change the up/down event set at the default
                 knobs and break the report's own §2.3 reproduction
                 acceptance bar (`GET /compare` at default knobs must
                 reproduce the "Bass energy jumps up/down" rows on the
                 four pinned songs).
  window_beats — "how many beats a cue may move" (the report's own words
                 for the R3 PLACEMENT rule, a future task — see the
                 module docstring of a not-yet-built beat_snap.place_cue).
                 In THIS module, before that placement rule exists, its
                 only live effect is on gap detection: the minimum run
                 length (in beats) of consecutive quiet beats that counts
                 as a genuine gap (`gap_beats` in the report evidence
                 script, there fixed at 2). Exposing it here at its own
                 default (8) rather than the evidence script's internal 2
                 is safe because the report's reproduction acceptance is
                 scoped to the up/down rows only, never the gap rows (see
                 the module docstring above and report §2.3's own table:
                 "Beat resumes"/"Beat stops" are reported but not part of
                 any ship-task acceptance number).

Deliberately does NOT do capture-offset shifting — this module works in
the SAME raw analysis-file frame `beats_for_uri`/`sections_for_uri` already
use (see beat_snap.py's own "ONE FRAME, NO SHIFT" section and AGENTS.md's
`librosa_offset_ms` note). The one caller that needs a cross-frame
comparison (`spectra/api/testbed.py::_estimate_for`, already shifting
every OTHER engine's marks by `testbed_audio.capture_offset_ms_or_zero`)
applies the shift uniformly; duplicating it here would double it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from spectra.services import analysis_reader

DEFAULT_WINDOW_BEATS = 8
DEFAULT_SENSITIVITY = 0.5

MIN_WINDOW_BEATS = 1
MAX_WINDOW_BEATS = 16
MIN_SENSITIVITY = 0.2
MAX_SENSITIVITY = 1.5

# The report evidence script's own fixed "how quiet is quiet" / "how loud
# counts as resumed" fractions of the local median (score_rules.py's
# q_low=0.35, q_high=0.8) — not exposed as knobs; only window_beats
# (the run-length threshold) and sensitivity (the up/down step threshold)
# are tunable, per the report's own two-knob design.
QUIET_FRACTION = 0.35
RESUME_FRACTION = 0.8

# The local-median lookback the up/down step threshold compares against —
# FIXED at the report evidence script's own rolling_median(x, w=16)
# default. See the module docstring's "TWO KNOBS" section for why this is
# not window_beats.
MEDIAN_LOOKBACK_BEATS = 16

KIND_BASS_UP = "bass_up"
KIND_BASS_DOWN = "bass_down"
KIND_GAP_STOP = "gap_stop"
KIND_GAP_RESUME = "gap_resume"
KINDS = (KIND_BASS_UP, KIND_BASS_DOWN, KIND_GAP_STOP, KIND_GAP_RESUME)


@dataclass(frozen=True)
class EdgeMark:
    time_ms: float
    kind: str


def clamp_window_beats(value) -> int:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_BEATS
    return max(MIN_WINDOW_BEATS, min(MAX_WINDOW_BEATS, v))


def clamp_sensitivity(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SENSITIVITY
    return max(MIN_SENSITIVITY, min(MAX_SENSITIVITY, v))


def _rolling_median(values: list[float], lookback: int) -> list[float]:
    """Local median over a `±lookback`-beat window around each index —
    score_rules.py's own rolling_median, floored at a small epsilon so a
    silent stretch never divides a later comparison by zero."""
    out = []
    n = len(values)
    for i in range(n):
        lo = max(0, i - lookback)
        hi = min(n, i + lookback + 1)
        seg = sorted(values[lo:hi])
        m = len(seg)
        med = seg[m // 2] if m % 2 else (seg[m // 2 - 1] + seg[m // 2]) / 2.0
        out.append(max(med, 1e-6))
    return out


def edges_for_beats(
    beat_ms: list[float],
    rms_bass: list[float],
    *,
    window_beats: int = DEFAULT_WINDOW_BEATS,
    sensitivity: float = DEFAULT_SENSITIVITY,
) -> dict[str, list[float]]:
    """Pure function: `beat_ms`/`rms_bass` are parallel per-beat arrays,
    sorted ascending by `beat_ms` (the caller's responsibility — a song's
    own `beats` list from `.librosa.json` is already beat-ordered). Returns
    `{kind: sorted ms list}` for every kind in KINDS, every list possibly
    empty. Never raises: fewer than 2 beats, or mismatched array lengths,
    returns every kind empty."""
    n = len(beat_ms)
    if n < 2 or len(rms_bass) != n:
        return {kind: [] for kind in KINDS}

    step = clamp_sensitivity(sensitivity)
    gap_run = clamp_window_beats(window_beats)
    med = _rolling_median(rms_bass, MEDIAN_LOOKBACK_BEATS)

    ups = [beat_ms[i] for i in range(1, n)
          if (rms_bass[i] - rms_bass[i - 1]) > step * med[i]]
    downs = [beat_ms[i] for i in range(1, n)
            if (rms_bass[i - 1] - rms_bass[i]) > step * med[i]]

    quiet = [rms_bass[i] < QUIET_FRACTION * med[i] for i in range(n)]
    stops: list[float] = []
    resumes: list[float] = []
    i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= gap_run:
                stops.append(beat_ms[i])
                k = j
                while k < n and rms_bass[k] < RESUME_FRACTION * med[k]:
                    k += 1
                if k < n:
                    resumes.append(beat_ms[k])
            i = j
        else:
            i += 1

    return {
        KIND_BASS_UP: sorted(ups),
        KIND_BASS_DOWN: sorted(downs),
        KIND_GAP_STOP: sorted(stops),
        KIND_GAP_RESUME: sorted(resumes),
    }


def edges_for_uri(
    uri: str,
    *,
    window_beats: int = DEFAULT_WINDOW_BEATS,
    sensitivity: float = DEFAULT_SENSITIVITY,
) -> Optional[dict[str, list[EdgeMark]]]:
    """`{kind: [EdgeMark, ...]}` for a song's own stored beats, or None
    when there is no usable beat analysis at all (no `.librosa.json`, or
    one with no beats) — matching every other engine's "not available"
    convention. A song WITH beats but no detected edges of some kind
    returns that kind as an empty list, not None."""
    beats = analysis_reader.beats_for_uri(uri)
    if not beats:
        return None
    ordered = sorted(beats, key=lambda b: float(b.get("ms", 0)))
    beat_ms = [float(b.get("ms", 0)) for b in ordered]
    rms_bass = [float(b.get("rms_bass", 0.0)) for b in ordered]
    raw = edges_for_beats(beat_ms, rms_bass, window_beats=window_beats,
                         sensitivity=sensitivity)
    return {kind: [EdgeMark(time_ms=t, kind=kind) for t in times]
           for kind, times in raw.items()}
