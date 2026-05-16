"""
SpotFX — Recapture playlist CLI.

Examples:
  python -m scripts.recapture_playlist --mode all
  python -m scripts.recapture_playlist --mode missing_shape
  python -m scripts.recapture_playlist --devices
  python -m scripts.recapture_playlist --mode missing_shape --play --device Serenity
"""
from __future__ import annotations
import argparse
import logging
import sys

from services import recapture_playlist


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/refresh the SpotFX Recapture playlist.")
    parser.add_argument(
        "--mode",
        choices=["all", "missing_shape", "needs_recapture"],
        default="all",
        help="Which profiles to include (default: all).",
    )
    parser.add_argument("--devices", action="store_true", help="List available Spotify Connect devices and exit.")
    parser.add_argument("--play", action="store_true", help="Start playback after building.")
    parser.add_argument("--device", default=None, help="Device name to play on (default: current active device).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.devices:
        devs = recapture_playlist.list_devices()
        if not devs:
            print("No Spotify Connect devices available. Open Spotify on a device first.")
            return 1
        for d in devs:
            active = " (active)" if d.get("is_active") else ""
            print(f"  {d.get('name','?')!r}  type={d.get('type','?')}  id={d.get('id','?')}{active}")
        return 0

    result = recapture_playlist.build(mode=args.mode)
    print(f"Playlist: {recapture_playlist.PLAYLIST_NAME}")
    print(f"  id:     {result['playlist_id']}")
    print(f"  mode:   {result['mode']}")
    print(f"  tracks: {result['track_count']}")

    if args.play:
        info = recapture_playlist.start_playback(
            playlist_id=result["playlist_id"], device_name=args.device
        )
        print(f"Playback started on {info['device_name']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
