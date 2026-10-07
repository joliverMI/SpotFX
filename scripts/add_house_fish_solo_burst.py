"""One-time migration: turn the SOLO BURST on in his "House Fish" scene.

HIS WORDS (2026-10-06): "In house fish scene, give individual ones an
occasional burst of speed." The mechanism is the fish effect's own
`solo_burst_rate` / `solo_burst_speed` / `solo_burst_time`
(fx/effects/fish.py, the SOLO BURST block), and its schema default rate is
0 — never — so the music "Fish" scene and every other fish entry are
untouched. Only THIS scene's own Matrix fish entry turns it on, with the
values in SOLO_BURST_PARAMS below (also what scripts/seed_house_lighting.py
seeds, and what scripts/check_fish_wall.py measures).

He saved House Fish himself on 2026-10-06 (5 fish, size 6, speed 0.16 —
not the seeder's starting 3 / 4.0 / 0.08), so re-running the house seeder
would leave his scene alone (it keeps an entry he has edited). This script
is the narrow edit instead: it adds the three keys to that one entry's
`params` and touches nothing else.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — the same reason as
scripts/set_scene_colorset_preference.py: a model round-trip re-serializes
every field (and runs the legacy flare migration shim) on the whole scene.
The scene is only READ through SceneV2 (validation, diagnostics); the write
sets three keys on the raw dict entry. A value he has already set for any
of the three is KEPT, never overwritten — so the script is idempotent and
can never undo his tuning.

Dry-run by default; --apply backs the store up to
storage/spectra/backups/scenes-house-fish-solo-burst-<stamp>.json and writes
it atomically (tmp + replace, indent=2 — scene_store's own on-disk format).
The store is read fresh by every scene fire, so the next fire of House Fish
picks it up; the effect only understands the keys once the fish change that
introduced them is deployed (until then they are inert extra keys).

    .venv/bin/python scripts/add_house_fish_solo_burst.py            # dry run
    .venv/bin/python scripts/add_house_fish_solo_burst.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402

SCENE_NAME = "House Fish"
# about one dash every fifteen seconds somewhere in a shoal of five, each a
# real sprint (two and a half times its calm pace) held for most of a
# second before it eases back — calm enough for the night light
SOLO_BURST_PARAMS = {
    "solo_burst_rate": 4.0,
    "solo_burst_speed": 2.5,
    "solo_burst_time": 0.8,
}


def plan(store: dict) -> tuple[str, int, dict]:
    """(scene id, device index, the keys to add) for the one House Fish
    Matrix fish entry. Refuses by name rather than guessing."""
    matches = [sid for sid, raw in store.items() if raw.get("name") == SCENE_NAME]
    if not matches:
        raise SystemExit(f"no scene named {SCENE_NAME!r} — refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"{len(matches)} scenes named {SCENE_NAME!r} — "
                         "refusing to guess which one")
    sid = matches[0]
    SceneV2(**store[sid])   # read-only: it must still load as a scene
    entries = [
        i for i, dev in enumerate(store[sid].get("devices", []))
        if dev.get("effect_type") == "fish"
    ]
    if len(entries) != 1:
        raise SystemExit(f"{SCENE_NAME!r} has {len(entries)} fish entries — "
                         "expected exactly one; refusing to guess")
    di = entries[0]
    params = store[sid]["devices"][di].get("params") or {}
    add = {k: v for k, v in SOLO_BURST_PARAMS.items() if k not in params}
    return sid, di, add


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    sid, di, add = plan(store)
    params = store[sid]["devices"][di].get("params") or {}
    print(f"{SCENE_NAME} ({sid}), device {di} "
          f"({store[sid]['devices'][di].get('target')}, fish):")
    for key in SOLO_BURST_PARAMS:
        if key in add:
            print(f"  + {key} = {add[key]}")
        else:
            print(f"    {key} = {params[key]} (already set — kept)")
    if not add:
        print("nothing to do")
        return
    if not args.apply:
        print(f"DRY RUN — would add {len(add)} key(s) to that one entry's "
              "params (use --apply); nothing else in the store changes")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-house-fish-solo-burst-{stamp}.json"
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")

    entry = store[sid]["devices"][di]
    entry["params"] = dict(entry.get("params") or {}, **add)
    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"added {len(add)} key(s) to {SCENE_NAME}'s fish entry")


if __name__ == "__main__":
    main()
