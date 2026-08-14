"""Continuous record-vs-reality reconciler — spot-effects side (report gate
e3, companion to spectra/services/ownership_reconciler.py; two-writers
incident 2026-08-13, owner-ruled prevention build).

The SPECTRA-side module asserts "while spectra owns, LedFX must be dark and
her WLEDs painted only by her." This module is the OTHER half of report
gate e3: while the record says spot-effects owns, SPECTRA's own liveness
must not report her live stack painting — a live stack without ownership is
exactly the split-brain shape spectra/api/ownership.py's liveness handler
already names, but that self-check lives IN her process; this is the
independent, cross-process assertion the report calls for (the owner-of-
record proving the anti-state, not trusting the other side's self-report
alone — the same "verified independently of the claim" discipline
spectra/services/handover.py already applies to quiesce).

Polled directly against SPECTRA's own process (settings.spectra_port), not
through services/spectra_proxy.py: a proxied read shares THIS process's
event loop (see that module's docstring), so it would go blind exactly when
this process itself is unhealthy. An unreachable SPECTRA is not treated as
a violation — it degrades the same way the S2 bridge does when SPECTRA is
down (nothing to reconcile against), logged at debug only.

Escalation is DESIGNED but OFF by default — same
SPECTRA_RECONCILER_ESCALATE=1 knob as the SPECTRA-side module (shared
env var; either process arms both). Armed, a sustained violation calls
SPECTRA's own panic-release route (POST /spectra/api/ownership/release,
NOT gated by SPECTRA_HANDOVER_ARMED — going to no-writer is always safe)
rather than this process reaching into SPECTRA's internals directly, which
would cross the process-split's import discipline for no good reason when
an HTTP call already does the job safely.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

TICK_S = 30.0                  # matches write_plane_watchdog cadence
REQUEST_TIMEOUT_S = 3.0
ESCALATE_AFTER_TICKS = 3       # ~90s sustained (armed only) before escalation fires

_alarmed = False
_violation_streak = 0


def _spot_effects_owns() -> bool:
    from fx import light_ownership
    return light_ownership.writes_allowed(light_ownership.SPOT_EFFECTS)


async def _spectra_liveness() -> dict | None:
    url = f"http://127.0.0.1:{settings.spectra_port}/spectra/api/liveness"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            resp = await client.get(url)
        return resp.json()
    except Exception as exc:
        logger.debug("reconciler: could not reach SPECTRA liveness (%r)", exc)
        return None


def _escalation_enabled() -> bool:
    import os
    return os.getenv("SPECTRA_RECONCILER_ESCALATE") == "1"


async def _escalate(state: str) -> None:
    """See the module docstring: gated, drops SPECTRA to `released` over her
    own API. Never raises — a failed escalation must not crash this task."""
    url = f"http://127.0.0.1:{settings.spectra_port}/spectra/api/ownership/release"
    logger.critical(
        "reconciler: ESCALATING — releasing SPECTRA (liveness state=%s "
        "while spot-effects owns)", state)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            resp = await client.post(url)
        if resp.status_code == 207:
            # released, but the post-release read-back couldn't confirm
            # every device actually went dark — still loud, not silent.
            logger.error("reconciler: escalation released but unverified: %s",
                        resp.text[:200])
        elif resp.status_code >= 300:
            logger.error("reconciler: escalation release call returned %d: %s",
                        resp.status_code, resp.text[:200])
    except Exception:
        logger.exception("reconciler: escalation release call failed")


async def _tick() -> None:
    global _alarmed, _violation_streak
    if not _spot_effects_owns():
        if _alarmed:
            _alarmed = False
            _violation_streak = 0
        return
    body = await _spectra_liveness()
    if body is None:
        return  # can't verify; not proof of a violation
    state = body.get("state")
    if state not in ("live", "split-brain"):
        if _alarmed:
            _alarmed = False
            _violation_streak = 0
            logger.warning(
                "reconciler: anti-state restored — SPECTRA is dark again")
        return
    _violation_streak += 1
    _alarmed = True
    logger.critical(
        "RECORD-VS-REALITY VIOLATION (record says spot-effects owns): "
        "SPECTRA liveness reports state=%s (owner=%s) — a second writer "
        "may be painting the room", state, body.get("owner"))
    if _escalation_enabled() and _violation_streak >= ESCALATE_AFTER_TICKS:
        await _escalate(state)
        _violation_streak = 0


async def run_supervised() -> None:
    """Own asyncio task — monitoring must not die with the monitored (same
    discipline as services/write_plane_watchdog.run_supervised)."""
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("spectra-liveness reconciler tick crashed (retrying): %r", exc)
        await asyncio.sleep(TICK_S)
