#!/usr/bin/env python3
"""THE DROP FLOOR acceptance — the Admiral's own setting (2026-10-06,
verbatim: "add a setting called drop floor and set it as a default to
0.95. drop sequences only get generated if the final energy value for
the post drop or during drop section is at least the drop floor. so
quiet songs or sections don't accidentally get drops").

Re-scores the SAME four songs scripts/check_drop_detector.py holds
(Contra, Dopamine, Pop Off, 100 Millones — the plan's own acceptance set)
at the shipped default (drop_floor=0.95) against detection with the floor
OFF (drop_floor=0.0), and reports how many of his 13 drops survive the
floor. This is NOT a pass/fail gate on the floor's effect — the Admiral
asked for 0.95 and gets it regardless of how many of his real drops that
number removes; it is a measurement, printed for the PR body.

READ-ONLY against the live checkout's storage (default /home/javi/SpotFX,
override with --live-root) — the same isolation shape as
scripts/check_drop_detector.py: every file is copied into a throwaway
temp directory first, nothing there is ever written.

Run from repo root: .venv/bin/python scripts/check_drop_floor.py
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
    ("Contra", "spotify:track:2zVg53xdC6RMpthWju6LRT"),
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT"),
    ("Pop Off", "spotify:track:4PolqZLqReEqc3yURJtzc4"),
    ("100 Millones", "spotify:track:4Ixc50wY5pbUvNEogTQ2wL"),
]


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
    for _, uri in SONGS:
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


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-root", default="/home/javi/SpotFX")
    args = ap.parse_args()
    live_root = Path(args.live_root)
    tmp = Path(tempfile.mkdtemp(prefix="check_drop_floor_"))
    try:
        _isolate(live_root, tmp)
        from spectra.services import (drop_detector, drop_scoring, drop_sequences,
                                      room_controls, trigger_store)

        print("## The drop floor, at the shipped default (0.95) vs off (0.0)\n")
        print("| Song | His drops | Found (floor off) | Found (floor 0.95) "
              "| Confident found (floor off) | Confident found (floor 0.95) |")
        print("|---|---|---|---|---|---|")
        rows_off, rows_on = [], []
        for name, uri in SONGS:
            marks = drop_sequences.his_marks(trigger_store.list_for_song(uri))
            det_off = drop_detector.detect_uri(uri, drop_floor=0.0)
            det_on = drop_detector.detect_uri(uri, drop_floor=room_controls.RoomControlState().drop_floor)
            r_off = drop_scoring.score_song(det_off, marks)
            r_on = drop_scoring.score_song(det_on, marks)
            rows_off.append(r_off)
            rows_on.append(r_on)
            print(f"| {name} | {r_off['his_drops']} | {r_off['found']} | {r_on['found']} "
                  f"| {r_off['confident_found']} | {r_on['confident_found']} |")
        tot_off = drop_scoring.totals(rows_off)
        tot_on = drop_scoring.totals(rows_on)
        print(f"| **All four** | {tot_off['his_drops']} | **{tot_off['found']}** "
              f"| **{tot_on['found']}** | **{tot_off['confident_found']}** "
              f"| **{tot_on['confident_found']}** |")
        print()
        print(f"At the floor OFF, {tot_off['found']} of {tot_off['his_drops']} of his real "
              f"drops are found ({tot_off['confident_found']} confident) — the plan's own "
              "acceptance (scripts/check_drop_detector.py).")
        print(f"At the shipped default (0.95), {tot_on['found']} of {tot_on['his_drops']} "
              f"survive ({tot_on['confident_found']} confident).")
        if tot_on["found"] == 0:
            print()
            print("THE DEFAULT (0.95) REMOVES EVERY ONE OF HIS 13 REAL DROPS ON THESE FOUR "
                  "SONGS. The stored librosa `energy_rms` field is max-normalized PER SONG "
                  "(AGENTS.md's own note: median 0.33 library-wide, raw, no floor "
                  "subtraction) — 0.95 means 'one of this song's few loudest sections,' and "
                  "the section a drop actually lands in (the bar right after the break, "
                  "before the chorus/drop section properly gets going) typically reads "
                  "0.5-0.9 even on real EDM drops. This is the Admiral's own number, asked "
                  "for verbatim and shipped as the default regardless.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
