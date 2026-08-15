"""SPECTRA's own Ambient Mode — the behaviour behind the room bar's Ambient
checkbox (spectra.services.room_controls.RoomControlState.ambient_enabled /
ambient_color).

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
    already is.

Release (ambient OFF) is a TWO-PHASE bridge-side ramp, matching legacy's
own two-phase off-sequence (fade-toward-landing-colour, then ease toward
the real show) rather than the single fixed-brightness fade this module
shipped with in PR #56 — that shipped version faded to 35% and unfroze
immediately, an abrupt cut the Admiral flagged after living with it
("the spot effects version of transferring from ambient mode to releasing
was way better", 2026-08-14). Legacy's two phases are a REST fade toward
the wake scene's colour (services.ambient_mode._wake_fade_color, over
settings.ambient_transition_s) and, after the stream reconnects, an
LedFX-side effect-config tween from the wake scene's look back to a
CAPTURED pre-ambient look (settings.ambient_catchup_s) — that second phase
has no direct analogue here: SPECTRA's driving virtual never goes dark or
gets replaced by a wake scene, so there is no separate "wake config" to
capture-then-tween-away-from the way legacy's LedFX-side tween needs. What
IS reproducible, and is the same qualitative fix, is easing the HELD BULB
toward whatever the room's live effect is ACTUALLY rendering right now
before handing back control — sourced from the literal live pixel buffer
(Device.assemble_frame(), the exact per-flush frame HueDevice.flush()
already receives and drops while frozen — see fx/devices/hue.py) rather
than a captured scene config, since that buffer is a truer target than any
snapshot legacy could take (SPECTRA's render loop never stopped). Phase 1
(dim fade, AMBIENT_TRANSITION_MS) and phase 2 (catch-up ramp toward the
live look, AMBIENT_CATCHUP_MS) both run over Hue's own bridge-side
`dynamics.duration`, still frozen — the same REST-ramp primitive phase 1
already used, just re-aimed at a live-derived target instead of a fixed
dim. Only once that lands does set_frozen(False) hand back to the stream,
so the jump the stream then picks up from is small. Numbers
(AMBIENT_TRANSITION_MS=1500, AMBIENT_OFF_FADE_PCT=35, AMBIENT_CATCHUP_MS=
8000) are legacy's own shipped defaults (ambient_transition_s=1.5,
ambient_fade_brightness=35, ambient_catchup_s=8.0 in config.py) — not
re-guessed, matched.

Light-state REST calls go over a direct httpx.AsyncClient (same pattern as
spectra/services/ledfx_release.py), not the live HueDevice's own
`_hue_request` — that vendored helper never checks response.status_code
(fx/devices/hue.py:175-186 returns response.json() unconditionally), so a
Hue CLIP v2 4xx error body would silently count as a successful write.
Legacy's own _apply_hue (services/ambient_mode.py) explicitly gates on
`status_code < 400`; raise_for_status() here is that same gate. Bridge
credentials come from the device's public `.config` property
(fx/utils.py BaseRegistry.config). Freezing itself still goes through the
device's own `set_frozen()` — the one call this module doesn't replicate.

State-only when SPECTRA doesn't own the live stack (dark, or spot-effects
owns) — reconcile() no-ops and reports "dark" rather than raising, so
saving the control never fails even when there's nothing to drive.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Legacy defaults (services/ambient_mode.py's settings.ambient_transition_s /
# ambient_fade_brightness / ambient_catchup_s) — internal timing, not a
# room-control the Admiral tunes per song, so these stay constants rather
# than growing the settings surface.
AMBIENT_BRIGHTNESS_PCT = 100
AMBIENT_TRANSITION_MS = 1500
AMBIENT_OFF_FADE_PCT = 35
AMBIENT_CATCHUP_MS = 8000

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


def _light_payload(color_hex: str, ramp_ms: Optional[int] = None,
                   brightness_pct: int = AMBIENT_BRIGHTNESS_PCT) -> dict:
    x, y = _hex_to_xy(color_hex)
    body: dict = {
        "on": {"on": True},
        "dimming": {"brightness": float(max(1, min(100, brightness_pct)))},
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


# ── bridge REST, direct to the bridge (not through LedFX) ──────────────────

_REST_TIMEOUT = httpx.Timeout(connect=3.0, read=4.0, write=4.0, pool=1.0)


def _bridge_client(cfg: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"https://{cfg['ip_address']}",
        headers={"hue-application-key": cfg["username"]},
        verify=False,  # the bridge uses a self-signed cert
        timeout=_REST_TIMEOUT,
    )


async def _hue_get(client: httpx.AsyncClient, endpoint: str) -> dict:
    resp = await client.get(endpoint)
    resp.raise_for_status()
    return resp.json()


async def _hue_put(client: httpx.AsyncClient, endpoint: str, body: dict) -> None:
    resp = await client.put(endpoint, json=body)
    resp.raise_for_status()


async def _resolve_lights(client: httpx.AsyncClient, cfg: dict) -> list[str]:
    """Map the device's entertainment stream to individual Hue `light`
    resource ids, so ambient can PUT each one directly over REST — cached
    per bridge, same as legacy (topology is stable)."""
    cache_key = (cfg["ip_address"], cfg["entertainment_id"])
    if cache_key in _light_cache:
        return _light_cache[cache_key]
    try:
        ent = (await _hue_get(client, "/clip/v2/resource/entertainment"))["data"]
        ent_owner = {e["id"]: e["owner"]["rid"] for e in ent}
        lights = (await _hue_get(client, "/clip/v2/resource/light"))["data"]
        dev_light = {l["owner"]["rid"]: l["id"] for l in lights}
        ec = (await _hue_get(
            client, f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}",
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
    """PUT `body` to every light this device's entertainment stream covers,
    over ONE connection to its bridge (a device can carry ten-plus lights —
    a fresh TLS handshake per light would make every toggle noticeably
    slow). Best-effort per light — one unreachable/rejecting bulb must not
    stop the rest, but a non-2xx response (raise_for_status) still doesn't
    count toward the returned total — a rejected write is not a write."""
    cfg = dev.config
    count = 0
    async with _bridge_client(cfg) as client:
        for rid in await _resolve_lights(client, cfg):
            try:
                await _hue_put(client, f"/clip/v2/resource/light/{rid}", body)
                count += 1
            except Exception:
                logger.exception("Ambient: failed to set light %s on %s",
                                 rid, cfg.get("ip_address"))
    return count


# ── device discovery ─────────────────────────────────────────────────────────

def _hue_devices(host: Any) -> dict[str, Any]:
    return {did: host.devices.get(did) for did in host.devices
            if getattr(host.devices.get(did), "type", None) == "hue"}


def _live_look(dev: Any) -> Optional[tuple[str, int]]:
    """Best-effort (hex colour, brightness %) snapshot of what this
    device's driving virtual is CURRENTLY rendering, for the release
    catch-up ramp (see module docstring). assemble_frame() is the exact
    per-flush frame HueDevice.flush() receives and drops while frozen
    (fx/devices/hue.py) — the render loop never stopped computing it, so
    this is a live read, not a stale capture. Mean RGB across the frame
    gives both a representative hue (for the bridge's xy chromaticity) and
    a brightness proxy (the max channel, standard HSV "value"). None when
    there's nothing to read (device not yet activated, or the read itself
    failed) — the caller skips the catch-up ramp for that device rather
    than aiming it at a fabricated colour."""
    try:
        frame = dev.assemble_frame()
    except Exception:
        logger.exception("Ambient catch-up: could not read the live frame for %s",
                         getattr(dev, "name", dev))
        return None
    if frame is None or len(frame) == 0:
        return None
    n = len(frame)
    r = sum(px[0] for px in frame) / n
    g = sum(px[1] for px in frame) / n
    b = sum(px[2] for px in frame) / n
    brightness_pct = max(1, min(100, round(max(r, g, b) / 255 * 100)))
    color_hex = "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))
    return color_hex, brightness_pct


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
        if not touched:
            # Every Hue device failed — the switch must NOT report success
            # with nothing held (the exact failure shape this feature exists
            # to stop reporting: a control that says "on" while the room
            # didn't change).
            logger.error("Ambient: ON requested but every Hue device failed "
                         "— the room is NOT held")
            return {"status": "failed", "devices": [], "lights_set": 0}
        logger.info("Ambient ON: %s held at %s, %d light(s) set",
                    touched, color or "#ffffff", lights_set)
        return {"status": "on", "devices": touched, "lights_set": lights_set}

    fade = _fade_dim_payload(AMBIENT_OFF_FADE_PCT, AMBIENT_TRANSITION_MS)
    for did, dev in sorted(hue_devices.items()):
        try:
            await _apply_hue(dev, fade)
        except Exception:
            logger.exception("Ambient: off-fade failed for %s", did)
    if AMBIENT_TRANSITION_MS > 0:
        await asyncio.sleep(AMBIENT_TRANSITION_MS / 1000)

    # Catch-up: ease the still-frozen bulbs toward whatever the room's live
    # effect is actually showing right now, over the SAME bridge-side ramp
    # phase 1 used — before handing back to the stream, not after (module
    # docstring). Best-effort per device; a device with nothing to read
    # (not yet activated) just releases straight from the phase-1 fade.
    caught_up = False
    for did, dev in sorted(hue_devices.items()):
        look = _live_look(dev)
        if look is None:
            continue
        color_hex, brightness_pct = look
        try:
            await _apply_hue(dev, _light_payload(
                color_hex, AMBIENT_CATCHUP_MS, brightness_pct=brightness_pct))
            caught_up = True
        except Exception:
            logger.exception("Ambient: catch-up ramp failed for %s", did)
    if caught_up and AMBIENT_CATCHUP_MS > 0:
        await asyncio.sleep(AMBIENT_CATCHUP_MS / 1000)

    for did, dev in sorted(hue_devices.items()):
        try:
            await dev.set_frozen(False)  # re-engages the stream; the room's
                                          # live scene resumes on its own
            touched.append(did)
        except Exception:
            logger.exception("Ambient: failed to release %s", did)
    if not touched:
        logger.error("Ambient: OFF requested but every Hue device failed to "
                     "release — the room may still be held on the ambient colour")
        return {"status": "failed", "devices": []}
    logger.info("Ambient OFF: %s released (caught up: %s)", touched, caught_up)
    return {"status": "off", "devices": touched}
