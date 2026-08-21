"""One-time migration: switch STAR's two existing reverse flares — "Reverse
Direction" and "Reverse Momentarily (500ms)" (added by scripts/
add_star_reverse_flares.py) — from driving `spin` (radial's signed speed
param) negative to using `spin_sign` ("Flip") instead.

His words, verbatim: "use the flip control for star". He was told the trade
before choosing — NO PAUSE, but the turn becomes INSTANT and more jarring —
and made the call knowingly; this script does not soften that with easing.

WHY: `spin` is registry smooth=true (fx/effects/radial.py's config_updated
re-derives it via nonlinear_log every tween frame, continuous through zero
and negative x — retagged 2026-08-17). An absolute `spin: -0.55` patch
therefore GLIDES from +0.55 to -0.55 over DICE_REROLL_GLIDE_MS, passing
through a real zero-speed moment on the way — his own report, precisely:
"star is freezing on every flare... but then it continues smoothly."
`spin_sign` targets the SAME register (`maps_to: spin`) but is now (as of
2026-08-20, spectra/services/scene_response.py's own sign-control port —
see config/effect_params.json's spin_sign note and AGENTS.md) translated
into a magnitude-preserving, sign-flipping write forced through an INSTANT
jump on both departure and release, regardless of spin's own smooth tag —
no glide, so no zero-crossing, on the way out OR the way back.

Before this port landed, `spin_sign` was structurally INERT under SPECTRA —
radial.py's CONFIG_SCHEMA has no such key, and no code in spectra/ read
`maps_to`/`sign_control` at all — so simply repointing these two kinds at
`spin_sign` would have been a silent no-op (STAR never reverses at all),
not a milder version of the freeze. Do not run this migration against a
checkout that predates that port; scripts/check_spectra.py's own STAR
reverse-flare section proves the mechanism first.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — same reasoning as
scripts/set_scene_colorset_preference.py's own docstring, restated because
it matters here too: loading a scene through SceneV2 and writing it back
via model_dump_json() re-serializes EVERY field in current canonical form,
including a legacy flare-kind migration shim that has (separately, the
same night as this task) silently added extra flare kinds to at least one
other scene on a round-trip write. This script loads the RAW JSON dict,
uses SceneV2 only to READ (name matching, diagnostics), and writes back by
mutating exactly ONE key — `params` — on exactly the two named flare_kinds
list entries. Every other field on STAR, and every other scene in the
store, is left byte-identical.

Idempotent: a kind already carrying the target `spin_sign` shape is
reported unchanged and skipped. A kind whose `params` does NOT match the
expected pre-migration shape (`{"spin": {"mode": "absolute", "value":
-0.55, ...}}`) is reported and left untouched rather than blindly
overwritten — it means something else already edited it since
add_star_reverse_flares.py ran, and this script only knows how to perform
this one specific, authorised swap.

TO REVERT: re-run with --revert, which performs the exact inverse patch
(spin_sign back to spin: -0.55) — the one-line change the PR calls out.

Dry-run by default; --apply writes the raw store (atomic tmp+replace,
indent=2, matching scene_store's own on-disk format) after copying it to
storage/spectra/backups/scenes-star-flip-<stamp>.json. Not run against
live storage by this build — an operator/deploy step, same convention as
set_scene_colorset_preference.py and seed_star_strips.py.
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

SCENE_NAME = "STAR"
KIND_NAMES = ["Reverse Direction", "Reverse Momentarily (500ms)"]

OLD_SPIN_VALUE = -0.55
OLD_PARAMS = {"spin": {"mode": "absolute", "value": OLD_SPIN_VALUE,
                       "offset": None, "lo": None, "hi": None}}
NEW_PARAMS = {"spin_sign": {"mode": "absolute", "value": 0.0,
                            "offset": None, "lo": None, "hi": None}}


def _find_scene_id(store: dict, name: str, scenes_file: Path) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene '{name}' not found in {scenes_file} — "
                         "refusing to guess; check the name against the live store")
    if len(matches) > 1:
        raise SystemExit(f"scene '{name}' matches {len(matches)} scenes in "
                         f"{scenes_file} — refusing to guess which one")
    return matches[0]


def _kind_index(flare_kinds: list, name: str) -> int | None:
    for i, k in enumerate(flare_kinds):
        if k.get("name") == name:
            return i
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the store (default: dry-run print)")
    parser.add_argument("--revert", action="store_true",
                        help="perform the exact inverse patch (spin_sign -> spin: -0.55) "
                             "instead of the forward migration")
    parser.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE,
                        help="SPECTRA scenes store (default: the live one)")
    args = parser.parse_args()

    src_params, dst_params, direction = (
        (NEW_PARAMS, OLD_PARAMS, "revert (flip -> spin)") if args.revert
        else (OLD_PARAMS, NEW_PARAMS, "forward (spin -> flip)"))

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to migrate")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))

    sid = _find_scene_id(store, SCENE_NAME, args.scenes_file)
    scene = SceneV2(**store[sid])   # read-only: name confirmation + diagnostics
    print(f"— {SCENE_NAME} ({sid}), {direction}:")
    print(f"  flare_kinds (as loaded/migrated): {len(scene.flare_kinds)}")

    raw_kinds = store[sid].get("flare_kinds", [])
    to_patch: list[int] = []
    for kind_name in KIND_NAMES:
        idx = _kind_index(raw_kinds, kind_name)
        if idx is None:
            print(f"  '{kind_name}': not found on {SCENE_NAME} — "
                  "did add_star_reverse_flares.py ever run against this store? skipping")
            continue
        current = raw_kinds[idx].get("params")
        if current == dst_params:
            print(f"  '{kind_name}': already carries the target params — nothing to do")
            continue
        if current != src_params:
            print(f"  '{kind_name}': params don't match the expected pre-migration shape "
                  f"— refusing to guess. Found: {current}")
            continue
        to_patch.append(idx)
        print(f"  '{kind_name}': params {current} -> {dst_params}")

    if not to_patch:
        print("nothing to do")
        return

    if not args.apply:
        print(f"\nDRY RUN — would patch {len(to_patch)} flare kind(s) on {SCENE_NAME} in "
              f"{args.scenes_file} (use --apply). Only the `params` key on these two named "
              "flare_kinds entries changes; every other field on STAR, and every other "
              "scene in the store, is left byte-identical.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = backup_dir / f"scenes-star-flip-{stamp}.json"
    shutil.copy2(args.scenes_file, backup_path)
    print(f"backed up {args.scenes_file} -> {backup_path}")

    for idx in to_patch:
        raw_kinds[idx]["params"] = dict(dst_params)   # the ONLY key touched, per entry

    fd, tmp = tempfile.mkstemp(dir=str(args.scenes_file.parent), prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, args.scenes_file)
    print(f"patched {len(to_patch)} flare kind(s) on {SCENE_NAME} in {args.scenes_file} "
          "(params only — verify with a before/after diff)")


if __name__ == "__main__":
    main()
