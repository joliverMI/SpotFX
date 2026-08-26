"""The drift conductor — a held scene's declared life, executed (report
§2.5). One leg every LEG_S seconds; per leg, a FEW SMALL CALLS through the
executor seam (fx_executor) — glides the shared library's tween engine
interpolates per render frame. No per-frame traffic, ever.

Mechanisms per leg:
  creep  — bounded autonomous wander: next target = position + rate·leg,
           reflected ("bounce": direction flips at lo/hi) or wrapped.
  follow — the value tracks the music's energy arc: read intensity (the
           bridge's section energy; 0.5 neutral when absent — stated),
           evaluate the declared curve, glide toward it over slew_s.
           Deliberately the slow layer; beat-rate response stays inside the
           effects' own audio params.
  colour journey — DESTINATION-DRIVEN (services/color_journey holds the
           binding model + custody semantics): the room holds a destination
           colour set picked by the shipped selector (curve × genre ×
           wheel-travel) — the destination determines both the target and
           the pace (fixed at selection from distance) — and each leg the
           wheel travels toward it along the shortest arc, the active
           palette rotating WITH it (gradient + background together,
           hue-blend glides on set-mode virtuals). ON ARRIVAL the next
           destination is selected (arrived set excluded) and the walk sets
           off again. No destination in state → one is selected; no
           eligible set → the walk holds (never aimless creep, never forced
           churn). Rainbow/achromatic palettes pause the walk; a scene fire
           or wheel teleport clears the bearing so the new custody/position
           reselects; the wheel + bearing persist to shared room state
           every leg, so custody transfers never move the position.

  gradient drift — the two-dimensional drift gradient (owner ask
           2026-08-20, spectra/models/gradient2d.py): OFF by default
           (room_controls.RoomControlState.active_gradient_id is None,
           today's journey behaviour is entirely unchanged). When a
           gradient is active it REPLACES the colour journey above for
           set-mode virtuals — the journey is held (no wheel travel, no
           destination picked) for exactly the same reason a live rainbow
           palette already holds it: a different colour source has taken
           over. X (time) advances a fixed fraction of the gradient's
           0..1 span every leg (room_controls.gradient_x_period_s is the
           full-span duration), looping or bouncing per the gradient's own
           x_mode. Y (intensity) does NOT track live intensity every leg —
           it DRIFTS toward a target (room_controls.gradient_y_slew_s is
           roughly how long that drift takes) that only changes on
           on_intensity_event(), called from trigger_engine.py at exactly
           the two moments his own proposal named: a trigger firing, or an
           analysed (song) transition firing. This is his answer to "the
           next colour is chosen well ahead of when it reaches there, since
           we drift to it": don't re-target continuously (chasing every
           tick's momentary fluctuation), retarget on the same discrete
           moments the rest of this app already treats as "the intensity
           changed." Flares are UNCHANGED by any of this — a flare colour
           jump (scene_response.py) still writes state.gradient/
           background_color directly via apply_color_set's instant jump;
           the next gradient leg (its OWN absolute (x,y) sample, not a
           delta) simply overwrites it on its own schedule, same as the
           wheel journey's rotation already gets overwritten-then-resumed
           around a flare jump today.
           A DROP is the one event that moves this axis pair OUT of band
           (owner ask 2026-08-24): on_drop_event() jumps X a full extra
           leg-step, pushes the Y TARGET up by the drop's own energy
           (DROP_Y_KICK — never down, never past 1.0), and lands the
           resulting colour immediately instead of waiting for the next
           ~20 s leg. Y itself still only drifts toward the target on
           legs — the drop moves the target, not Y.

Degeneracy floor/ceiling (owner defect fix, 2026-08-14): a creep or follow
spec is authored PARAM-AGNOSTIC (a named profile is reused across effects —
decision-4) so it can carry bounds that make sense for one param and are
wildly wrong for another (e.g. a [0,1]-ish default wandering a pixel-scale
"particle size" whose own effect declares a [0.5, 6.0] legal range: every
creep step below 0.5 is silently REJECTED by the effect's own config schema
— fx.effects.__init__._apply_config logs and no-ops rather than raising —
so the light sticks at its last legal value while the conductor's OWN
position model keeps wandering into illegal territory, visibly parked near
the floor). `_registry_range()` reads the shared fx.device_model param
registry (config/effect_params.json, the same curated min/max every other
param editor already trusts) for the mechanism's (effect_type, param) and
INTERSECTS it with the spec's own lo/hi (creep, at Mechanism construction)
or clips the resolved target (follow, every leg) — so no drift declaration,
however authored, can ever push a registered param outside the range its
own effect calls usable. An unregistered param (no schema, e.g. `fx`-less
test doubles) is untouched — this is a floor, not a new restriction.

Re-baseline: any scene fire drops every leg and restarts mechanisms from
the new resolved initial conditions (on_scene_fire, hooked into
scene_compiler.fire_scene). Carry (the owner's words): surges move the
baseline drift resumes from — on_surge() moves a creep's wander position
(clamped into bounds) and updates colour/brightness baselines; a surge on a
followed param needs no bookkeeping, because the next leg re-asserts the
curve target over slew_s from wherever the jump left the value — the
impulse decays by construction.

Deferral: pause / Dinner Party / Ambient hold everything (no legs, no
walk). Force Scene does NOT defer drift — a pinned scene keeps its
declared life (the design's stated exception).

Production S2 runs this against the RecordingExecutor: the engine is DARK
against real lights (status/observability only) until S3 hands SPECTRA the
room; headless tests prove the same code against the FacadeExecutor.
Executable specs: scripts/check_drift.py, tests/test_spectra_engine.py.
"""
from __future__ import annotations

import asyncio
import logging
import time
from random import Random
from typing import Any, Awaitable, Callable, Optional

from spectra.models import gradient2d
from spectra.models.scene import DriftSpec, SceneV2
from spectra.models.sequencer import CurvePoint, SelectorEntry
from spectra.services import color_journey, color_rotate
from spectra.services import selection_kernel as kernel
from spectra.services.selection_kernel import curve_eval

logger = logging.getLogger(__name__)

LEG_S = 20.0            # design band 10–30 s; one leg every 20 s
NEUTRAL_INTENSITY = 0.5  # follow's stated degradation when no feed exists

# The DROP kick (owner ask 2026-08-24, order item 2: "when there is a Drop, I
# want it to change colors. Jump a full extra step in the drift, but also use
# the drop energy to move the drift target 'up' on the 2D graph"). Both are
# HIS tuning knobs, named here rather than inlined:
DROP_Y_KICK = 0.5          # target_y += drop intensity * this (clamped to 1.0)
DROP_COLOR_GLIDE_MS = 150  # the drop's own colour change — fast, but not a
                           # hard snap (a drop is a moment, not a strobe)


class VirtualState:
    """Per-virtual engine truth, seeded at re-baseline: the effect type the
    glides address, whether colour-set colours own this virtual, the current
    palette strings (rotation baseline), the brightness baseline the gain
    envelope returns to, and the per-param numeric baselines momentary
    flare kinds return to (permanent kinds move them via on_surge; a
    creep-driven param's live truth stays the mechanism's position)."""

    def __init__(self, effect_type: str, entry_id: str, color_mode: str,
                 config: dict[str, Any]) -> None:
        self.effect_type = effect_type
        self.entry_id = entry_id
        self.set_mode = color_mode == "set"
        self.gradient: str | None = config.get("gradient")
        self.background_color: str | None = config.get("background_color")
        self.brightness_baseline: float = float(config.get("brightness", 1.0))
        # A toggle param's baseline (e.g. `reverse`) is kept as a real bool,
        # not coerced to float — a momentary flare on a toggle param needs
        # its true/false baseline back verbatim (scene_response._carried_value).
        self.param_baseline: dict[str, float | bool] = {
            k: (v if isinstance(v, bool) else float(v))
            for k, v in config.items() if isinstance(v, (int, float))}


def _registry_range(effect_type: str, param: str) -> Optional[tuple[float, float]]:
    """The param's own declared legal range (config/effect_params.json, via
    the shared fx.device_model registry) — None for an unregistered effect/
    param (untouched, never invented). Non-numeric metadata (toggle/enum/
    string) has no min/max and is likewise left alone."""
    from fx import device_model
    meta = device_model.get_param_meta(effect_type, param)
    if not meta:
        return None
    lo, hi = meta.get("min"), meta.get("max")
    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
        return None
    return float(lo), float(hi)


class Mechanism:
    def __init__(self, vid: str, param: str, spec: DriftSpec,
                 baseline: float, effect_type: str = "") -> None:
        self.vid = vid
        self.param = param
        self.spec = spec
        self.kind = spec.kind
        self.effect_type = effect_type
        # The degeneracy floor/ceiling: intersect the spec's own lo/hi with
        # the param's registered legal range, if any. An empty intersection
        # (a profile declared entirely outside the legal range) falls back
        # to the registry's own range rather than producing a zero-span
        # window — the registry always wins over a nonsensical spec.
        self.eff_lo, self.eff_hi = spec.lo, spec.hi
        reg = _registry_range(effect_type, param)
        if reg is not None:
            reg_lo, reg_hi = reg
            eff_lo, eff_hi = max(spec.lo, reg_lo), min(spec.hi, reg_hi)
            if eff_lo >= eff_hi:
                logger.warning(
                    "drift spec for %s.%s (lo=%g hi=%g) sits outside its "
                    "registered range [%g, %g] — falling back to the "
                    "registered range", effect_type, param, spec.lo,
                    spec.hi, reg_lo, reg_hi)
                eff_lo, eff_hi = reg_lo, reg_hi
            self.eff_lo, self.eff_hi = eff_lo, eff_hi
        # creep state: the wander position IS the carried baseline.
        self.position = min(max(baseline, self.eff_lo), self.eff_hi) \
            if spec.kind == "creep" else baseline
        self.direction = 1

    def as_status(self) -> dict:
        out = {"virtual_id": self.vid, "param": self.param, "kind": self.kind}
        if self.kind == "creep":
            out.update(position=round(self.position, 4), lo=self.eff_lo,
                       hi=self.eff_hi, rate_per_min=self.spec.rate_per_min,
                       motion=self.spec.motion)
        else:
            out.update(slew_s=self.spec.slew_s)
        return out


def _creep_step(mech: Mechanism, leg_s: float) -> float:
    """Advance a creep's wander one leg within the mechanism's EFFECTIVE
    bounds (spec lo/hi intersected with the registered legal range —
    Mechanism.__init__) — the NumericNudge bounce semantics made continuous;
    wrap folds into [lo, hi); hold parks at whichever bound it reaches and
    stops (direction 0), never oscillating back."""
    spec = mech.spec
    lo, hi = mech.eff_lo, mech.eff_hi
    span = hi - lo
    pos = mech.position + spec.rate_per_min * (leg_s / 60.0) * mech.direction
    if spec.motion == "wrap":
        pos = lo + ((pos - lo) % span)
    elif spec.motion == "hold":
        if pos >= hi:
            pos, mech.direction = hi, 0
        elif pos <= lo:
            pos, mech.direction = lo, 0
    else:
        while pos > hi or pos < lo:
            if pos > hi:
                pos = hi - (pos - hi)
                mech.direction = -1
            else:
                pos = lo + (lo - pos)
                mech.direction = 1
    mech.position = pos
    return pos


class DriftConductor:
    """Constructor injectables exist for the executable specs; production
    (services/engine.py) passes the RecordingExecutor and the bridge's
    intensity/deferral feeds."""

    def __init__(
        self, *,
        executor,
        clock: Callable[[], float] = time.monotonic,
        leg_s: float = LEG_S,
        intensity: Callable[[], Optional[float]] | None = None,
        deferral: Callable[[], Optional[str]] | None = None,
        broadcast: Callable[[dict], Awaitable[None]] | None = None,
        drift_profiles: Callable[[], dict] | None = None,
        curve_profiles: Callable[[], dict] | None = None,
        room_load: Callable[[], color_journey.RoomColorState] | None = None,
        room_save: Callable[[color_journey.RoomColorState], None] | None = None,
        set_position: Callable[[str], Optional[float]] | None = None,
        set_cards: Callable[[], list] | None = None,
        sequencer_config: Callable[[], Any] | None = None,
        genre_bucket: Callable[[], Optional[str]] | None = None,
        gradient_profiles: Callable[[], dict] | None = None,
        room_controls: Callable[[], Any] | None = None,
        rng: Random | None = None,
    ) -> None:
        self.executor = executor
        self._clock = clock
        self.leg_s = leg_s
        self._intensity = intensity or (lambda: None)
        self._deferral = deferral or (lambda: None)
        self._broadcast = broadcast or self._no_broadcast
        self._drift_profiles = drift_profiles or self._default_drift_profiles
        self._curve_profiles = curve_profiles or self._default_curve_profiles
        self._room_load = room_load or color_journey.load_room
        self._room_save = room_save or color_journey.save_room
        self._set_position = set_position or self._default_set_position
        self._set_cards = set_cards or self._default_set_cards
        self._sequencer_config = sequencer_config \
            or self._default_sequencer_config
        self._genre_bucket = genre_bucket or (lambda: None)
        self._gradient_profiles = gradient_profiles \
            or self._default_gradient_profiles
        self._room_controls = room_controls or self._default_room_controls
        self._rng = rng or Random()

        self.scene: SceneV2 | None = None
        self.virtuals: dict[str, VirtualState] = {}
        self.mechanisms: list[Mechanism] = []
        self._last_leg: dict | None = None
        self._last_rebaseline: dict | None = None
        self._deferred_by: str | None = None

    # ── re-baseline (any scene fire) ─────────────────────────────────────────

    def _resolve_spec(self, ref) -> Optional[DriftSpec]:
        if ref.inline is not None:
            return ref.inline
        profile = self._drift_profiles().get(ref.profile)
        if profile is None:
            logger.warning("drift ref names missing profile '%s' — skipped",
                           ref.profile)
            return None
        return profile.spec

    def on_scene_fire(self, scene: SceneV2, writes: list[dict],
                      color_set_id: str | None = None) -> None:
        """Drop all legs; restart every mechanism from the fire's resolved
        initial conditions. The wheel position does not move — custody may
        transfer (color_journey semantics), the story never snaps — but the
        journey's DESTINATION clears: the fire changed the palette (and
        possibly custody/pace), so the new steering picks a fresh bearing
        on the next leg."""
        entries = {dev.id: dev for dev in scene.devices}
        self.scene = scene
        self.virtuals = {}
        self.mechanisms = []
        for w in writes:
            vid = w["virtual_id"]
            state = VirtualState(w["effect_type"], w.get("entry_id", ""),
                                 w.get("color_mode", "set"), w["config"])
            self.virtuals[vid] = state
            entry = entries.get(state.entry_id)
            if entry is None:
                continue
            # Stepped-effect entry: drift follows the variant this fire
            # selected (the write's effect). A declared drift whose param
            # the selected variant doesn't set sits out until a fire
            # selects one that does — stated, never a glide on a param the
            # live effect doesn't carry.
            selected_params = (entry.params_for_effect(state.effect_type)
                               if entry.effect_steps else None)
            for param, ref in entry.drift.items():
                if (selected_params is not None
                        and param not in selected_params
                        and param not in ("brightness",
                                          "background_brightness")):
                    continue
                spec = self._resolve_spec(ref)
                if spec is None:
                    continue
                if spec.kind == "creep":
                    fallback = (spec.lo + spec.hi) / 2.0
                    raw = w["config"].get(param, fallback)
                    baseline = float(raw) if isinstance(raw, (int, float)) \
                        else fallback
                else:
                    baseline = float(w["config"].get(param, 0.0) or 0.0)
                self.mechanisms.append(Mechanism(vid, param, spec, baseline,
                                                 effect_type=state.effect_type))
        room = self._room_load()
        update: dict[str, Any] = {"destination": None}
        if color_set_id is not None:
            update["active_set_id"] = color_set_id
        self._room_save(room.model_copy(update=update))
        journey = color_journey.active_journey(self._room_load(), scene)
        self._last_rebaseline = {
            "at": self._clock(), "scene_id": scene.id, "scene_name": scene.name,
            "mechanisms": len(self.mechanisms),
            "journey_custody": journey.custody,
            "journey_degrees_per_min": journey.degrees_per_min,
        }
        logger.info("drift re-baseline: scene '%s', %d mechanism(s), journey "
                    "custody=%s @ %g°/min", scene.name, len(self.mechanisms),
                    journey.custody, journey.degrees_per_min)

    # ── carry (surges move the baseline drift resumes from) ──────────────────

    def on_surge(self, changes: dict[tuple[str, str], Any]) -> None:
        """(virtual_id, param) → new value, already applied by the response
        engine. Creep wanders resume from the moved point (clamped into
        bounds); brightness/colour baselines update; followed params need
        nothing — the next leg re-asserts over slew_s."""
        for (vid, param), value in changes.items():
            for mech in self.mechanisms:
                if mech.vid == vid and mech.param == param \
                        and mech.kind == "creep" \
                        and isinstance(value, (int, float)):
                    mech.position = min(max(float(value), mech.eff_lo),
                                        mech.eff_hi)
            state = self.virtuals.get(vid)
            if state is None:
                continue
            if isinstance(value, bool):
                state.param_baseline[param] = value
            elif isinstance(value, (int, float)):
                state.param_baseline[param] = float(value)
            if param == "brightness" and isinstance(value, (int, float)):
                state.brightness_baseline = float(value)
            elif param == "gradient" and isinstance(value, str):
                state.gradient = value
            elif param == "background_color" and isinstance(value, str):
                state.background_color = value

    # ── the leg ──────────────────────────────────────────────────────────────

    async def tick(self) -> dict | None:
        """One conductor leg. Returns the leg record (None when deferred)."""
        self._deferred_by = self._deferral()
        if self._deferred_by is not None:
            return None
        leg_ms = int(self.leg_s * 1000)
        # (vid, duration_ms) → params, so each virtual gets ONE glide per
        # distinct duration this leg.
        batches: dict[tuple[str, int], dict[str, Any]] = {}
        legs: list[dict] = []

        # A room is never set-less: bootstrap the first set before the leg
        # (owner defect fix — see _bootstrap_room_color).
        bootstrap = None
        if self._room_load().active_set_id is None:
            bootstrap = await self._bootstrap_room_color(
                color_journey.active_journey(self._room_load(), self.scene))

        active_gradient_id = self._room_controls().active_gradient_id
        if active_gradient_id is not None:
            # An active gradient REPLACES the wheel journey for set-mode
            # virtuals — held exactly like a live rainbow palette holds it
            # (a different colour source has taken over; see the module
            # docstring's "gradient drift" section).
            journey_rec = {"custody": "room", "paused": True,
                          "held_for": "gradient_drift"}
            gradient_rec = self._gradient_leg(active_gradient_id, batches,
                                              leg_ms, legs)
        else:
            journey_rec = self._journey_leg(batches, leg_ms, legs)
            gradient_rec = {"active": False}
        if bootstrap is not None:
            journey_rec["bootstrap"] = bootstrap

        intensity = self._intensity()
        if intensity is None:
            intensity = NEUTRAL_INTENSITY
        for mech in self.mechanisms:
            if mech.kind == "creep":
                target = _creep_step(mech, self.leg_s)
                duration = leg_ms
            else:
                target = curve_eval(self._follow_points(mech.spec), intensity)
                reg = _registry_range(mech.effect_type, mech.param)
                if reg is not None:
                    target = min(max(target, reg[0]), reg[1])
                duration = int(mech.spec.slew_s * 1000)
            batches.setdefault((mech.vid, duration), {})[mech.param] = target
            legs.append({"virtual_id": mech.vid, "param": mech.param,
                         "kind": mech.kind, "target": round(float(target), 4),
                         "duration_ms": duration})

        for (vid, duration), params in batches.items():
            state = self.virtuals.get(vid)
            if state is None:
                continue
            await self.executor.glide(vid, state.effect_type, params, duration)

        record = {"at": self._clock(), "journey": journey_rec,
                  "gradient": gradient_rec, "legs": legs,
                  "intensity": round(intensity, 4)}
        self._last_leg = record
        await self._broadcast({"type": "drift_leg", **record})
        return record

    def _follow_points(self, spec: DriftSpec):
        if spec.inline_points is not None:
            return spec.inline_points
        if spec.curve_ref is not None:
            profile = self._curve_profiles().get(spec.curve_ref)
            if profile is not None:
                return profile.points
            logger.warning("follow curve_ref '%s' missing — holding neutral",
                           spec.curve_ref)
        # No curve = hold wherever the intensity axis is (identity map).
        from spectra.models.scene import CurveMapPoint
        return [CurveMapPoint(x=0.0, y=0.0), CurveMapPoint(x=1.0, y=1.0)]

    def _destination_pool(self) -> dict[str, tuple[Any, float]]:
        """Eligible chromatic destinations under current custody, as
        {set_id: (card, wheel_position)}: an OVERRIDE picks within its own
        palette bounds (the scene's accepted sets); room custody picks from
        every set not globally opted out. Rainbow/achromatic sets are never
        destinations — they have no wheel position to travel toward, and a
        DISABLED set is never a destination either (owner ask
        2026-08-25)."""
        scene = self.scene
        override = (scene is not None
                    and scene.color_journey.mode == "override")
        pool: dict[str, tuple[Any, float]] = {}
        for card in self._set_cards():
            if getattr(card, "kind", "set") != "set":
                continue
            # DISABLED (owner ask 2026-08-25, models/color_set.py's
            # ColorSetCard.disabled) — a disabled set is never chosen as a
            # journey destination, in either custody. It keeps painting if
            # it is the room's CURRENT set (nothing yanks it mid-paint);
            # this only stops it being travelled TO again.
            if getattr(card, "disabled", False):
                continue
            if override:
                if not scene.accepts_color_set(card):
                    continue
            elif getattr(card, "scene_v2_opt_out", False):
                continue
            position = self._set_position(card.id)
            if position is None:
                continue
            pool[card.id] = (card, position)
        return pool

    def _select_destination(
        self, journey: color_journey.EffectiveJourney, from_deg: float,
        exclude_id: Optional[str],
    ) -> Optional[color_journey.JourneyDestination]:
        """Pick the next destination with the SHIPPED selector (curve ×
        genre × wheel-travel, decision-3 ladder). Selector entries narrow
        and weight the pool when configured; an unconfigured selector falls
        back to neutral entries over every eligible set, so the journey
        keeps moving (uniform-among-eligible is the ladder's own rung, not
        an invention). Terminal keep → None → the walk holds (never forced
        churn). The pick fixes its own pace from its distance."""
        pool = self._destination_pool()
        if not pool:
            return None
        config = self._sequencer_config()
        curves = self._curve_profiles()
        positions = {sid: pos for sid, (_name, pos) in pool.items()}
        entries = {sid: entry
                   for sid, entry in config.color_set_entries.items()
                   if sid in positions}
        if not entries:
            entries = {sid: SelectorEntry() for sid in positions}
        wheel_profile = (curves.get(config.wheel_travel_curve)
                         if config.wheel_travel_curve else None)
        candidates = kernel.build_color_set_candidates(
            entries, curves,
            genre_bucket=self._genre_bucket(),
            room_deg=from_deg,
            set_positions=positions,
            wheel_points=(wheel_profile.points if wheel_profile
                          else [CurvePoint(x=0.0, y=1.0)]))
        intensity = self._intensity()
        if intensity is None:
            intensity = NEUTRAL_INTENSITY
        pick = kernel.select_color_set(candidates, intensity=intensity,
                                       rng=self._rng, current_id=exclude_id)
        if pick.picked_id is None:
            return None
        position = positions[pick.picked_id]
        travel = abs(color_journey.signed_travel(from_deg, position))
        return color_journey.JourneyDestination(
            set_id=pick.picked_id,
            set_name=getattr(pool[pick.picked_id][0], "name",
                             pick.picked_id),
            position_deg=position,
            pace_deg_per_min=color_journey.destination_pace(
                journey.degrees_per_min, travel),
            from_deg=from_deg,
            rung=pick.rung)

    async def apply_color_set(self, card) -> int:
        """Land a colour-set card on the live scene's set-mode virtuals as
        a JUMP and move the palette/brightness baselines with it (the
        conductor owns the baselines drift resumes from). Returns virtuals
        landed — 0 with no live scene, which still leaves the set active
        for the next fire to wear (scene_compiler.fire_scene)."""
        from spectra.services import scene_compiler
        from spectra.services.room_controls import resolve_authored_bg_color
        from fx import device_model
        by_vid = scene_compiler._set_entry_by_virtual(card)
        controls = self._room_controls()
        landed = 0
        for vid, state in self.virtuals.items():
            if not state.set_mode:
                continue
            entry = by_vid.get(vid)
            if entry is None:
                continue
            params: dict[str, Any] = {}
            if entry.color_value:
                params["gradient"] = entry.color_value
                state.gradient = entry.color_value
            if entry.bg_color and not device_model.bg_color_blocked(
                    state.effect_type):
                bg_color = resolve_authored_bg_color(
                    entry.bg_color, controls.display_mode,
                    controls.display_light_bg_color)
                params["background_color"] = bg_color
                state.background_color = bg_color
            if entry.bg_mode:
                params["background_mode"] = entry.bg_mode
            if entry.brightness is not None:
                params["brightness"] = entry.brightness
                state.brightness_baseline = float(entry.brightness)
            if entry.background_brightness is not None:
                params["background_brightness"] = entry.background_brightness
            if params:
                await self.executor.jump(vid, state.effect_type, params)
                landed += 1
        return landed

    async def apply_set_directly(self, card) -> dict:
        """The supported manual apply-this-set surface (owner defect fix,
        part b — reached via POST /api/room-color/apply): the card becomes
        the room's active set, the wheel anchors at its position (rainbow:
        colours land but the wheel stays where it was), its colours land on
        any live set-mode virtuals, and the journey clears its bearing to
        travel on from the new anchor."""
        position = self._set_position(card.id)
        landed = await self.apply_color_set(card)
        room = self._room_load()
        update: dict[str, Any] = {"active_set_id": card.id,
                                  "destination": None}
        if position is not None:
            update["wheel_position_deg"] = position
        self._room_save(room.model_copy(update=update))
        logger.info("room colour set applied directly: '%s' (%d virtuals)",
                    getattr(card, "name", card.id), landed)
        from spectra.services import fire_history
        fire_history.record_fire("color_sets", card.id, {
            "set_name": getattr(card, "name", card.id),
            "position_deg": position,
        })
        return {"applied": card.id,
                "set_name": getattr(card, "name", card.id),
                "position_deg": position, "virtuals": landed}

    async def _bootstrap_room_color(
            self, journey: color_journey.EffectiveJourney) -> Optional[dict]:
        """(owner defect fix, part a) A ROOM IS NEVER SET-LESS: with no
        active set — first boot, wiped state — the journey immediately
        selects its first set with the shipped selector (an unanchored
        wheel is neutral for every candidate) and APPLIES it as the room's
        anchor. Destination travel then proceeds from there. Without this,
        nothing ever applies a first set (the sequencer is off, the flare
        jump can't pick from an unanchored journey) and scenes render
        effect-default LedFX wheel colours instead of the owner's sets."""
        pool = self._destination_pool()
        if not pool:
            return None
        config = self._sequencer_config()
        curves = self._curve_profiles()
        positions = {sid: pos for sid, (_card, pos) in pool.items()}
        entries = {sid: entry
                   for sid, entry in config.color_set_entries.items()
                   if sid in positions}
        if not entries:
            entries = {sid: SelectorEntry() for sid in positions}
        wheel_profile = (curves.get(config.wheel_travel_curve)
                         if config.wheel_travel_curve else None)
        candidates = kernel.build_color_set_candidates(
            entries, curves,
            genre_bucket=self._genre_bucket(),
            room_deg=None,
            set_positions=positions,
            wheel_points=(wheel_profile.points if wheel_profile
                          else [CurvePoint(x=0.0, y=1.0)]))
        intensity = self._intensity()
        if intensity is None:
            intensity = NEUTRAL_INTENSITY
        pick = kernel.select_color_set(candidates, intensity=intensity,
                                       rng=self._rng, current_id=None)
        if pick.picked_id is None:
            return None
        # Found missing 2026-08-19 (same audit as scene_compiler.
        # room_active_set): _destination_pool's cards are RAW (from
        # _set_cards(), no overlay) — apply_set_directly's other two
        # callers (POST /room-color/apply, the select_color_set trigger
        # action) both resolve through color_set_groups before calling
        # it; the bootstrap picked its own destination pool's card
        # directly and skipped that resolution.
        from spectra.services import color_set_groups
        chosen = color_set_groups.resolve_for_fire(pool[pick.picked_id][0])
        result = await self.apply_set_directly(chosen)
        result["rung"] = pick.rung
        logger.info("room colour bootstrap: first set '%s' selected and "
                    "applied", result["set_name"])
        return result

    def _destination_rec(self, dest: Optional[color_journey.JourneyDestination],
                         wheel_deg: Optional[float]) -> Optional[dict]:
        if dest is None:
            return None
        return {"set_id": dest.set_id, "set_name": dest.set_name,
                "position_deg": round(dest.position_deg, 2),
                "pace_deg_per_min": round(dest.pace_deg_per_min, 3),
                "progress": round(color_journey.progress(dest, wheel_deg), 3),
                "rung": dest.rung}

    def _journey_leg(self, batches: dict, leg_ms: int,
                     legs: list[dict]) -> dict:
        """One destination-journey leg under whoever steers: ensure a
        bearing exists (select one if not), travel toward it along the
        shortest arc at ITS pace, rotate the active palette with the wheel
        on set-mode virtuals, land exactly on arrival and reselect. Persists
        wheel + bearing to room state so restarts and custody transfers
        read one truth."""
        room = self._room_load()
        journey = color_journey.active_journey(room, self.scene)
        rainbow = False
        if room.active_set_id is not None:
            rainbow = self._set_position(room.active_set_id) is None
        rec: dict[str, Any] = {
            "custody": journey.custody,
            "degrees_per_min": journey.degrees_per_min,
            "wheel_position_deg": (round(room.wheel_position_deg, 2)
                                   if room.wheel_position_deg is not None
                                   else None),
            "paused": True, "arrived": False,
            "destination": self._destination_rec(room.destination,
                                                 room.wheel_position_deg),
        }
        # Held: no chromatic story yet, rainbow palette live, or pace 0
        # (pace_factor 0 / a zero spec). Bearing kept, nothing travels.
        if (room.wheel_position_deg is None or rainbow
                or journey.degrees_per_min <= 0.0):
            return rec

        dest = room.destination
        if dest is None:
            dest = self._select_destination(journey, room.wheel_position_deg,
                                            room.active_set_id)
            if dest is None:
                return rec   # no eligible destination — the walk holds
            rec["destination"] = self._destination_rec(
                dest, room.wheel_position_deg)

        new_deg, arrived = color_journey.step_toward(
            room.wheel_position_deg, dest.position_deg,
            dest.pace_deg_per_min, self.leg_s)
        delta = color_journey.signed_travel(room.wheel_position_deg, new_deg)
        rec.update(paused=False, arrived=arrived,
                   wheel_position_deg=round(new_deg, 2))
        if delta != 0.0:
            from spectra.services.room_controls import resolve_authored_bg_color
            controls = self._room_controls()
            for vid, state in self.virtuals.items():
                if not state.set_mode:
                    continue
                params: dict[str, Any] = {}
                if state.gradient:
                    state.gradient = color_rotate.rotate_color_value(
                        state.gradient, delta)
                    params["gradient"] = state.gradient
                if state.background_color:
                    # A hue rotation of an achromatic authored black is a
                    # no-op (value=0 in HSV carries no hue) — this rotated
                    # value carries the SAME authored #000000 through as
                    # many legs as run, so the light-mode substitution
                    # below still fires correctly no matter how long the
                    # journey has been walking. Once resolved (light mode
                    # only) the substitute colour rotates like any other
                    # authored colour from here on — expected, not a
                    # separate case to special-case.
                    rotated = color_rotate.rotate_color_value(
                        state.background_color, delta)
                    bg_color = resolve_authored_bg_color(
                        rotated, controls.display_mode,
                        controls.display_light_bg_color)
                    state.background_color = bg_color
                    params["background_color"] = bg_color
                if params:
                    batches.setdefault((vid, leg_ms), {}).update(params)
                    legs.append({"virtual_id": vid, "param": "palette",
                                 "kind": "journey",
                                 "target": round(delta, 3),
                                 "duration_ms": leg_ms})
        if arrived:
            # ON ARRIVAL: select the next destination (arrived set
            # excluded) and set off again next leg.
            dest = self._select_destination(journey, new_deg, dest.set_id)
            rec["destination"] = self._destination_rec(dest, new_deg)
        else:
            rec["destination"] = self._destination_rec(dest, new_deg)
        self._room_save(room.model_copy(
            update={"wheel_position_deg": new_deg, "destination": dest}))
        return rec

    # ── the two-dimensional drift gradient ───────────────────────────────────

    def on_intensity_event(self) -> None:
        """A trigger fired, or an analysed (song) transition fired — his own
        adopted proposal for the gradient's Y-axis "chosen well ahead of
        when it reaches there" problem: re-anchor the Y TARGET to the
        current live intensity right now, rather than re-targeting every
        leg (which would just chase each tick's momentary fluctuation) or
        never re-targeting at all (which would leave Y stuck at whatever it
        started at). Y then drifts toward this target over subsequent legs,
        same shape as every other mechanism here — it does not jump.
        Called from trigger_engine.py's _fire()/_fire_transition(); a no-op
        while no gradient is active (still cheap: one small file write)."""
        intensity = self._intensity()
        if intensity is None:
            intensity = NEUTRAL_INTENSITY
        room = self._room_load()
        self._room_save(room.model_copy(
            update={"gradient_target_y": max(0.0, min(1.0, intensity))}))

    def _gradient_color_params(self, color: str) -> list[tuple[str, dict]]:
        """The gradient's landing rule, shared by the scheduled leg and the
        drop kick: every set-mode virtual takes the sampled colour on
        whichever of gradient/background_color it ALREADY carries (the same
        "only touch what's already there" rule _journey_leg's palette
        rotation follows). Mutates VirtualState so the engine's own carried
        colour stays true; returns (vid, params) for the caller to write
        however it writes (batched into a leg, or immediately)."""
        out: list[tuple[str, dict]] = []
        for vid, state in self.virtuals.items():
            if not state.set_mode:
                continue
            params: dict[str, Any] = {}
            if state.gradient:
                state.gradient = color
                params["gradient"] = color
            if state.background_color:
                state.background_color = color
                params["background_color"] = color
            if params:
                out.append((vid, params))
        return out

    async def on_drop_event(self, intensity: float | None = None) -> dict | None:
        """A DROP fired (owner ask 2026-08-24, order item 2, his words: "On
        All effects, when there is a Drop, I want it to change colors. Jump a
        full extra step in the drift, but also use the drop energy to move
        the drift target 'up' on the 2D graph"). Three things, in that order,
        and ONLY while a gradient is active — a strict no-op otherwise (the
        wheel colour journey is deliberately out of scope):

          X — advance one FULL extra leg-step (self.leg_s over the room's
              gradient_x_period_s), through gradient2d.advance_x so the
              profile's own loop/bounce x_mode governs it exactly as a
              scheduled leg does. This is IN ADDITION to the normal ~20 s
              leg schedule: the next leg simply continues from here, since
              the advanced x/direction persist to room state.
          Y — push the TARGET up by the drop's energy (DROP_Y_KICK), never
              down, clamped to 1.0. Y ITSELF is untouched: it keeps drifting
              toward the target over gradient_y_slew_s on ordinary legs,
              same as on_intensity_event's own retarget.
          colour — sample at the advanced (x, y-as-it-is-right-now) and land
              it NOW over DROP_COLOR_GLIDE_MS, rather than waiting up to a
              full leg for the room to catch up with the music.

        Called from services/engine.py's fire_response_event when
        event_class == "drop" — the SAME already-mode-gated/preview-gated
        path a real drop drives, never a second route. Honours the
        conductor's own deferral (ambient/dinner-party/preview/force-scene)
        like every other write this class makes."""
        room_controls = self._room_controls()
        gradient_id = room_controls.active_gradient_id
        if gradient_id is None:
            return None
        profile = self._gradient_profiles().get(gradient_id)
        if profile is None:
            logger.warning("drop kick: active_gradient_id '%s' names no saved "
                           "gradient — skipped", gradient_id)
            return None
        deferred_by = self._deferral()
        if deferred_by is not None:
            return {"active": False, "deferred_by": deferred_by}
        if intensity is None:
            intensity = self._intensity()
        if intensity is None:
            intensity = NEUTRAL_INTENSITY
        intensity = max(0.0, min(1.0, float(intensity)))

        room = self._room_load()
        x_delta = self.leg_s / max(room_controls.gradient_x_period_s, 1e-6)
        new_x, new_dir = gradient2d.advance_x(
            room.gradient_x, room.gradient_x_direction, x_delta, profile.x_mode)
        new_target_y = min(1.0, room.gradient_target_y + intensity * DROP_Y_KICK)
        color = gradient2d.sample(profile.top, profile.bottom, new_x,
                                  room.gradient_y)
        rec: dict[str, Any] = {
            "active": True, "kick": "drop", "gradient_id": profile.id,
            "gradient_name": profile.name, "intensity": round(intensity, 4),
            "x": round(new_x, 4), "y": round(room.gradient_y, 4),
            "target_y": round(new_target_y, 4), "color": color, "legs": [],
        }
        if color is not None:
            for vid, params in self._gradient_color_params(color):
                state = self.virtuals[vid]
                await self.executor.glide(vid, state.effect_type, params,
                                          DROP_COLOR_GLIDE_MS)
                rec["legs"].append({"virtual_id": vid, "param": "gradient2d",
                                    "kind": "gradient", "target": color,
                                    "duration_ms": DROP_COLOR_GLIDE_MS})
        self._room_save(room.model_copy(update={
            "gradient_x": new_x, "gradient_x_direction": new_dir,
            "gradient_target_y": new_target_y}))
        await self._broadcast({"type": "drift_gradient_drop", **rec})
        return rec

    def _gradient_leg(self, gradient_id: str, batches: dict, leg_ms: int,
                      legs: list[dict]) -> dict:
        """One leg of the 2D drift gradient: advance X (time) a fixed
        fraction of its span, drift Y toward its last-set target, sample the
        gradient at the resulting (x, y), and land that colour on every
        set-mode virtual's gradient/background_color — whichever of those
        two params the virtual already carries (same "only touch what's
        already there" rule _journey_leg's palette rotation follows)."""
        profile = self._gradient_profiles().get(gradient_id)
        if profile is None:
            logger.warning("active_gradient_id '%s' names no saved gradient "
                           "— gradient drift holds", gradient_id)
            return {"active": False, "missing": gradient_id}
        room_controls = self._room_controls()
        room = self._room_load()
        x_delta = self.leg_s / max(room_controls.gradient_x_period_s, 1e-6)
        new_x, new_dir = gradient2d.advance_x(
            room.gradient_x, room.gradient_x_direction, x_delta, profile.x_mode)
        y_step = min(1.0, self.leg_s / max(room_controls.gradient_y_slew_s, 1e-6))
        new_y = room.gradient_y + (room.gradient_target_y - room.gradient_y) * y_step
        color = gradient2d.sample(profile.top, profile.bottom, new_x, new_y)
        rec: dict[str, Any] = {
            "active": True, "gradient_id": profile.id, "gradient_name": profile.name,
            "x": round(new_x, 4), "y": round(new_y, 4),
            "target_y": round(room.gradient_target_y, 4), "color": color,
        }
        if color is not None:
            for vid, params in self._gradient_color_params(color):
                batches.setdefault((vid, leg_ms), {}).update(params)
                legs.append({"virtual_id": vid, "param": "gradient2d",
                             "kind": "gradient", "target": color,
                             "duration_ms": leg_ms})
        self._room_save(room.model_copy(update={
            "gradient_x": new_x, "gradient_x_direction": new_dir,
            "gradient_y": new_y}))
        return rec

    # ── supervised production loop ───────────────────────────────────────────

    async def run(self) -> None:
        # First tick immediately: a set-less room bootstraps its first
        # colour set at engine start, not one leg-interval later.
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("drift conductor: leg failed")
            await asyncio.sleep(self.leg_s)

    # ── observability ────────────────────────────────────────────────────────

    def status(self) -> dict:
        room = self._room_load()
        journey = color_journey.active_journey(room, self.scene)
        rainbow = (room.active_set_id is not None
                   and self._set_position(room.active_set_id) is None)
        return {
            "executor_mode": self.executor.mode,
            "leg_s": self.leg_s,
            "active_scene": ({"id": self.scene.id, "name": self.scene.name}
                             if self.scene else None),
            "deferred_by": self._deferred_by,
            "journey": {
                "custody": journey.custody,
                "degrees_per_min": journey.degrees_per_min,
                "room_degrees_per_min": room.journey.degrees_per_min,
                "wheel_position_deg": room.wheel_position_deg,
                "active_set_id": room.active_set_id,
                "rainbow_paused": rainbow,
                "destination": self._destination_rec(
                    room.destination, room.wheel_position_deg),
            },
            "mechanisms": [m.as_status() for m in self.mechanisms],
            "gradient": {
                "active_gradient_id": self._room_controls().active_gradient_id,
                "x": room.gradient_x, "y": room.gradient_y,
                "target_y": room.gradient_target_y,
            },
            "last_leg": self._last_leg,
            "last_rebaseline": self._last_rebaseline,
        }

    # ── production defaults (lazy imports; specs inject fakes) ───────────────

    @staticmethod
    def _default_drift_profiles() -> dict:
        from spectra.services import drift_profiles
        return drift_profiles.load_all()

    @staticmethod
    def _default_curve_profiles() -> dict:
        from spectra.services import sequencer_store
        return sequencer_store.load_curves()

    @staticmethod
    def _default_gradient_profiles() -> dict:
        from spectra.services import gradient2d_store
        return gradient2d_store.load_all()

    @staticmethod
    def _default_room_controls():
        from spectra.services.room_controls import load_room_controls
        return load_room_controls()

    @staticmethod
    def _default_set_position(set_id: str) -> Optional[float]:
        from spectra.services import color_sets, color_wheel
        card = color_sets.get_by_id(set_id)
        if card is None:
            return None
        return color_wheel.wheel_position(card).position_deg

    @staticmethod
    def _default_set_cards() -> list:
        from spectra.services import color_sets
        return color_sets.list_all()

    @staticmethod
    def _default_sequencer_config():
        from spectra.services import sequencer_store
        return sequencer_store.load_config()

    @staticmethod
    async def _no_broadcast(payload: dict) -> None:
        pass
