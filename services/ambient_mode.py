"""
SpotFX — Ambient Mode.

A front-page / Home-Assistant toggle that switches a chosen device category to a
static, full-brightness color (or white temperature) and removes those devices
from music-reactive triggers.

Why this exists
---------------
Philips Hue's Entertainment *streaming* API (what LedFX uses for low-latency
music reactivity) caps brightness well below a normal static scene and mixes the
color LEDs for white, so streamed white never reaches full output. The Hue
*REST* API does — `dimming.brightness=100` with a `color_temperature` drives the
bulbs' dedicated white LEDs at full lumens.

So Ambient Mode, for each Hue device in the target category:
  1. excludes the virtual from the trigger engine (ledfx_client.set_ambient_excluded),
  2. clears its LedFX effect + stops the entertainment stream (so REST state sticks),
  3. PUTs every light in the entertainment group to the configured color at full
     brightness over the Hue REST API.

Bridge credentials (ip / app-key / entertainment id) are read live from the
LedFX Hue device config — SpotFX stores no Hue secrets of its own.

Non-Hue devices in the category are left on their normal reactive path (logged).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from api import ledfx_client
from config import settings
from services.device_category_service import get_category, get_category_by_name

logger = logging.getLogger(__name__)

# Cache of resolved light resource-ids per (bridge_ip, entertainment_id).
# The mapping rarely changes; cleared implicitly on process restart.
_light_cache: dict[tuple[str, str], list[str]] = {}

# Serializes enable/disable so rapid front-page (or HA) toggles can't overlap
# and fight each other over the Hue stream. Created lazily to bind to the loop.
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


# ── Color math ───────────────────────────────────────────────────────────────

def _gamma(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _hex_to_xy(hex_color: str) -> tuple[float, float]:
    """Hex RGB -> CIE xy chromaticity (Philips Wide-gamut D65 matrix)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except (ValueError, IndexError):
        return 0.3127, 0.3290  # fall back to D65 white
    r, g, b = _gamma(r), _gamma(g), _gamma(b)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = X + Y + Z
    if total == 0:
        return 0.3127, 0.3290
    return X / total, Y / total


def _light_payload() -> dict:
    """Build the Hue REST light state from current settings (full-brightness)."""
    bri = max(1, min(100, int(settings.ambient_brightness)))
    body: dict = {"on": {"on": True}, "dimming": {"brightness": float(bri)}}
    if settings.ambient_color_mode == "color":
        x, y = _hex_to_xy(settings.ambient_color)
        body["color"] = {"xy": {"x": round(x, 4), "y": round(y, 4)}}
    else:
        kelvin = max(2000, min(6500, int(settings.ambient_kelvin)))
        mirek = max(153, min(500, round(1_000_000 / kelvin)))
        body["color_temperature"] = {"mirek": mirek}
    return body


# ── Target resolution ──────────────────────────────────────────────────────────

def _target_virtuals() -> list[str]:
    """Virtual ids of the configured target category (by id, then by name)."""
    key = (settings.ambient_target_category or "").strip()
    if not key:
        return []
    cat = get_category(key) or get_category_by_name(key)
    return list(cat.virtuals) if cat else []


async def _hue_cfg(device_id: str) -> dict | None:
    """Return the LedFX Hue device config for a device id, or None if not Hue."""
    rec = await ledfx_client.get_device(device_id)
    rec = rec.get(device_id, rec) if isinstance(rec, dict) else {}
    cfg = rec.get("config", rec) if isinstance(rec, dict) else {}
    if cfg.get("entertainment_id") and cfg.get("ip_address") and cfg.get("username"):
        return cfg
    return None


async def _all_virtuals() -> dict:
    # force=True: must read topology even during an audio capture, else segment
    # discovery misses driving virtuals (e.g. single-color-effect) and they keep
    # streaming over the REST-set bulbs.
    raw = await ledfx_client.get_all_virtuals(force=True)
    return raw.get("virtuals", raw) if isinstance(raw, dict) else {}


def _segment_devices(vobj: dict) -> set[str]:
    """Device ids referenced by a virtual's segments ([device_id, start, end, ...])."""
    devs: set[str] = set()
    for seg in (vobj.get("segments") or []):
        if isinstance(seg, (list, tuple)) and seg:
            devs.add(seg[0])
    return devs


def _persist_deactivated(vids: list) -> None:
    """Persist which virtuals ambient parked, so a SpotFX restart (while ambient
    is on) can still reactivate the right ones when ambient is later turned off."""
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["ambient_deactivated"] = list(vids)
    _save_settings_file(saved)


# ── Hue bridge REST ──────────────────────────────────────────────────────────

def _bridge_client(cfg: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"https://{cfg['ip_address']}",
        headers={"hue-application-key": cfg["username"]},
        verify=False,  # bridge uses a self-signed cert
        timeout=4.0,
    )


async def _resolve_lights(cfg: dict) -> list[str]:
    """Map the entertainment group's channels to Hue light resource ids (cached)."""
    cache_key = (cfg["ip_address"], cfg["entertainment_id"])
    if cache_key in _light_cache:
        return _light_cache[cache_key]
    rids: list[str] = []
    try:
        async with _bridge_client(cfg) as client:
            ent = (await client.get("/clip/v2/resource/entertainment")).json()["data"]
            ent_owner = {e["id"]: e["owner"]["rid"] for e in ent}
            lights = (await client.get("/clip/v2/resource/light")).json()["data"]
            dev_light = {l["owner"]["rid"]: l["id"] for l in lights}
            ec = (await client.get(
                f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}"
            )).json()["data"][0]
            seen: set[str] = set()
            for channel in ec.get("channels", []):
                for member in channel.get("members", []):
                    svc = member.get("service", {})
                    if svc.get("rtype") == "entertainment":
                        lr = dev_light.get(ent_owner.get(svc.get("rid")))
                        if lr and lr not in seen:
                            seen.add(lr)
                            rids.append(lr)
                        break
    except Exception as exc:
        logger.error("Ambient: failed to resolve Hue lights for %s: %r", cfg.get("ip_address"), exc)
        return []
    _light_cache[cache_key] = rids
    return rids


async def _apply_hue(cfg: dict) -> int:
    """Set every light in the group to the static color via REST.
    Returns the number of lights set.

    The entertainment stream is NOT stopped here: callers deactivate the LedFX
    virtuals first, so LedFX itself tears the stream down. Sending our own
    'action stop' directly to the bridge while LedFX still owns the session
    raced LedFX's Hue socket and could wedge its (synchronous) flush — so we
    leave stream lifecycle entirely to LedFX."""
    body = _light_payload()
    try:
        async with _bridge_client(cfg) as client:
            lights = await _resolve_lights(cfg)
            count = 0
            for rid in lights:
                resp = await client.put(f"/clip/v2/resource/light/{rid}", json=body)
                if resp.status_code < 400:
                    count += 1
            return count
    except Exception as exc:
        logger.error("Ambient: failed to apply Hue REST state on %s: %r", cfg.get("ip_address"), exc)
        return 0


# ── Public API ───────────────────────────────────────────────────────────────

async def enable() -> dict:
    """Locked wrapper around _enable_impl (serializes with disable)."""
    async with _get_lock():
        return await _enable_impl()


async def disable() -> dict:
    """Locked wrapper around _disable_impl (serializes with enable)."""
    async with _get_lock():
        return await _disable_impl()


async def _enable_impl() -> dict:
    """Activate ambient mode.

    From the target category's virtuals we resolve the underlying Hue *devices*
    (via segments), then auto-discover EVERY virtual that streams to those
    devices — including spanning virtuals like 'single-color-effect' that the
    user didn't pick directly. All of those are parked (deactivated, effect
    preserved) + excluded from triggers (so nothing re-dims the bulbs), then
    each Hue device is set to the static full-brightness color over REST."""
    vids = _target_virtuals()
    all_v = await _all_virtuals()

    # 1) Resolve target Hue device ids from the chosen virtuals' segments.
    target_devices: set[str] = set()
    for vid in vids:
        vobj = all_v.get(vid, {})
        target_devices |= _segment_devices(vobj)
        target_devices.add(vid)  # device-backed virtual references itself
    hue_cfgs: dict[str, dict] = {}
    for did in target_devices:
        cfg = await _hue_cfg(did)
        if cfg:
            hue_cfgs[did] = cfg
    hue_device_ids = set(hue_cfgs)

    # 2) Auto-discover every virtual that drives any target Hue device.
    driving: set[str] = set(vids) | hue_device_ids
    for v_id, vobj in all_v.items():
        if _segment_devices(vobj) & hue_device_ids:
            driving.add(v_id)

    # 3) Exclude ALL driving virtuals from triggers FIRST (so nothing re-drives
    #    the bulbs), then PARK only the ones that are CURRENTLY ACTIVE by
    #    deactivating them (active=false). Parking preserves their effect, so
    #    turning ambient off resumes exactly what was showing. We record only the
    #    ones we actually parked, so disable() won't wrongly activate virtuals
    #    that were already idle (e.g. unused device-virtuals).
    from models.state import state
    driving_list = sorted(driving)
    ledfx_client.set_ambient_excluded(driving_list)
    to_park = [v for v in driving_list if (all_v.get(v) or {}).get("active")]
    for v_id in to_park:
        await ledfx_client.set_virtual_active(v_id, False)
    state.ambient_deactivated = to_park
    _persist_deactivated(to_park)

    # 5) Set every target Hue device to the static color at full brightness.
    total_lights = 0
    for cfg in hue_cfgs.values():
        total_lights += await _apply_hue(cfg)

    if not hue_device_ids:
        logger.warning("Ambient: no Hue devices resolved from category %r", settings.ambient_target_category)
    logger.info(
        "Ambient ENABLED: %d Hue device(s), %d driving virtual(s) parked, %d light(s) set.",
        len(hue_device_ids), len(to_park), total_lights,
    )
    return {
        "hue_devices": sorted(hue_device_ids),
        "stopped_virtuals": driving_list,
        "lights_set": total_lights,
    }


async def _disable_impl() -> dict:
    """Deactivate ambient mode: re-include virtuals in triggers and REACTIVATE
    the virtuals we parked, so each resumes the exact effect it was showing
    before ambient took over — no waiting for the next trigger."""
    from models.state import state
    # Re-include in triggers first so reactivation isn't fought by the guard.
    ledfx_client.set_ambient_excluded([])
    parked = list(state.ambient_deactivated or [])
    for v_id in parked:
        # Best-effort: the call may time out on the slow Hue handshake, but LedFX
        # completes the activation server-side regardless, so we don't gate on it.
        await ledfx_client.set_virtual_active(v_id, True)
    state.ambient_deactivated = []
    _persist_deactivated([])
    logger.info("Ambient DISABLED: requested reactivation of %d virtual(s): %s", len(parked), parked)
    return {"status": "disabled", "reactivated": parked}


async def reapply() -> dict:
    """Re-run enable() if ambient mode is currently active (e.g. settings changed)."""
    from models.state import state
    if state.ambient_mode_enabled:
        return await enable()
    return {"status": "inactive"}


async def selfheal() -> dict:
    """Recover from an unclean shutdown. If SpotFX restarted (e.g. a dev auto-
    reload) while ambient was ON, it may have died before disable() reactivated
    the parked virtuals — leaving them stuck active=false with ambient now off.
    Reactivate any stale parked virtuals and clear the list."""
    from models.state import state
    vids = list(state.ambient_deactivated or [])
    if state.ambient_mode_enabled or not vids:
        return {"status": "noop"}
    healed = 0
    for v_id in vids:
        if await ledfx_client.set_virtual_active(v_id, True):
            healed += 1
    state.ambient_deactivated = []
    _persist_deactivated([])
    logger.info("Ambient self-heal: reactivated %d stale parked virtual(s): %s", healed, vids)
    return {"status": "healed", "reactivated": healed}
