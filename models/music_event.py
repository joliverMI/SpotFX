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
from pydantic import BaseModel, Field, model_validator
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
    amount: nudge magnitude in abstract 0..1 space (negative ok). May be a
            ValueBinding (⚡ intensity map / 🎲 random roll) — resolved to a
            scalar at the executor seam like every other bound field.
    scale:  intensity_scale — 0 ignores intensity, 1 fully modulates.
    random_sign: flip the delta's sign with 50% probability per fire — the
            param randomly nudges up or down by the same magnitude.
    wrap:   when True, reflect off min/max and reverse direction on future
            fires so the value bounces instead of sticking at a boundary.
    lo/hi:  optional custom nudge range (None = the effect param's full range);
            clamping/bounce use these bounds. For x/y offset they are in the
            frontend −1..1 space."""
    amount: float | ValueBinding = 0.0
    scale:  float = 0.0
    random_sign: bool = False
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
                                                reactivity additionally supports per-param
                                                sub-fields (reactivity_values /
                                                reactivity_nudges — see below) that override
                                                the single-number distribution per param
      aspect=color                            → color_kind + color_value
      aspect=bg_color                         → bg_color
      aspect=shape                            → any subset of {polygon, star, edges, twist, flip,
                                                reverse, swirl, horizon_scale, radius_scale,
                                                blob_size, x_offset, y_offset}.
                                                `edges` doubles as the particle count on effects
                                                with a `particle_count` param (orbits) — the UI
                                                shows it as "Edge / Particle Count".
                                                Booleans (polygon, flip) accept True, False,
                                                or "toggle" (flip the current cached value).
                                                When target.mode='nudge', the numeric sub-fields
                                                use their *_nudge specs instead of their
                                                absolute value.
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
    # blackhole/orbits shape sub-fields (ignored by effects without the params)
    swirl:          float | ValueBinding | None = None
    horizon_scale:  float | ValueBinding | None = None
    radius_scale:   float | ValueBinding | None = None
    blob_size:      float | ValueBinding | None = None
    reverse:        Optional[bool | Literal["toggle"] | ValueBinding] = None
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
    swirl_nudge:         NumericNudge | None = None
    horizon_scale_nudge: NumericNudge | None = None
    radius_scale_nudge:  NumericNudge | None = None
    blob_size_nudge:     NumericNudge | None = None
    # Per-param Reactivity sub-fields (aspect="reactivity"), mirroring the Shape
    # sub-field semantics but keyed by raw LedFX param name so any effect's
    # reactivity params (accel, edge_speed, beat_burst, spawn_rate, …) are
    # addressable without a model field each. Values are in the param's OWN
    # range (not abstract 0..1): set = write, absent = ignore, ValueBinding =
    # variable (e.g. section energy). Toggle params (keybeat2d half_beat) take
    # the usual tri-state True / False / "toggle". When target.mode="nudge",
    # reactivity_nudges entries drive the per-param nudge math instead; the
    # single-number distribution (nudge_amount × aspect_scale) still applies to
    # params without an entry. Params the current effect lacks are ignored.
    reactivity_values: dict[str, float | bool | Literal["toggle"] | ValueBinding] | None = None
    reactivity_nudges: dict[str, NumericNudge] | None = None


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
    name:             str = ""  # optional editor display name, shown in summaries/previews
    labels:           list[str] = Field(default_factory=list)
    weight:           float = 1.0
    ramp_ms:          int | ValueBinding | None = None  # default for targets that don't override
    intensity_source: Literal["rms_total", "rms_bass", "onset_score"] = "rms_total"
    targets:          list[MorphTarget] = Field(default_factory=list)


# SetColorAction.ref_id sentinels — resolved to a real ColorSetCard id at fire
# time by trigger_engine._execute_set_color:
#   SCENE_GROUP_COLOR_REF   → the Color Group designated by the ACTIVE scene
#                             group (scene_group_color_ref_id); falls back to
#                             the current group when none designates one.
#   CURRENT_COLOR_GROUP_REF → the last Color Group any set_color fire used.
SCENE_GROUP_COLOR_REF = "__scene_group__"
CURRENT_COLOR_GROUP_REF = "__current__"


class SetColorAction(BaseModel):
    """Apply a saved Color Set — or pick one from a Color Group — across many
    devices at once, setting FG color, BG color, and (optionally) background
    mode. `ref_id` points at a ColorSetCard (kind="set" or "group"), or one of
    the sentinels above (follow the active Scene Group's designated Color
    Group / re-use the current Color Group). For a
    group, `pick_mode` overrides the group's default selection; "default" uses
    the group's own `mode`. `ramp_ms` is the step default; each Color Set entry
    may override it. `advance`/`direction` apply only when the resolved mode is
    "cycle" (wrap or bounce): `advance` is how many members to move per fire (1 =
    next, 3 = skip 2, 0 = stay — re-apply the current member without moving,
    which on a Palette Sync group means "repaint in the room's current color
    family"). For wrap, `direction` is the absolute index direction; for
    bounce, "forward" continues the current travel direction and "backward"
    reverses it. See `services/trigger_engine._execute_set_color`."""
    type:      Literal["set_color"] = "set_color"
    labels:    list[str] = Field(default_factory=list)
    weight:    float = 1.0
    ref_id:    str = ""
    pick_mode: Literal["default", "cycle", "weighted"] = "default"
    advance:   Union[Annotated[int, Field(ge=0)], ValueBinding] = 1
    direction: Literal["forward", "backward"] = "forward"
    ramp_ms:   int | ValueBinding | None = None
    # Runtime multiplier for per-entry ramp overrides that live on the Color
    # Set card (not on this action). Set by the Override Blend plan scaler on
    # its deep copies; 1.0 (inert) on stored events.
    ramp_scale: float = 1.0
    # Dark/Light display mode for this step. "default" = defer to the color
    # cards (group, then set); "dark" / "light" force it — but the global
    # TopBar mode, trigger, scene group and scene all outrank this action.
    # See services/display_mode.resolve().
    display_mode: Literal["default", "dark", "light"] = "default"
    # When True (default), skip any color-set value that would reset the LedFX
    # effect (params flagged `resets_effect`), preserving the running effect.
    # When False, those values are still applied — but always instantly, never
    # ramped. Since the 2026-07-10 ledfx-src background_* patch no stock param
    # resets, so this flag is inert unless a param is flagged in effect_params.
    preserve_effect: bool = True


class MorphColorAction(BaseModel):
    """Morph the colors already showing on the scoped devices by rotating every
    color (FG gradient/color, BG color, and accent) around the hue wheel by
    `degrees`. The default 180° yields the complementary contrast. Like other
    morphs: `scope` selects devices/categories (empty = inherit the nearest
    group/lane Target, else global), `ramp_ms` smooths the change, and
    `intensity_scale` lets beat intensity modulate the rotation
    (factor = 1 + (intensity − 0.5) · intensity_scale, same math as nudges).

    `direction`: "forward" rotates + degrees around the wheel, "backward" −.
    `degrees` may be a ValueBinding (⚡ intensity map / 🎲 random roll per
    fire; its ± flips rotation direction) — resolved at the executor seam.
    `morph_bg`: when True (default) the BG color rotates along with FG and
    accent; False leaves every effect's background untouched. Replaces the
    old melt-only `preserve_melt_bg` (legacy True loads as morph_bg=False).
    See `services/trigger_engine._execute_morph_color`."""
    type:      Literal["morph_color"] = "morph_color"
    labels:    list[str] = Field(default_factory=list)
    weight:    float = 1.0
    scope:     MorphScope = Field(default_factory=MorphScope)
    degrees:   float | ValueBinding = 180.0
    direction: Literal["forward", "backward"] = "forward"
    ramp_ms:   int | ValueBinding | None = None
    intensity_scale:  float = 0.0       # 0 = ignore beat intensity, 1 = full scaling
    intensity_source: Literal["rms_total", "rms_bass", "onset_score"] = "rms_total"
    morph_bg: bool = True

    @model_validator(mode="before")
    @classmethod
    def _legacy_preserve_melt_bg(cls, data):
        # Old payloads carried melt-only `preserve_melt_bg`; map it onto the
        # general toggle when the new field is absent.
        if isinstance(data, dict) and "morph_bg" not in data:
            if data.pop("preserve_melt_bg", False):
                data["morph_bg"] = False
        return data


class SceneMorphAction(BaseModel):
    """Step the ACTIVE Scene Group forward/backward `advance` members and fire
    the resulting member scene (normal First/Rest lane behavior). Carries no
    group reference — it acts on whichever scene_group event last fired or is
    held by Force Scene; when none is active (or Force Scene holds a single
    scene) it is a no-op. `advance` = members to move per fire (0 = re-fire
    the current member, which runs its Rest lane). Stepping is always ordinal
    ("cycle"), even on weighted-mode groups; bounce groups honor their bounce
    travel, where "backward" reverses it — same semantics as SetColorAction.
    See `services/trigger_engine._execute_scene_morph`."""
    type:      Literal["scene_morph"] = "scene_morph"
    labels:    list[str] = Field(default_factory=list)
    weight:    float = 1.0
    advance:   Annotated[int, Field(ge=0)] = 1
    direction: Literal["forward", "backward"] = "forward"


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
    fallback_s: float | None = None  # if set: POST full merged config with LedFX server-side
                                     # fallback — prior effect auto-restores after this many
                                     # seconds (flare bursts; ramp_ms is ignored)


class RandomOption(BaseModel):
    """One weighted branch of a RandomGroupAction. When chosen, all of its
    actions fire concurrently (same semantics as SequenceStep.actions).
    `actions` may nest further random_groups (depth-capped at execution)."""
    id:      str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:    str = ""                     # optional editor display name
    labels:  list[str] = Field(default_factory=list)
    weight:  float = 1.0
    # ── Energy gate/scale — evaluated against the firing trigger's intensity
    # (0-1; machine triggers default it to section energy). Option is eligible
    # only when floor <= energy <= ceiling (None = unbounded). energy_scale
    # tilts the weight across that window: 0 = flat, +1 = 0x weight at the
    # window's low edge up to 2x at the high edge, -1 = the inverse. Fires
    # with no energy context (manual test fires) skip the gate entirely.
    energy_floor:   Optional[float] = Field(default=None, ge=0.0, le=1.0)
    energy_ceiling: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    energy_scale:   float = Field(default=0.0, ge=-1.0, le=1.0)
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
    # ms mode only: also fire this child after this many scene-family fires
    # (scene picks, Update/Reset Scene, flares, Scene Morph) — whichever of
    # delay_ms / delay_updates completes first. delay_ms == 0 with updates set
    # waits on updates alone (released early by a track change). Ignored in
    # beats mode and by the legacy event-level sequence editor.
    delay_updates: Optional[int] = None
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


class IntensityLane(BaseModel):
    """One lane of an IntensityChooserAction. When selected, all `actions`
    fire concurrently (same semantics as RandomOption.actions).

    `threshold` is the lane's LOWER bound on the 0-1 intensity scale; a lane
    covers [threshold, next lane's threshold). lanes[0] is the DEFAULT lane —
    it covers everything below the first thresholded lane and its own
    threshold is ignored."""
    id:        str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:      str = ""
    labels:    list[str] = Field(default_factory=list)
    threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    # None = inherit the group's scope; set = override for this lane.
    scope:     Optional[MorphScope] = None
    actions:   list[Action] = Field(default_factory=list)


class IntensityChooserAction(BaseModel):
    """Deterministic sibling of RandomGroupAction: the firing trigger's
    intensity (0-1, after the song/genre intensity scaler) selects exactly ONE
    lane, whose actions fire concurrently. Among lanes[1:], the highest lane
    whose threshold <= intensity wins (equal thresholds -> the later lane).
    lanes[0] is the default lane: it fires when intensity is below every
    threshold, when it is the only lane, or when the fire carries no intensity
    context (manual test fires).

    `source` is pluggable for future signals; only the trigger's intensity is
    implemented today."""
    type:   Literal["intensity_chooser"] = "intensity_chooser"
    id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    labels: list[str] = Field(default_factory=list)
    weight: float = 1.0        # weight of the group itself inside a parent pool
    source: Literal["trigger_intensity"] = "trigger_intensity"
    # Default target for every lane (lanes inherit unless they override).
    scope:  Optional[MorphScope] = None
    lanes:  list[IntensityLane] = Field(default_factory=list)


# Discriminated union of all action types
Action = Annotated[
    EventRefAction
    | LedFxSceneAction
    | LedFxAmbientAction
    | LedFxAmbientColorAction
    | LedFxGlobalTransitionAction
    | LedFxEffectParamAction
    | MorphStepAction
    | SetColorAction
    | MorphColorAction
    | SceneMorphAction
    | DeviceSettingsAction
    | RandomGroupAction
    | SequenceGroupAction
    | ParallelGroupAction
    | IntensityChooserAction,
    Field(discriminator="type"),
]

# These models reference the Action union recursively.
for _m in (RandomOption, RandomGroupAction, SequenceChild, SequenceGroupAction,
           ParallelChild, ParallelGroupAction, IntensityLane,
           IntensityChooserAction):
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


class SceneGroupMember(BaseModel):
    """One reference to a scene_update event within a scene_group event.
    `weight` matters only when the group's mode is "weighted"."""
    event_id: str
    weight:   float = 1.0


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
        # Ordered set of member Scene Updates picked one at a time, like a
        # Color Group: cycle (wrap/bounce) or weighted random. Firing the
        # group advances its cursor and fires the picked member (normal
        # First/Rest). Force Scene may hold a scene_group — every new-scene
        # pick then rotates the group. See scene_group_* fields below.
        "scene_group",
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

    # For event_type == "scene_group" — member Scene Updates + selection
    # behavior (mirrors ColorSetCard group semantics; cursor lives in the
    # engine, keyed by this event's id, and persists across track changes).
    scene_group_members: list[SceneGroupMember] = Field(default_factory=list)
    scene_group_mode: Literal["cycle", "weighted"] = "cycle"
    scene_group_cycle_behavior: Literal["wrap", "bounce"] = "wrap"
    scene_group_exclude_current: bool = True
    # Cycle mode only: when the group is freshly called (it wasn't the active
    # scene group), start cycling from a random member instead of the
    # persisted cursor. Weighted mode ignores it (every pick is random).
    scene_group_random_start: bool = False
    # Optional ColorSetCard (kind="group") id this scene group designates.
    # Set Color actions with ref_id == SCENE_GROUP_COLOR_REF resolve to it
    # while this group is active — the room's colors follow the scene group.
    scene_group_color_ref_id: str = ""
    # Dark/Light variants of the designated Color Group. When the resolved
    # display mode (global → trigger → this group → scene → set_color) is
    # dark/light and the matching ref is set, SCENE_GROUP_COLOR_REF resolves
    # to it instead of scene_group_color_ref_id. "" = no variant, use the base.
    scene_group_dark_color_ref_id: str = ""
    scene_group_light_color_ref_id: str = ""

    # Dark/Light display mode carried by this event. Meaningful on
    # event_type == "scene_group" (the group's default mode, level 3) and
    # "scene_update" (the scene's mode, level 4). "default" = defer downward.
    # See services/display_mode.resolve() for the full precedence chain.
    display_mode: Literal["default", "dark", "light"] = "default"

    # Timing offset: shift when this event fires (negative = earlier, positive = later)
    event_offset_ms: int = 0

    # Internal: id of last-called action (to avoid repeating), not persisted
    _last_action_id: str | None = None
