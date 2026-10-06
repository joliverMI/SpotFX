#!/usr/bin/env python3
"""Drop-detector acceptance (drop-detection plan, phase 2) — the plan's own
four-song table, reproduced by the SHIPPED code.

READ-ONLY against the live checkout's storage (default /home/javi/SpotFX,
override with --live-root): the four songs' stored audio shapes and beat
analyses, and his own triggers for those four songs. NOTHING is written
there — every file this run reads is COPIED into a throwaway temp
directory and every store it touches (AUDIO_SHAPES_DIR, TRIGGERS_FILE,
DROP_SEQUENCES_FILE, ROOM_CONTROLS_FILE) is repointed at that copy first,
the scripts/check_transition_alignment.py isolation shape.

Four songs, the Admiral's: Contra, Dopamine, Pop Off (the EDM examples)
and 100 Millones (not EDM, has a drop).

THREE THINGS ARE HELD:

  1. THE PORT. spectra/services/drop_detector.py is method B of the plan's
     testbed ported line for line. Its raw output (every drop at the
     suggested threshold, its score, lull, charge and break length, before
     the guards) must equal the testbed's own, recorded below from
     `drop_testbed.py song <name>` at the plan's commit — exactly, to the
     millisecond.
  2. THE PLAN'S NUMBERS (report section 5.1), through the store
     (drop_sequences.ensure_detected) and the shared scorer
     (drop_scoring.score_song): 11 of his 13 drops found at the suggested
     tier; 9 of 13 at the confident tier with NOTHING false on the three
     EDM songs. A drop is found within one beat of his mark.
  3. THE STORE. A second ensure_detected is "fresh" (the stamp holds), and
     the merged view stands every detection that sits on one of his own
     drops down as "matches yours".

Prints a markdown table (the PR body's) and exits non-zero on any failure.

Run from repo root: .venv/bin/python scripts/check_drop_detector.py
                     [--live-root /home/javi/SpotFX]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SONGS = [
    ("Contra", "spotify:track:2zVg53xdC6RMpthWju6LRT", True),
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT", True),
    ("Pop Off", "spotify:track:4PolqZLqReEqc3yURJtzc4", True),
    ("100 Millones", "spotify:track:4Ixc50wY5pbUvNEogTQ2wL", False),
]

# The testbed's own output (drop_testbed.py song <name>, plan commit, method
# B at the suggested threshold 0.7, lull rule `tail`, charge rule `build2`):
# (drop_ms, score rounded to 3, lull_ms, charge_ms, break_beats).
GOLDEN = {
    "Contra": [
        (47612, 0.717, 46080, 39915, 3.22), (66803, 1.202, 65236, 62484, 3.29),
        (112883, 1.088, 111130, 105209, 3.68), (158969, 0.821, 147551, 139552, 23.99),
        (162811, 0.707, 161372, 158511, 3.02), (170486, 0.712, 169081, 162811, 2.95),
        (189677, 1.431, 187889, 181039, 3.76), (205048, 1.499, 202332, 197363, 3.73),
    ],
    "Dopamine": [
        (47853, 1.532, 41827, 35047, 12.72), (87582, 0.918, 85086, 81327, 5.97),
        (100829, 0.974, 100028, 97520, 1.92),
    ],
    "Pop Off": [
        (59570, 1.211, 57248, 53474, 5.56), (100983, 0.8, 100228, 94446, 1.81),
        (171983, 1.077, 169302, 165226, 6.41), (178753, 1.309, 177196, 171152, 3.81),
    ],
    "100 Millones": [
        (39314, 0.773, 37939, 32497, 2.57), (59194, 1.101, 47873, 39314, 21.2),
        (87070, 1.014, 81962, 77306, 9.56), (96114, 0.793, 94733, 87070, 2.59),
        (116002, 0.944, 104682, 96114, 21.2), (127357, 1.132, 125267, 118835, 3.91),
        (150084, 1.147, 137267, 133860, 24.0), (155819, 0.905, 153683, 150084, 4.0),
        (166594, 1.004, 161485, 153242, 9.57), (221442, 1.029, 217030, 212926, 6.57),
    ],
}

# The plan's acceptance (report section 5.1; the Admiral approved it).
PLAN_FOUND = 11
PLAN_CONFIDENT_FOUND = 9
PLAN_HIS_DROPS = 13


def _stem_for(live_root: Path, uri: str) -> str | None:
    for path in (live_root / "storage" / "audio_shapes").glob("*.json"):
        if path.name.endswith(".librosa.json"):
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("spotify_uri") == uri:
                return path.stem
        except Exception:
            continue
    return None


def _isolate(live_root: Path, tmp: Path) -> None:
    from spectra import config as scfg
    audio = tmp / "audio_shapes"
    audio.mkdir(parents=True)
    triggers_live = json.loads(
        (live_root / "storage" / "spectra" / "triggers.json").read_text(encoding="utf-8"))
    triggers = {}
    for _, uri, _ in SONGS:
        stem = _stem_for(live_root, uri)
        if stem is None:
            raise SystemExit(f"no captured audio shape for {uri} under {live_root}")
        for suffix in (".json", ".librosa.json", ".npz"):
            src = live_root / "storage" / "audio_shapes" / f"{stem}{suffix}"
            if src.exists():
                shutil.copyfile(src, audio / f"{stem}{suffix}")
        triggers[uri] = triggers_live.get(uri, [])
    (tmp / "spectra").mkdir()
    (tmp / "spectra" / "triggers.json").write_text(json.dumps(triggers), encoding="utf-8")
    scfg.AUDIO_SHAPES_DIR = audio
    scfg.TRIGGERS_FILE = tmp / "spectra" / "triggers.json"
    scfg.DROP_SEQUENCES_FILE = tmp / "spectra" / "drop_sequences.json"
    scfg.ROOM_CONTROLS_FILE = tmp / "spectra" / "room_controls.json"
    scfg.FIRE_HISTORY_FILE = tmp / "spectra" / "fire_history.json"
    scfg.SHOW_LOG_FILE = tmp / "spectra" / "show_log.json"


def _check_port(problems: list[str]) -> None:
    from spectra.services import drop_detector
    print("## 1. The port (raw detector vs the plan's testbed)\n")
    for name, uri, _ in SONGS:
        analysis = drop_detector.analyse(uri)
        got = []
        for drop_ms, cand in drop_detector.raw_drops(analysis, drop_detector.SUGGESTED_SCORE):
            lull, charge, brk = drop_detector.place_sequence(analysis.prep, drop_ms)
            got.append((drop_ms, round(cand.score, 3), lull, charge, brk))
        ok = got == GOLDEN[name]
        print(f"- {name}: {len(got)} raw detections — {'identical' if ok else 'DIFFERENT'}")
        if not ok:
            problems.append(f"port differs from the testbed on {name}: {got} != {GOLDEN[name]}")
    print()


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-root", default="/home/javi/SpotFX")
    args = ap.parse_args()
    live_root = Path(args.live_root)
    tmp = Path(tempfile.mkdtemp(prefix="check_drop_detector_"))
    problems: list[str] = []
    try:
        _isolate(live_root, tmp)
        from spectra.services import (drop_detector, drop_scoring, drop_sequences,
                                      trigger_store)
        _check_port(problems)

        rows, edm = [], []
        print("## 2. The plan's four-song table (shipped code, guards on)\n")
        print("| Song | His drops | Found | Extra | Confident found | Confident extra "
              "| Median miss | Worst | Within 50 ms | Lull within 1 beat | Charge within 2 beats |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for name, uri, is_edm in SONGS:
            first = drop_sequences.ensure_detected(uri)
            second = drop_sequences.ensure_detected(uri)
            if first.get("status") != "detected" or second.get("status") != "fresh":
                problems.append(f"{name}: store did not detect then hold "
                                f"({first.get('status')}, {second.get('status')})")
            det = drop_detector.SongDetection.from_dict(drop_sequences.stored(uri)["detected"])
            marks = drop_sequences.his_marks(trigger_store.list_for_song(uri))
            r = drop_scoring.score_song(det, marks)
            rows.append(r)
            edm.append(is_edm)
            print(f"| {name} | {r['his_drops']} | {r['found']} of {r['his_drops']} | {r['extra']} "
                  f"| {r['confident_found']} of {r['his_drops']} | {r['confident_extra']} "
                  f"| {_fmt(r['median_abs_ms'])} ms | {_fmt(r['worst_abs_ms'])} ms "
                  f"| {r['within_50ms']} of {r['found']} "
                  f"| {r['lull_within_1_beat']} of {r['lull_compared']} "
                  f"| {r['charge_within_2_beats']} of {r['charge_compared']} |")
            if is_edm and r["confident_extra"]:
                problems.append(f"{name}: {r['confident_extra']} false confident drop(s) on an "
                                f"EDM song: {r['confident_extras']}")
        tot = drop_scoring.totals(rows)
        etot = drop_scoring.totals(rows, edm_only=edm)
        print(f"| **All four** | {tot['his_drops']} | **{tot['found']} of {tot['his_drops']}** "
              f"| {tot['extra']} | **{tot['confident_found']} of {tot['his_drops']}** "
              f"| {tot['confident_extra']} (EDM songs: **{etot['confident_extra']}**) "
              f"| {_fmt(tot['median_abs_ms'])} ms | {_fmt(tot['worst_abs_ms'])} ms "
              f"| {tot['within_50ms']} of {tot['found']} "
              f"| {tot['lull_within_1_beat']} of {tot['lull_compared']} "
              f"| {tot['charge_within_2_beats']} of {tot['charge_compared']} |")
        print()
        for (name, _, _), r in zip(SONGS, rows):
            print(f"- {name}: signed drop misses {r['drop_errors_ms']} ms; missed {r['missed']}; "
                  f"extras on his marks {r['extras_by_kind']}")
        print()
        if tot["his_drops"] != PLAN_HIS_DROPS:
            problems.append(f"his drops on the four songs: {tot['his_drops']}, "
                            f"the plan counted {PLAN_HIS_DROPS} — his marks have changed")
        if tot["found"] < PLAN_FOUND:
            problems.append(f"found {tot['found']} of {tot['his_drops']}, plan {PLAN_FOUND}")
        if tot["confident_found"] < PLAN_CONFIDENT_FOUND:
            problems.append(f"confident found {tot['confident_found']}, plan {PLAN_CONFIDENT_FOUND}")

        print("## 3. The merged view (his own triggers win)\n")
        for name, uri, _ in SONGS:
            v = drop_sequences.view(uri)
            print(f"- {name}: {v['counts']}")
            for s in v["sequences"]:
                if s["state"] != drop_sequences.STATE_MATCHES_YOURS and any(
                        m["kind"] == "drop" for m in s["matches"]):
                    problems.append(f"{name}: detection on his drop at {s['drop_ms']} "
                                    f"did not stand down")
        print()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: port identical; {PLAN_FOUND}+ of {PLAN_HIS_DROPS} found, "
          f"{PLAN_CONFIDENT_FOUND}+ confident with nothing false on the EDM songs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
