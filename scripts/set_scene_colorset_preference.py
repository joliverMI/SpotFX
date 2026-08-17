"""One-time migration: set his four named scenes' PREFERRED COLOUR SET MODE
to "dark" (spectra/models/scene.py SceneV2.preferred_color_set_mode, owner
ask 2026-08-17 — see spectra/services/mode_availability.color_set_preferred()
for the resolution rule this field drives).

His words: "black hole would prefer dark mode color sets. This means you
don't have to change any color sets. We just set black hole, fireworks,
and Dancer to having a preference for dark mode color sets." A follow-up
confirmed a SECOND Black Hole scene ("Black Hole V2 UI") gets the same
preference — four scenes, not three:

    Black Hole V2, Black Hole V2 UI, Fireworks V2, Dancers V2

"Black Hole V2 UI" is structurally thinner than its sibling — worth reading
before assuming it's an equal, fired scene rather than a work-in-progress:
it targets a Particles device entry where "Black Hole V2" targets Matrix,
it carries noticeably fewer flare kinds once loaded, and nothing outside
scenes.json (no scene id search anywhere else in storage) references it.
He was told this and said yes regardless — this script still sets its
preference — but the note stays here for whoever reads this migration
later.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save(): loading a scene
through SceneV2 and writing it back via model_dump_json() re-serializes
EVERY field in its current canonical form — in particular it runs the
legacy flare-band migration shim (_migrate_flare_kinds) and permanently
rewrites param_patch/gain/reroll_dice/color_set_jump into the newer
flare_kinds/kinds shape, even though the model asserts the two are
behaviourally equivalent. That is a far bigger change than "set one field"
and is exactly what the task's "do not modify his scenes beyond setting
the preference" boundary rules out — caught by diffing this script's own
first draft's before/after JSON and reverted before shipping. This script
instead loads the RAW JSON dict, uses SceneV2 only to READ (name matching,
the current value, the diagnostic printout below), and writes back by
setting exactly one key, `preferred_color_set_mode`, on the untouched raw
dict entry — every other key byte-identical to what was on disk.

THE FALLBACK THAT MUST NOT GO WRONG: this script only sets a PREFERENCE. It
does not mark any colour set light or dark — measured 2026-08-17, his real
color_sets.json has 0 of 50 sets carrying a dark_variant/light_variant and
0 of 58 cards (sets + groups) carrying a non-null display_availability. A
preference that finds nothing marked must fall back to the FULL unfiltered
selection, never an empty one — spectra/services/mode_availability.
color_set_preferred() guarantees this by treating an unmarked
("default"-availability) colour set as matching every preference (see its
own docstring + tests/test_color_set_preference.py's
test_eligible_sets_finds_nothing_new_while_every_set_is_unmarked, which
proves it against zero marked sets rather than asserting it). So running
this script changes NOTHING about what colours these four scenes draw from
until he separately marks some colour sets dark/light on the Colours page
(ColorSetsPage.tsx's existing ModeAvailabilityToggle — no second marking
system was built) — it only arms the preference for when he does.

Dry-run by default; --apply writes the raw store (atomic tmp+replace,
indent=2, matching scene_store's own on-disk format) after copying it to
storage/spectra/backups/scenes-preference-<stamp>.json. Idempotent — a
scene already carrying the target preference is reported unchanged and
skipped, and its raw entry is left untouched (not even rewritten
verbatim).
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

from spectra import config
from spectra.models.scene import SceneV2

TARGET_SCENE_NAMES = ["Black Hole V2", "Black Hole V2 UI", "Fireworks V2", "Dancers V2"]
TARGET_MODE = "dark"


def _describe(scene: SceneV2) -> str:
    devices = ", ".join(f"{d.target_kind}:{d.target}" for d in scene.devices) or "(no devices)"
    return (f"  devices: {devices}\n"
           f"  flare_kinds (as loaded/migrated): {len(scene.flare_kinds)}\n"
           f"  entry_ramp_ms: {scene.entry_ramp_ms}\n"
           f"  phase_blend: charge={scene.phase_blend.charge_ramp_ms} "
           f"lull={scene.phase_blend.lull_ramp_ms}\n"
           f"  update_kind: {scene.update_kind}\n"
           f"  current preferred_color_set_mode: {scene.preferred_color_set_mode!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    parser.add_argument("--mode", default=TARGET_MODE, choices=["default", "dark", "light"],
                        help=f"preferred_color_set_mode to set (default: {TARGET_MODE!r})")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))

    by_name: dict[str, list[str]] = {}
    for sid, raw in store.items():
        by_name.setdefault(raw.get("name"), []).append(sid)

    to_patch: list[str] = []
    for name in TARGET_SCENE_NAMES:
        matches = by_name.get(name, [])
        if not matches:
            raise SystemExit(f"scene '{name}' not found in {args.scenes_file} — "
                             "refusing to guess; check the name against the live store")
        if len(matches) > 1:
            raise SystemExit(f"scene '{name}' matches {len(matches)} scenes in "
                             f"{args.scenes_file} — refusing to guess which one")
        sid = matches[0]
        scene = SceneV2(**store[sid])   # read-only: name/value confirmation + diagnostics
        print(f"— {name} ({sid}):")
        print(_describe(scene))
        current = store[sid].get("preferred_color_set_mode", "default")
        if current == args.mode:
            print(f"  already prefers {args.mode!r} — nothing to do\n")
            continue
        to_patch.append(sid)
        print(f"  -> preferred_color_set_mode = {args.mode!r}\n")

    if not to_patch:
        print("all four scenes already carry the target preference — nothing to do")
        return

    if not args.apply:
        print(f"DRY RUN — would patch {len(to_patch)} scene(s) in {args.scenes_file} "
              "(use --apply). Only the preferred_color_set_mode key changes; every "
              "other field on disk is left byte-identical.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"scenes-preference-{stamp}.json"
    shutil.copy2(args.scenes_file, backup_path)
    print(f"backed up {args.scenes_file} -> {backup_path}")

    for sid in to_patch:
        store[sid]["preferred_color_set_mode"] = args.mode   # the ONLY key touched

    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent), prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"patched {len(to_patch)} scene(s) in {args.scenes_file} "
          "(preferred_color_set_mode only — verify with a before/after diff)")


if __name__ == "__main__":
    main()
