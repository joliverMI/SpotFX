"""The response engine — surges (report §2.4). Retires the "bands carried
but not evaluated" placeholder: all four event classes (flare / charge /
lull / drop) now EXECUTE against the active scene's responses block.

Per event, fed by the bridge with the fire's intensity:

  0. CHARGE/LULL/DROP DRIVE THE REAL PHASE MACHINERY FIRST (the owner's
     five-updates item 2). The build/suspend/release grammar lives IN the
     vendored effects (fx/effects — the fork's charge/lull/drop handling:
     phase + phase_progress config keys, edge-detected, per-family
     choreography, shared orphan watchdog); this engine drives it exactly
     the way the original SpotFX program did (trigger_engine._fire_phase):
     an instant {"phase": <class>, "phase_progress": 0.0} arm per
     phase-capable virtual (the 0.0 reset re-arms the edge), then a glide
     of phase_progress → 1.0 over the class's ramp — charge/lull DYNAMICALLY
     stretch to ~90% of the real gap to the next trigger when it's known
     (_phase_ramp_ms, the OVERRIDE BLEND equivalent), else the flat 4000 ms/
     2500 ms tuned default; drop always stays the fixed 400 ms snap. The
     drive fires for EVERY charge/lull/drop event, band or no band — exactly
     as the
     original fired the phase for every phase event, with the per-scene
     band riding on top as the scene's colouring. Per-family grammar:
     docs/SPECTRA_RESPONSES.md. Phase keys ride ONLY these dedicated
     writes (the registry gate keeps them out of band patches; the
     editor/compiler never carries them) — a re-sent stale "charge" would
     spuriously re-fire the choreography with no drop coming.
  1. Select the band containing the intensity ([min, max); the top band is
     inclusive at exactly 1.0 so a full-scale fire always matches). No band
     → the class's BAND extras stay silent at that intensity — bands are
     the response's WHEN along the axis (the phase drive above is not
     band-gated).
  2. THE BAND SELECTS AND SCALES NAMED KINDS (the owner's item-8 shape):
     band.kinds maps kind name → scale factor; each kind executes per its
     type, in a fixed order so the carry interplay is deterministic —
     dice drift-jumps, permanent param moves, momentary param moves,
     permanent gains, momentary gains, colour drift-jumps (the legacy
     reroll → patch → gain → colour order, generalized):
       drift_jump/dice      — the scene's 🎲 (signal="random") bindings
                  re-resolve with fresh dice. A re-rolled value the param
                  registry marks smooth (a genuine continuous numeric —
                  e.g. STAR's `star`) GLIDES to the new value over
                  DICE_REROLL_GLIDE_MS instead of snapping (owner report,
                  2026-08-17: re-rolling every ordinary flare read as a
                  strobe). Anything not smooth (toggle / string / integer
                  — e.g. STAR's `edges`, itself already sticky and
                  excluded above) still JUMPS; it can't be meaningfully
                  interpolated. The rolls CARRY either way. Scale is
                  inert (a roll has no magnitude — stated).
       momentary/permanent params — absolute targets, name-broadcast: a
                  key lands on every virtual whose live effect carries the
                  param (shared registry truth). Scale s moves the target
                  to baseline + (declared − baseline)·s against the
                  carried-now baseline, clamped to the param's registry
                  range; ×1 lands the declared value verbatim. Landing
                  respects the SAME registry smooth gate as a dice re-roll
                  (fixed 2026-08-17, _move_params): a registry-smooth
                  param glides over DICE_REROLL_GLIDE_MS, anything else
                  still jumps — a patch on a smooth param used to always
                  jump regardless, e.g. STAR's "Flare patch 0.7–1" setting
                  `star` (smooth=true) to 0.0 every high-intensity flare.
                  PERMANENT carries — the landed value is the new baseline
                  drift resumes from. MOMENTARY schedules a return: the
                  release glides back to the baseline AS CARRIED AT FLUSH
                  TIME (a creep's current wander position, or the tracked
                  param baseline) — the spike never moves the baseline;
                  the release itself was already an unconditional glide
                  (flush_releases, PULSE_RELEASE_S) before this fix and is
                  unaffected by it.
       momentary/permanent gain — the brightness envelope around the
                  carried baseline at effective gain 1 + (gain − 1)·s:
                  MOMENTARY spikes to baseline×effective and glides back
                  (release scheduled after the spike holds a beat);
                  PERMANENT glides to baseline×effective and HOLDS — the
                  landed level becomes the new baseline.
       drift_jump/color_set — roll the shipped colour-set selector
                  (curve × genre × wheel-travel) against the scene's
                  eligible sets and the ROOM wheel position at the
                  scale-steered intensity (clamped ×s), and land the pick
                  with the intensity-scaled RAMP-IN (the owner's
                  refinement of jump-not-blend: gentle flares ease in over
                  COLOR_JUMP_RAMP_MS_GENTLE, full-scale flares land hard
                  near COLOR_JUMP_RAMP_MS_HARD, hue-arc blend — never
                  through grey, never a crossfade re-creation); the
                  terminal rung KEEPS the current colours (decision 3 —
                  never forced churn). A chromatic pick moves the room's
                  wheel position at selection, and the room journey
                  RESUMES FROM THE NEW POINT — the jump moves the story,
                  the walk carries on.
       color_rotate — the ROTATE-AND-BACK flare (owner ask, 2026-08-20):
                  rotates the live foreground colour's hue by an
                  intensity-scaled amount, ramps in to land the full
                  rotation ON the trigger mark, dwells, then fades back to
                  the exact original — see _color_rotate's own docstring.
                  MOMENTARY in spirit (spike-and-return) but never carries
                  and never touches the jumps/glides dicts the param/gain
                  kinds above share, so it composes freely alongside a
                  shape-targeting kind in the same band.
  Stepped-effect entries (SceneDeviceConfig.effect_steps) and surges — the
  stated interplay, simple on purpose: EFFECT SELECTION IS FIRE-TIME ONLY.
  A surge never switches an entry's effect; dice re-rolls re-resolve the
  params of the variant the FIRE selected (the entry's live effect — the
  same registry gate that already scopes param moves), param moves
  broadcast by name against the live effects as always, and the next FIRE
  re-selects and re-baselines honestly (conductor.on_scene_fire seeds from
  the fire's writes, which carry the selected effect).

  3. CARRY (the owner's words): re-rolls, permanent moves, held gains, and
     colour jumps permanently move the baseline drift resumes from
     (conductor.on_surge); momentary moves never do. A surge on a followed
     param is an impulse the follow re-asserts from smoothly over slew_s —
     no bookkeeping needed, the next leg does it by construction.

  Legacy flare_bands / param_patch / per-class flags are auto-named into
  kinds at load (models/scene._migrate_flare_kinds) — this engine executes
  kinds ONLY; post-validation scenes carry no live legacy fields.

Pulse releases are two-phase on purpose: the spike must LAND (at least one
render frame) before the release glide starts, or the tween engine would
retarget from the pre-spike value and the peak would never show. Production
schedules one flush_releases(hold_s) task per pending_hold_groups() entry,
each after its own CHOSEN HOLD (a momentary kind's hold_ms, default
PULSE_HOLD_S — models.scene.FlareKind); the executable specs call
flush_releases() directly (hold_s=None drains every group) for determinism.

Executable specs: scripts/check_spectra.py, tests/test_spectra_engine.py.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from random import Random
from typing import Any, Awaitable, Callable, Optional

from fx import device_model
from spectra.models.binding import ValueBinding
from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                  ResponseClass, SceneV2)
from spectra.models.sequencer import CurvePoint
from spectra.services import binding_resolver, color_journey, color_rotate
from spectra.services import selection_kernel as kernel
from spectra.services.binding_resolver import FireContext

logger = logging.getLogger(__name__)

PULSE_HOLD_S = 0.25      # the spike shows for a couple of frames, then releases
PULSE_RELEASE_S = 1.5    # glide back to baseline
GAIN_GLIDE_S = 0.8       # linear/ease_* land over this, then hold (carried)
SURGE_LOG_LIMIT = 50

# A dice re-roll's own eased landing (registry "smooth": true params only —
# see _reroll). Live-measured ordinary flare cadence during active music is
# roughly 0.6-1.2s apart (2026-08-17); this is short enough to still read
# as a flare accent and comfortably settles before the next re-roll, long
# enough to erase the visible snap. Not intensity-scaled like the colour
# jump's ramp — a dice roll carries no magnitude to key a ramp off of
# (stated above), so one fixed duration for every re-roll.
DICE_REROLL_GLIDE_MS = 220

# Flare colour-jump RAMP-IN (owner refinement of jump-not-blend, not its
# reversal): the ramp length scales INVERSELY with the fire's intensity —
# a gentle flare eases its new colours in noticeably, a full-scale flare
# still lands hard, close to the old immediate jump. Linear between the
# ends; the blend rides the tween engine's hue arc (never through grey),
# and the room journey resumes from the landed colour exactly as before.
COLOR_JUMP_RAMP_MS_GENTLE = 2500   # intensity 0.0 — the felt ease-in
COLOR_JUMP_RAMP_MS_HARD = 150      # intensity 1.0 — lands hard


def _intensity_scaled(intensity: float, at0: float, at1: float) -> float:
    """Shared linear-interpolation shape behind every intensity-scaled
    quantity in this module: at0 at intensity 0.0, at1 at intensity 1.0,
    clamped first so an out-of-range fire intensity never extrapolates past
    either named endpoint. A future change to the interpolation itself
    (easing, clamp behaviour) only needs to happen here, not once per
    family."""
    frac = max(0.0, min(1.0, intensity))
    return at0 + (at1 - at0) * frac


def _intensity_scaled_ramp_ms(intensity: float, gentle_ms: int, hard_ms: int) -> int:
    """Same shape as _intensity_scaled, rounded to whole milliseconds —
    every ramp-duration family in this module (colour jump, colour rotate's
    ramp/dwell/fade) shares this rounding."""
    return int(round(_intensity_scaled(intensity, gentle_ms, hard_ms)))


def color_jump_ramp_ms(intensity: float) -> int:
    return _intensity_scaled_ramp_ms(
        intensity, COLOR_JUMP_RAMP_MS_GENTLE, COLOR_JUMP_RAMP_MS_HARD)


# COLOUR ROTATE-AND-BACK FLARE (owner ask, 2026-08-20 — verbatim spec in
# scripts/add_color_rotate_flares.py's own docstring): rotate the live
# FOREGROUND colour's hue by an intensity-scaled amount, ramp in so the
# full rotation lands ON THE TRIGGER MARK (the flare anchor rule — see
# color_rotate_lead_ms/trigger_engine._response_switch_lead_ms), dwell,
# then fade back to the exact original over 1.5x the (already-scaled)
# ramp. All four numbers are his own, exact; they scale from the SAME
# effective intensity as one mechanism — no per-kind authored knobs
# (FlareKind.type="color_rotate" carries none, see its own docstring).
COLOR_ROTATE_DEG_GENTLE = 60.0       # intensity 0.0
COLOR_ROTATE_DEG_HARD = 180.0        # intensity 1.0
COLOR_ROTATE_RAMP_MS_GENTLE = 1000   # intensity 0.0 — ramp-IN duration
COLOR_ROTATE_RAMP_MS_HARD = 250      # intensity 1.0
COLOR_ROTATE_DWELL_MS_GENTLE = 1000  # intensity 0.0
COLOR_ROTATE_DWELL_MS_HARD = 400     # intensity 1.0
COLOR_ROTATE_FADE_FACTOR = 1.5       # fade-back = 1.5x the ramp, itself scaled


def color_rotate_degrees(intensity: float) -> float:
    return _intensity_scaled(intensity, COLOR_ROTATE_DEG_GENTLE, COLOR_ROTATE_DEG_HARD)


def color_rotate_ramp_ms(intensity: float) -> int:
    return _intensity_scaled_ramp_ms(
        intensity, COLOR_ROTATE_RAMP_MS_GENTLE, COLOR_ROTATE_RAMP_MS_HARD)


def color_rotate_dwell_ms(intensity: float) -> int:
    return _intensity_scaled_ramp_ms(
        intensity, COLOR_ROTATE_DWELL_MS_GENTLE, COLOR_ROTATE_DWELL_MS_HARD)


def color_rotate_fade_ms(intensity: float) -> int:
    return int(round(color_rotate_ramp_ms(intensity) * COLOR_ROTATE_FADE_FACTOR))


def color_rotate_lead_ms(scene: SceneV2, event_class: ResponseClass,
                         intensity: float, virtuals: dict) -> int:
    """Read-only peek for trigger_engine's lead-time alignment — the colour
    ROTATE-AND-BACK flare's own contribution, alongside
    momentary_switch_would_glide's fixed-duration one (see
    trigger_engine._response_switch_lead_ms, which takes the max of both).
    A separate function rather than folded into momentary_switch_would_glide
    because this kind's ramp-in has a real, INTENSITY-SCALED duration
    (color_rotate_ramp_ms), not that function's single fixed
    DICE_REROLL_GLIDE_MS — it can't share that function's boolean-then-
    constant shape. His own words apply the same rule momentary flares
    already use: 'It should reach the full rotation at the trigger point' —
    the ramp must finish ON the mark, so the fire itself must move earlier
    by exactly the ramp's own duration. 0 when no color_rotate kind is
    attached to the band at this intensity (true of every scene this build
    ships against — declared, never attached; see
    scripts/add_color_rotate_flares.py)."""
    spec = scene.responses.get(event_class)
    band = select_band(spec.bands, intensity) if spec else None
    if band is None:
        return 0
    declared = {k.name: k for k in scene.flare_kinds}
    lead = 0
    for name, scale in band.kinds.items():
        kind = declared.get(name)
        if kind is not None and kind.type == "color_rotate":
            sel_intensity = max(0.0, min(1.0, intensity * scale))
            lead = max(lead, color_rotate_ramp_ms(sel_intensity))
    return lead

# phase_progress ramp per class — the original program's tuned durations
# (config.py phase_*_ramp_ms defaults): "Drop stays short — it's the snap."
# This is now the UNKNOWN-GAP fallback for charge/lull (see _phase_ramp_ms
# below), not the universal default it used to be — it still IS the whole
# story for drop, which is never stretched.
PHASE_RAMP_MS = {"charge": 4000, "lull": 2500, "drop": 400}

# OVERRIDE BLEND — the dynamic half (owner order 2026-08-20, "fix the lull
# ramp"). Legacy (root services/trigger_engine.py's _phase_blend_ramp_ms/
# _blend_factor_for) stretched a charge/lull ramp to the gap to the next
# enabled trigger, so a build always peaked exactly as the next musical
# moment hit. SPECTRA's original port carried only a STATIC half of that
# grammar (models.scene.PhaseBlend, a per-scene optional number) — a
# PORTING GAP, not a deliberate simplification: at the time it was built,
# SPECTRA had no forward trigger schedule to compute a gap against, so the
# dynamic half was left for later. trigger_store now gives it exactly that
# schedule (TriggerEngine._next_trigger_gap_ms), so this closes the actual
# gap instead of leaving the placeholder. Measured on his own room (Dopamine
# repeat capture, 2026-08-20): one lull ran 6040ms, another 900ms, on the
# SAME song — PHASE_RAMP_MS["lull"]=2500 idled for 3.5s on the long one and
# got cut off at 36% on the short one. No single constant can satisfy both,
# so a per-scene static number was RETIRED rather than kept alongside the
# dynamic stretch — see PhaseBlend's own retirement note in
# spectra/models/scene.py for why a knob was deliberately not rebuilt here.
#
# His spec, verbatim: "the single blob waiting in lull should reach the
# center just and hang for just a moment, maybe 10% of the lull time,
# before the explosion" — ramp to ~90% of the real gap, then HANG at
# phase_progress=1.0 for the remaining ~10%. The hang is free: nothing
# writes phase_progress again until the next phase event fires, so a ramp
# that finishes early just sits at 1.0 until then.
PHASE_RAMP_HANG_FRACTION = 0.10
PHASE_RAMP_STRETCH_CLASSES = ("charge", "lull")   # drop is never stretched
# Floor on the stretched ramp itself (legacy used the same 200ms floor
# value on its own, differently-shaped gap-120 formula) — guards a gap so
# small that 90% of it would be a near-zero, visually-degenerate glide.
PHASE_RAMP_MIN_MS = 200


def _phase_ramp_ms(event_class: str, gap_ms: Optional[int]) -> int:
    """The class's phase ramp for one fire. gap_ms is the live distance
    (from TriggerEngine._next_trigger_gap_ms) to the next trigger this
    song will actually fire — None means the gap is UNKNOWABLE, not merely
    unset: either there's no next trigger for this song (this fire is the
    last one, or nothing is playing), or the event arrived with no SPECTRA
    trigger-schedule context at all (a bridge-classified legacy
    trigger_fired event, or a manual /api/engine/event test-fire — both
    call fire_response_event with no gap_ms, its documented default).
    Falling back to the flat, hand-tuned class default in that case is a
    DOCUMENTED degradation — the honest "nothing to stretch toward" answer
    — never a silent reintroduction of the constant this feature exists to
    replace for the common case.

    NOT the same "gap" minimum dwell reasons about (spectra/services/
    dwell.py, landed the same week) — that module's own docstring has the
    full comparison and the one real interaction between the two (a ramp
    that stretches toward a fire_scene trigger dwell then defers into an
    update effect instead of the switch the build promised); checked
    deliberately, not assumed, since both features touch trigger timing."""
    if (event_class in PHASE_RAMP_STRETCH_CLASSES
            and gap_ms is not None and gap_ms > 0):
        return max(PHASE_RAMP_MIN_MS,
                   round(gap_ms * (1.0 - PHASE_RAMP_HANG_FRACTION)))
    return PHASE_RAMP_MS[event_class]


def select_band(bands: list[FlareBand], intensity: float) -> Optional[FlareBand]:
    for band in bands:
        if band.intensity_min <= intensity < band.intensity_max:
            return band
        if intensity == band.intensity_max == 1.0:
            return band
    return None


def momentary_switch_would_glide(scene: SceneV2, event_class: ResponseClass,
                                 intensity: float, virtuals: dict) -> bool:
    """Read-only peek for trigger_engine's lead-time alignment (his ask: a
    momentary flare's FIRST SWITCH must FINISH on the trigger, then the
    hold, then the flip back after). True iff firing this response class at
    this intensity would land at least one MOMENTARY kind's param on a
    registry-smooth target — i.e. _move_params would put it in `glides` (a
    DICE_REROLL_GLIDE_MS ease) rather than `jumps` (instant, already
    finishes at fire time with no lead needed). Mirrors _move_params' own
    smooth gate exactly, without executing any write or rolling any dice.
    A momentary GAIN's spike is always an instant jump (see _gain) and
    never needs this — only param moves can glide."""
    spec = scene.responses.get(event_class)
    band = select_band(spec.bands, intensity) if spec else None
    if band is None:
        return False
    declared = {k.name: k for k in scene.flare_kinds}
    for name in band.kinds:
        kind = declared.get(name)
        if kind is None or kind.type != "momentary" or not kind.params:
            continue
        for pname in kind.params:
            for state in virtuals.values():
                meta = device_model.get_param_meta(state.effect_type, pname)
                mkind, _lo, _hi = binding_resolver.kind_for_meta(meta)
                if (mkind == binding_resolver.KIND_NUMERIC and meta is not None
                        and meta.get("smooth")):
                    return True
    return False


class ResponseEngine:
    def __init__(
        self, *,
        conductor,
        executor,
        rng: Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        broadcast: Callable[[dict], Awaitable[None]] | None = None,
        genre_bucket: Callable[[], Optional[str]] | None = None,
        sequencer_config: Callable[[], Any] | None = None,
        curve_profiles: Callable[[], dict] | None = None,
        eligible_sets: Callable[[SceneV2], dict[str, Optional[float]]] | None = None,
        set_card: Callable[[str], Any] | None = None,
        room_load: Callable[[], color_journey.RoomColorState] | None = None,
        room_save: Callable[[color_journey.RoomColorState], None] | None = None,
        room_controls: Callable[[], Any] | None = None,
    ) -> None:
        self.conductor = conductor
        self.executor = executor
        self._rng = rng or Random()
        self._clock = clock
        self._broadcast = broadcast or self._no_broadcast
        self._genre_bucket = genre_bucket or (lambda: None)
        self._sequencer_config = sequencer_config or self._default_sequencer_config
        self._curve_profiles = curve_profiles or self._default_curve_profiles
        self._eligible_sets = eligible_sets or self._default_eligible_sets
        self._set_card = set_card or self._default_set_card
        self._room_load = room_load or color_journey.load_room
        self._room_save = room_save or color_journey.save_room
        # Lazy on purpose (never a module-level `room_controls` import in
        # this file): `room_controls` above is a constructor PARAMETER, so
        # any reference to that name inside __init__ is this parameter, not
        # a module. `self._room_controls()` only imports the real module
        # the first time it's actually CALLED (_default_room_controls,
        # below) — same shape as DriftConductor's own `_room_controls`.
        # ResponseEngine is itself built at spectra/services/engine.py's
        # MODULE IMPORT TIME (`responses = ResponseEngine(...)`), which is
        # exactly the constraint that broke the reverted PR #142: it bound
        # `self._room_controls_load = room_controls_load or
        # room_controls.load_room_controls` — a real module attribute
        # access — inside __init__ itself, so the eager access ran at
        # import time. AGENTS.md's light-mode-fix-import-crash entry has
        # the full incident writeup.
        self._room_controls = room_controls or self._default_room_controls

        self.surges: deque[dict] = deque(maxlen=SURGE_LOG_LIMIT)
        # (virtual_id, param, hold_s) triples a momentary kind spiked,
        # awaiting the release glide back to the carried baseline — hold_s
        # is the CHOSEN HOLD (kind.hold_ms or the PULSE_HOLD_S default) so
        # different kinds in the same surge can hold their spike for
        # different lengths before releasing (pending_hold_groups groups
        # them for the engine to schedule one release task per hold).
        self._pending_releases: list[tuple[str, str, float]] = []
        # (virtual_id, original_gradient, dwell_s, fade_ms) — the colour
        # ROTATE-AND-BACK flare's OWN release queue, separate from
        # _pending_releases: its fade-back duration is itself
        # intensity-scaled per fire (color_rotate_fade_ms), where every
        # other momentary kind's release shares one fixed PULSE_RELEASE_S
        # — the two can't share flush_releases' hardcoded duration. See
        # _color_rotate's own docstring.
        self._pending_color_rotates: list[tuple[str, str, float, int]] = []
        self._phase_armed: Optional[str] = None  # "charge"|"lull" awaiting payoff

    # ── the event ────────────────────────────────────────────────────────────

    async def on_event(self, event_class: ResponseClass,
                       intensity: float, gap_ms: Optional[int] = None) -> dict:
        scene = self.conductor.scene
        record: dict[str, Any] = {
            "at": self._clock(), "class": event_class,
            "intensity": round(intensity, 4),
        }
        if scene is None:
            record["result"] = "no_active_scene"
            self.surges.append(record)
            return record
        phase_driven = False
        if event_class in PHASE_RAMP_MS:
            record["phase"] = await self._drive_phase(event_class, gap_ms)
            phase_driven = bool(record["phase"]["targets"])
        spec = scene.responses.get(event_class)
        band = select_band(spec.bands, intensity) if spec else None
        if spec is None or band is None:
            record["result"] = ("phase_only" if phase_driven
                                else "no_class" if spec is None
                                else "no_band")
            self.surges.append(record)
            if phase_driven:
                await self._broadcast({"type": "surge", **record})
            return record
        record["band"] = {"intensity_min": band.intensity_min,
                          "intensity_max": band.intensity_max}
        await self._execute_band(scene, band, intensity, record)
        self.surges.append(record)
        await self._broadcast({"type": "surge", **record})
        return record

    async def _execute_band(self, scene: SceneV2, band: FlareBand,
                            intensity: float, record: dict[str, Any]) -> None:
        """Run every kind attached to an already-selected band at `intensity`
        and fold the results into `record` — the shared tail of on_event
        (a genuine flare/charge/lull/drop) and on_update's placeholder
        double-intensity flare (below), factored out so the two can never
        drift into two different executions of "what a band does"."""
        declared = {k.name: k for k in scene.flare_kinds}
        attached = [(declared[n], s) for n, s in band.kinds.items()]
        # Fixed execution order (the legacy reroll → patch → gain → colour
        # pass, generalized): dice first so explicit param kinds override
        # same-key rolls; permanent params before momentary so a spike on
        # the same param returns to the just-carried point; gains read the
        # carried brightness; colour jump then colour rotate last so a
        # rotate (if ever attached alongside a jump) has the last word on
        # `gradient` — rotate never conflicts with any of the param/gain
        # kinds above it (gradient is never a device_model registry param,
        # so it never enters their shared jumps/glides dicts — see
        # _color_rotate's own docstring on shape/colour concurrency).
        dice = [(k, s) for k, s in attached
                if k.type == "drift_jump" and k.jump == "dice"]
        moves = sorted(((k, s) for k, s in attached if k.params),
                       key=lambda ks: ks[0].type != "permanent")
        gains = sorted(((k, s) for k, s in attached
                        if k.type in ("momentary", "permanent")
                        and k.gain != 1.0),
                       key=lambda ks: ks[0].type != "permanent")
        colours = [(k, s) for k, s in attached
                   if k.type == "drift_jump" and k.jump == "color_set"]
        rotates = [(k, s) for k, s in attached if k.type == "color_rotate"]

        carry: dict[tuple[str, str], Any] = {}
        jumps: dict[str, dict[str, Any]] = {}    # vid → params, instant
        glides: dict[str, dict[str, Any]] = {}   # vid → params, eased (registry smooth params — dice re-rolls and explicit patches alike)
        kind_records: list[dict] = []

        if dice:   # one fresh roll per fire, however many dice kinds attach
            kind, scale = dice[0]
            kind_records.append({
                "name": kind.name, "type": kind.type, "jump": "dice",
                "scale": scale,
                "rolled": self._reroll(scene, intensity, jumps, glides, carry)})
        for kind, scale in moves:
            kind_records.append({
                "name": kind.name, "type": kind.type, "scale": scale,
                "moved": self._move_params(kind, scale, jumps, glides, carry)})
        # An explicit param-patch kind (moves, above — the legacy
        # reroll→patch precedence) targeting the same param on the same
        # event must still win over a dice re-roll: since _move_params now
        # sorts into jumps/glides by the same smooth verdict dice used for
        # that param, the patch's dict.update() naturally overwrites dice's
        # value in whichever dict both land in (no cross-dict race is
        # possible — smooth is a static per-param registry lookup, so dice
        # and a patch on the same param always agree which dict it's in).
        # This cleanup is now a defensive no-op kept for exactly the case
        # that invariant breaks: any pname that landed in jumps can't also
        # be a live glide target.
        for vid, patched in jumps.items():
            for pname in patched:
                glides.get(vid, {}).pop(pname, None)
        for vid, params in glides.items():
            state = self.conductor.virtuals.get(vid)
            if state is not None and params:
                await self.executor.glide(
                    vid, state.effect_type, params, DICE_REROLL_GLIDE_MS)
        for vid, params in jumps.items():
            state = self.conductor.virtuals.get(vid)
            if state is not None:
                await self.executor.jump(vid, state.effect_type, params)

        for kind, scale in gains:
            kind_records.append({
                "name": kind.name, "type": kind.type, "scale": scale,
                "gain_envelope": await self._gain(kind, scale, carry)})

        if colours:   # one selector roll per fire — a jump is a jump
            kind, scale = colours[0]
            sel_intensity = max(0.0, min(1.0, intensity * scale))
            record["color_jump"] = await self._color_jump(
                scene, sel_intensity, carry)
            kind_records.append({
                "name": kind.name, "type": kind.type, "jump": "color_set",
                "scale": scale, **record["color_jump"]})

        if rotates:   # one rotation per fire — a spike is a spike
            kind, scale = rotates[0]
            sel_intensity = max(0.0, min(1.0, intensity * scale))
            record["color_rotate"] = await self._color_rotate(sel_intensity)
            kind_records.append({
                "name": kind.name, "type": kind.type,
                "scale": scale, **record["color_rotate"]})

        record["kinds"] = kind_records
        self.conductor.on_surge(carry)
        record["carried"] = [{"virtual_id": vid, "param": p}
                             for (vid, p) in carry]
        record["result"] = "applied"

    async def fire_kind(self, kind: FlareKind, intensity: float) -> dict:
        """Fire ONE declared kind in isolation, bypassing band selection
        entirely — the scrubbing flare-preview timeline's execution entry
        point (spectra/services/flare_preview.py, his ask: "bring up a
        timeline... so I can see it's evolution and help edit where the
        trigger should land with respect to the effect"). Mirrors on_event's
        own fixed dice -> moves -> gain -> colour order for exactly this one
        kind, at scale=1.0 — a kind previewed alone carries its own declared
        magnitude; there is no band in play to scale it. Momentary releases
        still go through the normal _pending_releases/pending_hold_groups/
        flush_releases path — the preview service drives those against its
        own fake clock so the recorded release write lands at its real
        hold_s offset instead of coinciding with the spike."""
        scene = self.conductor.scene
        record: dict[str, Any] = {
            "at": self._clock(), "kind": kind.name, "type": kind.type,
            "intensity": round(intensity, 4)}
        if scene is None:
            record["result"] = "no_active_scene"
            return record
        carry: dict[tuple[str, str], Any] = {}
        jumps: dict[str, dict[str, Any]] = {}
        glides: dict[str, dict[str, Any]] = {}
        if kind.type == "drift_jump" and kind.jump == "dice":
            record["rolled"] = self._reroll(scene, intensity, jumps, glides, carry)
        if kind.params:
            record["moved"] = self._move_params(kind, 1.0, jumps, glides, carry)
        for vid, patched in jumps.items():
            for pname in patched:
                glides.get(vid, {}).pop(pname, None)
        for vid, params in glides.items():
            state = self.conductor.virtuals.get(vid)
            if state is not None and params:
                await self.executor.glide(
                    vid, state.effect_type, params, DICE_REROLL_GLIDE_MS)
        for vid, params in jumps.items():
            state = self.conductor.virtuals.get(vid)
            if state is not None:
                await self.executor.jump(vid, state.effect_type, params)
        if kind.gain != 1.0:
            record["gain_envelope"] = await self._gain(kind, 1.0, carry)
        if kind.type == "drift_jump" and kind.jump == "color_set":
            record["color_jump"] = await self._color_jump(scene, intensity, carry)
        if kind.type == "color_rotate":
            record["color_rotate"] = await self._color_rotate(intensity)
        self.conductor.on_surge(carry)
        record["carried"] = [{"virtual_id": vid, "param": p} for (vid, p) in carry]
        record["result"] = "applied"
        return record

    # ── batched actions ──────────────────────────────────────────────────────

    def _reroll(self, scene: SceneV2, intensity: float,
                jumps: dict, glides: dict, carry: dict) -> list[dict]:
        """Fresh dice: every signal="random" binding re-resolves in one new
        FireContext (correlated letters stay correlated — one roll per
        letter) and the changed params land on the entry's winning
        virtuals. Stepped-effect entries re-roll the variant the FIRE
        selected (keyed by the entry's live effect) — a surge re-rolls
        dice, it never re-selects the effect. STICKY bindings (ValueBinding.
        sticky, e.g. STAR's edges — decision: OQ-6, docs/SPECTRA_SPEC.md
        §54) are skipped here on purpose: they still roll fresh at fire time
        (resolve_scene doesn't check this flag), the initial pick just holds
        for the rest of that scene's run instead of moving on every flare.

        A landed value goes to `glides` (eased, see DICE_REROLL_GLIDE_MS)
        when the registry marks the param genuinely smooth — a continuous
        numeric, never a toggle/string/integer that can't be meaningfully
        interpolated (fx/device_model's `config/effect_params.json`
        already carries this per param, e.g. star: smooth=true,
        edges: smooth=false — it just went unread by any jump/glide
        choice until now). An unregistered param (meta is None) has no
        smooth verdict and stays in `jumps`, the previously-unconditional
        behaviour. brightness/background_brightness are always genuine
        floats and always glide, matching how every other brightness
        write in this module already lands (_gain, colour jump, release)."""
        ctx = FireContext(intensity, rng=self._rng)
        entry_vids: dict[str, list[str]] = {}
        for vid, state in self.conductor.virtuals.items():
            entry_vids.setdefault(state.entry_id, []).append(vid)
        rolled: list[dict] = []
        for dev in scene.devices:
            vids = entry_vids.get(dev.id, [])
            if not vids:
                continue
            live_effect = self.conductor.virtuals[vids[0]].effect_type
            targets: dict[str, Any] = {}
            eased: dict[str, Any] = {}
            for pname, value in dev.params_for_effect(live_effect).items():
                if (isinstance(value, ValueBinding) and value.signal == "random"
                        and not value.sticky):
                    meta = device_model.get_param_meta(live_effect, pname)
                    kind, lo, hi = binding_resolver.kind_for_meta(meta)
                    out = binding_resolver.apply_binding(value, ctx, kind, lo, hi)
                    if out is None:
                        continue
                    if (kind == binding_resolver.KIND_NUMERIC
                            and meta is not None and meta.get("smooth")):
                        eased[pname] = out
                    else:
                        targets[pname] = out
            for field in ("brightness", "background_brightness"):
                value = getattr(dev, field)
                if (isinstance(value, ValueBinding) and value.signal == "random"
                        and not value.sticky):
                    out = binding_resolver.apply_binding(
                        value, ctx, binding_resolver.KIND_NUMERIC, 0.0, 1.0)
                    if out is not None:
                        eased[field] = out
            for vid in vids:
                jumps.setdefault(vid, {}).update(targets)
                glides.setdefault(vid, {}).update(eased)
                for pname, out in {**targets, **eased}.items():
                    carry[(vid, pname)] = out
            rolled.extend({"param": p, "value": v, "eased": False}
                          for p, v in targets.items())
            rolled.extend({"param": p, "value": v, "eased": True}
                          for p, v in eased.items())
        return rolled

    def _carried_value(self, vid: str, state, pname: str,
                       carry: dict) -> Optional[float | bool]:
        """The baseline a scale excursion measures from and a momentary
        move returns to: same-surge carry first, then brightness's own
        baseline, a creep's current wander position, or the tracked param
        baseline. None = unknown (scale falls back to the declared value).
        A toggle param's baseline is a bool, returned as-is (not coerced to
        float) — a creep never drives a toggle, so only the carry/tracked-
        baseline branches can ever produce one."""
        if (vid, pname) in carry:
            v = carry[(vid, pname)]
            if isinstance(v, bool):
                return v
            return float(v) if isinstance(v, (int, float)) else None
        if pname == "brightness":
            return float(state.brightness_baseline)
        for mech in self.conductor.mechanisms:
            if mech.vid == vid and mech.param == pname \
                    and mech.kind == "creep":
                return float(mech.position)
        v = state.param_baseline.get(pname)
        if isinstance(v, bool):
            return v
        return float(v) if isinstance(v, (int, float)) else None

    def _resolve_target(self, target: ParamTarget, base: Optional[float],
                        rolled: dict[str, float], pname: str) -> Optional[float]:
        """The DECLARED target a ParamTarget expression resolves to, before
        the band's scale steers it — the same declared/base split the scale
        formula below has always used, generalized past a bare absolute
        float. offset needs a known baseline (a creep's current wander
        position or the tracked param baseline) — unresolvable skips the
        param, same as an unknown registry param (a name-broadcast kind
        never moves blind)."""
        if target.mode == "absolute":
            return target.value
        if target.mode == "offset":
            return None if base is None else base + target.offset
        return rolled[pname]   # random — pre-rolled once, broadcast to all

    def _compute_param_moves(self, kind: FlareKind, scale: float,
                             carry: dict) -> dict[str, dict[str, float]]:
        """Per-virtual param moves for one kind at this scale — the pure
        declared/scale/clamp computation. Split out of _move_params so any
        future caller needing this same math (carry/hold bookkeeping
        included) doesn't have to re-derive it. Name-broadcast
        targeting: each key lands on every virtual whose live effect has
        that param (registry truth). Each param's ParamTarget resolves to a
        declared target (absolute value / baseline + offset / a fresh
        random draw — random rolls ONCE per kind execution, broadcast like
        an absolute value); scale ×1 then lands it VERBATIM (legacy
        parity), any other scale moves it to baseline + (declared −
        baseline)·scale, clamped to the param's registry range. PERMANENT
        enters the carry; MOMENTARY schedules the return at its CHOSEN HOLD
        (kind.hold_ms, default PULSE_HOLD_S) instead.

        A TOGGLE-type param (registry KIND_TOGGLE — e.g. `reverse`) can
        never be meaningfully scaled or offset (ParamTarget.value is a
        float, so an authored True/False arrives here as 1.0/0.0): its
        declared target is landed as a real Python bool at scale 1, or a
        0.5-threshold blend of the (bool) baseline and declared target at
        any other scale — never a bare float, which the effect's own
        CONFIG_SCHEMA (`bool` exactly, no coercion) would silently reject
        (fx/effects/__init__.py::_apply_config, validate=True logs and
        drops the whole write rather than raising)."""
        rolled = {pname: self._rng.uniform(target.lo, target.hi)
                  for pname, target in kind.params.items()
                  if target.mode == "random"}
        hold_s = (kind.hold_ms / 1000.0 if kind.hold_ms is not None
                  else PULSE_HOLD_S)
        out: dict[str, dict[str, float]] = {}
        for vid, state in self.conductor.virtuals.items():
            moves: dict[str, float] = {}
            for pname, target in kind.params.items():
                meta = device_model.get_param_meta(state.effect_type, pname)
                if meta is None:
                    continue
                mkind, lo, hi = binding_resolver.kind_for_meta(meta)
                base = None
                if target.mode == "offset" or scale != 1.0 \
                        or mkind == binding_resolver.KIND_TOGGLE:
                    base = self._carried_value(vid, state, pname, carry)
                declared = self._resolve_target(target, base, rolled, pname)
                if declared is None:
                    continue
                if mkind == binding_resolver.KIND_TOGGLE:
                    if scale != 1.0 and base is not None:
                        value = (float(base) + (declared - float(base)) * scale) >= 0.5
                    else:
                        value = bool(declared)
                else:
                    value = declared
                    if scale != 1.0:
                        b = base if base is not None else declared
                        value = b + (declared - b) * scale
                        if mkind == binding_resolver.KIND_NUMERIC:
                            if lo is not None:
                                value = max(float(lo), value)
                            if hi is not None:
                                value = min(float(hi), value)
                moves[pname] = value
                if kind.type == "permanent":
                    carry[(vid, pname)] = value
                else:
                    self._pending_releases.append((vid, pname, hold_s))
            if moves:
                out[vid] = moves
        return out

    def _move_params(self, kind: FlareKind, scale: float,
                     jumps: dict, glides: dict, carry: dict) -> list[dict]:
        """The band-driven path (on_event): collects this kind's moves into
        the shared `jumps`/`glides` dicts, split by the SAME registry
        smooth gate _reroll already applies to dice re-rolls (fixed
        2026-08-17: an explicit param-patch kind targeting a registry-smooth
        param — e.g. STAR's "Flare patch 0.7–1" setting `star` to 0.0 — was
        landing an instant jump unconditionally; the smooth gate only ever
        covered dice re-rolls, not this path, so `star` kept snapping on
        every flare in that band even after the dice-reroll fix, exactly as
        scripts/check_spectra.py's own "unchanged by the smoothing fix"
        assertion documented). A non-smooth target on the same kind (e.g.
        the same patch's `spin`) still jumps — the split is per-param, not
        per-kind. Because a param's smooth verdict is a static registry
        lookup, dice and a patch targeting the SAME param always agree on
        which dict it lands in — precedence (patch overrides dice) falls
        out of plain dict.update() ordering (moves execute after dice),
        with no risk of a value landing in both."""
        landed: list[dict] = []
        for vid, moves in self._compute_param_moves(kind, scale, carry).items():
            state = self.conductor.virtuals.get(vid)
            instant: dict[str, Any] = {}
            eased: dict[str, Any] = {}
            for pname, value in moves.items():
                meta = (device_model.get_param_meta(state.effect_type, pname)
                        if state is not None else None)
                mkind, _lo, _hi = binding_resolver.kind_for_meta(meta)
                if mkind == binding_resolver.KIND_NUMERIC and meta is not None \
                        and meta.get("smooth"):
                    eased[pname] = value
                else:
                    instant[pname] = value
            if instant:
                jumps.setdefault(vid, {}).update(instant)
            if eased:
                glides.setdefault(vid, {}).update(eased)
            landed.append({"virtual_id": vid, "params": moves})
        return landed

    async def _color_rotate(self, intensity: float) -> dict:
        """The COLOUR ROTATE-AND-BACK flare (owner ask, 2026-08-20, his
        verbatim spec in scripts/add_color_rotate_flares.py): rotate every
        set-mode virtual's live FOREGROUND colour (state.gradient — his own
        word; the background is a deliberately different target, untouched
        here, unlike the colour journey's own rotation in drift_conductor.py
        which moves both together) by an intensity-scaled number of
        degrees, RAMPING IN so the full rotation lands ON THE TRIGGER MARK
        (the flare anchor rule, not the drop rule — see
        color_rotate_lead_ms/trigger_engine._response_switch_lead_ms),
        DWELLING at the rotated colour, then FADING BACK to the exact
        original value over 1.5x the ramp. All four quantities (degrees,
        ramp-in, dwell, fade-back) scale together from this one effective
        intensity — one mechanism, no fifth knob, matching his own
        instruction.

        MOMENTARY, never carried: unlike the flare colour JUMP (which picks
        a fresh set and moves the room's story forward), a rotation is a
        spike-and-return around the CURRENT colour — state.gradient itself
        is left untouched at spike time (mirrors _compute_param_moves'
        momentary branch, which never writes into `carry`/param_baseline
        either), so a concurrent read of "the room's current colour" during
        the dwell still sees the pre-rotation truth. The fade-back glide
        therefore targets its own CAPTURED original, not a live baseline
        lookup — gradient isn't a device_model registry param, so
        _carried_value's generic machinery doesn't apply to it.

        Releases through its OWN queue (_pending_color_rotates /
        pending_color_rotate_holds / flush_color_rotates), never
        _pending_releases/flush_releases: this kind's fade-back duration is
        itself intensity-scaled per fire, where every existing momentary
        kind's release shares one fixed PULSE_RELEASE_S — the two can't
        share one queue without one of them losing its own duration.

        COLOUR/SHAPE CONCURRENCY (his requirement, not a preference —
        "should concur with some shape flares"): this method only ever
        writes `gradient` via its own direct executor.glide call, entirely
        outside the jumps/glides dicts _move_params/_reroll build from the
        device_model PARAM REGISTRY (gradient is a scene colour assignment,
        never a registered per-effect param) — so a shape-targeting
        momentary/permanent kind attached to the SAME band still executes
        its own jump/glide calls independently, in the same on_event pass,
        never gated on or overwritten by this one. Proven, not assumed:
        tests/test_color_rotate.py's concurrency proof fires a band
        carrying both a color_rotate kind and a shape param-move kind and
        asserts both land as separate executor writes.

        A virtual with no live gradient (achromatic/rainbow, or not
        currently set-mode) has nothing to rotate and is silently skipped,
        matching every other colour write's "nothing to move" convention in
        this module. A rotation that lands back on its own starting colour
        (delta a multiple of 360°, or an unparseable/None value
        color_rotate.rotate_color_value passes through unchanged) is also
        skipped — nothing visible would happen and nothing should be
        queued for release."""
        degrees = color_rotate_degrees(intensity)
        ramp_ms = color_rotate_ramp_ms(intensity)
        dwell_ms = color_rotate_dwell_ms(intensity)
        fade_ms = color_rotate_fade_ms(intensity)
        dwell_s = dwell_ms / 1000.0
        rotated_count = 0
        for vid, state in self.conductor.virtuals.items():
            if not state.set_mode or not state.gradient:
                continue
            original = state.gradient
            rotated = color_rotate.rotate_color_value(original, degrees)
            if rotated == original:
                continue
            await self.executor.glide(vid, state.effect_type,
                                      {"gradient": rotated}, ramp_ms)
            self._pending_color_rotates.append((vid, original, dwell_s, fade_ms))
            rotated_count += 1
        return {"degrees": round(degrees, 2), "ramp_ms": ramp_ms,
                "dwell_ms": dwell_ms, "fade_ms": fade_ms,
                "virtuals": rotated_count}

    def pending_color_rotate_holds(self) -> list[float]:
        """Distinct DWELLS still pending for the colour rotate-and-back
        flare — mirrors pending_hold_groups()'s shape for this kind's own,
        separately-timed release queue (see _color_rotate's own docstring
        for why the two can't share one)."""
        return sorted({dwell_s for _, _, dwell_s, _ in self._pending_color_rotates})

    async def flush_color_rotates(self, dwell_s: Optional[float] = None) -> int:
        """Fade every pending colour rotation back to its captured ORIGINAL
        value, over ITS OWN intensity-scaled fade_ms (captured at spike
        time — recomputing it now would need the original fire's
        intensity, which this queue doesn't otherwise carry). dwell_s=None
        drains every pending rotation regardless of its own dwell (test/
        preview convenience, mirrors flush_releases); a specific dwell_s
        drains only that dwell's group, leaving other dwells' entries
        pending for their own release."""
        if dwell_s is None:
            pending, self._pending_color_rotates = self._pending_color_rotates, []
        else:
            due, keep = [], []
            for entry in self._pending_color_rotates:
                (due if entry[2] == dwell_s else keep).append(entry)
            pending, self._pending_color_rotates = due, keep
        count = 0
        for vid, original, _dwell_s, fade_ms in pending:
            state = self.conductor.virtuals.get(vid)
            if state is None:
                continue
            await self.executor.glide(vid, state.effect_type,
                                      {"gradient": original}, fade_ms)
            count += 1
        return count

    async def _gain(self, kind: FlareKind, scale: float,
                    carry: dict) -> list[dict]:
        """One kind's brightness envelope around the carried baseline, at
        effective gain 1 + (gain − 1)·scale — neutral stays neutral, a duck
        scales into a deeper duck. MOMENTARY: spike to baseline×effective,
        release back (the baseline stays). PERMANENT: glide to
        baseline×effective and hold over the default GAIN_GLIDE_S — CARRIED."""
        effective = 1.0 + (kind.gain - 1.0) * scale
        hold_s = (kind.hold_ms / 1000.0 if kind.hold_ms is not None
                  else PULSE_HOLD_S)
        out: list[dict] = []
        for vid, state in self.conductor.virtuals.items():
            baseline = carry.get((vid, "brightness"),
                                 state.brightness_baseline)
            peak = max(0.0, min(1.0, float(baseline) * effective))
            if kind.type == "momentary":
                await self.executor.jump(vid, state.effect_type,
                                         {"brightness": peak})
                self._pending_releases.append((vid, "brightness", hold_s))
                out.append({"virtual_id": vid, "peak": round(peak, 4),
                            "returns_to": round(float(baseline), 4)})
            else:
                await self.executor.glide(vid, state.effect_type,
                                          {"brightness": peak},
                                          int(GAIN_GLIDE_S * 1000))
                carry[(vid, "brightness")] = peak
                out.append({"virtual_id": vid, "lands": round(peak, 4),
                            "held": True})
        return out

    # ── UPDATE (placeholder, 2026-08-20 — see on_update's own docstring) ──

    async def on_update(self, intensity: float) -> dict:
        """PLACEHOLDER (his words: "make update scene act like a double
        intensity flare until we build it out specifically"). This is a
        full replacement of the original UPDATE design (data/spectra-
        trigger-migration-scoping/RULING.md), not an extension of it: that
        design fired the active scene's OWN designated kind
        (SceneV2.update_kind) directly, bypassing intensity-band selection,
        restricted to a single type="permanent" kind — but 8 of his 9 real
        scenes have no update_kind authored, so the minimum-dwell rebuild's
        own deferral (engine.fire_scene_update_event) was landing on
        nothing for almost every hold. Confirmed reading, approved as-is:
        fire the active scene's own ordinary "flare" ResponseClass — the
        SAME band-selection + kind-execution on_event runs for a genuine
        flare (_execute_band, shared with on_event above) — at 2x
        `intensity`, clamped to 1.0 (his own accepted ceiling: "double" and
        "full" read identical from intensity 0.5 up; a deliberately
        accepted consequence, not a gap to fill with a second gain or a
        rescale). No permanent-only restriction and nothing new to author —
        whatever kinds the doubled intensity's own band already has
        attached fire exactly as a real flare would, on every scene he
        already has; a scene with no "flare" response/bands declared at
        all still holds silently, same "nothing declared → nothing
        happens" convention on_event's own "no band" already follows.
        SceneV2.update_kind is untouched by this and simply unread by this
        path now — a future, deliberately-designed update effect is its
        own build, not this placeholder; don't repurpose update_kind for
        it without a fresh ask."""
        scene = self.conductor.scene
        doubled = min(1.0, intensity * 2.0)
        record: dict[str, Any] = {"at": self._clock(), "class": "update",
                                  "intensity": round(intensity, 4),
                                  "doubled_intensity": round(doubled, 4)}
        if scene is None:
            record["result"] = "no_active_scene"
            self.surges.append(record)
            return record
        spec = scene.responses.get("flare")
        band = select_band(spec.bands, doubled) if spec else None
        if spec is None or band is None:
            record["result"] = "no_class" if spec is None else "no_band"
            self.surges.append(record)
            return record
        record["band"] = {"intensity_min": band.intensity_min,
                          "intensity_max": band.intensity_max}
        await self._execute_band(scene, band, doubled, record)
        self.surges.append(record)
        await self._broadcast({"type": "surge", **record})
        return record

    def pending_hold_groups(self) -> list[float]:
        """Distinct CHOSEN HOLDS still pending — the engine spawns one
        release task per group (asyncio.sleep(hold_s) then
        flush_releases(hold_s)) so kinds authored with different hold_ms
        in the same surge each release on their own schedule. A surge with
        every kind at the PULSE_HOLD_S default returns exactly one group —
        today's unchanged single-task shape."""
        return sorted({hold_s for _, _, hold_s in self._pending_releases})

    async def flush_releases(self, hold_s: Optional[float] = None) -> int:
        """Issue pending momentary releases — every spiked (virtual, param)
        glides back to its baseline AS CARRIED NOW (a colour jump or
        permanent kind in the same surge may have moved it; a creep kept
        wandering — the release honors the carry, never a stale snapshot).
        hold_s=None drains EVERY pending release regardless of its authored
        hold (test/preview convenience and a final drain point — the /api/
        engine/event dark injector uses this to settle immediately); a
        specific hold_s (production: engine._release_after_hold, one task
        per pending_hold_groups() entry) drains only that hold's group,
        leaving other holds' entries pending for their own release.
        Production schedules the default group PULSE_HOLD_S after the
        spike (services/engine.py); specs call it directly once the spike
        has provably landed. Returns virtuals released."""
        if hold_s is None:
            pending, self._pending_releases = self._pending_releases, []
        else:
            due, keep = [], []
            for entry in self._pending_releases:
                (due if entry[2] == hold_s else keep).append(entry)
            pending, self._pending_releases = due, keep
        by_vid: dict[str, dict[str, float]] = {}
        for vid, pname, _hold_s in dict.fromkeys(pending):
            state = self.conductor.virtuals.get(vid)
            if state is None:
                continue
            target = self._carried_value(vid, state, pname, {})
            if target is None:
                continue
            by_vid.setdefault(vid, {})[pname] = target
        for vid, params in by_vid.items():
            state = self.conductor.virtuals[vid]
            await self.executor.glide(vid, state.effect_type, params,
                                      int(PULSE_RELEASE_S * 1000))
        return len(by_vid)

    async def _drive_phase(self, event_class: str,
                           gap_ms: Optional[int] = None) -> dict:
        """Arm + ramp the vendored phase machinery on every phase-capable
        virtual — the exact drive the original program used: the instant
        arm write must land before the ramp (jump, then glide — in-process
        the calls are ordered by construction; the legacy path needed an
        explicit bus drain). The choreography itself — blackhole's swallow,
        orbits' collapse, fireworks' rockets, the eye's lids — is the
        effects' own vendored code, not re-invented here.

        OVERRIDE BLEND equivalent (see _phase_ramp_ms/PHASE_RAMP_MS above):
        charge/lull ramps stretch to ~90% of the real gap_ms when it's
        known, hanging the remaining ~10% at phase_progress=1.0; drop is
        never stretched, it stays the fixed snap."""
        ramp_ms = _phase_ramp_ms(event_class, gap_ms)
        targets: list[str] = []
        for vid, state in self.conductor.virtuals.items():
            if state.effect_type not in device_model.PHASE_EFFECTS:
                continue
            await self.executor.jump(
                vid, state.effect_type,
                {"phase": event_class, "phase_progress": 0.0})
            await self.executor.glide(
                vid, state.effect_type, {"phase_progress": 1.0}, ramp_ms)
            targets.append(vid)
        if targets:
            self._phase_armed = (event_class
                                 if event_class in ("charge", "lull")
                                 else None)
        return {"targets": targets, "ramp_ms": ramp_ms, "gap_ms": gap_ms}

    async def release_phases(self) -> int:
        """The lifecycle guard carried from the original program
        (trigger_engine cleared _phase_armed on track change): a charge or
        lull armed mid-song must not linger into the next track — release
        every phase-capable virtual with an instant phase "none" write.
        The effects would eventually free themselves anyway (the shared
        orphan watchdog: 12 s grace / 60 s cap) — this is the deliberate
        release, not the safety net."""
        if self._phase_armed is None:
            return 0
        self._phase_armed = None
        count = 0
        for vid, state in self.conductor.virtuals.items():
            if state.effect_type not in device_model.PHASE_EFFECTS:
                continue
            await self.executor.jump(
                vid, state.effect_type,
                {"phase": "none", "phase_progress": 0.0})
            count += 1
        return count

    async def _color_jump(self, scene: SceneV2, intensity: float,
                          carry: dict) -> dict:
        """The flare colour jump: the shipped selector picks (curve × genre
        × wheel-travel, terminal KEEP), the pick lands on set-mode virtuals
        with the intensity-scaled RAMP-IN (color_jump_ramp_ms — a hue-arc
        glide, gentle flares ease in, big flares land hard), a chromatic
        pick moves the room's wheel AT SELECTION — and the journey resumes
        from the new point on the conductor's next leg. The carry records
        the landed targets, so releases and palette rotation measure from
        where the ramp finishes, never a mid-blend snapshot."""
        config = self._sequencer_config()
        if not config.color_set_entries:
            return {"result": "selector_unconfigured"}
        room = self._room_load()
        eligible = self._eligible_sets(scene)
        curves = self._curve_profiles()
        wheel_profile = (curves.get(config.wheel_travel_curve)
                         if config.wheel_travel_curve else None)
        candidates = kernel.build_color_set_candidates(
            config.color_set_entries, curves,
            genre_bucket=self._genre_bucket(),
            room_deg=room.wheel_position_deg,
            set_positions=eligible,
            wheel_points=(wheel_profile.points if wheel_profile
                          else [CurvePoint(x=0.0, y=1.0)]))
        pick = kernel.select_color_set(candidates, intensity=intensity,
                                       rng=self._rng,
                                       current_id=room.active_set_id)
        if pick.picked_id is None:
            return {"result": "kept_current", "rung": pick.rung}
        card = self._set_card(pick.picked_id)
        if card is None:
            return {"result": "missing_set", "picked_id": pick.picked_id}
        from spectra.services import scene_compiler
        from spectra.services.room_controls import resolve_authored_bg_color
        by_vid = scene_compiler._set_entry_by_virtual(card)
        controls = self._room_controls()
        ramp_ms = color_jump_ramp_ms(intensity)
        landed = 0
        for vid, state in self.conductor.virtuals.items():
            if not state.set_mode:
                continue
            entry = by_vid.get(vid)
            if entry is None:
                continue
            params: dict[str, Any] = {}
            if entry.color_value:
                params["gradient"] = entry.color_value
                carry[(vid, "gradient")] = entry.color_value
            if entry.bg_color and not device_model.bg_color_blocked(
                    state.effect_type):
                bg_color = resolve_authored_bg_color(
                    entry.bg_color, controls.display_mode,
                    controls.display_light_bg_color)
                params["background_color"] = bg_color
                carry[(vid, "background_color")] = bg_color
            if entry.bg_mode:
                params["background_mode"] = entry.bg_mode
            if entry.brightness is not None:
                params["brightness"] = entry.brightness
                carry[(vid, "brightness")] = entry.brightness
            if entry.background_brightness is not None:
                params["background_brightness"] = entry.background_brightness
            if params:
                await self.executor.glide(vid, state.effect_type, params,
                                          ramp_ms)
                landed += 1
        position = eligible.get(pick.picked_id)
        update: dict[str, Any] = {"active_set_id": pick.picked_id}
        if position is not None:   # rainbow/achromatic never move the wheel
            update["wheel_position_deg"] = position
            # A teleport invalidates the journey's bearing — the conductor
            # reselects a destination from the new point next leg.
            update["destination"] = None
        self._room_save(room.model_copy(update=update))
        return {"result": "jumped", "picked_id": pick.picked_id,
                "rung": pick.rung, "virtuals": landed,
                "ramp_ms": ramp_ms, "wheel_position_deg": position}

    # ── production defaults (lazy imports; specs inject fakes) ───────────────

    @staticmethod
    def _default_sequencer_config():
        from spectra.services import sequencer_store
        return sequencer_store.load_config()

    @staticmethod
    def _default_curve_profiles() -> dict:
        from spectra.services import sequencer_store
        return sequencer_store.load_curves()

    @staticmethod
    def _default_eligible_sets(scene: SceneV2) -> dict[str, Optional[float]]:
        from spectra.services import color_sets, color_wheel
        out: dict[str, Optional[float]] = {}
        for card in color_sets.list_all():
            if card.kind != "set" or not scene.accepts_color_set(card):
                continue
            out[card.id] = color_wheel.wheel_position(card).position_deg
        return out

    @staticmethod
    def _default_room_controls():
        from spectra.services.room_controls import load_room_controls
        return load_room_controls()

    @staticmethod
    def _default_set_card(set_id: str):
        """Found missing 2026-08-19 (same audit as scene_compiler.
        room_active_set): the flare colour jump picked from
        _default_eligible_sets (kind="set" only, never a group id) and
        rendered the RAW card — no enclosing group's override entries.
        resolve_for_fire's set-branch chains them, matching every other
        rendering choke point."""
        from spectra.services import color_set_groups, color_sets
        card = color_sets.get_by_id(set_id)
        if card is None:
            return None
        return color_set_groups.resolve_for_fire(card)

    @staticmethod
    async def _no_broadcast(payload: dict) -> None:
        pass
