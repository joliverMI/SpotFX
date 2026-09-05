"""A RELOCATED DEVICE IS RE-FOUND, AND THE NEW ADDRESS IS REMEMBERED.

SPECTRA's half of the identity fix. `fx/device_identity.py` is the binding
statement for HOW a WLED is found by its MAC; this module is the two things
that only SPECTRA can do, and the policy that keeps the cheap path cheap.

  PERSIST   `fx/devices/wled.py` learns a MAC and adopts a new address on
            the LIVE device object. That is enough to drive the fixture
            tonight and not enough to survive a restart — and the restart
            case is the one that matters most, because a process that comes
            up against a stale pin has nothing to contact and therefore
            nothing to learn an identity from. So a learned `hardware_id`
            and a reconciled `ip_address` are written back into
            `storage/spectra/fx-live/config.json` through the vendored
            `save_config`, exactly the call every facade write already makes
            — one write path, not a second one racing it.

            NOTHING IS MASS-REWRITTEN. A device is touched only when it
            actually learned an identity or actually moved; a save happens
            only when at least one device changed. His config is not
            migrated on deploy, and a device that never answers is never
            given a fabricated identity.

  RECOVER   `spectra/services/activation_report.py` rechecks still-dark
            devices every 30 s and re-inits any that never resolved. A
            RELOCATED device does not look like that: a literal pinned IP
            "resolves" verbatim (`fx/utils.py::resolve_destination` returns
            it without contacting anything), so it has a destination, is
            never re-inited, and stays dark forever. `reconcile()` is what
            that recheck now asks first.

THE SWEEP IS RATE-LIMITED, and that is the whole reason this module holds
state. mDNS is one lookup and costs nothing, so it runs on every recheck.
The /24 sweep is up to 254 HTTP probes and must not run every 30 s per dark
device — `SWEEP_COOLDOWN_S` lets it run once, then holds it off while the
cheap paths keep being tried. A device found by mDNS never reaches it.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Minimum wall time between two subnet sweeps for the SAME device. The
#: cheap paths (pinned, mDNS, peers) are unaffected and run every time.
SWEEP_COOLDOWN_S = 300.0

#: Last sweep per device id. Module-global like the other per-process
#: bookkeeping in this package; `reset()` is the test seam.
_last_sweep: dict[str, float] = {}


def reset() -> None:
    """Forget every sweep cooldown (tests; a fresh process starts empty)."""
    _last_sweep.clear()


def _is_wled(device: Any) -> bool:
    return getattr(device, "type", None) == "wled" and hasattr(
        device, "reconcile_address")


def _sweep_allowed(device_id: str, now: float) -> bool:
    last = _last_sweep.get(device_id)
    return last is None or (now - last) >= SWEEP_COOLDOWN_S


async def reconcile(device: Any, *, host: Any = None,
                    allow_sweep: bool = True) -> Optional[Any]:
    """Find `device` by its stored identity and adopt wherever it is.

    Returns the `fx.device_identity.Location` (`.moved` False when the pin
    was right) or None — None meaning "no identity stored" or "not found",
    never "dead". A healthy device costs one `json/info` and changes
    nothing, which is what keeps this safe to call from a poll.
    """
    if not _is_wled(device):
        return None
    if getattr(device, "hardware_id", None) is None:
        return None

    device_id = getattr(device, "id", "?")
    now = time.monotonic()
    sweep = allow_sweep and _sweep_allowed(device_id, now)

    peers: list[str] = []
    if host is not None:
        peers = await _peer_addresses(host, exclude_id=device_id)

    try:
        location = await device.reconcile_address(
            peer_addresses=peers, sweep=sweep)
    except Exception as exc:                              # never fatal
        logger.debug("relocation: %s reconcile failed: %r", device_id, exc)
        return None
    if sweep:
        _last_sweep[device_id] = now
    if location is not None and location.moved:
        logger.warning(
            "relocation: %s found by hardware id at %s (via %s)",
            device_id, location.address, location.via)
        persist(host, device)
    return location


async def _peer_addresses(host: Any, exclude_id: str) -> list[str]:
    """Addresses the room's OTHER reachable WLEDs already know about."""
    try:
        from fx.devices.wled import discover_peer_addresses
        siblings = [d for d in getattr(host, "devices", {}).values()
                    if _is_wled(d) and getattr(d, "id", None) != exclude_id]
        if not siblings:
            return []
        return await discover_peer_addresses(
            siblings, executor=getattr(host, "thread_executor", None))
    except Exception as exc:                              # best effort
        logger.debug("relocation: peer discovery failed: %r", exc)
        return []


def persist(host: Any, *devices: Any) -> list[str]:
    """Write each device's current `ip_address`/`hardware_id` back into the
    fx-live config, and save only if something actually changed. Returns the
    ids that were updated."""
    if host is None:
        return []
    config = getattr(host, "config", None)
    if not isinstance(config, dict):
        return []
    entries = config.get("devices")
    if not isinstance(entries, list):
        return []
    by_id = {e.get("id"): e for e in entries if isinstance(e, dict)}

    changed: list[str] = []
    for device in devices:
        device_id = getattr(device, "id", None)
        entry = by_id.get(device_id)
        if entry is None or not isinstance(entry.get("config"), dict):
            continue
        stored = entry["config"]
        live = getattr(device, "_config", {}) or {}
        wanted = {k: live.get(k) for k in ("ip_address", "hardware_id")
                  if live.get(k)}
        if all(stored.get(k) == v for k, v in wanted.items()):
            continue
        stored.update(wanted)
        changed.append(device_id)

    if not changed:
        return []
    try:
        from fx.config import save_config
        save_config(config=config, config_dir=host.config_dir)
    except Exception as exc:
        logger.warning("relocation: could not persist %s: %r", changed, exc)
        return []
    logger.info("relocation: persisted identity/address for %s", changed)
    return changed


def learn_from_live(host: Any) -> list[str]:
    """Persist every hardware id the live devices have learned but the
    config does not carry yet. Called once after an activation, so a device
    that answered ONCE is re-findable forever after — including across the
    restart where its address has already changed and there is nothing left
    to ask."""
    if host is None:
        return []
    devices = [d for d in getattr(host, "devices", {}).values() if _is_wled(d)]
    return persist(host, *devices)
