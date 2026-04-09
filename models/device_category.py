"""
SpotFX — Device category model.

Groups LedFX virtuals into named categories with associated effect types.
Replaces the static 'categories' section of config/effect_params.json.
"""
from __future__ import annotations
import uuid
from pydantic import BaseModel, Field


class DeviceCategory(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    parent_id: str | None = None
    virtuals: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    sort_order: int = 0
    role: str | None = None  # "ambient" or None
