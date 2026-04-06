"""
SpotFX — Re-run librosa analysis on existing WAV files.

Re-analyzes songs that have saved WAV files, adding any new features
(e.g. MFCCs) without re-capturing audio. Safe for existing timing offsets.

Usage:
  python scripts/rerun_librosa.py                              # all songs with WAVs
  python scripts/rerun_librosa.py --uri spotify:track:abc123   # specific song
  python scripts/rerun_librosa.py --dry-run                    # show what would run
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import AUDIO_SHAPES_DIR
from models.audio_shape import AudioShapeMeta

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def find_songs_with_wavs() -> list[tuple[AudioShapeMeta, Path]]:
    """Find all audio shape metadata entries that have a corresponding WAV file."""
    results = []
    for json_path in AUDIO_SHAPES_DIR.glob("*.json"):
        # Skip librosa JSON files
        if json_path.name.endswith(".librosa.json"):
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if "npz_file" not in data or "spotify_uri" not in data:
                continue
            meta = AudioShapeMeta(**data)
            stem = Path(meta.npz_file).stem
            wav = AUDIO_SHAPES_DIR / f"{stem}.wav"
            if wav.exists():
                results.append((meta, wav))
        except Exception:
            continue
    return results


def find_songs_without_wavs() -> list[tuple[str, str, str]]:
    """Find songs that have librosa JSON but no WAV (can't re-analyze)."""
    results = []
    for json_path in AUDIO_SHAPES_DIR.glob("*.json"):
        if json_path.name.endswith(".librosa.json"):
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if "npz_file" not in data:
                continue
            meta = AudioShapeMeta(**data)
            stem = Path(meta.npz_file).stem
            wav = AUDIO_SHAPES_DIR / f"{stem}.wav"
            librosa_json = AUDIO_SHAPES_DIR / f"{stem}.librosa.json"
            if not wav.exists() and librosa_json.exists():
                results.append((meta.spotify_uri, meta.title or "", meta.artist or ""))
        except Exception:
            continue
    return results


def rerun_one(meta: AudioShapeMeta) -> bool:
    """Re-run librosa analysis for a single song. Returns True on success."""
    from services.librosa_service import analyze_sync, has_wav
    if not has_wav(meta):
        logger.warning("No WAV for %s — skipping", meta.title)
        return False
    try:
        t0 = time.perf_counter()
        analyze_sync(meta)
        elapsed = time.perf_counter() - t0
        logger.info("  Analyzed: %s by %s (%.1fs)", meta.title, meta.artist, elapsed)
        return True
    except Exception as e:
        logger.error("  FAILED: %s — %s", meta.title, e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Re-run librosa analysis on existing WAV files")
    parser.add_argument("--uri", type=str, help="Specific Spotify URI to re-analyze")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be analyzed without running")
    args = parser.parse_args()

    songs = find_songs_with_wavs()

    if args.uri:
        songs = [(m, w) for m, w in songs if m.spotify_uri == args.uri]
        if not songs:
            print(f"No WAV found for {args.uri}")
            return

    print(f"\nFound {len(songs)} songs with WAV files")

    if args.dry_run:
        print("\nWould re-analyze:")
        for meta, wav in sorted(songs, key=lambda x: x[0].title or ""):
            stem = Path(meta.npz_file).stem
            librosa_exists = (AUDIO_SHAPES_DIR / f"{stem}.librosa.json").exists()
            status = "update" if librosa_exists else "NEW"
            print(f"  [{status}] {meta.title} by {meta.artist}")

        missing = find_songs_without_wavs()
        if missing:
            print(f"\nSongs with librosa data but NO WAV ({len(missing)} — need re-capture to update):")
            for uri, title, artist in sorted(missing, key=lambda x: x[1]):
                print(f"  {title} by {artist}")
        return

    print()
    success = 0
    failed = 0
    for meta, wav in sorted(songs, key=lambda x: x[0].title or ""):
        if rerun_one(meta):
            success += 1
        else:
            failed += 1

    print(f"\nDone: {success} analyzed, {failed} failed, {len(songs)} total")

    missing = find_songs_without_wavs()
    if missing:
        print(f"\nSongs needing re-capture (no WAV): {len(missing)}")
        for uri, title, artist in sorted(missing, key=lambda x: x[1]):
            print(f"  {title} by {artist}")


if __name__ == "__main__":
    main()
