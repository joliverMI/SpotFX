"""The S2 evolution-engine runtime — the singletons, their wiring, and the
DARK discipline in one place.

What runs in production (shared process, started from the host lifespan):
  bridge     — read-only spot-effects feed (WS client + settings poll).
  conductor  — one drift leg every LEG_S seconds against the
               RecordingExecutor: legs, surges, and colour-journey walks
               are COMPUTED, RECORDED, and shown on the status surface, and
               the room's wheel state (SPECTRA's own storage) advances —
               but NO light write of any kind leaves this process. Live
               execution arrives at S3 by swapping the executor for the
               FacadeExecutor when SPECTRA owns the room; nothing else
               changes (proven today by the headless tests, which run the
               same engine against the facade on the dummy device).
  responses  — surges fed by the bridge's classified trigger fires.
  trigger_engine — THE MID-SONG CLOCK (spectra.services.trigger_engine):
               polls the bridge's streamed track position every TICK_S and
               fires the owner's SPECTRA-native per-song triggers at their
               moments. Legacy scene-change/flare events keep arriving via
               the bridge unchanged — two worlds coexist during migration.

Scene fires re-baseline the engine: scene_compiler.fire_scene (non-dry)
hands the ORIGINAL scene (bindings intact — re-rolls need them) plus the
resolved writes to on_scene_fired(). The sequencer's own picks and
SPECTRA-native fire_scene triggers both arrive through the same choke point
(scene_sequencer.fire_scene_by_id); response events (bridge-classified or
trigger-fired) both arrive through fire_response_event above.

Pulse releases: the spike must land a render frame before the release glide
starts (scene_response docstring); production schedules one release task per
responses.pending_hold_groups() entry — a momentary kind's CHOSEN HOLD
(hold_ms, default PULSE_HOLD_S) after each surge.
"""
from __future__ import annotations

import asyncio
import logging

from fx import light_ownership
from spectra.models.scene import SceneV2
from spectra.services.bridge import SpotEffectsBridge
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.scene_response import ResponseEngine
from spectra.services.trigger_engine import trigger_engine
from spectra.services.ws import ws_manager

logger = logging.getLogger(__name__)

executor = RecordingExecutor()

conductor = DriftConductor(
    executor=executor,
    intensity=lambda: bridge.intensity(),
    deferral=lambda: bridge.conductor_deferral(),
    broadcast=ws_manager.broadcast,
    genre_bucket=lambda: bridge.genre_bucket(),
)

responses = ResponseEngine(
    conductor=conductor,
    executor=executor,
    genre_bucket=lambda: bridge.genre_bucket(),
    broadcast=ws_manager.broadcast,
)

# Two-dimensional drift gradient retarget hook (owner ask 2026-08-20) — wired
# explicitly here rather than left to a lazy default inside trigger_engine.py
# (see TriggerEngine.__init__'s own comment for why): this module already
# owns constructing conductor/responses as production singletons, so it also
# owns wiring the one other thing trigger_engine.py's real fires need to
# reach on this process's conductor.
trigger_engine._intensity_event = conductor.on_intensity_event


async def fire_response_event(event_class: str, intensity: float) -> None:
    """The ONE response-fire choke point: the bridge's classified legacy
    trigger_fired events and SPECTRA-native fire_response triggers
    (spectra.services.trigger_engine) both call this. Flares are the
    owner's authored material (scene response bands, hand-tuned per scene)
    — gated to the settings model's "full" tier
    (room_controls.RoomControlState.scene_change_mode), same as
    hand-authored triggers. Covers BOTH callers from one seam: a
    trigger-driven fire_response action is already gated at its own
    crossing by trigger_engine's tick() (it can only be source="authored"),
    so this redundantly-but-harmlessly re-checks that path while being the
    ONLY gate for the bridge's always-classifying path. Also gated by a
    live colour Preview (spectra/services/preview_pause.py) — checked
    first, ahead of the settings-tier gate."""
    from spectra.services import fire_history, preview_pause
    from spectra.services.room_controls import load_room_controls
    if preview_pause.active():
        return
    if load_room_controls().scene_change_mode != "full":
        return
    await responses.on_event(event_class, intensity)
    fire_history.record_fire("responses", event_class,
                             {"event_class": event_class, "intensity": intensity})
    for hold_s in responses.pending_hold_groups():
        asyncio.create_task(_release_after_hold(hold_s))


async def _release_after_hold(hold_s: float) -> None:
    await asyncio.sleep(hold_s)
    await responses.flush_releases(hold_s)


async def fire_scene_update_event(intensity: float) -> None:
    """The UPDATE choke point (data/spectra-trigger-migration-scoping
    RULING.md): a SPECTRA-native fire_scene_update trigger
    (spectra.services.trigger_engine) calls this — there is no legacy
    bridge-classified equivalent (update_scene/reset_scene never went
    through the bridge's flare/charge/lull/drop classification either).
    Gated the same "full" tier as fire_response_event, for the same
    reason: an authored trigger's own action, same settings-model rule.
    Never schedules a hold release — on_update only fires permanent kinds,
    which carry immediately and never pend a return."""
    from spectra.services import preview_pause
    from spectra.services.room_controls import load_room_controls
    if preview_pause.active():
        return
    if load_room_controls().scene_change_mode != "full":
        return
    await responses.on_update(intensity)


_last_track_uri: str | None = None


async def _on_track_uri(uri) -> None:
    # The bridge relays every state message; change detection lives here.
    # A track change releases any armed charge/lull (the lifecycle guard
    # the original program kept — a build must not linger into the next
    # song) before the sequencer sees the transition.
    global _last_track_uri
    if uri != _last_track_uri:
        _last_track_uri = uri
        await responses.release_phases()
        if uri is not None:
            # Admiral ask, order 12: a song with no stored triggers gets
            # them generated automatically — see trigger_engine's
            # AUTO-GENERATION docstring section. Fire-and-forget; never
            # awaited here, so a slow/unanalyzed song can't delay the
            # scene_sequencer/trigger_engine transition work below.
            trigger_engine.maybe_auto_generate(uri)
    from spectra.services.scene_sequencer import scene_sequencer
    await scene_sequencer.on_track_state(uri)
    await trigger_engine.on_track_state(uri)
    # Ambient's music-precedence gate (services/ambient_music_gate.py) —
    # every bridge broadcast re-evaluates whether Ambient should be
    # holding the room right now. Backgrounded, not awaited: a hold/
    # release can take several seconds (services.ambient's own read-back
    # retries), and this callback must not stall the WS message loop for
    # that long. The gate's own lock still serialises the actual work.
    from spectra.services import ambient_music_gate
    asyncio.create_task(ambient_music_gate.reconcile(bridge.is_playing()))


bridge = SpotEffectsBridge(
    on_response_event=fire_response_event,
    on_track_uri=_on_track_uri,
)

_conductor_task: asyncio.Task | None = None
_trigger_task: asyncio.Task | None = None


async def _run_trigger_engine() -> None:
    """The trigger clock — SPECTRA's own poll of the bridge's streamed
    track position (bridge already interpolates between broadcasts;
    TICK_S just needs to be short enough that a fast build doesn't skip a
    tightly-packed trigger cluster). Ticks on effective_position_ms(), not
    the raw position — the same xcorr-derived shape_offset_ms spot-effects'
    own trigger engine applies before comparing against a trigger's
    timestamp (bridge.py's module docstring has the full port rationale);
    without it every migrated trigger fires late/early by that song's own
    offset (measured live: one song at +7052ms) instead of at the moment
    it was authored against. Errors are logged and swallowed per tick —
    one bad trigger must never stop the clock."""
    from spectra.services.trigger_engine import TICK_S
    while True:
        try:
            await trigger_engine.tick(bridge.effective_position_ms())
        except Exception:
            logger.exception("trigger engine: tick failed")
        await asyncio.sleep(TICK_S)


def on_scene_fired(scene: SceneV2, writes: list[dict],
                   color_set_id: str | None = None) -> None:
    """Any real scene fire re-baselines the engine (drift's declared life
    restarts from the new initial conditions)."""
    conductor.on_scene_fire(scene, writes, color_set_id)
    if conductor._last_rebaseline is not None:
        asyncio.ensure_future(ws_manager.broadcast(
            {"type": "drift_rebaseline", **conductor._last_rebaseline}))


def go_live(live_executor, grant: light_ownership.ActivationGrant) -> None:
    """S3: swap the engine onto a real executor — the whole live delta the
    S2 docstrings promised. Orchestrator-only: requires an ActivationGrant
    valid against the ownership record RIGHT NOW, so no code path can point
    the engine at lights SPECTRA doesn't hold."""
    global executor
    light_ownership.require_grant(grant, light_ownership.SPECTRA,
                                  detail="engine go_live")
    executor = live_executor
    conductor.executor = live_executor
    responses.executor = live_executor
    logger.warning("SPECTRA engine LIVE (executor=%s)", live_executor.mode)


def go_dark() -> None:
    """Return the engine to the recording executor (always safe — this is
    the shipped S2 state). The handover's quiesce/rollback path."""
    global executor
    dark = RecordingExecutor()
    executor = dark
    conductor.executor = dark
    responses.executor = dark
    logger.warning("SPECTRA engine dark (executor=recording)")


async def start() -> None:
    global _conductor_task, _trigger_task
    # A handover orphaned by a crash leaves owner=handing-over — both worlds
    # refusing to write (safe but dark). Land it back at its from-world.
    # Age-gated so a live orchestrator in another process is never fought.
    light_ownership.recover_stale_handover()
    bridge.start()
    if _conductor_task is None or _conductor_task.done():
        _conductor_task = asyncio.create_task(conductor.run(),
                                              name="spectra-drift-conductor")
    if _trigger_task is None or _trigger_task.done():
        _trigger_task = asyncio.create_task(_run_trigger_engine(),
                                            name="spectra-trigger-engine")
    logger.info("SPECTRA S2 engine started (executor=%s — dark against real "
                "lights until S3)", executor.mode)


async def stop() -> None:
    global _conductor_task, _trigger_task
    await bridge.stop()
    for attr in ("_conductor_task", "_trigger_task"):
        task = globals()[attr]
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        globals()[attr] = None


def status() -> dict:
    from spectra.services import ambient_music_gate
    return {
        "increment": "S3",
        "dark": executor.mode == "recording",
        "light_ownership": light_ownership.load().owner,
        "executor": {"mode": executor.mode,
                     "recent_writes": list(executor.writes)[-20:]},
        "conductor": conductor.status(),
        "responses": {"recent_surges": list(responses.surges)[-10:]},
        "bridge": bridge.status(),
        "triggers": trigger_engine.status(),
        "ambient": ambient_music_gate.status(),
    }
