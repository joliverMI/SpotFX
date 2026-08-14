"""SPECTRA's own Ambient Mode — the behaviour behind the room bar's Ambient
checkbox (spectra.services.room_controls.RoomControlState.ambient_enabled /
ambient_color), which until now only recorded the switch.

The legacy world (services/ambient_mode.py) is the spec for what "ambient"
MEANS: a calm takeover of the Hue devices in the room — freeze each Hue
device's entertainment (DTLS) stream so its bridge reverts to normal
REST-controlled mode, then PUT every light in that stream to a static,
full-brightness colour directly over the bridge's own REST API. Non-Hue
devices (WLED etc.) are left running their normal reactive show, same as
legacy — the Entertainment-API brightness cap this sidesteps is a Hue-only
problem.

Two things are simpler here than in the legacy world, both because SPECTRA
drives her devices in-process (live_host.live) instead of through a remote
LedFX HTTP API:

  - No device-category setting to resolve a target from — every live Hue
    device in the room (live_host.live.host.devices, type "hue") is held.
    Matches "a calm takeover of THE ROOM" literally, and keeps this off the
    settings-form the room-controls surface deliberately avoids.
  - No "wake scene" on disable. Legacy needed one because freezing a LedFX
    virtual could leave it inactive, so re-arming the stream needed a fresh
    scene fire to put a real effect back on it. A SPECTRA-owned Hue virtual
    never goes inactive while frozen — set_frozen() only mutes this
    device's OWN flush(); the virtual keeps rendering the room's live scene
    the whole time (fx/devices/hue.py's own docstring) — so unfreezing
    alone is enough for the stream to pick back up wherever the scene
    already is. A short REST-only brightness fade still runs first (no
    colour target, since there's no "next scene" to fade toward) purely so
    the handoff isn't a hard cut from white to whatever the effect is
    currently outputting.

Freeze/REST calls go through the live HueDevice's own `_hue_request` — its
only REST surface, no public wrapper exists — off the event loop via
run_in_executor, same as the class's own internal blocking calls. Bridge
credentials come from the device's public `.config` property
(fx/utils.py BaseRegistry.config, backed by the same dict `_hue_request`
itself reads).

State-only when SPECTRA doesn't own the live stack (dark, or spot-effects
owns) — reconcile() no-ops and reports "dark" rather than raising, so
saving the control never fails even when there's nothing to drive.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Legacy defaults (services/ambient_mode.py's settings.ambient_transition_s /
# ambient_fade_brightness) — internal timing, not a room-control the Admiral
# tunes per song, so these stay constants rather than growing the settings
# surface.
AMBIENT_BRIGHTNESS_PCT = 100
AMBIENT_TRANSITION_MS = 1500
AMBIENT_OFF_FADE_PCT = 35

_lock: Optional[asyncio.Lock] = None
# {(ip_address, entertainment_id): [light resource id, ...]}
_light_cache: dict[tuple[str, str], list[str]] = {}


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


# ── colour math (Philips Wide-gamut D65 matrix — ported from
#    services/ambient_mode.py, unchanged) ────────────────────────────────────

def _gamma(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _hex_to_xy(hex_color: str) -> tuple[float, float]:
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


def _light_payload(color_hex: str, ramp_ms: Optional[int] = None) -> dict:
    x, y = _hex_to_xy(color_hex)
    body: dict = {
        "on": {"on": True},
        "dimming": {"brightness": float(AMBIENT_BRIGHTNESS_PCT)},
        "color": {"xy": {"x": round(x, 4), "y": round(y, 4)}},
    }
    if ramp_ms and ramp_ms > 0:
        body["dynamics"] = {"duration": int(ramp_ms)}
    return body


def _fade_dim_payload(brightness_pct: int, ramp_ms: int) -> dict:
    """Brightness-only fade (no colour target — see module docstring on why
    disable has no 'wake colour' to fade toward)."""
    return {
        "on": {"on": True},
        "dimming": {"brightness": float(max(1, min(100, brightness_pct)))},
        "dynamics": {"duration": int(ramp_ms)},
    }


# ── bridge REST, via the live device's own request surface ─────────────────

async def _hue_call(dev: Any, method: str, endpoint: str, data: Optional[dict] = None) -> dict:
    loop = asyncio.get_running_loop()
    body, _headers = await loop.run_in_executor(
        None, dev._hue_request, method, endpoint, data, True)
    return body


async def _resolve_lights(dev: Any) -> list[str]:
    """Map the device's entertainment stream to individual Hue `light`
    resource ids, so ambient can PUT each one directly over REST — cached
    per bridge, same as legacy (topology is stable)."""
    cfg = dev.config
    cache_key = (cfg["ip_address"], cfg["entertainment_id"])
    if cache_key in _light_cache:
        return _light_cache[cache_key]
    try:
        ent = (await _hue_call(dev, "GET", "/clip/v2/resource/entertainment"))["data"]
        ent_owner = {e["id"]: e["owner"]["rid"] for e in ent}
        lights = (await _hue_call(dev, "GET", "/clip/v2/resource/light"))["data"]
        dev_light = {l["owner"]["rid"]: l["id"] for l in lights}
        ec = (await _hue_call(
            dev, "GET",
            f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}",
        ))["data"][0]
        rids: list[str] = []
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
    except Exception:
        logger.exception("Ambient: failed to resolve Hue lights for %s",
                         cfg.get("ip_address"))
        return []
    _light_cache[cache_key] = rids
    return rids


async def _apply_hue(dev: Any, body: dict) -> int:
    """PUT `body` to every light this device's entertainment stream covers.
    Best-effort per light — one unreachable bulb must not stop the rest."""
    count = 0
    for rid in await _resolve_lights(dev):
        try:
            await _hue_call(dev, "PUT", f"/clip/v2/resource/light/{rid}", body)
            count += 1
        except Exception:
            logger.exception("Ambient: failed to set light %s on %s",
                             rid, dev.config.get("ip_address"))
    return count


# ── device discovery ─────────────────────────────────────────────────────────

def _hue_devices(host: Any) -> dict[str, Any]:
    return {did: host.devices.get(did) for did in host.devices
            if getattr(host.devices.get(did), "type", None) == "hue"}


# ── public entry point ──────────────────────────────────────────────────────

async def reconcile(enabled: bool, color: Optional[str]) -> dict:
    """Drive the room's live Hue devices toward `enabled` (held at `color`,
    default white) or released. Locked so rapid toggles can't overlap and
    fight each other over a device's stream state. No-ops (status "dark")
    when SPECTRA doesn't currently own the live stack — the room-control
    save must never fail just because there's nothing to drive right now."""
    async with _get_lock():
        return await _reconcile_impl(enabled, color)


async def _reconcile_impl(enabled: bool, color: Optional[str]) -> dict:
    from spectra.services.live_host import live

    if not live.active or live.host is None:
        logger.warning("Ambient: SPECTRA does not own the live stack — "
                       "state saved, no lights touched")
        return {"status": "dark"}

    hue_devices = _hue_devices(live.host)
    if not hue_devices:
        logger.warning("Ambient: no live Hue devices in the room")
        return {"status": "no-hue-devices"}

    touched: list[str] = []
    if enabled:
        body = _light_payload(color or "#ffffff", AMBIENT_TRANSITION_MS)
        lights_set = 0
        for did, dev in sorted(hue_devices.items()):
            try:
                await dev.set_frozen(True)   # must land before the REST write
                lights_set += await _apply_hue(dev, body)
                touched.append(did)
            except Exception:
                logger.exception("Ambient: failed to hold %s at the ambient colour", did)
        logger.info("Ambient ON: %s held at %s, %d light(s) set",
                    touched or "none", color or "#ffffff", lights_set)
        return {"status": "on", "devices": touched, "lights_set": lights_set}

    fade = _fade_dim_payload(AMBIENT_OFF_FADE_PCT, AMBIENT_TRANSITION_MS)
    for did, dev in sorted(hue_devices.items()):
        try:
            await _apply_hue(dev, fade)
        except Exception:
            logger.exception("Ambient: off-fade failed for %s", did)
    if AMBIENT_TRANSITION_MS > 0:
        await asyncio.sleep(AMBIENT_TRANSITION_MS / 1000)
    for did, dev in sorted(hue_devices.items()):
        try:
            await dev.set_frozen(False)  # re-engages the stream; the room's
                                          # live scene resumes on its own
            touched.append(did)
        except Exception:
            logger.exception("Ambient: failed to release %s", did)
    logger.info("Ambient OFF: %s released", touched or "none")
    return {"status": "off", "devices": touched}
