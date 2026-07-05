#!/usr/bin/env python3
"""Flag audio shapes with broken song-time baselines for recapture.

Some captures were saved with timestamps placed beyond the song's end — the
result of a stale Spotify poll poisoning the song_start baseline (see
models.state.interpolated_progress_ms and audio_shape_service._start). Such
shapes render no canvas and fire no triggers. The capture code now prevents
this going forward; this one-shot script flags the shapes already on disk so
they re-record cleanly the next time each song plays.

Detection (per shape, against its sidecar duration_ms):
  - offset_past_end : first sample at/after duration   (Brinca-class)
  - ts_jump         : last sample > 1.2x duration       (mid-capture gap/jump)

By default only offset_past_end shapes are flagged — that is the "no shape,
no triggers" failure. ts_jump shapes have valid in-bounds early data (they
partially render/fire) and new ones are already rejected at capture time, so
they are reported as advisory and only flagged with --include-jumps.

Usage:
  .venv/bin/python scripts/flag_bad_timestamp_shapes.py                   # dry run
  .venv/bin/python scripts/flag_bad_timestamp_shapes.py --apply           # flag offset_past_end
  .venv/bin/python scripts/flag_bad_timestamp_shapes.py --apply --include-jumps
"""
from __future__ import annotations
import sys
import glob
import json
import os

import numpy as np

# Run from the repo root so config/AUDIO_SHAPES_DIR resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import AUDIO_SHAPES_DIR  # noqa: E402
from services.audio_analyzer import flag_needs_recapture  # noqa: E402

JUMP_FACTOR = 1.2  # ts_last beyond this multiple of duration → mid-capture jump


def classify(npz_path: str) -> tuple[str, dict] | None:
    """Return (reason, info) if the shape is broken, else None."""
    sidecar = npz_path[:-4] + ".json"
    if not os.path.exists(sidecar):
        return None
    meta = json.loads(open(sidecar, encoding="utf-8").read())
    dur = int(meta.get("duration_ms") or 0)
    if dur <= 0:
        return None
    ts = np.load(npz_path)["timestamps_ms"]
    tmin, tmax = int(ts.min()), int(ts.max())
    info = {"uri": meta.get("spotify_uri", ""), "dur": dur, "tmin": tmin, "tmax": tmax}
    if tmin >= dur:
        return "offset_past_end", info
    if tmax > dur * JUMP_FACTOR:
        return "ts_jump", info
    return None


def main() -> int:
    apply = "--apply" in sys.argv
    include_jumps = "--include-jumps" in sys.argv
    broken: list[tuple[str, str, dict]] = []
    for npz_path in sorted(glob.glob(str(AUDIO_SHAPES_DIR / "*.npz"))):
        name = os.path.basename(npz_path)[:-4]
        try:
            res = classify(npz_path)
        except Exception as exc:
            print(f"  ERR  {name}: {exc}")
            continue
        if res:
            broken.append((name, res[0], res[1]))

    if not broken:
        print("No broken-timestamp shapes found.")
        return 0

    # ts_jump shapes are only flagged with --include-jumps; offset_past_end
    # is the reported "no shape / no triggers" bug and is always in scope.
    def in_scope(reason: str) -> bool:
        return reason == "offset_past_end" or include_jumps

    print(f"{'APPLYING' if apply else 'DRY RUN'} — {len(broken)} broken shape(s) "
          f"(scope: offset_past_end{' + ts_jump' if include_jumps else ''}):\n")
    flagged = 0
    for name, reason, info in broken:
        scoped = in_scope(reason)
        line = (f"  [{reason:14s}] {name[:46]:46s} "
                f"dur={info['dur']:<7d} ts=[{info['tmin']}..{info['tmax']}]")
        if not scoped:
            print(line + "  -> advisory (use --include-jumps to flag)")
        elif apply:
            uri = info["uri"]
            ok = flag_needs_recapture(uri, reason) if uri else False
            print(line + ("  -> flagged" if ok else "  -> FAILED (no uri/index miss)"))
            flagged += int(ok)
        else:
            print(line)

    if apply:
        print(f"\nFlagged {flagged} shape(s) for recapture. "
              "They re-record next time each song plays on the target device.")
    else:
        print("\nDry run only. Re-run with --apply to flag the in-scope shapes for recapture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
