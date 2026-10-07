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

#: The Hue directive's internal look kind for one bulb a house mode leaves
#: alone (HouseSettings.hue_excluded_lights); its area is "<area>/<bulb>".
#: Never authored on a mode — house.hue_directive adds it.
SKIP_LOOK = "skip"


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
    off     the fixture shows nothing (Dark on the output layer).
    music_level  percent while the MUSIC SHOW has the room (mode.music
            "show"), 100 = unchanged. Phase 2: Spectra owns each WLED's
            master brightness (house_fixtures.py writes 255), so the
            brightness Home Assistant's music scripts used to write
            (crystal 11-100%, strips 100%) lives here instead. None = the
            show runs at the picture's own brightness."""
    model_config = ConfigDict(extra="ignore")
    target: HouseTarget = Field(default_factory=HouseTarget)
    level: Optional[float] = Field(default=None, ge=0.0, le=200.0)
    motion: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fps: Optional[int] = Field(default=None, ge=1, le=60)
    off: bool = False
    music_level: Optional[float] = Field(default=None, ge=0.0, le=200.0)


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


#: Serenity's states (assist_satellite): idle is "put the look back".
VOICE_STATES = ("listening", "processing", "responding")
VOICE_IDLE = "idle"

#: A media source Home Assistant reports (the Roku, the Switch, the Blu-ray
#: player — or any other word it sends; the word is kept as given).
MEDIA_ACTIVE_STATES = ("playing", "paused", "idle")
MEDIA_STATES = MEDIA_ACTIVE_STATES + ("stopped",)


#: Home Assistant's three Serenity colours, read off his own automations
#: (serenity_listening / _processing / _responding, 2026-10-05): solid,
#: brightness 100%, on the crystal and both kitchen sconces.
DEFAULT_VOICE_LOOKS = {
    "listening": {"color": "#0000ff", "level": 100.0},
    "processing": {"color": "#26a269", "level": 100.0},
    "responding": {"color": "#613583", "level": 100.0},
}


class VoiceLook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    color: str = "#0000ff"
    #: percent of full, over Spectra's owned master brightness
    level: float = Field(default=100.0, ge=1.0, le=200.0)

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX.match(v or ""):
            raise ValueError("colour must look like #ffaa00")
        return v.lower()


#: Phase 3's default resting frame-rate caps (the plan's energy section,
#: data/standard-lighting-plan/report.md §6.3 E1): every calm mode gets
#: these unless one of its own fixture settings says otherwise. Keys are a
#: device CATEGORY or a fixture id; a cap only ever lowers a fixture's own
#: rate (fx/device_rate.py), so his crystal's 30 fps is a ceiling no cap
#: can raise.
DEFAULT_RESTING_FPS = {"Matrix": 20, "Strips": 20, "Singles": 10}


class HouseEnergy(BaseModel):
    """PHASE 3 — what a mode does to save energy and network while it drives
    the room (spectra/services/house_energy.py is the binding statement).

    resting_fps        frame-rate caps while the mode RESTS (and through
                       music in a calm/ignore mode): {category or fixture:
                       fps}. A mode's own fixture setting `fps` wins for the
                       fixtures it names. {} = no default caps.
    park_idle          a virtual none of whose fixtures takes its frames (a
                       dummy, a fixture lent / off / unpowered, a Hue area
                       held over the bridge) renders at 2 frames/s instead
                       of its full rate (fx/device_rate.py PARKING)
    send_on_change     a fixture whose picture is not changing is sent
                       nothing but a keep-alive every `keepalive_s`
                       (fx/device_output.py SEND ON CHANGE)
    keepalive_s        that keep-alive — must stay well inside the shortest
                       WLED realtime timeout in the room (the sconces' 2.5 s)
    audio_pause_after_s  stop listening to the room's audio after this long
                       with no music (0 = never). Listening resumes the
                       moment music plays."""
    model_config = ConfigDict(extra="ignore")
    resting_fps: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_RESTING_FPS))
    park_idle: bool = True
    send_on_change: bool = True
    keepalive_s: float = Field(default=1.0, ge=0.2, le=2.0)
    audio_pause_after_s: float = Field(default=120.0, ge=0.0, le=3600.0)

    @field_validator("resting_fps")
    @classmethod
    def _fps(cls, v: dict) -> dict:
        out: dict[str, int] = {}
        for k, fps in (v or {}).items():
            key = str(k or "").strip()
            if not key:
                continue
            n = int(fps)
            if n < 1 or n > 60:
                raise ValueError(f"resting fps for {key!r} must be 1-60")
            out[key] = n
        return out


class HouseSettings(BaseModel):
    """Phase 2's seam settings — HIS data, in the library file, edited only
    on purpose (PUT /api/house/settings).

    tv_strips        the fixture(s) lent to Hyperion while TV Music is off or
                     a media source is on (his TV backlight)
    voice_fixtures   where Serenity's listening/processing/responding colours
                     show (Home Assistant used the crystal and both sconces)
    voice_looks      one colour + level per voice state
    own_brightness   while a mode drives the room, Spectra manages every
                     WLED's power switch where the mode says. Its master
                     brightness is NEVER raised above the level HIS OWN
                     prior setting (Home Assistant or the fixture itself)
                     had it at — that captured level is the ceiling
                     (house_fixtures.py's `pre_take`), and the per-fixture
                     Levels dimmer only ever scales within it. The ceiling
                     can still RISE during the take — a later reading above
                     it with no reboot evidence behind it (its own uptime
                     never dropped) is HIS OWN deliberate increase and is
                     adopted into `pre_take` as the new ceiling, never
                     corrected back down; only a genuine reboot's brighter
                     boot preset is capped back to the prior ceiling.
                     Off = leave both power and brightness alone.
    owned_brightness an ADDITIONAL hard cap (0-255) on top of the preserved
                     ceiling above — never a value Spectra forces upward.
                     255 (the default) imposes no extra limit.

    PHASE 4:
    enabled          THE CUTOVER SWITCH. Off (the default) = house lighting
                     applies NOTHING: Home Assistant's lighting_mode is still
                     recorded and mapped (the status says which mode it would
                     be), but no look, level, Hue hold, brightness or lend
                     reaches a fixture, so a music take runs exactly as it did
                     before house lighting existed. On = a set mode drives the
                     room whenever SPECTRA holds it. Flipped on purpose — the
                     House tab's power button, or PUT /api/house/settings.
    hue_excluded_lights  Hue BULB names (his bridge's own names, any case)
                     a house mode never writes — not held, not switched off,
                     not reported. Empty by default: every bulb in Spectra's
                     entertainment areas is an ordinary house-mode bulb
                     (the Loft Ceiling Uplight and the three Ledge lights
                     included — carving them out as Home Assistant's was a
                     wrong assumption, corrected 2026-10-06). This is the
                     mechanism for a FUTURE bulb he genuinely wants Home
                     Assistant to keep, never a standing exclusion."""
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    hue_excluded_lights: list[str] = Field(default_factory=list)
    tv_strips: list[str] = Field(default_factory=lambda: ["tv-backlight"])
    voice_fixtures: list[str] = Field(default_factory=lambda: [
        "crystal", "sconce-kitchen-left", "sconce-kitchen-right"])
    voice_looks: dict[str, VoiceLook] = Field(default_factory=lambda: {
        k: VoiceLook(**v) for k, v in DEFAULT_VOICE_LOOKS.items()})
    own_brightness: bool = True
    owned_brightness: int = Field(default=255, ge=1, le=255)
    #: phase 3: energy and network (HouseEnergy above)
    energy: HouseEnergy = Field(default_factory=HouseEnergy)

    @field_validator("hue_excluded_lights")
    @classmethod
    def _light_names(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for name in v or []:
            name = (name or "").strip()
            if name and name.lower() not in {x.lower() for x in out}:
                out.append(name)
        return out

    @field_validator("voice_looks")
    @classmethod
    def _states(cls, v: dict) -> dict:
        bad = [k for k in v if k not in VOICE_STATES]
        if bad:
            raise ValueError(f"unknown voice state(s) {bad}; "
                             f"known: {list(VOICE_STATES)}")
        out = {k: VoiceLook(**DEFAULT_VOICE_LOOKS[k]) for k in DEFAULT_VOICE_LOOKS}
        out.update(v)
        return out


class HouseLibrary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = SCHEMA_VERSION
    modes: list[HouseMode] = Field(default_factory=list)
    settings: HouseSettings = Field(default_factory=HouseSettings)


class FixtureOverride(BaseModel):
    """What Home Assistant (or he) asked of ONE fixture, on top of the mode.

    power    "off" = the WLED is switched off and gets no stream; "on" or
             None = the mode decides (streamed, powered on)
    lent_to  a name ("hyperion") = Spectra stops streaming to it and lets
             go of it until it is reclaimed; None = not lent"""
    model_config = ConfigDict(extra="ignore")
    power: Optional[Literal["on", "off"]] = None
    lent_to: Optional[str] = None
    source: str = ""
    since_ms: Optional[int] = None


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
    # ── phase 2: what Home Assistant reports (spectra/services/house.py's
    #    MEDIA and house_fixtures.py) — facts, recorded whatever the room's
    #    state, acted on only while a mode drives it ──
    #: switch.tv_music_lighting as last reported; None = never reported
    tv_music: Optional[bool] = None
    tv_music_ms: Optional[int] = None
    #: the media source on (roku / switch / bluray / ...) and its state;
    #: None or "stopped" = no media centre
    media_source: Optional[str] = None
    media_state: Optional[str] = None
    media_since_ms: Optional[int] = None
    #: per-fixture overrides (device id -> FixtureOverride)
    fixtures: dict[str, FixtureOverride] = Field(default_factory=dict)
    #: phase 3: fixtures whose MAINS Home Assistant reports OFF (his kitchen
    #: sconces on light.dimmer_kitchen_sconce) -> since when (ms). While a
    #: mode drives the room Spectra neither streams to them nor searches
    #: for them; "mains on" (or a recheck naming them) clears the entry.
    mains_off: dict[str, int] = Field(default_factory=dict)
    #: phase 3: what each WLED's power and master brightness were BEFORE
    #: Spectra first took them over (device -> {"on", "bri", "ip",
    #: "at_ms"}) — handed back when the room is released, so a fixture
    #: that was off before a take is off after it (house_fixtures.py
    #: HAND-BACK). The first reading wins until it has been handed back.
    pre_take: dict[str, dict] = Field(default_factory=dict)
