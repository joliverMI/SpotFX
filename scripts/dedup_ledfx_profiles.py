"""
Dedup LedFX-mode profile duplicates.

When SpotFX runs in LedFX song source mode before the title/artist fallback
lookup was added, it auto-creates blank profiles keyed by ledfx:artist:title
for songs that already have a richer spotify:track:XXX profile.

This script:
  1. Finds all profiles whose spotify_uri starts with "ledfx:"
  2. For each, searches for a matching spotify: profile by normalized title/artist
  3. If a match exists:
       - Copies triggers from the ledfx: profile into the spotify: one (if richer)
       - Deletes the ledfx: profile file
  4. Prints a summary

Run from the SpotFX root:
    python scripts/dedup_ledfx_profiles.py [--dry-run]
"""
import json
import sys
from pathlib import Path

PROFILES_DIR = Path("storage/profiles")


def _key(artist: str, title: str) -> str:
    return f"{artist.lower().strip()}::{title.lower().strip()}"


def load_all() -> list[tuple[Path, dict]]:
    results = []
    for p in PROFILES_DIR.glob("*.json"):
        try:
            results.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception as e:
            print(f"  SKIP (parse error): {p.name}: {e}")
    return results


def main(dry_run: bool) -> None:
    if not PROFILES_DIR.exists():
        print("No profiles directory found — nothing to do.")
        return

    all_profiles = load_all()

    ledfx_profiles = [(p, d) for p, d in all_profiles if d.get("spotify_uri", "").startswith("ledfx:")]
    spotify_profiles = [(p, d) for p, d in all_profiles if not d.get("spotify_uri", "").startswith("ledfx:")]

    print(f"Found {len(ledfx_profiles)} ledfx: profile(s), {len(spotify_profiles)} spotify: profile(s).")

    if not ledfx_profiles:
        print("Nothing to do.")
        return

    # Build index of spotify profiles by normalized key
    spotify_index: dict[str, tuple[Path, dict]] = {}
    for p, d in spotify_profiles:
        k = _key(d.get("artist", ""), d.get("title", ""))
        if k:
            spotify_index[k] = (p, d)

    merged = 0
    triggers_copied = 0
    deleted = 0
    no_match = 0

    for ledfx_path, ledfx_data in ledfx_profiles:
        k = _key(ledfx_data.get("artist", ""), ledfx_data.get("title", ""))
        match = spotify_index.get(k)

        if match is None:
            print(f"  NO MATCH: {ledfx_path.name}  (keeping)")
            no_match += 1
            continue

        spotify_path, spotify_data = match
        ledfx_triggers = ledfx_data.get("triggers", [])
        spotify_triggers = spotify_data.get("triggers", [])

        action = "delete"
        if ledfx_triggers and not spotify_triggers:
            action = "merge+delete"

        print(
            f"  DUPLICATE: {ledfx_path.name}\n"
            f"    → matches {spotify_path.name}\n"
            f"    ledfx triggers={len(ledfx_triggers)}, spotify triggers={len(spotify_triggers)}"
            f"  [{action}]"
        )

        if not dry_run:
            if action == "merge+delete":
                spotify_data["triggers"] = ledfx_triggers
                spotify_path.write_text(json.dumps(spotify_data, indent=2), encoding="utf-8")
                triggers_copied += len(ledfx_triggers)
                merged += 1
            ledfx_path.unlink()
            deleted += 1

    print()
    if dry_run:
        print("DRY RUN — no files changed.")
    else:
        print(f"Done: {merged} profile(s) had triggers merged, {deleted} ledfx: file(s) deleted, {no_match} kept (no spotify: match).")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("--- DRY RUN ---")
    main(dry_run)
