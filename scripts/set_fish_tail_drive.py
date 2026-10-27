"""One-time migration: turn the fish TAIL DRIVE on for the music Fish scene.

The plan the Admiral approved on 2026-10-26 (data/fish-swim-plan): "tail-
driven swimming with beats as strong as today", with the defaults "the pond
rest is for the music Fish scene only". The effect's own `tail_drive`
default is 0 (the motion before it existed, exactly), so House Fish and any
other fish entry keep today's swimming unless he asks; this script sets
`tail_drive = 1.0` on exactly ONE device entry: the Fish scene's (id
FISH_SCENE_ID, the stable id scripts/seed_fish_scene.py writes, its stored
name confirmed first) Matrix entry running the `fish` effect.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() (AGENTS.md, "Editing an
existing SceneV2 by script"): a model round trip re-serialises every field
and runs the legacy flare migration. Only the one param changes; every other
field on disk is byte-identical. SceneV2 is used to READ only.

Dry run by default; --apply backs the store up to storage/spectra/backups/
scenes-tail-drive-<stamp>.json and writes it atomically. Idempotent.
--revert removes the param again (the entry then follows the effect's own
default, 0). A Fish scene already SHOWING keeps its old value until it next
fires (the engine reads the scene it fired).
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
TARGET = "Matrix"
EFFECT = "fish"
KEY = "tail_drive"
ON = 1.0


def find_entry(store: dict, key: str = KEY) -> tuple[dict, str]:
    """(the raw device entry, a description of what was found). Raises
    SystemExit unless the Fish scene and exactly one Matrix fish entry are
    there."""
    raw = store.get(FISH_SCENE_ID)
    if not isinstance(raw, dict):
        raise SystemExit(f"no scene with id {FISH_SCENE_ID} — refusing to "
                         "guess; check the live store")
    scene = SceneV2(**raw)              # read-only confirmation
    if scene.name != FISH_SCENE_NAME:
        raise SystemExit(f"scene {FISH_SCENE_ID} is named {scene.name!r}, "
                         f"not {FISH_SCENE_NAME!r} — refusing to guess")
    entries = [d for d in raw.get("devices", [])
               if d.get("target") == TARGET and d.get("effect_type") == EFFECT]
    if len(entries) != 1:
        raise SystemExit(f"{scene.name}: expected one {TARGET} entry running "
                         f"{EFFECT!r}, found {len(entries)} — refusing to "
                         "guess")
    entry = entries[0]
    current = (entry.get("params") or {}).get(key)
    return entry, (f"{scene.name} ({FISH_SCENE_ID}) {TARGET} entry "
                   f"{entry.get('id')}: {key}={current!r}")


def main(argv: list[str] | None = None) -> int:
    return run(argv, KEY, ON, "tail-drive", __doc__)


def run(argv: list[str] | None, key: str, value: float, tag: str,
        doc: str) -> int:
    """Set (or, with --revert, remove) one param on the music Fish scene's
    Matrix entry. scripts/set_fish_pond_rest.py runs this for quiet_rest."""
    parser = argparse.ArgumentParser(
        description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry run)")
    parser.add_argument("--revert", action="store_true",
                        help="remove the param again instead")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args(argv)

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    entry, found = find_entry(store, key)
    print(found)
    params = entry.get("params") or {}
    if args.revert:
        if key not in params:
            print(f"no {key} on the entry — nothing to do")
            return 0
        action = f"remove {key}"
    else:
        if params.get(key) == value:
            print(f"already {key}={value} — nothing to do")
            return 0
        action = f"set {key}={value}"
    if not args.apply:
        print(f"DRY RUN — would {action} on the Fish scene's {TARGET} entry "
              "(use --apply). Only that param changes.")
        return 0

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-{tag}-{stamp}.json"
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")

    if args.revert:                            # the ONLY param touched
        del entry["params"][key]
    else:
        entry.setdefault("params", {})[key] = value
    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"{action} on the Fish scene's {TARGET} entry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
