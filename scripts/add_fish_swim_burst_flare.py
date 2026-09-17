"""One-time migration: declare a "Fish Swim Burst" FlareKind on the Fish scene
and attach it to EVERY flare energy band, in a pick-one lane with that band's
other MOMENTARY SHAPE flares — his ask, verbatim (the Admiral's card
fish-effect-disperse-off-screen-instead--wyxr): "add a flare at all levels
that can run instead of other shape flares that makes the fish swim fast for
a burst, and have a dramatic change in the frequency of their fin strokes.
time it so that the burst starts 100ms before the trigger and lasts 300ms
total, and make sure Sonic can adjust those numbers easily". He then
corrected the start himself: "no, dont pull the band forward, just dont add
the 100ms pre-fire" — so the burst fires ON the trigger.

THE KIND IS AN ORDINARY MOMENTARY TOGGLE — no new flare type, no new release
queue. `params={"swim_burst": true}` spikes the fish effect's own
`swim_burst` level (fx/effects/fish.py, "the swim burst flare" block); the
release is an instant jump back (a toggle never glides — scene_response's
RELEASE OWNERSHIP rule), armed from the spike's own landing. So:
  * hold_ms=300          — the burst's whole length, his "300ms total";
  * trigger_offset_ms=0  — the burst starts ON the trigger mark. A toggle
    computes an automatic lead of 0, so nothing else moves the start.
    The field is OFFSET family (docs/SPECTRA_TIMING_CONVENTIONS.md) and
    stays Sonic-adjustable, but no pre-fire is authored here: a kind's
    offset moves its WHOLE band (see the consequence below), and the early
    start he first asked for is DEFERRED to the per-flare trigger-moment
    work, where a lead sits on the flare itself rather than on the band
    aggregate.
Both are plain FlareKind fields Sonic edits through set_flare_kind (hold_ms
already was; trigger_offset_ms was added to that surface by the same
change), each omit-means-keep so changing one never resets the other — e.g.
"make the fish burst 400ms" is one set_flare_kind call with hold_ms=400.

"INSTEAD OF OTHER SHAPE FLARES" IS A LANE. A kind absent from every pool is
its own one-member lane and fires ALONGSIDE the band's other kinds (that is
how add_fireworks_burst_flare.py put Firework Burst "on top of" his
fireworks). Kinds sharing a lane name form a pick-one pool: each fire rolls
ONE member, evenly (scene_response.resolve_lane_picks). So on every band this
script pools the burst with that band's own momentary shape flares.

WHICH KINDS COUNT AS "SHAPE FLARES" — a stated rule, computed, never a
hand-picked list: an attached kind of type `momentary` all of whose params
are registry aspect "shape" for the `fish` effect (config/effect_params.json).
On his Fish scene today that is exactly "Reverse Momentarily (500ms)" on all
three bands. Deliberately NOT pooled: the permanent "Flare patch" kinds (they
re-baseline particle_count / blob_size per intensity band — a level, not a
flare that "runs"; pooling them would sometimes skip the band's fish count),
the gains, Dice Re-roll and the two colour kinds. THIS IS HIS CALL: if he
meant the patches too, drag them into the "Shape" lane on the Scenes page's
lane rack; nothing here needs re-running.

THE CONSEQUENCE, NAMED BEFORE HE SEES IT IN HIS ROOM: pooling halves how
often "Reverse Momentarily (500ms)" fires on Fish — each flare now picks the
burst or the reverse, 50/50. Band timing is unchanged: the kind is authored
at offset 0, a band's anchor is the smallest offset among its attached
kinds, zero included (scene_response.band_trigger_offset_ms), and every
Fish kind sits at 0, so attaching it moves no Fish flare. (Sonic giving it
a nonzero offset later moves when the burst itself lands — each kind in a
trigger-relocated band fires at its own offset — and a negative one also
moves where that band's fire begins.)

A "Shape" LANE THAT ALREADY EXISTS IS HIS. On any band where some kind is
already pooled in a lane named "Shape" before this script runs, it REFUSES
by name rather than merging into (and, on --revert, tearing down) a pool he
built himself — which is what keeps --revert an exact inverse.

RAW-DICT PATCH, NOT scene_store.save() — the add_fireworks_burst_flare.py /
set_scene_colorset_preference.py rule (a model round-trip re-serializes every
field and has added unwanted kinds to another scene before). Mutates exactly:
Fish's `flare_kinds` (+1), each flare band's `kinds` (+1) and `kind_lanes`
(+ the burst and each pooled shape kind). After --apply it RE-READS the file
and structurally verifies that nothing else changed.

DEPLOY ORDER: only AFTER the code carrying fish.py's `swim_burst` key and the
registry entry is deployed and SPECTRA restarted — an older fish effect's
CONFIG_SCHEMA would reject the key on every fire. Dry-run by default;
--apply backs the store up to storage/spectra/backups/scenes-fish-swim-burst-
<stamp>.json first; --revert is the exact inverse. Not run against live
storage by this build — an operator/deploy step.
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

from spectra import config
from spectra.models.scene import SceneV2

SCENE_NAME = "Fish"
EFFECT = "fish"
KIND_NAME = "Fish Swim Burst"
LANE_NAME = "Shape"
NEW_KIND = {
    "name": KIND_NAME,
    "type": "momentary",
    "jump": None,
    "params": {"swim_burst": {"mode": "absolute", "value": 1.0,
                              "offset": None, "lo": None, "hi": None}},
    "gain": 1.0,
    "hold_ms": 300,
    "trigger_offset_ms": 0,
    "enabled": True,
}
REGISTRY = Path(__file__).resolve().parent.parent / "config" / "effect_params.json"


def _shape_params() -> set[str]:
    params = json.loads(REGISTRY.read_text())["effects"][EFFECT]["params"]
    return {k for k, v in params.items() if v.get("aspect") == "shape"}


def shape_flares(raw_scene: dict, band: dict) -> list[str]:
    """The band's attached MOMENTARY kinds whose every param is a fish shape
    param — the stated rule in the module docstring."""
    shape = _shape_params()
    by_name = {k.get("name"): k for k in raw_scene.get("flare_kinds", [])}
    out = []
    for name in band.get("kinds", {}):
        k = by_name.get(name)
        if (k is None or name == KIND_NAME or k.get("type") != "momentary"
                or not k.get("params")):
            continue
        if set(k["params"]) <= shape:
            out.append(name)
    return out


def _find_scene_id(store: dict, name: str, scenes_file: Path) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene '{name}' not found in {scenes_file} — "
                         "refusing to guess")
    if len(matches) > 1:
        raise SystemExit(f"scene '{name}' matches {len(matches)} scenes — "
                         "refusing to guess which one")
    return matches[0]


def _flare_bands(raw_scene: dict) -> list[dict]:
    return ((raw_scene.get("responses") or {}).get("flare") or {}).get("bands", [])


def forward(raw: dict) -> list[str]:
    """Apply the forward patch in place; return the report lines. Every band
    is checked BEFORE anything is changed, so a refusal leaves `raw` as it
    was."""
    bands = _flare_bands(raw)
    pooled_by_band = [shape_flares(raw, band) for band in bands]
    for i, (band, pooled) in enumerate(zip(bands, pooled_by_band)):
        lanes = band.get("kind_lanes") or {}
        ours = ({KIND_NAME, *pooled} if lanes.get(KIND_NAME) == LANE_NAME
                else set())
        for name, lane in lanes.items():
            if lane == LANE_NAME and name not in ours:
                raise SystemExit(
                    f"flare band {i}: '{name}' is already pooled in a lane "
                    f"named '{LANE_NAME}' — refusing to merge into a pool he "
                    "built himself (--revert could not undo it exactly)")
        for name in pooled:
            if lanes.get(name) not in (None, LANE_NAME):
                raise SystemExit(
                    f"flare band {i}: '{name}' is already pooled in lane "
                    f"'{lanes[name]}' — refusing to move it; he pooled it "
                    "himself")

    lines = []
    kinds = raw.setdefault("flare_kinds", [])
    if any(k.get("name") == KIND_NAME for k in kinds):
        lines.append(f"'{KIND_NAME}': already declared — skipping declaration")
    else:
        kinds.append(copy.deepcopy(NEW_KIND))
        lines.append(f"'{KIND_NAME}': declared (momentary swim_burst, "
                     "hold_ms=300, trigger_offset_ms=0 — on the trigger)")
    for i, (band, pooled) in enumerate(zip(bands, pooled_by_band)):
        lanes = band.setdefault("kind_lanes", {})
        band.setdefault("kinds", {})[KIND_NAME] = 1.0
        lanes[KIND_NAME] = LANE_NAME
        for name in pooled:
            lanes[name] = LANE_NAME
        lines.append(
            f"flare band {i} [{band.get('intensity_min')}-"
            f"{band.get('intensity_max')}]: attached x1.0, lane "
            f"'{LANE_NAME}' = {[KIND_NAME] + pooled}")
    return lines


def revert(raw: dict, pooled_by_band: list[list[str]]) -> list[str]:
    lines = []
    kinds = raw.setdefault("flare_kinds", [])
    declared = [k for k in kinds if k.get("name") == KIND_NAME]
    if declared:
        if declared != [NEW_KIND]:
            raise SystemExit(f"'{KIND_NAME}' was edited since this script "
                             f"wrote it ({declared}) — refusing to remove it "
                             "blindly")
        kinds[:] = [k for k in kinds if k.get("name") != KIND_NAME]
        lines.append(f"'{KIND_NAME}': declaration removed")
    for i, band in enumerate(_flare_bands(raw)):
        band.get("kinds", {}).pop(KIND_NAME, None)
        lanes = band.get("kind_lanes", {})
        lanes.pop(KIND_NAME, None)
        for name in pooled_by_band[i]:
            if lanes.get(name) == LANE_NAME:
                del lanes[name]
        lines.append(f"flare band {i}: detached, lane '{LANE_NAME}' removed")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)
    sid = _find_scene_id(store, SCENE_NAME, args.scenes_file)
    raw = store[sid]
    SceneV2(**raw)
    if not _flare_bands(raw):
        raise SystemExit(f"{SCENE_NAME} has no flare bands — refusing (his "
                         "placement was 'all levels')")

    if args.revert:
        # the lanes this script would have made, recomputed off the kinds
        pooled = [shape_flares(raw, b) for b in _flare_bands(raw)]
        lines = revert(raw, pooled)
    else:
        lines = forward(raw)
    print(f"— {SCENE_NAME} ({sid}), {'revert' if args.revert else 'forward'}:")
    for line in lines:
        print(f"  {line}")
    if raw == before[sid]:
        print("nothing to do")
        return
    SceneV2(**raw)

    # the executable half of the data contract: only Fish changed, and only
    # in flare_kinds and each flare band's kinds / kind_lanes
    for other in before:
        if other != sid and store[other] != before[other]:
            raise SystemExit(f"UNEXPECTED: scene {other} changed")
    b, a = copy.deepcopy(before[sid]), copy.deepcopy(raw)
    for side in (a, b):
        side.pop("flare_kinds", None)
        for band in _flare_bands(side):
            band.pop("kinds", None)
            band.pop("kind_lanes", None)
    if a != b:
        raise SystemExit("UNEXPECTED: Fish differs beyond flare_kinds and the "
                         "flare bands' kinds / kind_lanes")
    print("  every other scene, and every other field on Fish: unchanged")

    if not args.apply:
        print(f"\nDRY RUN — would patch {SCENE_NAME} in {args.scenes_file} "
              "(use --apply).")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-fish-swim-burst-{stamp}.json"
    shutil.copy2(args.scenes_file, backup)
    print(f"backed up {args.scenes_file} -> {backup}")
    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    if written != store:
        raise SystemExit("UNEXPECTED: the written file does not read back as "
                         "the planned store")
    print(f"patched {SCENE_NAME}; read back identical to the plan")


if __name__ == "__main__":
    main()
