#!/usr/bin/env python3
"""Create the PULSE TEST scene: a copy of one of his music scenes with the
Singles running Pulse instead of Power (single-led-power plan, phase 2 —
the tuning gate: he tunes Pulse's defaults on this scene before any real
scene switches over, which is phase 4 and not this script).

THE COPY, and its only differences from the source (default "Orbits V2",
`--source NAME` for another):

  * a new scene id and the name "Pulse Test (<source>)"
  * a new id for each device entry (device ids are scene-local)
  * the Singles entry's effect_type: "power" -> "pulse", and its params
    emptied, so Pulse starts from its own defaults (Power's
    bass_decay_rate/blur/flip mean nothing to it) — the defaults ARE what
    he is here to tune
  * the label "pulse-test" added

Everything else — flare kinds and bands, the other entries, colour
handling, journey, dwell curve, colour-set acceptance, ramps — is the
source verbatim, so the only thing that differs between the two scenes in
the room is the Singles.

NEVER DRAWN AUTOMATICALLY. The sequencer store is not touched: a scene with
no selector entry is never a candidate for the kernel's draws (the house
scenes' precedent), so the test scene plays only when he fires it from the
Scenes page or pins it with Force Scene. No existing scene changes.

RAW-DICT COPY, deliberately not scene_store.save() (scripts/seed_fish_scene.py
has the reason: a SceneV2 round-trip would rewrite the source's legacy flare
fields). SceneV2 is used only to READ (validation + the printed report).
Every pre-existing scene is serialised before and after the write and
compared byte for byte; any difference aborts before os.replace. The file
is re-read from disk afterwards and checked again.

Deterministic ids (uuid5), so re-running upserts the same scene.
Dry-run by default; --apply backs up the store first; --remove deletes
exactly the scene this script owns (and nothing else).
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
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spectra import config  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402

DEFAULT_SOURCE = "Orbits V2"
SINGLES = "Singles"
SOURCE_EFFECT = "power"
NEW_EFFECT = "pulse"
TEST_LABEL = "pulse-test"
NS = uuid.UUID("3b1d7f52-7a0e-5c4b-9e21-5d0a8c7f4e93")


def test_name(source: str) -> str:
    return f"Pulse Test ({source})"


def _sid(*parts: str) -> str:
    return str(uuid.uuid5(NS, ":".join(parts)))


def scene_id_for(source: str) -> str:
    return _sid("scene", test_name(source))


def _find_one(store: dict, name: str) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(f"scene {name!r} not found — refusing to guess. "
                         f"Check the name against the live store.")
    if len(matches) > 1:
        raise SystemExit(f"scene {name!r} matches {len(matches)} entries — "
                         f"refusing to guess which one to copy.")
    return matches[0]


def build_test_scene(src_raw: dict, source: str) -> dict:
    """The copy: `src_raw` verbatim except the documented differences."""
    out = copy.deepcopy(src_raw)
    name = test_name(source)
    out["id"] = _sid("scene", name)
    out["name"] = name
    labels = list(out.get("labels") or [])
    if TEST_LABEL not in labels:
        labels.append(TEST_LABEL)
    out["labels"] = labels
    swapped = 0
    for dev in out.get("devices", []):
        dev["id"] = _sid("device", name, str(dev.get("id", "")))
        if dev.get("target") != SINGLES:
            continue
        if dev.get("effect_type") != SOURCE_EFFECT:
            raise SystemExit(
                f"{source}'s Singles entry runs {dev.get('effect_type')!r}, "
                f"not {SOURCE_EFFECT!r} — refusing to guess.")
        if dev.get("effect_steps"):
            raise SystemExit(
                f"{source}'s Singles entry has intensity steps — refusing to "
                f"guess which effect each step should become.")
        if dev.get("drift"):
            raise SystemExit(
                f"{source}'s Singles entry declares drift on Power's params "
                f"— refusing to guess what it should drive on Pulse.")
        dev["effect_type"] = NEW_EFFECT
        dev["params"] = {}
        swapped += 1
    if swapped != 1:
        raise SystemExit(f"expected exactly one {SINGLES} entry running "
                         f"{SOURCE_EFFECT!r}, found {swapped} — refusing to "
                         f"guess.")
    return out


def _describe(scene: SceneV2) -> str:
    return "\n".join(
        f"      {d.target_kind}:{d.target} -> {d.effect_type} "
        f"({len(d.params)} params)" for d in scene.devices)


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=f".{path.stem}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _backup(path: Path, tag: str) -> Path:
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest = backup_dir / f"scenes-{tag}-{stamp}.json"
    n = 1
    while dest.exists():               # two runs in one second keep both
        n += 1
        dest = backup_dir / f"scenes-{tag}-{stamp}-{n}.json"
    shutil.copy2(path, dest)
    return dest


def _write_checked(path: Path, store: dict, before: dict) -> None:
    """Write `store`, refusing if any scene in `before` would change, then
    prove it from disk."""
    after = {sid: json.dumps(raw, sort_keys=True)
             for sid, raw in store.items() if sid in before}
    changed = [sid for sid in before if before[sid] != after.get(sid)]
    if changed:
        raise SystemExit(f"ABORTED before writing: existing scene(s) would "
                         f"change — {changed}. Nothing was written.")
    _atomic_write(path, store)
    written = json.loads(path.read_text(encoding="utf-8"))
    for sid, blob in before.items():
        if json.dumps(written.get(sid), sort_keys=True) != blob:
            raise SystemExit(f"POST-WRITE CHECK FAILED: scene {sid} changed "
                             f"on disk. Restore from {path.parent / 'backups'}.")


def run(scenes_file: Path, source: str, *, apply: bool = False,
        remove: bool = False, out=print) -> dict:
    if not scenes_file.exists():
        raise SystemExit(f"no {scenes_file} — nothing to copy from")
    store = json.loads(scenes_file.read_text(encoding="utf-8"))
    test_id = scene_id_for(source)
    before = {sid: json.dumps(raw, sort_keys=True)
              for sid, raw in store.items() if sid != test_id}

    if remove:
        if test_id not in store:
            out(f"{test_name(source)} is not in {scenes_file} — nothing to "
                f"remove.")
            return {"removed": False}
        if not apply:
            out(f"DRY RUN — would remove {test_name(source)} ({test_id}). "
                f"Use --apply.")
            return {"removed": False, "would_remove": test_id}
        dest = _backup(scenes_file, "pre-pulse-test-remove")
        out(f"backed up {scenes_file} -> {dest}")
        del store[test_id]
        _write_checked(scenes_file, store, before)
        out(f"removed {test_name(source)}; all {len(before)} other scenes "
            f"byte-identical on disk")
        return {"removed": True, "scene_id": test_id}

    src_id = _find_one(store, source)
    if src_id == test_id:
        raise SystemExit("the source is the test scene itself — refusing.")
    src_raw = store[src_id]
    test_raw = build_test_scene(src_raw, source)
    test = SceneV2(**test_raw)        # read-only: validation + the report
    out(f"source: {source} ({src_id})")
    out(_describe(SceneV2(**src_raw)))
    out(f"new:    {test.name} ({test_id})"
        f"{'   [already present — upsert]' if test_id in store else ''}")
    out(_describe(test))
    out("never drawn automatically: no sequencer entry is written — fire it "
        "from the Scenes page or pin it with Force Scene")
    if not apply:
        out(f"\nDRY RUN — would add 1 scene to {scenes_file}. Use --apply.")
        return {"applied": False, "scene_id": test_id, "scene": test_raw}
    dest = _backup(scenes_file, "pre-pulse-test")
    out(f"backed up {scenes_file} -> {dest}")
    store[test_id] = test_raw
    _write_checked(scenes_file, store, before)
    out(f"wrote {scenes_file}: {test.name}; all {len(before)} pre-existing "
        f"scenes byte-identical on disk, including {source}")
    return {"applied": True, "scene_id": test_id, "scene": test_raw}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the store (default: dry-run print)")
    ap.add_argument("--remove", action="store_true",
                    help="remove the test scene this script owns")
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help=f"the music scene to copy (default {DEFAULT_SOURCE!r})")
    ap.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    args = ap.parse_args()
    run(args.scenes_file, args.source, apply=args.apply, remove=args.remove)


if __name__ == "__main__":
    main()
