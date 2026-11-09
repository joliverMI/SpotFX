#!/usr/bin/env python3
"""What the emphasis score picks on real songs, read-only: for each word
timeline in a directory (the job's holding directory, or storage/audio_shapes
itself) prints how many words it picks at the slider's default, what they
are, and the two checks the score depends on: that the sidecar still matches
the capture, and that the lane's own slip measure agrees with the job's.

    .venv/bin/python scripts/check_lyrics_emphasis.py \\
        --source /home/javi/fleet-spotfx/data/lyrics-backfill/stage2 \\
        [--songs scripts/lyrics_first_songs.json] [--limit 20] [--top 14]

Reads only; writes nothing, drives nothing, loads no model.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectra import config  # noqa: E402
from spectra.services import (analysis_reader, lyrics_emphasis, lyrics_sidecar,  # noqa: E402
                              lyrics_timeline)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--shapes-dir", type=Path, default=config.AUDIO_SHAPES_DIR)
    parser.add_argument("--songs", type=Path, help="only these (a scripts/lyrics_first_songs.json shape)")
    parser.add_argument("--sensitivity", type=float, default=lyrics_emphasis.DEFAULT_SENSITIVITY)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top", type=int, default=14, help="words to print per song")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    config.AUDIO_SHAPES_DIR = args.shapes_dir

    if args.songs:
        wanted = [e["stem"] for e in json.loads(args.songs.read_text(encoding="utf-8"))["songs"]]
        paths = [lyrics_sidecar.path_for(args.source, stem) for stem in wanted]
    else:
        paths = sorted(args.source.glob(f"*{lyrics_sidecar.SUFFIX}"))
    if args.limit:
        paths = paths[:args.limit]

    picked_share: list[float] = []
    slips: list[float] = []
    flagged = 0
    for path in paths:
        stem = path.name[:-len(lyrics_sidecar.SUFFIX)]
        if not path.exists():
            print(f"-- {stem}: not in the source directory")
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        problems = lyrics_sidecar.validate(doc, expected_stem=stem)
        if problems:
            print(f"-- {stem}: invalid: {', '.join(problems)}")
            continue
        changed = lyrics_sidecar.problems_against_capture(doc, args.shapes_dir, require_wav=False)
        loudness = analysis_reader.capture_loudness_for_stem(stem)
        frames = lyrics_emphasis.Frames(*loudness) if loudness is not None else None
        analysis = analysis_reader.librosa_analysis_for_stem(stem) or {}
        timeline = lyrics_timeline.build_timeline(doc["uri"], doc, frames, analysis.get("beats") or [])
        chosen = lyrics_timeline.emphasized_words(timeline, args.sensitivity)
        share = len(chosen) / len(timeline.scored)
        picked_share.append(share)
        slips.append(timeline.clock.max_slip_ms or 0.0)
        flagged += int(timeline.clock.flagged)
        label_map = doc["stamp"].get("label_map") or {}
        print(f"{stem} [{doc.get('lang')}]: {len(chosen)} of {len(timeline.scored)} words "
              f"({share:.1%}), slip {timeline.clock.max_slip_ms} ms"
              f"{' FLAGGED' if timeline.clock.flagged else ''}"
              f" (job's own frame map: {label_map.get('max_abs_diff_ms')} ms)"
              f"{'; CAPTURE CHANGED ' + str(changed) if changed else ''}")
        if not args.summary_only:
            for w in sorted(sorted(chosen, key=lambda s: -s.score)[:args.top], key=lambda s: s.ms):
                f = w.features
                print(f"    {w.ms / 1000:7.2f}s {w.word:18s} {w.score:.2f}  loud {f.loud:.2f} "
                      f"held {f.held:.2f} beat {f.beat:.2f} end {f.line_end:.0f} hook {f.hook:.2f}")
    if picked_share:
        print(f"\n{len(picked_share)} songs: words picked at sensitivity {args.sensitivity}: "
              f"median {statistics.median(picked_share):.1%}, "
              f"range {min(picked_share):.1%} to {max(picked_share):.1%}; "
              f"{flagged} flagged (slip > {lyrics_timeline.SLIP_FLAG_MS:.0f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
