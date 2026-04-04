"""
SpotFX — Shared in-memory application state.

This module holds the single shared state object that is updated by the
Spotify poller and read by the trigger engine and WebSocket broadcaster.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class SpotifyTrackInfo:
    spotify_uri: str
    title: str
    artist: str
    duration_ms: int
    progress_ms: int           # last known progress from Spotify
    is_playing: bool
    fetched_at: float          # time.monotonic() when progress_ms was fetched
    device_name: str = ""
    genres: list = field(default_factory=list)

    def interpolated_progress_ms(self) -> int:
        """Estimate current progress without an extra API call."""
        if not self.is_playing:
            return self.progress_ms
        elapsed = (time.monotonic() - self.fetched_at) * 1000
        return int(self.progress_ms + elapsed)


@dataclass
class AppState:
    # ── Spotify ───────────────────────────────────────────────────────────────
    current_track: Optional[SpotifyTrackInfo] = None
    last_poll_time: float = 0.0
    last_activity_time: float = field(default_factory=time.monotonic)

    # ── Service control ───────────────────────────────────────────────────────
    paused: bool = True           # True = triggers suppressed, polling continues
    on_target_device: bool = False  # True = playing on settings.spotify_device_name
    audio_analysis_enabled: bool = False  # True = capture audio shapes for new songs
    use_unreviewed_ai_triggers: bool = False  # True = use saved AI suggestion set instead of profile triggers
    auto_generate_enabled: bool = False       # True = auto-generate triggers after shape capture
    dinner_party_mode: bool = False            # True = ignore song triggers, use Dinner Party triggerless profile

    # ── LedFX latency ────────────────────────────────────────────────────────
    ledfx_rtt_ms: float = 0.0    # calculated round-trip time to LedFX

    # ── LedFX virtual state cache (updated every 5 s by poll_virtual_states) ──
    ledfx_virtual_cache: dict = field(default_factory=dict)

    # ── Live sync timing info (updated each tick by TriggerEngine) ────────────
    timing: dict = field(default_factory=dict)


# Singleton instance — import this everywhere
state = AppState()
