#!/usr/bin/env python
"""
Replay a single song through the offline xcorr harness with a verbose
per-window trace.

  python -m scripts.xcorr_replay --song "Thunderstruck" --true-offset -2000
  python -m scripts.xcorr_replay --song "VeLD" --cut-in 15000 --true-offset 15000 --seed cold -v
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AUDIO_SHAPES_DIR  # noqa: E402
from bench.replay import Scenario, replay_play  # noqa: E402


def find_stem(query: str) -> str:
    matches = [w.stem for w in sorted(AUDIO_SHAPES_DIR.glob("*.wav"))
               if query.lower() in w.stem.lower()]
    if not matches:
        sys.exit(f"no WAV matching {query!r}")
    if len(matches) > 1:
        print(f"({len(matches)} matches, using first: {matches[0]})")
    return matches[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--song", required=True, help="substring of the stored stem")
    ap.add_argument("--true-offset", type=int, default=0, dest="true_offset")
    ap.add_argument("--cut-in", type=int, default=0, dest="cut_in")
    ap.add_argument("--gain", type=float, default=1.0)
    ap.add_argument("--noise-snr", type=float, default=None, dest="noise_snr")
    ap.add_argument("--blend-donor", default=None, help="stem substring for donor tail")
    ap.add_argument("--blend-ms", type=int, default=0)
    ap.add_argument("--seed", choices=["cold", "seeded_correct", "seeded_wrong_2s"],
                    default="cold")
    ap.add_argument("--play-type", choices=["first", "natural", "skip"], default="first")
    ap.add_argument("--force-search-ms", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    stem = find_stem(args.song)
    donor = find_stem(args.blend_donor) if args.blend_donor else None
    sc = Scenario(
        name="cli", true_offset_ms=args.true_offset, cut_in_ms=args.cut_in,
        gain=args.gain, noise_snr_db=args.noise_snr,
        blend_donor=donor, blend_ms=args.blend_ms,
        seed=args.seed, play_type=args.play_type,
        force_search_ms=args.force_search_ms,
    )
    print(f"Replaying: {stem}")
    print(f"  scenario: expected_offset={args.true_offset:+d}ms cut_in={args.cut_in}ms "
          f"seed={args.seed} noise={args.noise_snr} blend={args.blend_ms}ms")
    res = replay_play(stem, sc, verbose=True)

    print(f"\nResult:")
    print(f"  windows evaluated : {res.windows_evaluated}/{res.windows_planned}"
          f"{'  (lock-and-stop)' if res.locked_via_stop else ''}")
    print(f"  anchor matched    : {res.anchor_matched}")
    print(f"  saves             : {res.n_saves} ({res.wrong_lock_events} wrong >300ms)")
    print(f"  stored offset     : {res.final_stored_offset_ms} "
          f"(error {res.final_stored_error_ms}ms)" if res.final_stored_offset_ms is not None
          else "  stored offset     : none (no save fired)")
    print(f"  engine offset     : {res.engine_final_offset_ms:+d}ms "
          f"(error {res.engine_final_error_ms:+d}ms)")
    print(f"  first correct lock: {res.time_to_first_correct_lock_ms}ms song-time")
    print(f"  cpu               : total {res.cpu_ms_total}ms, "
          f"p50 {res.cpu_ms_p50}ms, p95 {res.cpu_ms_p95}ms per window")
    print(f"  verdict           : {'CORRECT' if res.correct else 'INCORRECT/NO-SAVE'}")


if __name__ == "__main__":
    main()
