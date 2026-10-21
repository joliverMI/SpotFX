#!/usr/bin/env python3
"""Absorb Music's bar against HIS REAL shapes, read-only
(data/absorb-music-plan/report.md §12 phase 1 acceptance: "a 20-song queue
classifies correctly against his real sidecars").

  .venv/bin/python scripts/check_absorb_classify.py \
      [--shapes-dir /home/javi/SpotFX/storage/audio_shapes] [--count 20]

What it does, writing nothing anywhere:

1. picks a deterministic 20-song mix out of his library — songs that pass,
   songs missing their head, songs with no librosa, failed attempts, songs
   whose shape starts past their own end, songs with no shape at all;
2. classifies each with services/absorb_bar.py (the runner's own bar);
3. classifies each AGAIN with an independent reading written here straight
   from the report's §8.2 text (raw JSON, the npz's own timestamps) and
   fails if the two ever disagree;
4. orders the 20 the way a window would (fresh first, then worst head
   first) and prints the queue;
5. prints the whole library's split beside the plan's 2026-10-20 numbers
   (344 pass / 817 re-capture — they drift as he plays).

Exit 0 when every song agrees, 1 on a disagreement, 2 when the directory
is missing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DIR = "/home/javi/SpotFX/storage/audio_shapes"
HEAD_MAX_MS = 1000


def independent(sidecar: Path | None, d: Path) -> tuple[str, int | None]:
    """The §8.2 bar, read straight off the files, sharing no code with
    services/absorb_bar.py."""
    if sidecar is None:
        return "fresh", None
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    if not data.get("capture_complete"):
        return "fresh", None
    npz_name = data.get("npz_file") or sidecar.stem + ".npz"
    npz = d / npz_name
    first = None
    if npz.exists():
        try:
            first = int(np.load(npz)["timestamps_ms"][0])
        except Exception:
            first = None
    stem = npz_name[:-4] if npz_name.endswith(".npz") else npz_name
    passes = (not data.get("capture_failed")
              and npz.exists()
              and int(data.get("librosa_version") or 0) >= 2
              and (d / f"{stem}.librosa.json").exists()
              and first is not None
              and first <= HEAD_MAX_MS
              and first < int(data.get("duration_ms") or 0)
              and not data.get("needs_recapture"))
    return ("skip" if passes else "recapture"), first


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shapes-dir", default=DEFAULT_DIR)
    ap.add_argument("--count", type=int, default=20)
    args = ap.parse_args()
    d = Path(args.shapes_dir)
    if not d.is_dir():
        print(f"no shapes directory at {d}")
        return 2

    import config
    import services.audio_analyzer as aa
    from services import absorb_bar
    from services.absorb import order_work
    for mod in (config, aa, absorb_bar):
        mod.AUDIO_SHAPES_DIR = d

    sidecars: dict[str, Path] = {}
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".librosa.json") or ".bak" in p.name:
            continue
        try:
            u = json.loads(p.read_text(encoding="utf-8")).get("spotify_uri") or ""
        except Exception:
            continue
        if u.startswith("spotify:track:"):
            sidecars.setdefault(u, p)

    library = {"skip": 0, "recapture": 0, "fresh": 0}
    buckets: dict[str, list[str]] = {}
    for u, p in sidecars.items():
        kind, first = independent(p, d)
        library[kind] += 1
        data = json.loads(p.read_text(encoding="utf-8"))
        if kind == "skip":
            b = "pass"
        elif kind == "fresh":
            b = "failed" if data.get("capture_failed") else "incomplete"
        elif first is not None and first >= int(data.get("duration_ms") or 0):
            b = "renders_nothing"
        elif int(data.get("librosa_version") or 0) < 2:
            b = "no_librosa"
        elif first is not None and first > HEAD_MAX_MS:
            b = "headless"
        else:
            b = "other_recapture"
        buckets.setdefault(b, []).append(u)

    # a deterministic mix, every bucket represented, then topped up
    picks: list[str] = []
    order = ["pass", "headless", "no_librosa", "renders_nothing", "failed",
             "incomplete", "other_recapture"]
    i = 0
    while len(picks) < args.count - 2 and any(buckets.get(b) for b in order):
        b = order[i % len(order)]
        if buckets.get(b):
            picks.append(buckets[b].pop(0))
        i += 1
    picks += ["spotify:track:absorbcheck000000000000", "spotify:track:absorbcheck000000000001"]

    disagree = 0
    verdicts = []
    print(f"{'uri':<40} {'bar':<10} {'independent':<12} head_ms  reasons")
    for u in picks:
        v = absorb_bar.classify(u, HEAD_MAX_MS)
        mine, first = independent(sidecars.get(u), d)
        flag = "" if v.kind == mine else "   <-- DISAGREE"
        disagree += v.kind != mine
        verdicts.append(v)
        print(f"{u:<40} {v.kind:<10} {mine:<12} {str(v.head_ms):>7}  "
              f"{','.join(v.reasons)}{flag}")

    queue = order_work(verdicts, "fresh_first")
    print(f"\nwindow order (fresh first, then worst head first): {len(queue)} songs")
    for n, u in enumerate(queue, 1):
        v = next(x for x in verdicts if x.uri == u)
        print(f"  {n:>2}. {v.kind:<10} missing {v.missing_ms:>7} ms  {v.title or u}")

    print(f"\nlibrary ({len(sidecars)} shapes): {library['skip']} pass, "
          f"{library['recapture']} re-capture, {library['fresh']} failed/incomplete"
          f"   (plan, 2026-10-20: 344 pass / 817 re-capture)")
    if disagree:
        print(f"\nFAIL: {disagree} song(s) classified differently")
        return 1
    print(f"\nOK: all {len(picks)} songs agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
