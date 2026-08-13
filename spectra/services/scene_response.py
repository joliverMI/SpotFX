"""The response engine — surges (report §2.4). Retires the "bands carried
but not evaluated" placeholder: all four event classes (flare / charge /
lull / drop) now EXECUTE against the active scene's responses block.

Per event, fed by the bridge with the fire's intensity:

  1. Select the band containing the intensity ([min, max); the top band is
     inclusive at exactly 1.0 so a full-scale fire always matches). No band
     → the class stays silent at that intensity — bands are the response's
     WHEN along the axis.
  2. One batched pass:
       re-roll  — the scene's 🎲 (signal="random") bindings re-resolve with
                  fresh dice and JUMP to the new values (reroll_dice flag).
       patch    — band.param_patch as a JUMP, name-broadcast targeting: a
                  key lands on every virtual whose live effect carries that
                  param (shared registry truth).
       gain     — the momentary envelope on brightness around the carried
                  baseline: curve "pulse" spikes to baseline×gain and
                  glides back (release scheduled after the spike holds a
                  beat); linear/ease_* glide to baseline×gain and HOLD —
                  the landed level becomes the new baseline.
       colour   — flares with color_set_jump roll the shipped colour-set
                  selector (curve × genre × wheel-travel) against the
                  scene's eligible sets and the ROOM wheel position, and
                  JUMP (never blend) to the pick; the terminal rung KEEPS
                  the current colours (decision 3 — never forced churn).
                  A chromatic pick moves the room's wheel position, and the
                  room journey RESUMES FROM THE NEW POINT — the jump moves
                  the story, the walk carries on.
  3. CARRY (the owner's words): patches, re-rolls, held gains, and colour
     jumps permanently move the baseline drift resumes from
     (conductor.on_surge). A surge on a followed param is an impulse the
     follow re-asserts from smoothly over slew_s — no bookkeeping needed,
     the next leg does it by construction.

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
from spectra.models.scene import FlareBand, ResponseClass, SceneV2
from spectra.models.sequencer import CurvePoint
from spectra.services import binding_resolver, color_journey
from spectra.services import selection_kernel as kernel
from spectra.services.binding_resolver import FireContext

logger = logging.getLogger(__name__)

PULSE_HOLD_S = 0.25      # the spike shows for a couple of frames, then releases
PULSE_RELEASE_S = 1.5    # glide back to baseline
GAIN_GLIDE_S = 0.8       # linear/ease_* land over this, then hold (carried)
SURGE_LOG_LIMIT = 50


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
        self._pending_releases: list[str] = []   # virtual ids awaiting release

    # ── the event ────────────────────────────────────────────────────────────

    async def on_event(self, event_class: ResponseClass,
                       intensity: float) -> dict:
        scene = self.conductor.scene
        record: dict[str, Any] = {
            "at": self._clock(), "class": event_class,
            "intensity": round(intensity, 4),
        }
        spec = scene.responses.get(event_class) if scene else None
        if scene is None or spec is None:
            record["result"] = "no_active_scene" if scene is None else "no_class"
            self.surges.append(record)
            return record
        band = select_band(spec.bands, intensity)
        if band is None:
            record["result"] = "no_band"
            self.surges.append(record)
            return record
        record["band"] = {"intensity_min": band.intensity_min,
                          "intensity_max": band.intensity_max,
                          "curve": band.curve, "gain": band.gain}

        carry: dict[tuple[str, str], Any] = {}
        jumps: dict[str, dict[str, Any]] = {}   # vid → params

        if spec.reroll_dice:
            record["reroll"] = self._reroll(scene, intensity, jumps, carry)
        if band.param_patch:
            record["patch"] = self._patch(band.param_patch, jumps, carry)
        for vid, params in jumps.items():
            state = self.conductor.virtuals.get(vid)
            if state is not None:
                await self.executor.jump(vid, state.effect_type, params)

        if band.gain != 1.0:
            record["gain_envelope"] = await self._gain(band, carry)

        if event_class == "flare" and spec.color_set_jump:
            record["color_jump"] = await self._color_jump(scene, intensity,
                                                          carry)

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
        virtuals."""
        ctx = FireContext(intensity, rng=self._rng)
        entry_vids: dict[str, list[str]] = {}
        for vid, state in self.conductor.virtuals.items():
            entry_vids.setdefault(state.entry_id, []).append(vid)
        rolled: list[dict] = []
        for dev in scene.devices:
            vids = entry_vids.get(dev.id, [])
            if not vids:
                continue
            targets: dict[str, Any] = {}
            for pname, value in dev.params.items():
                if isinstance(value, ValueBinding) and value.signal == "random":
                    meta = device_model.get_param_meta(dev.effect_type, pname)
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

    def _patch(self, param_patch: dict[str, float],
               jumps: dict, carry: dict) -> list[dict]:
        """Name-broadcast targeting: each key lands on every virtual whose
        live effect has that param (registry truth). Patches override
        same-key re-rolls — the band's explicit word wins."""
        landed: list[dict] = []
        for vid, state in self.conductor.virtuals.items():
            hits = {k: v for k, v in param_patch.items()
                    if device_model.get_param_meta(state.effect_type, k)
                    is not None}
            if not hits:
                continue
            jumps.setdefault(vid, {}).update(hits)
            for k, v in hits.items():
                carry[(vid, k)] = v
            landed.append({"virtual_id": vid, "params": hits})
        return landed

    async def _gain(self, band: FlareBand, carry: dict) -> list[dict]:
        """The envelope, around the carried brightness baseline. pulse:
        spike to baseline×gain, release back (momentary — baseline stays).
        linear/ease_*: glide to baseline×gain and hold — CARRIED."""
        out: list[dict] = []
        for vid, state in self.conductor.virtuals.items():
            baseline = carry.get((vid, "brightness"),
                                 state.brightness_baseline)
            peak = max(0.0, min(1.0, float(baseline) * band.gain))
            if band.curve == "pulse":
                await self.executor.jump(vid, state.effect_type,
                                         {"brightness": peak})
                self._pending_releases.append(vid)
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
        """Issue pending pulse releases — each virtual glides back to its
        brightness baseline AS CARRIED NOW (a colour jump in the same surge
        may have moved it; the release honors the carry, never a stale
        snapshot). Production schedules this PULSE_HOLD_S after the spike
        (services/engine.py); specs call it directly once the spike has
        provably landed."""
        pending, self._pending_releases = self._pending_releases, []
        count = 0
        for vid in dict.fromkeys(pending):
            state = self.conductor.virtuals.get(vid)
            if state is None:
                continue
            await self.executor.glide(
                vid, state.effect_type,
                {"brightness": state.brightness_baseline},
                int(PULSE_RELEASE_S * 1000))
            count += 1
        return count

    async def _color_jump(self, scene: SceneV2, intensity: float,
                          carry: dict) -> dict:
        """The flare colour jump: the shipped selector picks (curve × genre
        × wheel-travel, terminal KEEP), the pick lands as a JUMP on set-mode
        virtuals, a chromatic pick moves the room's wheel — and the journey
        resumes from the new point on the conductor's next leg."""
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
                await self.executor.jump(vid, state.effect_type, params)
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
                "wheel_position_deg": position}

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
