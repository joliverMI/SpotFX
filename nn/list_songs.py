"""
SpotFX NN -- List songs available for training.

Run: python -m nn.list_songs
     or via VS Code task "NN: List Latin Songs"

Shows all Latin-genre songs and their readiness for NN training:
  READY   - verified + triggers + librosa analysis (usable for training)
  NO-LIB  - verified + triggers but missing librosa analysis
  NO-TRIG - verified but no triggers assigned
  ai-gen  - triggers were AI-generated (not verified)
  emb-gen - triggers were embedded-generated (not verified)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nn.genre_map import map_genre, LATIN


def main():
    profiles_dir = PROJECT_ROOT / "storage" / "profiles"
    audio_shapes_dir = PROJECT_ROOT / "storage" / "audio_shapes"

    # Build set of spotify URIs that have librosa analysis (match by URI, not filename)
    librosa_uris = set()
    for lp in audio_shapes_dir.glob("*.librosa.json"):
        try:
            data = json.loads(lp.read_text(encoding="utf-8"))
            uri = data.get("spotify_uri", "")
            if uri:
                librosa_uris.add(uri)
        except Exception:
            pass

    ready = []          # verified + triggers + librosa
    no_lib = []          # verified + triggers, missing librosa
    verified_no_trig = [] # verified but no triggers
    not_verified = []    # not verified (may have ai/emb triggers or none)

    for profile_path in sorted(profiles_dir.glob("*.json")):
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Genre filter: Latin only
        genres = profile.get("artist_genre", [])
        genre_id = map_genre(genres)
        if genre_id != LATIN:
            continue

        artist = profile.get("artist", "?")
        title = profile.get("title", "?")
        # Sanitize for Windows terminal
        artist = artist.encode("ascii", errors="replace").decode("ascii")
        title = title.encode("ascii", errors="replace").decode("ascii")

        has_triggers = bool(profile.get("triggers"))
        is_verified = profile.get("verified", False)
        is_ai = profile.get("ai_generated", False)
        is_emb = profile.get("embedded_generated", False)

        spotify_uri = profile.get("spotify_uri", "")
        has_librosa = spotify_uri in librosa_uris

        num_triggers = len(profile.get("triggers", []))

        if not is_verified:
            tag = "ai-gen" if is_ai else "emb-gen" if is_emb else "manual"
            not_verified.append((artist, title, num_triggers, has_librosa, tag))
        elif not has_triggers:
            verified_no_trig.append((artist, title, has_librosa))
        elif not has_librosa:
            no_lib.append((artist, title, num_triggers))
        else:
            ready.append((artist, title, num_triggers))

    # Print results
    print(f"\n{'='*65}")
    print(f" Latin Songs for NN Training")
    print(f"{'='*65}")

    print(f"\n READY ({len(ready)}) -- verified + triggers + librosa:")
    if ready:
        for artist, title, n in ready:
            print(f"   {artist[:20]:<20} {title[:30]:<30} {n:>3} triggers")
    else:
        print("   (none)")

    print(f"\n NO-LIB ({len(no_lib)}) -- verified + triggers, needs librosa re-detect:")
    if no_lib:
        for artist, title, n in no_lib:
            print(f"   {artist[:20]:<20} {title[:30]:<30} {n:>3} triggers")
    else:
        print("   (none)")

    if verified_no_trig:
        print(f"\n VERIFIED, NO TRIGGERS ({len(verified_no_trig)}):")
        for artist, title, has_lib in verified_no_trig:
            lib_tag = "has-lib" if has_lib else "no-lib"
            print(f"   {artist[:20]:<20} {title[:30]:<30} [{lib_tag}]")

    print(f"\n NOT VERIFIED ({len(not_verified)}):")
    if not_verified:
        for artist, title, n, has_lib, tag in not_verified:
            lib_tag = "has-lib" if has_lib else "no-lib"
            print(f"   {artist[:20]:<20} {title[:30]:<30} {n:>3} trig [{tag}, {lib_tag}]")
    else:
        print("   (none)")

    total = len(ready) + len(no_lib) + len(verified_no_trig) + len(not_verified)
    print(f"\n{'-'*65}")
    print(f" Total Latin songs: {total}")
    print(f" Ready for training: {len(ready)}")
    if no_lib:
        print(f" Quick wins (verified, just need librosa): {len(no_lib)}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
