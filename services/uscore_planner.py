"""
SpotFX — U-Score offline window planner (round 7).

Replaces the runtime difficulty/uniqueness window planner with an offline scorer
that pre-vets windows against the runtime rejection criteria (beat-twin,
ambiguous-margin) so the sweep at runtime only evaluates windows that are
expected to produce clean signal.

Method A — shift-and-subtract:

  For each candidate window position, slide the captured shape against itself
  in 25ms steps over [-6 beats, +6 beats] and compute the L1 residual at each
  shift. A window's per-band U-Score is the MIN residual across all non-zero
  shifts: a high min means no shift produces a near-zero residual, i.e., the
  window is structurally unique within the test range.

  The final U-Score is the mean across bands. Windows that fail simulated
  beat-twin or ambiguous-margin tests are filtered out before selection.

Output: list of {start_ms, end_ms, length_ms, u_score, u_per_band, beat_period_ms}
        suitable for storage on AudioShapeMeta.xcorr_windows and direct use by
        the runtime sweep.
"""
from __future__ import annotations
import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Same resampling grid used by the runtime xcorr matcher so residuals are
# comparable to what runtime r values are computed against.
_BIN_MS = 25

# Default planner parameters (round 7).
_WINDOW_LENGTH_MS = 5000          # fixed for now; scaffold is variable per-window
_CANDIDATE_STEP_MS = 250          # slide between candidate window positions
# Round 9.6: bumped cap 20 → 40 and max overlap 1000 → 3000.
# Even narrow-envelope windows can incrementally refine the engine when many
# of them agree; the runtime envelope clip per-window prevents far-twin damage,
# so denser packing is safe. Adjacent 5000ms windows can now sit 2000ms apart
# (was 4000ms), and we'll accept up to 40 selections per song.
_MAX_WINDOWS_DEFAULT = 40
_MAX_OVERLAP_MS = 3000            # max overlap between two selected windows
_MANDATORY_EARLY_START_MIN = 10000
_MANDATORY_EARLY_START_MAX = 20000
_MANDATORY_BEFORE_MS = 40000
_MANDATORY_BEFORE_COUNT = 3       # 3 more windows after the [10-20s] mandatory one
_FIRST_START_MS = 5000
_END_BUFFER_MS = 30000

# U-Score threshold and runtime-gate simulation parameters.
# Round 9: widened from 6 → 12 to catch far beat-tile twins (the round-8
# `3pm4Xtcs` failure had four candidates spaced 1500-7500ms apart, beyond ±6
# beats at 120 BPM). Matrix width doubles; matrix-once architecture absorbs it.
_BEAT_RANGE = 12                  # ±N beats span for the shift search
_BEAT_TWIN_OFFSETS = (1, 2, 4)    # tested for the beat-twin filter (legacy; round 9.5 envelope subsumes)
_AMBIGUOUS_SEARCH_MS = 7000       # ±N ms range for the ambiguous-margin filter (legacy)
_AMBIGUOUS_MARGIN_PCT = 0.08      # legacy binary-gate threshold; superseded by envelope in round 9.5.
# Round 9.5: per-window safe-shift envelope. For each band, find the smallest
# |δ| in each direction where the residual drops within
# `_ENVELOPE_THRESHOLD_PCT` of the band's worst-case alternative-shift residual
# — that's the closest twin in that direction. The window's safe envelope =
# (twin_distance − _ENVELOPE_SAFETY_BUFFER_MS) in each direction, taken as the
# min across bands so the window is safe in ALL bands. Replaces the binary
# beat-twin / ambiguous-margin gates with a continuous, per-direction tolerance
# the runtime can clip its measurement to.
_ENVELOPE_THRESHOLD_PCT = 0.10        # twin = residual within 10% of band's worst-case alt
# Round 9.6: 200 → 100. Smaller buffer = wider envelopes, so more windows
# qualify with usable refinement range.
_ENVELOPE_SAFETY_BUFFER_MS = 100
# Round 9.6: 600 → 100. Even narrow-envelope windows can refine the engine in
# small steps when many of them agree. The runtime envelope clip still rejects
# any measurement that strays past a window's safe range, so admitting a
# tight-envelope window doesn't open the door to far twins — it just contributes
# evidence for offsets close to the engine's current position.
_MIN_TOTAL_ENVELOPE_MS = 100
_MIN_USCORE_KEEP = 0.005              # absolute uniqueness floor (round 9)
_DEFAULT_BEAT_MS_FALLBACK = 500.0 # 120 BPM if no librosa data

# Per-band weights for the mean-across-bands window U-Score. Bass dominates
# because triggers usually anchor on bass hits and the mid/high bands carry
# more noise. Round 10 appends two derived bands AFTER the four primary RMS
# bands: rms_low_inv (silence-emphasizing — high during quiet sections) and
# rms_low_deriv (onset/offset transitions — spikes at any abrupt energy change).
# Captures structure that signed_square amplitude weighting flattens to zero.
# Order: total, low, mid, high, low_inv, low_deriv.
_BAND_WEIGHTS = (1.0, 3.0, 1.5, 1.0, 2.0, 1.5)
_BAND_KEYS = ("rms_total", "rms_low", "rms_mid", "rms_high")  # primary bands loaded from npz
_DERIVED_BAND_NAMES = ("rms_low_inv", "rms_low_deriv")        # round 10 derived from rms_low


def _signed_square(arr: np.ndarray) -> np.ndarray:
    return arr * np.abs(arr)


def _local_beat_period_ms(beats_ms: list[int], song_pos_ms: int) -> float:
    """Median beat period over the 4-8 beats nearest `song_pos_ms`.
    Falls back to the global mean if not enough beats nearby, then to 500ms."""
    if not beats_ms or len(beats_ms) < 2:
        return _DEFAULT_BEAT_MS_FALLBACK
    arr = np.asarray(beats_ms, dtype=float)
    # Find the index of the beat closest to song_pos_ms.
    idx = int(np.argmin(np.abs(arr - song_pos_ms)))
    lo = max(0, idx - 4)
    hi = min(len(arr), idx + 5)
    nearby = arr[lo:hi]
    if len(nearby) < 2:
        # Use global mean as last resort
        global_diffs = np.diff(arr)
        return float(np.median(global_diffs)) if len(global_diffs) else _DEFAULT_BEAT_MS_FALLBACK
    diffs = np.diff(nearby)
    return float(np.median(diffs))


def _resample_band(timestamps_ms: np.ndarray, band: np.ndarray, grid_ms: np.ndarray) -> np.ndarray:
    """Resample a band onto a uniform 25ms grid, with signed-square amplitude
    weighting to match the runtime matcher."""
    raw = np.interp(grid_ms, timestamps_ms.astype(float), band.astype(float), left=0.0, right=0.0)
    return _signed_square(raw)


def _agc(arr: np.ndarray) -> np.ndarray:
    """Per-band AGC: divide by 95th percentile of |arr| so windows captured at
    different amplitudes are comparable. Mirrors runtime _agc_normalize."""
    if arr.size == 0:
        return arr
    scale = float(np.percentile(np.abs(arr), 95)) + 1e-6
    return arr / scale


def _sliding_mean(arr: np.ndarray, win_len: int) -> np.ndarray:
    """Compute mean(arr[p:p+win_len]) for each valid p. Output length =
    len(arr) - win_len + 1. Uses the cumsum trick: O(n) regardless of win_len.
    """
    if len(arr) < win_len:
        return np.array([], dtype=np.float64)
    cs = np.cumsum(arr, dtype=np.float64)
    cs = np.concatenate(([0.0], cs))
    return (cs[win_len:] - cs[:-win_len]) / win_len


def _build_window_uniqueness(
    bands_full_norm: list[np.ndarray],
    max_shift_bins: int,
    win_len_bins: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build per-band per-position WINDOW uniqueness profiles in one matrix pass.

    For each shift δ ∈ [-max_shift_bins, +max_shift_bins] excluding 0, each
    band b, and each window start position p:

        W[b, δ, p] = mean over t∈[p, p+win_len) of (band(t,b) - band(t+δ,b))²

    Then collapse across shifts:

        per_band_window_uniq[b, p] = min_{δ ≠ 0, valid} W[b, δ, p]

    The min-over-shifts is at the WINDOW level, not the tick level. This is
    deliberate: at the tick level, periodic music has *some* shift that fakes
    nearly any single tick, so the per-tick min collapses to ~0 everywhere.
    At the window level, a window's gestalt (a 5-second pattern, e.g.
    "drums-then-silence") is hard to fake unless the song repeats that exact
    pattern at one of the tested shifts.

    Returns:
      (per_band_window_uniq, per_tick_max_band)
      - per_band_window_uniq: shape (n_bands, n_positions). The window-level
        worst-case alternative-shift residual per band. High value ⇒ no shift
        produces a near-zero window-mean residual ⇒ the window is unique.
      - per_tick_max_band: shape (n_ticks,). For each tick, max across bands
        of (min across shifts of pointwise squared residual). Useful for
        visualizing the song's per-tick uniqueness profile (will be near-zero
        in periodic regions and spike at transitions). NOT used for window
        scoring.
    """
    n_bands = len(bands_full_norm)
    n_ticks = len(bands_full_norm[0])
    n_positions = n_ticks - win_len_bins + 1
    if n_positions <= 0:
        return np.zeros((n_bands, 0)), np.zeros(n_ticks)

    per_band_window_uniq = np.full((n_bands, n_positions), np.inf, dtype=np.float64)
    per_band_tick_min = np.full((n_bands, n_ticks), np.inf, dtype=np.float64)

    for band_idx, b in enumerate(bands_full_norm):
        for delta in range(-max_shift_bins, max_shift_bins + 1):
            if delta == 0:
                continue
            # Compute pointwise squared residual r[t] = (b[t] - b[t+δ])² for
            # valid t. Valid range depends on shift sign.
            if delta > 0:
                resid = (b[:n_ticks - delta] - b[delta:]) ** 2
                start_t = 0
            else:
                d = -delta
                resid = (b[d:] - b[:n_ticks - d]) ** 2
                start_t = d
            # Sliding window-mean of the residual signal. w_means[i] is the
            # window-mean residual for the window starting at residual-index i,
            # which corresponds to absolute tick (start_t + i).
            if len(resid) >= win_len_bins:
                w_means = _sliding_mean(resid, win_len_bins)
                # The window starting at absolute tick p uses residual-indices
                # [p - start_t : p - start_t + win_len_bins], which is valid
                # when p ∈ [start_t, start_t + len(w_means)). So map w_means
                # into per_band_window_uniq at positions [start_t, ...).
                upper = min(start_t + len(w_means), n_positions)
                length = upper - start_t
                if length > 0:
                    np.minimum(
                        per_band_window_uniq[band_idx, start_t:upper],
                        w_means[:length],
                        out=per_band_window_uniq[band_idx, start_t:upper],
                    )
            # Update per-tick min (visualization profile) — same residual
            # signal, no window aggregation.
            tick_upper = start_t + len(resid)
            np.minimum(
                per_band_tick_min[band_idx, start_t:tick_upper],
                resid,
                out=per_band_tick_min[band_idx, start_t:tick_upper],
            )

    # Convert leftover +inf cells (positions whose window never had a valid
    # shift) to NaN so window aggregation can ignore them.
    per_band_window_uniq[np.isinf(per_band_window_uniq)] = np.nan
    per_band_tick_min[np.isinf(per_band_tick_min)] = np.nan
    # Per-tick max-across-bands → visualization profile.
    per_tick_max_band = np.nanmax(per_band_tick_min, axis=0)
    return per_band_window_uniq, per_tick_max_band


def _window_u_score(
    per_band_window_uniq: np.ndarray,   # shape (n_bands, n_positions)
    win_start_bin: int,                 # = window position p
) -> Optional[tuple[float, list[float]]]:
    """Read the precomputed per-band window-uniqueness at a given start position
    and combine bands with bass-weighted mean.

    Returns (window_u_score, per_band_values) where:
      - per_band_values[b] = per_band_window_uniq[b, p] (NaN if invalid).
      - window_u_score = weighted mean across bands (_BAND_WEIGHTS, bass 3×).
    """
    n_bands = per_band_window_uniq.shape[0]
    n_positions = per_band_window_uniq.shape[1]
    if win_start_bin < 0 or win_start_bin >= n_positions:
        return None
    per_band_values: list[float] = []
    for b_idx in range(n_bands):
        v = float(per_band_window_uniq[b_idx, win_start_bin])
        if np.isnan(v):
            return None
        per_band_values.append(v)
    weights = np.asarray(_BAND_WEIGHTS, dtype=float)
    if weights.size != n_bands:
        weights = np.ones(n_bands, dtype=float)
    weights = weights / weights.sum()
    u_score = float(sum(w * v for w, v in zip(weights, per_band_values)))
    return u_score, per_band_values


def _residual_at_shift(
    band_window: np.ndarray,
    band_full: np.ndarray,
    win_start_bin: int,
    win_len_bins: int,
    shift_bins: int,
) -> Optional[float]:
    """Mean squared residual of `band_window` against `band_full` at a specific
    shift, used by the simulated runtime gates after the per-band uniqueness
    profile is built. Returns None when the shifted window goes off the song.
    """
    src = win_start_bin + shift_bins
    end = src + win_len_bins
    if src < 0 or end > len(band_full):
        return None
    diff = band_window - band_full[src:end]
    return float(np.mean(diff * diff))


def _compute_safe_envelope(
    bands_full_norm: list[np.ndarray],
    win_start_bin: int,
    win_len_bins: int,
    max_shift_bins: int,
    threshold_pct: float = _ENVELOPE_THRESHOLD_PCT,
    safety_buffer_bins: int = _ENVELOPE_SAFETY_BUFFER_MS // _BIN_MS,
) -> tuple[int, int]:
    """Compute the safe-shift envelope (safe_neg_bins, safe_pos_bins) for a
    candidate window.

    For each band, walk outward from δ=0 and find the smallest |δ| where the
    residual drops within `threshold_pct` of the band's worst-case alternative
    residual (the closest "twin" in that direction). Subtract the safety buffer
    and floor at 0. The window-level envelope is the MIN across bands — we
    must be safe in every band.

    Returns:
      (safe_neg_bins, safe_pos_bins) — both non-negative integers in
      bin units. The runtime can trust a window measurement that lands within
      [engine_current - safe_neg_bins*_BIN_MS, engine_current + safe_pos_bins*_BIN_MS].
    """
    if max_shift_bins < 1 or len(bands_full_norm) == 0:
        return 0, 0
    n_bands = len(bands_full_norm)
    band_windows = [b[win_start_bin:win_start_bin + win_len_bins] for b in bands_full_norm]
    if any(b.size != win_len_bins for b in band_windows):
        return 0, 0
    if any(float(b.std()) < 1e-6 for b in band_windows):
        return 0, 0

    per_band_neg = [max_shift_bins] * n_bands
    per_band_pos = [max_shift_bins] * n_bands

    for band_idx, (b_window, b_full) in enumerate(zip(band_windows, bands_full_norm)):
        residuals_pos: dict[int, float] = {}
        residuals_neg: dict[int, float] = {}
        band_min: float = float("inf")
        for delta in range(1, max_shift_bins + 1):
            r_pos = _residual_at_shift(b_window, b_full, win_start_bin, win_len_bins,  delta)
            if r_pos is not None:
                residuals_pos[delta] = r_pos
                if r_pos < band_min:
                    band_min = r_pos
            r_neg = _residual_at_shift(b_window, b_full, win_start_bin, win_len_bins, -delta)
            if r_neg is not None:
                residuals_neg[delta] = r_neg
                if r_neg < band_min:
                    band_min = r_neg
        if not np.isfinite(band_min) or band_min <= 0:
            # No valid alternative shifts; treat as fully safe (max range).
            continue
        threshold = band_min * (1.0 + threshold_pct)
        for delta in range(1, max_shift_bins + 1):
            r = residuals_pos.get(delta)
            if r is not None and r <= threshold:
                per_band_pos[band_idx] = delta
                break
        for delta in range(1, max_shift_bins + 1):
            r = residuals_neg.get(delta)
            if r is not None and r <= threshold:
                per_band_neg[band_idx] = delta
                break

    # Min across bands (worst-case) — minus the safety buffer, floored at 0.
    safe_pos = max(0, min(per_band_pos) - safety_buffer_bins)
    safe_neg = max(0, min(per_band_neg) - safety_buffer_bins)
    return safe_neg, safe_pos


def _gate_check_window(
    bands_full_norm: list[np.ndarray],
    win_start_bin: int,
    win_len_bins: int,
    beat_period_bins: int,
) -> tuple[bool, bool]:
    """Run the simulated runtime gates against a candidate window and return
    (beat_twin_safe, ambig_safe).

    Beat-twin gate: residuals at ±1, ±2, ±4 *local beats* must exceed the
    band's overall min residual by at least 10%. When any beat-shift residual
    is within 10% of the band's min, the runtime gate would reject.

    Ambiguous-margin gate: in ±_AMBIGUOUS_SEARCH_MS, the second-smallest
    residual must exceed the smallest by at least _AMBIGUOUS_MARGIN_PCT.
    """
    max_shift_bins = _BEAT_RANGE * beat_period_bins
    band_windows = [b[win_start_bin:win_start_bin + win_len_bins] for b in bands_full_norm]
    if any(float(b.std()) < 1e-6 for b in band_windows):
        return False, False

    beat_twin_safe = True
    ambig_safe = True
    ambig_search_bins = _AMBIGUOUS_SEARCH_MS // _BIN_MS
    for band_idx, (b_window, b_full) in enumerate(zip(band_windows, bands_full_norm)):
        residuals_by_delta: dict[int, float] = {}
        for delta in range(-max_shift_bins, max_shift_bins + 1):
            if delta == 0:
                continue
            r = _residual_at_shift(b_window, b_full, win_start_bin, win_len_bins, delta)
            if r is not None:
                residuals_by_delta[delta] = r
        if not residuals_by_delta:
            return False, False

        band_min = min(residuals_by_delta.values())

        # Beat-twin check
        if beat_twin_safe:
            for n in _BEAT_TWIN_OFFSETS:
                for sign in (-1, 1):
                    d = sign * n * beat_period_bins
                    tr = residuals_by_delta.get(d)
                    if tr is None:
                        continue
                    # Round 7 Looser B: 1.10 → 1.02. Beat shift only fails the
                    # gate when its residual is within 2% of the band's min —
                    # i.e., near-equivalence to the worst-case alternative.
                    if tr < band_min * 1.02:
                        beat_twin_safe = False
                        break
                if not beat_twin_safe:
                    break

        # Ambiguous-margin check
        if ambig_safe:
            nearby = [r for d, r in residuals_by_delta.items() if abs(d) <= ambig_search_bins]
            if len(nearby) >= 2:
                sorted_nearby = sorted(nearby)
                floor = sorted_nearby[0]
                if floor > 0 and (sorted_nearby[1] - floor) / floor < _AMBIGUOUS_MARGIN_PCT:
                    ambig_safe = False

        if not beat_twin_safe and not ambig_safe:
            break

    return beat_twin_safe, ambig_safe


def plan_uscore_windows(
    timestamps_ms: np.ndarray,
    bands: dict[str, np.ndarray],
    duration_ms: int,
    beats_ms: list[int],
    *,
    window_length_ms: int = _WINDOW_LENGTH_MS,
    candidate_step_ms: int = _CANDIDATE_STEP_MS,
    max_windows: int = _MAX_WINDOWS_DEFAULT,
    max_overlap_ms: int = _MAX_OVERLAP_MS,
) -> list[dict]:
    """Plan up to `max_windows` xcorr windows for a captured shape using the
    U-Score method (Method A — shift-and-subtract).

    Args:
        timestamps_ms: 1D array of sample timestamps from the npz.
        bands: dict with keys 'rms_total', 'rms_low', 'rms_mid', 'rms_high'.
        duration_ms: song duration.
        beats_ms: librosa beat onset times in ms (used for local beat period).

    Returns:
        list of dicts, each:
          {
            start_ms, end_ms, length_ms,
            u_score, u_per_band: [t, l, m, h],
            beat_period_ms,
            difficulty,            # backward-compat field; equals u_score
          }
        Sorted by start_ms ascending, ready for direct storage on
        AudioShapeMeta.xcorr_windows.
    """
    if duration_ms <= 0:
        return []
    if len(timestamps_ms) < 2:
        return []

    win_len_bins = window_length_ms // _BIN_MS
    max_end_ms = duration_ms - _END_BUFFER_MS
    if max_end_ms - window_length_ms < _FIRST_START_MS:
        return []

    # Build a uniform 25ms grid covering the full song (used for both reference
    # window slices and the shifted candidate slices).
    grid_ms = np.arange(0, duration_ms, _BIN_MS, dtype=float)
    bands_full_norm: list[np.ndarray] = []
    rms_low_resampled: Optional[np.ndarray] = None
    for key in _BAND_KEYS:
        b = bands.get(key)
        if b is None:
            return []
        squared = _resample_band(timestamps_ms, b, grid_ms)
        bands_full_norm.append(_agc(squared))
        if key == "rms_low":
            # Keep the raw resampled-and-squared rms_low for deriving the
            # silence/onset bands below — we want the same time grid and AGC
            # treatment but different transformations.
            rms_low_resampled = squared

    # Round 10: derived bands. Computed from the same rms_low grid so the
    # window indexing aligns. Both go through _agc independently so each
    # band's AGC scale is internally consistent.
    if rms_low_resampled is not None:
        # Inverse-energy: high during quiet, low during loud. signed_square has
        # already been applied in _resample_band; here we invert in normalized
        # space. Take |rms_low|, normalize by 95th percentile, invert (1 − x),
        # clip to [0, 1], then re-square for amplitude weighting consistency.
        abs_low = np.abs(rms_low_resampled)
        p95 = float(np.percentile(abs_low, 95)) + 1e-6
        inv = 1.0 - np.clip(abs_low / p95, 0.0, 1.0)
        inv_sq = _signed_square(inv)
        bands_full_norm.append(_agc(inv_sq))

        # Onset-derivative: |d/dt rms_low| spikes at any abrupt energy change
        # (loud→quiet or quiet→loud). Use np.diff and pad to keep length
        # aligned with the other bands.
        deriv = np.abs(np.diff(rms_low_resampled, prepend=rms_low_resampled[:1]))
        deriv_sq = _signed_square(deriv)
        bands_full_norm.append(_agc(deriv_sq))

    # Determine the global shift range for the residual matrix. Use the largest
    # local beat period × _BEAT_RANGE so every position has its full ±N-beat
    # search covered. The matrix is built once for the whole song.
    if beats_ms and len(beats_ms) >= 2:
        beat_diffs = np.diff(np.asarray(beats_ms, dtype=float))
        global_beat_ms = float(np.max(beat_diffs))
    else:
        global_beat_ms = _DEFAULT_BEAT_MS_FALLBACK
    max_shift_bins = max(1, int(np.ceil(_BEAT_RANGE * global_beat_ms / _BIN_MS)))

    # One matrix pass: per-band per-position WINDOW uniqueness + per-tick
    # max-band visualization profile.
    per_band_window_uniq, per_tick_max_band = _build_window_uniqueness(
        bands_full_norm, max_shift_bins, win_len_bins,
    )

    # Score every candidate position by reading from the precomputed profile.
    # Cheap: one column lookup + weighted mean per candidate.
    candidate_starts_ms: list[int] = list(
        range(_FIRST_START_MS, max_end_ms - window_length_ms, candidate_step_ms)
    )
    scored: list[dict] = []
    for start_ms in candidate_starts_ms:
        beat_ms = _local_beat_period_ms(beats_ms, start_ms + window_length_ms // 2)
        beat_period_bins = max(1, int(round(beat_ms / _BIN_MS)))
        win_start_bin = start_ms // _BIN_MS
        agg = _window_u_score(per_band_window_uniq, win_start_bin)
        if agg is None:
            continue
        u_score, per_band_values = agg
        # Round 9.5: envelope replaces binary beat-twin / ambiguous-margin gates.
        # Search range is the smaller of the global matrix max and the local
        # ±_BEAT_RANGE in this window's local beat period — we don't need to
        # inspect shifts farther than what the runtime would search.
        env_max_shift_bins = min(
            max_shift_bins,
            max(1, _BEAT_RANGE * beat_period_bins),
            _AMBIGUOUS_SEARCH_MS // _BIN_MS,
        )
        safe_neg_bins, safe_pos_bins = _compute_safe_envelope(
            bands_full_norm, win_start_bin, win_len_bins, env_max_shift_bins,
        )
        safe_neg_ms = -safe_neg_bins * _BIN_MS
        safe_pos_ms = safe_pos_bins * _BIN_MS
        scored.append({
            "start_ms": start_ms,
            "end_ms": start_ms + window_length_ms,
            "length_ms": window_length_ms,
            "u_score": round(u_score, 4),
            "u_per_band": [round(v, 4) for v in per_band_values],
            "beat_period_ms": round(beat_ms, 1),
            "safe_neg_ms": int(safe_neg_ms),
            "safe_pos_ms": int(safe_pos_ms),
            "difficulty": round(u_score, 4),    # backward-compat alias
        })

    if not scored:
        logger.info("U-Score planner: no valid candidate windows for duration=%dms", duration_ms)
        return []

    # Filter: envelope width must clear the minimum, AND U-Score must clear floor.
    # Round 9.5: the envelope subsumes the prior beat_twin_safe / ambig_safe
    # binary gates — a window with a useful safe range in both directions has
    # already implicitly passed both simulated gates.
    eligible = [
        w for w in scored
        if (w["safe_pos_ms"] - w["safe_neg_ms"]) >= _MIN_TOTAL_ENVELOPE_MS
        and w["u_score"] > _MIN_USCORE_KEEP
    ]
    if not eligible:
        # Fallback: take top candidates by U-Score even if they failed gates,
        # so we always have something to evaluate. Tag them so the caller can
        # see they were force-picked.
        scored.sort(key=lambda w: w["u_score"], reverse=True)
        eligible = scored[:max(8, max_windows // 2)]
        for w in eligible:
            w["force_picked"] = True
        logger.info(
            "U-Score planner: no candidates passed gates — force-picking top %d by U-Score",
            len(eligible),
        )

    # Selection rules.
    eligible.sort(key=lambda w: w["u_score"], reverse=True)

    selected: list[dict] = []

    def _overlaps(cand: dict, others: list[dict]) -> bool:
        for s in others:
            # Overlap is the negative gap between the windows.
            overlap = min(cand["end_ms"], s["end_ms"]) - max(cand["start_ms"], s["start_ms"])
            if overlap > max_overlap_ms:
                return True
        return False

    # Mandatory pick: highest-U-Score window with start in [10000, 20000],
    # force-pick even from the full scored pool if no eligible candidate falls
    # in that range.
    early_eligible = [w for w in eligible if _MANDATORY_EARLY_START_MIN <= w["start_ms"] <= _MANDATORY_EARLY_START_MAX]
    if early_eligible:
        selected.append(early_eligible[0])
    else:
        early_pool = [w for w in scored if _MANDATORY_EARLY_START_MIN <= w["start_ms"] <= _MANDATORY_EARLY_START_MAX]
        if early_pool:
            early_pool.sort(key=lambda w: w["u_score"], reverse=True)
            forced = dict(early_pool[0])
            forced["force_picked"] = True
            selected.append(forced)

    # Then fill: at least _MANDATORY_BEFORE_COUNT more windows with start < 40s.
    early_zone = [w for w in eligible if w["start_ms"] < _MANDATORY_BEFORE_MS and w not in selected]
    for w in early_zone:
        if len([s for s in selected if s["start_ms"] < _MANDATORY_BEFORE_MS]) >= 1 + _MANDATORY_BEFORE_COUNT:
            break
        if not _overlaps(w, selected):
            selected.append(w)
    # Force-pick from full scored pool if we still don't have enough early ones.
    if len([s for s in selected if s["start_ms"] < _MANDATORY_BEFORE_MS]) < 1 + _MANDATORY_BEFORE_COUNT:
        backfill_pool = [w for w in scored if w["start_ms"] < _MANDATORY_BEFORE_MS and w not in selected]
        backfill_pool.sort(key=lambda w: w["u_score"], reverse=True)
        for w in backfill_pool:
            if len([s for s in selected if s["start_ms"] < _MANDATORY_BEFORE_MS]) >= 1 + _MANDATORY_BEFORE_COUNT:
                break
            if not _overlaps(w, selected):
                forced = dict(w)
                forced["force_picked"] = True
                selected.append(forced)

    # Greedy fill the rest of the song by U-Score.
    for w in eligible:
        if len(selected) >= max_windows:
            break
        if w in selected:
            continue
        if not _overlaps(w, selected):
            selected.append(w)

    # Sort final list by start_ms for stable iteration.
    selected.sort(key=lambda w: w["start_ms"])

    # Strip internal-only field before returning.
    for w in selected:
        w.pop("win_start_bin", None)

    return selected


def plan_and_time(
    timestamps_ms: np.ndarray,
    bands: dict[str, np.ndarray],
    duration_ms: int,
    beats_ms: list[int],
) -> tuple[list[dict], float]:
    """Convenience wrapper that times the planning. Returns (windows, elapsed_sec)."""
    t0 = time.monotonic()
    windows = plan_uscore_windows(timestamps_ms, bands, duration_ms, beats_ms)
    return windows, time.monotonic() - t0
