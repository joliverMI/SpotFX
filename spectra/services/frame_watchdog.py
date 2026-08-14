"""SPECTRA's systemd watchdog — frame-flush freshness as the liveness gate
(detection Option B carried across the S3 process split, as the scoping
report §3 promised: "the liveness predicate just changes from gate
completions to render loop flushed frames to devices recently").

After the split the render/write plane lives in THIS process, so
spectra.service gets its own Type=notify/WatchdogSec pair (deploy/
spectra.service) and this task feeds it: sd_notify("WATCHDOG=1") every
TICK_S ONLY while the predicate holds. The signal source is the LIVENESS
CONTRACT's own freshness marks (live_host.FrameFreshness, stamped by the
render loop's VirtualUpdateEvent after assemble+flush) — the real path,
never a parallel health counter.

The predicate is process-liveness-shaped, NOT the liveness endpoint's
healthy bit verbatim, because a systemd restart must plausibly fix whatever
stops the pings (the same principle that keeps breaker-open windows alive in
services/write_plane_watchdog.py):

  live stack up, spectra owns     alive iff every ACTIVE virtual flushed
                                  within STALE_AFTER_S — stale frames here
                                  mean wedged render threads or a dead loop,
                                  which a restart does fix.
  live stack up, spot-effects     NOT alive — split-brain: a live stack
  owns                            without ownership is a rogue writer, and a
                                  restart tears it down (the record's gates
                                  then keep the reborn process dark).
  live stack up, handing-over     alive — the activation step of a handover
                                  legitimately runs a live stack before the
                                  record commits; the orchestrator owns every
                                  failure landing, the watchdog must not race
                                  it.
  live stack down                 alive — a dark process is a healthy
                                  process. Dark-but-owned only persists when
                                  the startup resume (handover.
                                  resume_own_room) FAILED — devices
                                  unreachable, seed missing — and a restart
                                  would just fail the same way; the alarm is
                                  the liveness endpoint's 503, and the
                                  watchdog must not restart-loop the service
                                  over it.

sd_notify is stdlib-only and dark-compatible: without Type=notify in the
unit, $NOTIFY_SOCKET is unset and every call is a no-op. (Deliberately
self-contained: spectra/ imports no spot-effects runtime module, so the
~15-line notify sender is duplicated from services/write_plane_watchdog.py
rather than shared through it.)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Optional

from fx import light_ownership

logger = logging.getLogger(__name__)

TICK_S = 30.0                # WatchdogSec=90 allows 2 missed ticks

_alarmed = False             # episode latch for the CRITICAL line


def sd_notify(state: str) -> bool:
    """One sd_notify datagram to $NOTIFY_SOCKET; silent no-op (False) when
    the socket is unset — i.e. whenever the unit is not Type=notify."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(state.encode())
        return True
    except OSError as exc:
        logger.debug("sd_notify(%r) failed: %r", state, exc)
        return False


def evaluate(owner: str, live_active: bool,
             frames_fresh: bool) -> tuple[bool, Optional[str]]:
    """Pure predicate: (alive, reason-if-not). See the module docstring for
    the case-by-case rationale; the executable spec pins every row."""
    if not live_active:
        return True, None
    if owner == light_ownership.SPECTRA:
        if frames_fresh:
            return True, None
        return False, ("render plane stale: live stack up but active "
                       "virtuals stopped flushing frames")
    if owner == light_ownership.HANDING_OVER:
        return True, None
    return False, (f"split-brain: live stack up while owner={owner!r} — "
                   "restart tears the rogue writer down")


def _tick() -> None:
    global _alarmed
    from spectra.services.live_host import live
    owner = light_ownership.load().owner
    alive, reason = evaluate(owner, live.active, live.fresh())
    if alive:
        if _alarmed:
            _alarmed = False
            logger.warning("frame watchdog: render plane healthy again")
        sd_notify("WATCHDOG=1")
        return
    if not _alarmed:
        _alarmed = True
        logger.critical(
            "RENDER PLANE DEAD-MAN TRIPPED — %s; watchdog pings withheld — "
            "systemd restarts SPECTRA if WatchdogSec is armed", reason)
    # No sd_notify while tripped: cessation IS the actuation signal.


async def run_supervised() -> None:
    """Own asyncio task (the 2026-08-12 lesson: monitoring must not die with
    the monitored). A crashing tick is logged and retried; a crash-looping
    tick never reaches sd_notify, so persistent breakage still stops the
    pings — the supervisor cannot mask real death."""
    sd_notify("READY=1")   # Type=notify startup handshake
    while True:
        try:
            _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("frame watchdog tick crashed (retrying): %r", exc)
        await asyncio.sleep(TICK_S)
