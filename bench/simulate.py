"""
Frame synthesis + fakes for offline xcorr replay.

`make_frames` turns a stored full-song WAV into the exact frame tuples the
live capture produces (same RMS/FFT math via
api.audio_capture.synthesize_frames_from_pcm), with controlled degradations:

  true_offset_ms — the offset xcorr SHOULD measure for this play.
                   Positive = triggers must fire earlier = live audio is
                   EARLY relative to the Spotify clock.
  cut_in_ms      — blended-playlist cut-in: the first N ms of the song's
                   audio never play (mix skipped the intro). A pure cut-in
                   of C produces an expected offset of +C, so callers
                   normally pass true_offset_ms=cut_in_ms for cut scenarios.
  gain / noise_snr_db / blend_* — capture-realism degradations.

Timestamp math: frames are synthesized from the (trimmed) PCM with ts=0 at
the first played sample, then shifted by `cut_in_ms − true_offset_ms`. A
frame at clock ts therefore contains song content from time
`ts + true_offset_ms` — i.e. live leads the clock by true_offset, and the
matcher's sign convention (offset = −shift, live late by X → offset −X)
recovers exactly `true_offset_ms`.

`FakeEngine` replicates trigger_engine.apply_save's gates
(services/trigger_engine.py:798-861: quality-wins, in-song drift cap with
bypass-Q tiers) so engine-snap dynamics match production. `FakeMetaStore`
replicates the _save_offset slot bookkeeping in memory.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import soundfile as sf

from config import settings
from api.audio_capture import synthesize_frames_from_pcm

logger = logging.getLogger(__name__)

Frame = tuple[int, float, float, float, float]


def load_wav(path) -> np.ndarray:
    """Load a stored capture WAV as mono float32 at the app sample rate."""
    pcm, rate = sf.read(path, dtype="float32", always_2d=False)
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1).astype("float32")
    if rate != settings.audio_sample_rate:
        raise ValueError(f"{path}: rate {rate} != {settings.audio_sample_rate}")
    return pcm


def make_frames(
    pcm: np.ndarray,
    *,
    true_offset_ms: int = 0,
    cut_in_ms: int = 0,
    gain: float = 1.0,
    noise_snr_db: Optional[float] = None,
    blend_donor_pcm: Optional[np.ndarray] = None,
    blend_ms: int = 0,
    rng_seed: int = 0,
) -> list[Frame]:
    """Synthesize live-capture frames from PCM with controlled degradations.
    Returns [(ts_ms, rms_total, rms_low, rms_mid, rms_high), ...]."""
    rate = settings.audio_sample_rate
    pcm = np.asarray(pcm, dtype=np.float32)

    if cut_in_ms > 0:
        pcm = pcm[int(cut_in_ms / 1000.0 * rate):]

    if gain != 1.0:
        pcm = pcm * np.float32(gain)

    if blend_donor_pcm is not None and blend_ms > 0:
        # Equal-power crossfade of the donor song's tail over our first
        # blend_ms — models a DJ-mix transition polluting the song start.
        n = min(int(blend_ms / 1000.0 * rate), len(pcm))
        donor_tail = np.asarray(blend_donor_pcm[-n:], dtype=np.float32)
        if len(donor_tail) < n:
            donor_tail = np.pad(donor_tail, (n - len(donor_tail), 0))
        t = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)
        pcm = pcm.copy()
        pcm[:n] = pcm[:n] * np.sin(t) + donor_tail * np.cos(t)

    if noise_snr_db is not None:
        rng = np.random.default_rng(rng_seed)
        sig_rms = float(np.sqrt(np.mean(pcm ** 2))) or 1e-9
        noise_rms = sig_rms / (10.0 ** (noise_snr_db / 20.0))
        pcm = pcm + rng.normal(0.0, noise_rms, len(pcm)).astype(np.float32)

    frames = synthesize_frames_from_pcm(pcm, 0)
    ts_shift = int(cut_in_ms - true_offset_ms)
    return [
        (f.timestamp_ms + ts_shift, f.rms_total, f.rms_low, f.rms_mid, f.rms_high)
        for f in frames
    ]


@dataclass
class SnapEvent:
    song_time_ms: int
    offset_ms: int
    quality: float
    source: str


class FakeEngine:
    """In-memory replica of trigger_engine's offset state + apply_save gates
    (services/trigger_engine.py:798-861). Perception trim is treated as 0."""

    def __init__(self, uri: str, loaded_offset_ms: int) -> None:
        self._last_uri = uri
        self._loaded_offset_ms = int(loaded_offset_ms)
        self._shape_offset_ms = int(loaded_offset_ms)
        self._shape_offset_quality = 0.0
        self._play_best_quality = 0.0
        self.snap_log: list[SnapEvent] = []
        self.now_ms: int = 0   # replay clock (song time), set by the driver

    def apply_save(self, uri: str, raw_offset_ms: int, quality: float,
                   source: str = "sweep", bypass_drift_cap: bool = False) -> bool:
        if uri != self._last_uri:
            return False
        if quality <= self._play_best_quality:
            return False
        trim = 0
        new_effective = int(raw_offset_ms) + trim
        drift_cap = int(getattr(settings, "engine_in_song_drift_cap_ms", 2000))
        bypass_q = float(getattr(settings, "engine_drift_bypass_q", 0.70))
        anti_corr_bypass_q = float(getattr(settings, "engine_anti_corr_bypass_q", 0.85))
        effective_bypass = bypass_drift_cap and quality >= anti_corr_bypass_q
        # Cold-start progressive exception (mirrors trigger_engine.apply_save).
        if source == "progressive" and self._play_best_quality == 0.0:
            effective_bypass = True
        if drift_cap > 0 and quality < bypass_q and not effective_bypass:
            drift = abs(new_effective - self._loaded_offset_ms)
            if drift > drift_cap:
                return False
        self._shape_offset_ms = new_effective
        self._shape_offset_quality = quality
        self._play_best_quality = quality
        self.snap_log.append(SnapEvent(self.now_ms, new_effective, quality, source))
        return True


@dataclass
class SaveEvent:
    song_time_ms: int
    offset_ms: int
    quality: float
    source: str


class FakeMetaStore:
    """In-memory replica of the _save_offset slot bookkeeping (history insert,
    cap 5, coarse_locked) for one (uri, slot). Mirrors
    services/auto_offset_service._save_offset including its engine apply."""

    def __init__(self, engine: FakeEngine, *,
                 seed_history: Optional[list[int]] = None,
                 seed_quality: float = 0.0,
                 coarse_locked: bool = False) -> None:
        self.engine = engine
        self.history: list[dict] = [
            {"offset_ms": int(o), "quality": seed_quality, "source": "seed"}
            for o in (seed_history or [])
        ]
        self.timestamp_offset_ms: int = int(seed_history[0]) if seed_history else 0
        self.offset_quality: float = seed_quality if seed_history else 0.0
        self.coarse_locked = coarse_locked
        self.save_log: list[SaveEvent] = []

    def median_offset(self) -> Optional[int]:
        vals = sorted(int(h["offset_ms"]) for h in self.history)
        if not vals:
            return None
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) // 2

    def save_offset(self, uri: str, offset_ms: int, quality: float,
                    source: str = "sweep", bypass_drift_cap: bool = False) -> None:
        self.history.insert(0, {"offset_ms": int(offset_ms),
                                "quality": round(quality, 3), "source": source})
        self.history = self.history[:5]   # _OFFSET_HISTORY_CAP
        self.timestamp_offset_ms = int(offset_ms)
        self.offset_quality = round(quality, 3)
        self.coarse_locked = True
        self.save_log.append(SaveEvent(self.engine.now_ms, int(offset_ms),
                                       quality, source))
        # _save_offset applies to the live engine with an anchor-provenance
        # quality boost (auto_offset_service._save_offset).
        apply_quality = float(quality) * (1.6 if source == "anchor" else 1.0)
        self.engine.apply_save(uri, int(offset_ms), apply_quality, source,
                               bypass_drift_cap=bypass_drift_cap)
