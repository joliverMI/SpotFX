"""
SpotFX — Re-run librosa analysis on existing WAV files.

Re-analyzes songs that have saved WAV files, adding any new features
(e.g. MFCCs) without re-capturing audio. Safe for existing timing offsets.

Usage:
  python scripts/rerun_librosa.py                              # all songs with WAVs
  python scripts/rerun_librosa.py --uri spotify:track:abc123   # specific song
  python scripts/rerun_librosa.py --uris uri1,uri2             # explicit list
  python scripts/rerun_librosa.py --training-profiles          # songs in storage/training_profiles.json
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


# rerun_one() outcomes:
#   "ok"        — analysis succeeded, librosa.json written.
#   "vanished"  — the WAV existed at listing time but was gone (or became
#                 unreadable) by the time analysis reached it. This is the
#                 signature of a concurrent capture racing a batch rerun on
#                 the same wav_path (the live app used to overwrite the file
#                 in place — fixed by the atomic write-then-rename in
#                 audio_shape_service._save_wav_and_analyze). Transient: the
#                 song should just work on a later rerun once nothing else is
#                 writing to it.
#   "corrupt"   — the WAV was still present and unchanged after the failure,
#                 so the failure reflects the file's actual content, not a
#                 race. Needs re-capture; not retried here.
RerunOutcome = str  # "ok" | "vanished" | "corrupt"


def rerun_one(meta: AudioShapeMeta) -> RerunOutcome:
    """Re-run librosa analysis for a single song. Never retries — a single
    attempt per song, classified so the caller can say plainly what happened."""
    from services.librosa_service import analyze_sync, has_wav
    if not has_wav(meta):
        logger.warning("No WAV for %s — skipping", meta.title)
        return "vanished"
    try:
        t0 = time.perf_counter()
        analyze_sync(meta)
        elapsed = time.perf_counter() - t0
        logger.info("  Analyzed: %s by %s (%.1fs)", meta.title, meta.artist, elapsed)
        return "ok"
    except Exception as e:
        if has_wav(meta):
            logger.error("  FAILED (corrupt/unreadable WAV, still present): %s — %s", meta.title, e)
            return "corrupt"
        logger.error("  FAILED (WAV vanished mid-run, likely a concurrent capture): %s — %s", meta.title, e)
        return "vanished"


def training_profile_uris() -> set[str]:
    """Union of training + embedded-only URIs across all training profiles."""
    tp_path = PROJECT_ROOT / "storage" / "training_profiles.json"
    uris: set[str] = set()
    for prof in json.loads(tp_path.read_text(encoding="utf-8")).values():
        uris.update(prof.get("training_uris") or [])
        uris.update(prof.get("embedded_only_uris") or [])
    return uris


def main():
    parser = argparse.ArgumentParser(description="Re-run librosa analysis on existing WAV files")
    parser.add_argument("--uri", type=str, help="Specific Spotify URI to re-analyze")
    parser.add_argument("--uris", type=str, help="Comma-separated list of Spotify URIs")
    parser.add_argument("--training-profiles", action="store_true",
                        help="Restrict to songs referenced by storage/training_profiles.json")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be analyzed without running")
    args = parser.parse_args()

    songs = find_songs_with_wavs()

    wanted: set[str] | None = None
    if args.uri:
        wanted = {args.uri}
    elif args.uris:
        wanted = {u.strip() for u in args.uris.split(",") if u.strip()}
    elif args.training_profiles:
        wanted = training_profile_uris()
        print(f"Training profiles reference {len(wanted)} unique URIs")
    if wanted is not None:
        songs = [(m, w) for m, w in songs if m.spotify_uri in wanted]
        if not songs:
            print("No matching songs with WAVs found")
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
    vanished: list[AudioShapeMeta] = []
    corrupt: list[AudioShapeMeta] = []
    for meta, wav in sorted(songs, key=lambda x: x[0].title or ""):
        outcome = rerun_one(meta)
        if outcome == "ok":
            success += 1
        elif outcome == "vanished":
            vanished.append(meta)
        else:
            corrupt.append(meta)

    failed = len(vanished) + len(corrupt)
    print(f"\nDone: {success} analyzed, {failed} failed, {len(songs)} total")

    if vanished:
        print(f"\nExpected to recover on rerun ({len(vanished)} — WAV vanished mid-run, "
              f"likely a concurrent capture; re-run just these once nothing else is capturing):")
        for meta in sorted(vanished, key=lambda m: m.title or ""):
            print(f"  {meta.title} by {meta.artist}")

    if corrupt:
        print(f"\nGenuinely unrecoverable without re-capture ({len(corrupt)} — WAV present "
              f"but unreadable/corrupt):")
        for meta in sorted(corrupt, key=lambda m: m.title or ""):
            print(f"  {meta.title} by {meta.artist}")

    missing = find_songs_without_wavs()
    if missing:
        print(f"\nSongs needing re-capture (no WAV): {len(missing)}")
        for uri, title, artist in sorted(missing, key=lambda x: x[1]):
            print(f"  {title} by {artist}")


if __name__ == "__main__":
    main()
