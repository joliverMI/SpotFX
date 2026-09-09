"""beat_this integration (CPJKU, 2024, "Beat This! Accurate beat tracking
without dynamic programming or diffusion methods") — the music-analysis
test bed's first real second engine
(data/spotfx-music-analysis-plan/report.md, Part 1.3/1.4, top pick:
downbeat F1 0.55 vs the current pipeline's 0.30 at +/-500ms).

LICENSE, checked before shipping (per the brief's own instruction): both the
`beat_this` PyPI package's code AND its published pretrained checkpoints are
MIT-licensed (github.com/CPJKU/beat_this's own README: "The code and the
published model weights are released under the MIT license") — no
non-commercial restriction, unlike madmom's CC BY-NC-SA-licensed models
(report Part 1.3), which is exactly why the report picked this engine over
madmom despite madmom being the more "obvious" academic-standard tool.

`dbn=False` — the report's own instruction, and it's load-bearing: dbn=True
routes beat_this's raw frame predictions through a madmom
DBNDownBeatTrackingProcessor for postprocessing, which would silently pull
madmom back in (the brief's explicit "do NOT pull madmom"). dbn=False uses
beat_this's own peak-picking postprocessing instead — still the model this
report measured (Part 1.4's numbers are all dbn=False).

This module is ONLY ever called from scripts/testbed_precompute.py — an
offline CLI, never a request handler (the report's own Part 3 "What it does
NOT do": no re-running an engine inside the request path; a beat_this pass
took ~97s CPU on one 4-minute song in the report's own measurement). The
`beat_this` package (~pytorch + a 77MB CPU checkpoint) is an OPTIONAL
dependency (requirements-testbed.txt, mirroring
requirements-capture-client.txt's precedent for a dependency scoped to one
offline tool rather than the whole app) — importing it here is guarded so a
host without it reports "unavailable" rather than crashing the precompute
script or, worse, the request path that reads this module's cached output.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ENGINE_VERSION = "beat_this-checkpoint=final0-dbn=false"


class BeatThisUnavailable(RuntimeError):
    """The `beat_this` package (or a dependency of it) isn't installed.
    Raised, never silently swallowed into an empty result — an empty
    result would read as "beat_this found zero beats," a false claim
    about the song rather than an honest statement about this host."""


def compute(wav_path: Path, device: str = "cpu") -> dict:
    """Returns {"beats_s": [...], "downbeats_s": [...]} — both in SECONDS,
    beat_this's own native unit (its README's own return-value
    description). Caller (scripts/testbed_precompute.py) converts to the
    test bed's ms convention and the normalized mark shape."""
    try:
        from beat_this.inference import File2Beats
    except ImportError as exc:
        raise BeatThisUnavailable(
            "the 'beat_this' package is not installed — "
            "pip install -r requirements-testbed.txt"
        ) from exc

    file2beats = File2Beats(checkpoint_path="final0", device=device, dbn=False)
    beats, downbeats = file2beats(str(wav_path))
    return {
        "beats_s": [float(b) for b in beats],
        "downbeats_s": [float(d) for d in downbeats],
    }


def compute_marks_ms(wav_path: Path, device: str = "cpu") -> list[dict]:
    """The test bed's normalized mark shape directly — every downbeat time
    ALSO appears as a plain beat (beat_this's own convention: downbeats are
    a labeled subset of beats, not a disjoint stream), matching how
    testbed_engines._librosa_marks reads the current pipeline's own beats
    (is_downbeat flag on a beat, not a separate list)."""
    result = compute(wav_path, device=device)
    downbeat_set = {round(s, 3) for s in result["downbeats_s"]}
    marks: list[dict] = []
    for s in result["beats_s"]:
        is_downbeat = round(s, 3) in downbeat_set
        marks.append({
            "time_ms": s * 1000.0,
            "kind": "downbeat" if is_downbeat else "beat",
            "label": None,
            "score": None,
        })
    # A downbeat time that beat_this didn't ALSO report as a plain beat
    # (shouldn't happen per its own convention, but never silently drop a
    # real downbeat if it does) — add anything missing.
    beat_set = {round(s, 3) for s in result["beats_s"]}
    for s in result["downbeats_s"]:
        if round(s, 3) not in beat_set:
            marks.append({"time_ms": s * 1000.0, "kind": "downbeat",
                          "label": None, "score": None})
    return sorted(marks, key=lambda m: m["time_ms"])
