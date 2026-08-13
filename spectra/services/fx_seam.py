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


class HandoverInProgress(RuntimeError):
    """Raised when a fire arrives while the room is changing hands."""


async def apply_writes(writes: list[dict]) -> None:
    """Send compiled writes as effect switches over the transport the
    ownership record grants. Raises on the first hard failure — the API
    surfaces it to the owner instead of half-applying a scene silently."""
    owner = light_ownership.load().owner
    if owner == light_ownership.SPECTRA:
        await _apply_via_facade(writes)
    elif owner == light_ownership.SPOT_EFFECTS:
        await _apply_via_http(writes)
    else:
        raise HandoverInProgress(
            "light handover in progress — fires are refused until it lands")


def _body(w: dict) -> dict:
    return {
        "type": w["effect_type"],
        "config": device_model.round_int_params(w["effect_type"], w["config"]),
    }


async def _apply_via_http(writes: list[dict]) -> None:
    async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                 timeout=REQUEST_DEADLINE_S) as client:
        for w in writes:
            async with _slots:
                resp = await client.put(
                    f"/api/virtuals/{w['virtual_id']}/effects", json=_body(w))
            resp.raise_for_status()
    logger.info("fx seam: %d writes applied via %s", len(writes),
                config.ledfx_url())


async def _apply_via_facade(writes: list[dict]) -> None:
    from fx import facade
    for w in writes:
        resp = await facade.handle(
            "PUT", f"/api/virtuals/{w['virtual_id']}/effects", json=_body(w))
        resp.raise_for_status()
    logger.info("fx seam: %d writes applied in-process (spectra owns)",
                len(writes))
