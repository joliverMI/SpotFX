"""SPECTRA scene sequencer engine — the spot-effects port, semantics
unchanged (decision-complete per the five answered holds), re-homed on
SPECTRA's stores with two deliberate S1 differences:

  1. The wheel position is SHARED ROOM-COLOUR STATE (storage/spectra/
     room_color.json via services/color_journey), no longer sequencer-private
     — creep, jumps, and the selector's travel factor all read one truth
     (a named change in the accepted design).
  2. The music feed IS the S2 read-only bridge (services/bridge): song
     transitions tick on_track_state(), intensity is section energy at the
     playback position (0.5 neutral when the bridge or analysis is absent —
     stated degradation), genre buckets come from the training profiles,
     deferrals from the broadcast flags + the settings poll, and
     trigger-fired scenes are observed via last_scene_id. enabled stays
     False by default regardless (its own dark switch) — feeding the engine
     is not enabling it.

Change moments: SONG TRANSITIONS ONLY (decision 5, binding) — the pluggable
ChangeMomentSource seam ports verbatim; no timer, ever, without the owner's
call. ACCEPTED CONSEQUENCE on record: a long mix holds one scene however
hard it builds; drift (S2) softens that without touching the clock.

Fires resolve bindings at the moment's intensity and go through
scene_compiler.fire_scene(dry_run=False) — scene + colour set in ONE compile.

Executable spec: scripts/check_spectra.py (fake clock, injected fire — no
live LedFX, no audio).
"""
from __future__ import annotations

import logging
import time
from random import Random
from typing import Any, Awaitable, Callable, Optional

from spectra.models.sequencer import CurvePoint, SequencerConfig
from spectra.services import selection_kernel as kernel
from spectra.services import sequencer_store

logger = logging.getLogger(__name__)

TRANSITION_SOURCE = "transition"


async def fire_scene_by_id(scene_id: str,
                           color_set_id: Optional[str] = None,
                           intensity: float = 0.5) -> dict:
    """The ONE scene-fire choke point for anything that picks a scene by id
    outside the editor's own test-fire — the sequencer's own rolls and
    SPECTRA-native triggers (spectra.services.trigger_engine) both call
    this, so "fire scene X" means exactly one thing everywhere it happens.

    Force Scene (room_controls.RoomControlState.force_scene_enabled/
    force_scene_scene_id, the legacy Now Playing control ported verbatim)
    redirects scene_id here — the single interception point every automatic
    pick already funnels through. Only the scene is pinned; color_set_id/
    intensity pass through as the caller resolved them, same as legacy's
    "reassert with normal First/Rest." A forced id pointing at a missing
    scene is treated as unset (falls through to the requested scene)."""
    from spectra.services import color_set_groups, color_sets, fire_history, scene_compiler, scene_store
    from spectra.services.room_controls import load_room_controls
    controls = load_room_controls()
    if controls.force_scene_enabled and controls.force_scene_scene_id:
        if scene_store.get_by_id(controls.force_scene_scene_id) is not None:
            scene_id = controls.force_scene_scene_id
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise ValueError(f"scene {scene_id} not found in spectra scenes")
    color_set = color_sets.get_by_id(color_set_id) if color_set_id else None
    if color_set is not None:
        # A Group reference resolves to its picked member here (§10) — a
        # missing/unusable one falls back to the room's active set below,
        # same as an unknown plain set id already did.
        color_set = color_set_groups.resolve_for_fire(color_set)
    result = await scene_compiler.fire_scene(scene, intensity=intensity,
                                             color_set=color_set, dry_run=False)
    fire_history.record_fire("scenes", scene_id, {
        "scene_name": getattr(scene, "name", scene_id),
        "color_set_id": color_set_id,
        "intensity": intensity,
    })
    return result


class ChangeMomentSource:
    """The pluggable clock seam. A source decides WHEN a change moment
    exists; the engine decides what the moment means. Shipped:
    TransitionSource only — a later owner-approved TimedSource binds the
    same way and needs no engine rework."""

    name = "unset"

    def bind(self, emit: Callable[[str], Awaitable[None]]) -> None:
        self._emit = emit

    async def _fire(self) -> None:
        await self._emit(self.name)


class TransitionSource(ChangeMomentSource):
    """Song transitions: a moment each time the playing URI changes to a new
    one. The first URI seen after startup only ARMS the source — a restart
    mid-song must not change the room mid-song. Stop/None holds the last
    URI, so pause→resume of the same song is not a transition."""

    name = TRANSITION_SOURCE

    def __init__(self) -> None:
        self._last_uri: Optional[str] = None

    async def observe_uri(self, uri: Optional[str]) -> None:
        if uri is None or uri == self._last_uri:
            return
        armed = self._last_uri is not None
        self._last_uri = uri
        if armed:
            await self._fire()


class SceneSequencer:
    """One instance per process (singleton below). Constructor injectables
    exist for the executable spec only — production uses the defaults."""

    def __init__(
        self, *,
        rng: Random | None = None,
        fire: Callable[..., Awaitable[Any]] | None = None,
        intensity: Callable[[], float] | None = None,
        genre_bucket: Callable[[], Optional[str]] | None = None,
        deferral_fn: Callable[[], Optional[str]] | None = None,
        trigger_scene_id: Callable[[], Optional[str]] | None = None,
        list_scene_ids: Callable[[], set[str]] | None = None,
        scene_name: Callable[[str], str] | None = None,
        broadcast: Callable[[dict], Awaitable[None]] | None = None,
        eligible_sets: Callable[[str], dict[str, Optional[float]]] | None = None,
        color_set_name: Callable[[str], str] | None = None,
        wheel_get: Callable[[], Optional[float]] | None = None,
        wheel_set: Callable[[Optional[float]], None] | None = None,
    ) -> None:
        self._rng = rng or Random()
        self._fire = fire or self._default_fire
        self._intensity = intensity or self._default_intensity
        self._genre_bucket = genre_bucket or self._default_genre_bucket
        self._deferral = deferral_fn or self._default_deferral
        self._trigger_scene_id = trigger_scene_id or self._default_trigger_scene_id
        self._list_scene_ids = list_scene_ids or self._default_list_scene_ids
        self._scene_name = scene_name or self._default_scene_name
        self._broadcast = broadcast or self._default_broadcast
        # scene_id → {set_id: wheel position_deg | None} for every existing
        # colour set the scene accepts (two-way filter applied).
        self._eligible_sets = eligible_sets or self._default_eligible_sets
        self._color_set_name = color_set_name or self._default_color_set_name
        # Shared room-colour truth (the design's named change).
        self._wheel_get = wheel_get or self._default_wheel_get
        self._wheel_set = wheel_set or self._default_wheel_set

        self.transition_source = TransitionSource()
        self.transition_source.bind(self._on_change_moment)

        # Runtime state — in-memory only, rebuilt from the room after restart.
        self._active_id: Optional[str] = None
        self._served_songs: int = 0
        self._dwell_target: int = 0
        self._dwell_weight: float = 1.0
        self._seen_trigger_scene_id: Optional[str] = None
        self._last_pick: Optional[dict] = None
        self._last_moment: Optional[dict] = None
        self._warned_change_mode: Optional[str] = None
        self._active_color_set_id: Optional[str] = None
        self._last_color_pick: Optional[dict] = None

    # ── feed (the S2 bridge calls this on every state broadcast) ────────────

    async def on_track_state(self, uri: Optional[str]) -> None:
        await self.transition_source.observe_uri(uri)

    # ── the moment ──────────────────────────────────────────────────────────

    async def _on_change_moment(self, source: str) -> None:
        config = sequencer_store.load_config()
        if not config.enabled:
            return
        if config.change_mode != "transition" and \
                self._warned_change_mode != config.change_mode:
            self._warned_change_mode = config.change_mode
            logger.warning(
                "sequencer change_mode=%s stored, but only the transition "
                "clock ships (decision 5) — ticking song transitions only",
                config.change_mode)

        deferral = self._deferral()
        if deferral is not None:
            self._record_moment(source, f"deferred:{deferral}")
            return

        adopted_now = self._observe_trigger_fires(config)

        if self._active_id is not None and not adopted_now:
            self._served_songs += 1
            if self._served_songs < self._dwell_target:
                self._record_moment(source, "held")
                return
        elif adopted_now and self._served_songs < self._dwell_target:
            # Freshly adopted (trigger-fired) scene hasn't been through a
            # full song yet — this moment neither counts nor changes it.
            self._record_moment(source, "held")
            return

        await self._roll(config, source)

    def _observe_trigger_fires(self, config: SequencerConfig) -> bool:
        """Observe (never drive) the legacy engine through the bridge: a new
        trigger-fired scene id since the last enabled moment is adopted with
        a fresh dwell count. The first enabled moment only baselines."""
        seen = self._trigger_scene_id() or None
        if self._seen_trigger_scene_id is None:
            self._seen_trigger_scene_id = seen or ""
            return False
        if seen and seen != self._seen_trigger_scene_id:
            self._seen_trigger_scene_id = seen
            self._adopt(seen, config)
            logger.info("sequencer: adopted trigger-fired scene %s "
                        "(dwell reset, target %d songs)", seen, self._dwell_target)
            return True
        return False

    def _adopt(self, scene_id: str, config: SequencerConfig) -> None:
        entry = config.entries.get(scene_id)
        self._active_id = scene_id
        self._served_songs = 0
        self._dwell_weight = entry.dwell_weight if entry else 1.0
        self._dwell_target = kernel.resolve_dwell_songs(self._dwell_weight, self._rng)

    async def _roll(self, config: SequencerConfig, source: str) -> None:
        curves = sequencer_store.load_curves()
        existing = self._list_scene_ids()
        missing = set(config.entries) - existing
        if missing:
            logger.warning("sequencer: %d entr(y/ies) reference no scene "
                           "and are skipped: %s", len(missing), sorted(missing))
        intensity = self._intensity()
        genre_bucket = self._genre_bucket()
        candidates = kernel.build_scene_candidates(
            config.entries, curves, config.affinity,
            genre_bucket=genre_bucket, prev_id=self._active_id,
            restrict_ids=existing)
        pick = kernel.select(candidates, intensity=intensity,
                             rng=self._rng, current_id=self._active_id,
                             terminal=kernel.TERMINAL_STAY)
        self._last_pick = {
            "picked_id": pick.picked_id,
            "picked_name": self._scene_name(pick.picked_id) if pick.picked_id else None,
            "rung": pick.rung,
            "intensity": round(pick.intensity, 4),
            "factors": pick.factors,
            "source": source,
            "at": time.time(),
        }
        if pick.picked_id is None:
            self._record_moment(source, "stay")
            logger.info("sequencer: ladder terminated at STAY (intensity %.2f)",
                        pick.intensity)
            return
        if pick.picked_id == self._active_id:
            # Only reachable via the re-admit/uniform rungs. The room already
            # shows this scene — renew dwell instead of re-firing.
            self._adopt(pick.picked_id, config)
            self._record_moment(source, "renewed")
            logger.info("sequencer: current scene %s renewed via rung=%s "
                        "(dwell target %d songs)", pick.picked_id, pick.rung,
                        self._dwell_target)
            return
        color = self._roll_color_set(config, curves, pick.picked_id,
                                     intensity, genre_bucket)
        try:
            await self._fire(pick.picked_id,
                             color["fire_set_id"] if color else None,
                             intensity)
        except Exception:
            logger.exception("sequencer: firing scene %s failed", pick.picked_id)
            self._record_moment(source, "fire_failed")
            return
        self._adopt(pick.picked_id, config)
        if color is not None:
            self._adopt_colors(color)
        self._record_moment(source, "picked")
        logger.info("sequencer: picked %s via rung=%s at intensity %.2f "
                    "(dwell target %d songs, weight %g)", pick.picked_id,
                    pick.rung, pick.intensity, self._dwell_target,
                    self._dwell_weight)
        await self._broadcast({
            "type": "sequencer_pick",
            **self._last_pick,
            "dwell_target_songs": self._dwell_target,
            "dwell_weight": self._dwell_weight,
            "color": self._last_color_pick if color is not None else None,
        })

    # ── the colour-set selector (colours change with scenes) ────────────────

    def _roll_color_set(self, config: SequencerConfig, curves: dict,
                        scene_id: str, intensity: float,
                        genre_bucket: Optional[str]) -> Optional[dict]:
        """Roll the colour-set selector for the scene about to fire. None =
        selector unconfigured. A TERMINAL_KEEP pick fires the CURRENT set so
        the new scene keeps the room's palette — never forced to churn."""
        if not config.color_set_entries:
            return None
        eligible = self._eligible_sets(scene_id)
        wheel_profile = (curves.get(config.wheel_travel_curve)
                         if config.wheel_travel_curve else None)
        wheel_points = (wheel_profile.points if wheel_profile
                        else [CurvePoint(x=0.0, y=1.0)])   # no curve ≡ neutral
        candidates = kernel.build_color_set_candidates(
            config.color_set_entries, curves,
            genre_bucket=genre_bucket, room_deg=self._wheel_get(),
            set_positions=eligible, wheel_points=wheel_points)
        pick = kernel.select_color_set(candidates, intensity=intensity,
                                       rng=self._rng,
                                       current_id=self._active_color_set_id)
        picked = pick.picked_id
        fire_set_id = picked if picked is not None else self._active_color_set_id
        return {
            "picked_id": picked,
            "fire_set_id": fire_set_id,
            "position_deg": eligible.get(picked) if picked is not None else None,
            "record": {
                "picked_id": picked,
                "picked_name": (self._color_set_name(picked)
                                if picked is not None else None),
                "kept_set_id": None if picked is not None else fire_set_id,
                "rung": pick.rung,
                "factors": pick.factors,
            },
        }

    def _adopt_colors(self, color: dict) -> None:
        """Commit colour state AFTER a successful fire. Rainbow/achromatic
        picks (position None) move the active set but leave the room's wheel
        position where the last chromatic set put it — the binding rule."""
        self._last_color_pick = color["record"]
        if color["picked_id"] is not None:
            self._active_color_set_id = color["picked_id"]
            if color["position_deg"] is not None:
                self._wheel_set(color["position_deg"])
        self._last_color_pick["wheel_position_deg"] = self._wheel_get()

    def _record_moment(self, source: str, result: str) -> None:
        self._last_moment = {"source": source, "result": result, "at": time.time()}

    # ── observability (GET /spectra/api/sequencer/status) ───────────────────

    def status(self) -> dict:
        config = sequencer_store.load_config()
        return {
            "enabled": config.enabled,
            "change_mode": config.change_mode,
            "next_change_source": TRANSITION_SOURCE,  # the only shipped clock
            "deferred_by": self._deferral(),
            "bridge_connected": self._bridge_connected(),
            "active_scene_id": self._active_id,
            "active_scene_name": (self._scene_name(self._active_id)
                                  if self._active_id else None),
            "dwell": {
                "served_songs": self._served_songs,
                "target_songs": self._dwell_target,
                "weight": self._dwell_weight,
            } if self._active_id else None,
            "last_pick": self._last_pick,
            "last_moment": self._last_moment,
            "color": {
                "active_set_id": self._active_color_set_id,
                "active_set_name": (self._color_set_name(self._active_color_set_id)
                                    if self._active_color_set_id else None),
                "wheel_position_deg": self._wheel_get(),
                "last_pick": self._last_color_pick,
            },
        }

    # ── production defaults (lazy imports; the spec injects fakes) ──────────

    async def _default_fire(self, scene_id: str,
                            color_set_id: Optional[str] = None,
                            intensity: float = 0.5) -> None:
        await fire_scene_by_id(scene_id, color_set_id, intensity)

    def _default_eligible_sets(self, scene_id: str) -> dict[str, Optional[float]]:
        from spectra.services import color_sets, color_wheel, scene_store
        scene = scene_store.get_by_id(scene_id)
        out: dict[str, Optional[float]] = {}
        for card in color_sets.list_all():
            if card.kind != "set":
                continue
            if scene is not None and not scene.accepts_color_set(card):
                continue
            out[card.id] = color_wheel.wheel_position(card).position_deg
        return out

    def _default_color_set_name(self, set_id: str) -> str:
        from spectra.services import color_sets
        card = color_sets.get_by_id(set_id)
        return card.name if card else set_id

    def _default_intensity(self) -> float:
        # Bridge feed: section energy at position; 0.5 neutral when absent
        # (stated degradation).
        from spectra.services.engine import bridge
        value = bridge.intensity()
        return value if value is not None else 0.5

    def _default_genre_bucket(self) -> Optional[str]:
        from spectra.services.engine import bridge
        return bridge.genre_bucket()

    def _default_deferral(self) -> Optional[str]:
        # Force Scene / pause / Dinner Party / Ambient, read off the bridge.
        from spectra.services.engine import bridge
        return bridge.sequencer_deferral()

    def _default_trigger_scene_id(self) -> Optional[str]:
        from spectra.services.engine import bridge
        return bridge.trigger_scene_id()

    def _bridge_connected(self) -> bool:
        from spectra.services.engine import bridge
        return bridge.connected

    def _default_list_scene_ids(self) -> set[str]:
        from spectra.services import scene_store
        return {s.id for s in scene_store.list_all()}

    def _default_scene_name(self, scene_id: str) -> str:
        from spectra.services import scene_store
        scene = scene_store.get_by_id(scene_id)
        return scene.name if scene else scene_id

    async def _default_broadcast(self, payload: dict) -> None:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast(payload)

    def _default_wheel_get(self) -> Optional[float]:
        from spectra.services import color_journey
        return color_journey.load_room().wheel_position_deg

    def _default_wheel_set(self, deg: Optional[float]) -> None:
        # A sequencer colour roll teleports the wheel, invalidating the
        # journey's bearing — clear it so the conductor reselects a
        # destination from the new point next leg.
        from spectra.services import color_journey
        room = color_journey.load_room()
        color_journey.save_room(room.model_copy(
            update={"wheel_position_deg": deg, "destination": None}))


scene_sequencer = SceneSequencer()
