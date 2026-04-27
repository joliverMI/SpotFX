"""
SpotFX — Early-feature anchor alignment.

Two-phase mechanism for snap-aligning the captured audio to a song's stored
shape at song start, before the per-window xcorr sweep has had time to run.

1. Offline (at audio shape capture completion): scan the first 30s of the
   captured shape for steep RMS rises in any band. Score each candidate's
   uniqueness against the surrounding early section. Persist the top
   candidates into AudioShapeMeta.anchor_candidates.

2. Online (at song start): as the live capture stream produces frames, match
   each stored candidate's template against the live signal. The shift that
   maximises correlation = the per-play offset. If the match correlation is
   high enough, write the offset directly (no cluster gate — uniqueness was
   already vetted offline) and the per-window sweep proceeds with the new
   baseline.

Bands referenced by name (rms_total, rms_low, rms_high) so the captured-side
matcher can pick the same band the offline detector picked.
"""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)

_BIN_MS = 25                # resample resolution for templates (matches xcorr)
_SLOPE_WINDOW_MS = 250      # rolling derivative span — short enough to catch sharp rises
_BASELINE_WINDOW_MS = 2000  # local baseline span used to score rise magnitude
_MIN_PEAK_SEPARATION_MS = 1500  # candidates must be at least this far apart


@dataclass
class AnchorCandidate:
    timestamp_ms: int
    band: str                 # "rms_total" | "rms_low" | "rms_high"
    rise_magnitude: float
    uniqueness: float
    template: list[float]     # ±anchor_template_radius_ms slice at _BIN_MS resolution

    def to_dict(self) -> dict:
        return {
            "timestamp_ms": int(self.timestamp_ms),
            "band": self.band,
            "rise_magnitude": round(float(self.rise_magnitude), 3),
            "uniqueness": round(float(self.uniqueness), 3),
            "template": [round(float(v), 5) for v in self.template],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnchorCandidate":
        return cls(
            timestamp_ms=int(d.get("timestamp_ms", 0)),
            band=str(d.get("band", "rms_total")),
            rise_magnitude=float(d.get("rise_magnitude", 0.0)),
            uniqueness=float(d.get("uniqueness", 0.0)),
            template=[float(v) for v in (d.get("template") or [])],
        )


@dataclass
class AnchorMatch:
    offset_ms: int            # offset applied to align live capture with stored shape
    match_r: float            # peak correlation
    match_q: float            # match_r × candidate.uniqueness
    candidate: AnchorCandidate


# ── Offline detector ────────────────────────────────────────────────────────

def detect_anchor_candidates(
    timestamps_ms: np.ndarray,
    rms_total: np.ndarray,
    rms_low: np.ndarray,
    rms_high: np.ndarray,
) -> list[AnchorCandidate]:
    """Scan the first `anchor_scan_window_ms` of each band for steep RMS rises,
    score uniqueness against the surrounding section, return the top
    `anchor_max_candidates` ranked by uniqueness.
    """
    scan_ms = int(settings.anchor_scan_window_ms)
    template_radius_ms = int(settings.anchor_template_radius_ms)
    min_unique = float(settings.anchor_min_uniqueness)
    min_rise_ratio = float(settings.anchor_min_rise_ratio)
    max_candidates = int(settings.anchor_max_candidates)

    # Resample all bands onto a uniform grid covering [0, scan_ms].
    grid = np.arange(0, scan_ms, _BIN_MS, dtype=float)
    if len(grid) < 4 or len(timestamps_ms) < 2:
        return []
    ts = timestamps_ms.astype(float)
    bands = {
        "rms_total": np.interp(grid, ts, rms_total.astype(float), left=0.0, right=0.0),
        "rms_low":   np.interp(grid, ts, rms_low.astype(float),   left=0.0, right=0.0),
        "rms_high":  np.interp(grid, ts, rms_high.astype(float),  left=0.0, right=0.0),
    }

    raw: list[AnchorCandidate] = []
    for band_name, signal in bands.items():
        raw.extend(_find_rise_candidates(grid, signal, band_name,
                                          template_radius_ms, min_rise_ratio))

    if not raw:
        return []

    # Score uniqueness for each candidate against its own band's signal.
    scored: list[AnchorCandidate] = []
    for cand in raw:
        signal = bands[cand.band]
        u = _score_uniqueness(signal, cand.template, cand.timestamp_ms)
        if u >= min_unique:
            cand.uniqueness = u
            scored.append(cand)

    # Sort by uniqueness desc, then dedupe nearby candidates (keep highest).
    scored.sort(key=lambda c: c.uniqueness, reverse=True)
    kept: list[AnchorCandidate] = []
    for cand in scored:
        if any(abs(cand.timestamp_ms - k.timestamp_ms) < _MIN_PEAK_SEPARATION_MS
               for k in kept):
            continue
        kept.append(cand)
        if len(kept) >= max_candidates:
            break
    return kept


def _find_rise_candidates(
    grid: np.ndarray,
    signal: np.ndarray,
    band_name: str,
    template_radius_ms: int,
    min_rise_ratio: float,
) -> list[AnchorCandidate]:
    """Find local maxima of the slope (rolling derivative) above threshold.
    Returns rough candidates with rise_magnitude and template populated;
    uniqueness is filled later.
    """
    if len(signal) < 8:
        return []
    slope_bins = max(2, _SLOPE_WINDOW_MS // _BIN_MS)
    baseline_bins = max(slope_bins * 2, _BASELINE_WINDOW_MS // _BIN_MS)
    template_bins = max(2, template_radius_ms // _BIN_MS)

    # Centred rolling derivative.
    slope = np.zeros_like(signal)
    for i in range(slope_bins, len(signal) - slope_bins):
        slope[i] = signal[i + slope_bins // 2] - signal[i - slope_bins // 2]

    # Local maxima of the slope.
    cands: list[AnchorCandidate] = []
    for i in range(template_bins + slope_bins, len(signal) - template_bins - slope_bins):
        s = slope[i]
        if s <= 0:
            continue
        # Local max in slope?
        lo = max(0, i - slope_bins)
        hi = min(len(slope), i + slope_bins + 1)
        if s != slope[lo:hi].max():
            continue
        # Rise magnitude: peak signal vs trailing baseline.
        bl_lo = max(0, i - baseline_bins)
        baseline = float(np.median(signal[bl_lo:i])) if i > bl_lo else 0.0
        peak = float(signal[i:i + slope_bins].max())
        if baseline <= 1e-9:
            continue
        rise_ratio = peak / baseline
        if rise_ratio < min_rise_ratio:
            continue
        template = signal[i - template_bins:i + template_bins].tolist()
        cands.append(AnchorCandidate(
            timestamp_ms=int(grid[i]),
            band=band_name,
            rise_magnitude=float(rise_ratio),
            uniqueness=0.0,            # filled below
            template=template,
        ))
    return cands


def _score_uniqueness(signal: np.ndarray, template: list[float], skip_ms: int) -> float:
    """Cross-correlate the template against the full early-section signal,
    return (best self-match correlation) − (best non-self correlation).
    Higher = the rise's shape is more distinctive within its surroundings.
    Excludes the source position from the non-self search.
    """
    if not template or len(signal) < len(template) + 2:
        return 0.0
    tmpl = np.asarray(template, dtype=float)
    tmpl_z = _zscore(tmpl)
    if tmpl_z is None:
        return 0.0
    # Slide template along signal, compute Pearson r at each offset.
    rs = np.full(len(signal) - len(tmpl), -1.0, dtype=float)
    for i in range(len(rs)):
        seg = signal[i:i + len(tmpl)]
        seg_z = _zscore(seg)
        if seg_z is None:
            continue
        rs[i] = float(np.dot(tmpl_z, seg_z) / len(tmpl))
    if len(rs) == 0:
        return 0.0
    best_idx = int(np.argmax(rs))
    best_r = float(rs[best_idx])
    # Mask out the self-match neighbourhood.
    mask = np.ones_like(rs, dtype=bool)
    half = len(tmpl) // 2
    mask_lo = max(0, best_idx - half)
    mask_hi = min(len(rs), best_idx + half + 1)
    mask[mask_lo:mask_hi] = False
    if not mask.any():
        return 0.0
    second_r = float(rs[mask].max())
    return max(0.0, best_r - second_r)


def _zscore(arr: np.ndarray) -> Optional[np.ndarray]:
    if arr.size == 0:
        return None
    m = float(arr.mean())
    s = float(arr.std())
    if s < 1e-9:
        return None
    return (arr - m) / s


# ── Online matcher ──────────────────────────────────────────────────────────

def match_in_frames(
    candidates: list[AnchorCandidate],
    frames: list[tuple],
) -> Optional[AnchorMatch]:
    """Try each anchor candidate (uniqueness order) against the captured
    frames. Returns the first match whose match_q clears the threshold.

    `frames` is the list[tuple] used by auto_offset_service: each entry is
    `(timestamp_ms, rms_total, rms_low, rms_high)`. The matcher picks the
    band the candidate was detected on, resamples to the same `_BIN_MS`
    grid, and slides the template within ±anchor_search_radius_ms of the
    candidate's stored timestamp.
    """
    if not candidates or not frames:
        return None
    search_radius_ms = int(settings.anchor_search_radius_ms)
    min_q = float(settings.anchor_min_match_q)
    template_radius_ms = int(settings.anchor_template_radius_ms)

    ts = np.array([f[0] for f in frames], dtype=float)
    if ts.size < 2:
        return None
    band_index = {"rms_total": 1, "rms_low": 2, "rms_high": 3}

    # Build resampled live signals once per needed band.
    earliest_ms = max(0.0, float(ts[0]))
    latest_ms = float(ts[-1])
    live_grid = np.arange(earliest_ms, latest_ms, _BIN_MS, dtype=float)
    live_signals: dict[str, np.ndarray] = {}
    for cand in candidates:
        if cand.band in live_signals:
            continue
        idx = band_index.get(cand.band, 1)
        values = np.array([f[idx] for f in frames], dtype=float)
        live_signals[cand.band] = np.interp(live_grid, ts, values)

    # Try each candidate.
    for cand in candidates:
        live = live_signals.get(cand.band)
        tmpl = np.asarray(cand.template, dtype=float)
        if live is None or tmpl.size == 0:
            continue
        # Search a ±search_radius_ms band around cand.timestamp_ms in LIVE time.
        tmpl_radius_bins = max(1, template_radius_ms // _BIN_MS)
        live_centre_ms = cand.timestamp_ms
        search_lo_ms = live_centre_ms - search_radius_ms
        search_hi_ms = live_centre_ms + search_radius_ms
        # Convert to live_grid bin indices.
        live_lo = int(round((search_lo_ms - earliest_ms) / _BIN_MS))
        live_hi = int(round((search_hi_ms - earliest_ms) / _BIN_MS))
        live_lo = max(tmpl_radius_bins, live_lo)
        live_hi = min(len(live) - tmpl_radius_bins, live_hi)
        if live_hi <= live_lo + 1:
            continue
        tmpl_z = _zscore(tmpl)
        if tmpl_z is None:
            continue
        best_r = -1.0
        best_centre_bin = -1
        for centre_bin in range(live_lo, live_hi):
            seg = live[centre_bin - tmpl_radius_bins:centre_bin + tmpl_radius_bins]
            if seg.size != tmpl.size:
                continue
            seg_z = _zscore(seg)
            if seg_z is None:
                continue
            r = float(np.dot(tmpl_z, seg_z) / len(tmpl))
            if r > best_r:
                best_r = r
                best_centre_bin = centre_bin
        if best_centre_bin < 0:
            continue
        match_q = best_r * cand.uniqueness
        min_r = float(getattr(settings, "anchor_min_match_r", 0.0))
        if best_r < min_r:
            logger.info(
                "Anchor: candidate at %dms band=%s declined — match_r=%.2f below %.2f (Q=%.2f, would beat min_q)",
                cand.timestamp_ms, cand.band, best_r, min_r, match_q,
            )
            continue
        if match_q < min_q:
            logger.info(
                "Anchor: candidate at %dms band=%s declined — match_r=%.2f Q=%.2f below %.2f",
                cand.timestamp_ms, cand.band, best_r, match_q, min_q,
            )
            continue
        live_match_ms = earliest_ms + best_centre_bin * _BIN_MS
        # Stored anchor is at `cand.timestamp_ms` in song coordinates.
        # Live capture has the same musical event at `live_match_ms` in song
        # coordinates (frame timestamp_ms is already song-relative).
        # The capture's "song time" is shifted vs. stored shape by
        # offset_ms = stored_time - live_time. A positive offset means live
        # arrived later than stored expected, so trigger fire times shift
        # into the future — same convention as the rest of auto_offset_service.
        offset_ms = int(round(cand.timestamp_ms - live_match_ms))
        return AnchorMatch(
            offset_ms=offset_ms,
            match_r=round(best_r, 3),
            match_q=round(match_q, 3),
            candidate=cand,
        )
    return None
