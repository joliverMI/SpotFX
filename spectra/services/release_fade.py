"""Pre-release Hue fade — the "let go" step release_room() was missing.

THE DEFECT (found live 2026-08-14, data/spectra-release-restores-lights):
release_room() stopped every Hue device's entertainment stream but never
touched the bulb's actual light state. Hue holds whatever colour/brightness
it last received via the (now-stopped) stream — so the bulb was simply
abandoned on SPECTRA's last frame. All 10 Music Group + 7 Dining/Kitchen
bulbs across both bridges sat "on", byte-identical, at that frame. The
entertainment sessions were already closed — Home Assistant was never
blocked — the room was just never told to let the LIGHT go, only the
session.

FIDELITY (captain.md: "exact where there is a direct equivalent, free
where the mechanism differs in kind"): legacy's ambient-mode disable
(services/ambient_mode.py) FADES the bulb on the bridge, via REST, before
handing control back — spectra/services/ambient.py already matched that
FEEL for its own off-switch. This module reuses the same two ordering
rules those two proved out: (1) freeze the entertainment stream FIRST — a
live stream frame must never win a race against a REST write, per
fx/devices/hue.py's own set_frozen() contract — then (2) issue the REST
write with the bridge's own `dynamics.duration` so it visibly fades rather
than snaps.

WHERE IT DIFFERS IN KIND: legacy's fade, and SPECTRA ambient's, lands ON a
colour (the wake scene / the room's live look) because a next state
follows immediately — the stream reconnects, a real effect resumes.
Release has no next state to land on: nothing reconnects this stream
again, ownership itself is leaving SPECTRA for Home Assistant. So instead
of fading TOWARD a colour, this fades brightness DOWN then powers the
light off — off is the only bulb state that does not itself read as "a
colour SPECTRA chose". That is this module's reading of "let go": dark,
handed back clean, not a prettier hold.

SCOPE: every live Hue device on live_host.live.host — every bridge, every
entertainment group SPECTRA streams to (his room spans two bridges,
hue-lights and dining-hues) — not just whichever one gets reported, and
not WLED (see spectra/services/release.py's module docstring / the PR body
for why WLED's own realtime-exit already reverts to its on-device show,
genuinely different in kind from a Hue bulb that has no "own show" to fall
back to).

Best-effort per device, same discipline as spectra/services/release.py:
one unreachable bridge must not stop another from being released, and a
fade failure here must never re-open the write gate — release_room() has
already landed the ownership record at `released` by the time this runs.

Bridge REST goes over a direct httpx.AsyncClient, same request shape as
spectra/services/ambient.py's own bridge client — kept as an independent
copy rather than a shared import: ambient.py's test harness monkeypatches
its own module-level `_bridge_client` name, so factoring the two through
one shared client module would silently stop those tests from
intercepting bridge calls. Both are small and rarely touched; keep them in
sync by inspection, not by coupling.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The dim-down duration before the final off — matches
# spectra/services/ambient.py's own AMBIENT_TRANSITION_MS (legacy's
# ambient_transition_s), the one fade duration already proven to feel
# right in this codebase.
RELEASE_FADE_MS = 1500

_REST_TIMEOUT = httpx.Timeout(connect=3.0, read=4.0, write=4.0, pool=1.0)

_light_cache: dict[tuple[str, str], list[str]] = {}


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
    """Entertainment stream -> owning device -> light resource id, cached
    per bridge (topology is stable) — same walk as ambient.py's
    _resolve_lights."""
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
        logger.exception("release fade: failed to resolve Hue lights for %s",
                         cfg.get("ip_address"))
        return []
    _light_cache[cache_key] = rids
    return rids


async def _apply_hue(dev: Any, body: dict) -> int:
    """PUT `body` to every light this device's entertainment stream covers,
    over one connection to its bridge. Best-effort per light — a rejected
    write (raise_for_status) does not count toward the returned total."""
    cfg = dev.config
    count = 0
    async with _bridge_client(cfg) as client:
        for rid in await _resolve_lights(client, cfg):
            try:
                await _hue_put(client, f"/clip/v2/resource/light/{rid}", body)
                count += 1
            except Exception:
                logger.exception("release fade: failed to set light %s on %s",
                                 rid, cfg.get("ip_address"))
    return count


def _dim_payload(ramp_ms: int) -> dict:
    """Brightness-only fade toward the bridge's own minimum (1%, matching
    ambient.py's own brightness clamp) — no colour target, see module
    docstring on why release has no landing colour to fade toward."""
    return {
        "on": {"on": True},
        "dimming": {"brightness": 1.0},
        "dynamics": {"duration": int(ramp_ms)},
    }


# Sent only after the dim fade above has visibly landed, so the power-off
# itself is imperceptible rather than a snap from full brightness.
_OFF_PAYLOAD = {"on": {"on": False}}


def _hue_devices(host: Any) -> dict[str, Any]:
    return {did: host.devices.get(did) for did in host.devices
            if getattr(host.devices.get(did), "type", None) == "hue"}


async def fade_and_release_hue(host: Any) -> dict:
    """Freeze + bridge-fade every live Hue device on `host` to off. Called
    once from release_room(), BEFORE the live stack itself tears down (the
    stream must still be reachable to freeze). Best-effort per device — one
    bridge failing to fade must not stop another, and must not raise past
    this call (release_room() already wraps its caller in _best_effort, but
    a partial run here still needs every OTHER device to get its own
    attempt). Returns {"devices": [...faded ids...], "failed": [...ids that
    raised before the dim landed...]} for logging/tests."""
    hue_devices = _hue_devices(host)
    if not hue_devices:
        return {"devices": [], "failed": []}

    faded: list[str] = []
    failed: list[str] = []
    for did, dev in sorted(hue_devices.items()):
        try:
            await dev.set_frozen(True)   # must land before any REST write
            await _apply_hue(dev, _dim_payload(RELEASE_FADE_MS))
        except Exception:
            logger.exception("release fade: failed to dim %s before release", did)
            failed.append(did)
            continue
        faded.append(did)

    if faded and RELEASE_FADE_MS > 0:
        await asyncio.sleep(RELEASE_FADE_MS / 1000)

    for did in faded:
        try:
            await _apply_hue(hue_devices[did], _OFF_PAYLOAD)
        except Exception:
            logger.exception("release fade: failed to power off %s after fade", did)

    logger.warning("release fade: %s faded to off before release (failed: %s)",
                   faded, failed)
    return {"devices": faded, "failed": failed}
