"""Declare the two Pulse flare kinds on the Pulse test scene and attach them
to every flare band (single-led-power plan, phase 3).

His goal 7, verbatim: "Flares should include things like a temporary color
rotation by 180 for the beat onset and fade out, but only at intensities
greater than .4. as well as brightness spikes, that jump in brightness and
then quickly fade to normal." The plan's prototype ran exactly this
placement: a flash on every flare, the colour flip only above 0.4.

  "Pulse Flash"        type pulse_flash — the light jumps and fades back in
                       about 180 ms (Pulse's flash_size / flash_ms)
  "Pulse Colour Flip"  type pulse_flip, min_intensity 0.4 — the colour turns
                       180 degrees at once, holds, and swings back round the
                       wheel (Pulse's flip_degrees / flip_hold_s / flip_fade_s,
                       0.5s hold + 1.0s fade by default — fixed seconds, not
                       beats)

Both are attached at x1.0 directly to every band of the scene's "flare"
response — NOT in a lane, so they fire alongside the band's other kinds
rather than as alternatives to them.

ONLY A SCENE THAT RUNS PULSE. The default target is the tuning scene "Pulse
Test (Orbits V2)" (scripts/seed_pulse_test_scene.py). --scene names another,
and the script REFUSES any scene with no Pulse entry: the kinds act only on
Pulse, and moving a real scene over is phase 4, after his tuning.

RAW-DICT PATCH, never scene_store.save() — the add_fireworks_burst_flare.py
rule: a model round-trip re-serializes every field. SceneV2 is used only to
READ (the store must parse before, and the result after). Exactly two things
change on exactly one scene: `flare_kinds` gains the two entries and each
flare band's `kinds` gains the two keys; the write is re-read and the diff
verified structurally against the backup.

DEPLOY ORDER: run only AFTER the code carrying the pulse_flash / pulse_flip
types is deployed and SPECTRA restarted — an older process cannot load the
new types. Dry-run by default; --apply writes (atomic tmp+replace, indent=2)
after copying the store to storage/spectra/backups/scenes-pulse-flares-
<stamp>.json; --revert is the exact inverse. Not run by the build.
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

DEFAULT_SCENE = "Pulse Test (Orbits V2)"
PULSE_EFFECT = "pulse"
NEW_KINDS = [
    {"name": "Pulse Flash", "type": "pulse_flash", "jump": None,
     "params": {}, "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0,
     "min_intensity": None, "enabled": True},
    {"name": "Pulse Colour Flip", "type": "pulse_flip", "jump": None,
     "params": {}, "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0,
     "min_intensity": 0.4, "enabled": True},
]
NAMES = [k["name"] for k in NEW_KINDS]


def find_scene_id(store: dict, name: str) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene {name!r} not found — refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"scene {name!r} matches {len(matches)} scenes — "
                         "refusing to guess which one")
    return matches[0]


def runs_pulse(raw_scene: dict) -> bool:
    for dev in raw_scene.get("devices") or []:
        if dev.get("effect_type") == PULSE_EFFECT:
            return True
        if any(step.get("effect_type") == PULSE_EFFECT
               for step in dev.get("effect_steps") or []):
            return True
    return False


def flare_bands(raw_scene: dict) -> list[dict]:
    return ((raw_scene.get("responses") or {}).get("flare") or {}).get("bands", [])


def patch(store: dict, sid: str, *, revert: bool = False) -> list[str]:
    """Mutate `store[sid]` in place (forward or revert); return what changed,
    one line each (empty = nothing to do)."""
    raw = store[sid]
    kinds = raw.setdefault("flare_kinds", [])
    lines: list[str] = []
    if revert:
        for spec in NEW_KINDS:
            have = [k for k in kinds if k.get("name") == spec["name"]]
            if not have:
                continue
            if have != [spec]:
                raise SystemExit(f"{spec['name']!r} no longer matches what this "
                                 f"script wrote ({have}) — refusing to remove it")
            kinds[:] = [k for k in kinds if k.get("name") != spec["name"]]
            lines.append(f"{spec['name']!r}: declaration removed")
        for i, band in enumerate(flare_bands(raw)):
            for name in NAMES:
                if name in band.get("kinds", {}):
                    del band["kinds"][name]
                    lines.append(f"flare band {i}: {name!r} detached")
        return lines
    for spec in NEW_KINDS:
        have = [k for k in kinds if k.get("name") == spec["name"]]
        if have:
            if have[0].get("type") != spec["type"]:
                raise SystemExit(f"{spec['name']!r} already exists as type "
                                 f"{have[0].get('type')!r} — refusing to "
                                 "overwrite it")
            continue
        kinds.append(dict(spec))
        lines.append(f"{spec['name']!r}: declared (type={spec['type']}"
                     + (f", only above intensity {spec['min_intensity']}"
                        if spec["min_intensity"] is not None else "") + ")")
    for i, band in enumerate(flare_bands(raw)):
        band_kinds = band.setdefault("kinds", {})
        for name in NAMES:
            if name in band_kinds:
                continue
            band_kinds[name] = 1.0
            lines.append(f"flare band {i} [{band.get('intensity_min')}-"
                         f"{band.get('intensity_max')}]: {name!r} attached at "
                         "x1.0 (directly, not in a lane)")
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
                               if k.get("name") not in NAMES]
        for band in flare_bands(side):
            for name in NAMES:
                band.get("kinds", {}).pop(name, None)
    if b != a:
        raise SystemExit("UNEXPECTED: the scene differs beyond the two "
                         "declarations and their band attachments")


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
                        help="exact inverse: remove both declarations and "
                             "every band attachment")
    parser.add_argument("--scene", default=DEFAULT_SCENE,
                        help=f"scene name (default {DEFAULT_SCENE!r}); must "
                             "run Pulse")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    args = parser.parse_args(argv)

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to do")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)
    sid = find_scene_id(store, args.scene)
    SceneV2(**store[sid])          # must parse under the current code
    if not runs_pulse(store[sid]):
        raise SystemExit(f"{args.scene!r} has no Pulse entry — refusing: these "
                         "flares act only on Pulse, and moving a scene over "
                         "to Pulse is phase 4")
    if not flare_bands(store[sid]) and not args.revert:
        raise SystemExit(f"{args.scene!r} has no flare bands to attach to")
    lines = patch(store, sid, revert=args.revert)
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
    backup = backup_dir / f"scenes-pulse-flares-{stamp}.json"
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")
    _atomic_write(args.scenes_file, store)
    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    verify_diff(json.loads(backup.read_text(encoding="utf-8")), written, sid)
    print("written and verified: only the two declarations and their band "
          "attachments changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
