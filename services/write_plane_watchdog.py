"""Write-plane wedge tripwire + systemd watchdog gating (detection Option B).

Sits behind the 2026-08-12 starvation fix in api/ledfx_client._request(): the
fix self-heals a starved gate, so this alarm is a should-never-fire tripwire
that fires only if the self-heal itself failed, a regression reintroduced
unbounded slot tenure, or the request-issuing tasks / event loop died.

Two pieces:

1. Alarm tick — every TICK_S evaluate the composite liveness predicate over
   ledfx_client.get_health() (see evaluate() for the exact condition). On trip:
   one logger.critical("WRITE PLANE WEDGED ...") per episode, one recovery
   line when the predicate goes healthy again.

2. systemd watchdog gating — sd_notify("WATCHDOG=1") is sent from the alarm
   tick ONLY while the predicate holds. With WatchdogSec=90 + Type=notify in
   the unit (deploy/spotfx.service), a wedged write plane, a dead event loop,
   or a dead alarm task all stop the pings and systemd restarts SpotFX with a
   permanent `watchdog timeout` journal record. Without those unit lines
   (today's live unit), $NOTIFY_SOCKET is unset and every sd_notify call is a
   harmless no-op — this module ships dark-compatible.

Demand is guaranteed: poll_virtual_states pushes a GET through _request every
5 s from boot, so "no completions for COMPLETION_AGE_ALARM_S" is never
idleness — a healthy ceiling for last_completion_age_s is ~5-15 s.

Predicate care (the one deliberate design pass from the detection scoping
report): a legitimate LedFX-side outage must never stop the pings. While the
circuit breaker is open — LedFX down or restarting, the failure-driven
machinery already handling it — deadline-counter advances and completion-age
staleness are excused: half-open probes against a black-holed LedFX can hit
the request deadline, and that is LedFX sickness, not write-plane death. Two
signals are NEVER excused because they are internal to the SpotFX write plane
regardless of LedFX's state: the gate_reset counter advancing (the starvation
self-heal firing repeatedly = it is not sticking) and oldest_inflight_s
exceeding the hard request deadline (the deadline machinery itself is dead —
only a stopped event loop lets a request outlive asyncio.timeout()).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket

logger = logging.getLogger(__name__)

TICK_S = 30.0                     # WatchdogSec=90 allows 2 missed ticks
COMPLETION_AGE_ALARM_S = 60.0     # >> the 5 s poll cadence; never idleness

_prev_counters: dict | None = None   # counters snapshot from the previous tick
_alarmed = False                     # episode latch for the CRITICAL line


def sd_notify(state: str) -> bool:
    """Send one sd_notify datagram to $NOTIFY_SOCKET (stdlib only, no sdnotify
    dependency). Returns False as a silent no-op when the socket is unset —
    i.e. whenever the unit is not Type=notify, keeping this dark-compatible."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):          # abstract-namespace socket
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(state.encode())
        return True
    except OSError as exc:
        logger.debug("sd_notify(%r) failed: %r", state, exc)
        return False


def evaluate(health: dict, prev_counters: dict | None) -> tuple[bool, list[str]]:
    """Pure liveness predicate over one get_health() snapshot plus the previous
    tick's counters. Returns (alive, reasons); reasons non-empty iff wedged.

    Wedge signals:
      - gate_reset counter advanced since last tick        (never excused)
      - oldest_inflight_s > request_deadline_s             (never excused)
      - deadline counter advanced since last tick          (excused while breaker open)
      - last_completion_age_s > COMPLETION_AGE_ALARM_S     (excused while breaker open)

    First tick (prev_counters None) skips the counter deltas — no baseline yet.
    last_completion_age_s of None means no request has completed since boot;
    startup grace, not a wedge.

    Light ownership (SPECTRA S3): when the snapshot says spot-effects does not
    own the lights, the write plane is deliberately surrendered — every call
    is shed at the ownership gate, so no completions and no deadlines is the
    CORRECT state, excused like a breaker-open outage. The two hard signals
    stay hard: they are internal to this process regardless of who owns the
    room. The room's health signal is SPECTRA's liveness endpoint then.
    """
    counters = health.get("counters") or {}
    hard: list[str] = []       # write-plane-internal — count regardless of breaker
    excusable: list[str] = []  # LedFX-outage shapes — excused while breaker open
    if prev_counters is not None:
        g = counters.get("gate_reset", 0) - prev_counters.get("gate_reset", 0)
        if g > 0:
            hard.append(f"gate_reset +{g}")
        d = counters.get("deadline", 0) - prev_counters.get("deadline", 0)
        if d > 0:
            excusable.append(f"deadline +{d}")
    oldest = health.get("oldest_inflight_s") or 0.0
    deadline_s = health.get("request_deadline_s") or 0.0
    if deadline_s and oldest > deadline_s:
        hard.append(f"oldest_inflight {oldest:.0f}s > deadline {deadline_s:.0f}s")
    age = health.get("last_completion_age_s")
    if age is not None and age > COMPLETION_AGE_ALARM_S:
        excusable.append(f"last_completion_age {age:.0f}s")
    surrendered = health.get("light_ownership", "spot-effects") != "spot-effects"
    reasons = hard + (
        [] if (health.get("breaker_open") or surrendered) else excusable)
    return (not reasons, reasons)


def _tick() -> None:
    """One alarm evaluation. Pings the systemd watchdog only while alive."""
    global _prev_counters, _alarmed
    from api import ledfx_client
    health = ledfx_client.get_health()
    alive, reasons = evaluate(health, _prev_counters)
    _prev_counters = dict(health.get("counters") or {})
    if alive:
        if _alarmed:
            _alarmed = False
            logger.warning("Write plane recovered — liveness predicate healthy again")
        sd_notify("WATCHDOG=1")
        return
    if not _alarmed:
        _alarmed = True
        logger.critical(
            "WRITE PLANE WEDGED — %s (breaker_open=%s inflight=%s "
            "oldest_inflight_s=%s last_completion_age_s=%s); watchdog pings "
            "withheld — systemd restarts SpotFX if WatchdogSec is armed",
            "; ".join(reasons), health.get("breaker_open"), health.get("inflight"),
            health.get("oldest_inflight_s"), health.get("last_completion_age_s"),
        )
    # No sd_notify while wedged: cessation IS the actuation signal.


async def run_supervised() -> None:
    """The alarm task body (own asyncio task, NOT inside latency_loop — the
    2026-08-12 lesson: monitoring must not die with the monitored). A crashing
    tick is logged and retried next interval; a crash-looping tick never
    reaches sd_notify, so persistent breakage still stops the pings and
    systemd still restarts us — the supervisor cannot mask real death."""
    sd_notify("READY=1")   # Type=notify startup handshake; no-op without the unit change
    while True:
        try:
            _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("write-plane watchdog tick crashed (retrying next tick): %r", exc)
        await asyncio.sleep(TICK_S)
