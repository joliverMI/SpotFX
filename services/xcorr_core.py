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


# ── Phase 2: FFT fast-NCC sweep ───────────────────────────────────────────────
def _nanmean_rows(stacked: np.ndarray) -> np.ndarray:
    """Column-wise mean ignoring NaNs, NaN where every row is NaN — without
    numpy's noisy empty-slice RuntimeWarning."""
    valid = np.isfinite(stacked)
    cnt = valid.sum(axis=0)
    s = np.where(valid, stacked, 0.0).sum(axis=0)
    return np.where(cnt > 0, s / np.maximum(cnt, 1), np.nan)


def ncc_sliding(template_norm: np.ndarray, search: np.ndarray,
                min_std: float = 1e-6) -> np.ndarray:
    """Exact z-scored Pearson r of `template_norm` (already zero-mean,
    unit-std, length n) against EVERY length-n window of `search`, in one
    pass (Lewis 1995 running-sums normalization).

    Because the template is zero-mean:
        dot(t, zscore(s_k)) = (Σ t·s_k) / σ_k
    so r[k] = c[k] / (n·σ_k), with c via a single FFT correlation and σ_k
    from cumulative sums of s and s². Windows with σ_k < min_std return NaN
    (mirrors the loop's flat-slice skip).
    """
    from scipy.signal import correlate

    t = np.asarray(template_norm, dtype=np.float64)
    s = np.asarray(search, dtype=np.float64)
    n = len(t)
    if len(s) < n or n == 0:
        return np.empty(0)
    c = correlate(s, t, mode="valid", method="auto")

    cs1 = np.concatenate(([0.0], np.cumsum(s)))
    cs2 = np.concatenate(([0.0], np.cumsum(s * s)))
    s1 = cs1[n:] - cs1[:-n]
    s2 = cs2[n:] - cs2[:-n]
    mean = s1 / n
    var = np.maximum(s2 / n - mean * mean, 0.0)
    sigma = np.sqrt(var)

    r = np.full(len(c), np.nan)
    ok = sigma >= min_std
    r[ok] = c[ok] / (n * sigma[ok])
    return r


@dataclass
class Landscape:
    """Full-resolution correlation landscape of one window sweep."""
    shifts_ms: np.ndarray          # shift at each index (25ms apart)
    r: np.ndarray                  # multi-band mean r at each shift (NaN = invalid)
    peaks: list[tuple[int, float]]  # [(shift_ms, r)] top-k, ≥min_sep apart, r desc
    comb_period_ms: Optional[float]
    comb_strength: float

    @property
    def top1(self) -> Optional[tuple[int, float]]:
        return self.peaks[0] if self.peaks else None

    @property
    def top2(self) -> Optional[tuple[int, float]]:
        return self.peaks[1] if len(self.peaks) > 1 else None

    @property
    def margin(self) -> float:
        if len(self.peaks) > 1:
            return self.peaks[0][1] - self.peaks[1][1]
        return float("inf")

    def r_at(self, shift_ms: int) -> Optional[float]:
        """r at the grid shift nearest shift_ms (None when out of range/NaN)."""
        if len(self.shifts_ms) == 0:
            return None
        idx = int(round((shift_ms - self.shifts_ms[0]) / XCORR_BIN_MS))
        if idx < 0 or idx >= len(self.r):
            return None
        v = self.r[idx]
        return float(v) if np.isfinite(v) else None


def analyze_landscape(shifts_ms: np.ndarray, r: np.ndarray, *,
                      top_k: Optional[int] = None,
                      min_sep_ms: Optional[int] = None,
                      comb_lag_min_ms: Optional[int] = None,
                      comb_lag_max_ms: Optional[int] = None) -> Landscape:
    """Peak picking with real separation + comb/periodicity detection.

    Peaks: scipy.signal.find_peaks with `distance`=min_sep, so top1−top2
    margin compares genuinely distinct peaks (the legacy fine-pass "second_r"
    was usually the 25ms shoulder of the same peak → margin≈0 always).

    Comb: autocorrelation of (r − mean). A strongly periodic landscape
    (beat-tile twins) shows a dominant lag in [comb_lag_min, comb_lag_max];
    `comb_strength` = a[lag]/a[0]. Works without librosa tempo.
    """
    from scipy.signal import find_peaks

    top_k = top_k if top_k is not None else int(getattr(settings, "xcorr_peak_top_k", 5))
    min_sep_ms = min_sep_ms if min_sep_ms is not None else int(getattr(settings, "xcorr_peak_min_sep_ms", 350))
    comb_lag_min_ms = comb_lag_min_ms if comb_lag_min_ms is not None else int(getattr(settings, "xcorr_comb_lag_min_ms", 250))
    comb_lag_max_ms = comb_lag_max_ms if comb_lag_max_ms is not None else int(getattr(settings, "xcorr_comb_lag_max_ms", 1500))

    r_clean = np.where(np.isfinite(r), r, -np.inf)
    distance = max(1, min_sep_ms // XCORR_BIN_MS)
    idx, _ = find_peaks(r_clean, distance=distance)
    # find_peaks excludes endpoints; the true best can sit at the search edge.
    for edge in (0, len(r_clean) - 1):
        if len(r_clean) > 1 and np.isfinite(r[edge]):
            neighbor = r_clean[1] if edge == 0 else r_clean[-2]
            if r_clean[edge] > neighbor:
                idx = np.append(idx, edge)
    cand = sorted(((int(shifts_ms[i]), float(r[i])) for i in idx
                   if np.isfinite(r[i])), key=lambda p: -p[1])
    # Enforce separation greedily across the merged (peaks+edges) list.
    peaks: list[tuple[int, float]] = []
    for shift, rv in cand:
        if all(abs(shift - p[0]) >= min_sep_ms for p in peaks):
            peaks.append((shift, rv))
        if len(peaks) >= top_k:
            break

    # Comb/periodicity on the mean-removed landscape.
    comb_period_ms: Optional[float] = None
    comb_strength = 0.0
    finite = np.isfinite(r)
    if finite.sum() >= 8:
        x = np.where(finite, r, np.nanmean(r[finite]))
        x = x - x.mean()
        a = np.correlate(x, x, mode="full")[len(x) - 1:]
        if a[0] > 1e-12:
            lag_lo = max(1, comb_lag_min_ms // XCORR_BIN_MS)
            lag_hi = min(len(a) - 1, comb_lag_max_ms // XCORR_BIN_MS)
            if lag_hi > lag_lo:
                lags = np.arange(lag_lo, lag_hi + 1)
                best_lag = lags[np.argmax(a[lag_lo:lag_hi + 1])]
                comb_period_ms = float(best_lag * XCORR_BIN_MS)
                comb_strength = float(a[best_lag] / a[0])

    return Landscape(shifts_ms=shifts_ms, r=r, peaks=peaks,
                     comb_period_ms=comb_period_ms, comb_strength=comb_strength)


def xcorr_window_full(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    *,
    search_ms: Optional[int] = None,
    search_lo_ms: Optional[int] = None,
    search_hi_ms: Optional[int] = None,
) -> Optional[Landscape]:
    """FFT fast-NCC: multi-band mean Pearson r at EVERY 25ms shift.
    Symmetric form (`search_ms` → shifts ∈ [−s, +s]) is grid-identical to
    `xcorr_window`'s score_at(). Phase 4's search ladder passes explicit
    shift-domain bounds (`search_lo_ms`/`search_hi_ms`) for centered or
    asymmetric ranges (a centered OFFSET range [c−span, c+span] is the
    shift range [−c−span, −c+span])."""
    if search_lo_ms is None or search_hi_ms is None:
        if search_ms is None:
            raise ValueError("need search_ms or search_lo_ms+search_hi_ms")
        search_lo_ms, search_hi_ms = -int(search_ms), int(search_ms)
    bins = np.arange(win_start, win_end, XCORR_BIN_MS, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    band_info: list[tuple[int, np.ndarray]] = []
    for band_idx, stored_rms in enumerate(stored_bands):
        template = agc_normalize(np.interp(bins, stored_ts, stored_rms))
        if template.std() < 1e-6:
            continue
        band_info.append((band_idx, (template - template.mean()) / template.std()))
    if not band_info:
        return None

    grid_start = win_start + search_lo_ms
    grid_end = win_end + search_hi_ms + XCORR_BIN_MS
    grid_ts = np.arange(grid_start, grid_end, XCORR_BIN_MS, dtype=float)
    base_idx_at_zero = int(round((win_start - grid_start) / XCORR_BIN_MS))

    r_bands = []
    for band_idx, template_norm in band_info:
        live_rms = agc_normalize(
            signed_square(np.array([f[1 + band_idx] for f in frames], dtype=float))
        )
        live_grid = np.interp(grid_ts, live_ts, live_rms, left=0.0, right=0.0)
        r_bands.append(ncc_sliding(template_norm, live_grid))
    if not r_bands or len(r_bands[0]) == 0:
        return None

    stacked = np.vstack(r_bands)
    r = _nanmean_rows(stacked)   # per-shift mean over non-flat bands
    shifts = (np.arange(len(r)) - base_idx_at_zero) * XCORR_BIN_MS
    return analyze_landscape(shifts, r)


def xcorr_window_fft(
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
    """Drop-in replacement for `xcorr_window` using the FFT landscape.
    Same return contract: (offset_ms, r) or None."""
    result, _ = xcorr_window_fft_full(
        stored_ts, stored_bands, frames, win_start, win_end,
        search_ms=search_ms, old_r=old_r, tempo_bpm=tempo_bpm,
    )
    return result


def xcorr_window_fft_full(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    *,
    search_ms: Optional[int] = None,
    search_lo_ms: Optional[int] = None,
    search_hi_ms: Optional[int] = None,
    old_r: Optional[float] = None,
    tempo_bpm: Optional[float] = None,
) -> tuple[Optional[tuple[int, float]], Optional["Landscape"]]:
    """FFT sweep returning BOTH the gated (offset_ms, r) result and the full
    Landscape (for evidence accumulation). Gates read from the landscape:
    the wide-search margin compares genuinely separated peaks, and the comb
    gate rejects beat-twin ambiguity even without librosa tempo. The
    tempo-based twin check is retained alongside for now."""
    if search_lo_ms is None or search_hi_ms is None:
        if search_ms is None:
            raise ValueError("need search_ms or search_lo_ms+search_hi_ms")
        search_lo_ms, search_hi_ms = -int(search_ms), int(search_ms)
    half_span = (search_hi_ms - search_lo_ms) // 2
    landscape = xcorr_window_full(
        stored_ts, stored_bands, frames, win_start, win_end,
        search_lo_ms=search_lo_ms, search_hi_ms=search_hi_ms,
    )
    if landscape is None or landscape.top1 is None:
        return None, landscape
    best_shift, best_r = landscape.top1

    threshold = settings.xcorr_global_threshold
    require_margin = 0.0
    if half_span > settings.xcorr_wide_threshold_ms:
        threshold = max(threshold, settings.xcorr_wide_min_r)
        require_margin = settings.xcorr_wide_top1_margin

    if best_r < threshold:
        logger.info(
            "xcorr reject: window [%d–%d]ms best r=%.2f below threshold %.2f (search=[%d,%d]ms, fft)",
            win_start, win_end, best_r, threshold, search_lo_ms, search_hi_ms,
        )
        return None, landscape

    if (require_margin > 0 and landscape.top2 is not None
            and best_r < settings.xcorr_high_confidence_r
            and (old_r is None or old_r >= 0.0)
            and landscape.margin < require_margin):
        logger.info(
            "xcorr reject: window [%d–%d]ms ambiguous — top1=%.2f@%+dms top2=%.2f@%+dms margin<%.2f (search=[%d,%d]ms, fft)",
            win_start, win_end, best_r, best_shift,
            landscape.top2[1], landscape.top2[0], require_margin, search_lo_ms, search_hi_ms,
        )
        return None, landscape

    # Comb gate: a periodic landscape means beat-tile twins. Require top1 to
    # beat the best twin at ±1..4 comb periods by the beat-twin margin.
    comb_min = float(getattr(settings, "xcorr_comb_min_strength", 0.35))
    twin_margin = float(getattr(settings, "xcorr_beat_twin_margin", 0.10))
    if (landscape.comb_period_ms and landscape.comb_strength >= comb_min
            and best_r < settings.xcorr_high_confidence_r):
        for n in (1, 2, 3, 4):
            for sign in (-1, 1):
                twin_r = landscape.r_at(best_shift + sign * int(round(n * landscape.comb_period_ms)))
                if twin_r is None:
                    continue
                if best_r - twin_r < twin_margin:
                    logger.info(
                        "xcorr reject: window [%d–%d]ms comb-twin — best=%.2f at %+dms vs twin=%.2f at %+d periods (comb=%.0fms str=%.2f)",
                        win_start, win_end, best_r, best_shift, twin_r,
                        sign * n, landscape.comb_period_ms, landscape.comb_strength,
                    )
                    return None, landscape

    # Tempo-based twin check retained (benchmark decides which retires).
    if tempo_bpm and tempo_bpm > 0 and best_r < settings.xcorr_high_confidence_r:
        beat_period_ms = 60_000.0 / float(tempo_bpm)
        for n in (1, 2, 3, 4):
            for sign in (-1, 1):
                twin_shift = best_shift + sign * int(round(n * beat_period_ms))
                if twin_shift < search_lo_ms or twin_shift > search_hi_ms:
                    continue
                twin_r = landscape.r_at(twin_shift)
                if twin_r is None:
                    continue
                if best_r - twin_r < twin_margin:
                    logger.info(
                        "xcorr reject: window [%d–%d]ms beat-twin — best=%.2f at %+dms vs twin=%.2f at %+dms (%+d beats, margin<%.2f, fft)",
                        win_start, win_end, best_r, best_shift,
                        twin_r, twin_shift, sign * n, twin_margin,
                    )
                    return None, landscape

    return (-best_shift, round(best_r, 3)), landscape


# ── Phase 3: progressive early matching ───────────────────────────────────────
@dataclass
class ProgressiveMatch:
    offset_ms: int
    r: float
    quality: float                 # r × min(1, span/8s) — short takes earn less
    span_ms: int                   # live template span after silence trim
    landscape: Landscape           # shifts_ms holds OFFSETS here (not shifts)


def progressive_match(
    frames: list[tuple[int, float, float, float, float]],
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    *,
    t_now_ms: int,
    search_ms: int,
    center_offset_ms: int = 0,
    min_cv: Optional[float] = None,
    min_r: Optional[float] = None,
    min_dominance: Optional[float] = None,
) -> Optional[ProgressiveMatch]:
    """Match ALL captured audio so far against the stored shape — the
    reverse direction of the window sweep: the LIVE take (silence-trimmed)
    is the fixed z-scored template, slid across the stored signal with
    per-position normalization via the same ncc_sliding kernel.

    Designed for song starts: runs every ~1.5s from ~2.5s of capture, so a
    lock can land well before the first planned window (9s+). Quiet intros
    fail the CV gate and simply retry next tick — the graceful-wait
    behavior slow-start songs need. Cut-in/blend starts are handled by the
    offset-domain search range.

    Returns a ProgressiveMatch (offset in the standard convention: stored
    position − live clock; cut-in of C ⇒ +C) or None when any strict early
    gate fails.
    """
    min_cv = min_cv if min_cv is not None else float(getattr(settings, "xcorr_progressive_min_cv", 0.25))
    min_r = min_r if min_r is not None else float(getattr(settings, "xcorr_progressive_min_r", 0.65))
    min_dominance = min_dominance if min_dominance is not None else float(getattr(settings, "xcorr_progressive_dominance", 0.12))

    if not frames:
        return None
    totals = np.array([f[1] for f in frames], dtype=float)
    ts = np.array([f[0] for f in frames], dtype=float)
    # Song-onset trim. The capture's head can contain the PREVIOUS track's
    # tail (and the stored shape's head carries the same ring-buffer
    # pre-roll), which matches itself at offset 0 with r≈1.0 — observed.
    # Start the template at the END of the LAST ≥1.5s quiet gap instead of
    # the first non-silent frame: pollution → gap → song trims to the song;
    # gapless starts (cut-ins/blends) keep the full take as before.
    peak = float(totals.max())
    if peak < 1e-9:
        return None
    quiet = totals < 0.05 * peak
    live_idx = int(np.argmax(~quiet))   # first non-silent (fallback)
    gap_start = None
    for i in range(live_idx, len(frames)):
        if quiet[i]:
            if gap_start is None:
                gap_start = i
        else:
            if gap_start is not None and ts[i] - ts[gap_start] >= 1500:
                live_idx = i            # song onset after a real gap
            gap_start = None
    t0 = float(ts[live_idx])
    span_ms = int(t_now_ms - t0)
    if span_ms < 3500:
        return None

    # CV gate on the raw total band within the template span — a quiet/flat
    # intro carries no alignment information yet; retry next tick.
    seg = totals[(ts >= t0) & (ts <= t_now_ms)]
    if len(seg) < 4 or seg.mean() < 1e-9:
        return None
    if float(seg.std()) / float(seg.mean()) < min_cv:
        return None

    # Live template bins [t0, t_now) — fixed, z-scored per band.
    bins = np.arange(t0, t_now_ms, XCORR_BIN_MS, dtype=float)
    if len(bins) < 8:
        return None

    # Structure gate: a sparse template (silence + one transient) correlates
    # near-perfectly with ANY similar transient — observed as a degenerate
    # r=1.00 match at the wrong position on a 2.5s quiet intro. Require a
    # meaningful fraction of template bins to carry signal so the take has
    # extended structure worth trusting.
    total_template = np.interp(bins, ts, totals, left=0.0, right=0.0)
    t_peak = float(total_template.max())
    if t_peak < 1e-9:
        return None
    active_frac = float((total_template >= 0.15 * t_peak).mean())
    if active_frac < 0.20:
        return None

    # Stored search grid: candidate stored positions p for the template
    # start, offset = p − t0 ∈ center ± search (Phase 4 ladder/cut-in memory
    # centers the range; default center 0).
    grid_start = t0 + center_offset_ms - search_ms
    grid_end = t0 + center_offset_ms + search_ms + (bins[-1] - bins[0]) + XCORR_BIN_MS
    grid_ts = np.arange(grid_start, grid_end, XCORR_BIN_MS, dtype=float)

    r_bands = []
    for band_idx in range(len(stored_bands)):
        live_rms = agc_normalize(signed_square(
            np.array([f[1 + band_idx] for f in frames], dtype=float)))
        template = np.interp(bins, ts, live_rms, left=0.0, right=0.0)
        if template.std() < 1e-6:
            continue
        template_norm = (template - template.mean()) / template.std()
        stored_grid = np.interp(grid_ts, stored_ts, stored_bands[band_idx])
        r_bands.append(ncc_sliding(template_norm, stored_grid))
    if not r_bands or len(r_bands[0]) == 0:
        return None

    r = _nanmean_rows(np.vstack(r_bands))
    offsets = (grid_ts[: len(r)] - t0)   # offset = stored position − live clock
    landscape = analyze_landscape(offsets, r)
    if landscape.top1 is None:
        return None
    best_offset, best_r = landscape.top1

    # Stored-head exclusion: the stored shape's first seconds can contain
    # ring-buffer pre-roll (the previous track's tail), which a polluted
    # live head matches at offset≈0 with r≈1.0. Require the matched stored
    # segment to extend well past that unreliable region — the same "skip
    # the first 5s" stance both production calibrators already take. Near-
    # zero offsets therefore can't lock before ~7s of capture; cut-ins
    # (matched mid-song) are unaffected.
    head_ms = int(getattr(settings, "anchor_min_timestamp_ms", 5000))
    if best_offset + t_now_ms < head_ms + 2000:
        return None

    if best_r < min_r:
        return None
    if landscape.top2 is not None and landscape.margin < min_dominance:
        return None
    # Comb gate — strict for early locks (no high-confidence skip): a
    # periodic landscape means the take could sit on any beat tile.
    comb_min = float(getattr(settings, "xcorr_comb_min_strength", 0.35))
    twin_margin = float(getattr(settings, "xcorr_beat_twin_margin", 0.10))
    if landscape.comb_period_ms and landscape.comb_strength >= comb_min:
        for n in (1, 2, 3, 4):
            for sign in (-1, 1):
                twin_r = landscape.r_at(int(best_offset + sign * round(n * landscape.comb_period_ms)))
                if twin_r is not None and best_r - twin_r < twin_margin:
                    return None

    quality = round(float(best_r) * min(1.0, span_ms / 8000.0), 3)
    return ProgressiveMatch(
        offset_ms=int(best_offset), r=round(float(best_r), 3),
        quality=quality, span_ms=span_ms, landscape=landscape,
    )


# ── Phase 5: mismatch spike extraction ────────────────────────────────────────
def mismatch_spike(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    *,
    engine_offset_ms: int,
    t_now_ms: int,
    lookback_ms: int = 15000,
    halfwin_ms: int = 2500,
    smooth_bins: int = 3,
) -> Optional[tuple[int, int, int, float]]:
    """Locate the strongest matcher-view |z-diff| cluster over the recent
    live span at the engine's current offset — the highest-information
    location for a corrective measurement when a wrong lock is suspected
    (a transient present in one signal but unaligned in the other would
    cancel under correct alignment; its residual marks a distinctive spot).

    Returns (win_start, win_end, spike_ms, strength) in STORED-shape time
    — directly consumable as a dynamically planned window — or None when
    the span is flat. Normalization mirrors eval_at_shift exactly
    (signed-square → 25ms bins → AGC → z-score, live sampled at
    bins+shift), which is also what the debug page's diff graph draws.
    """
    shift = -int(engine_offset_ms)
    end = min(float(t_now_ms + engine_offset_ms), float(stored_ts[-1]))
    start = max(float(stored_ts[0]), end - lookback_ms)
    if end - start < 2000:
        return None
    bins = np.arange(start, end, XCORR_BIN_MS, dtype=float)
    if len(bins) < 8:
        return None
    live_ts = np.array([f[0] for f in frames], dtype=float)

    diff_sum = np.zeros(len(bins))
    n_valid = 0
    for band_idx in range(len(stored_bands)):
        template = agc_normalize(np.interp(bins, stored_ts, stored_bands[band_idx]))
        if template.std() < 1e-6:
            continue
        z_t = (template - template.mean()) / template.std()
        live_rms = signed_square(
            np.array([f[1 + band_idx] for f in frames], dtype=float))
        live = agc_normalize(np.interp(bins + shift, live_ts, live_rms,
                                       left=0.0, right=0.0))
        if live.std() < 1e-6:
            continue
        z_l = (live - live.mean()) / live.std()
        diff_sum += np.abs(z_l - z_t)
        n_valid += 1
    if n_valid == 0:
        return None
    d = diff_sum / n_valid
    # 3-bin (75ms) smooth — same de-flicker the debug graph applies, so the
    # picked spike matches what the user sees.
    if smooth_bins > 1 and len(d) > smooth_bins:
        kernel = np.ones(smooth_bins) / smooth_bins
        d = np.convolve(d, kernel, mode="same")

    # Cluster pick: prefer a SUSTAINED spike region (sliding 500ms sum) over
    # a single noisy bin.
    cw = max(1, 500 // XCORR_BIN_MS)
    if len(d) <= cw:
        centers = [int(np.argmax(d))]
    else:
        sums = np.convolve(d, np.ones(cw), mode="valid")
        order = np.argsort(sums)[::-1]
        centers = [int(order[0] + cw // 2)]
        # Second-best cluster ≥ halfwin away (retry target when the best
        # lands on an uninformative stored region).
        for k in order[1:]:
            c = int(k + cw // 2)
            if abs(c - centers[0]) * XCORR_BIN_MS >= halfwin_ms:
                centers.append(c)
                break

    stored_rms_diff = stored_bands[1]   # squared rms_low — difficulty band
    min_diff = float(getattr(settings, "xcorr_starting_threshold", 0.15))
    for c in centers:
        spike_ms = int(bins[min(c, len(bins) - 1)])
        win_start = max(0, spike_ms - halfwin_ms)
        win_end = min(int(stored_ts[-1]), spike_ms + halfwin_ms)
        if win_end - win_start < 2000:
            continue
        w_bins = np.arange(win_start, win_end, XCORR_BIN_MS, dtype=float)
        w_tpl = np.interp(w_bins, stored_ts, stored_rms_diff)
        if difficulty_score(w_tpl, stored_rms_diff) >= min_diff:
            return (win_start, win_end, spike_ms,
                    round(float(d[min(c, len(d) - 1)]), 3))
    # Fall back to the best cluster even if low-difficulty — the downstream
    # gates make a useless window harmless (it just costs one sweep).
    spike_ms = int(bins[min(centers[0], len(bins) - 1)])
    win_start = max(0, spike_ms - halfwin_ms)
    win_end = min(int(stored_ts[-1]), spike_ms + halfwin_ms)
    if win_end - win_start < 2000:
        return None
    return (win_start, win_end, spike_ms,
            round(float(d[min(centers[0], len(d) - 1)]), 3))


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
