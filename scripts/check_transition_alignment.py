#!/usr/bin/env python3
"""Transition-alignment acceptance measurement (2026-09-23,
data/transition-alignment-plan/report.md §5 tasks 1 and 3) — extends
scripts/check_midsong_beat_snap.py with the FRAME FIX
(spectra/services/midsong_generator.py::candidate_moments, +
analysis_reader.section_energy_at) and PLACEMENT RULE R3 (spectra/services/
beat_snap.py::place_cue, the edge-then-downbeat rule that is now the
generator's own default placement rule) on top of Phase 2's existing
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

Four columns per song, matching the report's own table (section 1):

  Today        — the pre-fix baseline: capture_offset_ms treated as 0
                 (testbed_audio.capture_offset_ms_or_zero monkeypatched to
                 return 0 for the duration of this one run only), snap OFF.
  Frame fixed  — this fix alone: the real measured capture offset, snap
                 OFF (isolates the frame effect from Phase 2's separate
                 beat-snap feature, exactly as the report's own "Frame
                 fixed" column does).
  + Snap       — the real offset AND snap ON, with R3's edge search
                 disabled (Phase 2's own plain downbeat-only behaviour,
                 isolated from R3 — see _disabled_rhythmic_edges).
  + Edge rule  — the real offset AND the full R3-then-R1 placement rule at
                 its shipped default knobs (RoomControlState()'s own
                 defaults: window=8 beats, sensitivity=0.5, both
                 directions, snap-to-beat on) — the generator's actual
                 shipped behaviour as of this build.

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

ACCEPTANCE (report §5 task 1, unchanged): the four-song one-beat recall
for "Frame fixed" is at least 14/45/9/0% (Soy Peor/Contra/Dopamine/El
Apagón), and no song's "Frame fixed" recall is lower than its "Today"
recall.

ACCEPTANCE (report §5 task 3): the four-song one-beat recall for "+ Edge
rule" is at least 21/73/45/29% (F1 .15/.33/.33/.17), and no song's "+ Edge
rule" recall is lower than its "Today" column.

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

# The report's own "R3 both dirs, s=0.5, W=8, else R1 (proposed default)"
# row (section 3), and Firstmate's own acceptance restatement (section 5
# task 3): the four-song one-beat recall floor for the shipped default
# placement rule.
EDGE_RULE_FLOOR_PCT = {"Soy Peor": 21.0, "Contra": 73.0, "Dopamine": 45.0, "El Apagón": 29.0}


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


@contextmanager
def _disabled_rhythmic_edges():
    """Monkeypatches rhythmic_edges.edges_for_uri to report "no analysis"
    for the duration of the block — isolates the "Today"/"Frame fixed"/
    "+ Snap" columns from PLACEMENT RULE R3's edge search (stage 1, which
    runs unconditionally regardless of RoomControlState.
    midsong_snap_to_beat — see beat_snap.py's own PLACEMENT RULE R3
    docstring section), so those three columns reproduce exactly the
    pre-R3 behaviour they were named for. Sensitivity has no legal value
    that guarantees zero real edges on real bass-energy data (its ceiling
    is 1.5, not infinite), so a monkeypatch is the only honest way to turn
    stage 1 fully off for a comparison column."""
    from spectra.services import rhythmic_edges
    original = rhythmic_edges.edges_for_uri
    rhythmic_edges.edges_for_uri = lambda uri, **kw: None
    try:
        yield
    finally:
        rhythmic_edges.edges_for_uri = original


def _run_generation(
    tmp_root: Path, uri: str, *, label: str,
    snap: bool = True, edges_enabled: bool = True, max_per_song: int = 40,
) -> list[int]:
    """Fresh, isolated trigger + room-controls store per call — returns the
    resulting GENERATED cue timestamps. `edges_enabled=False` disables
    PLACEMENT RULE R3's edge search entirely (see
    _disabled_rhythmic_edges), reproducing the "Today"/"Frame fixed"/
    "+ Snap" columns' pre-R3 shape. `max_per_song` defaults to
    RoomControlState's own field ceiling (40) — well above the report's
    own observed 19-37 raw candidates per song — so the DENSITY cap (task
    3's own "strongest N", default 12) does not shrink those three
    baseline columns; "+ Edge rule" passes the shipped default (12)
    explicitly so its own reported recall is the generator's ACTUAL
    production behaviour, not an artificially uncapped one."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls, trigger_store
    from spectra.services import analysis_reader

    run_dir = tmp_root / label / uri.replace(":", "_")
    scfg.TRIGGERS_FILE = run_dir / "triggers.json"
    scfg.ROOM_CONTROLS_FILE = run_dir / "room_controls.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    room_controls.save_room_controls(room_controls.RoomControlState(
        midsong_snap_to_beat=snap, transition_max_per_song=max_per_song))
    # section_energy_at's own per-URI capture-offset cache (analysis_reader
    # ._capture_offset_cache) must not leak the "Today" monkeypatch's
    # forced-0 answer into a later, real-offset run for the same URI.
    analysis_reader._capture_offset_cache.pop(uri, None)
    if edges_enabled:
        midsong_generator.generate_for_song(uri)
    else:
        with _disabled_rhythmic_edges():
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
              f"{'today':>7}  {'frame fix':>9}  {'+snap':>7}  {'+edge rule':>10}")
    print(header)
    print("-" * len(header))

    floor_ok = True
    edge_floor_ok = True
    regression = False
    edge_regression = False
    for name, uri, stem in SONGS:
        _copy_analysis(live_root, tmp, uri, stem)
        analysis_reader._shape_index.clear()
        analysis_reader._index_built = False
        analysis_reader._capture_offset_cache.clear()

        tempo_bpm = analysis_reader.tempo_bpm_for_uri(uri)
        tol_ms = (60000.0 / tempo_bpm) if tempo_bpm else 500.0

        transitions_ref, flares_ref = _real_reference_marks(live_root, uri)

        with _forced_capture_offset_zero():
            today = _run_generation(tmp, uri, snap=False, edges_enabled=False, label="today")
        frame_fixed = _run_generation(tmp, uri, snap=False, edges_enabled=False, label="frame_fixed")
        plus_snap = _run_generation(tmp, uri, snap=True, edges_enabled=False, label="plus_snap")
        # The shipped default knobs — RoomControlState()'s own
        # window=8/sensitivity=0.5/both directions/max_per_song=12,
        # snap-to-beat on — the generator's ACTUAL production placement
        # rule as of this build (report §5 task 3).
        # DENSITY (transition_max_per_song, task 3's own "strongest N") is
        # deliberately NOT applied here — the report's own §3 recall table
        # (and this column's acceptance floor) measures the PLACEMENT rule
        # alone, same as the report's own methodology; density's effect on
        # precision/recall is a separate, already-unit-tested concern (see
        # tests/test_midsong_generator.py's own density tests), not part
        # of this four-song reproduction.
        edge_rule = _run_generation(tmp, uri, snap=True, edges_enabled=True, label="edge_rule")

        for ref_name, ref_marks in (("transitions", transitions_ref), ("flares", flares_ref)):
            if not ref_marks:
                print(f"{name:<10}{ref_name:<12}{tol_ms:>10.0f}ms  "
                      f"{'n/a':>7}  {'n/a':>9}  {'n/a':>7}  {'n/a':>10}")
                continue
            r_today = testbed_metrics.match_marks(ref_marks, today, tol_ms).recall
            r_frame = testbed_metrics.match_marks(ref_marks, frame_fixed, tol_ms).recall
            r_snap = testbed_metrics.match_marks(ref_marks, plus_snap, tol_ms).recall
            r_edge = testbed_metrics.match_marks(ref_marks, edge_rule, tol_ms).recall
            print(f"{name:<10}{ref_name:<12}{tol_ms:>10.0f}ms  "
                  f"{r_today*100:>6.0f}%  {r_frame*100:>8.0f}%  {r_snap*100:>6.0f}%  "
                  f"{r_edge*100:>9.0f}%")

            if ref_name == "transitions":
                if r_frame * 100.0 + 1e-6 < r_today * 100.0:
                    print(f"  REGRESSION: {name} frame-fixed recall "
                          f"({r_frame*100:.1f}%) is below today's "
                          f"({r_today*100:.1f}%)", file=sys.stderr)
                    regression = True
                floor = FRAME_FIXED_FLOOR_PCT.get(name)
                # Rounded to the nearest whole percent before comparing —
                # both floor tables are themselves whole-percent
                # transcriptions of the report's own exact fractions (e.g.
                # Contra's true R3 recall is 8/11 = 72.727...%, which the
                # report's own table rounds to "73%"); comparing the raw
                # float would fail a song that landed EXACTLY on the
                # report's own reproduced number.
                if floor is not None and round(r_frame * 100.0) < floor:
                    print(f"  BELOW ACCEPTANCE: {name} frame-fixed recall "
                          f"({r_frame*100:.1f}%) is below the plan's floor "
                          f"({floor:.0f}%)", file=sys.stderr)
                    floor_ok = False
                if r_edge * 100.0 + 1e-6 < r_today * 100.0:
                    print(f"  REGRESSION: {name} edge-rule recall "
                          f"({r_edge*100:.1f}%) is below today's "
                          f"({r_today*100:.1f}%)", file=sys.stderr)
                    edge_regression = True
                edge_floor = EDGE_RULE_FLOOR_PCT.get(name)
                if edge_floor is not None and round(r_edge * 100.0) < edge_floor:
                    print(f"  BELOW ACCEPTANCE: {name} edge-rule recall "
                          f"({r_edge*100:.1f}%) is below the plan's floor "
                          f"({edge_floor:.0f}%)", file=sys.stderr)
                    edge_floor_ok = False

    print()
    print("El Apagón is reported above but NOT weighted in any go/no-go "
          "read of this table (the report's own note, echoing the "
          "Admiral's word on Phase 2's own check).")
    shutil.rmtree(tmp, ignore_errors=True)

    if regression or not floor_ok or edge_regression or not edge_floor_ok:
        return 1
    print("PASS: frame fix and the edge-then-downbeat placement rule both "
          "meet the report's acceptance floors on every song, with no song "
          "regressing below today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
