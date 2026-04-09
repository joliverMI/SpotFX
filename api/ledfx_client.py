"""
SpotFX — LedFX REST API client.

Responsibilities:
  - Fire scenes / effect commands
  - Measure round-trip latency to LedFX (used for trigger timing offset)
  - List available scenes (for the UI music event builder)
  - Read / write virtual effect configs and global settings
  - Poll key virtual states every 5 s (cached in state.ledfx_virtual_cache)

Command bus
-----------
set_virtual_effect and set_config queue into an 8 ms coalesce window.
Within the window, patches for the same (virtual, effect_type) key are merged
(newer keys overwrite older), then all pending updates fire simultaneously via
asyncio.gather. This means two concurrent ramps on the same virtual produce one
HTTP request per step instead of two, and near-simultaneous instant commands
targeting the same virtual are merged atomically.

Anything that does not benefit from merging (trigger_scene, set_virtual_config,
all reads) calls the internal _direct variants and bypasses the bus.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

import httpx

from config import settings
from models.state import state

logger = logging.getLogger(__name__)

# Shared async client (reuse connections)
_client: Optional[httpx.AsyncClient] = None

# Cached global brightness — updated whenever we set it so ramps start from the right value
_current_brightness: float = 1.0

# ── Command bus ────────────────────────────────────────────────────────────────
_effect_bus: dict[tuple, dict] = {}   # (virtual_id, effect_type) → merged config patch
_config_bus: dict = {}                # global config patch (global_brightness, etc.)
_bus_task: Optional[asyncio.Task] = None
BUS_WINDOW_MS = 8  # coalesce window; must be << ramp step_ms (25 ms)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.ledfx_url,
            timeout=2.0,
        )
    return _client


# ── Internal direct-fire helpers (bypass bus) ─────────────────────────────────

async def _set_virtual_effect_direct(virtual_id: str, effect_type: str, config: dict) -> bool:
    client = _get_client()
    try:
        resp = await client.put(
            f"/api/virtuals/{virtual_id}/effects",
            json={"type": effect_type, "config": config},
        )
        logger.debug(
            "LedFX PUT /api/virtuals/%s/effects (type=%s) → %d: %s",
            virtual_id, effect_type, resp.status_code, resp.text[:300],
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Failed to patch LedFX virtual '%s' effect: %s", virtual_id, exc)
        return False


async def _set_config_direct(patch: dict) -> bool:
    client = _get_client()
    try:
        resp = await client.put("/api/config", json=patch)
        logger.debug("LedFX PUT /api/config → %d: %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Failed to update LedFX config %s: %s", patch, exc)
        return False


# ── Bus flush ─────────────────────────────────────────────────────────────────

async def _flush_bus() -> None:
    global _bus_task
    await asyncio.sleep(BUS_WINDOW_MS / 1000)
    effect_snap = dict(_effect_bus)
    config_snap = dict(_config_bus)
    _effect_bus.clear()
    _config_bus.clear()
    _bus_task = None
    coros = [
        _set_virtual_effect_direct(vid, etype, patch)
        for (vid, etype), patch in effect_snap.items()
    ]
    if config_snap:
        coros.append(_set_config_direct(config_snap))
    if coros:
        await asyncio.gather(*coros)


def _schedule_bus_flush() -> None:
    global _bus_task
    if _bus_task is None or _bus_task.done():
        _bus_task = asyncio.create_task(_flush_bus())


# ── Public write API (goes through bus) ───────────────────────────────────────

async def set_virtual_effect(virtual_id: str, effect_type: str, config: dict) -> None:
    """
    Queue a virtual effect patch into the coalesce bus.
    Patches for the same (virtual_id, effect_type) within the bus window are merged;
    later keys overwrite earlier ones.
    """
    key = (virtual_id, effect_type)
    _effect_bus[key] = {**_effect_bus.get(key, {}), **config}
    _schedule_bus_flush()


async def set_config(patch: dict) -> None:
    """
    Queue a global config patch into the coalesce bus.
    Multiple patches within the bus window are merged; later keys overwrite earlier.
    """
    global _current_brightness
    if "global_brightness" in patch:
        _current_brightness = patch["global_brightness"]
    _config_bus.update(patch)
    _schedule_bus_flush()


# ── Other API calls (bypass bus) ──────────────────────────────────────────────

async def measure_latency() -> float:
    """
    Send a lightweight status request to LedFX and return the RTT in ms.
    Updates state.ledfx_rtt_ms.
    """
    client = _get_client()
    try:
        t0 = time.monotonic()
        await client.get("/api/info")
        rtt_ms = (time.monotonic() - t0) * 1000
        state.ledfx_rtt_ms = rtt_ms
        return rtt_ms
    except Exception as exc:
        logger.warning("LedFX latency probe failed: %s", exc)
        return 0.0


async def trigger_scene(scene_id: str) -> bool:
    """
    Activate a LedFX scene by its scene_id.
    Returns True on success.
    """
    client = _get_client()
    try:
        resp = await client.put(
            "/api/scenes",
            json={"id": scene_id, "action": "activate"},
        )
        resp.raise_for_status()
        logger.info("LedFX scene triggered: %s", scene_id)
        return True
    except Exception as exc:
        logger.error("Failed to trigger LedFX scene '%s': %s", scene_id, exc)
        return False


async def get_scenes() -> list[dict]:
    """
    Fetch the list of available LedFX scenes.
    Returns an empty list if LedFX is unreachable.
    """
    client = _get_client()
    try:
        resp = await client.get("/api/scenes")
        resp.raise_for_status()
        data = resp.json()
        scenes_dict = data.get("scenes", {})
        return [{"id": sid, **meta} for sid, meta in scenes_dict.items()]
    except Exception as exc:
        logger.warning("Could not fetch LedFX scenes: %s", exc)
        return []


async def get_config() -> dict:
    """Fetch LedFX global config (GET /api/config). Returns {} on failure."""
    client = _get_client()
    try:
        resp = await client.get("/api/config")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Could not fetch LedFX config: %s", exc)
        return {}


async def get_virtual(virtual_id: str) -> dict:
    """Fetch a single LedFX virtual's current state. Returns {} on failure."""
    client = _get_client()
    try:
        resp = await client.get(f"/api/virtuals/{virtual_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Could not fetch LedFX virtual '%s': %s", virtual_id, exc)
        return {}


async def get_all_virtuals() -> dict:
    """Fetch all LedFX virtuals. Returns {} on failure."""
    client = _get_client()
    try:
        resp = await client.get("/api/virtuals")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Could not fetch LedFX virtuals: %s", exc)
        return {}


async def set_virtual_config(virtual_id: str, config: dict) -> bool:
    """
    Patch a virtual's device config (max_brightness, transition_time, etc.).
    POST /api/virtuals  body: {"id": virtual_id, "config": config}
    This merges with the existing virtual config — only specified fields are changed.
    """
    client = _get_client()
    try:
        resp = await client.post(
            "/api/virtuals",
            json={"id": virtual_id, "config": config},
        )
        logger.debug(
            "LedFX POST /api/virtuals (id=%s) → %d: %s",
            virtual_id, resp.status_code, resp.text[:300],
        )
        resp.raise_for_status()
        logger.debug("LedFX virtual config patched on '%s': %s", virtual_id, config)
        return True
    except Exception as exc:
        logger.error("Failed to patch LedFX virtual '%s' config: %s", virtual_id, exc)
        return False


def get_virtual_cache(virtual_id: str) -> dict:
    """Return the cached virtual state dict (from the last poll). Empty dict if not cached."""
    return state.ledfx_virtual_cache.get(virtual_id, {})


def get_cached_param(virtual_id: str, param_name: str) -> float | None:
    """Return a numeric effect param from the polled cache, or None if not found."""
    cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    val = cfg.get(param_name)
    return float(val) if val is not None else None


# ── Ramp functions (go through bus; step_ms=25 → 40 fps) ─────────────────────

async def ramp_brightness(target: float, ramp_ms: int, step_ms: int = 25) -> None:
    """Smoothly ramp global brightness from _current_brightness to target over ramp_ms."""
    start = _current_brightness
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        val = round(start + (target - start) * (i / steps), 4)
        await set_config({"global_brightness": val})
        if i < steps:
            await asyncio.sleep(step_ms / 1000)


async def ramp_effect_params(
    virtual_id: str, effect_type: str, patch: dict, ramp_ms: int, step_ms: int = 25
) -> None:
    """Smoothly ramp one or more effect params from their cached values to targets over ramp_ms.

    patch: {param_name: target_value, ...}
    Each step sends a single batched set_virtual_effect call with all interpolated values.
    """
    starts = {p: (get_cached_param(virtual_id, p) or 0.0) for p in patch}
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        t = i / steps
        frame = {p: round(starts[p] + (patch[p] - starts[p]) * t, 4) for p in patch}
        await set_virtual_effect(virtual_id, effect_type, frame)
        if i < steps:
            await asyncio.sleep(step_ms / 1000)
    # Update cache with final values after ramp completes
    effect_cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    effect_cfg.update(patch)


async def ramp_gradient_params(
    virtual_id: str, effect_type: str, patch: dict, ramp_ms: int, step_ms: int = 25
) -> None:
    """Smoothly interpolate gradient/color string params from their cached values to targets.

    patch: {param_name: target_css_string, ...}
    Uses gradient_interpolation.interpolate_gradient() for each step.
    """
    from services.gradient_interpolation import interpolate_gradient
    cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    starts = {p: (cfg.get(p) or "") for p in patch}
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        t = i / steps
        frame = {p: interpolate_gradient(starts[p], patch[p], t) for p in patch}
        await set_virtual_effect(virtual_id, effect_type, frame)
        if i < steps:
            await asyncio.sleep(step_ms / 1000)
    # Update cache with final values after ramp completes
    effect_cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    effect_cfg.update(patch)


async def ramp_polar_offset(
    virtual_id: str, effect_type: str,
    target_angle: float, target_radius: float,
    ramp_ms: int, step_ms: int = 25,
) -> None:
    """Interpolate x_offset+y_offset in polar space.

    target_angle: degrees, 0=top (y=1,x=0), clockwise.
    target_radius: 0..1 in frontend space (0=centre, 1=edge in -1..1 coords).
    Shortest angular path is always taken.
    """
    import math as _math
    _cx = get_cached_param(virtual_id, "x_offset")
    _cy = get_cached_param(virtual_id, "y_offset")
    cur_x_l = _cx if _cx is not None else 0.5
    cur_y_l = _cy if _cy is not None else 0.5
    cx = (cur_x_l - 0.5) * 2   # convert to frontend -1..1
    cy = (cur_y_l - 0.5) * 2
    cur_r = _math.sqrt(cx ** 2 + cy ** 2)
    cur_a = _math.degrees(_math.atan2(cx, cy))  # atan2(x,y) → 0=top, CW positive
    delta = ((target_angle - cur_a) + 180) % 360 - 180  # shortest angular path
    steps = max(1, ramp_ms // step_ms)
    for i in range(1, steps + 1):
        t = i / steps
        a_rad = _math.radians(cur_a + delta * t)
        r = cur_r + (target_radius - cur_r) * t
        x_l = round(_math.sin(a_rad) * r / 2 + 0.5, 4)
        y_l = round(_math.cos(a_rad) * r / 2 + 0.5, 4)
        await set_virtual_effect(virtual_id, effect_type, {"x_offset": x_l, "y_offset": y_l})
        if i < steps:
            await asyncio.sleep(step_ms / 1000)
    # Update cache with final values
    cfg = state.ledfx_virtual_cache.get(virtual_id, {}).get("effect", {}).get("config", {})
    a_final = _math.radians(cur_a + delta)
    cfg["x_offset"] = round(_math.sin(a_final) * target_radius / 2 + 0.5, 4)
    cfg["y_offset"] = round(_math.cos(a_final) * target_radius / 2 + 0.5, 4)


# ── Virtual state poller ───────────────────────────────────────────────────────

def _get_polled_virtuals() -> list[str]:
    """Return virtual IDs to poll, from device categories."""
    from services import effect_params
    return effect_params.get_all_virtual_ids()


async def poll_virtual_states() -> None:
    """Poll key LedFX virtuals every 5 s and cache results in state."""
    while True:
        for vid in _get_polled_virtuals():
            data = await get_virtual(vid)
            if data:
                state.ledfx_virtual_cache[vid] = data.get(vid, data)
        await asyncio.sleep(5)


async def latency_loop() -> None:
    """Periodically re-measure LedFX latency every 30 seconds."""
    while True:
        await measure_latency()
        await asyncio.sleep(30)
