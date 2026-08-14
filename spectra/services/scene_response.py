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
     of phase_progress → 1.0 over the class's ramp (charge 4000 ms builds,
     lull 2500 ms suspends, drop 400 ms — the snap). The drive fires for
     EVERY charge/lull/drop event, band or no band — exactly as the
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
                  re-resolve with fresh dice and JUMP to the new values.
                  The rolls CARRY. Scale is inert (a roll has no
                  magnitude — stated).
       momentary/permanent params — absolute targets, name-broadcast: a
                  key lands on every virtual whose live effect carries the
                  param (shared registry truth). Scale s moves the target
                  to baseline + (declared − baseline)·s against the
                  carried-now baseline, clamped to the param's registry
                  range; ×1 lands the declared value verbatim. PERMANENT
                  carries — the landed value is the new baseline drift
                  resumes from. MOMENTARY schedules a return: the release
                  glides back to the baseline AS CARRIED AT FLUSH TIME (a
                  creep's current wander position, or the tracked param
                  baseline) — the spike never moves the baseline.
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
schedules flush_releases() after PULSE_HOLD_S; the executable specs call it
explicitly for determinism.

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
from spectra.models.scene import FlareBand, FlareKind, ResponseClass, SceneV2
from spectra.models.sequencer import CurvePoint
from spectra.services import binding_resolver, color_journey
from spectra.services import selection_kernel as kernel
from spectra.services.binding_resolver import FireContext

logger = logging.getLogger(__name__)

PULSE_HOLD_S = 0.25      # the spike shows for a couple of frames, then releases
PULSE_RELEASE_S = 1.5    # glide back to baseline
GAIN_GLIDE_S = 0.8       # linear/ease_* land over this, then hold (carried)
SURGE_LOG_LIMIT = 50

# Flare colour-jump RAMP-IN (owner refinement of jump-not-blend, not its
# reversal): the ramp length scales INVERSELY with the fire's intensity —
# a gentle flare eases its new colours in noticeably, a full-scale flare
# still lands hard, close to the old immediate jump. Linear between the
# ends; the blend rides the tween engine's hue arc (never through grey),
# and the room journey resumes from the landed colour exactly as before.
COLOR_JUMP_RAMP_MS_GENTLE = 2500   # intensity 0.0 — the felt ease-in
COLOR_JUMP_RAMP_MS_HARD = 150      # intensity 1.0 — lands hard


def color_jump_ramp_ms(intensity: float) -> int:
    frac = max(0.0, min(1.0, intensity))
    return int(round(COLOR_JUMP_RAMP_MS_GENTLE
                     + (COLOR_JUMP_RAMP_MS_HARD
                        - COLOR_JUMP_RAMP_MS_GENTLE) * frac))

# phase_progress ramp per class — the original program's tuned durations
# (config.py phase_*_ramp_ms defaults): "Drop stays short — it's the snap."
PHASE_RAMP_MS = {"charge": 4000, "lull": 2500, "drop": 400}


def select_band(bands: list[FlareBand], intensity: float) -> Optional[FlareBand]:
    for band in bands:
        if band.intensity_min <= intensity < band.intensity_max:
            return band
        if intensity == band.intensity_max == 1.0:
            return band
    return None


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

        self.surges: deque[dict] = deque(maxlen=SURGE_LOG_LIMIT)
        # (virtual_id, param) pairs a momentary kind spiked, awaiting the
        # release glide back to the carried baseline.
        self._pending_releases: list[tuple[str, str]] = []
        self._phase_armed: Optional[str] = None  # "charge"|"lull" awaiting payoff

    # ── the event ────────────────────────────────────────────────────────────

    async def on_event(self, event_class: ResponseClass,
                       intensity: float) -> dict:
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
            record["phase"] = await self._drive_phase(event_class)
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
        jumps: dict[str, dict[str, Any]] = {}   # vid → params
        kind_records: list[dict] = []

        if dice:   # one fresh roll per fire, however many dice kinds attach
            kind, scale = dice[0]
            kind_records.append({
                "name": kind.name, "type": kind.type, "jump": "dice",
                "scale": scale,
                "rolled": self._reroll(scene, intensity, jumps, carry)})
        for kind, scale in moves:
            kind_records.append({
                "name": kind.name, "type": kind.type, "scale": scale,
                "moved": self._move_params(kind, scale, jumps, carry)})
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
                jumps: dict, carry: dict) -> list[dict]:
        """Fresh dice: every signal="random" binding re-resolves in one new
        FireContext (correlated letters stay correlated — one roll per
        letter) and the changed params jump on the entry's winning
        virtuals. Stepped-effect entries re-roll the variant the FIRE
        selected (keyed by the entry's live effect) — a surge re-rolls
        dice, it never re-selects the effect."""
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
            for pname, value in dev.params_for_effect(live_effect).items():
                if isinstance(value, ValueBinding) and value.signal == "random":
                    meta = device_model.get_param_meta(live_effect, pname)
                    kind, lo, hi = binding_resolver.kind_for_meta(meta)
                    out = binding_resolver.apply_binding(value, ctx, kind, lo, hi)
                    if out is not None:
                        targets[pname] = out
            for field in ("brightness", "background_brightness"):
                value = getattr(dev, field)
                if isinstance(value, ValueBinding) and value.signal == "random":
                    out = binding_resolver.apply_binding(
                        value, ctx, binding_resolver.KIND_NUMERIC, 0.0, 1.0)
                    if out is not None:
                        targets[field] = out
            for vid in vids:
                jumps.setdefault(vid, {}).update(targets)
                for pname, out in targets.items():
                    carry[(vid, pname)] = out
            rolled.extend({"param": p, "value": v} for p, v in targets.items())
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

    def _move_params(self, kind: FlareKind, scale: float,
                     jumps: dict, carry: dict) -> list[dict]:
        """One momentary/permanent kind's param moves. Name-broadcast
        targeting: each key lands on every virtual whose live effect has
        that param (registry truth); explicit kinds override same-key
        re-rolls — the band's word wins. Scale ×1 lands the declared value
        VERBATIM (legacy parity); any other scale moves the target to
        baseline + (declared − baseline)·scale, clamped to the param's
        registry range. PERMANENT enters the carry; MOMENTARY schedules
        the return instead."""
        landed: list[dict] = []
        for vid, state in self.conductor.virtuals.items():
            moves: dict[str, float] = {}
            for pname, value in kind.params.items():
                meta = device_model.get_param_meta(state.effect_type, pname)
                if meta is None:
                    continue
                target = float(value)
                if scale != 1.0:
                    base = self._carried_value(vid, state, pname, carry)
                    if base is not None:
                        target = base + (target - base) * scale
                        mkind, lo, hi = binding_resolver.kind_for_meta(meta)
                        if mkind == binding_resolver.KIND_NUMERIC:
                            if lo is not None:
                                target = max(float(lo), target)
                            if hi is not None:
                                target = min(float(hi), target)
                moves[pname] = target
                if kind.type == "permanent":
                    carry[(vid, pname)] = target
                else:
                    self._pending_releases.append((vid, pname))
            if moves:
                jumps.setdefault(vid, {}).update(moves)
                landed.append({"virtual_id": vid, "params": moves})
        return landed

    async def _gain(self, kind: FlareKind, scale: float,
                    carry: dict) -> list[dict]:
        """One kind's brightness envelope around the carried baseline, at
        effective gain 1 + (gain − 1)·scale — neutral stays neutral, a duck
        scales into a deeper duck. MOMENTARY: spike to baseline×effective,
        release back (the baseline stays). PERMANENT: glide to
        baseline×effective and hold — CARRIED."""
        effective = 1.0 + (kind.gain - 1.0) * scale
        out: list[dict] = []
        for vid, state in self.conductor.virtuals.items():
            baseline = carry.get((vid, "brightness"),
                                 state.brightness_baseline)
            peak = max(0.0, min(1.0, float(baseline) * effective))
            if kind.type == "momentary":
                await self.executor.jump(vid, state.effect_type,
                                         {"brightness": peak})
                self._pending_releases.append((vid, "brightness"))
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

    async def flush_releases(self) -> int:
        """Issue pending momentary releases — every spiked (virtual, param)
        glides back to its baseline AS CARRIED NOW (a colour jump or
        permanent kind in the same surge may have moved it; a creep kept
        wandering — the release honors the carry, never a stale snapshot).
        Production schedules this PULSE_HOLD_S after the spike
        (services/engine.py); specs call it directly once the spike has
        provably landed. Returns virtuals released."""
        pending, self._pending_releases = self._pending_releases, []
        by_vid: dict[str, dict[str, float]] = {}
        for vid, pname in dict.fromkeys(pending):
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

    async def _drive_phase(self, event_class: str) -> dict:
        """Arm + ramp the vendored phase machinery on every phase-capable
        virtual — the exact drive the original program used: the instant
        arm write must land before the ramp (jump, then glide — in-process
        the calls are ordered by construction; the legacy path needed an
        explicit bus drain). The choreography itself — blackhole's swallow,
        orbits' collapse, fireworks' rockets, the eye's lids — is the
        effects' own vendored code, not re-invented here."""
        ramp_ms = PHASE_RAMP_MS[event_class]
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
        return {"targets": targets, "ramp_ms": ramp_ms}

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
        by_vid = scene_compiler._set_entry_by_virtual(card)
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
                params["background_color"] = entry.bg_color
                carry[(vid, "background_color")] = entry.bg_color
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
    def _default_set_card(set_id: str):
        from spectra.services import color_sets
        return color_sets.get_by_id(set_id)

    @staticmethod
    async def _no_broadcast(payload: dict) -> None:
        pass
