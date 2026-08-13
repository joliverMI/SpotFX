"""SPECTRA's ONE write seam — every live write to the lights passes through
apply_writes(), nothing else in spectra/ performs LedFX I/O.

S1 (now): HTTP PUTs to the external LedFX service — the same API surface the
owner's spot-effects install already serves, used only by the editor's real
Fire button. Bounded concurrency + a hard per-request deadline carry the
write-plane lesson (the 2026-08-12 outage was leaked slots parking calls
forever); the full gate/breaker machinery arrives with S3 ownership.

S3 (later): this function re-targets to the in-process fx/ facade when
SPECTRA owns the lights — same seam, callers untouched. Do NOT point the
facade at live hardware before the S3 handover (Hue-DTLS / DDP single-sender
exclusivity; never two writers).

Tests never call this module (dry_run stops at the compiler).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from fx import device_model
from spectra import config

logger = logging.getLogger(__name__)

REQUEST_DEADLINE_S = 10.0
MAX_IN_FLIGHT = 4

_slots = asyncio.Semaphore(MAX_IN_FLIGHT)


async def apply_writes(writes: list[dict]) -> None:
    """Send compiled writes as effect switches. Raises on the first hard
    failure — the API surfaces it to the owner instead of half-applying a
    scene silently."""
    async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                 timeout=REQUEST_DEADLINE_S) as client:
        for w in writes:
            body = {
                "type": w["effect_type"],
                "config": device_model.round_int_params(
                    w["effect_type"], w["config"]),
            }
            async with _slots:
                resp = await client.put(
                    f"/api/virtuals/{w['virtual_id']}/effects", json=body)
            resp.raise_for_status()
    logger.info("fx seam: %d writes applied via %s", len(writes),
                config.ledfx_url())
