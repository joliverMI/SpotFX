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
    # ── Spotify playback context (playlist / album / artist) ──────────────────
    context_uri: str = ""      # e.g. "spotify:playlist:abc123" or "" if no context
    context_type: str = ""     # "playlist" | "album" | "artist" | ""

    def interpolated_progress_ms(self) -> int:
        """Estimate current progress without an extra API call.

        Clamped to [0, duration_ms]: playback can never run past the song's
        end. Without the clamp a stale fetched_at (machine sleep, stalled
        poller) extrapolates arbitrarily far forward — which previously
        poisoned the audio-capture time baseline, placing every sample
        beyond the song (invisible shape, triggers that never fire).
        """
        if not self.is_playing:
            progress = self.progress_ms
        else:
            elapsed = (time.monotonic() - self.fetched_at) * 1000
            progress = int(self.progress_ms + elapsed)
        if self.duration_ms > 0:
            return max(0, min(progress, self.duration_ms))
        return max(0, progress)


@dataclass
class PrevTrackSnapshot:
    """Snapshot of the outgoing track captured at the moment a new URI arrives.

    Used by Genre Blending to decide whether the previous song ended naturally
    (progress within a few seconds of duration) and whether its genres overlap
    with the incoming song's genres.
    """
    spotify_uri: str
    genres: list
    duration_ms: int
    last_known_progress_ms: int


@dataclass
class AppState:
    # ── Spotify ───────────────────────────────────────────────────────────────
    current_track: Optional[SpotifyTrackInfo] = None
    last_poll_time: float = 0.0
    last_activity_time: float = field(default_factory=time.monotonic)

    # ── Service control ───────────────────────────────────────────────────────
    paused: bool = False          # True = triggers suppressed, polling continues
    on_target_device: bool = False  # True = playing on one of settings.spotify_device_names
    audio_analysis_enabled: bool = False  # True = capture audio shapes for new songs
    # Force-recapture mode (was recapture_wavs — now force-recaptures every song
    # that plays while active, with a session-bound counter that auto-disables
    # the toggle at zero).
    recapture_active: bool = False        # True = force-recapture every song that plays
    recapture_remaining: int = 0          # 0 = inactive; >0 = N songs left to recapture
    use_unreviewed_ai_triggers: bool = False  # True = use saved AI suggestion set instead of profile triggers
    use_analyzed_triggerless: bool = True      # True = use embedded pipeline triggers instead of synthetic triggerless
    analyzed_trigger_override: bool = False    # True = override user triggers with analyzed (debug/testing)
    auto_generate_enabled: bool = False       # True = auto-generate triggers after shape capture
    dinner_party_mode: bool = False            # True = ignore song triggers, use Dinner Party triggerless profile
    ambient_mode_enabled: bool = False         # True = at least one Hue group frozen (LedFX stream stopped) + held at static full-brightness via Hue REST
    ambient_groups: list = field(default_factory=list)  # LedFX Hue device ids currently held in ambient (subset of the target category)

    # ── Genre Blending ────────────────────────────────────────────────────────
    # Snapshot of the outgoing track captured just before current_track is replaced.
    last_ended_track: Optional[PrevTrackSnapshot] = None

    # ── LedFX latency ────────────────────────────────────────────────────────
    ledfx_rtt_ms: float = 0.0    # calculated round-trip time to LedFX

    # ── LedFX virtual state cache (updated every 5 s by poll_virtual_states) ──
    ledfx_virtual_cache: dict = field(default_factory=dict)

    # ── Live sync timing info (updated each tick by TriggerEngine) ────────────
    timing: dict = field(default_factory=dict)

    # ── Last Scene Update ─────────────────────────────────────────────────────
    # Id of the most recent scene_update event the engine fired — this is the
    # scene the fixed Update/Reset Scene events act on. Mirrored from the engine
    # so broadcast_state can show a "last scene" indicator. Persists across songs.
    last_scene_update_id: str = ""
    # Id of the scene_group event currently driving the scene ("" = none) —
    # set when a group fires or Scene Morph steps it, cleared when a plain
    # scene_update is picked directly. Mirrored from the engine. Persists
    # across songs.
    active_scene_group_id: str = ""
    # Id of the most recent Color Set the engine applied (the resolved member id
    # when a Group was fired). Mirrored from the engine for the Now Playing
    # indicator. Persists across songs.
    last_color_set_id: str = ""
    # Id of the most recent Color GROUP a set_color fire drew from (the group
    # card itself, not the picked member). Set Color actions with
    # ref_id == CURRENT_COLOR_GROUP_REF re-use it. Persists across songs.
    last_color_group_id: str = ""

    # ── Set List context ─────────────────────────────────────────────────────
    next_track_uri: str = ""           # spotify URI of queue[0] after the current track
    next_track_title: str = ""         # display label for the next track
    active_setlist_id: str = ""        # id of the Set List matching current_track.context_uri
    active_setlist_xcorr_enabled: bool = True   # mirrored from Setlist.xcorr_enabled (False → skip per-play xcorr)
    # Snapshot of toggles before a Set List override took effect, so we can
    # restore them when leaving the Set List context.
    pre_setlist_state: dict = field(default_factory=dict)
    # Recently observed context URIs → last-known display name. Lets the Set List
    # page offer "track this playlist" without the user pasting URIs. Bounded
    # to the most recent ~20 entries.
    observed_context_uris: dict = field(default_factory=dict)


# Singleton instance — import this everywhere
state = AppState()
