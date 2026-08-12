"""
SpotFX — Song Profile data model.

A song profile links Spotify metadata to a list of timestamped music event triggers.
Stored as JSON: storage/profiles/{Artist} - {Song}.json
Looked up by spotify_uri.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


class MusicTrigger(BaseModel):
    """A single trigger: fire a named music event at a specific ms timestamp."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int          # when in the song to fire (ms)
    event_id: str              # references MusicEvent.id
    labels: list[str] = Field(default_factory=list)  # filter labels passed to event
    enabled: bool = True
    # User-driven fire intensity (0-1, 0.5 = mid). Drawn as the draggable
    # circle on the builder timeline; consumed by value bindings via the
    # "trigger_intensity" signal.
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    # Override Blend: rescale the fired event's ms timing (ramps + delays,
    # proportionally) so its last ramp completes exactly at the NEXT enabled
    # trigger (or song end). Beat-anchored spacing stays musical — only its
    # ramps scale. See trigger_engine._apply_override_blend.
    override_blend: bool = False
    # Scene-group color override: a ColorSetCard id (kind="group"). When this
    # trigger fires a scene_group (or anything that resolves the
    # "__scene_group__" color sentinel during the fire), that resolution uses
    # this group instead of the scene group's designated Color Group. None /
    # missing card → normal behavior, byte-identical to before the field.
    color_group_override: Optional[str] = None
    # Dark/Light display-mode override for this fire. "default" = defer to the
    # levels below (scene group → scene → set_color → color cards); "dark" /
    # "light" force the mode for everything this trigger fires. The global
    # TopBar mode still outranks it. See services/display_mode.resolve().
    display_mode: Literal["default", "dark", "light"] = "default"


class SongProfile(BaseModel):
    """Full profile for one song."""
    # ── Identity ──────────────────────────────────────────────────────────────
    spotify_uri: str           # e.g. "spotify:track:xxxxx"  — primary lookup key
    title: str
    artist: str
    artist_genre: list[str] = Field(default_factory=list)
    duration_ms: int

    # ── User metadata ─────────────────────────────────────────────────────────
    labels: list[str] = Field(default_factory=list)
    verified: bool = False
    notes: str = ""
    # ── Intensity scaling ─────────────────────────────────────────────────────
    # Pure multiplier (0-2 = 0-200%) applied to every trigger's intensity at
    # fire time, BEFORE gates / lane mapping / bindings (result clamped 0-1).
    # None → fall through to the genre profile's default_intensity_scale, then
    # 1.0. `intensity_scale_source` records who set it: "user" (Now Playing
    # slider — never overwritten automatically), "auto" (computed from librosa
    # / audio-shape loudness), "genre" (stamped by a future genre backfill).
    intensity_scale: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    intensity_scale_source: Optional[Literal["user", "auto", "genre"]] = None

    # ── Triggers ──────────────────────────────────────────────────────────────
    triggers: list[MusicTrigger] = Field(default_factory=list)
    # Per-Set-List trigger overrides. Keyed by Setlist.id (UUID, stable across
    # context_uri renames). When a Set List is the active context for this
    # song, the engine prefers its entry here over `triggers`. Empty list /
    # missing key → fall back to `triggers`.
    setlist_triggers: dict[str, list[MusicTrigger]] = Field(default_factory=dict)

    # ── Audio shape reference ─────────────────────────────────────────────────
    # Relative path under storage/audio_shapes/ or None if not yet captured
    audio_shape_file: Optional[str] = None

    # ── AI provenance ─────────────────────────────────────────────────────────
    ai_generated: bool = False
    ai_training_profile_id: str = ""
    ai_generated_date: str = ""   # ISO date, e.g. "2026-03-06"
    ai_model: str = ""            # last model used, e.g. "claude-haiku-4-5-20251001"
    embedded_generated: bool = False  # True when triggers were auto-placed by the KNN engine

    @property
    def filename(self) -> str:
        """Canonical filename (without extension)."""
        safe = lambda s: "".join(c for c in s if c not in r'\/:*?"<>|')
        artist = safe(self.artist)[:40]
        title = safe(self.title)[:40]
        return f"{artist} - {title}"
