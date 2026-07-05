"""
SpotFX — Music Event data models.

A MusicEvent is either:
  - A single action chosen randomly from a weighted list (type="single")
  - A sequence of other MusicEvents with delays (type="sequence")

Supported action types:
  ledfx_scene           — activate a named LedFX scene
  ledfx_ambient         — patch Single Color Effect (color, blur, etc.)
  ledfx_ambient_color   — apply complementary color to Single Color Effect (cache-based, no latency)
  ledfx_global_transition — set LedFX global transition time / mode
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field
import uuid

from models.value_binding import ValueBinding


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


class NumericNudge(BaseModel):
    """Per-element nudge spec used in Shape sub-fields when mode='nudge'.
    amount: nudge magnitude in abstract 0..1 space (negative ok)
    scale:  intensity_scale — 0 ignores intensity, 1 fully modulates.
    wrap:   when True, reflect off min/max and reverse direction on future
            fires so the value bounces instead of sticking at a boundary.
    lo/hi:  optional custom nudge range (None = the effect param's full range);
            clamping/bounce use these bounds. For x/y offset they are in the
            frontend −1..1 space."""
    amount: float = 0.0
    scale:  float = 0.0
    wrap:   bool = False
    lo:     float | None = None
    hi:     float | None = None


class AspectValue(BaseModel):
    """Polymorphic value for one MorphTarget. Only the fields relevant to the
    target's aspect are inspected by the compiler; the rest are ignored.

      aspect=brightness | reactivity | blur  → number (target.mode controls nudge vs absolute)
                                                brightness / reactivity may also carry
                                                scale_overrides (per-param weight overrides
                                                — e.g. split fg vs bg brightness; see below)
      aspect=color                            → color_kind + color_value
      aspect=bg_color                         → bg_color
      aspect=shape                            → any subset of {polygon, star, edges, twist, flip}
                                                Booleans (polygon, flip) accept True, False,
                                                or "toggle" (flip the current cached value).
                                                When target.mode='nudge', the numeric sub-fields
                                                (star, edges, twist) use their *_nudge specs
                                                instead of their absolute value.
      aspect=effect                           → effect_type
    """
    number:       float | ValueBinding | None = None
    # Per-param weight overrides for the numeric-distribution aspects (brightness
    # and reactivity in the UI; blur maps to a single param so the editor is
    # suppressed). Keyed by "{effect_type}.{param_name}", each value replaces that
    # param's default `aspect_scale` from effect_params.json when the single
    # `number` slider is distributed across the aspect's params. Absent / unset
    # keys fall back to the catalog default. See morph_compiler._patch_numeric.
    scale_overrides: dict[str, float] | None = None
    color_kind:   Optional[Literal["gradient", "solid"]] = None
    color_value:  str | None = None
    bg_color:     str | None = None
    # Explicit override for an effect's "third / accent color" (sparks_color on
    # power, peak_color on equalizer2d). When set on a target of any aspect,
    # the morph compiler uses this on effect-switch instead of auto-deriving
    # from bg_color. None = use bg_color (or starter default if no bg_color set).
    accent_color: str | None = None
    polygon:      Optional[bool | Literal["toggle"] | ValueBinding] = None
    star:         float | ValueBinding | None = None
    edges:        int | ValueBinding | None = None
    twist:        float | ValueBinding | None = None
    flip:         Optional[bool | Literal["toggle"] | ValueBinding] = None
    # x_offset / y_offset live in the FRONTEND −1..1 space. The compiler converts
    # to LedFX's 0..1 storage via the `scale_offset` flag in effect_params.json.
    x_offset:     float | ValueBinding | None = None
    y_offset:     float | ValueBinding | None = None
    effect_type:  str | None = None
    # Per-shape-sub-field nudge specs (consulted only when target.mode == "nudge"
    # and target.aspect == "shape"). Booleans (polygon, flip) don't have nudge —
    # their tri-state already gives an intensity-independent flip semantic.
    star_nudge:     NumericNudge | None = None
    edges_nudge:    NumericNudge | None = None
    twist_nudge:    NumericNudge | None = None
    x_offset_nudge: NumericNudge | None = None
    y_offset_nudge: NumericNudge | None = None


MorphAspect = Literal[
    "shape", "effect", "color", "bg_color", "reactivity", "brightness", "blur",
]


class MorphTarget(BaseModel):
    """One aspect change on one scope. A MorphStepAction has a list of these.

    target-level `nudge_amount` + `intensity_scale` apply to single-value
    aspects (brightness, reactivity, blur). For Shape, nudge specs live
    per-sub-field on AspectValue (star_nudge, edges_nudge, twist_nudge).
    `intensity_source` is read from the parent MorphStepAction; the field
    is kept here only for backwards compatibility and is ignored at fire time.
    """
    scope:            MorphScope = Field(default_factory=MorphScope)
    aspect:           MorphAspect
    mode:             Literal["absolute", "nudge"] = "absolute"
    absolute_value:   AspectValue = Field(default_factory=AspectValue)
    nudge_amount:     float = 0.0
    intensity_scale:  float = 0.0       # 0 = ignore beat intensity, 1 = full RMS scaling
    # Legacy — superseded by MorphStepAction.intensity_source. Kept so old data parses.
    intensity_source: Literal["rms_total", "rms_bass", "onset_score"] = "rms_total"
    ramp_ms:          int | ValueBinding | None = None  # overrides MorphStepAction.ramp_ms when set


class MorphStepAction(BaseModel):
    """A composable, multi-target change across Aspects (Shape/Effect/Color/BG Color/
    Reactivity/Brightness/Blur). Replaces the need for pre-configured LedFX scenes for
    parameter-level transitions. See `services/morph_compiler.py` for the per-target
    Aspect-to-raw-param translation.

    `intensity_source` is shared across every nudge target in this step — one
    beat-level signal feeds every per-target / per-sub-field nudge math.
    """
    type:             Literal["morph_step"] = "morph_step"
    labels:           list[str] = Field(default_factory=list)
    weight:           float = 1.0
    ramp_ms:          int | ValueBinding | None = None  # default for targets that don't override
    intensity_source: Literal["rms_total", "rms_bass", "onset_score"] = "rms_total"
    targets:          list[MorphTarget] = Field(default_factory=list)


class MorphColorAction(BaseModel):
    """Apply a saved Color Set — or pick one from a Color Group — across many
    devices at once, setting FG color, BG color, and (optionally) background
    mode. `ref_id` points at a ColorSetCard (kind="set" or "group"). For a
    group, `pick_mode` overrides the group's default selection; "default" uses
    the group's own `mode`. `ramp_ms` is the step default; each Color Set entry
    may override it. `advance`/`direction` apply only when the resolved mode is
    "cycle" (wrap or bounce): `advance` is how many members to move per fire (1 =
    next, 3 = skip 2). For wrap, `direction` is the absolute index direction; for
    bounce, "forward" continues the current travel direction and "backward"
    reverses it. See `services/trigger_engine._execute_morph_color`."""
    type:      Literal["morph_color"] = "morph_color"
    labels:    list[str] = Field(default_factory=list)
    weight:    float = 1.0
    ref_id:    str = ""
    pick_mode: Literal["default", "cycle", "weighted"] = "default"
    advance:   Union[Annotated[int, Field(ge=1)], ValueBinding] = 1
    direction: Literal["forward", "backward"] = "forward"
    ramp_ms:   int | ValueBinding | None = None
    # When True (default), skip any color-set value that would reset the LedFX
    # effect (e.g. background_color), preserving the running effect. When False,
    # those values are still applied — but always instantly, never ramped.
    preserve_effect: bool = True


class DeviceSettingTarget(BaseModel):
    """One scoped change to LedFX *virtual-config* settings (not effect params).
    Each field is optional — None means 'leave that setting alone'. Applied
    instantly via ledfx_client.set_virtual_config. See
    services/trigger_engine._apply_device_targets."""
    scope:          MorphScope = Field(default_factory=MorphScope)
    max_brightness: float | None = None   # 0..1
    frequency_min:  int | None = None     # Hz
    frequency_max:  int | None = None     # Hz


class DeviceSettingsAction(BaseModel):
    """Apply virtual-config Device Settings (max_brightness / frequency band)
    across one or more scoped targets. Embeddable like any other Action and also
    the payload of the `device_settings` event type. Applied instantly."""
    type:    Literal["device_settings"] = "device_settings"
    labels:  list[str] = Field(default_factory=list)
    weight:  float = 1.0
    targets: list[DeviceSettingTarget] = Field(default_factory=list)


class EffectParamChange(BaseModel):
    """One parameter change within a LedFxEffectParamAction."""
    param_label: str          # unified label e.g. "Reactivity", "Effect Brightness"
    target_value: float | ValueBinding = 0.0 # numeric value; ignored for toggle/color/gradient/polar params
    toggle_action: str | ValueBinding | None = None  # "on", "off", "toggle" — only for toggle-type params
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
    ramp_ms: int | ValueBinding | None = None  # None = use settings.smooth_ramp_ms; 0 = instant


class RandomOption(BaseModel):
    """One weighted branch of a RandomGroupAction. When chosen, all of its
    actions fire concurrently (same semantics as SequenceStep.actions).
    `actions` may nest further random_groups (depth-capped at execution)."""
    id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:    str = ""                     # optional editor display name
    labels:  list[str] = Field(default_factory=list)
    weight:  float = 1.0
    # None = inherit the group's scope; set = override for this option.
    scope:   Optional[MorphScope] = None
    actions: list[Action] = Field(default_factory=list)


class RandomGroupAction(BaseModel):
    """HA choose-style container: pick ONE option (weighted random, label-
    filtered, last-pick de-duped under this group's `id`) and fire its actions
    concurrently. Embeddable anywhere an Action is: single pools, sequence /
    beat-sequence step actions, morph lane alternatives, and nested inside
    another group's options.

    Carries no timing fields — every option fires at the group's own fire
    moment, which keeps the timeline planner pick-independent (resolution
    happens at fire time, not plan time). Note: event_refs inside an option
    are not walked by the planner, so their event_offset_ms is applied inline
    via the _execute_action fallback path (same as depth-overflow refs)."""
    type:    Literal["random_group"] = "random_group"
    id:      str = Field(default_factory=lambda: str(uuid.uuid4()))  # dedupe key
    labels:  list[str] = Field(default_factory=list)
    weight:  float = 1.0        # weight of the group itself inside a parent pool
    dedupe:  bool = True        # avoid repeating the last-picked option
    # Default target for every option (options inherit unless they override).
    scope:   Optional[MorphScope] = None
    options: list[RandomOption] = Field(default_factory=list)


class GroupRevert(BaseModel):
    """Unified revert config for a sequence_group. In timing="ms" mode the
    hold time is delay_ms; in timing="beats" mode it is delay_beats (+
    pre_ramp starts the restore ramp early so it completes on the target
    beat). transition_ms is the restore ramp duration in both modes."""
    enabled: bool = True
    delay_ms: int = 0
    delay_beats: int = 0
    transition_ms: int = 500
    pre_ramp: bool = True          # beats mode only


class SequenceChild(BaseModel):
    """One step of a SequenceGroupAction. All `actions` fire concurrently.

    timing="ms":    delay_ms is slept BEFORE this child fires (honored on
                    child 0 too, matching legacy SequenceStep semantics).
    timing="beats": delay_beats = extra beats skipped before this child
                    (ignored on child 0, matching legacy BeatSequenceStep);
                    pre_ramp starts ramps early so they complete on the beat."""
    id:          str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:        str = ""
    labels:      list[str] = Field(default_factory=list)
    delay_ms:    int = 0
    delay_beats: int = 0
    pre_ramp:    bool = True
    # None = inherit the parent group's scope ("parent" in the editor);
    # set = override for this step's subtree.
    scope:       Optional[MorphScope] = None
    actions:     list[Action] = Field(default_factory=list)


class SequenceGroupAction(BaseModel):
    """Ordered container: children fire one after another with ms or beat
    delays. Nestable anywhere an Action is (composite root, parallel/random
    children, other sequence groups). beat_fallback / start_offset_beats
    apply only when timing="beats"."""
    type:    Literal["sequence_group"] = "sequence_group"
    id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    labels:  list[str] = Field(default_factory=list)
    weight:  float = 1.0
    timing:  Literal["ms", "beats"] = "ms"
    # Default target for every child (steps inherit unless they override).
    # Leaf actions with an EMPTY scope adopt the inherited one at fire time;
    # no inherited scope anywhere = global (legacy behavior).
    scope:   Optional[MorphScope] = None
    children: list[SequenceChild] = Field(default_factory=list)
    revert:  Optional[GroupRevert] = None
    beat_fallback:      Literal["skip", "fallback"] = "fallback"
    start_offset_beats: int = 0


class ParallelChild(BaseModel):
    """One lane of a ParallelGroupAction. All `actions` fire concurrently.
    offset_ms staggers this child relative to the group's fire moment
    (negative = earlier); the group anchors at min(offset_ms) like legacy
    morph lanes."""
    id:        str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:      str = ""
    labels:    list[str] = Field(default_factory=list)
    offset_ms: int = 0
    # Per-lane target: leaf actions with empty scopes in this lane adopt it.
    scope:     Optional[MorphScope] = None
    actions:   list[Action] = Field(default_factory=list)


class ParallelGroupAction(BaseModel):
    """Concurrent container: every child fires together (subject to per-child
    offset_ms stagger). The composable generalization of morph_set lanes —
    put a RandomGroupAction inside a child to get 'pick one per lane'."""
    type:     Literal["parallel_group"] = "parallel_group"
    id:       str = Field(default_factory=lambda: str(uuid.uuid4()))
    labels:   list[str] = Field(default_factory=list)
    weight:   float = 1.0
    children: list[ParallelChild] = Field(default_factory=list)


# Discriminated union of all action types
Action = Annotated[
    EventRefAction
    | LedFxSceneAction
    | LedFxAmbientAction
    | LedFxAmbientColorAction
    | LedFxGlobalTransitionAction
    | LedFxEffectParamAction
    | MorphStepAction
    | MorphColorAction
    | DeviceSettingsAction
    | RandomGroupAction
    | SequenceGroupAction
    | ParallelGroupAction,
    Field(discriminator="type"),
]

# These models reference the Action union recursively.
for _m in (RandomOption, RandomGroupAction, SequenceChild, SequenceGroupAction,
           ParallelChild, ParallelGroupAction):
    _m.model_rebuild()


class MorphLane(BaseModel):
    """One lane in a `morph_set` MusicEvent. Each lane is a pool of alternative
    Actions; at fire time the engine picks ONE per lane (weighted random, with
    label filtering) and fires all picks concurrently. Lane labels merge with
    the trigger-level filter labels before selection.

    `offset_ms` staggers this lane relative to the scheduled trigger point
    (negative = earlier, positive = later). It compounds with the event-level
    `MusicEvent.event_offset_ms`. Lanes sharing one offset still fire together;
    differing offsets fall back to bus dispatch (see trigger_engine)."""
    name:         str = ""
    labels:       list[str] = Field(default_factory=list)
    alternatives: list[Action] = Field(default_factory=list)
    offset_ms:    int = 0


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
    event_type: Literal[
        "single", "sequence", "beat_sequence", "morph_set",
        # Stateful "scene" events. scene_update has four morph_lanes
        # (First/Rest/Shape/Color); the engine runs First when this isn't the
        # last Scene Update fired, else Rest. The fixed built-ins re-run a lane
        # of the last Scene Update: update_scene→Rest, reset_scene→First,
        # shape_flare→Shape, color_flare→Color, combo_flare→Shape+Color.
        "scene_update", "update_scene", "reset_scene",
        "shape_flare", "color_flare", "combo_flare",
        # Sets LedFX virtual-config Device Settings (max_brightness / freq band).
        "device_settings",
        # Unified node-tree event: the entire body is `root` (an Action, usually
        # a sequence_group / parallel_group / random_group). Legacy payload
        # fields are empty on composite events. Scene-family events stay
        # legacy-shaped until v2 (their cross-event statefulness — flares
        # re-running lanes of the last scene_update — needs named children).
        "composite",
    ] = "single"
    color: str = "#FFD700"     # hex color shown on timeline
    labels: list[str] = Field(default_factory=list)
    energy_level: int | None = None    # 1–10; None = energy-agnostic
    ai_exposed: bool = False           # True = include in AI trigger generation prompts
    fixed: bool = False                # True = built-in, non-editable / non-deletable
    # When True, this event's morph actions are pre-staged into a shared LedFX
    # scene ("spotfx-morph-temp") by the planner ahead of fire, and dispatched
    # at fire time via a single `PUT /api/scenes {action: activate}` so every
    # virtual changes atomically. Honored for event_type == "single" or
    # "morph_set"; ignored (with a warning log) for "sequence" / "beat_sequence".
    scene_override: bool = False

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
    # to fire; all picks fire concurrently. Brightness lives on the Morph Step
    # targets themselves and global scene transitions are gone.
    morph_lanes: list[MorphLane] = Field(default_factory=list)

    # For event_type == "device_settings" — virtual-config changes applied instantly.
    device_targets: list[DeviceSettingTarget] = Field(default_factory=list)

    # For event_type == "composite" — the whole event body as one Action tree.
    # None = empty event (executors no-op).
    root: Optional[Action] = None

    # Timing offset: shift when this event fires (negative = earlier, positive = later)
    event_offset_ms: int = 0

    # Internal: id of last-called action (to avoid repeating), not persisted
    _last_action_id: str | None = None
