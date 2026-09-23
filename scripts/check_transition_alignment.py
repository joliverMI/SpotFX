#!/usr/bin/env python3
"""Transition-alignment acceptance measurement (2026-09-23,
data/transition-alignment-plan/report.md §5 task 1) — extends
scripts/check_midsong_beat_snap.py with the FRAME FIX
(spectra/services/midsong_generator.py::candidate_moments, +
analysis_reader.section_energy_at) on top of Phase 2's existing
beat-snap measurement.

READ-ONLY against the live checkout's storage (default /home/javi/SpotFX,
override with --live-root) — his real .librosa.json analysis, his real
.npz capture-offset sidecar, his real beat_this precompute cache, and his
real authored triggers for the four reference songs (Soy Peor / Contra /
Dopamine / El Apagón). NOTHING is written there — every read is COPIED
into a throwaway temp directory (tempfile.mkdtemp) and every store this
run touches (AUDIO_SHAPES_DIR, TESTBED_ANALYSIS_DIR, TRIGGERS_FILE,
ROOM_CONTROLS_FILE) is repointed at that copy before midsong_generator
ever runs against it — the same isolation shape
check_midsong_beat_snap.py already uses.

Three columns per song, matching the report's own table (section 1):

  Today        — the pre-fix baseline: capture_offset_ms treated as 0
                 (testbed_audio.capture_offset_ms_or_zero monkeypatched to
                 return 0 for the duration of this one run only), snap OFF.
  Frame fixed  — this fix alone: the real measured capture offset, snap
                 OFF (isolates the frame effect from Phase 2's separate
                 beat-snap feature, exactly as the report's own "Frame
                 fixed" column does).
  + Snap (live) — the real offset AND snap ON — today's actual shipped
                 default (RoomControlState.midsong_snap_to_beat=True).

Scored with the test bed's own matcher (testbed_metrics.match_marks)
against his REAL authored transition marks (fire_scene/fire_scene_update),
read separately from the live triggers.json and never copied into the
temp store — at ONE BEAT tolerance (60000 / that song's own tempo_bpm),
matching the report's own methodology (section 2: "the complaint is in
beats"). Flares are also reported (informational only — the acceptance
gate below is transitions-only, matching the report's own table 1).

El Apagón is reported but NOT weighted in the go/no-go read (report
section 5 task 1's own acceptance note, echoing the Admiral's word on
Phase 2's own check).

ACCEPTANCE (report §5 task 1): the four-song one-beat recall for "Frame
fixed" is at least 14/45/9/0% (Soy Peor/Contra/Dopamine/El Apagón), and no
song's "Frame fixed" recall is lower than its "Today" recall.

Run from repo root: .venv/bin/python scripts/check_transition_alignment.py
                     [--live-root /home/javi/SpotFX]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SONGS = [
    ("Soy Peor", "spotify:track:1JxhrUWZjuI8AOjDJ1JpMN", "Bad Bunny - Soy Peor"),
    ("Contra", "spotify:track:2zVg53xdC6RMpthWju6LRT", "Pixel Terror, Sara Skinner - Contra"),
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT", "Wooli, Tape B - Dopamine"),
    ("El Apagón", "spotify:track:0UvZcEfpzVyx47QsRbjyBz", "Bad Bunny - El Apagón"),
]

# The report's own "Frame fixed" column (section 1, one-beat recall, %),
# in the same song order as SONGS. This is the acceptance floor.
FRAME_FIXED_FLOOR_PCT = {"Soy Peor": 14.0, "Contra": 45.0, "Dopamine": 9.0, "El Apagón": 0.0}


def _copy_analysis(live_root: Path, tmp: Path, uri: str, stem: str) -> None:
    audio_dir = tmp / "audio_shapes"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".json", ".librosa.json", ".npz"):
        src = live_root / "storage" / "audio_shapes" / f"{stem}{suffix}"
        if src.exists():
            shutil.copyfile(src, audio_dir / f"{stem}{suffix}")

    bt_src = (live_root / "storage" / "spectra" / "testbed" / "analysis"
              / "beat_this" / f"{uri.replace(':', '_').replace('/', '_')}.json")
    if bt_src.exists():
        bt_dir = tmp / "spectra" / "testbed" / "analysis" / "beat_this"
        bt_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bt_src, bt_dir / bt_src.name)


def _real_reference_marks(live_root: Path, uri: str) -> tuple[list[int], list[int]]:
    """(transitions, flares) timestamps from his REAL authored triggers —
    read directly from the live triggers.json, read-only, never copied
    into the temp store this run drives generation against."""
    path = live_root / "storage" / "spectra" / "triggers.json"
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get(uri, [])
    transition_kinds = ("fire_scene", "fire_scene_update")
    flare_kinds = ("fire_response", "select_color_set")
    transitions, flares = [], []
    for row in rows:
        if row.get("source") != "authored":
            continue
        kind = (row.get("action") or {}).get("kind")
        ts = row.get("timestamp_ms")
        if kind in transition_kinds:
            transitions.append(ts)
        elif kind in flare_kinds:
            flares.append(ts)
    return transitions, flares


@contextmanager
def _forced_capture_offset_zero():
    """Monkeypatches testbed_audio.capture_offset_ms_or_zero to return 0
    for the duration of the block — reproduces the pre-frame-fix baseline
    ("Today") from the ACTUAL production candidate_moments code, rather
    than a second, hand-rolled copy of its old logic that could drift
    from what candidate_moments really did."""
    from spectra.services import testbed_audio
    original = testbed_audio.capture_offset_ms_or_zero
    testbed_audio.capture_offset_ms_or_zero = lambda uri: 0
    try:
        yield
    finally:
        testbed_audio.capture_offset_ms_or_zero = original


def _run_generation(tmp_root: Path, uri: str, *, snap: bool, label: str) -> list[int]:
    """Fresh, isolated trigger + room-controls store per call — returns the
    resulting GENERATED cue timestamps."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls, trigger_store
    from spectra.services import analysis_reader

    run_dir = tmp_root / label / uri.replace(":", "_")
    scfg.TRIGGERS_FILE = run_dir / "triggers.json"
    scfg.ROOM_CONTROLS_FILE = run_dir / "room_controls.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    room_controls.save_room_controls(
        room_controls.RoomControlState(midsong_snap_to_beat=snap))
    # section_energy_at's own per-URI capture-offset cache (analysis_reader
    # ._capture_offset_cache) must not leak the "Today" monkeypatch's
    # forced-0 answer into a later, real-offset run for the same URI.
    analysis_reader._capture_offset_cache.pop(uri, None)
    midsong_generator.generate_for_song(uri)
    return [t.timestamp_ms for t in trigger_store.list_for_song(uri)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-root", default="/home/javi/SpotFX")
    args = parser.parse_args()
    live_root = Path(args.live_root)
    if not (live_root / "storage").is_dir():
        print(f"no live checkout at {live_root} — nothing to measure "
              f"(pass --live-root)", file=sys.stderr)
        return 1

    from spectra import config as scfg
    from spectra.services import analysis_reader

    tmp = Path(tempfile.mkdtemp(prefix="spectra-transition-alignment-check-"))
    scfg.AUDIO_SHAPES_DIR = tmp / "audio_shapes"
    scfg.TESTBED_ANALYSIS_DIR = tmp / "spectra" / "testbed" / "analysis"

    from spectra.services import testbed_metrics

    header = (f"{'song':<10}{'ref':<12}{'tol(1 beat)':>12}  "
              f"{'today':>7}  {'frame fix':>9}  {'+snap':>7}")
    print(header)
    print("-" * len(header))

    floor_ok = True
    regression = False
    for name, uri, stem in SONGS:
        _copy_analysis(live_root, tmp, uri, stem)
        analysis_reader._shape_index.clear()
        analysis_reader._index_built = False
        analysis_reader._capture_offset_cache.clear()

        tempo_bpm = analysis_reader.tempo_bpm_for_uri(uri)
        tol_ms = (60000.0 / tempo_bpm) if tempo_bpm else 500.0

        transitions_ref, flares_ref = _real_reference_marks(live_root, uri)

        with _forced_capture_offset_zero():
            today = _run_generation(tmp, uri, snap=False, label="today")
        frame_fixed = _run_generation(tmp, uri, snap=False, label="frame_fixed")
        plus_snap = _run_generation(tmp, uri, snap=True, label="plus_snap")

        for ref_name, ref_marks in (("transitions", transitions_ref), ("flares", flares_ref)):
            if not ref_marks:
                print(f"{name:<10}{ref_name:<12}{tol_ms:>10.0f}ms  {'n/a':>7}  {'n/a':>9}  {'n/a':>7}")
                continue
            r_today = testbed_metrics.match_marks(ref_marks, today, tol_ms).recall
            r_frame = testbed_metrics.match_marks(ref_marks, frame_fixed, tol_ms).recall
            r_snap = testbed_metrics.match_marks(ref_marks, plus_snap, tol_ms).recall
            print(f"{name:<10}{ref_name:<12}{tol_ms:>10.0f}ms  "
                  f"{r_today*100:>6.0f}%  {r_frame*100:>8.0f}%  {r_snap*100:>6.0f}%")

            if ref_name == "transitions":
                if r_frame * 100.0 + 1e-6 < r_today * 100.0:
                    print(f"  REGRESSION: {name} frame-fixed recall "
                          f"({r_frame*100:.1f}%) is below today's "
                          f"({r_today*100:.1f}%)", file=sys.stderr)
                    regression = True
                floor = FRAME_FIXED_FLOOR_PCT.get(name)
                if floor is not None and r_frame * 100.0 + 1e-6 < floor:
                    print(f"  BELOW ACCEPTANCE: {name} frame-fixed recall "
                          f"({r_frame*100:.1f}%) is below the plan's floor "
                          f"({floor:.0f}%)", file=sys.stderr)
                    floor_ok = False

    print()
    print("El Apagón is reported above but NOT weighted in any go/no-go "
          "read of this table (the report's own note, echoing the "
          "Admiral's word on Phase 2's own check).")
    shutil.rmtree(tmp, ignore_errors=True)

    if regression or not floor_ok:
        return 1
    print("PASS: frame fix meets the report's acceptance floor on every "
          "song, with no song regressing below today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
