"""Offline precompute for the music-analysis test bed
(data/spotfx-music-analysis-plan/report.md, Part 3's own "What it does NOT
do": no re-running an engine inside the request path). Run this to fill
storage/spectra/testbed/analysis/<engine>/<song>.json — the
spectra/services/testbed_cache.py file the app reads and never writes
itself.

Usage (repo root):
  .venv/bin/python scripts/testbed_precompute.py --uri spotify:track:XXXX \
      --engine beat_this [--device cpu] [--wav /path/to/song.wav]

`--wav` defaults to the test bed's own pinned copy
(storage/spectra/testbed/audio/<safe-uri>.wav — see
spectra/services/testbed_audio.py); pin the song first (POST
/api/testbed/audio/pin) or pass an explicit path.

`--engine librosa` is a deliberate no-op: librosa's marks are derived LIVE
from the already-computed .librosa.json (testbed_engines.py), never
cached — this flag exists only so the CLI's error message for a typo'd
engine name lists it as a real, if uncacheable, option.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectra.services import testbed_audio, testbed_beatthis, testbed_cache, testbed_engines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True, help="spotify:track:... URI")
    parser.add_argument("--engine", required=True,
                        choices=[testbed_engines.ENGINE_LIBROSA, testbed_engines.ENGINE_BEAT_THIS])
    parser.add_argument("--device", default="cpu", help="beat_this device (cpu/cuda)")
    parser.add_argument("--wav", default=None, help="override the WAV path")
    args = parser.parse_args()

    if args.engine == testbed_engines.ENGINE_LIBROSA:
        print("librosa is derived live from .librosa.json — nothing to precompute.")
        return 0

    wav_path = Path(args.wav) if args.wav else testbed_audio.wav_copy_path(args.uri)
    if not wav_path.exists():
        print(f"No WAV at {wav_path} — pin this song's audio first "
              f"(POST /api/testbed/audio/pin?uri=...) or pass --wav.", file=sys.stderr)
        return 1

    print(f"Running {args.engine} on {wav_path} ({args.device})...")
    try:
        marks = testbed_beatthis.compute_marks_ms(wav_path, device=args.device)
    except testbed_beatthis.BeatThisUnavailable as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    saved = testbed_cache.save(testbed_engines.ENGINE_BEAT_THIS, args.uri,
                               testbed_beatthis.ENGINE_VERSION, marks)
    n_beats = sum(1 for m in marks if m["kind"] == "beat")
    n_downbeats = sum(1 for m in marks if m["kind"] == "downbeat")
    print(f"Saved {saved}: {n_beats} beats, {n_downbeats} downbeats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
