"""Acceptance measurement for THE SCENE-CHANGE PLANNER (2026-10-04,
data/scene-change-ranking-plan/report.md): how often a song's strongest
analysed transitions actually become scene changes.

Re-runs the plan's own validated simulator (evidence/simlib.py — the
dwell gate first-come-first-served from the song-start pick at 1 s, a hold
latched at each real fire from the dwell curve at render intensity), but
lets the BUILT planner (midsong_generator.plan_moments) choose the scene
changes, and plays them back with dwell.PLANNED_CUE_TOLERANCE_S. Ranks are
section-energy change over every candidate (placement duplicates included),
deciles exactly as the plan's final.py scored its "Recommended" row.

The plan's figures for the recommended design: top-10% -> 85%, top-3 -> 87%,
~2.95 scene changes/min (its simulator assumed a 0.86 factor; offline the
planner plans with the no-genre factor, so holds run a little longer).

READ-ONLY against his live checkout: storage/audio_shapes and the beat_this
cache are read in place; everything SPECTRA would write lands in a temp
copy of his spectra storage (SPECTRA_STORAGE_DIR, set before import).

    .venv/bin/python scripts/check_scene_change_ranking.py [--play-factor 0.86|own|0.5]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COPY = ("triggers.json", "room_controls.json", "scenes.json", "sequencer.json",
        "intensity_scale_marks.json", "intensity_scale_features.json")
START_MS = 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live-root", default="/home/javi/SpotFX")
    ap.add_argument("--play-factor", default="0.86",
                    help="the factor playback latches holds with: a number, or 'own'")
    ap.add_argument("--tolerance", type=float, default=None)
    args = ap.parse_args()
    live = Path(args.live_root) / "storage"
    if not (live / "spectra" / "triggers.json").exists():
        print(f"no live storage at {live}", file=sys.stderr)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="scene-change-ranking-"))
    for name in COPY:
        if (live / "spectra" / name).exists():
            shutil.copy2(live / "spectra" / name, tmp / name)
    os.environ["SPECTRA_STORAGE_DIR"] = str(tmp)
    sys.path.insert(0, str(REPO))
    from spectra import config as scfg
    scfg.AUDIO_SHAPES_DIR = live / "audio_shapes"
    scfg.TESTBED_ANALYSIS_DIR = live / "spectra" / "testbed" / "analysis"
    assert str(scfg.TRIGGERS_FILE).startswith(str(tmp))
    from spectra.services import (analysis_reader, dwell, intensity_scale,
                                  midsong_generator as mg, room_controls, selection_kernel,
                                  trigger_store)
    tol = dwell.PLANNED_CUE_TOLERANCE_S if args.tolerance is None else args.tolerance
    controls = room_controls.load_room_controls()
    curves = mg.planning_hold_curves()

    def hold(raw, factor):
        render = intensity_scale.combine_measured_and_scale(raw, factor)
        return max(selection_kernel.curve_eval(p, render) for p in curves)

    # The plan's own population: every analysed song carrying none of his
    # own triggers (whether or not it has played yet), longer than a minute.
    stored = trigger_store.load_raw()
    songs = sorted(u for u in analysis_reader.stem_index()
                   if not any(r.get("source", "authored") == "authored"
                              for r in stored.get(u, [])))
    dec = {d: [0, 0] for d in range(10)}
    top3 = [0, 0]
    per_min, actions_min, longest, closest = [], [], [], []
    planned = deferred = n = 0
    for uri in songs:
        with analysis_reader.memoized_reads():
            sections = analysis_reader.sections_for_uri(uri)
            if not sections:
                continue
            dur = max(int(s.get("end_ms", 0)) for s in sections)
            if dur <= 60_000:
                continue
            plan = mg.plan_moments(uri, **mg._planning_kwargs(controls), hold_curves=curves)
        everything = plan.kept + plan.unselected + plan.dropped
        if len(everything) < 3:
            continue
        n += 1
        factor = (mg.effective_intensity_scale_factor(uri) if args.play_factor == "own"
                  else float(args.play_factor))
        ordered = sorted(sections, key=lambda s: int(s.get("start_ms", 0)))
        t_last, h_last = START_MS, hold(float(ordered[0].get("energy_rms", 0.5)), factor)
        scenes = set()
        for c in sorted(plan.kept, key=lambda c: c.timestamp_ms):
            planned += 1
            if (c.timestamp_ms - t_last) / 1000.0 >= h_last - tol:
                scenes.add(c.generator_key)
                t_last, h_last = c.timestamp_ms, hold(c.intensity, factor)
            else:
                deferred += 1
        by_rank = sorted(sorted(everything, key=lambda c: int(c.generator_key.split(":")[1])),
                         key=lambda c: -c.strength)
        for pos, c in enumerate(by_rank):
            d = min(9, int(10 * pos / len(by_rank)))
            hit = c.generator_key in scenes
            dec[d][0] += hit
            dec[d][1] += 1
            if pos < 3:
                top3[0] += hit
                top3[1] += 1
        times = sorted(c.timestamp_ms for c in plan.kept if c.generator_key in scenes)
        per_min.append(len(times) / (dur / 60000))
        actions_min.append((len(plan.kept) + len(plan.unselected)) / (dur / 60000))
        gaps = [b - a for a, b in zip([START_MS, *times], [*times, dur])]
        longest.append(max(gaps) / 1000)
        if len(times) > 1:
            closest.append(min(b - a for a, b in zip(times, times[1:])) / 1000)
    curve = [round(100 * dec[d][0] / dec[d][1]) if dec[d][1] else None for d in range(10)]
    out = {
        "songs": n, "play_factor": args.play_factor, "tolerance_s": tol,
        "settings": {"total_actions_per_minute": controls.transitions_per_minute,
                     "window_beats": controls.transition_window_beats,
                     "scene_changes_per_minute": controls.scene_changes_per_minute},
        "top10_pct": curve[0], "top3_pct": round(100 * top3[0] / max(1, top3[1])),
        "decile_curve_pct": curve,
        "scene_changes_per_min": round(statistics.median(per_min), 2),
        "actions_per_min": round(statistics.median(actions_min), 2),
        "median_longest_gap_s": round(statistics.median(longest), 1),
        "median_closest_pair_s": round(statistics.median(closest), 1) if closest else None,
        "planned_changes": planned,
        "planned_deferred_pct": round(100 * deferred / max(1, planned), 2),
    }
    print(json.dumps(out, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if (curve[0] or 0) >= 75 else 1


if __name__ == "__main__":
    sys.exit(main())
