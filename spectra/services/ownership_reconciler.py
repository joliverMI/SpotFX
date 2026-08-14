"""Continuous record-vs-reality reconciler — SPECTRA side (report gate e3,
two-writers incident 2026-08-13, owner-ruled prevention build).

Tonight's root cause (report §(b)): the ownership RECORD said spectra owned
for ~28 minutes while a resurrected external LedFX painted the room too, and
nothing ever checked the anti-condition — not spot-effects (it correctly
shed writes and stayed silent about it), not SPECTRA (she correctly kept
painting and had no reason to look outward), not the fleet's minute-cadence
alert-only watch (it never encoded the check). The record was proven true at
handover time, then trusted forever.

This is the owner-of-record's OWN process periodically asserting the
ANTI-state instead of its own health, exactly as the report specifies:
while the record says spectra owns, TWO things must independently hold —

  1. ledfx.service is inactive. A resurrected external LedFX (a unit
     dependency, a stray `systemctl start`, anything outside the handover
     orchestrator) is the literal shape of tonight's incident.
  2. none of SPECTRA's own WLED devices report a foreign realtime source.
     WLED's JSON `json/state` carries "live" (realtime override active) and
     "lip" (the IP that last sent it) — "live" from an IP that isn't this
     host is a second writer, whatever renders it.

Both checks are best-effort and fail toward "not a violation" on their own
errors (no systemctl, an unreachable WLED) — this module proves a violation,
it does not assume one from a missing signal (same posture as the S2 bridge
degrading to neutral rather than alarming on its own absence).

Escalation is DESIGNED but OFF by default: SPECTRA_RECONCILER_ESCALATE=1
arms it (same "gated until the owner's word" discipline as
SPECTRA_HANDOVER_ARMED — see spectra/services/handover.py). Armed, a
SUSTAINED violation (ESCALATE_AFTER_TICKS consecutive ticks, so a single
noisy read never fires it) drops the room to `released`
(spectra/services/release.py) rather than reaching in to stop the intruder's
unit directly: going to no-writer is always safe (release's own doctrine)
and reuses the one already-audited panic handle instead of a second,
less-proven direct-stop path. A targeted "stop the intruder's unit"
escalation was considered and rejected here for that reason; this knob is
where the owner could plug it in later. Unarmed (the shipped default), a
violation is alarm-only — CRITICAL log every tick it persists, one recovery
line when it clears — matching report gate e3's "cheapest first increment"
bar, raised to run inside the owner-of-record's own process rather than an
external fleet watch.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from fx import light_ownership

logger = logging.getLogger(__name__)

TICK_S = 30.0                  # matches frame_watchdog / write_plane_watchdog cadence
ESCALATE_AFTER_TICKS = 3       # ~90s sustained (armed only) before escalation fires

_alarmed = False
_violation_streak = 0


@dataclass
class ReconcileResult:
    violated: bool
    reasons: list[str] = field(default_factory=list)


async def _ledfx_service_active() -> bool:
    """Is the external LedFX unit up right now? Missing systemctl (a test or
    non-systemd host) is not a violation signal — it means this check simply
    cannot run here, not that LedFX is running."""
    from spectra.services.handover import _systemctl
    try:
        rc, out = await _systemctl(
            "is-active", os.getenv("SPECTRA_LEDFX_UNIT", "ledfx"))
    except FileNotFoundError:
        return False
    return out.strip() == "active"


async def _foreign_wled_sources() -> list[str]:
    """SPECTRA's own WLED devices that report a realtime source she didn't
    open (json/state's "live"+"lip"). An unreachable device can't be
    painting anything, so it is skipped, not flagged."""
    from fx.utils import get_local_ip
    from spectra.services.live_host import live

    if live.host is None:
        return []
    local_ip = get_local_ip()
    foreign: list[str] = []
    for device in live.host.devices.values():
        wled = getattr(device, "wled", None)
        if wled is None:
            continue
        try:
            wled_state = await wled.get_state()
        except Exception as exc:
            logger.debug("reconciler: WLED %s unreachable (%r) — skipping",
                        device.id, exc)
            continue
        lip = wled_state.get("lip")
        if wled_state.get("live") and lip not in (None, "", local_ip, "127.0.0.1"):
            foreign.append(f"{device.id} (lip={lip})")
    return foreign


async def check() -> ReconcileResult:
    """The anti-state assertion. Vacuously fine whenever the record doesn't
    say spectra owns — callers only need to tick while she does, but this is
    safe to call any time."""
    record = light_ownership.load()
    if record.owner != light_ownership.SPECTRA:
        return ReconcileResult(violated=False)
    reasons: list[str] = []
    if await _ledfx_service_active():
        reasons.append("ledfx.service is active while spectra owns the lights")
    foreign = await _foreign_wled_sources()
    if foreign:
        reasons.append("foreign realtime source on WLED(s): " + ", ".join(foreign))
    return ReconcileResult(violated=bool(reasons), reasons=reasons)


def _escalation_enabled() -> bool:
    return os.getenv("SPECTRA_RECONCILER_ESCALATE") == "1"


async def _escalate(reasons: list[str]) -> None:
    """See the module docstring: gated, drops to `released`. Never raises —
    a failed escalation must not crash the reconciler task itself."""
    from spectra.services.release import release_room
    detail = "; ".join(reasons)
    logger.critical("reconciler: ESCALATING — dropping to released (%s)", detail)
    try:
        await release_room(f"reconciler: sustained anti-state violation — {detail}")
    except Exception:
        logger.exception("reconciler: escalation release_room() failed")


async def _tick() -> None:
    global _alarmed, _violation_streak
    result = await check()
    if not result.violated:
        if _alarmed:
            _alarmed = False
            _violation_streak = 0
            logger.warning(
                "reconciler: anti-state restored — spectra is the sole "
                "writer again")
        return
    _violation_streak += 1
    _alarmed = True
    logger.critical(
        "RECORD-VS-REALITY VIOLATION (record says spectra owns): %s",
        "; ".join(result.reasons))
    if _escalation_enabled() and _violation_streak >= ESCALATE_AFTER_TICKS:
        await _escalate(result.reasons)
        _violation_streak = 0


async def run_supervised() -> None:
    """Own asyncio task (the 2026-08-12 lesson: monitoring must not die with
    the monitored — same discipline as frame_watchdog.run_supervised)."""
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("ownership reconciler tick crashed (retrying): %r", exc)
        await asyncio.sleep(TICK_S)
