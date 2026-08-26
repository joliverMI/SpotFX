#!/usr/bin/env python3
"""Create the FISH scene, copied wholesale from his live Orbits V2.

His ask (2026-08-25, corr=6dd10a8c3c5bd72a): "create a new effect and scene
that is almost a copy of orbits. It should have all the same spectra values
as orbits in terms of flares, initial values, weightings, curves, etc. Call
it Fish."

So this script copies, it does not author. Everything about the new scene
comes from the Orbits V2 entry that is on disk at the moment it runs —
flare kinds, flare bands and their kinds maps, initial params, colour
handling, journey, dwell curve, mode availability, colour-set acceptance,
labels, ramps — and the ONLY differences are:

  * a new scene id and the name "Fish"
  * a new id for each device entry (a scene's device ids are scene-local)
  * the Matrix entry's effect_type: "orbits" -> "fish"

...plus, in the sequencer store, the Orbits scene's own selector entry
(likelihood curve, genre multipliers, dwell weight) re-keyed to the new
scene id, and any affinity edge naming Orbits mirrored onto Fish.

DELIBERATE, STATED NON-COPY — the Strips entry keeps `orbits1d`. His spec
is inherently 2D ("from a birds-eye-view"); there is no `fish1d`, and
inventing a 1-pixel-tall fish was not asked for. The strips therefore run
exactly what Orbits V2 runs on them today. A `fish1d` is future work if he
wants it.

RAW-DICT COPY, DELIBERATELY NOT scene_store.save(): loading a scene through
SceneV2 and writing it back re-serializes every field in current canonical
form — in particular the legacy flare-band migration shim
(_migrate_flare_kinds) permanently rewrites param_patch/gain/reroll_dice/
color_set_jump into the newer flare_kinds/kinds shape. That would silently
rewrite HIS Orbits data as a side effect of adding a new scene. This script
loads the raw JSON, uses SceneV2 only to READ (validation + the printed
diagnostics), and appends one new raw entry. See
scripts/set_scene_colorset_preference.py, which established this rule.

NOTHING ABOUT ORBITS MAY CHANGE. Before writing, every pre-existing scene
entry is serialized; after writing, they are serialized again and compared
byte for byte. Any difference — in Orbits V2 or in any other scene — aborts
before `os.replace` and leaves the store untouched.

Deterministic ids (uuid5, the seeder convention in docs/ADDING_EFFECTS.md),
so re-running upserts the same scene instead of piling up copies.

Dry-run by default; --apply backs up both stores to
storage/spectra/backups/ first and prints a before/after diff.
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
from spectra.models.scene import SceneV2

SOURCE_SCENE_NAME = "Orbits V2"
NEW_SCENE_NAME = "Fish"
SOURCE_EFFECT = "orbits"
NEW_EFFECT = "fish"
# Deterministic id namespace — re-running this script upserts.
NS = uuid.UUID("6f19b7c2-1c4e-5a2f-9b3d-fa5b2e0d7c11")


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
        f"({len(d.params)} params)"
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
    return (
        f"    labels: {scene.labels}\n"
        f"    devices:\n{devices}\n"
        f"    flare kinds ({len(scene.flare_kinds)}): "
        f"{[k.name for k in scene.flare_kinds]}\n"
        f"    flare bands:\n{band_lines}\n"
        f"    entry_ramp_ms={scene.entry_ramp_ms} "
        f"accept_all_sets={scene.accept_all_sets} "
        f"accepted_set_ids={len(scene.accepted_set_ids)}\n"
        f"    update_kind={scene.update_kind} "
        f"journey={scene.color_journey.mode!r}"
    )


def build_fish(src_raw: dict) -> dict:
    """The copy. Everything is `src_raw` verbatim except the three
    documented differences."""
    fish = copy.deepcopy(src_raw)
    fish["id"] = _sid("scene", NEW_SCENE_NAME)
    fish["name"] = NEW_SCENE_NAME
    swapped = 0
    for dev in fish.get("devices", []):
        old_id = dev.get("id", "")
        dev["id"] = _sid("device", NEW_SCENE_NAME, str(old_id))
        if dev.get("effect_type") == SOURCE_EFFECT:
            dev["effect_type"] = NEW_EFFECT
            swapped += 1
    if swapped != 1:
        raise SystemExit(
            f"expected exactly one {SOURCE_EFFECT!r} device entry to swap, "
            f"found {swapped} — refusing to guess."
        )
    return fish


def sequencer_plan(seq: dict, src_id: str, fish_id: str) -> dict:
    """What the sequencer store gains: the source scene's own selector entry
    (curve + genre multipliers + dwell weight) re-keyed, and any affinity
    edge naming the source mirrored onto the new scene. Nothing existing is
    modified."""
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
                    mirrored[key] = fish_id
        elif edge.get("to_id") == src_id or edge.get("to") == src_id:
            mirrored = copy.deepcopy(edge)
            for key in ("to_id", "to"):
                if key in mirrored:
                    mirrored[key] = fish_id
        if mirrored is not None:
            plan["affinity"].append(mirrored)
    # idempotence: never add an edge that is already there
    existing = {json.dumps(e, sort_keys=True) for e in cfg.get("affinity", []) or []}
    plan["affinity"] = [
        e for e in plan["affinity"]
        if json.dumps(e, sort_keys=True) not in existing
    ]
    return plan


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.stem}-", suffix=".json"
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--apply", action="store_true",
                    help="write the stores (default: dry-run print)")
    ap.add_argument("--scenes-file", type=Path, default=config.SCENES_FILE)
    ap.add_argument("--sequencer-file", type=Path,
                    default=config.SEQUENCER_FILE)
    args = ap.parse_args()

    if not args.scenes_file.exists():
        raise SystemExit(f"no {args.scenes_file} — nothing to copy from")
    store = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    src_id = _find_one(store, SOURCE_SCENE_NAME)
    src_raw = store[src_id]
    # The byte-identity baseline covers every scene EXCEPT the one this
    # script owns — a re-run upserts Fish, and only Fish.
    fish_id_early = _sid("scene", NEW_SCENE_NAME)
    before = {sid: json.dumps(raw, sort_keys=True)
              for sid, raw in store.items() if sid != fish_id_early}
    print(f"source: {SOURCE_SCENE_NAME} ({src_id})")
    print(_describe(SceneV2(**src_raw)))

    fish_raw = build_fish(src_raw)
    fish_id = fish_raw["id"]
    fish = SceneV2(**fish_raw)          # read-only: validation + diagnostics
    print(f"\nnew:    {NEW_SCENE_NAME} ({fish_id})"
          f"{'   [already present — upsert]' if fish_id in store else ''}")
    print(_describe(fish))

    # the exhaustive difference report: everything that is NOT identical
    diffs = []
    for key in sorted(set(src_raw) | set(fish_raw)):
        a, b = src_raw.get(key), fish_raw.get(key)
        if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
            if key == "devices":
                for da, db in zip(a, b):
                    for dk in sorted(set(da) | set(db)):
                        if json.dumps(da.get(dk), sort_keys=True) != \
                                json.dumps(db.get(dk), sort_keys=True):
                            diffs.append(
                                f"devices[{da.get('target')}].{dk}: "
                                f"{da.get(dk)!r} -> {db.get(dk)!r}"
                            )
            else:
                diffs.append(f"{key}: {a!r} -> {b!r}")
    print("\ndifferences from Orbits V2 (everything else is a verbatim copy):")
    for line in diffs:
        print(f"    {line}")
    expected = {"id", "name"}
    unexpected = [
        d for d in diffs
        if not (d.split(":")[0] in expected or d.startswith("devices["))
    ]
    if unexpected:
        raise SystemExit(f"unexpected differences, refusing to write: "
                         f"{unexpected}")

    seq = (json.loads(args.sequencer_file.read_text(encoding="utf-8"))
           if args.sequencer_file.exists() else {"config": {}, "curves": {}})
    seq_before = json.dumps(seq, sort_keys=True)
    plan = sequencer_plan(seq, src_id, fish_id)
    print("\nsequencer:")
    if plan["entry"] is None:
        print(f"    Orbits V2 has NO selector entry in {args.sequencer_file} "
              f"— nothing to copy (Fish gets none either; the sequencer's "
              f"own dark switch is separate)")
    else:
        print(f"    selector entry re-keyed to Fish: "
              f"{json.dumps(plan['entry'], sort_keys=True)}")
    print(f"    affinity edges mirrored: {len(plan['affinity'])}")
    for edge in plan["affinity"]:
        print(f"      {json.dumps(edge, sort_keys=True)}")

    if not args.apply:
        print(f"\nDRY RUN — would add 1 scene to {args.scenes_file} and "
              f"{'1' if plan['entry'] else '0'} sequencer entry + "
              f"{len(plan['affinity'])} affinity edge(s) to "
              f"{args.sequencer_file}. Use --apply.")
        return

    backup_dir = args.scenes_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for path, tag in ((args.scenes_file, "scenes"),
                      (args.sequencer_file, "sequencer")):
        if path.exists():
            dest = backup_dir / f"{tag}-pre-fish-{stamp}.json"
            shutil.copy2(path, dest)
            print(f"backed up {path} -> {dest}")

    store[fish_id] = fish_raw
    after = {sid: json.dumps(raw, sort_keys=True)
             for sid, raw in store.items() if sid != fish_id}
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
            cfg.setdefault("entries", {})[fish_id] = plan["entry"]
        if plan["affinity"]:
            cfg.setdefault("affinity", []).extend(plan["affinity"])
        _atomic_write(args.sequencer_file, seq)
        print(f"wrote {args.sequencer_file}: "
              f"+{1 if plan['entry'] else 0} entry, "
              f"+{len(plan['affinity'])} affinity edge(s)")
    else:
        assert json.dumps(seq, sort_keys=True) == seq_before
        print(f"{args.sequencer_file} unchanged (nothing to copy)")

    # re-read from disk and prove it, rather than trusting the in-memory dict
    written = json.loads(args.scenes_file.read_text(encoding="utf-8"))
    for sid, blob in before.items():
        if json.dumps(written[sid], sort_keys=True) != blob:
            raise SystemExit(
                f"POST-WRITE CHECK FAILED: scene {sid} changed on disk. "
                f"Restore from {backup_dir}."
            )
    print(f"verified on disk: all {len(before)} pre-existing scenes "
          f"byte-identical, including {SOURCE_SCENE_NAME}")


if __name__ == "__main__":
    main()
