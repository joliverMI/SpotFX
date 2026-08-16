#!/usr/bin/env python3
"""Regression check: the Admiral's 2026-07-29 calibration, carried forward.

Read-only, no writes, no live LedFX/HTTP — reads storage/audio_shapes and
storage/training_profiles.json (the exact spectra.services.intensity_scale
inputs) and reports where his three reference songs land TODAY:

    Dopamine (Wooli, Tape B)         target ~120%
    Let It Be (The Beatles)          target ~50%
    Soy Peor (Bad Bunny)             target ~100%

Those numbers are his ears on his own songs (2026-07-29, EDM 1.85 / Rock
0.7 / Trap 1.35 sliders) — the only ground truth any future change to this
mechanism has. A drift here is worth reporting even when nothing in the
CODE changed: the analysed library grows over time, and the bass-rank
percentile is relative to whatever's currently on disk.

Also reports the 2026-08-15 headroom-reserve consequence
(intensity_scale.combine_measured_and_scale): each song's FINAL render
intensity at its single most intense moment (measured_intensity=1.0) —
this is what actually reaches the lights, not song_scaling_factor alone.

Run from repo root:  .venv/bin/python scripts/check_intensity_scale_reference_songs.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectra.services import intensity_scale as isc  # noqa: E402

REFERENCE_SONGS = [
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT",
    ["dubstep", "melodic bass", "riddim", "edm", "deathstep", "future bass", "bass music"],
    1.20),
    ("Let It Be", "spotify:track:7iN1s7xHE4ifF5povM6A48",
    ["classic rock", "psychedelic rock"], 0.50),
    ("Soy Peor", "spotify:track:1JxhrUWZjuI8AOjDJ1JpMN",
    ["reggaeton", "trap latino", "latin", "urbano latino"], 1.00),
]


def main() -> int:
    print(f"{'song':<12} {'genre base':>10} {'bass rank':>10} {'auto scale':>11} "
          f"{'target':>7} {'diff':>7}   {'final @1.0':>10}")
    any_missing = False
    for name, uri, genres, target in REFERENCE_SONGS:
        base = isc.resolve_genre_scale(genres)
        rank = isc.bass_rank(uri)
        scale = isc.song_scaling_factor(uri, genres)
        final_at_peak = isc.combine_measured_and_scale(1.0, scale)
        if rank is None:
            any_missing = True
            print(f"{name:<12} {base:>10.3f} {'—':>10} {scale:>11.3f} "
                  f"{target:>7.2f} {scale - target:>+7.3f}   {final_at_peak:>10.3f}  "
                  f"(no capture/librosa data found for this song, or library <20 songs)")
        else:
            print(f"{name:<12} {base:>10.3f} {rank:>10.3f} {scale:>11.3f} "
                  f"{target:>7.2f} {scale - target:>+7.3f}   {final_at_peak:>10.3f}")

    print()
    print(f"headroom reserve: {isc.HEADROOM_RESERVE} — structural ceiling for ANY "
          f"auto-scaled song (no manual per-song override exists in SPECTRA today) "
          f"is {isc.HEADROOM_RESERVE} * {isc.SCALE_MAX} = "
          f"{isc.HEADROOM_RESERVE * isc.SCALE_MAX:.3f}, at measured_intensity=1.0")
    if any_missing:
        print("\nNOTE: one or more reference songs had no bass-rank data — this is "
              "expected in a worktree/CI without the real storage/audio_shapes "
              "library; run this against the live checkout for a real reading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
