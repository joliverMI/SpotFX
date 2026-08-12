"""
Backfill SongProfile.intensity_scale from the v2 auto formula (genre-anchored
bass rank — see services/intensity_scale_service.py).

For every stored profile:
  - source "user" is NEVER touched (the manual Now Playing slider wins);
  - songs with capture + librosa data get the auto value (source "auto");
  - songs without data get the genre starting value (source "genre");
  - existing auto/genre stamps are recomputed (idempotent — reruns after
    genre-slider changes update every non-user song).

Dry-run by default: prints the distribution and the biggest movers.
--apply first copies storage/profiles/ to storage/backups/
profiles-preintensityscale-<stamp>/ then writes atomically (tmp + replace),
operating on the raw JSON docs so unknown/legacy fields survive untouched.

USAGE
  .venv/bin/python scripts/backfill_intensity_scale.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROFILES_DIR                                    # noqa: E402
from services.intensity_scale_service import (                     # noqa: E402
    compute_auto_scale, resolve_genre_scale,
)

BACKUPS_DIR = Path("storage/backups")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    updated: list[tuple[Path, dict, float | None, float, str]] = []  # path, doc, old, new, src
    user_kept = 0
    skipped: list[str] = []

    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            skipped.append(f"{path.name}: unreadable ({e})")
            continue
        uri = doc.get("spotify_uri")
        if not uri:
            skipped.append(f"{path.name}: no spotify_uri")
            continue
        if doc.get("intensity_scale_source") == "user":
            user_kept += 1
            continue
        genres = list(doc.get("artist_genre") or [])
        new = compute_auto_scale(uri, genres or None)
        src = "auto"
        if new is None:
            new = round(resolve_genre_scale(genres), 3)
            src = "genre"
        old = doc.get("intensity_scale")
        if old == new and doc.get("intensity_scale_source") == src:
            continue
        doc["intensity_scale"] = new
        doc["intensity_scale_source"] = src
        updated.append((path, doc, old, new, src))

    news = [n for _, _, _, n, _ in updated]
    n_auto = sum(1 for u in updated if u[4] == "auto")
    print(f"profiles: {len(list(PROFILES_DIR.glob('*.json')))}  "
          f"to update: {len(updated)} (auto {n_auto}, genre {len(updated) - n_auto})  "
          f"user kept: {user_kept}  skipped: {len(skipped)}")
    if news:
        qs = statistics.quantiles(news, n=4)
        print(f"new values: min {min(news):.2f}  p25 {qs[0]:.2f}  median {qs[1]:.2f}  "
              f"p75 {qs[2]:.2f}  max {max(news):.2f}")
        by_val = sorted(updated, key=lambda u: u[3])
        print("\nlowest 8:")
        for path, _, old, new, src in by_val[:8]:
            print(f"  {new:.2f} ({src}, was {old})  {path.stem}")
        print("highest 8:")
        for path, _, old, new, src in by_val[-8:]:
            print(f"  {new:.2f} ({src}, was {old})  {path.stem}")
    for s in skipped[:10]:
        print("  skipped: " + s)

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUPS_DIR / f"profiles-preintensityscale-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROFILES_DIR, backup)
    print(f"\nbacked up profiles -> {backup}")

    for path, doc, _, _, _ in updated:
        tmp = path.with_suffix(".json.tmp")
        # ensure_ascii (json.dumps default) matches the app's \uXXXX escapes.
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        tmp.replace(path)
    print(f"wrote {len(updated)} profiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
