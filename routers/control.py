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
    """Return the engine's currently active trigger list (synthetic triggerless or empty)."""
    from main import engine
    triggers = engine._triggerless_triggers
    if triggers is None:
        return []
    return [t.model_dump() for t in triggers]


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
