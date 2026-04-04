"""
SpotFX — Triggerless Play profile model.

Defines interval-based lighting behaviour for songs that have no
manually-configured triggers (or when Dinner Party mode is active).
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class TriggerlessProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    genres: list[str] = Field(default_factory=list)
    is_default: bool = False

    # Song start — fires once at 0:00 (or on detection)
    start_event_id: str = ""

    # Song end — fires once at (duration - end_pre_fire_ms)
    end_event_id: str = ""
    end_pre_fire_ms: int = 5000

    # Scene change — fires every scene_change_interval_s; first fire after one full interval
    scene_event_id: str = ""
    scene_change_interval_s: int = 30

    # Flare — optional; fires every flare_interval_s, skipped if coincides with scene event
    flare_event_id: Optional[str] = None
    flare_interval_s: int = 15
