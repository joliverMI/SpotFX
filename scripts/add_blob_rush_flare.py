"""One-time migration: declare a "Blob rush" FlareKind on Black Hole V2 and
pool it with "Reverse Momentarily (500ms)" in ONE LANE on every flare band
— his ask, verbatim: "Also on Black Hole, add a new effect that runs as a
shape flare that randomly chooses between the momentary reverse and this
one. This one is called 'blob rush' and it just generates 12 blobs all at
once spread out fairly evenly. Override any max blob counts for this
generation if that's easy, or remove the ones in the event horizon."

"RANDOMLY CHOOSES BETWEEN THE MOMENTARY REVERSE AND THIS ONE" IS A LANE.
scene_response.resolve_lane_picks is exactly that mechanism: kinds sharing
a lane name form a pool of alternatives and exactly ONE member fires per
fire, even weights. So this script does two things per band: attaches "Blob
rush" alongside the reverse kind, and puts BOTH under one lane name
(LANE_NAME) so they are alternatives rather than both firing. Every OTHER
kind on those bands is left out of the lane and therefore keeps firing on
every fire, exactly as it does today.

THE COUNT IS FIXED, NEVER AUTHORED: BLOB_RUSH_BLOBS = 12
(spectra/services/scene_response.py) — his one number, so unlike
firework_burst's rocket count nothing here scales with intensity.
FlareKind.type="blob_rush" therefore carries no jump/params/gain/hold_ms of
its own (the model rejects any); the declaration is nothing but a name and
a type.

MECHANISM: the engine writes the effect's own `blob_rush` key (an instant,
edge-detected, self-resetting count — fx/VENDOR.md deviation #19), and
fx/effects/blackhole.py::_blob_rush spawns that many blobs at evenly-spaced
angles, past max_blobs via the effect's own no-cap tag. His first override
option was taken and his second ("or remove the ones in the event horizon")
deliberately was NOT: nothing already on screen is disturbed, so a rush
never empties the ring it arrives at.

BLACK HOLE V2 UI IS DELIBERATELY LEFT ALONE: it has no "Reverse
Momentarily (500ms)" kind declared or attached, so there is no pair to
pool it against, and his ask names the choice between the two. Its own
Particles/Strips entries are untouched by this script.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — the
switch_star_reverse_flares_to_flip.py / add_fireworks_burst_flare.py rule:
a model round-trip re-serializes EVERY field in current canonical form (and
the legacy flare-kind migration shim has previously added unwanted kinds to
another scene on exactly such a round-trip). This script loads the RAW JSON
dict, uses SceneV2 only to READ (validation + diagnostics), and mutates
exactly three things on exactly one scene: the `flare_kinds` list gains one
entry, each flare band's `kinds` map gains one key, and each flare band's
`kind_lanes` map gains two keys. After --apply it RE-READS the written file
and STRUCTURALLY VERIFIES the diff against the backup, failing loudly on
anything incidental instead of leaving it to be noticed later.

DEPLOY ORDER MATTERS: run this only AFTER the code carrying
FlareKind.type="blob_rush" is deployed and the SPECTRA process restarted —
an older process re-reading a store that contains the new type fails model
validation on load. Dry-run by default; --apply writes (atomic tmp+replace,
indent=2, matching scene_store's own on-disk format) after copying the
store to storage/spectra/backups/scenes-blob-rush-<stamp>.json. --revert
performs the exact inverse. Not run against live storage by this build — an
operator/deploy step, same convention as every other migration script here.
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

SCENE_NAME = "Black Hole V2"
KIND_NAME = "Blob rush"
PAIR_NAME = "Reverse Momentarily (500ms)"
LANE_NAME = "Shape flare"
NEW_KIND = {
    "name": KIND_NAME,
    "type": "blob_rush",
    "jump": None,
    "params": {},
    "gain": 1.0,
    "hold_ms": None,
    "trigger_offset_ms": 0,
}


def _find_scene_id(store: dict, name: str, scenes_file: Path) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene '{name}' not found in {scenes_file} — "
                         "refusing to guess; check the name against the live store")
    if len(matches) > 1:
        raise SystemExit(f"scene '{name}' matches {len(matches)} scenes in "
                         f"{scenes_file} — refusing to guess which one")
    return matches[0]


def _flare_bands(raw_scene: dict) -> list[dict]:
    return ((raw_scene.get("responses") or {}).get("flare") or {}).get("bands", [])


def _verify_diff(before: dict, after: dict, sid: str, *, revert: bool) -> list[str]:
    """Every difference between the backup and the written store, named.
    Returns the report lines; raises SystemExit on any difference that is
    NOT the intended change."""
    lines: list[str] = []
    if set(before) != set(after):
        raise SystemExit(f"UNEXPECTED: scene id set changed "
                         f"{set(before) ^ set(after)}")
    for other_sid in before:
        if other_sid == sid:
            continue
        if before[other_sid] != after[other_sid]:
            raise SystemExit(f"UNEXPECTED: scene {other_sid} "
                             f"('{before[other_sid].get('name')}') changed — "
                             "refusing to accept this write")
    lines.append(f"every other scene (Black Hole V2 UI included): "
                 f"byte-identical ({len(before) - 1} scenes)")

    b, a = copy.deepcopy(before[sid]), copy.deepcopy(after[sid])
    src, dst = (a, b) if revert else (b, a)   # dst = the side carrying the kind

    dst_kinds = dst.get("flare_kinds", [])
    src_kinds = src.get("flare_kinds", [])
    extra = [k for k in dst_kinds if k not in src_kinds]
    if extra != [NEW_KIND] or [k for k in src_kinds if k not in dst_kinds]:
        raise SystemExit(f"UNEXPECTED: flare_kinds diff is not exactly the "
                         f"'{KIND_NAME}' declaration: {extra}")
    lines.append(f"flare_kinds: +1 entry ('{KIND_NAME}', type=blob_rush)"
                 + (" [removed]" if revert else ""))
    src["flare_kinds"] = dst_kinds if not revert else src_kinds
    dst["flare_kinds"] = src["flare_kinds"]

    b_bands, a_bands = _flare_bands(b), _flare_bands(a)
    if len(b_bands) != len(a_bands):
        raise SystemExit("UNEXPECTED: flare band count changed")
    for i, (bb, ab) in enumerate(zip(b_bands, a_bands)):
        with_kind, without = (bb, ab) if revert else (ab, bb)
        expected = dict(without.get("kinds", {}))
        expected[KIND_NAME] = 1.0
        if with_kind.get("kinds") != expected:
            raise SystemExit(f"UNEXPECTED: flare band {i} kinds diff is not "
                             f"exactly '{KIND_NAME}': x1.0 — "
                             f"{without.get('kinds')} -> {with_kind.get('kinds')}")
        expected_lanes = dict(without.get("kind_lanes", {}))
        expected_lanes[KIND_NAME] = LANE_NAME
        expected_lanes[PAIR_NAME] = LANE_NAME
        if with_kind.get("kind_lanes", {}) != expected_lanes:
            raise SystemExit(
                f"UNEXPECTED: flare band {i} kind_lanes diff is not exactly "
                f"the two '{LANE_NAME}' pool members — "
                f"{without.get('kind_lanes')} -> {with_kind.get('kind_lanes')}")
        lines.append(
            f"flare band {i} "
            f"[{without.get('intensity_min')}-{without.get('intensity_max')}]: "
            f"kinds {'-' if revert else '+'} {{'{KIND_NAME}': 1.0}}, "
            f"kind_lanes {'-' if revert else '+'} "
            f"{{'{KIND_NAME}', '{PAIR_NAME}'}} -> '{LANE_NAME}'")
        with_kind["kinds"] = dict(without.get("kinds", {}))
        with_kind["kinds"][KIND_NAME] = 1.0
        without["kinds"] = dict(with_kind["kinds"])
        with_kind["kind_lanes"] = dict(expected_lanes)
        without["kind_lanes"] = dict(expected_lanes)
    if b != a:
        raise SystemExit(f"UNEXPECTED: {SCENE_NAME} differs beyond the "
                         "declaration, the band attachments and the lane "
                         "pooling — refusing to accept this write")
    lines.append(f"everything else on {SCENE_NAME}: byte-identical")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--revert", action="store_true",
                        help="exact inverse: remove the declaration, every "
                             "band attachment, and the lane pooling")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)

    sid = _find_scene_id(store, SCENE_NAME, args.scenes_file)
    raw = store[sid]
    SceneV2(**raw)   # read-only: current store must parse under current code
    bands = _flare_bands(raw)
    print(f"— {SCENE_NAME} ({sid}), {'revert' if args.revert else 'forward'}:")
    if not bands:
        raise SystemExit(f"{SCENE_NAME} has no flare bands — nothing to "
                         "attach to; refusing")
    missing = [i for i, b in enumerate(bands)
               if PAIR_NAME not in b.get("kinds", {})]
    if missing and not args.revert:
        raise SystemExit(
            f"flare band(s) {missing} have no '{PAIR_NAME}' attached — his "
            "ask is a CHOICE between that kind and the rush, so pooling the "
            "rush alone would silently make it fire every time instead. "
            "Refusing; check the scene against the live store.")

    kinds = raw.setdefault("flare_kinds", [])
    have_kind = any(k.get("name") == KIND_NAME for k in kinds)
    changed = False

    if args.revert:
        if have_kind:
            declared = [k for k in kinds if k.get("name") == KIND_NAME]
            if declared != [NEW_KIND]:
                raise SystemExit(
                    f"  '{KIND_NAME}': declaration doesn't match the shape "
                    f"this script wrote ({declared}) — something else edited "
                    "it since; refusing to blindly remove")
            kinds[:] = [k for k in kinds if k.get("name") != KIND_NAME]
            print(f"  '{KIND_NAME}': declaration removed")
            changed = True
        for i, band in enumerate(bands):
            if KIND_NAME in band.get("kinds", {}):
                del band["kinds"][KIND_NAME]
                print(f"  flare band {i}: detached")
                changed = True
            lanes = band.get("kind_lanes", {})
            for name in (KIND_NAME, PAIR_NAME):
                if lanes.get(name) == LANE_NAME:
                    del lanes[name]
                    print(f"  flare band {i}: '{name}' removed from lane "
                          f"'{LANE_NAME}'")
                    changed = True
            # a band that had no kind_lanes key at all before this script
            # ran gets it back exactly as it was — an empty map is the
            # model's default, but it is not the same BYTES, and the point
            # of --revert is a byte-identical undo
            if "kind_lanes" in band and not band["kind_lanes"]:
                del band["kind_lanes"]
    else:
        if have_kind:
            print(f"  '{KIND_NAME}': already declared — skipping declaration")
        else:
            kinds.append(dict(NEW_KIND))
            print(f"  '{KIND_NAME}': declared (type=blob_rush, no authored "
                  "knobs — a fixed 12 blobs, evenly spread, past the "
                  "density cap)")
            changed = True
        for i, band in enumerate(bands):
            band_kinds = band.setdefault("kinds", {})
            if band_kinds.get(KIND_NAME) == 1.0:
                print(f"  flare band {i}: already attached — skipping")
            else:
                band_kinds[KIND_NAME] = 1.0
                print(f"  flare band {i} [{band.get('intensity_min')}-"
                      f"{band.get('intensity_max')}]: attached at x1.0")
                changed = True
            lanes = band.setdefault("kind_lanes", {})
            for name in (KIND_NAME, PAIR_NAME):
                existing = lanes.get(name)
                if existing == LANE_NAME:
                    continue
                if existing is not None:
                    raise SystemExit(
                        f"  flare band {i}: '{name}' is already pooled in "
                        f"lane '{existing}' — refusing to move it; a kind "
                        "belongs to exactly one lane and this is his data")
                lanes[name] = LANE_NAME
                print(f"  flare band {i}: '{name}' pooled into lane "
                      f"'{LANE_NAME}' (one member fires per flare)")
                changed = True

    if not changed:
        print("nothing to do")
        return

    SceneV2(**raw)   # the result must parse too, before anything is written

    if not args.apply:
        print(f"\nDRY RUN — would patch {SCENE_NAME} in {args.scenes_file} "
              "(use --apply). Only the flare_kinds declaration, each flare "
              "band's kinds map and each band's kind_lanes map change; every "
              "other field, and every other scene (Black Hole V2 UI "
              "included), is left byte-identical — verified structurally "
              "after the write, not assumed.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"scenes-blob-rush-{stamp}.json"
    shutil.copy2(args.scenes_file, backup_path)
    print(f"backed up {args.scenes_file} -> {backup_path}")

    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)

    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    print("\nbefore-and-after verification (backup vs written file):")
    for line in _verify_diff(before, written, sid, revert=args.revert):
        print(f"  ✓ {line}")
    print(f"\npatched {SCENE_NAME} in {args.scenes_file}")


if __name__ == "__main__":
    main()
