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
    # Recapture-suggested flag: set by runtime detectors that observe the
    # captured shape is no longer aligning well (chronic anti-corr baselines,
    # repeated sweep-final Q < threshold, no usable U-Score windows, etc.).
    # An external script will scan the audio_shapes directory for shapes with
    # `needs_recapture=True` and recapture them. Once a fresh capture saves
    # over the same npz, the flag is reset to False.
    needs_recapture: bool = False
    needs_recapture_reason: str = ""           # short tag, e.g. "anti_corr_persistent", "low_q_streak", "no_uscore_windows"
    needs_recapture_flagged_at: str = ""       # ISO 8601 UTC timestamp when set
    needs_recapture_flag_count: int = 0        # incremented on each flag event; lets the script prioritize chronic offenders
    timestamp_offset_ms: int = 0     # shift shape data to align capture timing with playhead
    perception_trim_ms: int = 0      # user-applied nudge layered on top of timestamp_offset_ms
                                      # (applies when no Set List is active; per-Set-List trims
                                      # live in setlist_offsets[id].perception_trim_ms)
    offset_verification: Literal["unverified", "auto_verified", "user_verified"] = "unverified"
    offset_quality: float = 0.0      # best quality score: r × difficulty (0–1); 0 = not calibrated
    # Cached smart-window schedule (recomputed if params or shape change)
    xcorr_windows: list[dict] = Field(default_factory=list)   # [{start_ms, end_ms, difficulty}]
    xcorr_params_hash: str = ""                                # invalidation hash
    # Pre-computed early-feature anchor candidates (computed at capture time).
    # Each entry: {timestamp_ms, band, rise_magnitude, uniqueness, template: [float, ...]}
    # Used at song start by anchor_detector.match_in_frames() to snap-align before
    # the per-window xcorr sweep runs. Empty list = no anchor available, fall back
    # to the regular sweep.
    anchor_candidates: list[dict] = Field(default_factory=list)
    # Per-play offset history (most recent first, cap at 20)
    offset_history: list[dict] = Field(default_factory=list)   # [{iso_timestamp, offset_ms, quality, window_count}]
    # Per-Set-List offset memory. Keyed by Setlist.id (UUID). Each entry is
    # {
    #   timestamp_offset_ms : int    — latest xcorr-derived offset (math)
    #   offset_quality      : float  — Q score of latest lock
    #   generated_at        : iso    — when latest lock was saved
    #   observed_cut_ms     : int    — captured−polled duration delta (crude
    #                                  mix-trim estimate, diagnostics only)
    #   observed_cut_in_ms  : int    — directly-observed blend cut-in point
    #                                  (a saved lock ≥ xcorr_cut_in_record_min_ms);
    #                                  centers the next play's narrow search stage
    #   perception_trim_ms  : int    — user-applied nudge layered on top of xcorr
    #                                  (positive = fire later; negative = earlier)
    #   history             : list   — last 5 saved locks, most-recent first:
    #                                    [{offset_ms, quality, generated_at}]
    #   anti_corr_count     : int    — consecutive plays where stored offset
    #                                  was anti-correlated against captured audio
    #   last_anti_corr_at   : iso
    # }
    # Legacy `timestamp_offset_ms` / `offset_quality` remain the no-Set-List baseline.
    setlist_offsets: dict[str, dict] = Field(default_factory=dict)
    # Librosa analysis version: 0=none, 1=basic (no MFCC), 2=full (with MFCC)
    librosa_version: int = 0
    # Post-recapture self-correction record (services/capture_alignment.py).
    # shift_ms = new_label − old_label of the same musical moment. status:
    # "applied" | "no_shift" | "low_confidence" | "no_baseline" | "disabled".
    last_realign_status: str = ""
    last_realign_shift_ms: int = 0
    last_realign_r: float = 0.0
    last_realign_at: str = ""
