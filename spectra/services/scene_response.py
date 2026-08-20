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
from spectra.services import binding_resolver, color_journey
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

# UPDATE's own ramp-in (the owner's words, spectra-trigger-migration-scoping
# RULING.md: "a major change ... bigger than the flare ... arriving on a
# ramp-in transition"). Same intensity-scaled shape as the colour jump's
# (gentle eases in, hard lands quicker) but deliberately slower at both
# ends — "bigger than a flare" should never glide faster than the flare
# colour-jump's own hard end.
UPDATE_RAMP_MS_GENTLE = 3000   # intensity 0.0
UPDATE_RAMP_MS_HARD = 800      # intensity 1.0 — still a visible glide, never a snap


def _intensity_scaled_ramp_ms(intensity: float, gentle_ms: int, hard_ms: int) -> int:
    """Shared shape behind every intensity-scaled ramp-in in this module:
    linear between GENTLE (intensity 0.0) and HARD (intensity 1.0), clamped.
    A future change to the interpolation itself (easing, clamp behaviour)
    only needs to happen here, not once per ramp family."""
    frac = max(0.0, min(1.0, intensity))
    return int(round(gentle_ms + (hard_ms - gentle_ms) * frac))


def color_jump_ramp_ms(intensity: float) -> int:
    return _intensity_scaled_ramp_ms(
        intensity, COLOR_JUMP_RAMP_MS_GENTLE, COLOR_JUMP_RAMP_MS_HARD)


def update_ramp_ms(intensity: float) -> int:
    return _intensity_scaled_ramp_ms(
        intensity, UPDATE_RAMP_MS_GENTLE, UPDATE_RAMP_MS_HARD)

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
    replace for the common case."""
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

        declared = {k.name: k for k in scene.flare_kinds}
        attached = [(declared[n], s) for n, s in band.kinds.items()]
        # Fixed execution order (the legacy reroll → patch → gain → colour
        # pass, generalized): dice first so explicit param kinds override
        # same-key rolls; permanent params before momentary so a spike on
        # the same param returns to the just-carried point; gains read the
        # carried brightness; colour last so its landed brightness is the
        # release target, never an enveloped one.
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

        record["kinds"] = kind_records
        self.conductor.on_surge(carry)
        record["carried"] = [{"virtual_id": vid, "param": p}
                             for (vid, p) in carry]
        record["result"] = "applied"
        self.surges.append(record)
        await self._broadcast({"type": "surge", **record})
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
                       carry: dict) -> Optional[float]:
        """The baseline a scale excursion measures from and a momentary
        move returns to: same-surge carry first, then brightness's own
        baseline, a creep's current wander position, or the tracked param
        baseline. None = unknown (scale falls back to the declared value)."""
        if (vid, pname) in carry:
            v = carry[(vid, pname)]
            return float(v) if isinstance(v, (int, float)) \
                and not isinstance(v, bool) else None
        if pname == "brightness":
            return float(state.brightness_baseline)
        for mech in self.conductor.mechanisms:
            if mech.vid == vid and mech.param == pname \
                    and mech.kind == "creep":
                return float(mech.position)
        v = state.param_baseline.get(pname)
        return float(v) if isinstance(v, (int, float)) \
            and not isinstance(v, bool) else None

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
        declared/scale/clamp computation. Split out of _move_params so
        on_update's ramped path (_move_params_ramped) shares the EXACT same
        math and carry/hold bookkeeping; the two differ only in how the
        result reaches the executor (an instant jump collected across
        several kinds vs. this one kind's own ramp). Name-broadcast
        targeting: each key lands on every virtual whose live effect has
        that param (registry truth). Each param's ParamTarget resolves to a
        declared target (absolute value / baseline + offset / a fresh
        random draw — random rolls ONCE per kind execution, broadcast like
        an absolute value); scale ×1 then lands it VERBATIM (legacy
        parity), any other scale moves it to baseline + (declared −
        baseline)·scale, clamped to the param's registry range. PERMANENT
        enters the carry; MOMENTARY schedules the return at its CHOSEN HOLD
        (kind.hold_ms, default PULSE_HOLD_S) instead."""
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
                base = None
                if target.mode == "offset" or scale != 1.0:
                    base = self._carried_value(vid, state, pname, carry)
                declared = self._resolve_target(target, base, rolled, pname)
                if declared is None:
                    continue
                value = declared
                if scale != 1.0:
                    b = base if base is not None else declared
                    value = b + (declared - b) * scale
                    mkind, lo, hi = binding_resolver.kind_for_meta(meta)
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

    async def _move_params_ramped(self, kind: FlareKind, scale: float,
                                  carry: dict, ramp_ms: int) -> list[dict]:
        """on_update's own param-move path: same declared/scale/clamp math
        as _move_params, but glides each virtual to its landed value over
        ramp_ms instead of an instant jump — the "ramp in transition" his
        definition calls for. Only ever called with a permanent kind (see
        on_update), so always carries via _compute_param_moves, never
        schedules a release."""
        landed: list[dict] = []
        for vid, moves in self._compute_param_moves(kind, scale, carry).items():
            state = self.conductor.virtuals.get(vid)
            if state is None:
                continue
            await self.executor.glide(vid, state.effect_type, moves, ramp_ms)
            landed.append({"virtual_id": vid, "params": moves})
        return landed

    async def _gain(self, kind: FlareKind, scale: float, carry: dict,
                    *, ramp_ms: Optional[int] = None) -> list[dict]:
        """One kind's brightness envelope around the carried baseline, at
        effective gain 1 + (gain − 1)·scale — neutral stays neutral, a duck
        scales into a deeper duck. MOMENTARY: spike to baseline×effective,
        release back (the baseline stays). PERMANENT: glide to
        baseline×effective and hold — CARRIED. `ramp_ms` overrides the
        default GAIN_GLIDE_S duration for the permanent glide only (on_update
        passes its own update_ramp_ms so params and gain land on the same
        transition; every other caller leaves it unset — unchanged
        behaviour)."""
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
                duration_ms = ramp_ms if ramp_ms is not None else int(GAIN_GLIDE_S * 1000)
                await self.executor.glide(vid, state.effect_type,
                                          {"brightness": peak},
                                          duration_ms)
                carry[(vid, "brightness")] = peak
                out.append({"virtual_id": vid, "lands": round(peak, 4),
                            "held": True})
        return out

    # ── UPDATE (report data/spectra-trigger-migration-scoping/RULING.md) ──

    async def on_update(self, intensity: float) -> dict:
        """A major change WITHIN the active scene, bigger than a flare,
        overriding the drift, landing on a ramp-in — the owner's words.
        Deliberately NOT band-gated like on_event's four classes: this
        always executes the active scene's OWN designated kind
        (SceneV2.update_kind), bypassing intensity-band selection entirely
        — reset and update are the SAME call (his correction: "reset is
        treated as update"). No update_kind authored on the active scene,
        or the named kind isn't a declared type="permanent" kind, is a
        silent no-op — same "nothing declared → nothing happens"
        convention as on_event's "no band". Only permanent params/gain are
        supported (never drift_jump/colour — his definition is about
        magnitude and drift override, not a colour pick; also keeps this
        path clear of the colour-jump KeyError class documented in
        spectra-room-fault-diagnosis/report.md section 3)."""
        scene = self.conductor.scene
        record: dict[str, Any] = {"at": self._clock(), "class": "update",
                                  "intensity": round(intensity, 4)}
        if scene is None:
            record["result"] = "no_active_scene"
            self.surges.append(record)
            return record
        kind = None
        if scene.update_kind:
            kind = {k.name: k for k in scene.flare_kinds}.get(scene.update_kind)
        if kind is None or kind.type != "permanent":
            record["result"] = "no_update_kind"
            self.surges.append(record)
            return record

        ramp_ms = update_ramp_ms(intensity)
        record["ramp_ms"] = ramp_ms
        carry: dict[tuple[str, str], Any] = {}
        if kind.params:
            record["moved"] = await self._move_params_ramped(kind, intensity, carry, ramp_ms)
        if kind.gain != 1.0:
            record["gained"] = await self._gain(kind, intensity, carry, ramp_ms=ramp_ms)
        self.conductor.on_surge(carry)
        record["carried"] = [{"virtual_id": vid, "param": p} for (vid, p) in carry]
        record["result"] = "updated"
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
