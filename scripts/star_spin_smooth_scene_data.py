"""STAR's scene data for the spin smooth plan (2026-11-12,
data/star-spin-smooth/plan.md) — ONE surgical change to ONE scene, with a
timestamped backup, a structural diff, --revert, and a dry run by default.

His words, verbatim (after the star improve plan went live): "i like it,
but it is too jerky in it's spin especially on big bass hits. the burst
speed is too fast and fades too fast. I think sometimes it moves so fast
it's hard to tell it moved. We need to cap the burst speed. Do actual
analysis on how it moves, it shouldn't be jerky, but it should be
dynamic"; after the analysis page: "the burst fade should be snappier at
higher energies and lazier at low energies. do 18 degrees per frame for
now".

WHAT CHANGES, and nothing else (every other field on STAR and every other
scene byte-identical, asserted after the write):

  Matrix entry (radial): the release's two ends —
    `spin_release_low_s: 0.45`  (seconds the burst is spread over at energy 0)
    `spin_release_high_s: 0.2`  (... at energy 1; a straight line between)
  The effect's own default for both stays 0 (no filter — today's motion to
  the frame), so every other Radial scene is byte-identical.

NOT here: the 18 deg per frame cap (fx/effects/radial.py
ROTATION_CAP_DEG_FRAME — engine code, a constant by his "for now").

RAW-DICT PATCH, DELIBERATELY NOT scene_store.save() — the discipline of
scripts/star_improve_scene_data.py (whose helpers this script reuses):
SceneV2 is used to READ (validation before and after) only; the patched
store is re-read from disk and diffed against the pre-write snapshot, and
the run fails unless the only differing paths are the two listed above.

--revert performs the exact inverse (a value at neither the expected
target nor absent is REFUSED rather than overwritten). Idempotent.

Dry-run by default; --apply writes (atomic tmp+replace, indent=2) after
copying the store to storage/spectra/backups/scenes-star-spin-smooth-
<stamp>.json. Not run against live storage by the build — DJ applies it at
deploy.
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
    STAR_SPIN_RELEASE_HIGH_S, STAR_SPIN_RELEASE_LOW_S)
import star_improve_scene_data as base                       # noqa: E402

SCENE_NAME = base.SCENE_NAME
STAR_ID = base.STAR_ID
MATRIX_ENTRY = base.MATRIX_ENTRY
Refuse = base.Refuse
diff_paths = base.diff_paths

RELEASE = {"spin_release_low_s": STAR_SPIN_RELEASE_LOW_S,
           "spin_release_high_s": STAR_SPIN_RELEASE_HIGH_S}


def plan(raw: dict, revert: bool) -> list[tuple[str, Any]]:
    """The list of (path, action) this run would perform — printed on a dry
    run, applied on --apply. Each action is a closure over `raw`."""
    actions: list[tuple[str, Any]] = []
    matrix = base._entry(raw, MATRIX_ENTRY, "Matrix", "radial")
    mp = matrix.setdefault("params", {})
    for key, want in RELEASE.items():
        cur = mp.get(key)
        if revert:
            if key in mp:
                if cur != want:
                    raise Refuse(f"Matrix.params.{key} is {cur!r}, not {want} — refusing")
                actions.append((f"Matrix.params.{key}", ("del", mp, key)))
        elif cur != want:
            if key in mp and cur is not None:
                raise Refuse(f"Matrix.params.{key} is {cur!r}, neither absent nor {want} — refusing")
            actions.append((f"Matrix.params.{key}", ("set", mp, key, want)))
    return actions


def allowed_paths(sid: str) -> tuple[str, ...]:
    return tuple(f".{sid}.devices[{i}].params.{k}" for i in range(16) for k in RELEASE)


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
        raise Refuse(f"the patch touched paths outside STAR's Matrix release params: {bad}")
    if not apply:
        print(f"\nDRY RUN — would write {len(changed)} leaf path(s) on {SCENE_NAME} in {scenes_file} "
              "(use --apply); every other scene byte-identical.")
        return changed
    backup_dir = scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"scenes-star-spin-smooth-{stamp}.json"
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
