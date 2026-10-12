"""One-time migration: switch the drop Shockwave OFF on the Fish scene.

The Admiral, 2026-10-12: "Shockwave should be a setting that can be toggled
per scene, as well as globally, as well as a global setting for minimum
energy before it is allowed to fire ... Turn it off for fish to test it at
first and leave it on globally for drops over .7 energy."

The per-scene switch is SceneV2.drop_shock_enabled (default True, so every
other scene is untouched — the room's own drop_shock_enabled and
drop_shock_min_energy=0.7 defaults are the "on globally over .7" half and
need no migration). This script sets exactly that one key to false on the
Fish scene (id FISH_SCENE_ID, the stable id scripts/seed_fish_scene.py
writes), confirming the stored name is "Fish" first and refusing to guess
otherwise.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() (AGENTS.md, "Editing an
existing SceneV2 by script"): a model round trip re-serialises every field
and runs the legacy flare migration. Only the one key changes; every other
field on disk is byte-identical. SceneV2 is used to READ only.

Dry run by default; --apply backs the store up to storage/spectra/backups/
scenes-drop-shock-<stamp>.json and writes it atomically. Idempotent. --on
puts it back (the same one key, true). A Fish scene already SHOWING keeps
its old value until it next fires (the engine reads the scene it fired).
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

FISH_SCENE_ID = "80811c53-56ad-552e-bdb5-12028448accc"
FISH_SCENE_NAME = "Fish"
KEY = "drop_shock_enabled"


def plan(store: dict, value: bool) -> tuple[bool, str]:
    """(needs a write, what was found). Raises SystemExit when the Fish
    scene cannot be found by its id with its name."""
    raw = store.get(FISH_SCENE_ID)
    if not isinstance(raw, dict):
        raise SystemExit(f"no scene with id {FISH_SCENE_ID} — refusing to "
                         "guess; check the live store")
    scene = SceneV2(**raw)              # read-only confirmation
    if scene.name != FISH_SCENE_NAME:
        raise SystemExit(f"scene {FISH_SCENE_ID} is named {scene.name!r}, "
                         f"not {FISH_SCENE_NAME!r} — refusing to guess")
    current = bool(raw.get(KEY, True))
    return current != value, f"{scene.name} ({FISH_SCENE_ID}): {KEY}={current}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry run)")
    parser.add_argument("--on", action="store_true",
                        help="switch it back ON instead (the revert)")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args(argv)
    value = bool(args.on)

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    needed, found = plan(store, value)
    print(found)
    if not needed:
        print(f"already {KEY}={value} — nothing to do")
        return 0
    if not args.apply:
        print(f"DRY RUN — would set {KEY}={value} on the Fish scene "
              "(use --apply). Only that key changes.")
        return 0

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-drop-shock-{stamp}.json"
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")

    store[FISH_SCENE_ID][KEY] = value          # the ONLY key touched
    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"set {KEY}={value} on the Fish scene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
