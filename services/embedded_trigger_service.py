"""
SpotFX — Embedded structural trigger suggestion engine.

Eight-stage pipeline:
  0. Song start    — fixed event at ms=0
  1. Beat start    — first bass entry (rms_bass rises from near-zero)
  2. Song end      — fade-out detection (bookend; placed early)
  3. Gap detection — finds quiet valleys → Lull (gap start) + Bass Drop (gap end+1)
  4. Charge        — peak energy/onset beat before each lull
  5. Quiet section — extended low-energy passages with gradual entry
  6. Standard fill — energy uptick → harmonic → downbeat (fill-until-satisfied)
  7. Flare fill    — energy-scaled, harmonic-aligned high-energy events

All detection thresholds are per-profile (TrainingProfile hidden tuning params).
KNN functions are retained for the Claude-path but not called in suggest_triggers.
"""
from __future__ import annotations
import logging
from collections import Counter
from typing import Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from services.training_profile_manager import TrainingProfile

logger = logging.getLogger(__name__)

# ── Tuning constants (module defaults, overridden per-profile) ────────────────
K = 5                      # KNN neighbours
MIN_CONFIDENCE = 0.4       # fraction of K agreeing on the same event
MAX_DIST = 1.2             # max normalised euclidean distance to nearest neighbour
MIN_GAP_MS = 1000          # minimum ms between two accepted suggestions (default)
MATCH_WINDOW_MS = 500      # max ms from trigger to its nearest beat (training)

# ── Structural detection ──────────────────────────────────────────────────────
# Defaults used only for flare stage and learn_structural_patterns.
# All per-stage thresholds now live in TrainingProfile hidden tuning fields.
FLARE_HARMONIC_THRESH = 0.3   # beat harmonic_score must exceed this for flare placement
STRUCTURAL_CONSISTENCY = 0.5  # fraction of training songs that must show a pattern

# ── Confidence boost caps ─────────────────────────────────────────────────────
SCORE_BOOST_MAX = 1.5         # maximum multiplier applied to any confidence boost

_FEAT_PER_BEAT = 5    # features per single beat
_CONTEXT_BEATS = 4   # beats before and after to include in the window
_WINDOW_SIZE   = 2 * _CONTEXT_BEATS + 1   # = 9
_FEAT_DIMS     = _FEAT_PER_BEAT * _WINDOW_SIZE  # = 45


# ── Feature extraction ────────────────────────────────────────────────────────

def _single_beat_vec(beat) -> np.ndarray:
    """5-dim feature vector for one beat."""
    return np.array([
        beat.rms_total,
        beat.rms_bass,
        beat.onset_score,
        beat.bass_onset_score,
        beat.harmonic_score,
    ], dtype=float)


def _beat_vec(beats: list, idx: int) -> np.ndarray:
    """
    45-dim context window: 4 beats before + current + 4 beats after, each 5-dim.
    Missing neighbours (at song boundaries) are zero-padded.
    """
    parts = []
    for offset in range(-_CONTEXT_BEATS, _CONTEXT_BEATS + 1):
        i = idx + offset
        if 0 <= i < len(beats):
            parts.append(_single_beat_vec(beats[i]))
        else:
            parts.append(np.zeros(_FEAT_PER_BEAT, dtype=float))
    return np.concatenate(parts)  # shape (45,)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nearest_beat(beats, ms: int):
    """Return the beat closest to ms."""
    return min(beats, key=lambda b: abs(b.ms - ms))


def _covered(ms: int, placed: list[dict], gap_ms: int) -> bool:
    return any(abs(ms - p["timestamp_ms"]) < gap_ms for p in placed)


def _knn_event(vec: np.ndarray, X_norm: np.ndarray, y_train: list[str],
               scaler: np.ndarray, k: int, available: set[str],
               restrict: set[str] | None = None) -> tuple[str | None, float, float]:
    """
    Run KNN for a single normalised feature vector.
    Returns (event_id, confidence, nn_dist) or (None, 0, inf).
    restrict: if set, only consider training samples whose event_id is in this set.
    """
    if X_norm is None or len(X_norm) == 0:
        return None, 0.0, float("inf")

    v = (vec / scaler).reshape(1, _FEAT_DIMS)
    dists = np.linalg.norm(X_norm - v, axis=1)

    if restrict:
        mask = np.array([y_train[i] in restrict for i in range(len(y_train))])
        if mask.sum() == 0:
            return None, 0.0, float("inf")
        filtered_dists = np.where(mask, dists, np.inf)
        actual_k = min(k, int(mask.sum()))
        knn_idx = np.argsort(filtered_dists)[:actual_k]
    else:
        actual_k = min(k, len(X_norm))
        knn_idx = np.argsort(dists)[:actual_k]

    nn_dist = float(dists[knn_idx[0]])

    # Distance-weighted voting: closer matches have higher influence
    eps = 1e-9
    weights: dict[str, float] = {}
    for i in knn_idx:
        eid = y_train[i]
        if eid not in available:
            continue
        weights[eid] = weights.get(eid, 0.0) + 1.0 / (float(dists[i]) + eps)
    if not weights:
        return None, 0.0, nn_dist

    total_w = sum(weights.values())
    event_id = max(weights, key=weights.get)
    confidence = weights[event_id] / total_w
    return event_id, confidence, nn_dist


# ── Training ──────────────────────────────────────────────────────────────────

def build_training_data(
    all_training_uris: list[str],
    exclude_uri: str | None = None,
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """
    Build KNN feature matrix from verified training songs.

    Per-song z-score normalisation is applied before pooling so that each
    training song contributes equally regardless of its overall energy level.
    exclude_uri: skip this URI's rows (used to prevent self-match when the
    target song is also in the training set).

    Returns:
        X      — shape (n_samples, _FEAT_DIMS), z-scored then max-scaled
        y      — event_id strings, len = n_samples
        scaler — shape (_FEAT_DIMS,) column maxes for normalisation
    """
    from services.librosa_service import get_analysis_by_uri
    from services.profile_manager import load_profile_by_uri

    # Collect raw vectors per song before pooling
    per_song: list[tuple[np.ndarray, list[str]]] = []  # (rows_array, labels)

    for uri in all_training_uris:
        if uri == exclude_uri:
            continue
        profile = load_profile_by_uri(uri)
        if not profile or not profile.verified or not profile.triggers:
            continue
        la = get_analysis_by_uri(uri)
        if not la or not la.beats:
            continue
        off = la.librosa_offset_ms

        beats = la.beats
        song_rows: list[np.ndarray] = []
        song_labels: list[str] = []
        for trigger in profile.triggers:
            tms = trigger.timestamp_ms
            nearest_idx = min(range(len(beats)), key=lambda i: abs(beats[i].ms + off - tms))
            if abs(beats[nearest_idx].ms + off - tms) > MATCH_WINDOW_MS:
                continue
            song_rows.append(_beat_vec(beats, nearest_idx))
            song_labels.append(trigger.event_id)

        if song_rows:
            per_song.append((np.array(song_rows), song_labels))

    if not per_song:
        return np.empty((0, _FEAT_DIMS)), [], np.ones(_FEAT_DIMS)

    # Per-song z-score: equalises contribution across songs of different energy levels
    _Z_STD_FLOOR = 0.1  # prevents noise amplification on near-constant features
    pooled_X: list[np.ndarray] = []
    pooled_y: list[str] = []
    for rows, labels in per_song:
        mean = rows.mean(axis=0)
        std  = np.maximum(rows.std(axis=0), _Z_STD_FLOOR)
        pooled_X.append((rows - mean) / std)
        pooled_y.extend(labels)

    X = np.vstack(pooled_X)
    scaler = np.maximum(X.max(axis=0), 1e-9)
    return X, pooled_y, scaler


def learn_structural_patterns(all_training_uris: list[str]) -> dict:
    """
    Learn which mark types consistently have triggers placed at them.

    Returns:
        {mark_type: {"event_id": str, "consistency": float}}
        Only mark_types where consistency >= STRUCTURAL_CONSISTENCY are included.
    """
    from services.librosa_service import get_analysis_by_uri
    from services.profile_manager import load_profile_by_uri
    from services.audio_analyzer import load_audio_shape_meta

    # mark_type → list of (event_id | None) — one entry per training song that has that mark
    per_mark: dict[str, list[str | None]] = {}
    MARK_TYPES = {"bass_drop", "charging", "quiet"}

    for uri in all_training_uris:
        profile = load_profile_by_uri(uri)
        if not profile or not profile.verified:
            continue
        meta = load_audio_shape_meta(uri)
        if not meta or not meta.music_marks:
            continue
        la = get_analysis_by_uri(uri)
        if not la or not la.beats:
            continue
        off = la.librosa_offset_ms

        for mark in meta.music_marks:
            if mark.mark_type not in MARK_TYPES:
                continue
            if mark.mark_type not in per_mark:
                per_mark[mark.mark_type] = []
            # Find nearest trigger within MATCH_WINDOW_MS
            tms = mark.timestamp_ms
            nearest_trigger = min(
                profile.triggers,
                key=lambda t: abs(t.timestamp_ms - tms),
                default=None,
            )
            if nearest_trigger and abs(nearest_trigger.timestamp_ms - tms) <= MATCH_WINDOW_MS:
                per_mark[mark.mark_type].append(nearest_trigger.event_id)
            else:
                per_mark[mark.mark_type].append(None)

    result: dict = {}
    for mark_type, entries in per_mark.items():
        total = len(entries)
        matched = [e for e in entries if e is not None]
        consistency = len(matched) / total if total > 0 else 0.0
        if consistency < STRUCTURAL_CONSISTENCY or not matched:
            continue
        top_event_id, _ = Counter(matched).most_common(1)[0]
        result[mark_type] = {"event_id": top_event_id, "consistency": consistency}

    return result


# ── Stage detectors ───────────────────────────────────────────────────────────

def _detect_beat_start(beats, tp, off: int = 0) -> int | None:
    """
    Return index of the first beat where bass energy clearly enters.
    rms_bass must have been near-zero in the preceding window and rise notably
    in the following window. Fires only once — earliest qualifying beat.

    Special case: if the first librosa beat starts more than 4 seconds into the
    song (i.e. librosa didn't detect any beats during a long intro), return beat 0
    so we still place a trigger at the musical start.
    """
    if not beats:
        return None

    # Long intro: librosa beats start late → use the first beat as the entry point
    if beats[0].ms + off > 4000:
        return 0

    lookback   = getattr(tp, "beat_start_lookback_beats",   4)
    lookahead  = getattr(tp, "beat_start_lookahead_beats",   4)
    near_zero  = getattr(tp, "beat_start_near_zero_thresh", 0.05)
    factor     = getattr(tp, "beat_start_factor",            3.0)
    abs_thresh = getattr(tp, "beat_start_abs_thresh",        0.15)

    n = len(beats)
    for i in range(1, n):
        past   = beats[max(0, i - lookback):i]
        future = beats[i:min(n, i + lookahead)]
        if not past or not future:
            continue
        past_avg   = sum(b.rms_bass for b in past)   / len(past)
        future_avg = sum(b.rms_bass for b in future) / len(future)
        if (past_avg < near_zero
                and future_avg > factor * max(past_avg, 0.001)
                and future_avg > abs_thresh):
            return i

    # Fallback: song opens with immediate bass — return the first beat with
    # meaningful bass energy (no quiet intro to contrast against)
    for i, b in enumerate(beats):
        if b.rms_bass > abs_thresh:
            return i
    return None


def _detect_song_end(beats, tp) -> int | None:
    """
    Return the index of the last beat where energy was still present before
    the final sustained fade — the song-end trigger position.
    Walks backwards from the last beat; returns the latest beat whose rms_total
    is above the threshold AND all following sustain_beats are below it.
    """
    if not beats:
        return None
    threshold = getattr(tp, "song_end_fade_thresh",   0.20)
    sustain   = getattr(tp, "song_end_sustain_beats", 8)
    n = len(beats)
    for i in range(n - 1, -1, -1):
        if beats[i].rms_total > threshold:
            tail = beats[i + 1 : i + 1 + sustain]
            if not tail or all(b.rms_total < threshold for b in tail):
                return i
    return n - 1


def _detect_gaps(beats, tp) -> list[tuple[int, int, float]]:
    """
    Find structural gaps: quiet valleys (2–20 beats) bounded by energy on both sides.
    Returns list of (gap_start_idx, gap_end_idx, score).
      gap_start = first quiet beat  → Lull trigger position
      gap_end+1 = re-entry beat     → Bass Drop trigger position
    Score reflects energy contrast and sustain across the gap.
    """
    energy_thresh  = getattr(tp, "gap_energy_thresh",         0.15)
    min_beats      = getattr(tp, "gap_min_beats",              2)
    max_beats      = getattr(tp, "gap_max_beats",              20)
    before_thresh  = getattr(tp, "gap_before_thresh",         0.35)
    before_window  = getattr(tp, "gap_before_window",          4)
    after_thresh   = getattr(tp, "gap_after_thresh",           0.45)
    after_window   = getattr(tp, "gap_after_window",           4)
    bass_gate      = getattr(tp, "gap_bass_onset_gate",        True)
    gate_window    = getattr(tp, "gap_bass_onset_gate_window", 4)
    gate_thresh    = getattr(tp, "gap_bass_onset_gate_thresh", 0.20)

    n = len(beats)

    # Find contiguous runs of gap-candidate beats
    raw_gaps: list[tuple[int, int]] = []
    in_gap = False
    gap_start = 0
    for i, beat in enumerate(beats):
        is_gap = beat.rms_bass < energy_thresh
        if is_gap and not in_gap:
            in_gap = True
            gap_start = i
        elif not is_gap and in_gap:
            in_gap = False
            raw_gaps.append((gap_start, i - 1))
    if in_gap:
        raw_gaps.append((gap_start, n - 1))

    # Filter, check context, score
    results: list[tuple[int, int, float]] = []
    for gs, ge in raw_gaps:
        gap_len = ge - gs + 1
        if not (min_beats <= gap_len <= max_beats):
            continue

        pre_beats = beats[max(0, gs - before_window) : gs]
        if not pre_beats:
            continue
        pre_avg = sum(b.rms_bass for b in pre_beats) / len(pre_beats)
        if pre_avg < before_thresh:
            continue

        post_beats = beats[ge + 1 : min(n, ge + 1 + after_window)]
        if not post_beats:
            continue
        post_avg = sum(b.rms_bass for b in post_beats) / len(post_beats)
        if post_avg < after_thresh:
            continue

        if bass_gate:
            gate_beats = beats[max(0, gs - gate_window) : gs]
            if not gate_beats or max(b.bass_onset_score for b in gate_beats) < gate_thresh:
                continue

        contrast      = post_avg / max(pre_avg, 0.01)
        pre_sust  = sum(1 for b in pre_beats  if b.rms_bass > before_thresh) / len(pre_beats)
        post_sust = sum(1 for b in post_beats if b.rms_bass > after_thresh)  / len(post_beats)
        score = contrast * (0.5 + 0.25 * pre_sust + 0.25 * post_sust)
        results.append((gs, ge, score))

    # Resolve overlapping gaps: keep highest-scoring
    if not results:
        return results
    results.sort(key=lambda x: x[0])
    merged: list[tuple[int, int, float]] = [results[0]]
    for gs, ge, sc in results[1:]:
        prev_gs, prev_ge, prev_sc = merged[-1]
        if gs <= prev_ge:  # overlapping — keep best
            if sc > prev_sc:
                merged[-1] = (gs, ge, sc)
        else:
            merged.append((gs, ge, sc))
    return merged


def _detect_charges_from_gaps(beats, gaps, tp) -> list[int | None]:
    """
    Return one charge beat index (or None) per gap.
    Scans the preceding window for the highest combined bass+total energy beat.
    Uses (rms_total + rms_bass) / 2 so the charge is the loudest bass-present beat
    in the buildup, not biased by onset_score which normalises to the song max.
    Returns a list aligned with gaps: charges[i] is the charge for gaps[i], or None.
    """
    lookback  = getattr(tp, "charge_lookback_beats", 12)
    min_score = getattr(tp, "charge_min_score",      0.40)

    def _score(b):
        return (b.rms_total + b.rms_bass) / 2.0

    charges: list[int | None] = []
    for gs, ge, _ in gaps:
        search_start = max(0, gs - lookback)
        window = beats[search_start : gs]
        if not window:
            charges.append(None)
            continue
        best = max(window, key=_score)
        if _score(best) >= min_score:
            charges.append(search_start + window.index(best))
        else:
            charges.append(None)
    return charges


def _detect_quiet_sections(beats, tp) -> list[int]:
    """
    Find extended quiet sections (>= quiet_min_beats) and return the best
    trigger position for each.  All qualifying runs produce a trigger — the
    ramp window is used purely to choose WHERE to place it:

      • Gradual ramp detected (energy declining gently in the window before
        the quiet section, starting from above quiet_thresh):
          → fire at START OF RAMP (run_start - ramp_beats), so the scene
            change leads the silence rather than reacting to it.

      • No clear gradual ramp (abrupt drop, flat, or insufficient context):
          → fire at run_start (start of the quiet section itself).

    The ramp is not a hard gate — abrupt entries still produce a trigger at
    run_start (the gap/lull detector handles the abrupt-entry pair up to
    gap_max_beats; sections longer than that still need a quiet trigger).

    quiet_min_beats > gap_max_beats by design, preventing overlap with gap
    detection on normally-short lull/drop pairs.
    """
    thresh        = getattr(tp, "quiet_thresh",       0.40)
    min_beats     = getattr(tp, "quiet_min_beats",     24)
    ramp_beats_n  = getattr(tp, "quiet_ramp_beats",     8)
    ramp_max_step = getattr(tp, "quiet_ramp_max_step", 0.08)

    n = len(beats)
    in_quiet = False
    quiet_start = 0
    runs: list[int] = []

    for i, beat in enumerate(beats):
        if beat.rms_total < thresh and not in_quiet:
            in_quiet = True
            quiet_start = i
        elif beat.rms_total >= thresh and in_quiet:
            in_quiet = False
            if i - quiet_start >= min_beats:
                runs.append(quiet_start)
    if in_quiet and n - quiet_start >= min_beats:
        runs.append(quiet_start)

    result: list[int] = []
    for run_start in runs:
        pre = beats[max(0, run_start - ramp_beats_n) : run_start]
        trigger_idx = run_start  # default: fire at quiet entry

        if len(pre) >= 2:
            mid = len(pre) // 2
            early_avg = sum(b.rms_total for b in pre[:mid]) / max(mid, 1)
            late_avg  = sum(b.rms_total for b in pre[mid:]) / max(len(pre) - mid, 1)
            per_beat_drop = (early_avg - late_avg) / max(mid, 1)
            # Gradual ramp: was above quiet_thresh and declining gently
            if early_avg > thresh and 0 < per_beat_drop <= ramp_max_step:
                trigger_idx = max(0, run_start - ramp_beats_n)

        result.append(trigger_idx)
    return result


# ── Standard fill helper ───────────────────────────────────────────────────────

def _fill_standard_scenes(
    beats, placed: list[dict], off: int,
    event_id: str, coverage_gap_ms: int, fill_spacing_ms: int,
    uptick_thresh: float, harmonic_thresh: float,
) -> None:
    """
    Iteratively fill the timeline until no gap between placed triggers exceeds
    coverage_gap_ms (min_scene_change_spacing_beats).  Candidate beats are
    selected by priority:
      1. Energy uptick: next beat is notably louder than either of the 2 preceding
      2. Harmonic change: harmonic_score above threshold (take highest in gap)
      3. Downbeat: is_downbeat = True (take first)
      4. Fallback: first beat in window

    fill_spacing_ms (fill_min_spacing_beats) is a hard minimum: no fill is placed
    within that distance of any already-placed trigger.  If the best gap can't
    accommodate a beat satisfying this constraint, filling stops.
    """
    n = len(beats)
    song_start_ms = beats[0].ms + off
    song_end_ms   = beats[-1].ms + off

    for _ in range(n):  # safety upper bound
        placed_ms = sorted(p["timestamp_ms"] for p in placed)
        # sort so gap arithmetic is always positive
        checkpoints = sorted(set([song_start_ms, song_end_ms] + placed_ms))

        # Find the largest uncovered gap
        best_width, best_lo, best_hi = 0, 0, 0
        for j in range(len(checkpoints) - 1):
            w = checkpoints[j + 1] - checkpoints[j]
            if w > best_width:
                best_width, best_lo, best_hi = w, checkpoints[j], checkpoints[j + 1]

        if best_width <= coverage_gap_ms:
            break  # all gaps satisfied

        # Candidate beats: inside the gap AND at least fill_spacing_ms from every
        # existing trigger (enforces minimum density between fills)
        window = [
            (i, b) for i, b in enumerate(beats)
            if best_lo < b.ms + off < best_hi
            and not _covered(b.ms + off, placed, fill_spacing_ms)
        ]
        if not window:
            break  # gap can't be filled without violating minimum spacing

        chosen_ms: int | None = None
        chosen_conf = 0.40

        # Priority 1 — energy uptick
        uptick = [
            (i, b) for i, b in window
            if i >= 2 and i + 1 < n
            and beats[i + 1].rms_total > max(beats[i - 1].rms_total, beats[i - 2].rms_total) + uptick_thresh
        ]
        if uptick:
            bi, b = max(uptick,
                        key=lambda x: beats[x[0] + 1].rms_total
                                      - max(beats[x[0] - 1].rms_total, beats[x[0] - 2].rms_total))
            chosen_ms, chosen_conf = b.ms + off, 0.70

        # Priority 2 — harmonic change
        if chosen_ms is None:
            harm = [(i, b) for i, b in window if b.harmonic_score >= harmonic_thresh]
            if harm:
                bi, b = max(harm, key=lambda x: x[1].harmonic_score)
                chosen_ms, chosen_conf = b.ms + off, 0.60

        # Priority 3 — downbeat
        if chosen_ms is None:
            down = [(i, b) for i, b in window if b.is_downbeat]
            if down:
                chosen_ms, chosen_conf = down[0][1].ms + off, 0.50

        # Fallback
        if chosen_ms is None:
            chosen_ms, chosen_conf = window[0][1].ms + off, 0.40

        placed.append({
            "timestamp_ms": chosen_ms,
            "event_id":     event_id,
            "confidence":   chosen_conf,
            "_exempt":      False,
        })


# ── Confidence boost helpers ──────────────────────────────────────────────────

def _drop_score_boost(beats: list, idx: int) -> float:
    """
    Boost for bass drop: reward clear energy contrast across the drop.
    Compares avg(rms_total + rms_bass) for the 2 beats before vs 2 beats after.
    Returns a multiplier in [1.0, SCORE_BOOST_MAX].
    """
    if idx < 2 or idx + 2 >= len(beats):
        return 1.0
    pre  = (beats[idx - 2].rms_total + beats[idx - 2].rms_bass +
            beats[idx - 1].rms_total + beats[idx - 1].rms_bass) / 4.0
    post = (beats[idx + 1].rms_total + beats[idx + 1].rms_bass +
            beats[idx + 2].rms_total + beats[idx + 2].rms_bass) / 4.0
    if post <= pre or pre <= 0:
        return 1.0
    contrast = post / pre - 1.0          # 0 = no change, 1 = doubled energy
    boost = 1.0 + min(contrast * 0.5, SCORE_BOOST_MAX - 1.0)
    return min(boost, SCORE_BOOST_MAX)


def _quiet_score_boost(beats: list, idx: int) -> float:
    """
    Boost for quiet entry: reward when the next 5 beats are quieter than the preceding 5.
    Compares avg(rms_total + rms_bass) across the two windows.
    Returns a multiplier in [1.0, SCORE_BOOST_MAX].
    """
    n = len(beats)
    pre_window  = beats[max(0, idx - 5):idx]
    post_window = beats[idx + 1:min(n, idx + 6)]
    if not pre_window or not post_window:
        return 1.0
    pre  = sum(b.rms_total + b.rms_bass for b in pre_window)  / len(pre_window)
    post = sum(b.rms_total + b.rms_bass for b in post_window) / len(post_window)
    if pre <= 0 or post >= pre:
        return 1.0
    drop_frac = (pre - post) / pre          # 0 = no drop, 1 = silence after
    boost = 1.0 + min(drop_frac * 0.5, SCORE_BOOST_MAX - 1.0)
    return min(boost, SCORE_BOOST_MAX)


def _charge_score_boost(beats: list, idx: int) -> float:
    """
    Boost for charge: reward when onset/bass energy is higher in the next 5 beats
    than the preceding 5 (confirming the build is heading toward a peak).
    Returns a multiplier in [1.0, SCORE_BOOST_MAX].
    """
    n = len(beats)
    pre_window  = beats[max(0, idx - 5):idx]
    post_window = beats[idx + 1:min(n, idx + 6)]
    if not pre_window or not post_window:
        return 1.0
    pre  = sum(b.onset_score + b.bass_onset_score for b in pre_window)  / len(pre_window)
    post = sum(b.onset_score + b.bass_onset_score for b in post_window) / len(post_window)
    if post <= pre or pre <= 0:
        return 1.0
    contrast = post / pre - 1.0
    boost = 1.0 + min(contrast * 0.5, SCORE_BOOST_MAX - 1.0)
    return min(boost, SCORE_BOOST_MAX)


def _flare_score_boost(beats: list, idx: int) -> float:
    """
    Boost for flare: reward rising energy into the beat + strong harmonic content.
    Returns a multiplier in [1.0, SCORE_BOOST_MAX].
    """
    beat  = beats[idx]
    boost = 1.0
    # Rising energy: this beat is louder than the previous
    if idx > 0 and beat.rms_total > beats[idx - 1].rms_total:
        boost += 0.20
    # Harmonic strength above baseline (graduated 0–0.25 over FLARE_HARMONIC_THRESH → 1.0)
    harmonic_range = 1.0 - FLARE_HARMONIC_THRESH
    if harmonic_range > 0 and beat.harmonic_score > FLARE_HARMONIC_THRESH:
        frac = (beat.harmonic_score - FLARE_HARMONIC_THRESH) / harmonic_range
        boost += frac * 0.25
    return min(boost, SCORE_BOOST_MAX)


# ── Density filter ────────────────────────────────────────────────────────────

def _density_filter(candidates: list[dict], min_gap_ms: int,
                    exempt_ids: set[str] | None = None) -> list[dict]:
    """Keep highest-confidence trigger when two fall within min_gap_ms.
    Triggers in exempt_ids are always kept."""
    if not candidates:
        return []
    candidates.sort(key=lambda c: c["timestamp_ms"])
    kept: list[dict] = []
    for c in candidates:
        is_exempt = exempt_ids and c.get("_exempt")
        if is_exempt:
            kept.append(c)
            continue
        if kept and c["timestamp_ms"] - kept[-1]["timestamp_ms"] < min_gap_ms:
            if not kept[-1].get("_exempt") and c["confidence"] > kept[-1]["confidence"]:
                kept[-1] = c
        else:
            kept.append(c)
    # Strip internal marker
    for c in kept:
        c.pop("_exempt", None)
    return kept


# ── Main entry point ──────────────────────────────────────────────────────────

def suggest_triggers(
    target_uri: str,
    all_training_uris: list[str],
    available_event_ids: set[str],
    *,
    training_profile=None,
) -> list[dict]:
    """
    Run the 8-stage explicit structural pipeline for target_uri.
    No KNN — all event placements are driven by analytical detectors.

    Returns a list of dicts: {timestamp_ms, event_id, confidence}
    """
    from services.librosa_service import get_analysis_by_uri

    tp = training_profile

    # ── Per-profile event IDs ─────────────────────────────────────────────────
    start_event_id       = getattr(tp, "song_start_event_id",  "") or ""
    beat_start_event_id  = getattr(tp, "beat_start_event_id", "") or ""
    end_event_id         = getattr(tp, "song_end_event_id",   "") or ""
    drop_event_id       = getattr(tp, "drop_event_id",        "") or ""
    lull_event_id       = getattr(tp, "lull_event_id",        "") or ""
    charge_event_id     = getattr(tp, "charge_event_id",      "") or ""
    quiet_event_id      = getattr(tp, "quiet_event_id",       "") or ""
    scene_fill_event_id = getattr(tp, "scene_fill_event_id",  "") or ""
    flare_event_id      = getattr(tp, "flare_event_id",       "") or ""
    flare_max_gap_beats = getattr(tp, "flare_max_gap_beats",  32)

    # ── Per-profile spacing ───────────────────────────────────────────────────
    spacing_beats       = getattr(tp, "min_trigger_spacing_beats",      4)
    scene_spacing_beats = getattr(tp, "min_scene_change_spacing_beats", 16)

    # ── Load target analysis ──────────────────────────────────────────────────
    la = get_analysis_by_uri(target_uri)
    if not la or not la.beats:
        logger.warning("Embedded: no librosa analysis for %s", target_uri)
        return []

    beats = la.beats
    off   = la.librosa_offset_ms

    beat_interval_ms = (60_000.0 / la.tempo_bpm) if la.tempo_bpm > 0 else 500.0
    gap_ms           = max(MIN_GAP_MS, int(spacing_beats * beat_interval_ms))
    scene_gap_ms     = max(gap_ms, int(scene_spacing_beats * beat_interval_ms))

    placed: list[dict] = []

    def _add(timestamp_ms: int, event_id: str, confidence: float, exempt: bool = False):
        placed.append({
            "timestamp_ms": timestamp_ms,
            "event_id":     event_id,
            "confidence":   confidence,
            "_exempt":      exempt,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 0 — Song start (always ms=0)
    # ─────────────────────────────────────────────────────────────────────────
    if start_event_id and start_event_id in available_event_ids:
        _add(0, start_event_id, 1.0, exempt=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 1 — Beat start (first bass entry)
    # Uses beat_start_event_id if set; falls back to scene_fill_event_id.
    # ─────────────────────────────────────────────────────────────────────────
    _bs_event = (beat_start_event_id if beat_start_event_id and beat_start_event_id in available_event_ids
                 else scene_fill_event_id if scene_fill_event_id and scene_fill_event_id in available_event_ids
                 else "")
    if _bs_event:
        bs_idx = _detect_beat_start(beats, tp, off)
        if bs_idx is not None:
            bs_ms = beats[bs_idx].ms + off
            if not _covered(bs_ms, placed, gap_ms):
                _add(bs_ms, _bs_event, 0.90)

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 2 — Song end (bookend; placed before fill stages)
    # ─────────────────────────────────────────────────────────────────────────
    if end_event_id and end_event_id in available_event_ids:
        end_idx = _detect_song_end(beats, tp)
        if end_idx is not None:
            _add(beats[end_idx].ms + off, end_event_id, 1.0, exempt=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Stages 3 + 4 — Gap detection → Charge + Lull + Bass Drop
    #
    # Rule: Drop can stand alone. Lull is only emitted when a Charge is also
    # found for the same gap (they form a trio: Charge → Lull → Drop).
    # ─────────────────────────────────────────────────────────────────────────
    gaps = _detect_gaps(beats, tp)
    charge_idxs = _detect_charges_from_gaps(beats, gaps, tp)  # aligned with gaps

    for (gs, ge, gap_score), charge_idx in zip(gaps, charge_idxs):
        drop_idx = min(ge + 1, len(beats) - 1)

        # Bass Drop — always emitted when a valid gap is found
        if drop_event_id and drop_event_id in available_event_ids:
            drop_ms = beats[drop_idx].ms + off
            if not _covered(drop_ms, placed, gap_ms):
                boost = _drop_score_boost(beats, drop_idx)
                _add(drop_ms, drop_event_id, min(gap_score * boost, SCORE_BOOST_MAX))

        # Lull + Charge — only emitted together when a charge beat was found
        if charge_idx is not None:
            if lull_event_id and lull_event_id in available_event_ids:
                lull_ms = beats[gs].ms + off
                if not _covered(lull_ms, placed, gap_ms):
                    boost = _quiet_score_boost(beats, gs)
                    _add(lull_ms, lull_event_id, min(gap_score * boost, SCORE_BOOST_MAX))

            if charge_event_id and charge_event_id in available_event_ids:
                cms = beats[charge_idx].ms + off
                if not _covered(cms, placed, gap_ms):
                    boost = _charge_score_boost(beats, charge_idx)
                    _add(cms, charge_event_id, min(0.85 * boost, SCORE_BOOST_MAX))

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 5 — Quiet sections (extended low-energy with gradual entry)
    # ─────────────────────────────────────────────────────────────────────────
    if quiet_event_id and quiet_event_id in available_event_ids:
        for qi in _detect_quiet_sections(beats, tp):
            qms = beats[qi].ms + off
            if not _covered(qms, placed, gap_ms):
                boost = _quiet_score_boost(beats, qi)
                _add(qms, quiet_event_id, min(0.80 * boost, SCORE_BOOST_MAX))

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 6 — Standard scene fill (fill-until-satisfied)
    # ─────────────────────────────────────────────────────────────────────────
    if scene_fill_event_id and scene_fill_event_id in available_event_ids:
        fill_uptick       = getattr(tp, "fill_uptick_thresh",      0.10)
        fill_harmonic     = getattr(tp, "fill_harmonic_thresh",    0.35)
        fill_min_spacing  = getattr(tp, "fill_min_spacing_beats",  48)
        fill_spacing_ms   = max(gap_ms, int(fill_min_spacing * beat_interval_ms))
        _fill_standard_scenes(
            beats, placed, off,
            scene_fill_event_id, scene_gap_ms, fill_spacing_ms,
            fill_uptick, fill_harmonic,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 7 — Flare fill (dynamic gap, harmonic-sorted)
    # ─────────────────────────────────────────────────────────────────────────
    if flare_event_id and flare_event_id in available_event_ids:
        from config import settings as _cfg
        # Flares use gap_ms (min trigger spacing) as the high-energy floor —
        # they are not bounded by min_scene_change_spacing_beats.
        flare_max_gap_ms = max(gap_ms, int(flare_max_gap_beats * beat_interval_ms))
        rms_high  = _cfg.flare_rms_high
        rms_low   = _cfg.flare_rms_low
        rms_range = max(rms_high - rms_low, 1e-9)

        rms_arr     = np.array([b.rms_total for b in beats])
        n_beats     = len(rms_arr)
        window_avgs = np.zeros(n_beats)
        for bi in range(n_beats):
            lo = max(0, bi - _CONTEXT_BEATS)
            hi = min(n_beats, bi + _CONTEXT_BEATS + 1)
            window_avgs[bi] = rms_arr[lo:hi].mean()

        candidates = [(bi, b) for bi, b in enumerate(beats) if b.harmonic_score > FLARE_HARMONIC_THRESH]
        candidates.sort(key=lambda x: x[1].harmonic_score, reverse=True)

        for fbi, fb in candidates:
            fms = fb.ms + off
            t = float(np.clip((window_avgs[fbi] - rms_low) / rms_range, 0.0, 1.0))
            local_gap_ms = int(flare_max_gap_ms + t * (gap_ms - flare_max_gap_ms))
            local_gap_ms = max(gap_ms, local_gap_ms)
            if _covered(fms, placed, local_gap_ms):
                continue
            _add(fms, flare_event_id, 1.0)

    # ─────────────────────────────────────────────────────────────────────────
    # Density filter + final sort
    # ─────────────────────────────────────────────────────────────────────────
    results = _density_filter(placed, gap_ms)
    results.sort(key=lambda c: c["timestamp_ms"])

    logger.info(
        "Embedded: %d candidates → %d after density filter for %s",
        len(placed), len(results), target_uri,
    )
    return results
