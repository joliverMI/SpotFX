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
    """A temporary Level modifier. Several on DIFFERENT device sets stack
    (they multiply) — show_output.add_level() replaces, rather than
    stacking, a hold on the exact same device set (his 2026-10-08 report:
    re-firing the same step must restart it, never queue a duplicate)."""
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
    None is not this hold's business. Two holds on DIFFERENT virtual sets,
    or on the same set but a DIFFERENT dimension (reactivity vs floor/
    ceiling), stack: reactivities multiply, the highest floor and the
    lowest ceiling win. A hold on the SAME virtual set and dimension
    REPLACES the matching one instead (his 2026-10-08 report: re-firing
    the same step must restart it, never queue a duplicate)."""
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
    `_flare_states`). Re-firing "flares off" on the exact same virtual set
    REPLACES the matching block (fresh until/ends_at) instead of stacking
    a second, visually-duplicate entry (his 2026-10-08 report)."""
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
    #: the Show Sequence that is running (or last ran), if any
    #: (spectra/services/show_sequence.py) — one at a time
    sequence_run: Optional["SequenceRun"] = None


# ── Show Sequences (the Admiral, 2026-10-09: "a sequence of pre-armed sets")
# spectra/services/show_sequence.py is the binding statement for how one
# runs. Like the sets, the LIBRARY (light_show_sequences.json) is his and is
# only written by an edit; the RUN lives in LightShowState above.

SEQUENCE_ARMS = ("instant", "scene_change", "high", "low")
"""How a Set item is armed — the same four timings the Run view's one-tap
buttons offer: bolt (instant), bunny (next scene change), up (next High
Trigger), down (next Low Trigger)."""

WAIT_KINDS = ("duration", "trigger_count", "songs", "song_list")
WAIT_TRIGGERS = ("scene_change", "high", "low")


class SongRef(BaseModel):
    """One song on a song-list Wait. Title/artist are carried so the list
    still reads when the song is no longer in the library."""
    model_config = ConfigDict(extra="ignore")
    uri: str
    title: str = ""
    artist: str = ""


class SequenceWait(BaseModel):
    """A Wait item's settings. Only the fields its `kind` names are read."""
    model_config = ConfigDict(extra="ignore")
    kind: str = "duration"           # duration | trigger_count | songs | song_list
    seconds: float = 60.0            # duration
    trigger: str = "scene_change"    # trigger_count: scene_change | high | low
    count: int = 1                   # trigger_count / songs
    songs: list[SongRef] = Field(default_factory=list)   # song_list


class SequenceItem(BaseModel):
    """A step of a sequence: a Set armed one of four ways, or a Wait."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    kind: str = "set"                # set | wait
    set_id: Optional[str] = None
    arm: str = "instant"             # SEQUENCE_ARMS
    wait: Optional[SequenceWait] = None
    #: his own words for this step (optional)
    label: str = ""


class ShowSequence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    name: str
    items: list[SequenceItem] = Field(default_factory=list)
    #: start again from the top after the last item (needs one item that
    #: waits for something, or it would spin)
    loop: bool = False
    notes: str = ""
    created_ms: int = Field(default_factory=now_ms)
    updated_ms: int = Field(default_factory=now_ms)


class SequenceLibrary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    sequences: list[ShowSequence] = Field(default_factory=list)


class SequenceRun(BaseModel):
    """A sequence being run. The items are a SNAPSHOT taken at start, so an
    edit made mid-show never shifts the position under it."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    sequence_id: str
    name: str
    items: list[SequenceItem] = Field(default_factory=list)
    loop: bool = False
    state: str = "running"           # running | paused | finished | stopped
    index: int = 0
    loops_done: int = 0
    started_ms: int = Field(default_factory=now_ms)
    ended_ms: Optional[int] = None
    end_reason: str = ""
    paused_reason: str = ""
    # the current item
    item_entered_ms: Optional[int] = None
    arm_id: Optional[str] = None     # a Set item's arm (show_arms)
    fired: bool = False              # an instant Set item has fired
    firing: bool = False             # an instant fire is in flight
    awaiting_fire: bool = False      # a manual step back onto an instant item
    waiting_reason: str = ""         # why the current item cannot act right now
    wait_count: int = 0              # triggers/songs counted so far
    wait_deadline_ms: Optional[int] = None
    wait_remaining_ms: Optional[int] = None   # a duration Wait, while paused
    #: the last song this run saw start — a restart re-sees the playing
    #: song and must not count it as a new one
    last_uri: Optional[str] = None
    log: list[dict] = Field(default_factory=list)


LightShowState.model_rebuild()
