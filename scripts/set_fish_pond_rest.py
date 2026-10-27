"""One-time migration: turn the fish POND REST on for the music Fish scene.

The plan the Admiral approved on 2026-10-26 (data/fish-swim-plan): "a quiet
pond rest with occasional darts", with the defaults "the pond rest is for
the music Fish scene only; 'quiet' means the music's own level". The
effect's own `quiet_rest` default is 0 (the motion before it existed,
exactly), so House Fish and every other fish entry are untouched; this sets
`quiet_rest = 1.0` on exactly the music Fish scene's Matrix entry, the same
entry, guards and raw single-param patch as scripts/set_fish_tail_drive.py.
The rest works with the tail drive off too, but the plan measured the two
together, so the music Fish runs that script as well.

Dry run by default; --apply backs the store up to storage/spectra/backups/
scenes-pond-rest-<stamp>.json and writes it atomically. Idempotent.
--revert removes the param again. A Fish scene already SHOWING keeps its old
value until it next fires.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import set_fish_tail_drive as entry  # noqa: E402

FISH_SCENE_ID = entry.FISH_SCENE_ID
KEY = "quiet_rest"
ON = 1.0


def main(argv: list[str] | None = None) -> int:
    return entry.run(argv, KEY, ON, "pond-rest", __doc__)


if __name__ == "__main__":
    raise SystemExit(main())
