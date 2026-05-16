"""
SpotFX — Music Event data models.

A MusicEvent is either:
  - A single action chosen randomly from a weighted list (type="single")
  - A sequence of other MusicEvents with delays (type="sequence")

Supported action types:
  ledfx_scene           — activate a named LedFX scene
  ledfx_ambient         — patch Single Color Effect (color, blur, etc.)
  ledfx_ambient_color   — apply complementary color to Single Color Effect (cache-based, no latency)
  ledfx_global_brightness — set LedFX global brightness
  ledfx_global_transition — set LedFX global transition time / mode
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field
import uuid


class ActionLabel(BaseModel):
    """A filterable label attached to an action or sequence step."""
    name: str  # lowercase enforced on use; prefix '-' means 'not'


class LedFxSceneAction(BaseModel):
    """Trigger a specific LedFX scene by name."""
    type: Literal["ledfx_scene"] = "ledfx_scene"
    scene_id: str
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0


class LedFxAmbientAction(BaseModel):
    """
    Patch the Single Color Effect virtual (single-color-effect, Power effect).
    All fields optional — None means 'don't change that parameter'.
    color sets gradient, background_color, and sparks_color together.
    """
    type: Literal["ledfx_ambient"] = "ledfx_ambient"
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0
    color: str | None = None               # hex → gradient + background_color + sparks_color
    brightness: float | None = None        # Power effect brightness (0–1)
    max_brightness: float | None = None    # virtual max_brightness cap (0–1)
    blur: float | None = None
    bass_decay_rate: float | None = None
    background_brightness: float | None = None


class LedFxAmbientColorAction(BaseModel):
    """
    Reads the current Single Color Effect color from the polled cache and applies
    the complementary color (180° hue rotation). No parameters — always contrasts
    whatever is currently showing. Zero extra latency at fire time.
    """
    type: Literal["ledfx_ambient_color"] = "ledfx_ambient_color"
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0



class LedFxGlobalBrightnessAction(BaseModel):
    """Set the LedFX global brightness knob."""
    type: Literal["ledfx_global_brightness"] = "ledfx_global_brightness"
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0
    brightness: float  # 0.0–1.0
    ramp_ms: int | None = None   # None = use settings.smooth_ramp_ms; 0 = instant


class LedFxGlobalTransitionAction(BaseModel):
    """Set the LedFX global transition time (and optionally transition mode)."""
    type: Literal["ledfx_global_transition"] = "ledfx_global_transition"
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0
    transition_time: float           # seconds
    transition_mode: str | None = None  # e.g. "Add", "Dissolve"


class EventRefAction(BaseModel):
    """Reference to another event — when selected, fires from that event's action pool."""
    type: Literal["event_ref"] = "event_ref"
    event_id: str = ""
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0


class MorphScope(BaseModel):
    """Where a Morph target lands. Union semantics: any virtual matched by any field is in scope.
    Empty across all three = global (all known virtuals)."""
    virtual_ids: list[str] = Field(default_factory=list)
    categories:  list[str] = Field(default_factory=list)
    roles:       list[str] = Field(default_factory=list)


class AspectValue(BaseModel):
    """Polymorphic value for one MorphTarget. Only the fields relevant to the
    target's aspect are inspected by the compiler; the rest are ignored.

      aspect=brightness | reactivity | blur  → number
      aspect=color                            → color_kind + color_value
      aspect=bg_color                         → bg_color
      aspect=shape                            → any subset of {polygon, star, edges, twist, flip}
      aspect=effect                           → effect_type
    """
    number:       float | None = None
    color_kind:   Optional[Literal["gradient", "solid"]] = None
    color_value:  str | None = None
    bg_color:     str | None = None
    polygon:      bool | None = None
    star:         float | None = None
    edges:        int | None = None
    twist:        float | None = None
    flip:         bool | None = None
    effect_type:  str | None = None


MorphAspect = Literal[
    "shape", "effect", "color", "bg_color", "reactivity", "brightness", "blur",
]


class MorphTarget(BaseModel):
    """One aspect change on one scope. A MorphStepAction has a list of these."""
    scope:            MorphScope = Field(default_factory=MorphScope)
    aspect:           MorphAspect
    mode:             Literal["absolute", "nudge"] = "absolute"
    absolute_value:   AspectValue = Field(default_factory=AspectValue)
    nudge_amount:     float = 0.0
    intensity_scale:  float = 0.0       # 0 = ignore beat intensity, 1 = full RMS scaling
    intensity_source: Literal["rms_total", "rms_bass", "onset_score"] = "rms_total"
    ramp_ms:          int | None = None  # overrides MorphStepAction.ramp_ms when set


class MorphStepAction(BaseModel):
    """A composable, multi-target change across Aspects (Shape/Effect/Color/BG Color/
    Reactivity/Brightness/Blur). Replaces the need for pre-configured LedFX scenes for
    parameter-level transitions. See `services/morph_compiler.py` for the per-target
    Aspect-to-raw-param translation."""
    type:    Literal["morph_step"] = "morph_step"
    labels:  list[str] = Field(default_factory=list)
    weight:  float = 1.0
    ramp_ms: int | None = None  # default for targets that don't override
    targets: list[MorphTarget] = Field(default_factory=list)


class EffectParamChange(BaseModel):
    """One parameter change within a LedFxEffectParamAction."""
    param_label: str          # unified label e.g. "Reactivity", "Effect Brightness"
    target_value: float = 0.0 # numeric value; ignored for toggle/color/gradient/polar params
    toggle_action: str | None = None  # "on", "off", "toggle" — only for toggle-type params
    string_value: str | None = None   # hex color or CSS gradient string — for color/gradient params
    flip_sign:    bool         = False  # if True: apply abs(target_value) with opposite sign of current
    polar_angle:  float | None = None   # degrees, 0=top (y=1,x=0), clockwise — for polar-type params
    polar_radius: float | None = None   # 0..1 in frontend space — for polar-type params
    move_x:       float | None = None   # delta x in frontend -1..1 space (move_xy type)
    move_y:       float | None = None   # delta y in frontend -1..1 space (move_xy type)
    move_angle:   float | None = None   # delta degrees, positive = clockwise (move_polar type)
    move_radius:  float | None = None   # delta radius in frontend 0..1 space (move_polar type)


class LedFxEffectParamAction(BaseModel):
    """
    Set one or more effect parameters by unified label.

    The LABEL is the primary target — applies to every virtual whose active effect has a
    matching parameter. virtual_id and category are optional scope filters; if neither is
    set, all known virtuals are candidates.

    Scope resolution order: virtual_id > category > global (all virtuals).
    Virtuals whose active effect doesn't support a given label are silently skipped.
    """
    type: Literal["ledfx_effect_param"] = "ledfx_effect_param"
    labels: list[str] = Field(default_factory=list)   # action filter labels
    weight: float = 1.0
    virtual_id: str | None = None   # e.g. "crystal-mapper"
    category: str | None = None     # e.g. "Matrix" | "Strips" | "Singles"
    params: list[EffectParamChange] = Field(default_factory=list)
    ramp_ms: int | None = None      # None = use settings.smooth_ramp_ms; 0 = instant


# Discriminated union of all action types
Action = Annotated[
    EventRefAction
    | LedFxSceneAction
    | LedFxAmbientAction
    | LedFxAmbientColorAction
    | LedFxGlobalBrightnessAction
    | LedFxGlobalTransitionAction
    | LedFxEffectParamAction
    | MorphStepAction,
    Field(discriminator="type"),
]


class MorphLane(BaseModel):
    """One lane in a `morph_set` MusicEvent. Each lane is a pool of alternative
    Actions; at fire time the engine picks ONE per lane (weighted random, with
    label filtering) and fires all picks concurrently. Lane labels merge with
    the trigger-level filter labels before selection."""
    name:         str = ""
    labels:       list[str] = Field(default_factory=list)
    alternatives: list[Action] = Field(default_factory=list)


class SequenceStep(BaseModel):
    """One step in a MusicEvent sequence — either an event reference or a raw action."""
    step_type: Literal["event", "action"] = "event"
    event_id: Optional[str] = None     # used when step_type == "event"
    action: Optional[Action] = None    # used when step_type == "action"
    actions: list[Action] = Field(default_factory=list)  # multi-action: all fire concurrently
    delay_ms: int = 0                  # delay before this step fires
    labels: list[str] = Field(default_factory=list)


class RevertConfig(BaseModel):
    """
    Optional revert step appended to a sequence event.
    Before the sequence fires, SpotFX snapshots the LedFX values that the
    sequence will change. After the last step fires (plus delay_ms), those
    values are restored. transition_ms controls the ramp for global brightness;
    effect params and virtual configs revert instantly (LedFX's own transition
    handles the visual blend).
    """
    enabled: bool = True
    delay_ms: int = 0        # extra hold time after ALL steps (incl. ramps) complete
    transition_ms: int = 500  # ramp duration for global brightness restore


class BeatSequenceStep(BaseModel):
    """One step in a MusicEvent beat sequence — fires on a specific song beat."""
    step_type: Literal["event", "action"] = "action"
    event_id: Optional[str] = None     # used when step_type == "event"
    action: Optional[Action] = None    # used when step_type == "action"
    actions: list[Action] = Field(default_factory=list)  # multi-action: all fire concurrently
    delay_beats: int = 0               # 0=consecutive next beat, N=skip N beats
    pre_ramp: bool = True              # start ramp ramp_ms before the beat so it completes on beat
    labels: list[str] = Field(default_factory=list)


class BeatRevertConfig(BaseModel):
    """Revert config for beat sequence events — timing in beats, not milliseconds."""
    enabled: bool = True
    delay_beats: int = 0       # beats to wait after last step's beat before reverting
    transition_ms: int = 500   # ramp duration for restoration
    pre_ramp: bool = True      # start revert ramp early so it completes on the target beat


class MusicEvent(BaseModel):
    """
    A named, reusable music event that defines what happens at a trigger point.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    event_type: Literal["single", "sequence", "beat_sequence", "morph_set"] = "single"
    color: str = "#FFD700"     # hex color shown on timeline
    labels: list[str] = Field(default_factory=list)
    energy_level: int | None = None    # 1–10; None = energy-agnostic
    ai_exposed: bool = False           # True = include in AI trigger generation prompts

    # Pre-commands — fired before the main action (single) or before the first step (sequence / beat_sequence)
    pre_brightness_enabled: bool = True
    pre_brightness_value: float = 1.0
    pre_brightness_ramp_ms: int | None = None   # None = use settings.smooth_ramp_ms; 0 = instant
    pre_transition_enabled: bool = True
    pre_transition_value: float = 0.5   # seconds

    # For event_type == "single": randomly picked from this list
    actions: list[Action] = Field(default_factory=list)

    # For event_type == "sequence"
    sequence_steps: list[SequenceStep] = Field(default_factory=list)
    revert: Optional[RevertConfig] = None

    # For event_type == "beat_sequence"
    beat_sequence_steps: list[BeatSequenceStep] = Field(default_factory=list)
    beat_revert: Optional[BeatRevertConfig] = None
    beat_sequence_fallback: Literal["skip", "fallback"] = "fallback"
    beat_sequence_start_offset_beats: int = 0  # beats to shift entire sequence (negative = earlier)

    # For event_type == "morph_set" — each lane independently picks one Action
    # to fire; all picks fire concurrently. pre_brightness_* / pre_transition_*
    # are intentionally NOT applied to morph_set events (brightness now lives
    # on the Morph Step targets themselves and global scene transitions are gone).
    morph_lanes: list[MorphLane] = Field(default_factory=list)

    # Timing offset: shift when this event fires (negative = earlier, positive = later)
    event_offset_ms: int = 0

    # Internal: id of last-called action (to avoid repeating), not persisted
    _last_action_id: str | None = None
