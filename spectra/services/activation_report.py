"""The ACTIVATION REPORT — what the last activation of SPECTRA's live stack
actually brought up, and which light it had to leave dark, by name and
with the reason. The visible half of the owner's 2026-08-21 ruling:

    one unreachable device must not be able to keep his entire room dark.

Before that ruling the take-back from `released` (spectra/services/
handover.py, run_handover with from_world == RELEASED) aborted on ANY
device it could not confirm — six times in a row the night of 2026-08-21
on one WLED ("Dining Table") whose mDNS name would not resolve, and twice
the morning before on two kitchen sconces that merely answered too slowly
— each abort tearing down the twenty devices that HAD come up. Aborting
never saved the unreachable light (it was unreachable either way); it only
darkened the ones that worked. The orchestrator now commits such a
take-back PARTIALLY (the same policy resume_own_room already applied to a
restart, owner amendment 2026-08-13) — and a partial activation that is
only a log line is its own trap: he would be looking at one dark fixture
with no idea why. So every partial activation, from either path, lands
here, and from here it reaches every surface he actually looks at:

  - the take-back's own API response (`result: "committed-partial"` +
    this report — RoomOwnershipBar's toast names the skipped light),
  - `GET /spectra/api/ownership` → `activation` (the bar polls this every
    4 s; a persistent strip on every page names each still-dark light
    and why, with the age of its last recheck),
  - `GET /spectra/api/liveness` → `activation` (additive, informational —
    NEVER part of `healthy`: the liveness contract's `healthy` is virtual-
    level frame freshness + activation_gaps, and the frame watchdog's
    systemd dead-man reads `live.fresh()` only; a device-level skip must
    not restart-loop the service — see evaluate() there),
  - the Status page's ownership card,
  - the ownership record's durable history note at commit
    (fx.light_ownership.commit(detail=...)) — the one place that survives
    a restart.

STATUS HONESTY (the codebase's standing rule — ambient_music_gate.py's
"Status honesty", AGENTS.md "A write-time confirmation is a snapshot"):
the verdict taken at activation is a SNAPSHOT. Two of the three real
failure kinds this covers are transient — a slow WLED (valid address, no
answer inside the probe window) usually flips live=true on its own a few
seconds later once frames keep arriving; a name that did not resolve
comes back when the device is power-cycled. A report that still said
"skipped" over a light that had since come up would be a lie, and one
that said nothing over a light still dark would be the silent trap. So
run_supervised() re-asks reality for every still-dark device every
RECHECK_INTERVAL_S, through the SAME probe device_gaps() used
(live_host.LiveLights.probe_device_live — one definition of "confirmed
driving", never two), records the recheck's age, marks a device
`recovered` the moment it confirms, and — for a device whose driver never
got past name resolution (the vendored NetworkedDevice leaves it
`_destination=None`, inactive, and nothing in the render loop ever
re-resolves an inactive device) — retries the driver's OWN initialization
(`async_initialize()` + `activate()`, the identical calls a fresh
activation makes) so a light fixed after the take-back joins the running
show by itself instead of needing the whole room released and taken back
again to collect one fixture.

What this module deliberately does NOT do: change `healthy`; touch a
device that is confirmed driving; restore, rewrite, or reseed any config;
keep any opinion once the stack is down (status() reports nothing while
`live.active` is False, and SpectraSide.activate()/deactivate() clear it
outright — a new activation attempt always starts from a clean report).
Module-global state, no DI seam (the param_watchdog.py / dwell.py shape);
tests/conftest.py's autouse `_isolated_activation_report` resets it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

RECHECK_INTERVAL_S = 30.0          # same cadence as ownership_reconciler /
                                   # frame_watchdog — one more 30 s tick
RECHECK_PROBE_TIMEOUT_S = 3.0      # per-device json/info read, =
                                   # live_host.DEVICE_VERIFY_TIMEOUT_S

SOURCE_TAKE_BACK = "take-back"
SOURCE_RESUME = "resume"

KIND_UNRESOLVED = "unresolved"        # name/address never resolved — the
                                      # driver has no destination at all
KIND_UNREACHABLE = "unreachable"      # resolved, but no answer to our probe
KIND_NOT_RECEIVING = "not-receiving"  # answers, reports live=false — not
                                      # taking SPECTRA's stream


@dataclass
class SkippedDevice:
    device_id: str
    name: str
    kind: str
    why: str                      # one human sentence — what he sees
    reason: str                   # the verifier's own raw reason, verbatim
    address: Optional[str]
    first_seen_wall: float
    last_checked_wall: float
    recovered_wall: Optional[float] = None
    retries: int = 0              # driver re-initialization attempts

    @property
    def still_dark(self) -> bool:
        return self.recovered_wall is None

    def to_json(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        out = asdict(self)
        out["still_dark"] = self.still_dark
        out["last_checked_age_s"] = round(now - self.last_checked_wall, 1)
        out["recovered_age_s"] = (round(now - self.recovered_wall, 1)
                                  if self.recovered_wall is not None else None)
        return out


@dataclass
class ActivationReport:
    source: str                   # SOURCE_TAKE_BACK | SOURCE_RESUME
    at_wall: float
    expected_virtuals: int        # config-declared, genuinely-driven set
    up_virtuals: int              # of those, active + fresh at verification
    devices_total: int            # real devices behind the expected virtuals
    skipped: dict[str, SkippedDevice] = field(default_factory=dict)
    virtual_gaps: dict[str, str] = field(default_factory=dict)

    @property
    def partial(self) -> bool:
        return bool(self.skipped or self.virtual_gaps)

    @property
    def still_dark(self) -> list[SkippedDevice]:
        return [d for d in self.skipped.values() if d.still_dark]

    @property
    def recovered(self) -> list[SkippedDevice]:
        return [d for d in self.skipped.values() if not d.still_dark]

    def summary(self) -> str:
        """One line, names included — the log line, the toast, the history
        note."""
        parts = []
        dark = self.still_dark
        if dark:
            parts.append(
                f"{len(dark)} light(s) skipped: "
                + "; ".join(f"{d.name} ({d.why})" for d in dark))
        if self.recovered:
            parts.append(
                f"{len(self.recovered)} came back later: "
                + ", ".join(d.name for d in self.recovered))
        if self.virtual_gaps:
            parts.append(
                f"{len(self.virtual_gaps)} virtual(s) never came up: "
                + "; ".join(f"{vid}: {why}"
                            for vid, why in sorted(self.virtual_gaps.items())))
        if not parts:
            return "every expected light came up"
        return "; ".join(parts)

    def to_json(self) -> dict:
        now = time.time()
        return {
            "source": self.source,
            "at_wall_ms": int(self.at_wall * 1000),
            "age_s": round(now - self.at_wall, 1),
            "partial": self.partial,
            "expected_virtuals": self.expected_virtuals,
            "up_virtuals": self.up_virtuals,
            "devices_total": self.devices_total,
            "devices_skipped": len(self.skipped),
            "devices_still_dark": len(self.still_dark),
            "skipped": [d.to_json(now) for d in
                        sorted(self.skipped.values(), key=lambda d: d.name)],
            "virtual_gaps": dict(sorted(self.virtual_gaps.items())),
            "summary": self.summary(),
            "recheck_interval_s": RECHECK_INTERVAL_S,
        }


_report: Optional[ActivationReport] = None
_recheck_lock = asyncio.Lock()


def reset() -> None:
    """Test isolation (tests/conftest.py autouse). The recheck lock is
    rebuilt too: an asyncio.Lock binds to the first loop that contends on
    it, and every test drives its own asyncio.run() loop."""
    global _report, _recheck_lock
    _report = None
    _recheck_lock = asyncio.Lock()


def clear() -> None:
    """A new activation attempt starts from a clean report; a torn-down
    stack keeps no opinion about lights it no longer drives."""
    global _report
    if _report is not None:
        logger.info("activation report: cleared (%s)", _report.summary())
    _report = None


def current() -> Optional[ActivationReport]:
    """The report for the CURRENT live stack, or None. Self-gates on the
    stack being up: a report can never outlive the activation it describes,
    even if a clear() was missed somewhere."""
    from spectra.services.live_host import live
    if _report is None or not live.active:
        return None
    return _report


def _describe(device_id: str, reason: str) -> tuple[str, str, Optional[str], str]:
    """(name, kind, address, why) for one skipped device, read off the live
    device object when there is one (the real fx driver's own state is the
    ground truth for WHY — a device with no `_destination` never resolved,
    whatever the probe's exception text says)."""
    from spectra.services.live_host import live
    device = live.host.devices.get(device_id) if live.host is not None else None
    name = device_id
    configured = None
    destination = None
    if device is not None:
        cfg = getattr(device, "_config", None) or {}
        name = cfg.get("name") or getattr(device, "name", device_id) or device_id
        configured = cfg.get("ip_address")
        destination = getattr(device, "_destination", None)
    if device is not None and destination is None \
            and getattr(device, "type", None) in ("wled", "ddp", "e131", "hue"):
        kind = KIND_UNRESOLVED
        shown = configured or "(no address configured)"
        why = (f"address '{shown}' did not resolve — the light is not "
               f"reachable on the network")
    elif "live=false" in reason:
        kind = KIND_NOT_RECEIVING
        shown = destination or configured or "it"
        why = (f"{shown} answers but reports it is not receiving SPECTRA's "
               f"stream")
    else:
        kind = KIND_UNREACHABLE
        shown = destination or configured or "its address"
        why = (f"no answer from {shown} within the activation window — "
               f"the light may be slow, off, or unreachable")
    return name, kind, (destination or configured), why


def record_from_live(source: str, virtual_gaps: dict[str, str],
                     device_gaps: dict[str, str]) -> ActivationReport:
    """Build and install the report for the activation that just verified
    against the live stack's own state (expected/up virtuals, device
    roster). Called by run_handover's tolerant from-released path and by
    resume_own_room; both after activate(), before anything else reads it.
    A clean activation (no gaps at all) installs a non-partial report so
    status() can say "every expected light came up" rather than nothing."""
    global _report
    from spectra.services.live_host import live
    now = time.time()
    expected = set(live.expected_active_ids)
    up = expected - set(virtual_gaps)
    devices_total = len(live.expected_device_ids())
    skipped: dict[str, SkippedDevice] = {}
    for device_id, reason in sorted(device_gaps.items()):
        name, kind, address, why = _describe(device_id, reason)
        skipped[device_id] = SkippedDevice(
            device_id=device_id, name=name, kind=kind, why=why,
            reason=reason, address=address,
            first_seen_wall=now, last_checked_wall=now)
    _report = ActivationReport(
        source=source, at_wall=now,
        expected_virtuals=len(expected), up_virtuals=len(up),
        devices_total=devices_total, skipped=skipped,
        virtual_gaps=dict(virtual_gaps))
    if _report.partial:
        logger.critical(
            "activation report (%s): PARTIAL — %d/%d virtual(s) up, "
            "%d/%d device(s) confirmed; %s — every other light stays up; "
            "rechecking the skipped ones every %.0fs (GET /spectra/api/"
            "ownership → activation)",
            source, len(up), len(expected), devices_total - len(skipped),
            devices_total, _report.summary(), RECHECK_INTERVAL_S)
    return _report


def status() -> Optional[dict]:
    """Full shape for GET /spectra/api/ownership (the bar's 4 s poll) and
    the Status page. None while the stack is down or nothing was recorded."""
    report = current()
    return report.to_json() if report is not None else None


def liveness_summary() -> Optional[dict]:
    """Compact, additive slice for GET /spectra/api/liveness — informational
    only, NEVER part of `healthy` (see the module docstring)."""
    report = current()
    if report is None:
        return None
    return {
        "source": report.source,
        "partial": report.partial,
        "devices_total": report.devices_total,
        "devices_still_dark": len(report.still_dark),
        "skipped": [
            {"device_id": d.device_id, "name": d.name, "kind": d.kind,
             "why": d.why, "still_dark": d.still_dark,
             "last_checked_age_s": round(time.time() - d.last_checked_wall, 1)}
            for d in sorted(report.skipped.values(), key=lambda d: d.name)],
        "virtual_gaps": dict(sorted(report.virtual_gaps.items())),
    }


async def _retry_driver_init(device) -> bool:
    """The vendored driver's OWN initialization, again — exactly what a
    fresh activation would have done for this device had it been reachable
    then: NetworkedDevice/WLEDDevice.async_initialize() (resolve the
    address, contact the device for its config, rebuild the DDP sender)
    followed by activate() (start sending; the virtual's segments on this
    device were already registered at virtual activation and flush skips
    it only while it is inactive). Returns True when the driver now has a
    destination. Every exception is the driver's normal "still not there"
    and is logged at debug — this runs every recheck for a still-dark
    light and must be quiet about it."""
    init = getattr(device, "async_initialize", None)
    if init is None:
        return False
    try:
        await init()
    except Exception as exc:
        logger.debug("activation report: %s re-init failed: %r",
                     getattr(device, "id", "?"), exc)
    if getattr(device, "_destination", None) is None:
        return False
    try:
        device.activate()
    except Exception as exc:
        logger.debug("activation report: %s re-activate failed: %r",
                     getattr(device, "id", "?"), exc)
        return False
    return True


async def recheck(probe_timeout_s: float = RECHECK_PROBE_TIMEOUT_S,
                  retry_init: bool = True) -> Optional[ActivationReport]:
    """Re-ask reality for every still-dark skipped device; mark the ones
    that confirm as recovered, stamp the others' last_checked, and (when
    `retry_init`) retry the driver's own initialization for a device that
    never resolved. Serialized (one recheck at a time). Returns the
    (possibly updated) report, or None when there is nothing to recheck."""
    from spectra.services import device_relocation
    from spectra.services.live_host import live
    async with _recheck_lock:
        report = current()
        if report is None or not report.still_dark:
            return report
        now = time.time()
        dark_ids = [d.device_id for d in report.still_dark]
        if retry_init and live.host is not None:
            for device_id in dark_ids:
                entry = report.skipped[device_id]
                device = live.host.devices.get(device_id)
                if device is None:
                    continue
                # A RELOCATED DEVICE HAS A DESTINATION AND IS STILL DARK.
                # A literal pinned IP "resolves" verbatim (fx/utils.py::
                # resolve_destination never contacts anything), so a fixture
                # that took a new DHCP lease keeps a destination that means
                # nothing, is never re-inited by the rule below, and stays
                # dark forever — the 2026-09-04 sconce, exactly. Ask its
                # hardware identity where it actually is FIRST; a device
                # with no stored identity, or one whose pin is still right,
                # costs one json/info and changes nothing (spectra/services/
                # device_relocation.py).
                moved = False
                try:
                    location = await device_relocation.reconcile(
                        device, host=live.host)
                    moved = location is not None and location.moved
                except Exception:
                    logger.debug("activation report: %s relocation check "
                                 "failed", device_id, exc_info=True)
                # Only a driver with no destination needs a re-init; a
                # resolved-but-silent device is already being sent frames
                # and only needs to be asked again. A device that just MOVED
                # needs one too — its sender was built against the old
                # address.
                if moved or getattr(device, "_destination", None) is None:
                    entry.retries += 1
                    await _retry_driver_init(device)
        confirmed = await live.probe_devices(dark_ids, probe_timeout_s)
        now = time.time()
        for device_id in dark_ids:
            entry = report.skipped[device_id]
            entry.last_checked_wall = now
            if device_id in confirmed:
                # Refresh WHY from the driver's current state — a name that
                # resolved on this retry but whose light still doesn't
                # answer moves from "did not resolve" to "no answer".
                _, kind, address, why = _describe(device_id, confirmed[device_id])
                entry.kind, entry.address, entry.why = kind, address, why
                entry.reason = confirmed[device_id]
                continue
            entry.recovered_wall = now
            logger.warning(
                "activation report: skipped light RECOVERED — %s (%s) is now "
                "confirmed driving, %.0fs after the %s",
                entry.name, device_id, now - report.at_wall, report.source)
        if not report.still_dark:
            logger.warning("activation report: every skipped light is back — "
                           "%s", report.summary())
        return report


async def run_supervised() -> None:
    """Own asyncio task in spectra/app.py's lifespan (the 2026-08-12
    lesson: monitoring must not die with the monitored). Idle-cheap: the
    recheck returns at once when no report is live or nothing is dark."""
    while True:
        try:
            await recheck()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("activation report recheck crashed (retrying): %r",
                         exc)
        await asyncio.sleep(RECHECK_INTERVAL_S)
