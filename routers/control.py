"""
SpotFX — Service control router.

Endpoints:
  POST /api/control/pause   — pause trigger firing (HA webhook compatible)
  POST /api/control/resume  — resume trigger firing
  GET  /api/control/status  — current pause state + LedFX latency
"""
from fastapi import APIRouter, HTTPException

from api.home_assistant import pause_service, resume_service
from api.ledfx_client import get_scenes, get_config
from models.state import state
from services.websocket_manager import ws_manager

router = APIRouter(prefix="/api/control", tags=["control"])


@router.post("/pause")
async def pause():
    pause_service()
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
    resume_service()
    return {"paused": False}


@router.get("/status")
async def status():
    return {
        "paused": state.paused,
        "ledfx_rtt_ms": round(state.ledfx_rtt_ms, 1),
        "dinner_party_mode": state.dinner_party_mode,
    }


@router.get("/ledfx/scenes")
async def ledfx_scenes():
    """Proxy: list available LedFX scenes for the UI."""
    return await get_scenes()


@router.post("/reroll")
async def reroll_trigger(trigger_id: str):
    """Re-roll the pre-selected action for the upcoming trigger."""
    from main import engine
    ok = await engine.reroll(trigger_id)
    if not ok:
        raise HTTPException(400, "Cannot re-roll: trigger not found, locked, or not a single-action event")
    return {"ok": True}


@router.post("/use-ai-triggers")
async def set_use_ai_triggers(enabled: bool):
    """Enable or disable using unreviewed AI suggestion set triggers for the current song."""
    state.use_unreviewed_ai_triggers = enabled
    await ws_manager.broadcast_state(state)
    return {"use_unreviewed_ai_triggers": enabled}


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
        engine._pre_ramp_fired.clear()
    await ws_manager.broadcast_state(state)
    return {"analyzed_trigger_override": enabled, "has_analyzed": engine._analyzed_triggers is not None,
            "count": len(engine._analyzed_triggers) if engine._analyzed_triggers else 0}


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
        resume_service()
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["dinner_party_mode"] = enabled
    _save_settings_file(saved)
    # Re-evaluate triggerless triggers for the current song immediately
    from main import engine
    engine.refresh_triggerless()
    await ws_manager.broadcast_state(state)
    return {"dinner_party_mode": enabled}


@router.get("/active-triggers")
async def active_triggers():
    """Return the engine's currently active trigger list if it's non-user triggers.
    Returns the triggers + a source label so the frontend knows what's playing."""
    from main import engine
    if engine._triggerless_triggers is not None:
        return {"source": "triggerless", "triggers": [t.model_dump() for t in engine._triggerless_triggers]}
    if state.analyzed_trigger_override and engine._analyzed_triggers:
        return {"source": "analyzed_override", "triggers": [t.model_dump() for t in engine._analyzed_triggers]}
    if engine._profile and any(t.enabled for t in engine._profile.triggers):
        return {"source": "user", "triggers": []}  # user triggers — frontend already has them
    if state.use_analyzed_triggerless and engine._analyzed_triggers:
        return {"source": "analyzed", "triggers": [t.model_dump() for t in engine._analyzed_triggers]}
    return {"source": "none", "triggers": []}


@router.get("/ledfx/probe")
async def ledfx_probe():
    """
    Diagnostic endpoint: returns LedFX global config + cached virtual states.
    Use this to verify API connectivity and confirm field names before relying
    on them in action execution.
    """
    return {
        "config":   await get_config(),
        "virtuals": state.ledfx_virtual_cache,
    }
