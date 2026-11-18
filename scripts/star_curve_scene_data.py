"""STAR's scene data for the star curve study (2026-11-18,
data/star-curve-study/report.md) — ONE surgical change to ONE scene, with a
timestamped backup, a structural diff, --revert, and a dry run by default.

His words, verbatim: "I think we need to cut the max angle/frame the star
can rotate, but let's scale it all down by 50%. So slow the star rotation by
50% at all speeds, including the burst speeds, not just the static speed.
Additionally, slow the 'star setting' drift by 75%, but keep the burst
speeds. However, it seems like it currently linearly bounces between the
limits. Instead, have it follow a curve so that it spends more time flat,
and at the ends"; after the five-curve page, "D2 and all recs".

WHAT CHANGES, and nothing else (every other field on STAR and every other
scene byte-identical, asserted after the write):

  Matrix entry (radial):
    `star_wave_curve: "plateau"`      four holds per cycle — at the low end,
                                      at FLAT, at the high end, at flat again
    `star_wave_dwell_flat: 0.161`     his 50% held, split 1.8 : 1 toward flat
    `star_wave_dwell_end: 0.089`      (two flat holds + two limit holds)
    `star_wave_period_slow_s: 28.0`   the calm end, x4 slower than the 7.0 default
    `star_wave_period_fast_s: 3.0`    the loud end — his "keep the burst
                                      speeds"; written explicitly so the kept
                                      value is pinned in HIS data rather than
                                      riding the effect default

The effect's own default curve stays `cosine` with the 7.0/3.0 periods, so
every other Radial scene — House Star is the only one — is byte-identical.

NOT here: the rotation halving (fx/effects/radial.py
ROTATION_SPEED_SCALE 0.8 -> 0.4 and ROTATION_CAP_DEG_FRAME 18 -> 9) — engine
constants, the same way the cap was last time. His `base_rotation` is not set
on this entry at all (0, his "it can slow to a stop during quiet music"), so
the halved ceiling has nothing to clamp here.

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — the discipline of
scripts/star_improve_scene_data.py (whose helpers this script reuses):
SceneV2 is used to READ (validation before and after) only; the patched
store is re-read from disk and diffed against the pre-write snapshot, and
the run fails unless the only differing paths are the five listed above.

--revert performs the exact inverse (a value at neither the expected
target nor absent is REFUSED rather than overwritten). Idempotent.

Dry-run by default; --apply writes (atomic tmp+replace, indent=2) after
copying the store to storage/spectra/backups/scenes-star-curve-<stamp>.json.
Not run against live storage by the build — DJ applies it at deploy.
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
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from spectra import config                                   # noqa: E402
from spectra.models.scene import SceneV2                     # noqa: E402
from fx.effects.radial import (                              # noqa: E402
    DEFAULT_STAR_WAVE_DWELL_END, DEFAULT_STAR_WAVE_DWELL_FLAT,
    STAR_WAVE_CURVE, STAR_WAVE_PERIOD_FAST_S, STAR_WAVE_PERIOD_SLOW_S)
import star_improve_scene_data as base                       # noqa: E402

SCENE_NAME = base.SCENE_NAME
STAR_ID = base.STAR_ID
MATRIX_ENTRY = base.MATRIX_ENTRY
Refuse = base.Refuse
diff_paths = base.diff_paths

CURVE = {
    "star_wave_curve": STAR_WAVE_CURVE,
    "star_wave_dwell_flat": DEFAULT_STAR_WAVE_DWELL_FLAT,
    "star_wave_dwell_end": DEFAULT_STAR_WAVE_DWELL_END,
    "star_wave_period_slow_s": STAR_WAVE_PERIOD_SLOW_S,
    "star_wave_period_fast_s": STAR_WAVE_PERIOD_FAST_S,
}


def plan(raw: dict, revert: bool) -> list[tuple[str, Any]]:
    """The list of (path, action) this run would perform — printed on a dry
    run, applied on --apply. Each action is a closure over `raw`."""
    actions: list[tuple[str, Any]] = []
    matrix = base._entry(raw, MATRIX_ENTRY, "Matrix", "radial")
    mp = matrix.setdefault("params", {})
    if not mp.get("star_wave", False):
        raise Refuse(
            "STAR's Matrix entry does not have `star_wave` on — the curve "
            "params would do nothing; refusing rather than enabling the sway "
            "behind his back")
    for key, want in CURVE.items():
        cur = mp.get(key)
        if revert:
            if key in mp:
                if cur != want:
                    raise Refuse(f"Matrix.params.{key} is {cur!r}, not {want!r} — refusing")
                actions.append((f"Matrix.params.{key}", ("del", mp, key)))
        elif cur != want:
            if key in mp and cur is not None:
                raise Refuse(
                    f"Matrix.params.{key} is {cur!r}, neither absent nor "
                    f"{want!r} — refusing")
            actions.append((f"Matrix.params.{key}", ("set", mp, key, want)))
    return actions


def allowed_paths(sid: str) -> tuple[str, ...]:
    return tuple(f".{sid}.devices[{i}].params.{k}" for i in range(16) for k in CURVE)


def run(scenes_file: Path, *, apply: bool, revert: bool) -> list[str]:
    if not scenes_file.exists():
        raise Refuse(f"no {scenes_file} — nothing to migrate")
    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    before = copy.deepcopy(store)
    sid = base._find_scene(store)
    SceneV2(**store[sid])          # read-only: the store validates before
    actions = plan(store[sid], revert)
    label = "revert" if revert else "forward"
    print(f"— {SCENE_NAME} ({sid}), {label}: {len(actions)} change(s)")
    for path, act in actions:
        print(f"  {path}: {act[0]}" + (f" -> {act[3]!r}" if act[0] == 'set' else ""))
    if not actions:
        print("nothing to do")
        return []
    base.apply_actions(actions)
    SceneV2(**store[sid])          # ... and after
    changed = diff_paths(before, store)
    bad = [c for c in changed if c not in allowed_paths(sid)]
    if bad:
        raise Refuse(f"the patch touched paths outside STAR's Matrix curve params: {bad}")
    if not apply:
        print(f"\nDRY RUN — would write {len(changed)} leaf path(s) on {SCENE_NAME} in {scenes_file} "
              "(use --apply); every other scene byte-identical.")
        return changed
    backup_dir = scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-star-curve-{stamp}.json"
    shutil.copy2(scenes_file, backup)
    print(f"backed up {scenes_file} -> {backup}")
    fd, tmp = tempfile.mkstemp(dir=str(scenes_file.parent), prefix=".scenes-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, scenes_file)
    after = json.loads(scenes_file.read_text(encoding="utf-8"))
    reread = diff_paths(before, after)
    if sorted(reread) != sorted(changed):
        raise Refuse(f"post-write diff differs from the plan: {reread} vs {changed}")
    print(f"patched {len(changed)} leaf path(s) on {SCENE_NAME}; every other scene byte-identical")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the store (default: dry run)")
    ap.add_argument("--revert", action="store_true", help="the exact inverse")
    ap.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    a = ap.parse_args()
    run(a.scenes_file, apply=a.apply, revert=a.revert)


if __name__ == "__main__":
    main()
