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
responses.take_release_schedule() group — the entries ONE fire armed at ONE
chosen hold (hold_ms, default PULSE_HOLD_S), sleeping until the group's
ABSOLUTE due time (stamped when the spike write went out, NOT when on_event
returned — the old "sleep hold_s after the whole fire finished" shape is
what held his 500ms reverse for ~1.0s live; scene_response.py's module
docstring, "RELEASE OWNERSHIP", has the trace). The colour ROTATE-AND-BACK
flare (2026-08-20) schedules its own, separately-timed release the same way,
off responses.pending_color_rotate_holds() — see scene_response._color_rotate's
own docstring for why it can't share the param/gain queue above. The
parameter watchdog (spectra/services/param_watchdog.py, its own supervised
task in spectra/app.py — PR #186) backstops a release that never lands.
"""
from __future__ import annotations

import asyncio
import logging

from fx import light_ownership
from spectra.models.scene import SceneV2
from spectra.services import av_sync_lead
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


async def fire_response_event(event_class: str, intensity: float,
                              gap_ms: int | None = None,
                              via_trigger: bool = False) -> None:
    """The ONE response-fire choke point: the bridge's classified legacy
    trigger_fired events and SPECTRA-native fire_response triggers
    (spectra.services.trigger_engine) both call this — and, since
    "triggers_only" (2026-08-20, data/spectra-my-triggers-only-mode), the
    two callers need DIFFERENT gates, which is what via_trigger is for.
    Flares are the owner's authored material (scene response bands,
    hand-tuned per scene). Also gated by a live colour Preview
    (spectra/services/preview_pause.py) — checked first, ahead of the
    settings-tier gate, for both paths.

    via_trigger=False (the default — the bridge's own call site, UNCHANGED
    by this field): requires literally scene_change_mode=="full", same as
    before "triggers_only" existed. The bridge classifies EVERY
    trigger_fired broadcast on the shared /ws, which still includes root
    spot-effects' own legacy trigger engine firing regardless of light
    ownership (a separate, larger, un-fixed defect — see
    data/charge-lull-drop-timing-blends-and-a-sus-7fm2/report.md §1) —
    this path is never "his triggers," so "triggers_only" never opens it.

    via_trigger=True (trigger_engine's own call site, spectra.services.
    trigger_engine._default_fire_response): the caller already gated this
    crossing (it can only be source=="authored", and only ever reaches
    here on a song trigger_engine._effective_mode_for_song has already
    confirmed carries an authored trigger of its own) — allowed at "full"
    OR "triggers_only". This is what makes his own charge/lull/drop marks
    fire under "triggers_only" while the bridge-relayed duplicate that
    used to double them stays silent — the mechanism the linked report
    proved causes that doubling.

    gap_ms is the OVERRIDE BLEND charge/lull stretch input
    (scene_response._phase_ramp_ms): TriggerEngine._fire computes it from
    the real per-song trigger schedule (honoring the SAME per-song
    effective mode _effective_mode_for_song resolves — see
    TriggerEngine._next_trigger_gap_ms) and passes it through; the
    bridge's own classified-event call (no SPECTRA trigger context) and a
    manual /api/engine/event test-fire both omit it, its documented
    default — an honest "unknown," not a zero."""
    from spectra.services import fire_history, preview_pause
    from spectra.services.room_controls import load_room_controls
    if preview_pause.active():
        return
    mode = load_room_controls().scene_change_mode
    allowed = mode in ("full", "triggers_only") if via_trigger else mode == "full"
    if not allowed:
        return
    await responses.on_event(event_class, intensity, gap_ms)
    # The 2D drift gradient's DROP kick (owner ask 2026-08-24, order item 2):
    # a drop jumps X a full extra leg-step, pushes the Y TARGET up by the
    # drop's own energy, and lands the resulting colour immediately — see
    # DriftConductor.on_drop_event. Wired HERE, inside the already
    # preview-/mode-gated choke point, so it rides exactly the path a real
    # drop drives; a strict no-op while no gradient is active. Direct call
    # (not an injectable like trigger_engine._intensity_event) because this
    # module already owns the conductor singleton — trigger_engine.py needed
    # the hook only because nothing there may reach this process's conductor.
    if event_class == "drop":
        try:
            await conductor.on_drop_event(intensity)
        except Exception:
            logger.exception("gradient drift: on_drop_event failed")
    fire_history.record_fire("responses", event_class,
                             {"event_class": event_class, "intensity": intensity})
    # One release task per ReleaseGroup this fire armed — owned by THIS
    # fire (fire_seq), sleeping until the group's ABSOLUTE due time, which
    # was stamped when the spike writes went out, not now: on_event's own
    # serial write burst (measured ~400ms on his live room) used to push
    # a 500ms hold out to ~1.0s (scene_response.py's module docstring,
    # "RELEASE OWNERSHIP").
    for group in responses.take_release_schedule():
        asyncio.create_task(_release_group(group))
    # The colour ROTATE-AND-BACK flare's own release queue (owner ask,
    # 2026-08-20) — its fade-back duration is intensity-scaled per fire, so
    # it can't share pending_hold_groups/_release_after_hold's fixed
    # PULSE_RELEASE_S (see scene_response._color_rotate's own docstring).
    # Same shape, separate queue, separate scheduling loop.
    for dwell_s in responses.pending_color_rotate_holds():
        asyncio.create_task(_release_color_rotate_after_dwell(dwell_s))


async def _release_group(group) -> None:
    await asyncio.sleep(responses.seconds_until(group.due_at))
    await responses.flush_releases(group.hold_s, fire_seq=group.fire_seq,
                                   due_by=group.due_at)


async def _release_color_rotate_after_dwell(dwell_s: float) -> None:
    await asyncio.sleep(dwell_s)
    await responses.flush_color_rotates(dwell_s)


async def fire_scene_update_event(intensity: float) -> Optional[dict]:
    """The UPDATE choke point (data/spectra-trigger-migration-scoping
    RULING.md): a SPECTRA-native fire_scene_update trigger
    (spectra.services.trigger_engine) calls this — there is no legacy
    bridge-classified equivalent (update_scene/reset_scene never went
    through the bridge's flare/charge/lull/drop classification either),
    so unlike fire_response_event above there's only ever the one
    (trigger-driven, necessarily authored) caller from THAT path — no
    via_trigger split needed for it. Gated at "full" OR "triggers_only",
    same reasoning as fire_response_event's via_trigger=True path: a
    fire_scene_update trigger action only ever reaches here on a song
    trigger_engine._effective_mode_for_song has already confirmed carries
    an authored trigger of its own.

    responses.on_update() is now (2026-08-20, his ask: "make update scene
    act like a double intensity flare until we build it out specifically")
    a placeholder that fires the active scene's own ordinary "flare" band
    at 2x intensity — the SAME kind execution a genuine flare runs, so
    unlike the original permanent-only design it CAN land a momentary
    kind, a dice re-roll, or a colour rotate, each of which pends its own
    release. This mirrors fire_response_event's own scheduling immediately
    below, rather than skipping it — a real hold/release here now behaves
    exactly like a real flare's.

    A SECOND caller as of the dwell rebuild (2026-08-20,
    spectra.services.scene_sequencer.fire_scene_by_id's dwell gate,
    spectra/services/dwell.py): a scene-change request deferred by an
    active minimum dwell fires the current scene's own update effect
    INSTEAD of switching — this is the confirmed "Update effect" his dwell
    card meant. This caller is NOT limited to "full" OR "triggers_only" by
    anything of its own — the dwell gate itself already applies
    uniformly regardless of scene_change_mode (his own decision C) — it
    just happens to reach the SAME tier check below as the trigger-driven
    caller; on a tighter tier (e.g. "analysed"/"transitions") the update
    simply doesn't run and the deferral still degrades to fire_scene_by_id's
    own recorded hold, never raises. Returns the on_update() record (None
    on an early gate-out above) so a caller that needs to know what
    happened — dwell's own fire_history "deferred" record — can log it;
    the trigger-driven caller still discards it, unchanged."""
    from spectra.services import preview_pause
    from spectra.services.room_controls import load_room_controls
    if preview_pause.active():
        return None
    if load_room_controls().scene_change_mode not in ("full", "triggers_only"):
        return None
    record = await responses.on_update(intensity)
    for group in responses.take_release_schedule():
        asyncio.create_task(_release_group(group))
    for dwell_s in responses.pending_color_rotate_holds():
        asyncio.create_task(_release_color_rotate_after_dwell(dwell_s))
    return record


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
    it was authored against. His own measured A/V-sync lead
    (RoomControlState.av_sync_lead_ms, the /avsync Apply button's target)
    is layered on top of that here — this is its single application point.
    Errors are logged and swallowed per tick — one bad trigger must never
    stop the clock."""
    from spectra.services.trigger_engine import TICK_S
    while True:
        try:
            # THE ONE PLACE the A/V-sync lead reaches the show (owner ask
            # 2026-08-28). LEAD family, positive = fire EARLIER, layered on
            # top of the xcorr correction the bridge already applied; None
            # (never calibrated, the default) shifts nothing. Read fresh
            # every tick like scene_change_mode beside it, so his apply
            # takes effect without a restart. The sign law and the reason
            # this term exists at all are in av_sync_lead.py's docstring —
            # do NOT add a second application point.
            await trigger_engine.tick(av_sync_lead.show_clock_ms(
                bridge.effective_position_ms(), av_sync_lead.current_lead_ms()))
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
    from spectra.services import ambient_music_gate, param_watchdog
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
        # The param orphan watchdog (spectra/services/param_watchdog.py):
        # restores, suspicions, give-ups — loud by design, see its docstring.
        "param_watchdog": param_watchdog.status(),
    }
