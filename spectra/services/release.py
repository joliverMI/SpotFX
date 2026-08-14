"""THE OWNER'S PANIC HANDLE — one press, everything lets go.

release_room() is NOT the S3 handover. Handing over swaps one writer for
another and is gated (SPECTRA_HANDOVER_ARMED) and staged (quiesce → verify →
activate → verify → commit) because a NEW writer is coming up and Hue/DDP
tolerate exactly one. Releasing has no new writer — there is nothing to
verify into existence — so it is one atomic step
(fx.light_ownership.release()) followed by best-effort device-class cleanup
and a post-cleanup verification read-back.
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

BOTH worlds' cleanup runs on every press, regardless of which one the
record SAYS was writing (merge-scout two-writers report, 2026-08-13): the
record can be wrong exactly when this button gets pressed — that incident
was the record saying `spectra` while a rogue external LedFX painted the
room too (started by systemd's Wants=, not by either app). Branching on
from_world would have released only the recorded owner and left the rogue
writer alone. Releasing is idempotent and going to no-writer is always
safe, so running both is free.

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
  LedFX    REST API (spectra/services/ledfx_release.py, a direct client —
  service  see its docstring for why this bypasses api.ledfx_client rather
           than asking its ownership gate for an exemption). This app never
           restarts or reaches into that process beyond its documented API.

Verification (spec gap closed 2026-08-13): a command is not proof. After
cleanup, _verify_released() reads real state back — the SPECTRA live stack
via live.active, the external LedFX service via the same
systemctl-is-active check handover.py's SpotEffectsSide uses, falling back
to a virtuals re-read over the direct client when the service is still
running. Runs on every press, including idempotent repeats, so a device
that ignored an earlier release is still caught. release_room() always
lands the record at `released` regardless of what verification finds
(same fail-safe discipline as above) but returns whether reality was
confirmed to match, so callers can surface a loud failure instead of
reporting a clean "released".

The way BACK is not here — it is the normal guarded handover
(run_handover(SPECTRA, ...)), still gated and staged, still readiness-gated.
See spectra/services/handover.py's from_world==RELEASED handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fx import light_ownership

logger = logging.getLogger(__name__)


async def _best_effort(step, label: str):
    """Runs `step`, swallowing any exception (logged) so a cleanup failure
    never re-opens the write gate. Returns the step's result, or None on
    failure."""
    try:
        return await step()
    except Exception:
        logger.exception("release: best-effort %s failed — released stands, "
                         "this device may still be lit until its own "
                         "timeout", label)
        return None


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
    from spectra.services import ledfx_release

    raw = await ledfx_release.get_all_virtuals()
    virtuals = raw.get("virtuals", raw) if isinstance(raw, dict) else {}
    active_ids = [vid for vid, v in virtuals.items()
                 if isinstance(v, dict) and v.get("active")]
    for vid in active_ids:
        try:
            ok = await ledfx_release.set_virtual_active(vid, False)
            if not ok:
                logger.warning("release: LedFX virtual %s did not confirm "
                               "deactivation", vid)
        except Exception:
            logger.exception("release: failed to deactivate LedFX virtual %s "
                             "— released stands, this virtual may still be "
                             "streaming", vid)
    return active_ids


async def _verify_released() -> tuple[bool, list[str]]:
    """Read real state back rather than trusting the cleanup calls' own
    claims (same discipline as handover.py's verify_quiesced). Runs
    unconditionally — including on an idempotent repeat press that skipped
    cleanup — so a device that never heard an earlier release is still
    caught."""
    from spectra.services.handover import SpotEffectsSide
    from spectra.services.live_host import live

    problems: list[str] = []
    if live.active:
        problems.append("spectra live stack still active after release")

    if not await SpotEffectsSide().verify_quiesced():
        try:
            from spectra.services import ledfx_release
            raw = await ledfx_release.get_all_virtuals()
            virtuals = raw.get("virtuals", raw) if isinstance(raw, dict) else {}
            still_active = sorted(
                vid for vid, v in virtuals.items()
                if isinstance(v, dict) and v.get("active"))
            if still_active:
                problems.append(
                    "external LedFX virtuals still active after release: "
                    + ", ".join(still_active))
        except Exception as exc:
            problems.append(
                "external LedFX service running but unreachable for "
                f"post-release verification: {exc!r}")
    return (not problems, problems)


@dataclass(frozen=True)
class ReleaseResult:
    """release_room()'s full outcome. `record` ALWAYS lands `released` (see
    fx.light_ownership.release) — `verified` is whether reality was
    confirmed to match, not whether the record moved."""
    record: light_ownership.OwnershipRecord
    from_world: str
    verified: bool
    problems: list[str] = field(default_factory=list)


async def release_room(reason: str = "owner panic release") -> ReleaseResult:
    """THE PANIC HANDLE. Idempotent and always lands `released` (or raises
    OwnershipError only if a handover is genuinely mid-flight — see
    fx.light_ownership.release). Device-class cleanup is best-effort, runs
    against BOTH worlds regardless of who the record said owned (see module
    docstring), and is followed by a verification read-back."""
    from_world = light_ownership.load().owner
    record = light_ownership.release(reason)

    if from_world != light_ownership.RELEASED:
        await _best_effort(_release_spectra_devices, "spectra live stack")
        await _best_effort(_release_ledfx_virtuals, "external LedFX virtuals")

    verified, problems = await _verify_released()
    if verified:
        logger.warning("release: room released to Home Assistant (was %s): %s",
                       from_world, reason)
    else:
        logger.critical(
            "release: VERIFICATION FAILED after release (was %s): %s — "
            "record says released but reality may not match: %s",
            from_world, reason, "; ".join(problems))
    return ReleaseResult(record=record, from_world=from_world,
                         verified=verified, problems=problems)
