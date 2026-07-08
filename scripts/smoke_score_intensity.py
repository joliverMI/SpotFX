"""
Smoke test for triggerless-training upgrades: per-trigger intensity,
onset snapping, the flare_scene tier, snare/burst components, and
intensity-weighted match scoring.

USAGE
  .venv/bin/python scripts/smoke_score_intensity.py

Runs entirely on synthetic data — no live backend, no disk fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.librosa_analysis import (            # noqa: E402
    LibrosaAnalysis, LibrosaBeat, LibrosaOnset, LibrosaSection,
)
from services.training_profile_manager import TrainingProfile  # noqa: E402
from services import embedded_trigger_service as ets           # noqa: E402
from scripts.score_triggers import match_triggers, INTENSITY_ALPHA  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ── Synthetic song: 64 beats @120bpm (500ms grid), 3 sections ─────────────────

BEAT_MS = 500
N_BEATS = 64
URI = "spotify:track:smoketest_intensity"


def make_analysis() -> LibrosaAnalysis:
    beats = []
    for i in range(N_BEATS):
        if i < 4:             # silent intro (beat_start fires at bass entry, beat 4)
            rms, bass = 0.08, 0.0
        elif i < 16:          # steady verse; bass peak at beat 10 → charge
            rms, bass = 0.50, (0.75 if i == 10 else 0.45)
        elif i < 20:          # quiet valley (gap → lull/drop)
            rms, bass = 0.02, 0.0
        elif i < 48:          # loud drop section
            rms, bass = 0.90, 0.90
        else:                 # outro
            rms, bass = 0.30, 0.20
        beats.append(LibrosaBeat(
            ms=i * BEAT_MS,
            is_downbeat=(i % 4 == 0),
            rms_total=rms, rms_bass=bass,
            onset_score=0.7 if 20 <= i < 48 else 0.3,
            bass_onset_score=0.8 if 20 <= i < 48 else 0.2,
            snare_onset_score=0.8 if 20 <= i < 48 and i % 2 == 0 else 0.0,
            harmonic_score=0.5 if i % 8 == 0 else 0.1,
        ))
    # General onsets 60ms after every beat; bass onsets 120ms after loud beats
    onsets = [LibrosaOnset(ms=i * BEAT_MS + 60, strength=0.5) for i in range(N_BEATS)]
    bass_onsets = [LibrosaOnset(ms=i * BEAT_MS + 120, strength=0.9) for i in range(20, 48)]
    snare_onsets = [LibrosaOnset(ms=i * BEAT_MS + 80, strength=0.8) for i in range(20, 48, 2)]
    sections = [
        LibrosaSection(start_ms=0, end_ms=8000, label="intro", energy_rms=0.30),
        LibrosaSection(start_ms=8000, end_ms=24000, label="drop", energy_rms=0.90),
        LibrosaSection(start_ms=24000, end_ms=32000, label="outro", energy_rms=0.45),
    ]
    return LibrosaAnalysis(
        spotify_uri=URI, title="Smoke", artist="Test", analyzed_at="now",
        tempo_bpm=120.0, beats=beats, onsets=onsets, bass_onsets=bass_onsets,
        snare_onsets=snare_onsets, sections=sections, harmonic_changes=[],
    )


ROLE_IDS = {
    "song_start_event_id": "ev_start", "beat_start_event_id": "ev_beat",
    "song_end_event_id": "ev_end", "drop_event_id": "ev_drop",
    "lull_event_id": "ev_lull", "charge_event_id": "ev_charge",
    "quiet_event_id": "ev_quiet", "scene_fill_event_id": "ev_scene",
    "flare_low_event_id": "ev_fl_low", "flare_mid_event_id": "ev_fl_mid",
    "flare_high_event_id": "ev_fl_high",
}


def make_profile(**overrides) -> TrainingProfile:
    return TrainingProfile(name="smoke", **{**ROLE_IDS, **overrides})


def run(tp: TrainingProfile, la: LibrosaAnalysis) -> list[dict]:
    available = {v for v in ROLE_IDS.values()}
    if tp.flare_scene_event_id:
        available.add(tp.flare_scene_event_id)
    return ets.suggest_triggers(
        target_uri=URI, all_training_uris=[], available_event_ids=available,
        training_profile=tp, _cached_analysis=la,
    )


def main() -> int:
    la = make_analysis()
    beat_grid = {b.ms for b in la.beats}
    onset_grid = {o.ms for o in la.onsets} | {o.ms for o in la.bass_onsets}

    # ── A. Intensity emission (snapping off) ─────────────────────────────────
    print("A. Intensity emission")
    tp_a = make_profile(intensity_drop_boost=0.05, intensity_quiet_cap=0.35)
    trig_a = run(tp_a, la)
    check("triggers generated", len(trig_a) > 0, f"got {len(trig_a)}")
    check("all have intensity in [0,1]",
          all(0.0 <= t.get("intensity", -1) <= 1.0 for t in trig_a),
          str([t.get("intensity") for t in trig_a]))
    check("all on beat grid with snapping off",
          all(t["timestamp_ms"] in beat_grid for t in trig_a),
          str([t["timestamp_ms"] for t in trig_a if t["timestamp_ms"] not in beat_grid]))

    drops = [t for t in trig_a if t["event_id"] == "ev_drop"]
    check("a drop fired", len(drops) > 0)
    for d in drops:
        base = ets._section_energy_at(la.sections, d["timestamp_ms"])
        check("drop intensity = section energy + boost",
              abs(d["intensity"] - min(1.0, base + 0.05)) < 1e-6,
              f"ts={d['timestamp_ms']} int={d['intensity']} sec={base}")
    quiets = [t for t in trig_a if t["event_id"] in ("ev_quiet", "ev_lull")]
    for q in quiets:
        check("quiet/lull intensity <= cap", q["intensity"] <= 0.35 + 1e-6,
              f"ts={q['timestamp_ms']} int={q['intensity']}")

    # ── B. Onset snapping ─────────────────────────────────────────────────────
    print("B. Onset snapping")
    tp_b = make_profile(onset_snap_radius_ms=250)
    trig_b = run(tp_b, la)
    snapped_roles = {"ev_drop", "ev_charge", "ev_scene",
                     "ev_fl_low", "ev_fl_mid", "ev_fl_high"}
    unsnapped_roles = {"ev_start", "ev_beat", "ev_end", "ev_quiet", "ev_lull"}
    for t in trig_b:
        if t["event_id"] in snapped_roles:
            check(f"{t['event_id']} snapped to an onset",
                  t["timestamp_ms"] in onset_grid,
                  f"ts={t['timestamp_ms']}")
        elif t["event_id"] in unsnapped_roles:
            check(f"{t['event_id']} stays on beat grid",
                  t["timestamp_ms"] in beat_grid, f"ts={t['timestamp_ms']}")
    # Min spacing survives snapping (density filter: 4 beats = 2000ms, bookends exempt)
    ts_sorted = sorted(t["timestamp_ms"] for t in trig_b)
    gaps_ok = all(b - a >= 500 for a, b in zip(ts_sorted, ts_sorted[1:]))
    check("no duplicate/overlapping timestamps after snap", gaps_ok, str(ts_sorted))

    # ── C. flare_scene tier ───────────────────────────────────────────────────
    print("C. flare_scene tier")
    tp_c = make_profile(flare_scene_event_id="ev_fl_scene", flare_scene_thresh=0.05,
                        flare_scene_min_spacing=8)
    trig_c = run(tp_c, la)
    check("scene-tier flares fire with low thresh",
          any(t["event_id"] == "ev_fl_scene" for t in trig_c))
    check("no scene-tier flares in default profile",
          all(t["event_id"] != "ev_fl_scene" for t in trig_a))
    tp_c2 = make_profile(flare_scene_event_id="ev_fl_scene", flare_scene_thresh=5.0)
    trig_c2 = run(tp_c2, la)
    baseline = [(t["timestamp_ms"], t["event_id"]) for t in run(make_profile(), la)]
    check("unreachable scene thresh == no-tier output",
          [(t["timestamp_ms"], t["event_id"]) for t in trig_c2] == baseline)

    # ── D. Snare/burst components ─────────────────────────────────────────────
    print("D. Snare/burst components")
    tp_d = make_profile(flare_snare_weight=0.2, flare_burst_weight=0.2)
    trig_d = run(tp_d, la)
    check("generator runs with snare/burst weights", len(trig_d) > 0)
    check("burst cache populated", URI in ets._BURST_CACHE)

    # ── E. Intensity-weighted matching ────────────────────────────────────────
    print("E. Intensity-weighted matching")
    role_map = {"e": "flare"}
    scores = match_triggers(
        [{"timestamp_ms": 1000, "event_id": "e", "intensity": 0.9}],
        [{"timestamp_ms": 1000, "event_id": "e", "intensity": 0.5}],
        role_map, tolerance_ms=1000)
    expected = 1.0 - INTENSITY_ALPHA * 0.4
    check("Δintensity=0.4 → credit scaled",
          abs(scores["flare"].tp - expected) < 1e-6, f"tp={scores['flare'].tp}")
    check("iMAE tracked", abs((scores["flare"].intensity_mae or 0) - 0.4) < 1e-6)
    scores2 = match_triggers(
        [{"timestamp_ms": 1000, "event_id": "e"}],
        [{"timestamp_ms": 1000, "event_id": "e"}],
        role_map, tolerance_ms=1000)
    check("missing intensity → full credit",
          abs(scores2["flare"].tp - 1.0) < 1e-6, f"tp={scores2['flare'].tp}")
    check("missing intensity → no iMAE", scores2["flare"].intensity_mae is None)

    print()
    if FAILURES:
        print(f"SMOKE FAILED — {len(FAILURES)} failing check(s): {FAILURES}")
        return 1
    print("SMOKE PASSED — all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
