"""
SpotFX — cross-window evidence accumulation (Phase 3).

Each evaluated window contributes its FULL correlation landscape, weighted
by window difficulty, onto a shared offset grid. The true offset reinforces
across windows while beat-tile twins decorrelate (a twin that wins one
window sits somewhere else in the next), so the accumulated function's
dominant peak is far more robust than per-window winners voting in
clusters. Anchor and progressive matches contribute narrow Gaussian bumps.

Grid domain is OFFSET (the value that gets saved), i.e. −shift for window
landscapes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from services.xcorr_core import XCORR_BIN_MS


@dataclass
class AccumPeak:
    offset_ms: int       # centroid-refined dominant offset
    mass: float          # accumulated weight at the peak
    dominance: float     # mass − strongest competitor ≥ min_sep away
    support: int         # windows/votes that individually showed r > 0.30 here


class EvidenceAccumulator:
    def __init__(self, max_offset_ms: int, bin_ms: int = XCORR_BIN_MS) -> None:
        self.bin_ms = int(bin_ms)
        self.max_offset_ms = int(max_offset_ms)
        self.offsets = np.arange(-self.max_offset_ms,
                                 self.max_offset_ms + self.bin_ms, self.bin_ms)
        self.mass = np.zeros(len(self.offsets))
        self.support = np.zeros(len(self.offsets), dtype=int)
        self.n_curves = 0

    def _idx(self, offset_ms: float) -> int:
        return int(round((offset_ms + self.max_offset_ms) / self.bin_ms))

    def add_curve(self, offsets_ms: np.ndarray, r: np.ndarray,
                  weight: float) -> None:
        """Add one window's landscape (offset domain). Positive correlation
        accumulates mass ∝ weight·r; r > 0.30 counts as support."""
        if weight <= 0 or len(offsets_ms) == 0:
            return
        idx = np.round((np.asarray(offsets_ms, dtype=float) + self.max_offset_ms)
                       / self.bin_ms).astype(int)
        ok = (idx >= 0) & (idx < len(self.offsets)) & np.isfinite(r)
        idx, rv = idx[ok], np.asarray(r, dtype=float)[ok]
        np.add.at(self.mass, idx, weight * np.maximum(0.0, rv))
        np.add.at(self.support, idx, (rv > 0.30).astype(int))
        self.n_curves += 1

    def add_gaussian(self, center_ms: int, mass: float,
                     sigma_ms: float = 100.0, count_support: bool = True) -> None:
        """Narrow vote from an anchor / progressive match — or, with
        count_support=False, a soft history prior that can tip ties but
        never substitutes for fresh evidence (support gate unaffected)."""
        if mass <= 0:
            return
        g = mass * np.exp(-((self.offsets - center_ms) ** 2)
                          / (2.0 * sigma_ms * sigma_ms))
        self.mass += g
        if count_support:
            lo, hi = self._idx(center_ms - 2 * sigma_ms), self._idx(center_ms + 2 * sigma_ms)
            lo, hi = max(0, lo), min(len(self.offsets), hi + 1)
            if hi > lo:
                self.support[lo:hi] += 1
            self.n_curves += 1

    def dominant(self, min_sep_ms: int = 350,
                 centroid_radius_ms: int = 150) -> Optional[AccumPeak]:
        if self.n_curves == 0 or not np.any(self.mass > 0):
            return None
        peak_i = int(np.argmax(self.mass))
        peak_mass = float(self.mass[peak_i])

        # Centroid refinement within ±radius — sub-bin placement when the
        # true offset straddles bins across windows.
        rad = max(1, centroid_radius_ms // self.bin_ms)
        lo, hi = max(0, peak_i - rad), min(len(self.offsets), peak_i + rad + 1)
        w = self.mass[lo:hi]
        offset = (float(np.dot(w, self.offsets[lo:hi]) / w.sum())
                  if w.sum() > 0 else float(self.offsets[peak_i]))

        # Strongest competitor outside ±min_sep.
        sep = max(1, min_sep_ms // self.bin_ms)
        masked = self.mass.copy()
        masked[max(0, peak_i - sep): peak_i + sep + 1] = 0.0
        runner_up = float(masked.max()) if len(masked) else 0.0

        support = int(self.support[lo:hi].max()) if hi > lo else 0
        return AccumPeak(
            offset_ms=int(round(offset)),
            mass=round(peak_mass, 3),
            dominance=round(peak_mass - runner_up, 3),
            support=support,
        )
