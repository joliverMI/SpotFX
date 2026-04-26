"""
SpotFX — Set List data model.

A Set List is a tracked Spotify playlist (DJ-style mix or otherwise) that
SpotFX should treat with custom behaviour while it is the active playback
context. Storage: storage/setlists.json keyed by Set List `id`.

Effects when active:
  - auto_activate         — unpause the engine if it was paused
  - auto_use_analyzed     — flip state.use_analyzed_triggerless to True
  - genre_blending        — override settings.genre_blending_enabled
  - xcorr_cut_buffer_ms   — override the global xcorr cut buffer (None = use global)

Per-song trigger overrides live on SongProfile.setlist_triggers, keyed by
this Set List's `id`. Per-Set-List xcorr offsets live on AudioShapeMeta.setlist_offsets,
also keyed by `id`.
"""
from __future__ import annotations
import uuid
from typing import Optional
from pydantic import BaseModel, Field


class Setlist(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    context_uri: str = ""              # spotify:playlist:... — unique constraint
    name: str = "New Set List"
    auto_activate: bool = False        # unpause when this Set List becomes active
    auto_use_analyzed: bool = False    # force use_analyzed_triggerless on while active
    genre_blending: str = "global"     # "on" | "off" | "global" (defer to settings)
    xcorr_cut_buffer_ms: Optional[int] = None  # None = use settings.xcorr_cut_buffer_ms
    notes: str = ""
    created_at: str = ""
