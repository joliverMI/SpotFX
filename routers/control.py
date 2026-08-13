"""
SpotFX — Service control router.

Endpoints:
  POST /api/control/pause   — pause trigger firing (HA webhook compatible)
  POST /api/control/resume  — resume trigger firing
  GET  /api/control/status  — current pause state + LedFX latency
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from api.ledfx_client import get_scenes
from models.state import state
from services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/pause")
async def pause():
    state.paused = True
    logger.info("SpotFX trigger service PAUSED.")
    if state.dinner_party_mode:
        state.dinner_party_mode = False
        from routers.settings_router import _load_settings_file, _save_settings_file
        saved = _load_settings_file()
        saved["dinner_party_mode"] = False
        _save_settings_file(saved)
        from main import engine
        engine.refresh_triggerless()
    await ws_manager.broadcast_state(state)
    return {"paused": True}


@router.post("/resume")
async def resume():
    state.paused = False
    logger.info("SpotFX trigger service RESUMED.")
    return {"paused": False}


@router.get("/status")
async def status():
    return {
        "paused": state.paused,
        "ledfx_rtt_ms": round(state.ledfx_rtt_ms, 1),
        "dinner_party_mode": state.dinner_party_mode,
        "ambient_mode_enabled": state.ambient_mode_enabled,
        "ambient_groups": state.ambient_groups,
        "display_mode": state.display_mode,
        "display_mode_resolved": state.display_mode_resolved,
    }


@router.get("/ledfx/scenes")
async def ledfx_scenes():
    """Proxy: list available LedFX scenes for the UI."""
    return await get_scenes()



@router.post("/use-analyzed-triggerless")
async def set_use_analyzed_triggerless(enabled: bool):
    """Toggle between analyzed triggers and synthetic triggerless for songs without user triggers."""
    state.use_analyzed_triggerless = enabled
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["use_analyzed_triggerless"] = enabled
    _save_settings_file(saved)
    # Ensure analyzed triggers exist for current song
    from main import engine
    if enabled and engine._analyzed_triggers is None and engine._profile:
        engine._analyzed_triggers = engine._generate_analyzed_triggers(engine._profile.spotify_uri)
    engine.refresh_triggerless()
    await ws_manager.broadcast_state(state)
    return {"use_analyzed_triggerless": enabled}


@router.post("/analyzed-trigger-override")
async def set_analyzed_trigger_override(enabled: bool):
    """Debug: override user triggers with analyzed triggers for testing."""
    state.analyzed_trigger_override = enabled
    # Ensure analyzed triggers are generated for the current song
    from main import engine
    if enabled and engine._analyzed_triggers is None and engine._profile:
        engine._analyzed_triggers = engine._generate_analyzed_triggers(engine._profile.spotify_uri)
    # Clear fired sets so triggers re-evaluate from current position
    if enabled:
        engine._fired.clear()
        engine._pre_fired.clear()
    await ws_manager.broadcast_state(state)
    return {"analyzed_trigger_override": enabled, "has_analyzed": engine._analyzed_triggers is not None,
            "count": len(engine._analyzed_triggers) if engine._analyzed_triggers else 0}


@router.post("/recapture")
async def set_recapture(enabled: bool, count: int = 0):
    """Force-recapture mode. While `recapture_active` is true, every song that
    plays gets recaptured with pre-roll PCM from the always-on ring buffer.
    The counter (1-999) decrements on every song-change poll; reaches 0 →
    auto-disables. Existing shape is preserved unless the new capture passes
    all four atomic-save checks (coverage, WAV write, librosa, anchor count).
    """
    if enabled:
        n = max(1, min(999, int(count or 50)))
        state.recapture_active = True
        state.recapture_remaining = n
    else:
        state.recapture_active = False
        state.recapture_remaining = 0
    await ws_manager.broadcast_state(state)
    return {
        "recapture_active": state.recapture_active,
        "recapture_remaining": state.recapture_remaining,
    }


@router.post("/auto-generate")
async def set_auto_generate(enabled: bool):
    """Enable or disable auto-generation of AI triggers after audio shape capture."""
    state.auto_generate_enabled = enabled
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["auto_generate_enabled"] = enabled
    _save_settings_file(saved)
    await ws_manager.broadcast_state(state)
    return {"auto_generate_enabled": state.auto_generate_enabled}


@router.post("/dinner-party")
async def set_dinner_party(enabled: bool):
    """Enable or disable Dinner Party mode (triggerless play for all songs)."""
    state.dinner_party_mode = enabled
    if enabled:
        state.paused = False
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["dinner_party_mode"] = enabled
    _save_settings_file(saved)
    # Re-evaluate triggerless triggers for the current song immediately
    from main import engine
    engine.refresh_triggerless()
    await ws_manager.broadcast_state(state)
    return {"dinner_party_mode": enabled}


@router.post("/display-mode")
async def set_display_mode(mode: str):
    """Set the GLOBAL Dark/Light display mode (TopBar toggle — top of the
    cascade). mode: "default" | "dark" | "light". "default" defers to the
    lower levels (trigger → scene group → scene → set_color → color cards).

    Applying is two-step: sync the per-virtual LedFX dark locks for the newly
    resolved mode (locking force-blacks backgrounds instantly), then re-fire
    the last Color Set in the background so light/default backgrounds come
    back without waiting for the next trigger."""
    if mode not in ("default", "dark", "light"):
        return {"error": f"invalid mode '{mode}'"}
    state.display_mode = mode
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["display_mode"] = mode
    _save_settings_file(saved)

    from services import display_mode as dm
    group_mode, scene_mode = dm.group_and_scene_modes()
    resolved = dm.resolve(mode, group_mode, scene_mode)

    async def _apply():
        await dm.sync_dark_locks(resolved)
        # Restore/repaint backgrounds by re-applying the current colors.
        # Prefer the last Color GROUP with advance=0 (stay on the current
        # member) so its per-device override layer is included; fall back to
        # the bare member set.
        card_id = state.last_color_group_id or state.last_color_set_id
        if resolved != "dark" and card_id:
            try:
                from main import engine
                await engine.fire_color_set_now(card_id, advance=0)
            except Exception:
                logger.exception("display-mode: color re-fire failed")
    asyncio.create_task(_apply())

    await ws_manager.broadcast_state(state)
    return {"display_mode": mode, "display_mode_resolved": resolved}


@router.post("/ambient-mode")
async def set_ambient_mode(enabled: bool, groups: str | None = None,
                           transition_s: float | None = None,
                           catchup_s: float | None = None):
    """Enable/disable Ambient Mode: freeze Hue groups in LedFX (stop their
    entertainment stream) and hold them at a static full-brightness color via
    Hue REST. HA-callable, same shape as /dinner-party and /pause.

    `groups`: comma-separated Hue group ids (LedFX device ids — see
    GET /control/ambient-groups). enabled=true ADDS them to the held set,
    enabled=false REMOVES them; omitted = all groups on / all off.
    `transition_s`: one-shot override of settings.ambient_transition_s for the
    bridge-side fade (turn-on ramp / turn-off fade toward the wake color).
    `catchup_s`: one-shot override of settings.ambient_catchup_s — how long the
    released groups take to ease from the wake look back to the current music
    look (0 = jump at the next trigger, the old behavior).

    The actual Hue work (freeze + REST light writes + fade) runs in a
    BACKGROUND task: freezing awaits the bridge stream-stop, the REST writes
    hit two bridges, and the off-fade sleeps for the transition — awaiting it
    here would hang the toggle. The task is serialized by a lock in
    ambient_mode, so rapid toggles can't overlap. The endpoint returns
    immediately; lights follow within a few seconds."""
    import asyncio
    from services import ambient_mode

    want: set[str] | None
    if groups is not None and groups.strip():
        ids = {g.strip() for g in groups.split(",") if g.strip()}
        known = await ambient_mode.resolve_groups()
        unknown = sorted(ids - set(known))
        ids &= set(known)
        if unknown and not ids:
            raise HTTPException(
                404,
                f"Unknown ambient group(s): {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(known))}",
            )
        current = set(state.ambient_groups)
        want = (current | ids) if enabled else (current - ids)
    else:
        unknown = []
        want = None if enabled else set()

    # Optimistic state for instant UI feedback + persist the intent so a crash
    # mid-apply restores it; set_groups() re-commits the resolved truth
    # (including the want=None → all-groups expansion) when it finishes.
    state.ambient_mode_enabled = enabled if want is None else bool(want)
    if want is not None:
        state.ambient_groups = sorted(want)
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["ambient_mode_enabled"] = state.ambient_mode_enabled
    saved["ambient_groups"] = state.ambient_groups if want is not None else []
    _save_settings_file(saved)

    asyncio.create_task(ambient_mode.set_groups(want, transition_s, catchup_s))
    await ws_manager.broadcast_state(state)
    return {
        "ambient_mode_enabled": state.ambient_mode_enabled,
        "ambient_groups": "all" if (want is None) else sorted(want),
        "unknown_groups": unknown,
        "status": "applying",
    }


@router.get("/ambient-groups")
async def ambient_groups():
    """Hue groups Ambient Mode can hold (from the target category), with their
    current held state — feeds the long-press group picker and HA discovery."""
    from config import settings
    from services import ambient_mode
    known = await ambient_mode.resolve_groups()
    active = set(state.ambient_groups)
    return {
        "groups": [
            {"id": did, "name": name, "ambient": did in active}
            for did, name in sorted(known.items())
        ],
        "transition_s": settings.ambient_transition_s,
    }


@router.get("/active-triggers")
async def active_triggers():
    """Return the engine's currently active trigger list if it's non-user triggers.
    Returns the triggers + a source label so the frontend knows what's playing."""
    from main import engine
    if engine._triggerless_triggers is not None:
        return {"source": "triggerless", "triggers": [t.model_dump() for t in engine._triggerless_triggers]}
    if state.analyzed_trigger_override and engine._analyzed_triggers:
        return {"source": "analyzed_override", "triggers": [t.model_dump() for t in engine._analyzed_triggers]}
    # User-defined triggers, honouring active Set List override. The frontend
    # already has profile.triggers (the default list) on hand from the WS
    # state broadcast — but when a Set List has its own override on this
    # song, the engine fires THOSE timestamps, not the default ones. Without
    # this branch the Now Playing markers showed default trigger positions
    # while triggers fired at setlist positions, looking like every trigger
    # was "early" (or late) by the position delta.
    sl_id = state.active_setlist_id
    if (engine._profile and sl_id
            and engine._profile.setlist_triggers.get(sl_id)
            and any(t.enabled for t in engine._profile.setlist_triggers[sl_id])):
        return {
            "source": "setlist",
            "setlist_id": sl_id,
            "triggers": [t.model_dump() for t in engine._profile.setlist_triggers[sl_id]],
        }
    if engine._profile and any(t.enabled for t in engine._profile.triggers):
        return {"source": "user", "triggers": []}  # user triggers — frontend already has them
    if state.use_analyzed_triggerless and engine._analyzed_triggers:
        return {"source": "analyzed", "triggers": [t.model_dump() for t in engine._analyzed_triggers]}
    return {"source": "none", "triggers": []}
