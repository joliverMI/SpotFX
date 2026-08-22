"""One-time migration: declare a "Firework Burst" FlareKind on Fireworks V2
and attach it to EVERY flare energy band — his ask, verbatim: "make a flare
meant to line up with a burst of fireworks on top of the standard ones in
the fireworks scene. 3 for 0 intensity and 6 for 1 intensity, scaled
linearly. put it in every energy intensity in the scene."

THE COUNT IS COMPUTED, NEVER AUTHORED: 3 rockets at intensity 0.0, 6 at
1.0, linear (spectra/services/scene_response.py's firework_burst_rockets —
FIREWORK_BURST_ROCKETS_GENTLE/HARD, the color_rotate constant/interpolation
shape, his own numbers exact). FlareKind.type="firework_burst" therefore
carries no jump/params/gain/hold_ms of its own (the model rejects any);
the declaration is nothing but a name and a type.

MECHANISM (why not beat_burst, which his existing Fireworks patches drive):
beat_burst only launches on the NEXT beat — up to a beat-period after the
trigger — which cannot "line up" with a mark. The engine instead writes the
effects' own `burst_rockets` key (an instant, edge-detected, self-resetting
count — fx/VENDOR.md deviation #15), and each fireworks effect explodes
that many rockets via its OWN drop-payoff spawn shape (_payoff_burst_at /
_flare_burst: fireworks1d's two staggered pairs per origin, fireworks'
giant near-center burst per origin, both ignore_cap so the density cap can
never swallow his burst). ADDS, never replaces: layered on top of the
scene's own rockets, nothing restarted or interrupted — proven against the
real vendored effects in tests/test_firework_burst.py.

ATTACHED, NOT JUST DECLARED — HIS EXPLICIT PLACEMENT, unlike every prior
FlareKind migration here (add_color_rotate_flares.py et al. deliberately
declared-only): he named the placement himself ("every energy intensity in
the scene"), so this script also adds the kind to every band of the
scene's "flare" response at x1.0. NOT in a lane — kind_lanes is never
touched: a kind absent from every pool is its own one-member lane and
always fires alongside the band's other kinds, which is exactly "on top of
the standard ones"; a lane would instead make it an ALTERNATIVE to them.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — the
switch_star_reverse_flares_to_flip.py / set_scene_colorset_preference.py
rule: a model round-trip re-serializes EVERY field in current canonical
form (and the legacy flare-kind migration shim has previously added
unwanted kinds to another scene on exactly such a round-trip). This script
loads the RAW JSON dict, uses SceneV2 only to READ (validation +
diagnostics), and mutates exactly two things on exactly one scene: the
`flare_kinds` list gains one entry, and each flare band's `kinds` map
gains one key. Every other field on Fireworks V2, and every other scene in
the store, is left byte-identical — and unlike the prior scripts this one
does not just promise that: after --apply it RE-READS the written file and
STRUCTURALLY VERIFIES the diff against the backup (his data contract:
"a before-and-after diff proving only the intended declaration and the
band attachments changed; report anything incidental"), failing loudly on
any unexpected difference instead of leaving it for someone to notice.

DEPLOY ORDER MATTERS: run this only AFTER the code carrying
FlareKind.type="firework_burst" is deployed and the SPECTRA process
restarted — an older process re-reading a store that contains the new type
fails model validation on load. Dry-run by default; --apply writes (atomic
tmp+replace, indent=2, matching scene_store's own on-disk format) after
copying the store to storage/spectra/backups/scenes-fireworks-burst-
<stamp>.json. --revert performs the exact inverse (remove the declaration
and every attachment). Not run against live storage by this build — an
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

SCENE_NAME = "Fireworks V2"
KIND_NAME = "Firework Burst"
NEW_KIND = {
    "name": KIND_NAME,
    "type": "firework_burst",
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
    """The data contract's executable half: every difference between the
    backup and the written store, named. Returns the report lines; raises
    SystemExit on any difference that is NOT the intended change."""
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
    lines.append(f"every other scene: byte-identical ({len(before) - 1} scenes)")

    b, a = copy.deepcopy(before[sid]), copy.deepcopy(after[sid])
    src, dst = (a, b) if revert else (b, a)   # dst = the side carrying the kind

    dst_kinds = dst.get("flare_kinds", [])
    src_kinds = src.get("flare_kinds", [])
    extra = [k for k in dst_kinds if k not in src_kinds]
    if extra != [NEW_KIND] or [k for k in src_kinds if k not in dst_kinds]:
        raise SystemExit(f"UNEXPECTED: flare_kinds diff is not exactly the "
                         f"'{KIND_NAME}' declaration: {extra}")
    lines.append(f"flare_kinds: +1 entry ('{KIND_NAME}', type=firework_burst)"
                 + (" [removed]" if revert else ""))
    # neutralize the intended kind change, then the band attachments
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
        if with_kind.get("kind_lanes") != without.get("kind_lanes"):
            raise SystemExit(f"UNEXPECTED: flare band {i} kind_lanes changed "
                             "— this kind must never be pooled into a lane")
        lines.append(
            f"flare band {i} "
            f"[{without.get('intensity_min')}-{without.get('intensity_max')}]: "
            f"kinds {'-' if revert else '+'} {{'{KIND_NAME}': 1.0}}, "
            f"lanes untouched")
        with_kind["kinds"] = dict(without.get("kinds", {}))
        with_kind["kinds"][KIND_NAME] = 1.0
        without["kinds"] = dict(with_kind["kinds"])
    if b != a:
        raise SystemExit("UNEXPECTED: Fireworks V2 differs beyond the "
                         "declaration and the band attachments — refusing "
                         "to accept this write")
    lines.append("everything else on Fireworks V2: byte-identical")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--revert", action="store_true",
                        help="exact inverse: remove the declaration and every "
                             "band attachment")
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
    print(f"— {SCENE_NAME} ({sid}), "
          f"{'revert' if args.revert else 'forward'}:")
    print(f"  flare bands: "
          + ", ".join(f"[{b.get('intensity_min')}-{b.get('intensity_max')}]"
                      for b in bands))
    if not bands:
        raise SystemExit(f"{SCENE_NAME} has no flare bands — nothing to "
                         "attach to; refusing (his placement was 'every "
                         "energy intensity in the scene')")

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
    else:
        if have_kind:
            print(f"  '{KIND_NAME}': already declared — skipping declaration")
        else:
            kinds.append(dict(NEW_KIND))
            print(f"  '{KIND_NAME}': declared (type=firework_burst, no "
                  "authored knobs — count is computed, 3 at intensity 0 to "
                  "6 at 1)")
            changed = True
        for i, band in enumerate(bands):
            band_kinds = band.setdefault("kinds", {})
            if band_kinds.get(KIND_NAME) == 1.0:
                print(f"  flare band {i}: already attached — skipping")
                continue
            band_kinds[KIND_NAME] = 1.0
            print(f"  flare band {i} [{band.get('intensity_min')}-"
                  f"{band.get('intensity_max')}]: attached at x1.0 "
                  "(directly, NOT in a lane)")
            changed = True

    if not changed:
        print("nothing to do")
        return

    SceneV2(**raw)   # the result must parse too, before anything is written

    if not args.apply:
        print(f"\nDRY RUN — would patch {SCENE_NAME} in {args.scenes_file} "
              "(use --apply). Only the flare_kinds declaration and each "
              "flare band's kinds map change; every other field, and every "
              "other scene, is left byte-identical — verified structurally "
              "after the write, not assumed.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"scenes-fireworks-burst-{stamp}.json"
    shutil.copy2(args.scenes_file, backup_path)
    print(f"backed up {args.scenes_file} -> {backup_path}")

    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent),
                               prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)

    # the data contract's diff proof — re-read what actually landed
    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    print("\nbefore-and-after verification (backup vs written file):")
    for line in _verify_diff(before, written, sid, revert=args.revert):
        print(f"  ✓ {line}")
    print(f"\npatched {SCENE_NAME} in {args.scenes_file}")


if __name__ == "__main__":
    main()
