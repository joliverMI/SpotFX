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
  colour journey — the room's walk (services/color_journey holds the binding
           custody semantics): the wheel advances Δ° per leg under whoever
           steers (room by default, an overriding scene outright), and the
           active palette rotates WITH it — gradient + background together,
           hue-blend glides on set-mode virtuals. Rainbow/achromatic
           palettes pause the walk; the wheel position persists to shared
           room state every leg, so custody transfers never move it.

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
from typing import Any, Awaitable, Callable, Optional

from spectra.models.scene import DriftSpec, SceneV2
from spectra.services import color_journey, color_rotate
from spectra.services.selection_kernel import curve_eval

logger = logging.getLogger(__name__)

LEG_S = 20.0            # design band 10–30 s; one leg every 20 s
NEUTRAL_INTENSITY = 0.5  # follow's stated degradation when no feed exists


class VirtualState:
    """Per-virtual engine truth, seeded at re-baseline: the effect type the
    glides address, whether colour-set colours own this virtual, the current
    palette strings (rotation baseline), and the brightness baseline the
    gain envelope returns to."""

    def __init__(self, effect_type: str, entry_id: str, color_mode: str,
                 config: dict[str, Any]) -> None:
        self.effect_type = effect_type
        self.entry_id = entry_id
        self.set_mode = color_mode == "set"
        self.gradient: str | None = config.get("gradient")
        self.background_color: str | None = config.get("background_color")
        self.brightness_baseline: float = float(config.get("brightness", 1.0))


class Mechanism:
    def __init__(self, vid: str, param: str, spec: DriftSpec,
                 baseline: float) -> None:
        self.vid = vid
        self.param = param
        self.spec = spec
        self.kind = spec.kind
        # creep state: the wander position IS the carried baseline.
        self.position = min(max(baseline, spec.lo), spec.hi) \
            if spec.kind == "creep" else baseline
        self.direction = 1

    def as_status(self) -> dict:
        out = {"virtual_id": self.vid, "param": self.param, "kind": self.kind}
        if self.kind == "creep":
            out.update(position=round(self.position, 4), lo=self.spec.lo,
                       hi=self.spec.hi, rate_per_min=self.spec.rate_per_min,
                       motion=self.spec.motion)
        else:
            out.update(slew_s=self.spec.slew_s)
        return out


def _creep_step(mech: Mechanism, leg_s: float) -> float:
    """Advance a creep's wander one leg — the NumericNudge bounce semantics
    made continuous; wrap folds into [lo, hi)."""
    spec = mech.spec
    span = spec.hi - spec.lo
    pos = mech.position + spec.rate_per_min * (leg_s / 60.0) * mech.direction
    if spec.motion == "wrap":
        pos = spec.lo + ((pos - spec.lo) % span)
    else:
        while pos > spec.hi or pos < spec.lo:
            if pos > spec.hi:
                pos = spec.hi - (pos - spec.hi)
                mech.direction = -1
            else:
                pos = spec.lo + (spec.lo - pos)
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
        transfer (color_journey semantics), the story never snaps."""
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
            for param, ref in entry.drift.items():
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
                self.mechanisms.append(Mechanism(vid, param, spec, baseline))
        if color_set_id is not None:
            room = self._room_load()
            self._room_save(room.model_copy(
                update={"active_set_id": color_set_id}))
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
                    mech.position = min(max(float(value), mech.spec.lo),
                                        mech.spec.hi)
            state = self.virtuals.get(vid)
            if state is None:
                continue
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

        journey_rec = self._journey_leg(batches, leg_ms, legs)

        intensity = self._intensity()
        if intensity is None:
            intensity = NEUTRAL_INTENSITY
        for mech in self.mechanisms:
            if mech.kind == "creep":
                target = _creep_step(mech, self.leg_s)
                duration = leg_ms
            else:
                target = curve_eval(self._follow_points(mech.spec), intensity)
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

        record = {"at": self._clock(), "journey": journey_rec, "legs": legs,
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

    def _journey_leg(self, batches: dict, leg_ms: int,
                     legs: list[dict]) -> dict:
        """Advance the wheel one leg under whoever steers; rotate the active
        palette with it on set-mode virtuals. Persists room state so the
        wheel survives restarts and custody transfers read one truth."""
        room = self._room_load()
        journey = color_journey.active_journey(room, self.scene)
        rainbow = False
        if room.active_set_id is not None:
            rainbow = self._set_position(room.active_set_id) is None
        new_deg = color_journey.step(journey, room.wheel_position_deg,
                                     self.leg_s, palette_rainbow=rainbow)
        rec = {"custody": journey.custody,
               "degrees_per_min": journey.degrees_per_min,
               "wheel_position_deg": round(new_deg, 2) if new_deg is not None
               else None,
               "paused": rainbow or new_deg is None}
        if new_deg is None or new_deg == room.wheel_position_deg:
            return rec
        delta = journey.degrees_per_min * (self.leg_s / 60.0)
        for vid, state in self.virtuals.items():
            if not state.set_mode:
                continue
            params: dict[str, Any] = {}
            if state.gradient:
                state.gradient = color_rotate.rotate_color_value(
                    state.gradient, delta)
                params["gradient"] = state.gradient
            if state.background_color:
                state.background_color = color_rotate.rotate_color_value(
                    state.background_color, delta)
                params["background_color"] = state.background_color
            if params:
                batches.setdefault((vid, leg_ms), {}).update(params)
                legs.append({"virtual_id": vid, "param": "palette",
                             "kind": "journey", "target": round(delta, 3),
                             "duration_ms": leg_ms})
        self._room_save(room.model_copy(update={"wheel_position_deg": new_deg}))
        return rec

    # ── supervised production loop ───────────────────────────────────────────

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.leg_s)
            try:
                await self.tick()
            except Exception:
                logger.exception("drift conductor: leg failed")

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
            },
            "mechanisms": [m.as_status() for m in self.mechanisms],
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
    def _default_set_position(set_id: str) -> Optional[float]:
        from spectra.services import color_sets, color_wheel
        card = color_sets.get_by_id(set_id)
        if card is None:
            return None
        return color_wheel.wheel_position(card).position_deg

    @staticmethod
    async def _no_broadcast(payload: dict) -> None:
        pass
