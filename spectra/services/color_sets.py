"""Read-only Colour Set access for SPECTRA.

Colour sets are spot-effects storage (storage/color_sets.json); SPECTRA's
own backend reads them by the one-directional bridge contract and NEVER
writes — authoring (create/edit/delete a Set or Group, incl. the global
scene opt-out toggle) goes through the spot-effects API directly from the
frontend (its own supported, already-general surface), not through this
module. The model here is a projection: just the fields the scene filter,
wheel math, compiler, and (kind=="group") pool resolution consume. Unknown
fields in storage are ignored, never round-tripped — safe ONLY because
nothing here ever writes storage back; the frontend's write path talks to
spot-effects' own unmodified model instead, so nothing an agent doesn't
render here (dark_variant/light_variant mode lanes, entries' accent_color/
ramp_ms — all owner-retired or unused by SPECTRA, §36/§42) is ever at risk
of being silently dropped on save.
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


class GroupMember(BaseModel):
    """One reference to a Color Set within a Group, with a selection weight
    (weighted mode only)."""
    color_set_id: str
    weight:       float = 1.0


class ColorSetCard(BaseModel):
    id:      str
    name:    str
    color:   str = "#FFD700"   # swatch, also the wheel-dot fallback tint
    kind:    Literal["set", "group"] = "set"
    labels:  list[str] = Field(default_factory=list)
    entries: list[ColorSetEntry] = Field(default_factory=list)
    scene_v2_opt_out: bool = False
    # Per-item mode availability (owner ask 2026-08-17) — see
    # spectra/services/mode_availability.py. Distinct from the retired
    # display_mode/dark_variant/light_variant mode-lane fields (§36),
    # which this projection deliberately still does NOT carry.
    display_availability: Literal["default", "dark", "light"] = "default"

    # kind == "group" (day-one bar item §10 — see color_set_groups.py for
    # the pick/merge logic that actually consumes these): members is the
    # pool, mode/cycle_behavior/exclude_current pick within it, entries (the
    # field above) act as a field-level OVERRIDE layer on top of whichever
    # member gets picked. Defaults mirror legacy's and match every one of
    # his 8 real authored groups (storage/color_sets.json, 2026-08-15).
    members:         list[GroupMember] = Field(default_factory=list)
    mode:            Literal["cycle", "weighted"] = "cycle"
    cycle_behavior:  Literal["wrap", "bounce"] = "wrap"
    exclude_current: bool = True
    palette_sync:    bool = False

    # Rainbow select (owner ask 2026-08-20) — see models/color_set.py's
    # ColorSetCard.is_rainbow docstring. ColorSetCard is defined TWICE
    # (that one, and this read-only projection); a field added to one and
    # not the other is silently dropped on every SPECTRA-side read
    # (AGENTS.md) — mirrored here for exactly that reason.
    is_rainbow: bool = False

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
