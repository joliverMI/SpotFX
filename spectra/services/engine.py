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

Scene fires re-baseline the engine: scene_compiler.fire_scene (non-dry)
hands the ORIGINAL scene (bindings intact — re-rolls need them) plus the
resolved writes to on_scene_fired(). The sequencer's fires arrive through
the same choke point.

Pulse releases: the spike must land a render frame before the release glide
starts (scene_response docstring); production schedules flush_releases()
PULSE_HOLD_S after each surge.
"""
from __future__ import annotations

import asyncio
import logging

from fx import light_ownership
from spectra.models.scene import SceneV2
from spectra.services import scene_response
from spectra.services.bridge import SpotEffectsBridge
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.scene_response import ResponseEngine
from spectra.services.ws import ws_manager

logger = logging.getLogger(__name__)

executor = RecordingExecutor()

conductor = DriftConductor(
    executor=executor,
    intensity=lambda: bridge.intensity(),
    deferral=lambda: bridge.conductor_deferral(),
    broadcast=ws_manager.broadcast,
)

responses = ResponseEngine(
    conductor=conductor,
    executor=executor,
    genre_bucket=lambda: bridge.genre_bucket(),
    broadcast=ws_manager.broadcast,
)


async def _on_response_event(event_class: str, intensity: float) -> None:
    await responses.on_event(event_class, intensity)
    if responses._pending_releases:
        asyncio.create_task(_release_after_hold())


async def _release_after_hold() -> None:
    await asyncio.sleep(scene_response.PULSE_HOLD_S)
    await responses.flush_releases()


async def _on_track_uri(uri) -> None:
    from spectra.services.scene_sequencer import scene_sequencer
    await scene_sequencer.on_track_state(uri)


bridge = SpotEffectsBridge(
    on_response_event=_on_response_event,
    on_track_uri=_on_track_uri,
)

_conductor_task: asyncio.Task | None = None


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
    global _conductor_task
    # A handover orphaned by a crash leaves owner=handing-over — both worlds
    # refusing to write (safe but dark). Land it back at its from-world.
    # Age-gated so a live orchestrator in another process is never fought.
    light_ownership.recover_stale_handover()
    bridge.start()
    if _conductor_task is None or _conductor_task.done():
        _conductor_task = asyncio.create_task(conductor.run(),
                                              name="spectra-drift-conductor")
    logger.info("SPECTRA S2 engine started (executor=%s — dark against real "
                "lights until S3)", executor.mode)


async def stop() -> None:
    global _conductor_task
    await bridge.stop()
    if _conductor_task is not None and not _conductor_task.done():
        _conductor_task.cancel()
        try:
            await _conductor_task
        except asyncio.CancelledError:
            pass
    _conductor_task = None


def status() -> dict:
    return {
        "increment": "S3",
        "dark": executor.mode == "recording",
        "light_ownership": light_ownership.load().owner,
        "executor": {"mode": executor.mode,
                     "recent_writes": list(executor.writes)[-20:]},
        "conductor": conductor.status(),
        "responses": {"recent_surges": list(responses.surges)[-10:]},
        "bridge": bridge.status(),
    }
