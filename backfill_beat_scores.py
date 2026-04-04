"""
backfill_beat_scores.py
=======================
One-shot script to add onset_score / bass_onset_score / harmonic_score to every
existing .librosa.json file that is missing those fields (or has them all at 0.0).

Run from the project root:
    python backfill_beat_scores.py

No server needed. Reads and writes files in storage/audio_shapes/ in-place.
Pass --dry-run to preview without writing.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np


# ── Resolve project root so imports work when run from any directory ──────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from config import AUDIO_SHAPES_DIR


def _compute_beat_event_scores(beats, onsets, bass_onsets, harmonic_changes):
    """
    Identical logic to librosa_service._compute_beat_event_scores but operates
    directly on plain dicts (as loaded from JSON) rather than Pydantic models.
    Returns three parallel lists normalised 0-1.
    """
    n = len(beats)
    if n == 0:
        return [], [], []

    beat_ms = np.array([b["ms"] for b in beats], dtype=int)

    onset_raw    = np.zeros(n)
    bass_raw     = np.zeros(n)
    harmonic_raw = np.zeros(n)

    for o in onsets:
        idx = int(np.searchsorted(beat_ms, o["ms"], side="right")) - 1
        if 0 <= idx < n:
            onset_raw[idx] += o.get("strength", 1.0)

    for bo in bass_onsets:
        idx = int(np.searchsorted(beat_ms, bo["ms"], side="right")) - 1
        if 0 <= idx < n:
            bass_raw[idx] += bo.get("strength", 1.0)

    for hc in harmonic_changes:
        idx = int(np.searchsorted(beat_ms, hc["ms"], side="right")) - 1
        if 0 <= idx < n:
            harmonic_raw[idx] += hc.get("novelty", 1.0)

    def _norm(arr):
        m = float(arr.max())
        return (arr / m).tolist() if m > 0 else arr.tolist()

    return _norm(onset_raw), _norm(bass_raw), _norm(harmonic_raw)


def _needs_backfill(beats: list[dict]) -> bool:
    """Return True if any beat is missing the computed score fields or all are 0.0.
    Note: rms_bass is NOT checked here — it is computed during the original librosa
    analysis (_compute_beat_rms) and is already present in all beat records."""
    if not beats:
        return False
    if "onset_score" not in beats[0]:
        return True
    # All-zero means either the song has no events (rare) or not yet computed
    all_zero = all(
        b.get("onset_score", 0.0) == 0.0
        and b.get("bass_onset_score", 0.0) == 0.0
        and b.get("harmonic_score", 0.0) == 0.0
        for b in beats
    )
    return all_zero


def backfill(dry_run: bool = False) -> None:
    paths = sorted(AUDIO_SHAPES_DIR.glob("*.librosa.json"))
    if not paths:
        print("No .librosa.json files found in", AUDIO_SHAPES_DIR)
        return

    updated = skipped = errors = 0

    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  ERROR reading {p.name}: {exc}")
            errors += 1
            continue

        beats           = data.get("beats", [])
        onsets          = data.get("onsets", [])
        bass_onsets     = data.get("bass_onsets", [])
        harmonic_changes = data.get("harmonic_changes", [])

        title = data.get("title", p.stem)

        if not _needs_backfill(beats):
            print(f"  skip  {title}  (scores already present)")
            skipped += 1
            continue

        onset_scores, bass_scores, harmonic_scores = _compute_beat_event_scores(
            beats, onsets, bass_onsets, harmonic_changes,
        )

        for i, b in enumerate(beats):
            b["onset_score"]      = round(onset_scores[i],    3)
            b["bass_onset_score"] = round(bass_scores[i],     3)
            b["harmonic_score"]   = round(harmonic_scores[i], 3)

        data["beats"] = beats

        if dry_run:
            print(f"  DRY   {title}  ({len(beats)} beats, {len(onsets)} onsets, "
                  f"{len(bass_onsets)} bass, {len(harmonic_changes)} harmonics)")
        else:
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"  ok    {title}  ({len(beats)} beats updated)")

        updated += 1

    print(f"\nDone — {updated} updated, {skipped} skipped, {errors} errors"
          + (" (dry run — nothing written)" if dry_run else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill per-beat event scores in .librosa.json files")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
