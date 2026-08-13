"""Read-only Colour Set access for SPECTRA.

Colour sets are spot-effects storage (storage/color_sets.json); SPECTRA
reads them by the one-directional bridge contract and NEVER writes — the
global scene opt-out toggle is the single exception, done through the
spot-effects API by the frontend, not through this module. The model here is
a projection: just the fields the scene filter, wheel math, and compiler
consume. Unknown fields in storage are ignored, never round-tripped.
"""
from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from spectra import config

logger = logging.getLogger(__name__)


class SetScope(BaseModel):
    virtual_ids: list[str] = Field(default_factory=list)
    categories:  list[str] = Field(default_factory=list)
    roles:       list[str] = Field(default_factory=list)


class ColorSetEntry(BaseModel):
    scope:       SetScope = Field(default_factory=SetScope)
    color_kind:  Optional[Literal["gradient", "solid"]] = None
    color_value: str | None = None
    bg_color:    str | None = None
    bg_mode:     Optional[Literal["additive", "overwrite"]] = None
    brightness:            float | None = None
    background_brightness: float | None = None


class ColorSetCard(BaseModel):
    id:      str
    name:    str
    kind:    Literal["set", "group"] = "set"
    entries: list[ColorSetEntry] = Field(default_factory=list)
    scene_v2_opt_out: bool = False

    model_config = {"extra": "ignore"}


def list_all() -> list[ColorSetCard]:
    path = config.COLOR_SETS_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("color_sets.json parse failed: %s", exc)
        return []
    out: list[ColorSetCard] = []
    for value in raw.values():
        try:
            out.append(ColorSetCard(**value))
        except Exception as exc:
            logger.warning("color set %s skipped: %s", value.get("id"), exc)
    return out


def get_by_id(set_id: str) -> Optional[ColorSetCard]:
    for card in list_all():
        if card.id == set_id:
            return card
    return None
