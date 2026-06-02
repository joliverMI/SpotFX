"""
SpotFX — Color Set data models.

A `ColorSetCard` is either:
  - kind="set":   a reusable bundle of FG/BG color entries, each scoped to a
                  device/category. Applied to many devices at once by a
                  Morph Color step.
  - kind="group": an ordered list of references to Color Sets, picked one at a
                  time (sequential cycle or weighted random) when fired.

A Color Set entry is essentially a restricted Morph Step target (color +
bg_color), so it reuses `MorphScope` from models.music_event and is compiled
through the same `morph_compiler` path at fire time.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid

from models.music_event import MorphScope


class ColorSetEntry(BaseModel):
    """One scoped FG/BG color definition within a Color Set. Both colors are
    optional — leave one unset to only change the other. `bg_mode` maps to the
    LedFX `background_mode` param (additive/overwrite); None = don't touch it.
    `ramp_ms` overrides the Morph Color step's ramp only when assigned."""
    scope:       MorphScope = Field(default_factory=MorphScope)
    color_kind:  Optional[Literal["gradient", "solid"]] = None
    color_value: str | None = None
    bg_color:    str | None = None
    bg_mode:     Optional[Literal["additive", "overwrite"]] = None
    ramp_ms:     int | None = None


class GroupMember(BaseModel):
    """One reference to a Color Set within a Group, with a selection weight."""
    color_set_id: str
    weight:       float = 1.0


class ColorSetCard(BaseModel):
    """A card on the Color Sets page — a Color Set or a Group of Color Sets."""
    id:    str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:  str
    color: str = "#FFD700"     # swatch shown in the card list
    kind:  Literal["set", "group"] = "set"
    labels: list[str] = Field(default_factory=list)

    # kind == "set"
    entries: list[ColorSetEntry] = Field(default_factory=list)

    # kind == "group"
    members:        list[GroupMember] = Field(default_factory=list)
    mode:           Literal["cycle", "weighted"] = "cycle"
    cycle_behavior: Literal["wrap", "bounce"] = "wrap"
    exclude_current: bool = True
