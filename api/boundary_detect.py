"""
SpotFX — Acoustic track-boundary detector.

Given a slice of mono float32 PCM and a hint sample offset where the boundary
is expected (Spotify-derived song_start), search a ±window for the strongest
acoustic discontinuity (RMS + spectral-centroid novelty) and return the
refined offset along with a confidence (peak-to-mean ratio).

Used by audio_shape_service to symmetrically trim the previous song's tail
and the new song's pre-roll using ONE shared boundary instant.
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_WINDOW_S = 2.0
HOP_MS = 50
CONFIDENCE_THRESHOLD = 2.5


def _rms_per_hop(pcm: np.ndarray, hop: int) -> np.ndarray:
    n_hops = len(pcm) // hop
    if n_hops == 0:
        return np.zeros(0, dtype=np.float32)
    trimmed = pcm[: n_hops * hop].reshape(n_hops, hop)
    return np.sqrt(np.mean(trimmed ** 2, axis=1)).astype(np.float32)


def _centroid_per_hop(pcm: np.ndarray, hop: int, sample_rate: int) -> np.ndarray:
    n_hops = len(pcm) // hop
    if n_hops == 0:
        return np.zeros(0, dtype=np.float32)
    trimmed = pcm[: n_hops * hop].reshape(n_hops, hop)
    freqs = np.fft.rfftfreq(hop, d=1.0 / sample_rate).astype(np.float32)
    out = np.zeros(n_hops, dtype=np.float32)
    for i in range(n_hops):
        mag = np.abs(np.fft.rfft(trimmed[i]))
        denom = mag.sum()
        if denom > 1e-9:
            out[i] = float((mag * freqs).sum() / denom)
    return out


def _normalize(curve: np.ndarray) -> np.ndarray:
    if curve.size == 0:
        return curve
    std = float(np.std(curve))
    if std < 1e-9:
        return np.zeros_like(curve)
    return (curve - float(np.mean(curve))) / std


def find_track_boundary(
    pcm: np.ndarray,
    sample_rate: int,
    hint_offset_samples: int,
    search_window_s: float = DEFAULT_SEARCH_WINDOW_S,
    hop_ms: int = HOP_MS,
) -> Tuple[int, float]:
    """Locate the most likely track boundary in `pcm` near `hint_offset_samples`.

    Returns (best_offset_samples, confidence). When confidence is below
    CONFIDENCE_THRESHOLD the caller should fall back to the hint (gapless
    transition with no acoustic discontinuity to lock onto).
    """
    if pcm.size == 0:
        return hint_offset_samples, 0.0
    hop = max(1, int(sample_rate * hop_ms / 1000))
    rms = _rms_per_hop(pcm, hop)
    centroid = _centroid_per_hop(pcm, hop, sample_rate)
    if rms.size < 3:
        return hint_offset_samples, 0.0
    drms = np.abs(np.diff(_normalize(rms)))
    dcen = np.abs(np.diff(_normalize(centroid)))
    novelty = drms + dcen   # length = n_hops - 1; novelty[i] = change at hop i+1
    hint_hop = hint_offset_samples // hop
    win_hops = max(1, int(search_window_s * 1000 / hop_ms))
    lo = max(0, hint_hop - win_hops)
    hi = min(len(novelty), hint_hop + win_hops + 1)
    if hi <= lo:
        return hint_offset_samples, 0.0
    window = novelty[lo:hi]
    mean = float(np.mean(window))
    if mean < 1e-9:
        return hint_offset_samples, 0.0
    peak_idx_local = int(np.argmax(window))
    peak = float(window[peak_idx_local])
    confidence = peak / mean
    best_hop = lo + peak_idx_local + 1   # +1 because novelty[i] is change AT hop i+1
    best_offset_samples = best_hop * hop
    return best_offset_samples, confidence
