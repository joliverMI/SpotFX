#!/usr/bin/env python3
"""Create the SAURON scene, copied from his stored Eye V2. WRITTEN, NOT RUN.

The Admiral, 2026-10-10: "copy our current scene Effect called [Eye] and
make it look a lot more like the eye of Sauron" — answers: "1) Copy",
"crystal for now". The approved plan (data/sauron-eye-plan/report.md v2,
"go with all recs, approved") makes this phase 2: the copy script is
written while he tunes the effect live, and run only AFTER the tuning
gate (docs/ADDING_EFFECTS.md — a seeded scene would fossilize untuned
guesses). Nothing runs it automatically.

So this script copies, it does not author. Everything about the new scene
comes from the Eye V2 entry on disk the moment it runs — flare kinds, flare
bands and their kinds maps, lanes, bindings, labels, journey, dwell curve,
mode availability, colour-set acceptance, ramps — and the ONLY differences
are:

  * a new scene id and the name "Sauron"
  * a new id for each device entry (a scene's device ids are scene-local)
  * the Matrix entry's effect_type: "eye" -> "sauron"
  * the Matrix entry's STATIC params named in DROPPED_MATRIX_PARAMS are
    left out, so Sauron's own (tuned) defaults govern them:
      iris_size, gaze_radius  the plan settled bigger/closer values for the
                              Sauron eye (0.62 / 0.36) than Eye's;
      pupil_size              means something else on Sauron (the SLIT's
                              height as a fraction of the iris, not a round
                              pupil's radius as a fraction of the panel);
      spin, spin_audio        Sauron has no iris spin.
    Every BINDING (drift_speed, snap_threshold, snap_hold, flames) and
    every other static value is copied verbatim — those names mean the
    same thing on Sauron (the plan keeps them for exactly this reason).
  * MATRIX_TUNED, his values from the live tuning gate, layered on top of
    the Matrix entry's params (empty until phase 3 fills it in).
  * one new flare kind, "Sauron Surge" (type sauron_surge), APPENDED to
    the scene's flare_kinds and attached to NO band — he attaches it on
    the lane rack.

...plus, in the sequencer store, Eye V2's own selector entry (likelihood
curve, genre multipliers, dwell weight) re-keyed to the new scene id, and
any affinity edge naming Eye V2 mirrored onto Sauron.

STATED, NOT CHANGED:
  * Eye V2 is DISABLED today, so the copy is born disabled too (the
    `disabled` flag is copied like everything else); the dry run says so.
  * A copied scene is not proof he authored it: whatever Eye V2 holds that
    day is copied, including its Pulse flare kinds and their -92/-355 ms
    offsets. The dry run prints the whole copy before --apply.
  * The Strips (`blackhole1d`) and Singles entries are untouched — a
    Sauron strip effect (`sauron1d`) is a later phase.

RAW-DICT COPY, DELIBERATELY NOT scene_store.save() — the same reason as
scripts/seed_fish_scene.py: a SceneV2 round trip rewrites legacy fields in
canonical form, silently changing HIS Eye V2 data as a side effect. SceneV2
is used only to READ (validation + diagnostics).

NOTHING ABOUT EYE V2 MAY CHANGE: every pre-existing scene is serialized
before and after; any difference aborts before `os.replace`, and the file
is re-read from disk afterwards and compared again.

Deterministic ids (uuid5), so re-running upserts the same scene. Dry-run by
default; --apply backs up both stores to storage/spectra/backups/ first.
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

from spectra import config
from spectra.models.scene import FlareKind, SceneV2

SOURCE_SCENE_NAME = "Eye V2"
NEW_SCENE_NAME = "Sauron"
SOURCE_EFFECT = "eye"
NEW_EFFECT = "sauron"
SURGE_KIND_NAME = "Sauron Surge"
# Static Matrix params NOT copied (see the module docstring for why each).
DROPPED_MATRIX_PARAMS = ("iris_size", "gaze_radius", "pupil_size", "spin",
                         "spin_audio")
# His values from the live tuning gate — phase 3 fills this in. Layered on
# top of the copied Matrix params.
MATRIX_TUNED: dict = {}
# Deterministic id namespace — re-running this script upserts.
NS = uuid.UUID("3c1f2a9e-5b7d-5e11-a0c4-5a0e2b8d9f37")


def _sid(*parts: str) -> str:
    return str(uuid.uuid5(NS, ":".join(parts)))


def _find_one(store: dict, name: str) -> str:
    matches = [sid for sid, raw in store.items() if raw.get("name") == name]
    if not matches:
        raise SystemExit(
            f"scene {name!r} not found — refusing to guess. Check the name "
            f"against the live store."
        )
    if len(matches) > 1:
        raise SystemExit(
            f"scene {name!r} matches {len(matches)} entries — refusing to "
            f"guess which one to copy."
        )
    return matches[0]


def _describe(scene: SceneV2) -> str:
    devices = "\n".join(
        f"      {d.target_kind}:{d.target} -> {d.effect_type} "
        f"({len(d.params)} params: {sorted(d.params)})"
        for d in scene.devices
    )
    bands = scene.responses.get("flare")
    band_lines = ""
    if bands is not None:
        band_lines = "\n".join(
            f"      [{b.intensity_min}-{b.intensity_max}] curve={b.curve} "
            f"gain={b.gain} kinds={sorted(b.kinds)}"
            for b in bands.bands
        )
    kinds = "\n".join(
        f"      {k.name} ({k.type}) offset={k.trigger_offset_ms}ms "
        f"enabled={k.enabled}"
        for k in scene.flare_kinds
    )
    return (
        f"    disabled: {scene.disabled}\n"
        f"    labels: {scene.labels}\n"
        f"    devices:\n{devices}\n"
        f"    flare kinds ({len(scene.flare_kinds)}):\n{kinds}\n"
        f"    flare bands:\n{band_lines}\n"
        f"    entry_ramp_ms={scene.entry_ramp_ms} "
        f"accept_all_sets={scene.accept_all_sets} "
        f"accepted_set_ids={len(scene.accepted_set_ids)}\n"
        f"    update_kind={scene.update_kind} "
        f"journey={scene.color_journey.mode!r}"
    )


def surge_kind() -> dict:
    """The new, unattached sauron_surge kind, in the stored raw shape."""
    return FlareKind(name=SURGE_KIND_NAME,
                     type="sauron_surge").model_dump(mode="json")


def build_sauron(src_raw: dict) -> tuple[dict, list[str]]:
    """The copy, and the list of Matrix params left out. Everything is
    `src_raw` verbatim except the documented differences."""
    new = copy.deepcopy(src_raw)
    new["id"] = _sid("scene", NEW_SCENE_NAME)
    new["name"] = NEW_SCENE_NAME
    swapped = 0
    dropped: list[str] = []
    for dev in new.get("devices", []):
        old_id = dev.get("id", "")
        dev["id"] = _sid("device", NEW_SCENE_NAME, str(old_id))
        if dev.get("effect_type") == SOURCE_EFFECT:
            dev["effect_type"] = NEW_EFFECT
            swapped += 1
            params = dev.setdefault("params", {})
            for key in DROPPED_MATRIX_PARAMS:
                if key in params:
                    params.pop(key)
                    dropped.append(key)
            params.update(copy.deepcopy(MATRIX_TUNED))
    if swapped != 1:
        raise SystemExit(
            f"expected exactly one {SOURCE_EFFECT!r} device entry to swap, "
            f"found {swapped} — refusing to guess."
        )
    kinds = new.setdefault("flare_kinds", [])
    if any(k.get("name") == SURGE_KIND_NAME for k in kinds):
        raise SystemExit(
            f"{SOURCE_SCENE_NAME} already declares a kind named "
            f"{SURGE_KIND_NAME!r} — refusing to guess which one to keep."
        )
    kinds.append(surge_kind())
    return new, dropped


def sequencer_plan(seq: dict, src_id: str, new_id: str) -> dict:
    """What the sequencer store gains: the source scene's own selector
    entry re-keyed, and any affinity edge naming the source mirrored onto
    the new scene. Nothing existing is modified."""
    cfg = seq.setdefault("config", {})
    entries = cfg.setdefault("entries", {})
    plan: dict = {"entry": None, "affinity": []}
    src_entry = entries.get(src_id)
    if src_entry is not None:
        plan["entry"] = copy.deepcopy(src_entry)
    for edge in cfg.get("affinity", []) or []:
        mirrored = None
        if edge.get("from_id") == src_id or edge.get("from") == src_id:
            mirrored = copy.deepcopy(edge)
            for key in ("from_id", "from"):
                if key in mirrored:
                    mirrored[key] = new_id
        elif edge.get("to_id") == src_id or edge.get("to") == src_id:
            mirrored = copy.deepcopy(edge)
            for key in ("to_id", "to"):
                if key in mirrored:
                    mirrored[key] = new_id
        if mirrored is not None:
            plan["affinity"].append(mirrored)
    existing = {json.dumps(e, sort_keys=True)
                for e in cfg.get("affinity", []) or []}
    plan["affinity"] = [
        e for e in plan["affinity"]
        if json.dumps(e, sort_keys=True) not in existing
    ]
    return plan


def difference_report(src_raw: dict, new_raw: dict) -> list[str]:
    """Every field of the copy that is NOT identical to the source."""
    diffs = []
    for key in sorted(set(src_raw) | set(new_raw)):
        a, b = src_raw.get(key), new_raw.get(key)
        if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True):
            continue
        if key == "devices":
            for da, db in zip(a, b):
                for dk in sorted(set(da) | set(db)):
                    if json.dumps(da.get(dk), sort_keys=True) != \
                            json.dumps(db.get(dk), sort_keys=True):
                        diffs.append(f"devices[{da.get('target')}].{dk}: "
                                     f"{da.get(dk)!r} -> {db.get(dk)!r}")
        elif key == "flare_kinds":
            added = [k.get("name") for k in b[len(a or []):]]
            if (a or []) != b[:len(a or [])]:
                diffs.append("flare_kinds: EXISTING KINDS CHANGED")
            diffs.append(f"flare_kinds: + {added}")
        else:
            diffs.append(f"{key}: {a!r} -> {b!r}")
    return diffs


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.stem}-", suffix=".json"
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--apply", action="store_true",
                    help="write the stores (default: dry-run print)")
    ap.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    ap.add_argument("--sequencer-file", type=Path,
                    default=config.SEQUENCER_FILE)
    args = ap.parse_args(argv)

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to copy from")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    src_id = _find_one(store, SOURCE_SCENE_NAME)
    src_raw = store[src_id]
    new_id_early = _sid("scene", NEW_SCENE_NAME)
    before = {sid: json.dumps(raw, sort_keys=True)
              for sid, raw in store.items() if sid != new_id_early}
    print(f"source: {SOURCE_SCENE_NAME} ({src_id})")
    print(_describe(SceneV2(**src_raw)))

    new_raw, dropped = build_sauron(src_raw)
    new_id = new_raw["id"]
    new = SceneV2(**new_raw)            # read-only: validation + diagnostics
    print(f"\nnew:    {NEW_SCENE_NAME} ({new_id})"
          f"{'   [already present — upsert]' if new_id in store else ''}")
    print(_describe(new))
    if new.disabled:
        print(f"    NOTE: born DISABLED because {SOURCE_SCENE_NAME} is "
              f"disabled today — switch it on with its power button.")
    print(f"    Matrix params left out (Sauron's own defaults govern): "
          f"{dropped or 'none'}")
    print(f"    Matrix params from the tuning gate: "
          f"{MATRIX_TUNED or 'none yet (phase 3 fills MATRIX_TUNED in)'}")

    diffs = difference_report(src_raw, new_raw)
    print(f"\ndifferences from {SOURCE_SCENE_NAME} "
          f"(everything else is a verbatim copy):")
    for line in diffs:
        print(f"    {line}")
    unexpected = [
        d for d in diffs
        if not (d.split(":")[0] in {"id", "name"}
                or d.startswith("devices[")
                or (d.startswith("flare_kinds: +")))
    ]
    if unexpected:
        raise SystemExit(f"unexpected differences, refusing to write: "
                         f"{unexpected}")

    seq = (json.loads(args.sequencer_file.read_text(encoding="utf-8"))
           if args.sequencer_file.exists() else {"config": {}, "curves": {}})
    seq_before = json.dumps(seq, sort_keys=True)
    plan = sequencer_plan(seq, src_id, new_id)
    print("\nsequencer:")
    if plan["entry"] is None:
        print(f"    {SOURCE_SCENE_NAME} has NO selector entry in "
              f"{args.sequencer_file} — nothing to copy")
    else:
        print(f"    selector entry re-keyed to {NEW_SCENE_NAME}: "
              f"{json.dumps(plan['entry'], sort_keys=True)}")
    print(f"    affinity edges mirrored: {len(plan['affinity'])}")
    for edge in plan["affinity"]:
        print(f"      {json.dumps(edge, sort_keys=True)}")

    if not args.apply:
        print(f"\nDRY RUN — would add 1 scene to {args.scenes_file} and "
              f"{'1' if plan['entry'] else '0'} sequencer entry + "
              f"{len(plan['affinity'])} affinity edge(s) to "
              f"{args.sequencer_file}. Use --apply (AFTER the tuning gate).")
        return 0

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for path, tag in ((args.scenes_file, "scenes"),
                      (args.sequencer_file, "sequencer")):
        if path.exists():
            dest = backup_dir / f"{tag}-pre-sauron-{stamp}.json"
            shutil.copy2(path, dest)
            print(f"backed up {path} -> {dest}")

    store[new_id] = new_raw
    after = {sid: json.dumps(raw, sort_keys=True)
             for sid, raw in store.items() if sid != new_id}
    if after != before:
        changed = [sid for sid in before if before[sid] != after.get(sid)]
        raise SystemExit(
            "ABORTED before writing: existing scene(s) would change — "
            f"{changed}. Nothing was written."
        )
    _atomic_write(args.scenes_file, store)
    print(f"wrote {args.scenes_file}: +1 scene ({NEW_SCENE_NAME})")

    if plan["entry"] is not None or plan["affinity"]:
        cfg = seq.setdefault("config", {})
        if plan["entry"] is not None:
            cfg.setdefault("entries", {})[new_id] = plan["entry"]
        if plan["affinity"]:
            cfg.setdefault("affinity", []).extend(plan["affinity"])
        _atomic_write(args.sequencer_file, seq)
        print(f"wrote {args.sequencer_file}: "
              f"+{1 if plan['entry'] else 0} entry, "
              f"+{len(plan['affinity'])} affinity edge(s)")
    else:
        assert json.dumps(seq, sort_keys=True) == seq_before
        print(f"{args.sequencer_file} unchanged (nothing to copy)")

    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    for sid, blob in before.items():
        if json.dumps(written[sid], sort_keys=True) != blob:
            raise SystemExit(
                f"POST-WRITE CHECK FAILED: scene {sid} changed on disk. "
                f"Restore from {backup_dir}."
            )
    print(f"verified on disk: all {len(before)} pre-existing scenes "
          f"byte-identical, including {SOURCE_SCENE_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
