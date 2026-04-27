"""
SpotFX — One-shot back-fill of AudioShapeMeta.anchor_candidates.

Walks every sidecar JSON in storage/audio_shapes/, loads the matching .npz,
runs services.anchor_detector.detect_anchor_candidates, and writes the
result into the sidecar. Safe to re-run — overwrites the field with fresh
detection results.

Usage:
    python -m scripts.backfill_anchor_candidates
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np

# Add project root to path so we can import config + services
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import AUDIO_SHAPES_DIR
from services import anchor_detector


def main() -> None:
    if not AUDIO_SHAPES_DIR.exists():
        print(f"No audio shapes dir at {AUDIO_SHAPES_DIR}")
        return

    json_files = sorted(AUDIO_SHAPES_DIR.glob("*.json"))
    print(f"Found {len(json_files)} sidecar JSON files in {AUDIO_SHAPES_DIR}")

    stats = {"processed": 0, "with_anchors": 0, "skipped": 0, "errors": 0}

    for j_path in json_files:
        try:
            data = json.loads(j_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  [skip] {j_path.name}: JSON parse failed — {exc}")
            stats["errors"] += 1
            continue

        if not data.get("capture_complete"):
            print(f"  [skip] {j_path.name}: capture incomplete")
            stats["skipped"] += 1
            continue

        npz_filename = data.get("npz_file")
        if not npz_filename:
            print(f"  [skip] {j_path.name}: no npz_file in meta")
            stats["skipped"] += 1
            continue
        npz_path = AUDIO_SHAPES_DIR / npz_filename
        if not npz_path.exists():
            print(f"  [skip] {j_path.name}: npz missing at {npz_path.name}")
            stats["skipped"] += 1
            continue

        try:
            npz = np.load(npz_path)
            anchors = anchor_detector.detect_anchor_candidates(
                npz["timestamps_ms"],
                npz["rms_total"],
                npz["rms_low"],
                npz["rms_high"],
            )
        except Exception as exc:
            print(f"  [error] {j_path.name}: detector failed — {exc}")
            stats["errors"] += 1
            continue

        data["anchor_candidates"] = [c.to_dict() for c in anchors]
        try:
            j_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"  [error] {j_path.name}: write failed — {exc}")
            stats["errors"] += 1
            continue

        title = data.get("title", "?")
        artist = data.get("artist", "?")
        if anchors:
            top = anchors[0]
            print(
                f"  [ok]   {artist} — {title}: {len(anchors)} anchors "
                f"(top: {top.timestamp_ms}ms band={top.band} rise={top.rise_magnitude:.2f} "
                f"uniqueness={top.uniqueness:.2f})"
            )
            stats["with_anchors"] += 1
        else:
            print(f"  [ok]   {artist} — {title}: 0 anchors (no candidates passed thresholds)")
        stats["processed"] += 1

    print()
    print(f"Summary:")
    print(f"  Processed:      {stats['processed']}")
    print(f"  With anchors:   {stats['with_anchors']}")
    print(f"  Without anchors:{stats['processed'] - stats['with_anchors']}")
    print(f"  Skipped:        {stats['skipped']}")
    print(f"  Errors:         {stats['errors']}")


if __name__ == "__main__":
    main()
