"""
SpotFX — Trigger scoring script.

Compares embedded-pipeline generated triggers against human-verified profiles.
Reports per-category weighted F1 scores.

Usage:
  python scripts/score_triggers.py --profile "EDM - High Energy"
  python scripts/score_triggers.py --profile "Trap/Reggaeton" --tolerance-beats 3
  python scripts/score_triggers.py --all
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass, field

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.training_profile_manager import TrainingProfile, TRAINING_PROFILES_FILE
from services.profile_manager import load_profile_by_uri
from services.embedded_trigger_service import suggest_triggers
from services.librosa_service import get_analysis_by_uri

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Default score weights per category ────────────────────────────────────────
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "drop":         3.0,
    "scene_change": 2.0,
    "structural":   1.5,
    "flare":        1.0,
    "flare_low":    0.8,
    "flare_mid":    1.0,
    "flare_high":   1.5,
    "song_start":   1.0,
    "song_end":     1.0,
}

# Category groups for sub-scores
SCENE_CATEGORIES = {"drop", "scene_change", "structural", "song_start", "song_end"}
FLARE_CATEGORIES = {"flare", "flare_low", "flare_mid", "flare_high"}


# ── Data classes ──────────────────────────────────────────────────────────────

import math

# Distance-weighted scoring:
#   0 - 1000ms (FULL_CREDIT_MS): 100% credit
#   1000 - 2000ms: exponential decay from 100% to ~0%
# DECAY_RANGE_MS controls how quickly it falls off beyond the full-credit zone.
# k is fitted so that credit at FULL_CREDIT_MS + DECAY_RANGE_MS is ~0.01.
FULL_CREDIT_MS = 1000
DECAY_RANGE_MS = 1000
_DECAY_K = math.log(100) / DECAY_RANGE_MS  # e^(-k * 1000) = 0.01

def _distance_credit(distance_ms: float) -> float:
    """Full credit within 1000ms, exponential decay to ~0 by 2000ms."""
    d = abs(distance_ms)
    if d <= FULL_CREDIT_MS:
        return 1.0
    overshoot = d - FULL_CREDIT_MS
    return math.exp(-_DECAY_K * overshoot)


@dataclass
class CategoryScore:
    tp: float = 0.0       # weighted true positives (sum of distance credits)
    fp: int = 0           # unmatched generated (integer count)
    fn: float = 0.0       # weighted false negatives (1 - credit for partial matches, + 1.0 for full misses)
    match_count: int = 0  # how many human triggers had any match (for reporting)
    human_count: int = 0  # total human triggers in this category
    gen_count: int = 0    # total generated triggers in this category

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


@dataclass
class SongScore:
    title: str = ""
    artist: str = ""
    uri: str = ""
    categories: dict[str, CategoryScore] = field(default_factory=dict)
    human_count: int = 0
    generated_count: int = 0

    def weighted_f1(self, weights: dict[str, float]) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        for cat, score in self.categories.items():
            w = weights.get(cat, 1.0)
            if score.tp + score.fp + score.fn > 0:
                weighted_sum += w * score.f1
                total_weight += w
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def group_f1(self, group_cats: set[str], weights: dict[str, float]) -> float:
        """Weighted F1 over a subset of categories (e.g. scene-only or flare-only)."""
        total_weight = 0.0
        weighted_sum = 0.0
        for cat, score in self.categories.items():
            if cat not in group_cats:
                continue
            w = weights.get(cat, 1.0)
            if score.tp + score.fp + score.fn > 0:
                weighted_sum += w * score.f1
                total_weight += w
        return weighted_sum / total_weight if total_weight > 0 else 0.0


# ── Role mapping ──────────────────────────────────────────────────────────────

def build_role_map(tp: TrainingProfile) -> dict[str, str]:
    """Build event_id → role mapping from a training profile's *_event_id fields."""
    role_map: dict[str, str] = {}

    mapping = {
        "song_start_event_id":  "song_start",
        "beat_start_event_id":  "structural",
        "song_end_event_id":    "song_end",
        "drop_event_id":        "drop",
        "lull_event_id":        "structural",
        "charge_event_id":      "structural",
        "quiet_event_id":       "scene_change",
        "scene_fill_event_id":  "scene_change",
        "flare_event_id":       "flare",
        "flare_low_event_id":   "flare_low",
        "flare_mid_event_id":   "flare_mid",
        "flare_high_event_id":  "flare_high",
    }

    for attr, role in mapping.items():
        eid = getattr(tp, attr, None)
        if eid:
            role_map[eid] = role

    # Also check event_roles dict if the user has defined it explicitly
    explicit = getattr(tp, "event_roles", None)
    if isinstance(explicit, dict):
        for role, eids in explicit.items():
            for eid in (eids if isinstance(eids, list) else [eids]):
                role_map[eid] = role

    return role_map


def categorize_trigger(trigger: dict, role_map: dict[str, str]) -> str:
    """Return the category/role for a trigger based on its event_id."""
    eid = trigger.get("event_id", "")
    return role_map.get(eid, "unknown")


# ── Matching ──────────────────────────────────────────────────────────────────

def match_triggers(
    human: list[dict],
    generated: list[dict],
    role_map: dict[str, str],
    tolerance_ms: int,
) -> dict[str, CategoryScore]:
    """
    Match generated triggers against human triggers by category.
    tolerance_ms is the full-credit window; matching extends to
    tolerance_ms + DECAY_RANGE_MS for partial credit.

    For each human trigger, find the nearest generated trigger of the same category
    within tolerance_ms. Each generated trigger can only match one human trigger.

    Returns per-category CategoryScore.
    """
    # Group by category
    human_by_cat: dict[str, list[int]] = {}
    gen_by_cat: dict[str, list[int]] = {}

    for t in human:
        cat = categorize_trigger(t, role_map)
        human_by_cat.setdefault(cat, []).append(t.get("timestamp_ms", 0))

    for t in generated:
        cat = categorize_trigger(t, role_map)
        gen_by_cat.setdefault(cat, []).append(t.get("timestamp_ms", 0))

    # All categories seen
    all_cats = set(human_by_cat.keys()) | set(gen_by_cat.keys())
    all_cats.discard("unknown")

    scores: dict[str, CategoryScore] = {}
    for cat in sorted(all_cats):
        h_times = sorted(human_by_cat.get(cat, []))
        g_times = sorted(gen_by_cat.get(cat, []))

        cs = CategoryScore(human_count=len(h_times), gen_count=len(g_times))
        matched_gen: set[int] = set()
        max_match_ms = tolerance_ms + DECAY_RANGE_MS  # full credit + decay zone

        for h_ms in h_times:
            best_idx = -1
            best_dist = max_match_ms + 1
            for gi, g_ms in enumerate(g_times):
                if gi in matched_gen:
                    continue
                dist = abs(h_ms - g_ms)
                if dist <= max_match_ms and dist < best_dist:
                    best_dist = dist
                    best_idx = gi
            if best_idx >= 0:
                credit = _distance_credit(best_dist)
                cs.tp += credit
                cs.match_count += 1
                matched_gen.add(best_idx)
            else:
                cs.fn += 1.0  # full miss only for unmatched triggers

        cs.fp = len(g_times) - len(matched_gen)
        scores[cat] = cs

    return scores


# ── Score one song ────────────────────────────────────────────────────────────

def score_song(
    uri: str,
    tp: TrainingProfile,
    role_map: dict[str, str],
    tolerance_ms: int,
    _cached: dict | None = None,
) -> SongScore | None:
    """Generate triggers for a song and score against human-verified profile.

    _cached: optional dict with pre-loaded data:
      {"profile": SongProfile, "analysis": LibrosaAnalysis}
    Skips disk I/O when provided (used by the tuning loop).
    """
    # Load human-verified profile
    if _cached:
        profile = _cached.get("profile")
        la = _cached.get("analysis")
    else:
        profile = load_profile_by_uri(uri)
        la = get_analysis_by_uri(uri)

    if not profile or not profile.triggers:
        logger.warning("No verified profile/triggers for %s — skipping", uri)
        return None
    if not la or not la.beats:
        logger.warning("No librosa analysis for %s — skipping", uri)
        return None

    # Build available event IDs from role_map
    available_event_ids = set(role_map.keys())

    # Generate triggers using embedded pipeline
    generated = suggest_triggers(
        target_uri=uri,
        all_training_uris=[],
        available_event_ids=available_event_ids,
        training_profile=tp,
        _cached_analysis=la,
    )

    # Build human trigger dicts
    human = [
        {"timestamp_ms": t.timestamp_ms, "event_id": t.event_id}
        for t in profile.triggers if t.enabled
    ]

    # Match and score
    categories = match_triggers(human, generated, role_map, tolerance_ms)

    return SongScore(
        title=profile.title or "",
        artist=profile.artist or "",
        uri=uri,
        categories=categories,
        human_count=len(human),
        generated_count=len(generated),
    )


# ── Report ────────────────────────────────────────────────────────────────────

def print_song_score(song: SongScore, weights: dict[str, float]) -> None:
    print(f'\n  Song: "{song.title}" by {song.artist}')
    print(f"    Human triggers: {song.human_count}  |  Generated: {song.generated_count}")
    for cat, cs in sorted(song.categories.items(), key=lambda x: -weights.get(x[0], 1.0)):
        w = weights.get(cat, 1.0)
        print(
            f"    {cat:20s} (x{w:.1f}):  P={cs.precision:.2f}  R={cs.recall:.2f}  "
            f"F1={cs.f1:.2f}  ({cs.match_count}/{cs.human_count} matched, {cs.fp} extra, "
            f"{cs.human_count - cs.match_count} missed, credit={cs.tp:.1f})"
        )
    scene_f1 = song.group_f1(SCENE_CATEGORIES, weights)
    flare_f1 = song.group_f1(FLARE_CATEGORIES, weights)
    wf1 = song.weighted_f1(weights)
    print(f"    {'SCENE F1':20s}       {scene_f1:.3f}")
    print(f"    {'FLARE F1':20s}       {flare_f1:.3f}")
    print(f"    {'OVERALL F1':20s}       {wf1:.3f}")


def print_aggregate(songs: list[SongScore], weights: dict[str, float]) -> None:
    if not songs:
        print("\nNo songs scored.")
        return

    # Aggregate per-category
    all_cats: dict[str, CategoryScore] = {}
    for song in songs:
        for cat, cs in song.categories.items():
            agg = all_cats.setdefault(cat, CategoryScore())
            agg.tp += cs.tp
            agg.fp += cs.fp
            agg.fn += cs.fn
            agg.match_count += cs.match_count
            agg.human_count += cs.human_count
            agg.gen_count += cs.gen_count

    avg_wf1 = sum(s.weighted_f1(weights) for s in songs) / len(songs)

    print(f"\n{'='*60}")
    print(f"  AGGREGATE ({len(songs)} songs)")
    print(f"{'='*60}")
    for cat, cs in sorted(all_cats.items(), key=lambda x: -weights.get(x[0], 1.0)):
        w = weights.get(cat, 1.0)
        print(
            f"    {cat:20s} (x{w:.1f}):  P={cs.precision:.2f}  R={cs.recall:.2f}  "
            f"F1={cs.f1:.2f}  ({cs.match_count}/{cs.human_count} matched, {cs.fp} extra, "
            f"{cs.human_count - cs.match_count} missed, credit={cs.tp:.1f})"
        )
    avg_scene = sum(s.group_f1(SCENE_CATEGORIES, weights) for s in songs) / len(songs)
    avg_flare = sum(s.group_f1(FLARE_CATEGORIES, weights) for s in songs) / len(songs)
    print(f"    {'AVG SCENE F1':20s}       {avg_scene:.3f}")
    print(f"    {'AVG FLARE F1':20s}       {avg_flare:.3f}")
    print(f"    {'AVG OVERALL F1':20s}       {avg_wf1:.3f}")


# ── Main ──────────────────────────────────────────────────────────────────────

def load_training_profiles() -> dict[str, TrainingProfile]:
    """Load all training profiles from storage."""
    if not TRAINING_PROFILES_FILE.exists():
        return {}
    data = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8"))
    return {v["name"]: TrainingProfile(**v) for v in data.values()}


def run_scoring(profile_name: str, tolerance_beats: int = 2, verbose: bool = True) -> float:
    """Score all training songs for a profile. Returns aggregate weighted F1."""
    profiles = load_training_profiles()
    if profile_name not in profiles:
        print(f"Profile '{profile_name}' not found. Available: {list(profiles.keys())}")
        return 0.0

    tp = profiles[profile_name]
    role_map = build_role_map(tp)
    weights = getattr(tp, "score_weights", None) or DEFAULT_SCORE_WEIGHTS

    # Compute tolerance in ms from beats
    la_sample = None
    for uri in tp.training_uris + tp.embedded_only_uris:
        la_sample = get_analysis_by_uri(uri)
        if la_sample and la_sample.tempo_bpm:
            break
    beat_ms = (60_000 / la_sample.tempo_bpm) if (la_sample and la_sample.tempo_bpm) else 500
    tolerance_ms = int(tolerance_beats * beat_ms)

    # Gather all training URIs (both training and embedded_only have verified profiles)
    all_uris = list(set(tp.training_uris + tp.embedded_only_uris))

    if verbose:
        print(f"\nScoring profile: {profile_name}")
        print(f"  Songs: {len(all_uris)}  |  Tolerance: {tolerance_beats} beats ({tolerance_ms}ms)")
        print(f"  Role map: {len(role_map)} event IDs mapped")

    songs: list[SongScore] = []
    for uri in all_uris:
        result = score_song(uri, tp, role_map, tolerance_ms)
        if result:
            songs.append(result)
            if verbose:
                print_song_score(result, weights)

    if verbose:
        print_aggregate(songs, weights)

    if songs:
        return sum(s.weighted_f1(weights) for s in songs) / len(songs)
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="Score embedded trigger generation against verified profiles")
    parser.add_argument("--profile", type=str, help="Training profile name to score")
    parser.add_argument("--all", action="store_true", help="Score all training profiles")
    parser.add_argument("--tolerance-beats", type=int, default=2, help="Matching tolerance in beats (default: 2)")
    parser.add_argument("--quiet", action="store_true", help="Only show aggregate scores")
    args = parser.parse_args()

    if not args.profile and not args.all:
        parser.print_help()
        return

    if args.all:
        profiles = load_training_profiles()
        for name in profiles:
            run_scoring(name, args.tolerance_beats, verbose=not args.quiet)
            print()
    else:
        run_scoring(args.profile, args.tolerance_beats, verbose=not args.quiet)


if __name__ == "__main__":
    main()
