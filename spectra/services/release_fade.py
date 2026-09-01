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

Off-write read-back confirmation (2026-08-16, spectra-audit-2xx-proof — a
2xx-as-proof audit, not a live incident): this module's own `_apply_hue`
only ever checked `raise_for_status()` — a 2xx from the bridge — before
counting a light as faded/off. `spectra/services/ambient.py`'s own
docstring ("Read-back confirmation") already established why that is not
enough: his bridge returns a clean HTTP 200 with an empty `errors` array
whether or not the physical bulb (over zigbee, which can silently drop a
command the bridge already 2xx'd) actually took it — see
`docs/SPECTRA_SPEC.md` D6. For the ON-hold path that gap was closed in
`ambient.py`'s `_hold_and_confirm`; this module's own final OFF write —
the one write in the whole release path that determines whether Home
Assistant inherits a dark room or a bulb still lit at whatever colour
SPECTRA last streamed — had no equivalent. `_confirm_off()` below reads
each light back after the off write (`RELEASE_OFF_SETTLE_MS` wait, then
GET), retries once (a snap PUT, no ramp — a stubborn bulb should not get
another 1.5s to maybe land) if any light still reads on, and reports the
bridge-configured names of any light STILL on after that in
`fade_and_release_hue()`'s returned `still_on` list rather than folding a
possible failure into a bare "faded" claim. `release.py`'s
`_verify_released()` was NOT independently checking individual Hue bulb
state either — only the process-level ownership/virtuals state — so this
is the first read-back this specific claim ("the room is dark") has ever
had; see `release.py`'s own module docstring for how `still_on` now folds
into `ReleaseResult.verified`/`.problems`. Deliberately NOT the full
multi-attempt paced hold `ambient.py` uses (`AMBIENT_HOLD_ATTEMPTS=3`,
spaced retries): this is a one-shot power-off with no colour to keep
re-asserting, so one retry either lands or it doesn't — a light that's
still on after that is exactly the case a human needs told about, not
hammered at.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The dim-down duration before the final off — originally matched
# spectra/services/ambient.py's own AMBIENT_TRANSITION_MS (legacy's
# ambient_transition_s), the one fade duration already proven to feel
# right in this codebase. The two have since diverged: ambient.py's own
# constant was extended to 3000ms on 2026-08-16 (his stated preference for
# the colour-hold glide he watches, docs/SPECTRA_SPEC.md §63) while this
# one stays at legacy's original 1500ms — a one-shot power-off he isn't
# judging by eye the same way, out of scope for that change. Revisit only
# if he asks for this fade specifically.
RELEASE_FADE_MS = 1500

# Off-write read-back confirmation pacing (module docstring, "Off-write
# read-back confirmation"). Deliberately lighter than ambient.py's hold
# pacing — a one-shot power-off, not a colour held indefinitely.
RELEASE_OFF_SETTLE_MS = 300      # wait after a write before reading state back
RELEASE_OFF_RETRY_SPACING_MS = 500  # wait before the one retry attempt

_REST_TIMEOUT = httpx.Timeout(connect=3.0, read=4.0, write=4.0, pool=1.0)

_light_cache: dict[tuple[str, str], list[tuple[str, str]]] = {}


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


async def _resolve_lights_named(client: httpx.AsyncClient, cfg: dict) -> list[tuple[str, str]]:
    """Entertainment stream -> owning device -> (light resource id, bridge-
    configured friendly name), cached per bridge (topology is stable) —
    same walk as ambient.py's own _resolve_lights_named (kept as an
    independent copy, see module docstring). The name is what
    `_confirm_off` below needs to report exactly which bulb didn't let go,
    rather than a bare resource id."""
    cache_key = (cfg["ip_address"], cfg["entertainment_id"])
    if cache_key in _light_cache:
        return _light_cache[cache_key]
    try:
        ent = (await _hue_get(client, "/clip/v2/resource/entertainment"))["data"]
        ent_owner = {e["id"]: e["owner"]["rid"] for e in ent}
        lights = (await _hue_get(client, "/clip/v2/resource/light"))["data"]
        dev_light = {l["owner"]["rid"]: l["id"] for l in lights}
        light_name = {l["id"]: (l.get("metadata") or {}).get("name") or l["id"]
                     for l in lights}
        ec = (await _hue_get(
            client, f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}",
        ))["data"][0]
        rids: list[tuple[str, str]] = []
        seen: set[str] = set()
        for channel in ec.get("channels", []):
            for member in channel.get("members", []):
                svc = member.get("service", {})
                if svc.get("rtype") == "entertainment":
                    lr = dev_light.get(ent_owner.get(svc.get("rid")))
                    if lr and lr not in seen:
                        seen.add(lr)
                        rids.append((lr, light_name.get(lr, lr)))
                    break
    except Exception:
        logger.exception("release fade: failed to resolve Hue lights for %s",
                         cfg.get("ip_address"))
        return []
    _light_cache[cache_key] = rids
    return rids


async def _resolve_lights(client: httpx.AsyncClient, cfg: dict) -> list[str]:
    """Light resource ids only — the dim/off PUTs don't need names, only
    the read-back confirmation below (which reports failures by name)
    does."""
    return [rid for rid, _name in await _resolve_lights_named(client, cfg)]


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
    raised before the dim landed...], "still_on": [...bridge light names
    that did not confirm off after the read-back + one retry — module
    docstring, "Off-write read-back confirmation"...]} for logging/tests."""
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

    still_on: list[str] = []
    for did in faded:
        try:
            await _apply_hue(hue_devices[did], _OFF_PAYLOAD)
        except Exception:
            logger.exception("release fade: failed to power off %s after fade", did)
            continue
        try:
            still_on.extend(await _confirm_off(hue_devices[did].config))
        except Exception:
            logger.exception("release fade: could not confirm %s powered off", did)

    still_on = sorted(set(still_on))
    if still_on:
        logger.error(
            "release fade: %d light(s) NOT confirmed off after release — "
            "still reading on: %s", len(still_on), still_on)
    logger.warning("release fade: %s faded to off before release (failed: %s)",
                   faded, failed)
    return {"devices": faded, "failed": failed, "still_on": still_on}


async def read_hue_light_states(host: Any) -> list[dict]:
    """READ-ONLY: every Hue light SPECTRA streams to on `host`, and whether
    the BULB itself currently reads on. Never writes anything.

    Added for the night run's honest exit (`spectra/services/night_exit.py`),
    which has to answer "is this fixture actually dark" at the emitted light
    rather than from a mode or a setting. It lives HERE rather than in a
    third copy of the bridge client because this module already owns the
    entertainment-stream -> device -> light-resource walk, its per-bridge
    cache, and the read-back that `_confirm_off` performs — and a second
    implementation of that walk is exactly the drift this module's own
    docstring warns about for `ambient.py`.

    ONE INSTRUMENT CAVEAT, and it is load-bearing for how the exit report is
    read: while an entertainment stream is live, `GET .../resource/light`
    does NOT reflect the streamed colour (AGENTS.md, "Reading real Hue bulb
    state"). It DOES honestly report on/off, which is the only question
    asked here — but do not extend this to read a colour back and believe
    it.

    Best-effort per bridge: one unreachable bridge must not stop another
    from being read, and a light that could not be read is reported as
    `on: None` rather than as dark. An unreadable light is not a confirmed
    dark one — `_read_still_on`'s own rule."""
    out: list[dict] = []
    for did, dev in sorted(_hue_devices(host).items()):
        cfg = getattr(dev, "config", None) or {}
        try:
            async with _bridge_client(cfg) as client:
                named = await _resolve_lights_named(client, cfg)
                for rid, name in named:
                    try:
                        state = (await _hue_get(
                            client,
                            f"/clip/v2/resource/light/{rid}"))["data"][0]
                        on = bool((state.get("on") or {}).get("on"))
                        reason = ""
                    except Exception as exc:           # noqa: BLE001
                        logger.info("release fade: could not read %s (%s): %s",
                                    name, rid, exc)
                        on, reason = None, (f"the bridge did not answer for "
                                            f"this bulb ({type(exc).__name__})")
                    out.append({"device_id": did, "light_id": rid,
                                "name": name, "on": on, "reason": reason})
        except Exception as exc:                        # noqa: BLE001
            logger.info("release fade: could not reach bridge for %s: %s",
                        did, exc)
            out.append({"device_id": did, "light_id": "", "name": did,
                        "on": None,
                        "reason": f"this bridge did not answer "
                                  f"({type(exc).__name__})"})
    return out


async def _read_still_on(client: httpx.AsyncClient,
                         named: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Read each (rid, name) back and return the ones still reading on. A
    read failure counts as still-on — an unreadable light is not a
    confirmed-off one (same "don't count what you couldn't check" rule
    ambient.py's own read-back uses)."""
    still_on: list[tuple[str, str]] = []
    for rid, name in named:
        try:
            state = (await _hue_get(
                client, f"/clip/v2/resource/light/{rid}"))["data"][0]
        except Exception:
            logger.exception("release fade: could not read back %s (%s)", name, rid)
            still_on.append((rid, name))
            continue
        if (state.get("on") or {}).get("on"):
            still_on.append((rid, name))
    return still_on


async def _confirm_off(cfg: dict) -> list[str]:
    """Read every light this bridge/entertainment-id covers back after the
    off write above (module docstring, "Off-write read-back confirmation")
    and return the friendly names of any still reading on. One paced
    retry (a snap PUT, no ramp) before giving up on a light — a stubborn
    bulb should not get another 1.5s to maybe land."""
    async with _bridge_client(cfg) as client:
        named = await _resolve_lights_named(client, cfg)
        if not named:
            return []
        if RELEASE_OFF_SETTLE_MS > 0:
            await asyncio.sleep(RELEASE_OFF_SETTLE_MS / 1000)
        pending = await _read_still_on(client, named)
        if not pending:
            return []
        logger.warning(
            "release fade: %d light(s) still reading on after the off "
            "write, retrying: %s", len(pending), [n for _, n in pending])
        if RELEASE_OFF_RETRY_SPACING_MS > 0:
            await asyncio.sleep(RELEASE_OFF_RETRY_SPACING_MS / 1000)
        for rid, name in pending:
            try:
                await _hue_put(client, f"/clip/v2/resource/light/{rid}", _OFF_PAYLOAD)
            except Exception:
                logger.exception("release fade: retry off failed for %s (%s)",
                                 name, rid)
        if RELEASE_OFF_SETTLE_MS > 0:
            await asyncio.sleep(RELEASE_OFF_SETTLE_MS / 1000)
        still_on = await _read_still_on(client, pending)
        return sorted(name for _, name in still_on)
