"""SPECTRA-native trigger engine — THE KEYSTONE's execution half
(decision-mid-song-model.md, its 2026-08-14 framing correction, and the
settings-model brief, corr=c14a9bcee40e6df9). Fed by the S2 bridge's track
state through two calls (services/engine.py wires both): on_track_state(uri)
on every broadcast (mirrors scene_sequencer.TransitionSource.observe_uri)
and tick(position_ms) every TICK_S from the engine's own poll loop. Fires
each of the current song's stored triggers (trigger_store) exactly once, the
moment its timestamp is first crossed:

  fire_scene          scene_sequencer.fire_scene_by_id — the SAME choke
                       point the sequencer's own picks use (re-baselines
                       drift via scene_compiler.fire_scene's on_scene_fired).
                       scene_id=None (a GENERATED trigger's own default,
                       front 3 — spectra/services/midsong_generator.py)
                       instead resolves through the sequencer selection
                       kernel AT FIRE TIME (curve × genre × affinity, using
                       the TRIGGER's own intensity) — see
                       _default_select_scene below.
  fire_response        engine.fire_response_event — the SAME path the
                       bridge's classified trigger_fired events already
                       drive (phase drive, band selection, pulse release).
  select_color_set      drift_conductor.apply_set_directly — the SAME
                       manual-apply surface POST /api/room-color/apply uses.

THE SETTINGS MODEL (room_controls.RoomControlState.scene_change_mode,
replacing front 3's plain midsong_triggers_enabled bool): three additive
tiers the owner ticks on the room bar —
  "transitions" — a scene change on every song transition only, nothing
                  else: no stored trigger fires (see _fire_transition below).
  "analysed"    — transitions + GENERATED mid-song triggers (source=
                  "generated" — midsong_generator's analysed section
                  boundaries). Hand-authored triggers still don't fire.
  "full"        — everything: transitions + generated mid-song triggers +
                  the owner's own hand-authored triggers (source=
                  "authored") + response-engine flares (gated at
                  engine.fire_response_event, the same choke point both a
                  bridge-classified flare and a trigger's fire_response
                  action reach). Default.
Checked per-crossing in tick() below (_trigger_allowed) — same seam the old
bool switch used, extended to also cover authored triggers (which
previously always fired regardless of the switch) and, at
engine.fire_response_event, flares (previously always on regardless).

THE AUTOMATIC TRANSITION FIRE (_fire_transition, all three modes): "scene
changes ON song transitions" is the floor every tier shares — the STANDARD
the binding decision names ("out of the box a song behaves exactly as
transitions-only"). It is deliberately NOT a stored SpectraTrigger at
timestamp_ms=0: the tick() edge-crossing window rearms at
`position_ms - 1` on a song change (see below), so a trigger sitting
exactly at 0 only fires if the very first tick after the change happens to
land before playback has advanced past it — a real bridge-poll race, not a
reliable mechanism. Firing directly from on_track_state's own transition
detection (mirrors scene_sequencer.TransitionSource's arm/fire semantics:
the first URI seen only arms, a stop/None doesn't count as a transition)
sidesteps that race entirely while still routing through the SAME
selection-kernel + fire_scene_by_id choke point every other scene pick
uses — "one mechanism," in the sense of one execution pathway, even though
this one moment isn't individually retimable/deletable per song the way a
stored trigger is (a deliberate, documented scope call for this settings-
model build, not a rebuild of the full transition-authoring surface).

DEFERS TO scene_sequencer WHEN IT'S THE LIVE TRANSITION AUTHORITY: both
scene_sequencer.on_track_state and this engine's on_track_state are wired
off the SAME URI-change broadcast (services/engine.py's _on_track_uri) — if
the sequencer's own config.enabled is True it ALREADY fires a scene on
every transition through its own TransitionSource, with richer state
(dwell songs served, weighted re-admit/uniform rungs, curve×genre×affinity
carried across songs) than this engine's one-shot kernel draw. Two
mechanisms firing on the same transition would double-fire the room, and
neither would know about the other's pick. Resolution (settings-model
correction, live reality: the sequencer was enabled on the running system
the same day this was built, already observed picking real transitions):
_fire_transition checks sequencer_store.load_config().enabled and is a
no-op whenever it's True — the sequencer remains the sole transition
authority, unconditionally, whether or not the settings model is at its
"transitions" floor; this engine's automatic fire only ever runs when the
sequencer is at ITS shipped default (dark, config.enabled=False). This was
the deliberately smaller, more conservative resolution over formally
superseding/disabling the sequencer: the sequencer's dwell/affinity state
is real, already-verified-working production behaviour as of the
correction, and re-deriving it in this engine (or migrating it away) is a
materially bigger change than this settings-model build's scope. See
_default_sequencer_enabled below and scripts/check_triggers.py's coverage
proving exactly one scene change fires per transition either way.

Two worlds coexist during migration (CLAUDE.md): this engine only ever
reads storage/spectra/triggers.json and the bridge's read-only feed; it
never touches storage/profiles or the legacy trigger_fired path.

AUTO-GENERATION (Admiral ask, order 12 — "they should be auto-generated if
there are none when the song is playing, I shouldn't have to go in and do
that"): maybe_auto_generate(uri), called by services/engine.py's
_on_track_uri on the SAME first-time-seeing-this-URI edge that already
resets _last_track_uri, runs midsong_generator.generate_for_song for a song
with ZERO stored triggers of either source — no timeline visit required.
Fire-and-forget (scheduled via asyncio.create_task, never awaited by the
caller) so a slow or never-analyzed song can never delay the transition
fire or tick work that already ran synchronously before it. Generated
triggers fire immediately at their normal gate (scene_change_mode
"analysed"/"full") — no separate review step; holding them for review
would recreate the exact friction this exists to remove. Never touches a
trigger he has claimed as his own: the empty-store precondition means no
authored trigger can be present when generation starts, and
generate_for_song's own source="generated"-only filtering (front 3) is the
second, independent guard. An unanalyzed song degrades honestly —
generate_for_song already returns a clean zero-moment no-op, never a
fabricated trigger. _generating (per-uri) stops a song from being
re-scheduled while its own generation is still in flight; the module-level
generation lock serializes the actual file-writing bodies of concurrent
generations for DIFFERENT songs, so two songs starting close together can't
interleave their trigger_store read-modify-write cycles.

Edge-triggered: a trigger fires once, on the first tick whose
(last_position, position] window crosses its timestamp. A URI change (a
NEW song, or the bridge dropping to None and reconnecting) rearms: the
next tick anchors last_position at position-1, so a trigger sitting
exactly AT that position still fires, while nothing further back is
backfired — a mid-song process restart doesn't replay the whole song's
history. A backward seek (rewind/scrub) rearms the same way, silently, on
the tick it's detected — approaching the same moment again fires it again.

Executable spec: scripts/check_triggers.py (fake position feed, injected
fires — no live storage, no LedFX I/O, no audio).
Frame-level proof: tests/test_trigger_engine.py (FacadeExecutor + the
headless dummy device).
"""
from __future__ import annotations

import asyncio
import logging
from random import Random
from typing import Any, Awaitable, Callable, Optional

from spectra.models.trigger import SpectraTrigger
from spectra.services import trigger_store

logger = logging.getLogger(__name__)

TICK_S = 0.2

# Serializes the file-writing body of concurrent auto-generations for
# DIFFERENT songs (trigger_store's read-modify-write cycle isn't itself
# lock-protected). Lazily created — mirrors spectra/services/ambient.py's
# _get_lock — so constructing the module-level TriggerEngine singleton
# below never requires a running event loop.
_generation_lock: Optional[asyncio.Lock] = None


def _get_generation_lock() -> asyncio.Lock:
    global _generation_lock
    if _generation_lock is None:
        _generation_lock = asyncio.Lock()
    return _generation_lock


class TriggerEngine:
    """One instance per process (singleton below). Constructor injectables
    exist for the executable spec only — production uses the defaults."""

    def __init__(
        self, *,
        list_triggers: Callable[[str], list[SpectraTrigger]] | None = None,
        fire_scene: Callable[..., Awaitable[Any]] | None = None,
        fire_response: Callable[[str, float], Awaitable[Any]] | None = None,
        select_color_set: Callable[[str], Awaitable[Any]] | None = None,
        select_scene: Callable[[float], Optional[str]] | None = None,
        scene_change_mode: Callable[[], str] | None = None,
        transition_intensity: Callable[[], float] | None = None,
        sequencer_enabled: Callable[[], bool] | None = None,
        auto_generate: Callable[[str], Awaitable[Any]] | None = None,
        rng: Random | None = None,
    ) -> None:
        self._list_triggers = list_triggers or trigger_store.list_for_song
        self._fire_scene = fire_scene or self._default_fire_scene
        self._fire_response = fire_response or self._default_fire_response
        self._select_color_set = select_color_set or self._default_select_color_set
        self._select_scene = select_scene or self._default_select_scene
        self._scene_change_mode = scene_change_mode or self._default_scene_change_mode
        self._transition_intensity = (transition_intensity
                                      or self._default_transition_intensity)
        self._sequencer_enabled = sequencer_enabled or self._default_sequencer_enabled
        self._auto_generate = auto_generate or self._default_auto_generate
        self._generating: set[str] = set()
        self._rng = rng or Random()

        self._uri: Optional[str] = None
        self._last_position_ms: Optional[int] = None
        # Separate from _uri/_last_position_ms: mirrors
        # scene_sequencer.TransitionSource's arm/fire state so a stop/None
        # never counts as (or breaks arming for) a transition.
        self._last_transition_uri: Optional[str] = None
        self.last_fire: Optional[dict] = None  # observability

    # ── feed (services/engine.py calls both) ─────────────────────────────

    async def on_track_state(self, uri: Optional[str]) -> None:
        """A URI change rearms the tick clock: last_position resets so the
        next tick anchors fresh at wherever it finds the position, never
        backfiring the song's history. A genuine song-to-song change (armed
        after the first URI ever seen; a stop/None neither fires nor
        disarms) additionally fires the automatic transition scene change —
        see the module docstring's _fire_transition section."""
        if uri != self._uri:
            self._uri = uri
            self._last_position_ms = None
        if uri is None or uri == self._last_transition_uri:
            return
        armed = self._last_transition_uri is not None
        self._last_transition_uri = uri
        if armed:
            await self._fire_transition()

    async def _fire_transition(self) -> None:
        if self._sequencer_enabled():
            logger.info("song transition: scene_sequencer.config.enabled is "
                        "True — it already fires its own transition pick "
                        "(dwell/affinity), so trigger_engine defers to avoid "
                        "a double scene change")
            return
        intensity = self._transition_intensity()
        scene_id = self._select_scene(intensity)
        if scene_id is None:
            logger.info("song transition: kernel picked no scene "
                        "(ladder terminated at stay) — nothing fired")
            return
        try:
            await self._fire_scene(scene_id, None, intensity)
        except Exception:
            logger.exception("song transition: firing scene %s failed", scene_id)
            return
        logger.info("song transition: fired scene %s", scene_id)
        self.last_fire = {"id": None, "kind": "transition", "ok": True}

    def maybe_auto_generate(self, uri: Optional[str]) -> None:
        """Called by services/engine.py's _on_track_uri on the same
        first-time-seeing-this-URI edge that resets _last_track_uri — a
        song with zero stored triggers (of either source) gets generated
        for automatically. Fire-and-forget by design: the caller is never
        made to wait on this (see the module docstring's AUTO-GENERATION
        section)."""
        if not uri or uri in self._generating or self._list_triggers(uri):
            return
        self._generating.add(uri)
        asyncio.create_task(self._run_auto_generate(uri))

    async def _run_auto_generate(self, uri: str) -> None:
        try:
            await self._auto_generate(uri)
        except Exception:
            logger.exception("auto-generate: trigger generation failed for %s", uri)
        finally:
            self._generating.discard(uri)

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
        mode = self._scene_change_mode()
        fired: list[SpectraTrigger] = []
        for trig in self._list_triggers(self._uri):
            if not trig.enabled:
                continue
            if not self._trigger_allowed(trig, mode):
                continue
            if last < trig.timestamp_ms <= position_ms:
                await self._fire(trig)
                fired.append(trig)
        return fired

    @staticmethod
    def _trigger_allowed(trig: SpectraTrigger, mode: str) -> bool:
        """The settings model's gate (room_controls.RoomControlState.
        scene_change_mode): "full" fires everything; "analysed" and
        "transitions" both skip hand-authored triggers, and "transitions"
        additionally skips GENERATED (analysed mid-song) triggers — the
        automatic transition fire (_fire_transition) is the only thing that
        still happens in "transitions" mode, and it isn't a stored trigger
        at all, so it never reaches this gate."""
        if trig.source == "authored":
            return mode == "full"
        return mode in ("analysed", "full")

    async def _fire(self, trig: SpectraTrigger) -> None:
        a = trig.action
        try:
            if a.kind == "fire_scene":
                scene_id = a.scene_id
                if scene_id is None:
                    scene_id = self._select_scene(a.intensity)
                    if scene_id is None:
                        logger.info("trigger %s: kernel picked no scene "
                                    "(ladder terminated at stay) — nothing fired",
                                    trig.id)
                        self.last_fire = {"id": trig.id, "kind": a.kind,
                                          "ok": True, "picked": None}
                        return
                await self._fire_scene(scene_id, a.color_set_id, a.intensity)
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
        from spectra.services import fire_history
        fire_history.record_fire(
            "triggers", f"{trig.source}:{a.kind}",
            {"trigger_id": trig.id, "action_kind": a.kind, "source": trig.source},
            uri=self._uri, position_ms=self._last_position_ms)

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

    def _default_select_scene(self, intensity: float) -> Optional[str]:
        """A generated trigger's scene_id=None resolution: the SAME
        selection kernel the sequencer's own rolls use
        (scene_sequencer._roll), but a one-shot draw at the TRIGGER's own
        intensity — no dwell, no "current scene" affinity tracked across
        trigger fires (deliberately simpler than the sequencer's continuous
        state machine; a mid-song trigger names one moment, not a stream of
        them). picked_id None (the terminal STAY rung, or no configured
        sequencer entries at all) means nothing fires this crossing."""
        from spectra.services import scene_store, selection_kernel as kernel
        from spectra.services import sequencer_store
        from spectra.services.engine import bridge
        config = sequencer_store.load_config()
        curves = sequencer_store.load_curves()
        existing = {s.id for s in scene_store.list_all()}
        candidates = kernel.build_scene_candidates(
            config.entries, curves, config.affinity,
            genre_bucket=bridge.genre_bucket(), prev_id=None,
            restrict_ids=existing)
        pick = kernel.select(candidates, intensity=intensity, rng=self._rng,
                             current_id=None, terminal=kernel.TERMINAL_STAY)
        return pick.picked_id

    def _default_scene_change_mode(self) -> str:
        from spectra.services.room_controls import load_room_controls
        return load_room_controls().scene_change_mode

    def _default_transition_intensity(self) -> float:
        # Same bridge feed + 0.5 neutral fallback as scene_sequencer's own
        # _default_intensity — no per-song analysis is required for the
        # automatic transition fire to work.
        from spectra.services.engine import bridge
        value = bridge.intensity()
        return value if value is not None else 0.5

    def _default_sequencer_enabled(self) -> bool:
        # scene_sequencer's OWN dark switch (config.enabled, storage/
        # spectra/sequencer.json) — separate from scene_change_mode. When
        # True the sequencer is the live transition authority (see
        # _fire_transition's module-docstring section); this engine's
        # automatic transition fire only runs when it's False (the
        # sequencer's shipped default).
        from spectra.services import sequencer_store
        return sequencer_store.load_config().enabled

    async def _default_fire_response(self, event_class: str, intensity: float) -> None:
        from spectra.services import engine
        await engine.fire_response_event(event_class, intensity)

    async def _default_select_color_set(self, set_id: str) -> None:
        from spectra.services import color_sets, engine
        card = color_sets.get_by_id(set_id)
        if card is None or card.kind != "set":
            raise ValueError(f"colour set '{set_id}' not found")
        await engine.conductor.apply_set_directly(card)

    async def _default_auto_generate(self, uri: str) -> None:
        # Off the event loop entirely (candidate_moments can rescan
        # analysis_reader's whole shape index on a miss) and serialized
        # against any other song's concurrent auto-generation, so two songs
        # starting close together can't interleave trigger_store's
        # read-modify-write file cycle.
        from spectra.services import midsong_generator
        async with _get_generation_lock():
            result = await asyncio.to_thread(midsong_generator.generate_for_song, uri)
        if result.get("added"):
            logger.info("auto-generate: seeded %d mid-song trigger(s) for %s "
                        "(no timeline visit)", result["added"], uri)


trigger_engine = TriggerEngine()
