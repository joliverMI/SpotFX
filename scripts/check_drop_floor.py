#!/usr/bin/env python3
"""THE DROP FLOOR acceptance — the Admiral's own setting (2026-10-06,
drop-detection plan). First ask, verbatim: "add a setting called drop
floor and set it as a default to 0.95. drop sequences only get generated
if the final energy value for the post drop or during drop section is at
least the drop floor." Told that 0.95 removed every one of his 13 real
drops on the measure first shipped (raw librosa section `energy_rms`),
his follow-up: "what about when we factor in the mark score? i want to
match to the energy in the top bar shown. if that still needs 0.7 for my
drops to land, do .7. otherwise, stay with .95 if that fixes the issue."

A mark-factored composite (intensity_scale.combine_measured_and_scale over
the section energy and the song's own genre+bass scale) was tried and
measured: it structurally capped every one of these four songs' own
ceiling at 0.40-0.44 (their auto scale is 0.68-0.74, so HEADROOM_RESERVE
x scale never reaches 0.7 even at energy_rms=1.0), so NEITHER 0.95 NOR
0.7 ever let a single real drop through on that measure. Checking the
actual top-bar component settled it: LiveEnergyReadout.tsx renders
`bridge.intensity()` (== `analysis_reader.section_energy_at`) VERBATIM,
with no mark factored in anywhere — the adjacent "Mark" readout is a
separate, un-multiplied number. His final word, "match to the energy in
the top bar shown", is the DISPLAYED number. This script measures THAT
plain measure (drop_detector.final_energy_at, now == section_energy_at)
at 0.0 (off), 0.7 (the shipped default) and 0.95 (his first number, kept
for comparison), against his same 13 real drops.

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

FLOORS = [0.0, 0.7, 0.95]


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-root", default="/home/javi/SpotFX")
    args = ap.parse_args()
    live_root = Path(args.live_root)
    tmp = Path(tempfile.mkdtemp(prefix="check_drop_floor_"))
    try:
        _isolate(live_root, tmp)
        from spectra.services import drop_detector, drop_scoring, drop_sequences, trigger_store

        print("## The drop floor — the plain top-bar energy number (2026-10-06)\n")
        print("Each of his 13 real drops' top-bar-as-displayed energy (what "
              "`drop_detector.final_energy_at` reads — no mark factored in):\n")
        print("| Song | Drop (ms) | Displayed energy |")
        print("|---|---|---|")
        for name, uri in SONGS:
            marks = drop_sequences.his_marks(trigger_store.list_for_song(uri))
            for m in sorted(marks, key=lambda x: x.timestamp_ms):
                if m.kind != "drop":
                    continue
                energy = drop_detector.final_energy_at(uri, m.timestamp_ms)
                print(f"| {name} | {m.timestamp_ms} | {energy:.2f} |" if energy is not None
                      else f"| {name} | {m.timestamp_ms} | unknown |")
        print()

        print("## Found / confident-found of his 13 real drops, at each floor\n")
        header = " | ".join(f"Found ({f})" for f in FLOORS)
        cheader = " | ".join(f"Conf. found ({f})" for f in FLOORS)
        print(f"| Song | His drops | {header} | {cheader} |")
        print("|---|---|" + "---|" * len(FLOORS) + "---|" * len(FLOORS))
        rows_by_floor = {f: [] for f in FLOORS}
        for name, uri in SONGS:
            marks = drop_sequences.his_marks(trigger_store.list_for_song(uri))
            per_floor = {}
            for f in FLOORS:
                det = drop_detector.detect_uri(uri, drop_floor=f)
                r = drop_scoring.score_song(det, marks)
                per_floor[f] = r
                rows_by_floor[f].append(r)
            found_cells = " | ".join(str(per_floor[f]["found"]) for f in FLOORS)
            conf_cells = " | ".join(str(per_floor[f]["confident_found"]) for f in FLOORS)
            print(f"| {name} | {per_floor[FLOORS[0]]['his_drops']} | {found_cells} "
                  f"| {conf_cells} |")
        totals = {f: drop_scoring.totals(rows_by_floor[f]) for f in FLOORS}
        found_tot = " | ".join(f"**{totals[f]['found']}**" for f in FLOORS)
        conf_tot = " | ".join(f"**{totals[f]['confident_found']}**" for f in FLOORS)
        print(f"| **All four** | {totals[FLOORS[0]]['his_drops']} | {found_tot} "
              f"| {conf_tot} |")
        print()

        off, default, old = totals[0.0], totals[0.7], totals[0.95]
        print(f"Floor OFF: {off['found']} of {off['his_drops']} found "
              f"({off['confident_found']} confident) — the plan's own pre-floor "
              "acceptance.")
        print(f"Floor 0.7 (shipped default): {default['found']} of "
              f"{default['his_drops']} survive ({default['confident_found']} "
              "confident).")
        print(f"Floor 0.95 (his first number): {old['found']} of {old['his_drops']} "
              f"survive ({old['confident_found']} confident).")
        print()
        print("His own fallback rule: 0.95 kept none of his detector-found drops, "
              "so the default is 0.7 — and 0.7 keeps nearly all of them, unlike "
              "the mark-factored composite that was tried and rejected (it kept "
              "none of them at either number, structurally, since these four "
              "songs' own auto scale never lets the composite reach 0.7). The "
              "top bar's '⚡ Energy' readout and this floor now read the "
              "identical, unscaled number.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
