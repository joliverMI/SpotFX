"""THE OWNER'S PANIC HANDLE — one press, everything lets go.

release_room() is NOT the S3 handover. Handing over swaps one writer for
another and is gated (SPECTRA_HANDOVER_ARMED) and staged (quiesce → verify →
activate → verify → commit) because a NEW writer is coming up and Hue/DDP
tolerate exactly one. Releasing has no new writer — there is nothing to
verify into existence — so it is one atomic step
(fx.light_ownership.release()) followed by best-effort device-class cleanup.
Not gated by SPECTRA_HANDOVER_ARMED: going TO no-writer is always safe to
allow regardless of whether the S3 takeover is armed, and a panic handle
that needs an env var first is not a panic handle.

Ordering is deliberate: the ownership record moves to `released` FIRST,
before any device is touched. Both worlds' write gates
(api.ledfx_client._request's ownership check, spectra/services/fx_seam's
owner dispatch) key off the record, so the instant release() returns nothing
new can start writing — the device-class cleanup below can never race a
fresh frame. A cleanup failure is logged but never re-opens the gate;
`released` is the correct landing regardless of whether every device heard
the message (same fail-safe discipline as handover.py's abort()).

Per device class, RELEASED means (see fx/devices/*.py + PR body / help for
the full per-class writeup):
  WLED     realtime EXITED explicitly — {"live": false} to the JSON API
           (fx/utils.py WLED.release_realtime), not left to the per-packet
           UDP timeout byte lapsing on its own.
  Hue      the entertainment/streaming session STOPPED (action:"stop" to the
           bridge) — already explicit in the vendored driver
           (fx/devices/hue.py HueDevice.deactivate); release just calls it.
  dummy    deactivated (no I/O; a no-op release, correctly).
  external the released side's active virtuals set inactive via the LedFX
  LedFX    REST API (set_virtual_active) — deactivating a virtual there
  service  deactivates the device backing it, same as above one layer up.
           This app never restarts or reaches into that process beyond its
           documented API.

The way BACK is not here — it is the normal guarded handover
(run_handover(SPECTRA, ...)), still gated and staged, still readiness-gated.
See spectra/services/handover.py's from_world==RELEASED handling.
"""
from __future__ import annotations

import logging

from fx import light_ownership

logger = logging.getLogger(__name__)


async def _best_effort(step, label: str) -> None:
    try:
        await step()
    except Exception:
        logger.exception("release: best-effort %s failed — released stands, "
                         "this device may still be lit until its own "
                         "timeout", label)


async def _release_spectra_devices() -> None:
    """The SPECTRA-owned live stack: reuses SpectraSide.deactivate(), which
    tears down the host (deactivates every virtual, then every device — Hue
    stops its stream, WLED releases realtime, dummy is a no-op) and the
    audio hub. Same call the handover's quiesce step already makes."""
    from spectra.services.handover import SpectraSide
    await SpectraSide().deactivate()


async def _release_ledfx_virtuals() -> list[str]:
    """The external LedFX service (port 8888): deactivate every active
    virtual via its REST API — never a systemctl stop/restart of that
    process from this path. Best-effort per virtual: one unreachable
    virtual must not stop the rest from being released. Returns the ids
    this attempted to deactivate (for logging/tests)."""
    from api import ledfx_client

    raw = await ledfx_client.get_all_virtuals(force=True)
    virtuals = raw.get("virtuals", raw) if isinstance(raw, dict) else {}
    active_ids = [vid for vid, v in virtuals.items()
                 if isinstance(v, dict) and v.get("active")]
    for vid in active_ids:
        try:
            ok = await ledfx_client.set_virtual_active(vid, False)
            if not ok:
                logger.warning("release: LedFX virtual %s did not confirm "
                               "deactivation", vid)
        except Exception:
            logger.exception("release: failed to deactivate LedFX virtual %s "
                             "— released stands, this virtual may still be "
                             "streaming", vid)
    return active_ids


async def release_room(reason: str = "owner panic release") -> light_ownership.OwnershipRecord:
    """THE PANIC HANDLE. Idempotent and always lands `released` (or raises
    OwnershipError only if a handover is genuinely mid-flight — see
    fx.light_ownership.release). Device-class cleanup is best-effort and
    keyed off who owned the room BEFORE this call, captured first since the
    record transition below overwrites it."""
    from_world = light_ownership.load().owner
    record = light_ownership.release(reason)

    if from_world == light_ownership.SPECTRA:
        await _best_effort(_release_spectra_devices, "spectra live stack")
    elif from_world == light_ownership.SPOT_EFFECTS:
        await _best_effort(_release_ledfx_virtuals, "external LedFX virtuals")
    # from_world == RELEASED: already released, nothing new to clean up.

    logger.warning("release: room released to Home Assistant (was %s): %s",
                   from_world, reason)
    return record
