"""THE LIGHT SHOW's data model (the Admiral, 2026-10-04: "an ability to arm
and trigger different settings and events within spectra over time";
plan: /home/javi/fleet-spotfx/data/light-show-plan/report.md).

Two stores, deliberately separate:

  light_show_sets.json   HIS LIBRARY — named, ordered action sets. Only an
                         explicit edit writes it.
  light_show_state.json  RUNTIME — the fixtures the show is holding, the
                         settings it has changed (and what they were before),
                         and (phase 2) its arms. Churns constantly; can never
                         damage his library because it is a different file.

BUILT FOR PHASES 2 AND 4 WITHOUT A MIGRATION. Phase 1 fires sets NOW; the
`ShowArm` model and `LightShowState.arms` are declared today, empty, so
arming (next scene change, High/Low, one-shot/repeat, this-song-only,
expiry, restart persistence) and the phase-4 playlist runners land into a
file that already has the slot:

  * `ShowArm.on` is an OPEN string, not a Literal — new trigger kinds
    ("song_start", "at_time") are new values, not a schema change;
  * every arm refers to a set by ID, never by name, so renaming a set never
    orphans an arm or a script;
  * `ShowArm.song_uri` + `source` exist from day one, so a playlist script's
    song-scoped arms are ordinary arms tagged with where they came from;
  * `ShowArm.status` records each arm's outcome (armed/fired/missed/
    disarmed/expired) for the status surface a script reads its progress
    from.

Every model is `extra="ignore"` and every field defaulted, so a file written
by a later phase still loads here and a file written here loads there.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


def _id() -> str:
    return uuid.uuid4().hex[:12]


def now_ms() -> int:
    return int(time.time() * 1000)


class ShowAction(BaseModel):
    """One step: a registered action kind and its parameters
    (spectra/services/show_actions.py's ACTION_KINDS is the catalogue)."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    #: his own words for this step; the catalogue's label is used if empty
    label: str = ""
    #: a step can be switched off inside a set without deleting it
    enabled: bool = True


class ActionSet(BaseModel):
    """His named group. Order is list order — his to drag."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    name: str
    actions: list[ShowAction] = Field(default_factory=list)
    notes: str = ""
    created_ms: int = Field(default_factory=now_ms)
    updated_ms: int = Field(default_factory=now_ms)


class LightShowLibrary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    sets: list[ActionSet] = Field(default_factory=list)


# ── runtime ────────────────────────────────────────────────────────────────

class DeviceHold(BaseModel):
    """A fixture held in a state other than Show."""
    model_config = ConfigDict(extra="ignore")
    device_id: str
    state: str                       # steady | freeze | dark
    color: Optional[list[float]] = None
    fade_ms: int = 0
    since_ms: int = Field(default_factory=now_ms)
    source: str = ""                 # what put it there ("set:<id>", "action")


class LevelHold(BaseModel):
    """A temporary Level modifier. Several stack (they multiply)."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    device_ids: list[str]
    level: float
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    #: "time" (ends_at_ms) | "scene_change" | "released"
    until: str = "time"
    ends_at_ms: Optional[int] = None
    since_ms: int = Field(default_factory=now_ms)
    source: str = ""


class PulseModHold(BaseModel):
    """A Light Show modulation of the Pulse effect on some virtuals
    (spectra/services/show_mods.py; fx/pulse_modulation.py). A field left
    None is not this hold's business. Several stack: reactivities
    multiply, the highest floor and the lowest ceiling win."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    virtual_ids: list[str]
    #: his words for what was targeted ("Singles", "Hue Living Room")
    label: str = ""
    reactivity: Optional[float] = None
    floor: Optional[float] = None
    ceiling: Optional[float] = None
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    #: "time" (ends_at_ms) | "scene_change" | "released"
    until: str = "released"
    ends_at_ms: Optional[int] = None
    since_ms: int = Field(default_factory=now_ms)
    source: str = ""


class FlareBlock(BaseModel):
    """Flares switched OFF on some virtuals: while it holds, no flare kind
    writes to them (spectra/services/show_mods.py, scene_response's
    `_flare_states`)."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    virtual_ids: list[str]
    label: str = ""
    until: str = "released"
    ends_at_ms: Optional[int] = None
    since_ms: int = Field(default_factory=now_ms)
    source: str = ""


class SettingBaseline(BaseModel):
    """What a setting was before the show first changed it, and what the
    show last wrote. End show writes `original` back ONLY while the current
    value still equals `written` — anything he changed by hand since is his,
    left alone and named."""
    model_config = ConfigDict(extra="ignore")
    key: str                          # "room:display_mode", "scene:<id>", ...
    label: str = ""
    original: Any = None
    written: Any = None
    since_ms: int = Field(default_factory=now_ms)


class ShowArm(BaseModel):
    """A set (or one action) waiting for its trigger
    (spectra/services/show_arms.py is the binding statement)."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    set_id: Optional[str] = None
    action: Optional[ShowAction] = None
    #: the set's name when armed — the board still reads if it is renamed
    label: str = ""
    on: str = "scene_change"          # open list: scene_change | high | low | ...
    repeat: bool = False
    song_uri: Optional[str] = None    # "this song only" / a playlist script step
    source: str = "manual"            # manual | sonic | script:<id>
    #: a fade armed on High/Low starts early so it COMPLETES on the mark
    finish_on_mark: bool = True
    created_ms: int = Field(default_factory=now_ms)
    expires_ms: Optional[int] = None
    status: str = "armed"             # armed | fired | missed | disarmed | expired
    fire_count: int = 0
    ended_ms: Optional[int] = None
    end_reason: str = ""
    last_outcome: Optional[dict] = None


class LightShowState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    holds: dict[str, DeviceHold] = Field(default_factory=dict)
    levels: list[LevelHold] = Field(default_factory=list)
    baselines: dict[str, SettingBaseline] = Field(default_factory=dict)
    #: the room effect a show action started, if one is running
    room_effect: Optional[dict] = None
    arms: list[ShowArm] = Field(default_factory=list)
    started_ms: Optional[int] = None
    #: the Pulse modulations and flare switches the show is holding
    pulse_mods: list[PulseModHold] = Field(default_factory=list)
    flare_blocks: list[FlareBlock] = Field(default_factory=list)
