"""
SpotFX — Back-fill of AudioShapeMeta.xcorr_windows using the U-Score planner.

Re-plans xcorr windows for captured shapes using the new offline U-Score
algorithm (services.uscore_planner) and writes the results back to each
song's sidecar JSON. Captures per-song timing + window stats to stdout so
the user can inspect the planner's output before live testing.

Usage:
    python -m scripts.backfill_xcorr_windows                         # all songs
    python -m scripts.backfill_xcorr_windows --setlist <id>          # only songs in a Set List's playlist
    python -m scripts.backfill_xcorr_windows --playlist <uri>        # explicit Spotify playlist
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import AUDIO_SHAPES_DIR
from services import uscore_planner


def _playlist_uris(playlist_uri: str) -> set[str]:
    from api.spotify_client import get_spotify
    sp = get_spotify()
    pid = playlist_uri.split(":")[-1]
    uris: set[str] = set()
    offset = 0
    while True:
        page = sp.playlist_items(pid, offset=offset, fields="items(track(uri)),next", limit=100)
        if not page:
            break
        for item in (page.get("items") or []):
            t = (item or {}).get("track") or {}
            uri = t.get("uri")
            if uri:
                uris.add(uri)
        if not page.get("next"):
            break
        offset += 100
    return uris


def _setlist_playlist_uri(setlist_id: str) -> str | None:
    from services import setlist_store
    sl = setlist_store.get_by_id(setlist_id)
    return sl.context_uri if sl else None


def _load_beats(j_path: Path) -> list[int]:
    """Load librosa beats[] from the .librosa.json sidecar (if present)."""
    librosa_path = j_path.with_name(j_path.stem + ".librosa.json")
    if not librosa_path.exists():
        return []
    try:
        data = json.loads(librosa_path.read_text(encoding="utf-8"))
        beats = data.get("beats") or []
        return [int(b.get("ms", 0)) for b in beats if "ms" in b]
    except Exception:
        return []


def _format_windows(windows: list[dict]) -> str:
    lines = []
    for i, w in enumerate(windows):
        marker = " ⚠FORCED" if w.get("force_picked") else ""
        per_band = "/".join(f"{v:.2f}" for v in w.get("u_per_band", []))
        lines.append(
            f"    #{i+1:2d}  {w['start_ms']:6d}-{w['end_ms']:6d}ms  "
            f"U={w['u_score']:.3f}  bpm={w.get('beat_period_ms', 0):.0f}ms  "
            f"per-band=[{per_band}]{marker}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill U-Score xcorr windows")
    parser.add_argument("--setlist", help="Restrict to songs in this Set List's playlist")
    parser.add_argument("--playlist", help="Restrict to songs in this Spotify playlist URI")
    parser.add_argument("--quiet", action="store_true", help="Hide per-window detail; show only summary")
    args = parser.parse_args()

    target_uris: set[str] | None = None
    if args.setlist:
        ctx = _setlist_playlist_uri(args.setlist)
        if not ctx:
            print(f"Set List {args.setlist!r} not found.")
            return
        print(f"Set List {args.setlist} → playlist {ctx}")
        target_uris = _playlist_uris(ctx)
    elif args.playlist:
        target_uris = _playlist_uris(args.playlist)
    if target_uris is not None:
        print(f"Restricting backfill to {len(target_uris)} URIs from playlist.\n")

    if not AUDIO_SHAPES_DIR.exists():
        print(f"No audio shapes dir at {AUDIO_SHAPES_DIR}")
        return

    json_files = sorted(AUDIO_SHAPES_DIR.glob("*.json"))
    print(f"Found {len(json_files)} sidecar JSON files in {AUDIO_SHAPES_DIR}\n")

    stats = {"processed": 0, "with_windows": 0, "skipped": 0, "errors": 0}
    timings: list[tuple[str, float, int]] = []  # (title, seconds, n_windows)

    for j_path in json_files:
        if j_path.name.endswith(".librosa.json"):
            continue
        try:
            data = json.loads(j_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  [skip] {j_path.name}: JSON parse failed — {exc}")
            stats["errors"] += 1
            continue

        if not data.get("capture_complete"):
            stats["skipped"] += 1
            continue

        if target_uris is not None:
            uri = data.get("spotify_uri")
            if uri not in target_uris:
                stats["skipped"] += 1
                continue

        npz_filename = data.get("npz_file")
        if not npz_filename:
            stats["skipped"] += 1
            continue
        npz_path = AUDIO_SHAPES_DIR / npz_filename
        if not npz_path.exists():
            stats["skipped"] += 1
            continue

        try:
            npz = np.load(npz_path)
            timestamps_ms = npz["timestamps_ms"]
            bands = {
                "rms_total": npz["rms_total"],
                "rms_low":   npz["rms_low"],
                "rms_mid":   npz["rms_mid"],
                "rms_high":  npz["rms_high"],
            }
        except Exception as exc:
            print(f"  [error] {j_path.name}: npz load failed — {exc}")
            stats["errors"] += 1
            continue

        beats_ms = _load_beats(j_path)
        duration_ms = int(data.get("duration_ms", 0))
        title = data.get("title", "?")
        artist = data.get("artist", "?")

        t0 = time.monotonic()
        try:
            windows = uscore_planner.plan_uscore_windows(
                timestamps_ms, bands, duration_ms, beats_ms,
            )
        except Exception as exc:
            print(f"  [error] {j_path.name}: planner failed — {exc}")
            stats["errors"] += 1
            continue
        elapsed = time.monotonic() - t0
        timings.append((f"{artist} — {title}", elapsed, len(windows)))

        # Write back to sidecar.
        data["xcorr_windows"] = windows
        data["xcorr_params_hash"] = "uscore-v6"   # round 10: + rms_low_inv + rms_low_deriv bands
        try:
            j_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"  [error] {j_path.name}: write failed — {exc}")
            stats["errors"] += 1
            continue

        stats["processed"] += 1
        if windows:
            stats["with_windows"] += 1

        forced_count = sum(1 for w in windows if w.get("force_picked"))
        beats_count = len(beats_ms)
        print(
            f"  [ok]   {artist} — {title}: {len(windows)} windows "
            f"({elapsed:.2f}s, {beats_count} beats, {forced_count} forced)"
        )
        if not args.quiet and windows:
            print(_format_windows(windows))
        print()

    print()
    print(f"Summary:")
    print(f"  Processed:      {stats['processed']}")
    print(f"  With windows:   {stats['with_windows']}")
    print(f"  Skipped:        {stats['skipped']}")
    print(f"  Errors:         {stats['errors']}")

    if timings:
        total_t = sum(t for _, t, _ in timings)
        avg_t = total_t / len(timings)
        max_t = max(timings, key=lambda x: x[1])
        min_t = min(timings, key=lambda x: x[1])
        win_counts = [n for _, _, n in timings]
        print()
        print(f"Timing:")
        print(f"  Total:      {total_t:.2f}s across {len(timings)} songs")
        print(f"  Average:    {avg_t:.2f}s/song")
        print(f"  Slowest:    {max_t[1]:.2f}s — {max_t[0]}")
        print(f"  Fastest:    {min_t[1]:.2f}s — {min_t[0]}")
        print(f"Window counts: min={min(win_counts)}  median={sorted(win_counts)[len(win_counts)//2]}  max={max(win_counts)}")


if __name__ == "__main__":
    main()
