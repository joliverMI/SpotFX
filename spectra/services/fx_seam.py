"""SPECTRA's ONE write seam — every live write to the lights passes through
apply_writes(), nothing else in spectra/ performs LedFX I/O.

S3: the transport is routed by the LIGHT OWNERSHIP RECORD
(fx/light_ownership.py), enforced here — in the write path — not by
convention:

  spot-effects owns   HTTP PUTs to the external LedFX service (the S1
                      behavior): the owner's Fire button writing through the
                      one process that drives the devices. Not a second
                      writer — LedFX is the writer.
  spectra owns        in-process PUTs through fx.facade into the live host
                      the handover activated. Zero HTTP.
  handing-over        REFUSED. During the switch nobody writes; the API
                      surfaces the error to the owner instead of racing the
                      handover.
  released            REFUSED — the panic handle (fx.light_ownership.
                      RELEASED). Fires stay refused until the way-back
                      handover lands.

Bounded concurrency + a hard per-request deadline carry the write-plane
lesson (the 2026-08-12 outage was leaked slots parking calls forever).

Tests never call this module (dry_run stops at the compiler).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from fx import device_model, light_ownership
from spectra import config

logger = logging.getLogger(__name__)

REQUEST_DEADLINE_S = 10.0
MAX_IN_FLIGHT = 4

_slots = asyncio.Semaphore(MAX_IN_FLIGHT)

# Liveness blind spot (spectra-room-fault-diagnosis, 2026-08-14): frame
# freshness alone can't tell "streaming the wrong effect" apart from healthy
# — it only proves the render loop pushed A frame. This is additive
# observability for the case the fix above now handles instead of hiding:
# a requested type switch that would have hit fx/facade.py's stale-tween-PUT
# drop. Not a health signal on its own (a switch landing correctly is
# expected, ordinary traffic) — surfaced on /spectra/api/liveness for a human
# to notice a virtual that's switching types unusually often.
_type_switches_landed = 0
_last_type_switch: dict | None = None


def stats() -> dict:
    return {"type_switches_landed": _type_switches_landed,
            "last_type_switch": _last_type_switch}


class HandoverInProgress(RuntimeError):
    """Raised when a fire arrives while the room is changing hands."""


class RoomReleased(RuntimeError):
    """Raised when a fire arrives while the room is released to Home
    Assistant (the panic handle) — refused until the way-back handover
    lands."""


async def apply_writes(writes: list[dict], *, transition_ms: int = 0) -> None:
    """Send compiled writes as effect switches over the transport the
    ownership record grants. Raises on the first hard failure — the API
    surfaces it to the owner instead of half-applying a scene silently.

    transition_ms > 0 is the OVERRIDE BLEND entry-ramp equivalent
    (SceneV2.entry_ramp_ms): writes blend in (hue-arc for colour) instead of
    landing as an instant switch. 0 (the default) is today's unchanged
    instant-jump behaviour."""
    owner = light_ownership.load().owner
    if owner == light_ownership.SPECTRA:
        await _apply_via_facade(writes, transition_ms)
    elif owner == light_ownership.SPOT_EFFECTS:
        await _apply_via_http(writes, transition_ms)
    elif owner == light_ownership.RELEASED:
        raise RoomReleased(
            "room released to Home Assistant — fires are refused until the "
            "way-back handover lands")
    else:
        raise HandoverInProgress(
            "light handover in progress — fires are refused until it lands")


def _body(w: dict, transition_ms: int = 0) -> dict:
    body = {
        "type": w["effect_type"],
        "config": device_model.round_int_params(w["effect_type"], w["config"]),
    }
    if transition_ms > 0:
        # Same tween shape fx_executor uses for glides — hue-arc blend,
        # never through grey, never a colour-recreation crossfade.
        body["transition_ms"] = transition_ms
        body["transition_blend"] = "hue"
        body["easing"] = "linear"
    return body


async def _apply_via_http(writes: list[dict], transition_ms: int = 0) -> None:
    async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                 timeout=REQUEST_DEADLINE_S) as client:
        for w in writes:
            async with _slots:
                resp = await client.put(
                    f"/api/virtuals/{w['virtual_id']}/effects",
                    json=_body(w, transition_ms))
            resp.raise_for_status()
    logger.info("fx seam: %d writes applied via %s", len(writes),
                config.ledfx_url())


async def _is_type_switch(facade, virtual_id: str, effect_type: str) -> bool:
    """True if virtual_id is NOT currently running effect_type (read-only
    GET, no write-plane effect). Unknown (GET fails — bad id, no host) reads
    as False so the write still goes out as a single PUT and the PUT itself
    reports the real error, unchanged from today."""
    resp = await facade.handle("GET", f"/api/virtuals/{virtual_id}")
    if resp.status_code != 200:
        return False
    current = resp.json().get(virtual_id, {}).get("effect", {}).get("type")
    return current is not None and current != effect_type


async def _apply_via_facade(writes: list[dict], transition_ms: int = 0) -> None:
    global _type_switches_landed, _last_type_switch
    from fx import facade
    for w in writes:
        vid = w["virtual_id"]
        if transition_ms > 0 and await _is_type_switch(
                facade, vid, w["effect_type"]):
            # fx/facade.py's stale-tween-PUT guard (447-461) silently drops
            # a combined type-switch+transition PUT — a blend only makes
            # sense between two states of the SAME effect. Land the switch
            # instantly first; the write already carries the full target
            # config, so there is nothing left to tween.
            resp = await facade.handle(
                "PUT", f"/api/virtuals/{vid}/effects", json=_body(w, 0))
            _type_switches_landed += 1
            _last_type_switch = {"virtual_id": vid, "effect_type": w["effect_type"]}
        else:
            resp = await facade.handle(
                "PUT", f"/api/virtuals/{vid}/effects",
                json=_body(w, transition_ms))
        resp.raise_for_status()
    logger.info("fx seam: %d writes applied in-process (spectra owns)",
                len(writes))
