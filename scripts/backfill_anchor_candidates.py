"""
SpotFX — One-shot back-fill of AudioShapeMeta.anchor_candidates.

Walks every sidecar JSON in storage/audio_shapes/, loads the matching .npz,
runs services.anchor_detector.detect_anchor_candidates, and writes the
result into the sidecar. Safe to re-run — overwrites the field with fresh
detection results.

Usage:
    python -m scripts.backfill_anchor_candidates                         # all songs
    python -m scripts.backfill_anchor_candidates --setlist <id>          # only songs in a Set List's playlist
    python -m scripts.backfill_anchor_candidates --playlist <playlist_uri>  # explicit Spotify playlist
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Add project root to path so we can import config + services
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import AUDIO_SHAPES_DIR
from services import anchor_detector


def _playlist_uris(playlist_uri: str) -> set[str]:
    """Return the set of Spotify track URIs in a playlist."""
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
    """Look up the context_uri for a Set List by id."""
    from services import setlist_store
    sl = setlist_store.get_by_id(setlist_id)
    return sl.context_uri if sl else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill anchor candidates")
    parser.add_argument("--setlist", help="Restrict to songs in this Set List's playlist")
    parser.add_argument("--playlist", help="Restrict to songs in this Spotify playlist URI")
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
        print(f"Restricting backfill to {len(target_uris)} URIs from playlist.")

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

        # Filter to playlist scope if requested.
        if target_uris is not None:
            uri = data.get("spotify_uri")
            if uri not in target_uris:
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

        # Load librosa tempo (when available) so the beat-twin uniqueness
        # penalty can run. Songs without librosa analysis still get scored;
        # the penalty just no-ops in that case.
        tempo_bpm: float | None = None
        librosa_path = j_path.with_name(j_path.stem + ".librosa.json")
        if librosa_path.exists():
            try:
                lib = json.loads(librosa_path.read_text(encoding="utf-8"))
                tempo_bpm = float(lib.get("tempo_bpm")) if lib.get("tempo_bpm") else None
            except Exception:
                tempo_bpm = None

        try:
            npz = np.load(npz_path)
            anchors = anchor_detector.detect_anchor_candidates(
                npz["timestamps_ms"],
                npz["rms_total"],
                npz["rms_low"],
                npz["rms_high"],
                tempo_bpm=tempo_bpm,
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
