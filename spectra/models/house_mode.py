"""HOUSE LIGHTING's data model — the always-on resting look (the Admiral,
2026-10-04: "I'd like to use spectra as my standard lighting engine, not
just for music ... the lighting modes (standard, evening, dim, etc) are
definable within spectra and can be triggered from Home Assistant").
Plan: /home/javi/fleet-spotfx/data/standard-lighting-plan/report.md §4.

A MODE is what the room looks like when nothing more specific is happening:
which scenes and colour sets it flows through, how bright and how fast each
fixture is, how the Hue bulbs are held, and what music does on top of it.
spectra/services/house.py is the layer that applies one; read its docstring
for precedence and the music hand-in/hand-out.

Two stores, the Light Show's split:

  house_modes.json   HIS LIBRARY. Only an explicit edit writes it.
  house_state.json   RUNTIME — which mode is set, by whom, since when, and
                     the last value Home Assistant sent. Churns on every HA
                     call; can never damage his modes.

HOME ASSISTANT'S WORDS ARE ALIASES, not names. Each mode lists the
`input_select.lighting_mode` value(s) it answers to (Standard ← "Daytime"),
so neither side renames anything. An alias belongs to exactly one mode.

Every model is `extra="ignore"` with every field defaulted, so a file a
later phase writes still loads here.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

MusicPolicy = Literal["show", "calm", "ignore"]
MusicHue = Literal["hold", "join", "room"]
HueLookKind = Literal["hold", "off", "show"]
TargetKind = Literal["fixture", "category", "everything"]

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

#: Hue's own colour-temperature range on his bulbs (CLIP v2 mirek 153..500).
KELVIN_MIN = 2000
KELVIN_MAX = 6500

#: "*" in a Hue look means every Hue area the room drives.
EVERY_AREA = "*"


def _id() -> str:
    return uuid.uuid4().hex[:12]


def now_ms() -> int:
    return int(time.time() * 1000)


class HouseTarget(BaseModel):
    """One fixture (a device id), one category, or everything — the Light
    Show's own target shape, resolved by show_output.resolve_target."""
    model_config = ConfigDict(extra="ignore")
    kind: TargetKind = "everything"
    id: Optional[str] = None

    @model_validator(mode="after")
    def _needs_id(self):
        if self.kind != "everything" and not self.id:
            raise ValueError(f"a {self.kind} target needs an id")
        return self


class ScenePick(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene_id: str
    weight: float = Field(default=1.0, ge=0.0, le=100.0)


class ColorPick(BaseModel):
    """A colour SET or GROUP card. A group keeps its own rotation and
    overrides; its members join the colour journey's pool."""
    model_config = ConfigDict(extra="ignore")
    card_id: str
    weight: float = Field(default=1.0, ge=0.0, le=100.0)


class FixtureHook(BaseModel):
    """Per-fixture (or per-category) settings while the mode rests.

    level   percent of the picture's own brightness, 100 = unchanged (a
            Level on the per-device output layer, below any Light Show hold).
    motion  the resting speed: a position in the effect's own motion
            parameter range, 0 = its slowest, 1 = its fastest. Applied only
            to effects whose registry tags a motion parameter
            (config/effect_params.json `"motion": true`).
    fps     a frame-rate CAP (only ever lowers a fixture's own rate).
    off     the fixture shows nothing (Dark on the output layer)."""
    model_config = ConfigDict(extra="ignore")
    target: HouseTarget = Field(default_factory=HouseTarget)
    level: Optional[float] = Field(default=None, ge=0.0, le=200.0)
    motion: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fps: Optional[int] = Field(default=None, ge=1, le=60)
    off: bool = False


class HueLook(BaseModel):
    """How one Hue area (a Hue device id, or "*" for every area) is held
    while the mode rests — over the bridge, never streamed.

    hold   a colour temperature (kelvin) OR a colour, at `brightness`
    off    the bulbs are switched off over the bridge
    show   not held: the area follows the room's stream"""
    model_config = ConfigDict(extra="ignore")
    area: str = EVERY_AREA
    look: HueLookKind = "hold"
    kelvin: Optional[int] = Field(default=None, ge=KELVIN_MIN, le=KELVIN_MAX)
    color: Optional[str] = None
    brightness: float = Field(default=100.0, ge=1.0, le=100.0)

    @field_validator("color")
    @classmethod
    def _hex(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _HEX.match(v):
            raise ValueError("colour must look like #ffaa00")
        return v.lower()

    @model_validator(mode="after")
    def _hold_needs_one(self):
        if self.look == "hold" and self.kelvin is None and self.color is None:
            raise ValueError("a held Hue look needs a colour temperature or a colour")
        if self.kelvin is not None and self.color is not None:
            raise ValueError("a Hue look is a colour temperature OR a colour, not both")
        return self

    @property
    def mirek(self) -> Optional[int]:
        return round(1_000_000 / self.kelvin) if self.kelvin else None


class HouseFlow(BaseModel):
    """How the mode moves when no music plays.

    scene_every_min    draw a new scene from the pool this often (0 = keep
                       the first one for as long as the mode lasts)
    journey_deg_per_min  the colour journey's pace through the mode's sets
    intensity          what the mode's scenes are resolved at (their own
                       intensity bindings), music or not"""
    model_config = ConfigDict(extra="ignore")
    scene_every_min: float = Field(default=45.0, ge=0.0, le=1440.0)
    journey_deg_per_min: float = Field(default=15.0, ge=0.0, le=360.0)
    intensity: float = Field(default=0.25, ge=0.0, le=1.0)


class HouseTransitions(BaseModel):
    """clock_glide_s   entering this mode because Home Assistant's clock
                       moved (the 18:30 change)
       button_glide_s  entering it on a person's press (UI, Sonic, a button)
       music_debounce_s  how long music must stay stopped before the room
                       glides back (a pause or a track gap never flaps)
       music_return_glide_s  that glide back"""
    model_config = ConfigDict(extra="ignore")
    clock_glide_s: float = Field(default=90.0, ge=0.0, le=600.0)
    button_glide_s: float = Field(default=5.0, ge=0.0, le=600.0)
    music_debounce_s: float = Field(default=60.0, ge=0.0, le=900.0)
    music_return_glide_s: float = Field(default=20.0, ge=0.0, le=600.0)


class HouseMode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_id)
    name: str
    #: Home Assistant `lighting_mode` values this mode answers to
    ha_aliases: list[str] = Field(default_factory=list)
    scenes: list[ScenePick] = Field(default_factory=list)
    color_sets: list[ColorPick] = Field(default_factory=list)
    flow: HouseFlow = Field(default_factory=HouseFlow)
    fixtures: list[FixtureHook] = Field(default_factory=list)
    #: empty = the mode leaves Hue to the Hue Hold room setting
    hue: list[HueLook] = Field(default_factory=list)
    #: what music does on top of this mode: the full show, keep the mode's
    #: scene (flares only), or nothing at all
    music: MusicPolicy = "show"
    #: Hue while music plays: stay held at the mode's look, join the show's
    #: stream, or follow the Hue Hold room setting (HA's Bright/Dark)
    music_hue: MusicHue = "hold"
    transitions: HouseTransitions = Field(default_factory=HouseTransitions)
    notes: str = ""
    created_ms: int = Field(default_factory=now_ms)
    updated_ms: int = Field(default_factory=now_ms)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("a mode needs a name")
        return v

    @field_validator("ha_aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for a in v:
            a = (a or "").strip()
            if a and a.lower() not in {x.lower() for x in out}:
                out.append(a)
        return out

    def answers_to(self, ha_value: str) -> bool:
        low = (ha_value or "").strip().lower()
        return bool(low) and any(a.lower() == low for a in self.ha_aliases)


class HouseLibrary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    modes: list[HouseMode] = Field(default_factory=list)


class HouseState(BaseModel):
    """Which mode is set and why. `manual` = a person picked it (the UI,
    Sonic, a dashboard), so it holds until Home Assistant's value next
    CHANGES — HA's 5-minute re-assert of the same value is a no-op."""
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    mode_id: Optional[str] = None
    source: str = ""
    since_ms: Optional[int] = None
    manual: bool = False
    #: the glide the current mode was entered with
    glide_s: float = 0.0
    #: the last lighting_mode value Home Assistant sent, mapped or not
    ha_value: Optional[str] = None
    ha_value_ms: Optional[int] = None
    #: the scene / colour card the mode last drew — re-used after a restart
    #: so a Spectra restart keeps the picture instead of re-rolling it
    scene_id: Optional[str] = None
    color_card_id: Optional[str] = None
