"""One-entry migration: STAR's Strips always run MELT — remove the
intensity-step that swapped them to `power` at/above ⚡ 0.7.

His words, verbatim (2026-08-25, corr=d60c3013cdb748f8): "curently we can
use the power effect on the strips when running star scene. I dont want
that anymore, always do melt."

WHAT IS ACTUALLY BEING REMOVED — it is an INTENSITY STEP, not a pool pick.
STAR's Strips entry (039e4e68…, target_kind="category", target="Strips")
is base `melt` carrying

    effect_steps: [{threshold: 0.7, effect_type: "power",
                    params: {bass_decay_rate: 0.6, ...}}]

seeded by scripts/seed_star_strips.py (decision: star-fold-entry-growth).
scene_compiler.resolve_scene() resolves that list ONCE PER FIRE against the
fire's own intensity (SceneDeviceConfig.select_variant): the last step whose
threshold <= intensity replaces effect AND params wholesale, and the base
pair is the answer when no step qualifies. Emptying the list therefore makes
`melt` the answer at EVERY intensity — the base IS the fallback — with no
other mechanism to route around.

SCOPE — the Strips entry ONLY. STAR has three device entries and TWO of them
name `power`; they are not the same thing and only one is his ask:

    93385d09…  category "Matrix"   radial              (untouched)
    039e4e68…  category "Strips"   melt + power step   ← THIS ONE
    dc2da156…  category "Singles"  power               (untouched)

Verified against storage/device_categories.json rather than assumed: the
"Strips" category is virtuals strip-effect/radial-dummy and permits BOTH
melt and power, while "Singles" is single-color-effect and permits `power`
ONLY — the Singles entry could not be melt even in principle, and his ask
does not reach it. `power` stays perfectly valid everywhere else in his
library; this script removes exactly one step entry from one device entry
on one scene.

WHAT HAPPENS TO A STRIP ALREADY PAINTING `power` WHEN THIS LANDS: nothing,
until the next fire. Steps resolve at FIRE time inside resolve_scene(), so a
strip already rendering `power` from an earlier high-intensity STAR fire
keeps rendering it — no writer re-resolves a live entry — and every
SUBSEQUENT STAR fire lands melt. If STAR happens to be the live scene at
deploy, the deploy plan's own re-fire (or the next automatic scene change)
settles it; nothing here reaches the wire.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — same discipline as
scripts/switch_star_reverse_flares_to_flip.py and
scripts/set_scene_colorset_preference.py: loading a scene through SceneV2
and writing it back via model_dump_json() re-serializes EVERY field in
current canonical form, including the legacy flare-kind migration shim that
has silently ADDED flare kinds to another scene on a round-trip write. This
script loads the RAW JSON dict, uses SceneV2 only to READ (validation,
diagnostics, and a resolve-time proof that melt now wins at every
intensity), and writes back by mutating exactly ONE key — `effect_steps` —
on exactly ONE device entry. `[]` (not a deleted key) is the model's own
canonical stepless form: SceneDeviceConfig.effect_steps defaults to an empty
list and the store already serializes STAR's other two entries that way, so
the patched entry is byte-identical to a naturally stepless one.

The write is asserted STRUCTURALLY afterwards, not claimed: the file is
re-read from disk and diffed against the pre-write snapshot, and the run
fails loudly unless the ONLY differing path in the whole store is
STAR.devices[<strips>].effect_steps — every other STAR entry and every other
scene byte-identical (the blob-rush / fish seeder convention).

Idempotent: an entry already stepless is reported and skipped. An entry
whose base effect isn't `melt`, or whose steps don't match the expected
seeded shape, is REFUSED rather than blindly emptied — that means something
else edited it since seed_star_strips.py ran, and this script only knows how
to perform this one authorised removal.

TO REVERT: --revert re-adds the exact step that was removed (read back from
the backup is not needed — the shape is pinned in EXPECTED_STEP here and in
seed_star_strips.STRIPS_STEP).

DO NOT re-run scripts/seed_star_strips.py --apply after this lands: it
unconditionally re-writes this same step and would undo his ruling.

Dry-run by default; --apply writes the raw store (atomic tmp+replace,
indent=2 — scene_store's own on-disk format) after copying it to
storage/spectra/backups/scenes-star-strips-melt-<stamp>.json.
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
from random import Random

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config
from spectra.models.scene import SceneV2
from spectra.services import scene_compiler
from spectra.services.binding_resolver import FireContext

STAR_ID = "d3aab04c-7e23-4693-bd26-16bad45792a6"
STRIPS_TARGET = "Strips"
BASE_EFFECT = "melt"
STEP_EFFECT = "power"
# The step as seed_star_strips.py wrote it, plus the params his live store
# actually carries (that seeder wrote bass_decay_rate only; the extra keys
# below arrived from later UI edits). Either shape is accepted for removal,
# but the effect/threshold pair must match exactly.
EXPECTED_THRESHOLD = 0.7
REVERT_STEP = {"threshold": EXPECTED_THRESHOLD, "effect_type": STEP_EFFECT,
               "params": {"bass_decay_rate": 0.6}}


def _diff_paths(a, b, path=()):  # -> list[tuple]
    """Every path at which two JSON structures differ, deepest-common form:
    a differing leaf, or a differing container reported at the container."""
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(path + (k,))
            else:
                out.extend(_diff_paths(a[k], b[k], path + (k,)))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [path]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_diff_paths(x, y, path + (i,)))
        return out
    return [] if a == b else [path]


def _strips_index(raw_scene: dict) -> int:
    hits = [i for i, d in enumerate(raw_scene.get("devices", []))
            if d.get("target") == STRIPS_TARGET
            and d.get("target_kind") == "category"]
    if not hits:
        raise SystemExit(
            f"STAR has no category entry targeting '{STRIPS_TARGET}' — "
            "refusing to guess which entry his ask means")
    if len(hits) > 1:
        raise SystemExit(
            f"STAR has {len(hits)} category entries targeting "
            f"'{STRIPS_TARGET}' — refusing to guess which one")
    return hits[0]


def _resolved_effect(raw_scene: dict, intensity: float) -> str:
    scene = SceneV2(**json.loads(json.dumps(raw_scene)))
    res = scene_compiler.resolve_scene(
        scene, FireContext(intensity, rng=Random(6)))
    dev = next(d for d in res.devices if d.target == STRIPS_TARGET)
    return dev.effect_type


def plan(store: dict, revert: bool) -> tuple[int, list, str]:
    """(strips entry index, the effect_steps value to write, a report line).

    Raises SystemExit on anything unexpected; returns steps == the current
    value when there is nothing to do."""
    if STAR_ID not in store:
        raise SystemExit(f"scene {STAR_ID} (STAR) not in the store")
    raw = store[STAR_ID]
    idx = _strips_index(raw)
    dev = raw["devices"][idx]
    current = dev.get("effect_steps", [])

    if dev.get("effect_type") != BASE_EFFECT:
        raise SystemExit(
            f"STAR's {STRIPS_TARGET} entry has base effect "
            f"'{dev.get('effect_type')}', expected '{BASE_EFFECT}' — "
            "refusing to touch an entry this script doesn't recognise")

    # A drift declaration naming a step-only param would stop validating the
    # moment the step leaves; check before, not after the write.
    if not revert:
        base_params = set(dev.get("params", {}))
        step_params = {p for s in current for p in s.get("params", {})}
        orphaned = [p for p in dev.get("drift", {})
                    if p not in base_params and p in step_params
                    and p not in ("brightness", "background_brightness")]
        if orphaned:
            raise SystemExit(
                f"STAR's {STRIPS_TARGET} entry declares drift for {orphaned}, "
                "which only the step's params carry — removing the step would "
                "invalidate the scene. Refusing.")

    if revert:
        if current:
            return idx, current, (
                f"  {STRIPS_TARGET}: already carries {len(current)} step(s) "
                "— nothing to do")
        return idx, [dict(REVERT_STEP)], (
            f"  {STRIPS_TARGET}: effect_steps [] -> [{STEP_EFFECT} @ "
            f"⚡{EXPECTED_THRESHOLD}]  (re-adding the seeded step)")

    if not current:
        return idx, current, (
            f"  {STRIPS_TARGET}: already stepless — always {BASE_EFFECT}, "
            "nothing to do")
    if len(current) != 1 or current[0].get("effect_type") != STEP_EFFECT \
            or current[0].get("threshold") != EXPECTED_THRESHOLD:
        raise SystemExit(
            f"STAR's {STRIPS_TARGET} entry carries unexpected steps "
            f"{json.dumps(current)} — expected exactly one "
            f"{STEP_EFFECT} step at ⚡{EXPECTED_THRESHOLD}. Refusing to guess.")
    return idx, [], (
        f"  {STRIPS_TARGET}: effect_steps [{STEP_EFFECT} @ "
        f"⚡{EXPECTED_THRESHOLD}, params "
        f"{json.dumps(current[0].get('params', {}), sort_keys=True)}] -> []  "
        f"(always {BASE_EFFECT})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--revert", action="store_true",
                        help="re-add the removed power step instead")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    before_text = args.scenes_file.read_text(encoding="utf-8")
    store = json.loads(before_text)
    before = json.loads(before_text)

    direction = "revert (re-add power step)" if args.revert \
        else "forward (always melt)"
    print(f"— STAR ({STAR_ID}), {direction}:")
    idx, new_steps, line = plan(store, args.revert)
    print(line)

    dev = store[STAR_ID]["devices"][idx]
    if new_steps == dev.get("effect_steps", []):
        print("nothing to do")
        return

    # Prove the OUTCOME on the real compiler, not just the stored bytes.
    trial = json.loads(json.dumps(store[STAR_ID]))
    trial["devices"][idx]["effect_steps"] = new_steps
    lo, hi = _resolved_effect(trial, 0.5), _resolved_effect(trial, 0.95)
    print(f"  resolve_scene() after the patch: ⚡0.50 -> {lo}, ⚡0.95 -> {hi}")
    if not args.revert and not (lo == hi == BASE_EFFECT):
        raise SystemExit(
            f"FAIL: patched entry still resolves {lo}/{hi} — expected "
            f"{BASE_EFFECT} at every intensity")

    # Untouched siblings, named so the scope is visible in the run output.
    for i, d in enumerate(store[STAR_ID]["devices"]):
        if i != idx:
            print(f"  untouched: {d.get('target')} -> {d.get('effect_type')}")

    if not args.apply:
        print(f"\nDRY RUN — would patch ONE key (effect_steps) on ONE device "
              f"entry of STAR in {args.scenes_file} (use --apply). Every other "
              "STAR entry and every other scene stays byte-identical.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"scenes-star-strips-melt-{stamp}.json"
    shutil.copy2(args.scenes_file, backup_path)
    print(f"backed up {args.scenes_file} -> {backup_path}")

    dev["effect_steps"] = new_steps        # the ONLY key touched, anywhere

    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)

    after = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    diffs = _diff_paths(before, after)
    expected = [(STAR_ID, "devices", idx, "effect_steps")]
    if diffs != expected:
        raise SystemExit(
            "FAIL: the written store differs from the plan — expected exactly "
            f"{expected}, got {diffs}. The backup at {backup_path} is the "
            "pre-write file; restore it.")
    print(f"wrote {args.scenes_file} — verified: the ONLY changed path in the "
          f"whole store is STAR.devices[{idx}].effect_steps "
          f"({len(after) - 1} other scenes byte-identical)")


if __name__ == "__main__":
    main()
