"""Restore STAR's strips at high intensity — the deploy half of decision:
star-fold-entry-growth (data/spectra-scene-corrections/report.md Part 3,
"the not-foldable strips row").

The Hype Star fold could not carry the strips' melt→power flip while
effect_type was a plain string. The model now grows intensity-conditional
EFFECT SELECTION (SceneDeviceConfig.effect_steps); this script writes the
exact declaration Hype Star had onto STAR's Strips entry:

    below ⚡ 0.7      melt   (defaults — unchanged, the base form)
    at/above ⚡ 0.7   power  (bass_decay_rate 0.6 — the original
                             "reactivity 0.6")

Targets scene id d3aab04c… in storage/spectra/scenes.json BY ID — the live
store names it STAR; a pre-rename store still says Mid Star V2; both are
the same scene. Dry-run by default; --apply writes (atomic, whole store,
indent=2 — the store's own format). Idempotent.

SUPERSEDED FOR THE STRIPS ENTRY, 2026-08-25 — DO NOT RE-RUN --apply. His
ruling that day, verbatim: "curently we can use the power effect on the
strips when running star scene. I dont want that anymore, always do melt."
scripts/star_strips_always_melt.py removes the step this seeder writes;
re-running this one would silently put it back. The script below is kept
for its history and because scripts/check_spectra.py still exercises
with_star_strips() as the executable proof of the effect_steps mechanism
itself (against a COPY, never the live store).

DO NOT deliver this by re-running scripts/seed_spectra_from_v2.py: that
seeder REBUILDS the SPECTRA store from the legacy world and would erase the
live fold. This script is the supported migration path; running it against
the live store at deploy is what restores the behaviour.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config
from spectra.models.scene import SceneV2

STAR_ID = "d3aab04c-7e23-4693-bd26-16bad45792a6"
STRIPS_STEP = {"threshold": 0.7, "effect_type": "power",
               "params": {"bass_decay_rate": 0.6}}


def with_star_strips(raw_scene: dict) -> dict:
    """The scene with the strips declaration applied, model-normalized
    (validated through SceneV2 so the write is exactly what a load
    produces). Raises if the scene has no Strips/melt entry to grow."""
    out = json.loads(json.dumps(raw_scene))
    strips = [d for d in out.get("devices", [])
              if d.get("target") == "Strips" and d.get("effect_type") == "melt"]
    if not strips:
        raise SystemExit(
            f"scene '{raw_scene.get('name')}' has no Strips/melt entry — "
            "refusing to guess where the declaration belongs")
    for dev in strips:
        dev["effect_steps"] = [dict(STRIPS_STEP)]
    return json.loads(SceneV2(**out).model_dump_json())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    if STAR_ID not in store:
        raise SystemExit(f"scene {STAR_ID} (STAR / Mid Star V2) not in "
                         f"{args.scenes_file}")

    migrated = with_star_strips(store[STAR_ID])
    if migrated == store[STAR_ID]:
        print(f"'{migrated['name']}' already carries the strips declaration "
              "— nothing to do")
        return
    strips = next(d for d in migrated["devices"] if d["target"] == "Strips")
    print(f"— {migrated['name']} ({STAR_ID}): Strips melt below ⚡ 0.7, "
          f"power at/above (steps: {strips['effect_steps']})")
    if not args.apply:
        print(f"\nDRY RUN — would update the scene in {args.scenes_file} "
              "(use --apply)")
        return

    store[STAR_ID] = migrated
    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"wrote {args.scenes_file}")


if __name__ == "__main__":
    main()
