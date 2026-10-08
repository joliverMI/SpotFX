"""Declare the "Big Fish" flare kind on the Fish scene and pool it into every
flare band's "Shape" lane (2026-10-08).

His ask, verbatim: "add a flare to fish, where a really large fish swims
directly across the screen, in the background of the others, and at 60%
brightness (tuneable). ... The speed it goes at is dependant on intensity.
the color should be the 120 to 180 degree rotation of the central color of
the scene, so it contrasts. ... add it to the scene flares and make it
happen half the time". He then clarified the frequency: "when I say 'make
them happen half the time' i mean just generally weight it so it's about as
frequent as the other flares combined, don't build code to hit 50%".

THE KIND: type `big_fish` (spectra/models/scene.py FlareKind) — no jump,
params, gain or hold of its own; brightness (0.6), size and the two
crossing times are the Fish effect's own settings (fx/effects/fish.py's BIG
FISH block, registered in config/effect_params.json). Offset 0: it enters
ON the mark.

FREQUENCY IS THE EXISTING LANE, NOTHING NEW. The only flare weighting the
engine has is a lane: kinds sharing a lane name form a pick-one pool, EVEN
weights (scene_response.resolve_lane_picks). Every Fish flare band already
pools its momentary shape flares — "Fish Swim Burst" and "Reverse
Momentarily (500ms)" — in a lane named "Shape" (scripts/
add_fish_swim_burst_flare.py), so this script adds the big fish to THAT
pool: each flare now picks one of three, so about one flare in three is a
big fish (and each of the other two drops from one in two to one in
three). Exactly "as frequent as the others combined" (one in two) would
need a per-member lane weight, which the engine does not have — stated
here rather than built.

A BAND WITHOUT A "Shape" LANE IS REFUSED BY NAME: attaching the big fish
there alone would make it fire on EVERY flare of that band, which is not
what he asked for. --scene names another scene; the script refuses a scene
whose Matrix (or any) entry does not run Fish, since the kind acts only on
Fish. House Fish has no flare response at all (a house scene), so there is
nothing to add there and the script says so.

NEVER OVERWRITES: an existing "Big Fish" kind of another type is refused; an
identical one is left alone (idempotent). RAW-DICT PATCH, never
scene_store.save() (the add_pulse_flares.py rule: a model round-trip
re-serializes every field); SceneV2 is used only to READ. Mutates exactly:
the scene's `flare_kinds` (+1) and each flare band's `kinds` (+1) and
`kind_lanes` (+1). After --apply it re-reads the file and verifies nothing
else changed.

DEPLOY ORDER: only AFTER the code carrying the big_fish type and Fish's
`big_fish` key is deployed and SPECTRA restarted — an older process cannot
load the new type. Dry-run by default; --apply backs the store up to
storage/spectra/backups/scenes-fish-big-fish-<stamp>.json first; --revert is
the exact inverse. Not run against live storage by this build.
"""
from __future__ import annotations

import argparse
import copy
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

DEFAULT_SCENE = "Fish"
FISH_EFFECT = "fish"
LANE_NAME = "Shape"
KIND = {"name": "Big Fish", "type": "big_fish", "jump": None, "params": {},
        "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0,
        "min_intensity": None, "enabled": True}
NAME = KIND["name"]


def find_scene_id(store: dict, name: str) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene {name!r} not found — refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"scene {name!r} matches {len(matches)} scenes — "
                         "refusing to guess which one")
    return matches[0]


def runs_fish(raw_scene: dict) -> bool:
    for dev in raw_scene.get("devices") or []:
        if dev.get("effect_type") == FISH_EFFECT:
            return True
        if any(step.get("effect_type") == FISH_EFFECT
               for step in dev.get("effect_steps") or []):
            return True
    return False


def flare_bands(raw_scene: dict) -> list[dict]:
    return ((raw_scene.get("responses") or {}).get("flare") or {}).get("bands", [])


def _band_label(i: int, band: dict) -> str:
    return (f"flare band {i} [{band.get('intensity_min')}-"
            f"{band.get('intensity_max')}]")


def patch(raw: dict, *, revert: bool = False) -> list[str]:
    """Mutate `raw` (one scene) in place, forward or revert; return what
    changed, one line each (empty = nothing to do)."""
    kinds = raw.setdefault("flare_kinds", [])
    lines: list[str] = []
    if revert:
        have = [k for k in kinds if k.get("name") == NAME]
        if have and have != [KIND]:
            raise SystemExit(f"{NAME!r} no longer matches what this script "
                             f"wrote ({have}) — refusing to remove it")
        for i, band in enumerate(flare_bands(raw)):
            if NAME in band.get("kinds", {}):
                del band["kinds"][NAME]
                band.get("kind_lanes", {}).pop(NAME, None)
                lines.append(f"{_band_label(i, band)}: {NAME!r} detached")
        if have:
            kinds[:] = [k for k in kinds if k.get("name") != NAME]
            lines.append(f"{NAME!r}: declaration removed")
        return lines
    have = [k for k in kinds if k.get("name") == NAME]
    if have and have[0].get("type") != KIND["type"]:
        raise SystemExit(f"{NAME!r} already exists as type "
                         f"{have[0].get('type')!r} — refusing to overwrite it")
    for i, band in enumerate(flare_bands(raw)):
        if NAME in band.get("kinds", {}):
            continue
        lanes = band.get("kind_lanes") or {}
        pool = [k for k, lane in lanes.items() if lane == LANE_NAME]
        if not pool:
            raise SystemExit(
                f"{_band_label(i, band)} has no {LANE_NAME!r} lane to pool "
                f"{NAME!r} into — refusing: attached alone it would fire on "
                "every flare of that band")
    if not have:
        kinds.append(dict(KIND))
        lines.append(f"{NAME!r}: declared (type=big_fish, offset 0)")
    for i, band in enumerate(flare_bands(raw)):
        band_kinds = band.setdefault("kinds", {})
        if NAME in band_kinds:
            continue
        lanes = band.setdefault("kind_lanes", {})
        pool = [k for k, lane in lanes.items() if lane == LANE_NAME]
        band_kinds[NAME] = 1.0
        lanes[NAME] = LANE_NAME
        lines.append(f"{_band_label(i, band)}: {NAME!r} attached at x1.0 in "
                     f"the {LANE_NAME!r} lane with {', '.join(pool)} — each "
                     f"flare picks one of {len(pool) + 1}")
    return lines


def verify_diff(before: dict, after: dict, sid: str) -> None:
    """Every difference between `before` and `after` must be this script's
    own change on `sid`; raises SystemExit otherwise."""
    if set(before) != set(after):
        raise SystemExit("UNEXPECTED: the scene id set changed")
    for other in before:
        if other != sid and before[other] != after[other]:
            raise SystemExit(f"UNEXPECTED: scene {other} changed")
    b, a = copy.deepcopy(before[sid]), copy.deepcopy(after[sid])
    for side in (b, a):
        side["flare_kinds"] = [k for k in side.get("flare_kinds", [])
                               if k.get("name") != NAME]
        for band in flare_bands(side):
            band.get("kinds", {}).pop(NAME, None)
            band.get("kind_lanes", {}).pop(NAME, None)
    if b != a:
        raise SystemExit("UNEXPECTED: the scene differs beyond the big fish "
                         "declaration and its band attachments")


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--revert", action="store_true",
                        help="exact inverse: remove the declaration and every "
                             "band attachment")
    parser.add_argument("--scene", default=DEFAULT_SCENE,
                        help=f"scene name (default {DEFAULT_SCENE!r}); must "
                             "run Fish")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    args = parser.parse_args(argv)

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to do")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)
    sid = find_scene_id(store, args.scene)
    SceneV2(**store[sid])          # must parse under the current code
    if not runs_fish(store[sid]):
        raise SystemExit(f"{args.scene!r} has no Fish entry — refusing: the "
                         "big fish acts only on Fish")
    if not flare_bands(store[sid]) and not args.revert:
        raise SystemExit(f"{args.scene!r} has no flare bands to attach to — "
                         "nothing to do (a house scene has no flare response)")
    lines = patch(store[sid], revert=args.revert)
    print(f"— {args.scene} ({sid}), {'revert' if args.revert else 'forward'}:")
    for line in lines:
        print("  " + line)
    if not lines:
        print("  nothing to do")
        return 0
    SceneV2(**store[sid])          # the result must parse too
    verify_diff(before, store, sid)
    if not args.apply:
        print("\nDRY RUN — use --apply to write.")
        return 0
    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-fish-big-fish-{stamp}.json"
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")
    _atomic_write(args.scenes_file, store)
    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    verify_diff(json.loads(backup.read_text(encoding="utf-8")), written, sid)
    print("written and verified: only the big fish declaration and its band "
          "attachments changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
