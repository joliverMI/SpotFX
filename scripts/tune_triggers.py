"""
SpotFX — Trigger parameter tuning script.

Two-tier grid search that optimizes embedded pipeline parameters against
human-verified profiles, measured by weighted category F1.

Pre-caches all song profiles and librosa analysis to avoid disk I/O in the
inner loop (~100x faster than naive approach).

Usage:
  python scripts/tune_triggers.py --profile "Trap/Reggaeton"
  python scripts/tune_triggers.py --profile "Rock" --tier flare
  python scripts/tune_triggers.py --profile "EDM - Dance/High Energy" --tier scene
"""
from __future__ import annotations
import argparse
import itertools
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.training_profile_manager import TrainingProfile, TRAINING_PROFILES_FILE
from services.profile_manager import load_profile_by_uri
from services.librosa_service import get_analysis_by_uri
from services.embedded_trigger_service import suggest_triggers
from scripts.score_triggers import (
    load_training_profiles, build_role_map, match_triggers,
    SongScore, DEFAULT_SCORE_WEIGHTS,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ── Parameter grids ───────────────────────────────────────────────────────────

SCENE_GRID = {
    "gap_energy_thresh":            [0.10, 0.20],
    "gap_after_thresh":             [0.3, 0.4],
    "gap_min_beats":                [2, 4],
    "charge_min_score":             [0.3, 0.4],
    "quiet_thresh":                 [0.4, 0.5],
    "quiet_min_beats":              [16, 24],
    "scene_energy_delta":           [0.08, 0.12, 0.18],
    "scene_smooth_window":          [4, 8, 12],
    "scene_min_spacing_beats":      [16, 24],
    "scene_mfcc_weight":            [0.0, 0.2, 0.4, 0.6],
}

FLARE_GRID = {
    "flare_bass_hit_weight":        [0.1, 0.2, 0.3],
    "flare_bass_onset_weight":      [0.05, 0.15, 0.25],
    "flare_onset_weight":           [0.1, 0.2, 0.3],
    "flare_harmonic_weight":        [0.05, 0.15, 0.25],
    "flare_energy_uptick_weight":   [0.05, 0.15, 0.25],
    "flare_energy_weight":          [0.0, 0.1, 0.2],
    "flare_dip_weight":             [0.0, 0.1, 0.2],
    "flare_shape_thresh":           [0.10, 0.20, 0.30],
    "flare_shape_min_spacing":      [3, 4, 6],
}


def _grid_combos(grid: dict) -> list[dict]:
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _apply_overrides(tp: TrainingProfile, overrides: dict) -> TrainingProfile:
    data = tp.model_dump()
    data.update(overrides)
    return TrainingProfile(**data)


# ── Pre-cached song data ─────────────────────────────────────────────────────

def preload_songs(uris: list[str]) -> list[dict]:
    """Load all song profiles + librosa analysis once. Returns list of usable song dicts."""
    songs = []
    for uri in uris:
        profile = load_profile_by_uri(uri)
        if not profile or not profile.triggers:
            continue
        la = get_analysis_by_uri(uri)
        if not la or not la.beats:
            continue
        human = [
            {"timestamp_ms": t.timestamp_ms, "event_id": t.event_id}
            for t in profile.triggers if t.enabled
        ]
        songs.append({
            "uri": uri,
            "title": profile.title or "",
            "artist": profile.artist or "",
            "analysis": la,
            "human": human,
        })
    return songs


def score_fast(
    tp: TrainingProfile,
    songs: list[dict],
    role_map: dict[str, str],
    tolerance_ms: int,
    weights: dict[str, float],
) -> float:
    """Score all pre-loaded songs. No disk I/O. Returns avg weighted F1."""
    available = set(role_map.keys())
    f1_sum = 0.0
    for song in songs:
        generated = suggest_triggers(
            target_uri=song["uri"],
            all_training_uris=[],
            available_event_ids=available,
            training_profile=tp,
            _cached_analysis=song["analysis"],
        )
        categories = match_triggers(song["human"], generated, role_map, tolerance_ms)
        ss = SongScore(categories=categories)
        f1_sum += ss.weighted_f1(weights)
    return f1_sum / len(songs) if songs else 0.0


# ── Main tuning loop ─────────────────────────────────────────────────────────

def tune(profile_name: str, tier: str = "both", tolerance_beats: int = 2):
    profiles = load_training_profiles()
    if profile_name not in profiles:
        print(f"Profile '{profile_name}' not found. Available: {list(profiles.keys())}")
        return

    tp = profiles[profile_name]
    role_map = build_role_map(tp)
    weights = getattr(tp, "score_weights", None) or DEFAULT_SCORE_WEIGHTS
    all_uris = list(set(tp.training_uris + tp.embedded_only_uris))

    # Pre-load all songs
    print(f"\nTuning profile: {profile_name}")
    print(f"  Loading songs...", end=" ", flush=True)
    songs = preload_songs(all_uris)
    print(f"{len(songs)}/{len(all_uris)} usable")

    if not songs:
        print("  No usable songs. Aborting.")
        return

    # Compute tolerance_ms from first song's tempo
    beat_ms = (60_000 / songs[0]["analysis"].tempo_bpm) if songs[0]["analysis"].tempo_bpm else 500
    tolerance_ms = int(tolerance_beats * beat_ms)
    print(f"  Tolerance: {tolerance_beats} beats ({tolerance_ms}ms)")

    # Baseline
    baseline_f1 = score_fast(tp, songs, role_map, tolerance_ms, weights)
    print(f"  Baseline weighted F1: {baseline_f1:.3f}")

    best_scene_overrides: dict = {}
    best_flare_overrides: dict = {}

    # ── Tier 1: Scene structure ────────────────────────────────────────────
    if tier in ("scene", "both"):
        combos = _grid_combos(SCENE_GRID)
        print(f"\n=== Tier 1: Scene Structure ({len(combos)} combinations) ===")
        t0 = time.monotonic()

        best_f1 = baseline_f1
        best_params: dict = {}
        for i, overrides in enumerate(combos):
            tp_trial = _apply_overrides(tp, overrides)
            f1 = score_fast(tp_trial, songs, role_map, tolerance_ms, weights)
            if f1 > best_f1:
                best_f1 = f1
                best_params = overrides.copy()
            if (i + 1) % 500 == 0:
                elapsed = time.monotonic() - t0
                rate = (i + 1) / elapsed
                remaining = (len(combos) - i - 1) / rate
                print(f"  {i+1}/{len(combos)} — best F1={best_f1:.3f} — ~{remaining:.0f}s remaining")

        elapsed = time.monotonic() - t0
        if best_params:
            print(f"\n  Best scene F1: {best_f1:.3f} (was {baseline_f1:.3f}, +{(best_f1 - baseline_f1)*100:.1f}%)")
            print(f"  Time: {elapsed:.1f}s")
            for k, v in sorted(best_params.items()):
                print(f"    {k}: {v}")
            best_scene_overrides = best_params
        else:
            print(f"\n  No improvement found. Default params are best ({baseline_f1:.3f})")
            print(f"  Time: {elapsed:.1f}s")

    # Apply scene improvements for flare tuning
    tp_with_scene = _apply_overrides(tp, best_scene_overrides) if best_scene_overrides else tp
    scene_f1 = score_fast(tp_with_scene, songs, role_map, tolerance_ms, weights)

    # ── Tier 2: Flare tuning ──────────────────────────────────────────────
    if tier in ("flare", "both"):
        combos = _grid_combos(FLARE_GRID)
        print(f"\n=== Tier 2: Flare Tuning ({len(combos)} combinations) ===")
        t0 = time.monotonic()

        best_f1 = scene_f1
        best_params = {}
        for i, overrides in enumerate(combos):
            all_overrides = {**best_scene_overrides, **overrides}
            tp_trial = _apply_overrides(tp, all_overrides)
            f1 = score_fast(tp_trial, songs, role_map, tolerance_ms, weights)
            if f1 > best_f1:
                best_f1 = f1
                best_params = overrides.copy()
            if (i + 1) % 200 == 0:
                elapsed = time.monotonic() - t0
                rate = (i + 1) / elapsed
                remaining = (len(combos) - i - 1) / rate
                print(f"  {i+1}/{len(combos)} — best F1={best_f1:.3f} — ~{remaining:.0f}s remaining")

        elapsed = time.monotonic() - t0
        if best_params:
            print(f"\n  Best flare F1: {best_f1:.3f} (was {scene_f1:.3f}, +{(best_f1 - scene_f1)*100:.1f}%)")
            print(f"  Time: {elapsed:.1f}s")
            for k, v in sorted(best_params.items()):
                print(f"    {k}: {v}")
            best_flare_overrides = best_params
        else:
            print(f"\n  No improvement found. Default flare params are best ({scene_f1:.3f})")
            print(f"  Time: {elapsed:.1f}s")

    # ── Summary ───────────────────────────────────────────────────────────
    all_best = {**best_scene_overrides, **best_flare_overrides}
    if all_best:
        final_tp = _apply_overrides(tp, all_best)
        final_f1 = score_fast(final_tp, songs, role_map, tolerance_ms, weights)
        improvement = (final_f1 - baseline_f1) / max(baseline_f1, 0.001) * 100
        print(f"\n{'='*60}")
        print(f"  SUMMARY: {profile_name}")
        print(f"  Baseline: {baseline_f1:.3f} -> Tuned: {final_f1:.3f} ({improvement:+.1f}%)")
        print(f"  Best parameters to apply:")
        for k, v in sorted(all_best.items()):
            print(f"    {k}: {v}")
        print(f"{'='*60}")
    else:
        print(f"\n  No improvements found. Current parameters are optimal for this training set.")


def main():
    parser = argparse.ArgumentParser(description="Tune embedded trigger parameters via grid search")
    parser.add_argument("--profile", type=str, required=True, help="Training profile name")
    parser.add_argument("--tier", choices=["scene", "flare", "both"], default="both",
                        help="Which tier to tune (default: both)")
    parser.add_argument("--tolerance-beats", type=int, default=2, help="Matching tolerance in beats")
    args = parser.parse_args()

    tune(args.profile, args.tier, args.tolerance_beats)


if __name__ == "__main__":
    main()
