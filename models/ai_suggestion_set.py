"""
SpotFX — AI Suggestion Set model.

Persists a set of AI-generated trigger suggestions for one song so they can
be reviewed, applied, and re-loaded without re-running the AI.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class SavedSuggestion(BaseModel):
    timestamp_ms: int
    event_id: str
    event_name: str
    confidence: float = 1.0
    reasoning: str = ""
    original_timestamp_ms: int
    original_event_id: str
    labels: list[str] = []
    comment: str = ""
    manually_added: bool = False
    approved: Optional[bool] = None


class AISuggestionSet(BaseModel):
    spotify_uri: str
    title: str
    artist: str
    duration_ms: int
    generated_at: str           # ISO datetime string
    training_profile_id: str = ""
    training_profile_name: str = ""
    suggestions: list[SavedSuggestion] = []
    song_comment: str = ""
    reviewed: bool = False
    applied: bool = False
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
