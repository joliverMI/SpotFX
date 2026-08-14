"""SPECTRA scene model — the SceneV2 port, grown per the accepted
editor/drift design (data/spectra-editor-drift-design/report.md §2.2, as
amended by decision-review-answers.md).

A scene = INITIAL CONDITIONS (every value fixed, ⚡-mapped, or 🎲-rolled)
plus DECLARED MECHANISMS:
  effect_steps — intensity-conditional EFFECT SELECTION (decision:
               star-fold-entry-growth): a device entry may resolve to a
               DIFFERENT EFFECT at different fire intensities — threshold
               steps mirroring the steps-binding shape, each step carrying
               its OWN effect + param set. Selection happens ONCE, at
               fire/compile time (never a blend, never a mid-hold switch);
               an empty list is the single-effect form and the plain
               default, so every existing scene loads unchanged.
  drift      — per-param creep/follow declarations (named profile with an
               inline one-off escape hatch, decision-4 pattern)
  flare_kinds — NAMED FLARE KINDS (the owner's item-8 shape, judged and
               accepted): each kind is one of three types —
                 drift_jump  jumps the drift: the colour-set jump through
                             the shipped selector, or a 🎲 re-roll for shape
                 momentary   a parameter spike that RETURNS to where it was
                 permanent   the parameter lands and BECOMES the new
                             baseline drift carries from
               A momentary/permanent kind's params are ParamTarget
               expressions (absolute / offset-from-baseline / random-in-
               range — see ParamTarget); INTENSITY-DRIVEN strength is the
               band's own scale factor, orthogonal to the target mode.
               momentary also carries an optional hold_ms (CHOSEN HOLD
               before release; None = the fixed PULSE_HOLD_S default) —
               see scene_response.py.
  responses  — the four event classes (flare/charge/lull/drop), each an
               intensity-banded ResponseSpec whose bands SELECT AND SCALE
               the named kinds: band.kinds maps kind name → scale factor
               multiplying that kind's strength in that range
  color_journey — the room owns ONE continuous colour journey BY DEFAULT;
               a scene may OVERRIDE it outright as a first-class capability
               (owner's color-drift-scope answer). Transition semantics
               into/out of an override live in services/color_journey.py.

Loader-compatible with spot-effects' storage/scenes_v2.json: every current
value is a plain scalar and scalars remain legal everywhere; a legacy
`flare_bands` key becomes responses["flare"].bands on load. COMPATIBILITY
(binding): everything already authored — flare_bands, per-band param_patch
and gain envelopes, per-class reroll_dice / color_set_jump — loads
UNCHANGED as auto-named kinds (`_migrate_flare_kinds`); the engine executes
kinds ONLY. The S2 evolution engine consumes the declarations; S1 stores,
edits, resolves (test-fire) and dry-run compiles them.

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
    reflected ("bounce"), wrapped ("wrap"), or parked at the bound it
    reaches and left there ("hold") at [lo, hi]. lo/hi are also intersected
    against the target param's own registered legal range at drift-conductor
    resolve time (fx.device_model — see drift_conductor._registry_range) so
    a wide or default-ish spec can never wander a parameter past what the
    effect itself declares usable — the class-wide degeneracy floor/ceiling.
    follow: the value tracks the music's energy arc through a drawn
    intensity→value curve (points share the sequencer CurvePoint shape;
    y IS the parameter value here, not a likelihood), gliding over slew_s —
    the resolved target is intersected against the same registered range.
    """
    kind: Literal["creep", "follow"]
    # creep
    rate_per_min: float = 0.0
    lo: float = 0.0
    hi: float = 1.0
    motion: Literal["bounce", "wrap", "hold"] = "bounce"
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


class EffectStep(BaseModel):
    """One rung of an entry's intensity-conditional effect selection: at or
    above `threshold` the entry resolves to THIS effect with THIS param set
    (params may bind, exactly like the base set). Same-effect-different-
    params rungs are a plain ⚡ steps binding's job — effect steps exist to
    change the EFFECT, so every variant's effect_type must be distinct."""
    threshold:   float = Field(gt=0.0, le=1.0)
    effect_type: str
    params:      dict[str, SceneParamValue] = Field(default_factory=dict)


class SceneDeviceConfig(BaseModel):
    # "all" targets every imported virtual (target stays empty); category
    # targets expand to member virtuals at compile time. Narrower entries
    # override wider ones: all < category < virtual.
    id:          str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_kind: Literal["all", "category", "virtual"] = "category"
    target:      str = ""
    effect_type: str = ""
    params:      dict[str, SceneParamValue] = Field(default_factory=dict)
    # Intensity-conditional effect selection: the plain effect_type/params
    # pair is the entry BELOW the first threshold (and when the fire has no
    # intensity axis — the base is the fallback, mirroring a steps binding);
    # the last step whose threshold <= fire intensity wins, replacing effect
    # AND params wholesale. Resolved once per fire in
    # scene_compiler.resolve_scene; [] = the single-effect form (default).
    effect_steps: list[EffectStep] = Field(default_factory=list)
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
        if self.effect_steps:
            # Canonical storage form: ascending thresholds (BindingStep rule).
            self.effect_steps.sort(key=lambda s: s.threshold)
            thresholds = [s.threshold for s in self.effect_steps]
            if len(set(thresholds)) != len(thresholds):
                raise ValueError(
                    f"effect steps need distinct thresholds (got {thresholds})")
            effects = [self.effect_type] + [s.effect_type
                                            for s in self.effect_steps]
            if "" in effects[1:]:
                raise ValueError("an effect step has no effect_type")
            if len(set(effects)) != len(effects):
                raise ValueError(
                    "effect steps must each name a DIFFERENT effect "
                    f"(got {effects}); same-effect variation over intensity "
                    "is a ⚡ steps binding on the param, not an effect step")
        step_params = {p for step in self.effect_steps for p in step.params}
        for pname in self.drift:
            if pname not in self.params and pname not in step_params \
                    and pname not in ("brightness", "background_brightness"):
                raise ValueError(
                    f"drift declared for '{pname}' but no variant of the "
                    "entry sets such a param")
        return self

    def select_variant(self, intensity: Optional[float]) -> tuple[
            str, dict[str, SceneParamValue]]:
        """The (effect_type, params) a fire at this intensity resolves to:
        the last step whose threshold <= intensity wins; below the first
        threshold — or with no intensity axis at all — the base pair is the
        answer (the base IS the fallback, the steps-binding rule)."""
        chosen: Optional[EffectStep] = None
        if intensity is not None:
            for step in self.effect_steps:   # validator keeps these ascending
                if intensity >= step.threshold:
                    chosen = step
        if chosen is None:
            return self.effect_type, self.params
        return chosen.effect_type, chosen.params

    def params_for_effect(self, effect_type: str) -> dict[str, SceneParamValue]:
        """The param set belonging to the variant a past fire selected,
        keyed by the entry's LIVE effect (unambiguous — variants must name
        distinct effects). Engine truth for surges: re-rolls re-resolve the
        selected variant's bindings, never another variant's. An unknown
        effect falls back to the base set (the registry gate then decides
        what actually lands)."""
        for step in self.effect_steps:
            if step.effect_type == effect_type:
                return step.params
        return self.params


class ParamTarget(BaseModel):
    """One param's target expression on a momentary/permanent flare kind —
    the owner's five-ways extension. Five ways to say where a param goes,
    two independent of this type:
      absolute  (default, legacy-compatible) value verbatim — a bare
                number in authored JSON coerces to this shape.
      offset    a signed delta FROM THE CARRIED BASELINE AT FIRE TIME (a
                creep's current wander position, the same truth
                _carried_value already reads for the release) — "star down
                by 1" is offset=-1.0, up is a positive offset. Unresolvable
                (no known baseline) skips the param, same as an unknown
                registry param — a name-broadcast kind never moves blind.
      random    a fresh uniform draw in [lo, hi], rolled ONCE per kind
                execution and broadcast to every landing virtual — the same
                one-declared-value-many-virtuals shape as absolute.
    The other two ways are orthogonal, not modes here: INTENSITY-DRIVEN is
    the band's existing scale factor (moves the resolved declared target to
    baseline + (declared − baseline)·scale — composes with every mode
    above); ABSOLUTE set value is this type's own default mode."""
    mode: Literal["absolute", "offset", "random"] = "absolute"
    value:  Optional[float] = None   # absolute
    offset: Optional[float] = None   # offset — signed, up = positive
    lo:     Optional[float] = None   # random
    hi:     Optional[float] = None   # random

    @model_validator(mode="after")
    def _shape(self) -> "ParamTarget":
        if self.mode == "absolute" and self.value is None:
            raise ValueError("an absolute target needs a value")
        if self.mode == "offset" and self.offset is None:
            raise ValueError("an offset target needs an offset")
        if self.mode == "random":
            if self.lo is None or self.hi is None:
                raise ValueError("a random target needs lo and hi")
            if self.lo > self.hi:
                raise ValueError(f"random target needs lo ({self.lo}) <= hi ({self.hi})")
        return self


class FlareKind(BaseModel):
    """One NAMED flare kind — a first-class concept the scene declares and
    its bands select. The three types, binding semantics:
      drift_jump  jump the drift — jump="color_set" rolls the shipped
                  colour-set selector and JUMPS to the pick; jump="dice"
                  re-rolls the scene's 🎲 bindings (fresh shape). Both
                  CARRY — a drift jump moves the story.
      momentary   params/gain spike and RETURN exactly to the carried
                  baseline (the release honors drift's current position).
      permanent   params/gain land and BECOME the new baseline drift
                  carries from (conductor.on_surge).
    gain is a brightness-envelope multiplier around the carried baseline;
    params are ParamTarget expressions (absolute/offset/random — see that
    type), name-broadcast to every virtual whose live effect carries the
    param. A band attaches kinds with a scale factor: scale s moves a
    param's RESOLVED target to baseline + (resolved − baseline)·s and an
    envelope to 1 + (gain − 1)·s — ×1 lands the resolved target verbatim,
    ×0 is inert; scale is inert on a dice re-roll (a fresh roll has no
    magnitude) and steers the colour selector's intensity axis on a colour
    jump.
    hold_ms (momentary only; None = PULSE_HOLD_S, today's fixed 250 ms) is
    the CHOSEN HOLD before the release glide starts — the release itself is
    unchanged: it always glides to the baseline AS CARRIED AT RELEASE TIME,
    a creep's wander included (scene_response.flush_releases)."""
    name: str = Field(min_length=1)
    type: Literal["drift_jump", "momentary", "permanent"]
    jump: Optional[Literal["color_set", "dice"]] = None
    params: dict[str, ParamTarget] = Field(default_factory=dict)
    gain: float = Field(default=1.0, ge=0.0)
    hold_ms: Optional[int] = Field(default=None, ge=0, le=60_000)

    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_params(cls, data):
        if isinstance(data, dict) and isinstance(data.get("params"), dict):
            data = {**data, "params": {
                k: ({"mode": "absolute", "value": v}
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    else v)
                for k, v in data["params"].items()}}
        return data

    @model_validator(mode="after")
    def _shape(self) -> "FlareKind":
        if self.type == "drift_jump":
            if self.jump is None:
                raise ValueError(
                    f"drift-jump kind '{self.name}' needs jump=color_set|dice")
            if self.params or self.gain != 1.0:
                raise ValueError(
                    f"drift-jump kind '{self.name}' jumps the drift — params/"
                    f"gain belong on a momentary or permanent kind")
            if self.hold_ms is not None:
                raise ValueError(
                    f"drift-jump kind '{self.name}' never releases — "
                    f"hold_ms belongs on a momentary kind")
        else:
            if self.jump is not None:
                raise ValueError(
                    f"kind '{self.name}' is {self.type} — jump belongs on a "
                    f"drift_jump kind")
            if not self.params and self.gain == 1.0:
                raise ValueError(
                    f"kind '{self.name}' moves nothing — declare params "
                    f"and/or a gain ≠ 1")
            if self.hold_ms is not None and self.type != "momentary":
                raise ValueError(
                    f"kind '{self.name}' is permanent — it never releases, "
                    f"hold_ms belongs on a momentary kind")
        return self


class FlareBand(BaseModel):
    # One intensity window ([min, max)) that SELECTS AND SCALES the scene's
    # named kinds: kinds maps kind name → scale factor. The legacy fields
    # (curve/gain/param_patch) remain accepted input and are auto-named into
    # kinds on load (_migrate_flare_kinds) — post-validation they are always
    # neutral; the engine executes kinds only.
    intensity_min: float = Field(default=0.0, ge=0.0, le=1.0)
    intensity_max: float = Field(default=1.0, ge=0.0, le=1.0)
    curve: Literal["linear", "ease_in", "ease_out", "pulse"] = "linear"
    gain:  float = Field(default=1.0, ge=0.0)
    param_patch: dict[str, float] = Field(default_factory=dict)
    kinds: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _band_ordered(self) -> "FlareBand":
        if self.intensity_min >= self.intensity_max:
            raise ValueError(
                f"band intensity_min ({self.intensity_min}) must be "
                f"< intensity_max ({self.intensity_max})")
        for name, scale in self.kinds.items():
            if scale < 0.0:
                raise ValueError(
                    f"kind '{name}' scale must be ≥ 0 (got {scale})")
        return self


class ResponseSpec(BaseModel):
    """One event class's response: bands over the intensity axis, each
    selecting and scaling named kinds (band.kinds). The S2 engine picks the
    band containing the fire intensity and executes its kinds per type.
    reroll_dice / color_set_jump are the LEGACY per-class flags — accepted
    input, auto-named into drift-jump kinds on load; a legacy input missing
    reroll_dice keeps its historical default (True) via the migration, so
    the field default here is the canonical neutral False."""
    bands: list[FlareBand] = Field(default_factory=list)
    reroll_dice: bool = False
    color_set_jump: bool = False

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


class PhaseBlend(BaseModel):
    """OVERRIDE BLEND equivalent for the charge/lull phase build — the
    dominant real usage of legacy Override Blend (269 live triggers studied
    read-only: 225 Charge, 40 Lull, 4 scene-selection/update — trigger_engine
    `_phase_blend_ramp_ms`/`_blend_factor_for`). Legacy stretched the ramp
    DYNAMICALLY to the gap to the next enabled trigger, so a charge always
    peaked exactly as the lull hit. SPECTRA's S2 engine is bridge-reactive
    with no forward schedule of trigger fires to compute that gap against
    (that needs per-song trigger authoring — the gap report's item 1, a
    separate large gap) — so this authors the buildable half of the same
    grammar: a per-scene CONFIGURABLE ramp instead of the fixed global
    default (`scene_response.PHASE_RAMP_MS`), so a scene tuned for a long
    build can stretch it and one tuned for a tight cut can shorten it.
    None = unchanged default ramp for that class."""
    charge_ramp_ms: Optional[int] = Field(default=None, ge=200, le=20000)
    lull_ramp_ms:   Optional[int] = Field(default=None, ge=200, le=20000)


def _as_dict(value) -> dict:
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def _migrate_flare_kinds(data: dict) -> dict:
    """AUTO-NAMED KINDS — the binding load-unchanged guarantee: everything
    already authored (per-band param_patch as a permanent kind, per-band
    gain as a momentary kind when curve="pulse" else permanent, per-class
    reroll_dice as a shared "Dice Re-roll" drift-jump, flare-class
    color_set_jump as "Colour Jump") converts to named kinds attached to
    its bands at scale ×1 — exactly the legacy execution. Legacy execution
    fields are then neutralized so exactly ONE execution surface exists.

    A LEGACY input (no "flare_kinds" key) keeps the historical reroll_dice
    default True; a CANONICAL input (key present) treats a missing flag as
    False. color_set_jump on a non-flare class was a legacy no-op and
    neutralizes without a kind. Deterministic and idempotent — a second
    pass converts nothing."""
    responses = data.get("responses")
    if not isinstance(responses, dict) or not responses:
        return data
    legacy = "flare_kinds" not in data
    kinds = [_as_dict(k) for k in (data.get("flare_kinds") or [])]
    by_name = {k.get("name"): k for k in kinds}

    def declare(name: str, body: dict) -> str:
        existing = by_name.get(name)
        if existing is not None:
            same = all(existing.get(f) == body.get(f)
                       for f in ("type", "jump", "params", "gain"))
            if same:
                return name
            n = 2
            while f"{name} ({n})" in by_name:
                n += 1
            name = f"{name} ({n})"
        entry = {"name": name, **body}
        kinds.append(entry)
        by_name[name] = entry
        return name

    new_responses: dict = {}
    for cls, spec in responses.items():
        spec = _as_dict(spec)
        bands = [_as_dict(b) for b in (spec.get("bands") or [])]
        reroll = bool(spec.get("reroll_dice", legacy))
        colour = bool(spec.get("color_set_jump", False)) and cls == "flare"
        dice_name = declare("Dice Re-roll", {
            "type": "drift_jump", "jump": "dice", "params": {}, "gain": 1.0,
        }) if reroll else None
        colour_name = declare("Colour Jump", {
            "type": "drift_jump", "jump": "color_set", "params": {},
            "gain": 1.0,
        }) if colour else None
        out_bands = []
        for band in bands:
            refs = dict(band.get("kinds") or {})
            lo = band.get("intensity_min", 0.0)
            hi = band.get("intensity_max", 1.0)
            patch = dict(band.get("param_patch") or {})
            gain = band.get("gain", 1.0)
            if patch:
                refs.setdefault(declare(
                    f"{cls.capitalize()} patch {lo:g}–{hi:g}",
                    {"type": "permanent", "jump": None, "params": patch,
                     "gain": 1.0}), 1.0)
            if gain != 1.0:
                momentary = band.get("curve", "linear") == "pulse"
                refs.setdefault(declare(
                    f"{cls.capitalize()} gain {lo:g}–{hi:g}",
                    {"type": "momentary" if momentary else "permanent",
                     "jump": None, "params": {}, "gain": gain}), 1.0)
            if dice_name is not None:
                refs.setdefault(dice_name, 1.0)
            if colour_name is not None:
                refs.setdefault(colour_name, 1.0)
            out_bands.append({**band, "param_patch": {}, "gain": 1.0,
                              "kinds": refs})
        new_responses[cls] = {**spec, "bands": out_bands,
                              "reroll_dice": False, "color_set_jump": False}
    data["responses"] = new_responses
    data["flare_kinds"] = kinds
    return data


class SceneV2(BaseModel):
    id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:   str
    labels: list[str] = Field(default_factory=list)
    devices: list[SceneDeviceConfig] = Field(default_factory=list)
    flare_kinds: list[FlareKind] = Field(default_factory=list)
    responses: dict[ResponseClass, ResponseSpec] = Field(default_factory=dict)
    color_journey: SceneColorJourney = Field(default_factory=SceneColorJourney)
    choreography: PhaseChoreography = Field(default_factory=PhaseChoreography)
    phase_blend: PhaseBlend = Field(default_factory=PhaseBlend)
    # OVERRIDE BLEND equivalent for scene entry (the thinner facet of the
    # same legacy flag — see PhaseBlend for the dominant charge/lull facet):
    # blend the scene's compiled writes in over this ramp instead of an
    # instant jump when the scene fires, hue-arc for colour (fx_seam,
    # coherent with the flare colour-jump ramp-in — scene_response.
    # color_jump_ramp_ms, PR38 — and the destination journey's promised
    # no-snap custody transfer, services/color_journey.on_scene_enter). Only
    # blends params on a virtual whose ALREADY-ACTIVE effect matches this
    # scene's entry — a genuine effect-type switch still recreates instantly
    # (the vendored engine's own tween boundary, unchanged by this field;
    # see fx_executor's crossfade-branch note). 0 = today's unchanged
    # instant-jump behaviour.
    entry_ramp_ms: int = Field(default=0, ge=0, le=20000)
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
        if isinstance(data, dict):
            data = _migrate_flare_kinds(dict(data))
        return data

    @model_validator(mode="after")
    def _validate(self) -> "SceneV2":
        names = [k.name for k in self.flare_kinds]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate flare kind name(s): {sorted(dupes)}")
        declared = set(names)
        for cls, spec in self.responses.items():
            for band in spec.bands:
                missing = [n for n in band.kinds if n not in declared]
                if missing:
                    raise ValueError(
                        f"{cls} band [{band.intensity_min}, "
                        f"{band.intensity_max}) references undeclared "
                        f"kind(s): {missing}")
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
            values = [*dev.params.values(), dev.brightness,
                      dev.background_brightness]
            for step in dev.effect_steps:
                values.extend(step.params.values())
            for value in values:
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
