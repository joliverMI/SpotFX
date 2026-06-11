"""
SpotFX — xcorr math kernel (pure functions, no app state).

Extracted verbatim from services/auto_offset_service.py so the offline
replay/benchmark harness (bench/) can drive the exact production math.
The only intentional behavior delta vs the original:

  * `xcorr_window` / `xcorr_window_detail` take an explicit `search_ms`
    parameter instead of calling `_xcorr_search_ms()` (which reads
    app_state + setlist_store). The service computes the same value at
    the same point in its loop and passes it in — identical results.
  * `xcorr_window_detail` band fix: the original iterated `range(3)` over
    the 4 stored bands, so the CSV's "high" columns actually contained the
    MID band; it also correlated raw live values (no signed-square)
    against squared stored bands, making detail r's incomparable to sweep
    r's. Now all 4 bands are scored with the same signed-square + AGC
    pipeline the sweep uses (diagnostic-CSV-only blast radius).

Sign convention (matches trigger_engine._effective_offset_ms):
  live is LATE by X ms  →  best_shift = +X  →  offset_ms = -X  →  fires later
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)

XCORR_BIN_MS = 25       # resample resolution (ms)


def agc_normalize(arr: np.ndarray) -> np.ndarray:
    """Per-band AGC: divide by 95th percentile of |arr| so two windows captured
    at different volumes remain comparable. Symmetric on both sides of the
    correlation, so it never biases the winner; only stabilizes when SNR is
    asymmetric. Volume invariance is already mostly handled by the per-window
    z-score below — this is belt-and-suspenders for compressed dynamics.

    Uses `np.partition` for O(N) selection instead of `np.percentile`'s
    O(N log N) sort. Result is bit-identical to `np.percentile(..., 95)` for
    the integer index — no interpolation between adjacent percentiles, which
    is fine here since the AGC scale is then divided into a per-window
    z-score that absorbs any tiny offset.
    """
    if arr.size == 0:
        return arr
    n = arr.size
    k = min(n - 1, max(0, int(n * 0.95)))
    abs_arr = np.abs(arr)
    scale = float(np.partition(abs_arr, k)[k]) + 1e-6
    return arr / scale


def signed_square(arr: np.ndarray) -> np.ndarray:
    # x → x·|x|: amplitude-weighted, sign-preserving. Loud excursions dominate
    # downstream Pearson r; quiet noise-floor wiggles contribute proportionally
    # less. Z-norm downstream still works (mean/std of squared values are valid).
    return arr * np.abs(arr)


def difficulty_score(window_rms: np.ndarray, song_rms: np.ndarray) -> float:
    """
    How much dynamic content is in this window, normalised 0–1.
    Uses coefficient of variation (std/mean) of the window vs. the song-global CV.
    A flat/silent section → 0 (unreliable for alignment).
    A window as dynamic as the whole song → 1.
    A window more dynamic than average → capped at 1.
    """
    if len(window_rms) < 2:
        return 0.0
    w_mean = float(window_rms.mean())
    if w_mean < 1e-9:
        return 0.0
    cv_window = float(window_rms.std()) / w_mean

    g_mean = float(song_rms.mean())
    if g_mean < 1e-9:
        return 0.0
    cv_global = float(song_rms.std()) / g_mean
    if cv_global < 1e-9:
        return 0.0

    return float(min(1.0, cv_window / cv_global))


def eval_at_shift(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    shift_ms: int,
) -> Optional[float]:
    """
    Evaluate multi-band Pearson r at a SPECIFIC shift (no search).
    shift_ms > 0 means the live signal is tested shifted right by shift_ms.
    Returns simple-mean correlation across all 4 bands, or None if all flat.

    stored_bands: [rms_total, rms_low, rms_mid, rms_high] arrays from npz.
    frames: [(ts, rms_total, rms_low, rms_mid, rms_high), ...] from live capture.

    Round 5 reverted from variance-weighted combine to a simple mean: each
    band gets equal vote. Forces all 4 bands (including melody-carrying mid)
    to agree, which makes beat-tile twins much harder to fool the matcher
    than when one high-variance band (typically rms_high during repetitive
    hi-hat patterns) dominated the score.
    """
    bins = np.arange(win_start, win_end, XCORR_BIN_MS, dtype=float)
    live_ts = np.array([f[0] for f in frames], dtype=float)
    live_bins = bins + shift_ms

    r_values: list[float] = []
    for band_idx in range(len(stored_bands)):
        template = agc_normalize(np.interp(bins, stored_ts, stored_bands[band_idx]))
        if template.std() < 1e-6:
            continue
        template_norm = (template - template.mean()) / template.std()

        live_rms = signed_square(
            np.array([f[1 + band_idx] for f in frames], dtype=float)
        )
        signal = agc_normalize(np.interp(live_bins, live_ts, live_rms, left=0.0, right=0.0))
        if signal.std() < 1e-6:
            continue
        signal_norm = (signal - signal.mean()) / signal.std()
        r_values.append(float(np.dot(template_norm, signal_norm)) / len(bins))

    if not r_values:
        return None
    return sum(r_values) / len(r_values)


def xcorr_window(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    *,
    search_ms: int,
    old_r: Optional[float] = None,
    tempo_bpm: Optional[float] = None,
) -> Optional[tuple[int, float]]:
    """
    Multi-band cross-correlation of stored shape window against live audio.
    Returns (offset_ms, avg_pearson_r) or None if below threshold.

    Coarse-then-fine sweep:
      1. Coarse: step xcorr_coarse_step_ms across the full ±search range,
         keep top-K candidates by averaged r.
      2. Fine: refine each candidate with ±150 ms at XCORR_BIN_MS resolution.
         Keep the global best.

    The search range itself is mix-aware (derived by the caller from captured
    vs polled duration plus a buffer). When the range is wide, an adaptive
    threshold rejects ambiguous matches.

    Sign convention: offset_ms = -best_shift
      shift > 0  →  live is LATE by |shift| ms  →  offset < 0  →  fires later  ✓
    """
    bins = np.arange(win_start, win_end, XCORR_BIN_MS, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    # band_info: (band_idx, template_norm). Round 5 reverted from variance-
    # weighted to simple-mean band combine, so per-band variance is no longer
    # tracked — each of the 4 bands gets equal vote in score_at.
    band_info: list[tuple[int, np.ndarray]] = []
    for band_idx, stored_rms in enumerate(stored_bands):
        template = agc_normalize(np.interp(bins, stored_ts, stored_rms))
        if template.std() < 1e-6:
            continue
        band_info.append((band_idx, (template - template.mean()) / template.std()))
    if not band_info:
        return None

    live_arrays: dict[int, np.ndarray] = {}
    for band_idx, _ in band_info:
        live_arrays[band_idx] = agc_normalize(
            signed_square(np.array([f[1 + band_idx] for f in frames], dtype=float))
        )

    coarse_step = max(XCORR_BIN_MS, settings.xcorr_coarse_step_ms)

    # Pre-resample live signals onto a fine grid covering the full search range.
    # Coarse + fine shifts are integer multiples of XCORR_BIN_MS, so per-shift
    # signal extraction reduces to integer slicing — no per-shift np.interp.
    # That eliminates 720+ interp calls per window (was the dominant cost).
    grid_start = win_start - search_ms
    grid_end   = win_end   + search_ms + XCORR_BIN_MS
    grid_ts    = np.arange(grid_start, grid_end, XCORR_BIN_MS, dtype=float)
    n_grid     = len(grid_ts)
    live_grid: dict[int, np.ndarray] = {}
    for band_idx, _ in band_info:
        live_grid[band_idx] = np.interp(
            grid_ts, live_ts, live_arrays[band_idx], left=0.0, right=0.0
        )
    # Anchor: bins[0] sits at this index in the grid; shift adds shift/XCORR_BIN_MS bins.
    base_idx_at_zero = int(round((win_start - grid_start) / XCORR_BIN_MS))

    def score_at(shift: int) -> Optional[float]:
        offset = base_idx_at_zero + int(shift // XCORR_BIN_MS)
        # Out-of-range shifts shouldn't happen (grid sized for ±search_ms) but
        # guard defensively to avoid a numpy slice that silently underfills.
        if offset < 0 or offset + n_bins > n_grid:
            return None
        r_sum = 0.0
        n_valid = 0
        for band_idx, template_norm in band_info:
            signal = live_grid[band_idx][offset : offset + n_bins]
            if signal.std() < 1e-6:
                continue
            signal_norm = (signal - signal.mean()) / signal.std()
            r_sum += float(np.dot(template_norm, signal_norm)) / n_bins
            n_valid += 1
        return (r_sum / n_valid) if n_valid else None

    # ── Coarse pass ──────────────────────────────────────────────────────────
    coarse_results: list[tuple[float, int]] = []
    for shift in range(-search_ms, search_ms + 1, coarse_step):
        r = score_at(shift)
        if r is not None:
            coarse_results.append((r, shift))
    if not coarse_results:
        return None
    coarse_results.sort(reverse=True)  # by r desc
    top_k = max(1, settings.xcorr_top_k_refine)
    candidates = coarse_results[:top_k]

    # ── Fine pass (refine each top-K) ────────────────────────────────────────
    fine_radius = 150
    best_r, best_shift = -float("inf"), 0
    second_r = -float("inf")
    for _, c_shift in candidates:
        for shift in range(c_shift - fine_radius, c_shift + fine_radius + 1, XCORR_BIN_MS):
            r = score_at(shift)
            if r is None:
                continue
            if r > best_r:
                second_r = best_r
                best_r, best_shift = r, shift
            elif r > second_r:
                second_r = r

    if best_r == -float("inf"):
        return None

    # Adaptive thresholds for wide searches.
    threshold = settings.xcorr_global_threshold
    require_margin = 0.0
    if search_ms > settings.xcorr_wide_threshold_ms:
        threshold = max(threshold, settings.xcorr_wide_min_r)
        require_margin = settings.xcorr_wide_top1_margin

    if best_r < threshold:
        logger.info(
            "xcorr reject: window [%d–%d]ms best r=%.2f below threshold %.2f (search=±%dms)",
            win_start, win_end, best_r, threshold, search_ms,
        )
        return None
    # Margin check is skipped in two cases:
    #   1. top1 is itself high-confidence (xcorr_high_confidence_r) — strong
    #      enough on its own, twin peaks just reflect periodic music.
    #   2. OLD baseline is provably wrong (anti-correlated, r<0) — any peak
    #      that cleared `threshold` is better than what we have. The
    #      multi-window save gate will refuse to persist this until another
    #      window agrees, so letting the measurement through is safe.
    if (require_margin > 0 and second_r > -float("inf")
            and best_r < settings.xcorr_high_confidence_r
            and (old_r is None or old_r >= 0.0)
            and (best_r - second_r) < require_margin):
        logger.info(
            "xcorr reject: window [%d–%d]ms ambiguous — top1=%.2f top2=%.2f margin<%.2f (search=±%dms)",
            win_start, win_end, best_r, second_r, require_margin, search_ms,
        )
        return None

    # Beat-twin rejection. When tempo is known, explicitly score the same
    # template at best_shift ± n*beat_period for n ∈ {1, 2, 3, 4}. A periodic
    # passage's beat-tile twin matches strongly there; if any twin's r is
    # within `xcorr_beat_twin_margin` of best_r, the window is genuinely
    # ambiguous between two beat-aligned offsets and we should fall back to
    # OLD rather than commit to the wrong tile. Mirrors the anchor's
    # beat-twin penalty so both calibrators agree on what counts as
    # ambiguous in periodic music.
    if tempo_bpm and tempo_bpm > 0 and best_r < settings.xcorr_high_confidence_r:
        beat_period_ms = 60_000.0 / float(tempo_bpm)
        twin_margin = float(getattr(settings, "xcorr_beat_twin_margin", 0.10))
        for n in (1, 2, 3, 4):
            for sign in (-1, 1):
                twin_shift = best_shift + sign * int(round(n * beat_period_ms))
                if abs(twin_shift) > search_ms:
                    continue
                twin_r = score_at(twin_shift)
                if twin_r is None:
                    continue
                if best_r - twin_r < twin_margin:
                    logger.info(
                        "xcorr reject: window [%d–%d]ms beat-twin — best=%.2f at %+dms vs twin=%.2f at %+dms (%+d beats, margin<%.2f)",
                        win_start, win_end, best_r, best_shift,
                        twin_r, twin_shift, sign * n, twin_margin,
                    )
                    return None

    return (-best_shift, round(best_r, 3))


# DIAGNOSTIC CSV ──────────────────────────────────────────────────────────────
@dataclass
class XcorrDetail:
    """Per-band r at the winning shift and per-band independent peak shifts."""
    r_total: float
    r_low: float
    r_mid: float
    r_high: float
    peak_total_ms: int
    peak_low_ms: int
    peak_mid_ms: int
    peak_high_ms: int


def xcorr_window_detail(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    winning_shift: int,
    *,
    search_ms: int,
) -> XcorrDetail:
    """
    Compute per-band r at the winning shift and per-band independent peak shifts.
    Only called when xcorr_csv_logging is True.

    Live values go through the same signed-square + AGC pipeline as the sweep
    so per-band r's are directly comparable to the sweep's averaged r.

    winning_shift: raw shift in ms (positive = live is late).
                   Pass -offset_ms to convert from offset sign convention.
    """
    bins   = np.arange(win_start, win_end, XCORR_BIN_MS, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    per_band_r:    list[float] = []
    per_band_peak: list[int]   = []

    for band_idx in range(len(stored_bands)):
        template = agc_normalize(np.interp(bins, stored_ts, stored_bands[band_idx]))
        if template.std() < 1e-6:
            per_band_r.append(0.0)
            per_band_peak.append(0)
            continue
        template_norm = (template - template.mean()) / template.std()

        live_rms = agc_normalize(signed_square(
            np.array([f[1 + band_idx] for f in frames], dtype=float)
        ))

        # r at the winning shift
        signal = np.interp(bins + winning_shift, live_ts, live_rms, left=0.0, right=0.0)
        if signal.std() < 1e-6:
            per_band_r.append(0.0)
        else:
            signal_norm = (signal - signal.mean()) / signal.std()
            per_band_r.append(round(float(np.dot(template_norm, signal_norm)) / n_bins, 4))

        # independent peak for this band alone
        best_r     = -np.inf
        best_shift = 0
        for shift in range(-search_ms, search_ms + 1, XCORR_BIN_MS):
            sig = np.interp(bins + shift, live_ts, live_rms, left=0.0, right=0.0)
            if sig.std() < 1e-6:
                continue
            sn = (sig - sig.mean()) / sig.std()
            r  = float(np.dot(template_norm, sn)) / n_bins
            if r > best_r:
                best_r     = r
                best_shift = shift
        per_band_peak.append(-best_shift)  # shift → offset sign convention

    return XcorrDetail(
        r_total=per_band_r[0], r_low=per_band_r[1],
        r_mid=per_band_r[2], r_high=per_band_r[3],
        peak_total_ms=per_band_peak[0], peak_low_ms=per_band_peak[1],
        peak_mid_ms=per_band_peak[2], peak_high_ms=per_band_peak[3],
    )
# END DIAGNOSTIC CSV ──────────────────────────────────────────────────────────
