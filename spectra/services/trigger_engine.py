"""SPECTRA-native trigger engine — THE KEYSTONE's execution half
(decision-mid-song-model.md). Fed by the S2 bridge's track state through
two calls (services/engine.py wires both): on_track_state(uri) on every
broadcast (mirrors scene_sequencer.TransitionSource.observe_uri) and
tick(position_ms) every TICK_S from the engine's own poll loop. Fires each
of the current song's stored triggers (trigger_store) exactly once, the
moment its timestamp is first crossed:

  fire_scene          scene_sequencer.fire_scene_by_id — the SAME choke
                       point the sequencer's own picks use (re-baselines
                       drift via scene_compiler.fire_scene's on_scene_fired).
  fire_response        engine.fire_response_event — the SAME path the
                       bridge's classified trigger_fired events already
                       drive (phase drive, band selection, pulse release).
  select_color_set      drift_conductor.apply_set_directly — the SAME
                       manual-apply surface POST /api/room-color/apply uses.

Two worlds coexist during migration (CLAUDE.md): this engine only ever
reads storage/spectra/triggers.json and the bridge's read-only feed; it
never touches storage/profiles or the legacy trigger_fired path.

Edge-triggered: a trigger fires once, on the first tick whose
(last_position, position] window crosses its timestamp. A URI change (a
NEW song, or the bridge dropping to None and reconnecting) rearms: the
next tick anchors last_position at position-1, so a trigger sitting
exactly AT that position (timestamp_ms=0 at song start, chiefly) still
fires, while nothing further back is backfired — a mid-song process
restart doesn't replay the whole song's history. A backward seek
(rewind/scrub) rearms the same way, silently, on the tick it's detected —
approaching the same moment again fires it again.

Executable spec: scripts/check_triggers.py (fake position feed, injected
fires — no live storage, no LedFX I/O, no audio).
Frame-level proof: tests/test_trigger_engine.py (FacadeExecutor + the
headless dummy device).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from spectra.models.trigger import SpectraTrigger
from spectra.services import trigger_store

logger = logging.getLogger(__name__)

TICK_S = 0.2


class TriggerEngine:
    """One instance per process (singleton below). Constructor injectables
    exist for the executable spec only — production uses the defaults."""

    def __init__(
        self, *,
        list_triggers: Callable[[str], list[SpectraTrigger]] | None = None,
        fire_scene: Callable[..., Awaitable[Any]] | None = None,
        fire_response: Callable[[str, float], Awaitable[Any]] | None = None,
        select_color_set: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self._list_triggers = list_triggers or trigger_store.list_for_song
        self._fire_scene = fire_scene or self._default_fire_scene
        self._fire_response = fire_response or self._default_fire_response
        self._select_color_set = select_color_set or self._default_select_color_set

        self._uri: Optional[str] = None
        self._last_position_ms: Optional[int] = None
        self.last_fire: Optional[dict] = None  # observability

    # ── feed (services/engine.py calls both) ─────────────────────────────

    async def on_track_state(self, uri: Optional[str]) -> None:
        """A URI change rearms the clock: last_position resets so the next
        tick anchors fresh at wherever it finds the position, never
        backfiring the song's history."""
        if uri == self._uri:
            return
        self._uri = uri
        self._last_position_ms = None

    async def tick(self, position_ms: Optional[int]) -> list[SpectraTrigger]:
        """One evaluation, called every TICK_S with the CURRENT position.
        Also called directly by the executable spec / tests with a fake
        position feed. Returns the triggers fired this tick, in timestamp
        order."""
        if self._uri is None or position_ms is None:
            return []
        if self._last_position_ms is None:
            # Rearm: anchor one ms behind so a trigger sitting exactly AT
            # this position still fires, without backfiring further back.
            self._last_position_ms = position_ms - 1
        last = self._last_position_ms
        self._last_position_ms = position_ms
        if position_ms < last:
            return []  # rewind/seek back: silently rearmed via the line above
        fired: list[SpectraTrigger] = []
        for trig in self._list_triggers(self._uri):
            if not trig.enabled:
                continue
            if last < trig.timestamp_ms <= position_ms:
                await self._fire(trig)
                fired.append(trig)
        return fired

    async def _fire(self, trig: SpectraTrigger) -> None:
        a = trig.action
        try:
            if a.kind == "fire_scene":
                await self._fire_scene(a.scene_id, a.color_set_id, a.intensity)
            elif a.kind == "fire_response":
                await self._fire_response(a.event_class, a.intensity)
            else:
                await self._select_color_set(a.set_id)
        except Exception:
            logger.exception("trigger %s (%s @ %dms) failed to fire",
                             trig.id, a.kind, trig.timestamp_ms)
            self.last_fire = {"id": trig.id, "kind": a.kind, "ok": False}
            return
        logger.info("trigger %s fired: %s @ %dms", trig.id, a.kind, trig.timestamp_ms)
        self.last_fire = {"id": trig.id, "kind": a.kind, "ok": True}

    # ── observability ─────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "track_uri": self._uri,
            "position_ms": self._last_position_ms,
            "last_fire": self.last_fire,
        }

    # ── production defaults (lazy imports; the spec injects fakes) ──────────

    async def _default_fire_scene(self, scene_id: str,
                                  color_set_id: Optional[str],
                                  intensity: float) -> None:
        from spectra.services.scene_sequencer import fire_scene_by_id
        await fire_scene_by_id(scene_id, color_set_id, intensity)

    async def _default_fire_response(self, event_class: str, intensity: float) -> None:
        from spectra.services import engine
        await engine.fire_response_event(event_class, intensity)

    async def _default_select_color_set(self, set_id: str) -> None:
        from spectra.services import color_sets, engine
        card = color_sets.get_by_id(set_id)
        if card is None or card.kind != "set":
            raise ValueError(f"colour set '{set_id}' not found")
        await engine.conductor.apply_set_directly(card)


trigger_engine = TriggerEngine()
