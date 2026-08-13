"""SPECTRA scene model — the SceneV2 port, grown per the accepted
editor/drift design (data/spectra-editor-drift-design/report.md §2.2, as
amended by decision-review-answers.md).

A scene = INITIAL CONDITIONS (every value fixed, ⚡-mapped, or 🎲-rolled)
plus DECLARED MECHANISMS:
  drift      — per-param creep/follow declarations (named profile with an
               inline one-off escape hatch, decision-4 pattern)
  responses  — the four event classes (flare/charge/lull/drop), each an
               intensity-banded ResponseSpec; legacy `flare_bands` JSON
               loads unchanged as the flare class
  color_journey — the room owns ONE continuous colour journey BY DEFAULT;
               a scene may OVERRIDE it outright as a first-class capability
               (owner's color-drift-scope answer). Transition semantics
               into/out of an override live in services/color_journey.py.

Loader-compatible with spot-effects' storage/scenes_v2.json: every current
value is a plain scalar and scalars remain legal everywhere; a legacy
`flare_bands` key becomes responses["flare"].bands on load. The S2 evolution
engine consumes the declarations; S1 stores, edits, resolves (test-fire) and
dry-run compiles them.

Executable spec: scripts/check_spectra.py
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from spectra.models.binding import ValueBinding

SceneParamScalar = bool | int | float | str
SceneParamValue = SceneParamScalar | ValueBinding

RESPONSE_CLASSES = ("flare", "charge", "lull", "drop")
ResponseClass = Literal["flare", "charge", "lull", "drop"]


class SceneColorAssignment(BaseModel):
    # "set": active Color Set owns colors at fire time; "fixed": scene pins
    # them. Colour strings are the one un-bindable value on the Initial Set
    # page — palette variation is the colour-set system's job.
    mode:        Literal["set", "fixed"] = "set"
    color_kind:  Optional[Literal["gradient", "solid"]] = None
    color_value: str | None = None   # solid hex or linear-gradient string
    bg_color:    str | None = None
    bg_mode:     Optional[Literal["additive", "overwrite"]] = None


class CurveMapPoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)   # intensity axis
    y: float                            # parameter value (any range)


class DriftSpec(BaseModel):
    """One drift mechanism — the named-profile body.

    creep: bounded autonomous wander — next target = position + rate·leg,
    reflected ("bounce") or wrapped at [lo, hi].
    follow: the value tracks the music's energy arc through a drawn
    intensity→value curve (points share the sequencer CurvePoint shape;
    y IS the parameter value here, not a likelihood), gliding over slew_s.
    """
    kind: Literal["creep", "follow"]
    # creep
    rate_per_min: float = 0.0
    lo: float = 0.0
    hi: float = 1.0
    motion: Literal["bounce", "wrap"] = "bounce"
    # follow — exactly one of curve_ref (named sequencer CurveProfile id) /
    # inline_points may be set; slew_s is the re-assert glide time.
    curve_ref: Optional[str] = None
    inline_points: Optional[list["CurveMapPoint"]] = None
    slew_s: float = Field(default=10.0, gt=0.0)

    @model_validator(mode="after")
    def _validate(self) -> "DriftSpec":
        if self.kind == "creep":
            if self.lo >= self.hi:
                raise ValueError(f"creep bounds need lo < hi (got {self.lo} >= {self.hi})")
        if self.curve_ref is not None and self.inline_points is not None:
            raise ValueError("follow may set curve_ref or inline_points, not both")
        return self


class DriftRef(BaseModel):
    """A scene's drift declaration for one param: a NAMED profile (one edit
    retunes every scene using it — "put Slow Wander on Orbits") or an inline
    one-off. Exactly one must be set."""
    profile: Optional[str] = None       # drift_profiles store id
    inline: Optional[DriftSpec] = None

    @model_validator(mode="after")
    def _one_of(self) -> "DriftRef":
        if (self.profile is None) == (self.inline is None):
            raise ValueError("drift declaration needs exactly one of profile / inline")
        return self


class SceneDeviceConfig(BaseModel):
    # "all" targets every imported virtual (target stays empty); category
    # targets expand to member virtuals at compile time. Narrower entries
    # override wider ones: all < category < virtual.
    id:          str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_kind: Literal["all", "category", "virtual"] = "category"
    target:      str = ""
    effect_type: str = ""
    params:      dict[str, SceneParamValue] = Field(default_factory=dict)
    color:       SceneColorAssignment = Field(default_factory=SceneColorAssignment)
    brightness:            float | ValueBinding | None = None  # None = leave alone
    background_brightness: float | ValueBinding | None = None
    # param name → drift declaration (creep / follow). The S2 conductor
    # executes these; S1 stores and edits them.
    drift: dict[str, DriftRef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_entry(self) -> "SceneDeviceConfig":
        for field in ("brightness", "background_brightness"):
            v = getattr(self, field)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if not 0.0 <= float(v) <= 1.0:
                    raise ValueError(f"{field} must be within [0, 1], got {v}")
        for pname in self.drift:
            if pname not in self.params and pname not in (
                    "brightness", "background_brightness"):
                raise ValueError(
                    f"drift declared for '{pname}' but the entry sets no such param")
        return self


class FlareBand(BaseModel):
    # Response when the event class fires with intensity in [min, max).
    # gain is the momentary envelope (band curve: pulse spikes and returns;
    # linear/ease_* land and hold); param_patch is a JUMP — agent-authored,
    # shown in the UI only as a read-only indicator (flare-patch-ui answer).
    intensity_min: float = Field(default=0.0, ge=0.0, le=1.0)
    intensity_max: float = Field(default=1.0, ge=0.0, le=1.0)
    curve: Literal["linear", "ease_in", "ease_out", "pulse"] = "linear"
    gain:  float = Field(default=1.0, ge=0.0)
    param_patch: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _band_ordered(self) -> "FlareBand":
        if self.intensity_min >= self.intensity_max:
            raise ValueError(
                f"band intensity_min ({self.intensity_min}) must be "
                f"< intensity_max ({self.intensity_max})")
        return self


class ResponseSpec(BaseModel):
    """One event class's response. The S2 engine: pick the band containing
    the fire intensity; apply patch-as-jump + gain envelope; re-roll the
    scene's 🎲 dice when reroll_dice; on flares with color_set_jump, roll the
    colour-set selector and JUMP (not blend) to the pick — terminal rung
    keeps current colours. Surges CARRY: the new baseline is where drift
    resumes from."""
    bands: list[FlareBand] = Field(default_factory=list)
    reroll_dice: bool = True
    color_set_jump: bool = False   # migration seeds True on the flare class

    @model_validator(mode="after")
    def _no_overlap(self) -> "ResponseSpec":
        bands = sorted(self.bands, key=lambda b: b.intensity_min)
        for a, b in zip(bands, bands[1:]):
            if b.intensity_min < a.intensity_max:
                raise ValueError(
                    f"bands overlap: [{a.intensity_min}, {a.intensity_max}) "
                    f"and [{b.intensity_min}, {b.intensity_max})")
        return self


class ColorJourneySpec(BaseModel):
    """A DESTINATION-DRIVEN colour journey: the walk always has a target — a
    destination colour set picked by the shipped selector (curve × genre ×
    wheel-travel) — and travels toward it along the shortest arc; on arrival
    it selects the next destination and sets off again. Never aimless creep.

    degrees_per_min is the REFERENCE pace, and the destination fixes its own
    pace at selection: a destination 90° away travels at exactly this pace,
    nearer ones stroll (down to ×0.5), farther ones hurry (up to ×2.0) —
    services/color_journey.destination_pace. 0 holds the walk (no
    destinations picked). The owner's live room value is 30°/min — that is
    this default; a stored value always carries verbatim. Rainbow or
    achromatic palettes pause the walk (no wheel position — the binding
    exemption)."""
    degrees_per_min: float = 30.0


class SceneColorJourney(BaseModel):
    """The colour-journey field (owner's answer, refined): ROOM-LEVEL journey
    by default — inherit rides the room's walk, pace_factor scaling it
    (0 = hold while this scene shows). OVERRIDE is first-class: the scene's
    own journey replaces the room walk outright while the scene holds.
    Transition semantics (services/color_journey.py): an override takes
    CUSTODY of the room's wheel position, never a fork of it — entering seeds
    the override from the room's current position; leaving hands the position
    back and the room's own pace resumes from wherever the override left it.
    No snap in either direction."""
    mode: Literal["inherit", "override"] = "inherit"
    pace_factor: float = Field(default=1.0, ge=0.0)
    journey: Optional[ColorJourneySpec] = None

    @model_validator(mode="after")
    def _override_shape(self) -> "SceneColorJourney":
        if self.mode == "override" and self.journey is None:
            raise ValueError("override journey needs a journey spec")
        if self.mode == "inherit" and self.journey is not None:
            raise ValueError("inherit journey must not carry a journey spec")
        return self


class PhaseChoreography(BaseModel):
    # anchor_frac: crossfade fraction where the payoff lands; the engine
    # fires the switch early by anchor_frac × transition_ms.
    enabled:         bool = False
    transition_ms:   int = Field(default=800, ge=0, le=20000)
    transition_mode: str = "Add"
    anchor_frac:     float = Field(default=0.45, ge=0.0, le=1.0)


class SceneV2(BaseModel):
    id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:   str
    labels: list[str] = Field(default_factory=list)
    devices: list[SceneDeviceConfig] = Field(default_factory=list)
    responses: dict[ResponseClass, ResponseSpec] = Field(default_factory=dict)
    color_journey: SceneColorJourney = Field(default_factory=SceneColorJourney)
    choreography: PhaseChoreography = Field(default_factory=PhaseChoreography)
    # accept_all_sets=True: every set not globally opted out is eligible;
    # False narrows to accepted_set_ids.
    accept_all_sets:  bool = True
    accepted_set_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _flare_bands_shim(cls, data):
        # Legacy spot-effects scenes carry flare_bands=[...]; it loads
        # unchanged as the flare class. Canonical form is `responses` — an
        # input carrying both keeps `responses` and drops the legacy key.
        if isinstance(data, dict) and "flare_bands" in data:
            data = dict(data)
            bands = data.pop("flare_bands")
            responses = dict(data.get("responses") or {})
            if bands and "flare" not in responses:
                responses["flare"] = {"bands": bands}
            data["responses"] = responses
        return data

    @model_validator(mode="after")
    def _validate(self) -> "SceneV2":
        seen: set[tuple[str, str]] = set()
        for dev in self.devices:
            if dev.target_kind == "all":
                if dev.target:
                    raise ValueError(
                        f"all-devices entry must not name a target (got '{dev.target}')")
            elif not dev.target:
                raise ValueError("device entry has an empty target")
            if not dev.effect_type:
                raise ValueError(f"device entry for '{dev.target}' has no effect_type")
            key = (dev.target_kind, dev.target)
            if key in seen:
                raise ValueError(f"duplicate device entry for {dev.target_kind} '{dev.target}'")
            seen.add(key)
        return self

    def accepts_color_set(self, card) -> bool:
        # Two-way filter (design answer 3): the set's global opt-out wins.
        if getattr(card, "scene_v2_opt_out", False):
            return False
        if self.accept_all_sets:
            return True
        return card.id in self.accepted_set_ids

    def dice_letters(self) -> list[str]:
        """Every dice letter used by the scene's 🎲 bindings, sorted."""
        letters: set[str] = set()
        for dev in self.devices:
            for value in (*dev.params.values(), dev.brightness,
                          dev.background_brightness):
                if isinstance(value, ValueBinding) and value.dice:
                    letters.add(value.dice)
        return sorted(letters)


class ColorWheelPosition(BaseModel):
    # position_deg None: rainbow set (span > 180°) or achromatic.
    set_id:       str
    position_deg: float | None = None
    rainbow:      bool = False
    span_deg:     float = 0.0
    resultant:    float = 0.0
