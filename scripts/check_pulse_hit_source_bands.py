"""Evidence for the 2026-10-06 Pulse tuning feedback (`hit_source`): on his
four captured songs, classify every hit the OLD default ("bass weighted")
and the NEW default ("kick and bass") make against his song's own
BASS-onset marks vs SNARE/other-onset marks (librosa's own classification,
`.librosa.json` — `bass_onsets` vs `snare_onsets`/`onsets`, the stand-ins
for "kick and bass" vs "hats and cymbals"), and print before/after counts.

Read-only against `tests/fixtures/pulse/` (the effect's own recorded audio
input, drives no light) and his real `storage/audio_shapes/*.librosa.json`
(read-only, for the onset labels the committed fixture discards — it keeps
only one merged `onsets` set).

Run:  .venv/bin/python scripts/check_pulse_hit_source_bands.py
      [--shapes-dir /home/javi/SpotFX/storage/audio_shapes]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import numpy as np  # noqa: E402

import pulse_song_harness as h  # noqa: E402

NEAR_S = 0.07  # matches pulse_song_harness.onset_agreement_pct's own tolerance


def _onset_sets(stem: str, shapes_dir: str) -> tuple[np.ndarray, np.ndarray]:
    with open(os.path.join(shapes_dir, stem + ".librosa.json")) as f:
        an = json.load(f)
    bass = np.asarray(sorted(o["ms"] / 1000.0 for o in an.get("bass_onsets", [])))
    other = np.asarray(sorted(
        o["ms"] / 1000.0
        for k in ("snare_onsets", "onsets")
        for o in an.get(k, [])
    ))
    return bass, other


def _nearest_within(sorted_times: np.ndarray, t: float, within_s: float) -> bool:
    if not len(sorted_times):
        return False
    k = np.searchsorted(sorted_times, t)
    d = min(
        abs(sorted_times[k - 1] - t) if k > 0 else 1e9,
        abs(sorted_times[k] - t) if k < len(sorted_times) else 1e9,
    )
    return d < within_s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shapes-dir", default="/home/javi/SpotFX/storage/audio_shapes")
    args = ap.parse_args()

    for slug, spec in h.SONGS.items():
        meta, arrays = h.load_fixture(slug)
        bass_onsets, other_onsets = _onset_sets(spec["stem"], args.shapes_dir)
        print(f"{slug}: {spec['stem']}  "
              f"({len(bass_onsets)} bass onsets, {len(other_onsets)} snare/other onsets)")
        for source, label in (
            ("bass weighted", "OLD default"),
            ("kick and bass", "NEW default"),
        ):
            tr = h.run(meta, arrays, scale=spec["scale"], config={"hit_source": source})
            near_bass = near_other = neither = 0
            for hit in tr.hits:
                t = hit[0]
                b = _nearest_within(bass_onsets, t, NEAR_S)
                o = _nearest_within(other_onsets, t, NEAR_S)
                if b:
                    near_bass += 1
                elif o:
                    near_other += 1
                else:
                    neither += 1
            total = len(tr.hits)
            print(f"  {label:12s} ({source!r:16s}): {total:4d} hits — "
                  f"near a BASS onset {near_bass:4d} ({100.0*near_bass/max(1,total):5.1f}%)  "
                  f"near a SNARE/other onset {near_other:4d} ({100.0*near_other/max(1,total):5.1f}%)  "
                  f"neither {neither:4d}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
