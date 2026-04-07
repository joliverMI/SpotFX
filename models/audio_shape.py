"""
SpotFX — Audio Shape data model.

An audio shape is a time-series of audio features captured from real playback.
Stored as compressed numpy (.npz) for fast loading and sufficient detail.

Layout of the .npz file:
  timestamps_ms  : int32[N]   — sample times in ms
  rms_total      : float32[N] — overall RMS energy
  rms_low        : float32[N] — low-frequency RMS  (<250 Hz)
  rms_high       : float32[N] — high-frequency RMS (>4 kHz)
  avg_rms_1s     : float32[N] — 1-second rolling average of total RMS
  avg_rms_5s     : float32[N] — 5-second rolling average
  music_marks    : JSON string — see MusicMark below

MusicMark types (analytically detected, user-editable):
  tempo_change, bass_start, power_up, power_down, quiet, charging, bass_drop
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
import uuid

MarkType = Literal[
    "tempo_change",
    "bass_start",
    "bass_end",
    "power_up",
    "power_down",
    "quiet",
    "charging",
    "bass_drop",
]


class MusicMark(BaseModel):
    """An analytically detected (or user-edited) marker on the audio shape."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mark_type: MarkType
    timestamp_ms: int
    confidence: float = 1.0   # 0–1, set by detector; 1.0 for user-placed
    user_edited: bool = False
    notes: str = ""


class AudioShapeMeta(BaseModel):
    """
    Metadata stored alongside the .npz file.
    Kept as a small sidecar JSON for quick reads.
    """
    spotify_uri: str
    title: str
    artist: str
    duration_ms: int
    sample_interval_ms: int   # ms between samples (e.g. 23ms for 44100/1024)
    npz_file: str             # filename relative to storage/audio_shapes/
    music_marks: list[MusicMark] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    capture_complete: bool = False   # False while still being recorded
    capture_failed: bool = False     # True if capture was discarded (e.g. gap in data)
    timestamp_offset_ms: int = 0     # shift shape data to align capture timing with playhead
    offset_verification: Literal["unverified", "auto_verified", "user_verified"] = "unverified"
    offset_quality: float = 0.0      # best quality score: r × difficulty (0–1); 0 = not calibrated
    # Cached smart-window schedule (recomputed if params or shape change)
    xcorr_windows: list[dict] = Field(default_factory=list)   # [{start_ms, end_ms, difficulty}]
    xcorr_params_hash: str = ""                                # invalidation hash
    # Per-play offset history (most recent first, cap at 20)
    offset_history: list[dict] = Field(default_factory=list)   # [{iso_timestamp, offset_ms, quality, window_count}]
    # Librosa analysis version: 0=none, 1=basic (no MFCC), 2=full (with MFCC)
    librosa_version: int = 0
