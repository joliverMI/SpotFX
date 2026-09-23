#!/usr/bin/env python3
"""Phase 2 acceptance measurement (2026-09-22, spectra/services/
beat_snap.py) — the Admiral's own primary metric (data/spotfx-music-
analysis-plan/report.md's ADMIRAL CLARIFICATION): how well GENERATED cues
land on his marks, before vs after beat-snapping.

READ-ONLY against the live checkout's storage (default
/home/javi/SpotFX, override with --live-root) — his real .librosa.json
analysis, his real beat_this precompute cache, and his real authored
triggers for the four reference songs (Soy Peor / Contra / Dopamine /
El Apagón). NOTHING is written there. Every read is COPIED into a
throwaway temp directory (tempfile.mkdtemp) and every store this run
touches — AUDIO_SHAPES_DIR, TESTBED_ANALYSIS_DIR, TRIGGERS_FILE,
ROOM_CONTROLS_FILE — is repointed at that copy before anything runs
midsong_generator against it, so this script can never touch his live
triggers.json, storage/audio_shapes, or storage/spectra — matching the
"measure offline on copies" instruction and the same isolation shape
scripts/check_triggers.py already uses.

For each song: runs midsong_generator.generate_for_song ONCE with
snapping OFF (the pre-Phase-2 baseline) and ONCE with snapping ON, each
against its own fresh empty temp trigger store, then scores the
resulting GENERATED cue timestamps against his REAL authored marks (read
separately, read-only, from the live triggers.json — never copied into
the temp store, so they can never leak into midsong_generator's own
existing-trigger comparison) with the test bed's own matcher
(testbed_metrics.match_marks) at 150ms and 500ms, against both
transitions and flares — exactly data/music-analysis-octave-scout/
report.md's own methodology.

El Apagón is reported but explicitly NOT weighted in any verdict (his own
word, "don't put too much weight on the el apagon flares").

Run from repo root: .venv/bin/python scripts/check_midsong_beat_snap.py
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
    ("Soy Peor", "spotify:track:1JxhrUWZjuI8AOjDJ1JpMN", "Bad Bunny - Soy Peor"),
    ("Contra", "spotify:track:2zVg53xdC6RMpthWju6LRT", "Pixel Terror, Sara Skinner - Contra"),
    ("Dopamine", "spotify:track:7vFKcXQ39f74XNrZmXADIT", "Wooli, Tape B - Dopamine"),
    ("El Apagón", "spotify:track:0UvZcEfpzVyx47QsRbjyBz", "Bad Bunny - El Apagón"),
]
TOLERANCES_MS = (150.0, 500.0)


def _copy_analysis(live_root: Path, tmp: Path, uri: str, stem: str) -> None:
    audio_dir = tmp / "audio_shapes"
    audio_dir.mkdir(parents=True, exist_ok=True)
    src_json = live_root / "storage" / "audio_shapes" / f"{stem}.json"
    src_librosa = live_root / "storage" / "audio_shapes" / f"{stem}.librosa.json"
    if src_json.exists():
        shutil.copyfile(src_json, audio_dir / f"{stem}.json")
    if src_librosa.exists():
        shutil.copyfile(src_librosa, audio_dir / f"{stem}.librosa.json")

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


def _run_generation(tmp_root: Path, uri: str, *, snap: bool) -> list[int]:
    """Fresh, isolated trigger + room-controls store per call — returns the
    resulting GENERATED cue timestamps."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls, trigger_store

    run_dir = tmp_root / ("snap_on" if snap else "snap_off") / uri.replace(":", "_")
    scfg.TRIGGERS_FILE = run_dir / "triggers.json"
    scfg.ROOM_CONTROLS_FILE = run_dir / "room_controls.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    room_controls.save_room_controls(
        room_controls.RoomControlState(midsong_snap_to_beat=snap))
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

    tmp = Path(tempfile.mkdtemp(prefix="spectra-beat-snap-check-"))
    scfg.AUDIO_SHAPES_DIR = tmp / "audio_shapes"
    scfg.TESTBED_ANALYSIS_DIR = tmp / "spectra" / "testbed" / "analysis"

    from spectra.services import testbed_metrics

    header = f"{'song':<10}{'ref':<7}{'tol':>6}  {'F1 before':>10}  {'F1 after':>10}  {'delta':>7}"
    print(header)
    print("-" * len(header))
    rows = []
    for name, uri, stem in SONGS:
        _copy_analysis(live_root, tmp, uri, stem)
        analysis_reader._shape_index.clear()
        analysis_reader._index_built = False
        transitions_ref, flares_ref = _real_reference_marks(live_root, uri)

        before = _run_generation(tmp, uri, snap=False)
        after = _run_generation(tmp, uri, snap=True)

        for ref_name, ref_marks in (("transitions", transitions_ref), ("flares", flares_ref)):
            for tol in TOLERANCES_MS:
                f1_before = testbed_metrics.match_marks(ref_marks, before, tol).f1 if ref_marks else None
                f1_after = testbed_metrics.match_marks(ref_marks, after, tol).f1 if ref_marks else None
                delta = (f1_after - f1_before) if (f1_before is not None and f1_after is not None) else None
                rows.append((name, ref_name, tol, f1_before, f1_after, delta))
                b = f"{f1_before:.3f}" if f1_before is not None else "  n/a"
                a = f"{f1_after:.3f}" if f1_after is not None else "  n/a"
                d = f"{delta:+.3f}" if delta is not None else "    n/a"
                print(f"{name:<10}{ref_name:<7}{tol:>5.0f}ms  {b:>10}  {a:>10}  {d:>7}")

    print()
    print("El Apagón is reported above but NOT weighted in any go/no-go "
          "read of this table (the Admiral's own word).")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
