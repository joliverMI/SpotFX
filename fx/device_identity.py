"""FIND A DEVICE BY WHAT IT IS, NOT BY WHERE IT WAS (SpotFX-authored; not
fork code — see fx/VENDOR.md).

THE DEFECT THIS EXISTS FOR, twice in one evening on 2026-09-04: every WLED
in `storage/spectra/fx-live/config.json` is pinned by `ip_address` and
nothing else. When his kitchen sconce took a new DHCP lease the pinned
address stopped answering, and **a relocated device is indistinguishable
from a dead one when it is pinned by location** — the probe reported it
dark, the take-back reported "Failed to connect", and both were true
statements about an address that no longer meant anything.

`fx/utils.py::resolve_destination` cannot help: handed a literal IP it
returns that IP verbatim, with no contact and no check. So a pin that has
gone stale still "resolves" perfectly and fails one layer later.

THE FIX IS AN IDENTITY, AND THE IDENTITY IS THE MAC. A WLED reports it on
every `json/info` as `mac` (twelve lowercase hex digits, no separators), it
survives a lease, a reboot, a rename and a firmware update, and WLED's own
default mDNS name is DERIVED from it (`wled-<last six>`), so storing the MAC
gives us the hostname for free rather than a second thing to keep in sync.

    e0:8c:fe:5c:3a:78  ->  e08cfe5c3a78  ->  wled-5c3a78.local

THREE WAYS TO FIND IT, AND ONE WAY TO BELIEVE IT. `locate()` walks
candidate addresses cheapest-first and every one of them is confirmed the
SAME way — read `json/info` and require the MAC to match. A name that
resolves is never trusted on its own: avahi caches, and a cached answer
pointing at the wrong host is exactly the confident-wrong-answer this is
supposed to end.

  pinned   The address we already have. Checked FIRST and, when it matches,
           returned as `via="pinned"` with nothing changed — which is what
           makes a healthy device byte-identical to before this module
           existed.
  mdns     `wled-<mac6>.local` through the host resolver. Primary, because
           it is one lookup, WLED publishes it with no configuration, and
           it is measurably live on his host (nsswitch `mdns4_minimal`,
           avahi-daemon active, and two of his own devices are ALREADY
           pinned by `.local` names and work).
  peers    Addresses the caller gathered from a reachable sibling's
           `json/nodes` — WLEDs discover each other, so one answering
           fixture can name the rest. A handful of candidates, not a subnet.
  sweep    Last resort: the /24 the pinned address sat on, bounded by
           `sweep_limit` and `concurrency`. Ends in the same MAC check.

I/O IS INJECTED (`read_mac`, `resolve_host`), so every path here is proven
against a real HTTP server on loopback and never against his network. This
module holds no sockets, no requests import and no opinion about how a MAC
is fetched — `fx/devices/wled.py` supplies that.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional, Sequence

_LOGGER = logging.getLogger(__name__)

#: A WLED MAC as it appears in `json/info`: twelve lowercase hex digits.
_HEX12 = re.compile(r"^[0-9a-f]{12}$")

#: The suffix length WLED uses for its default mDNS name (`wled-XXXXXX`).
MDNS_SUFFIX_LEN = 6

#: How many hosts of a /24 a sweep may try, and how many at once. A sweep is
#: the fallback of the fallback; these bound its cost rather than tune it.
SWEEP_LIMIT = 254
SWEEP_CONCURRENCY = 24


def normalize_mac(raw: object) -> Optional[str]:
    """Twelve lowercase hex digits, or None. Accepts every spelling a human
    or a device might hand over — `e0:8c:fe:5c:3a:78`, `E0-8C-FE-5C-3A-78`,
    `e08cfe5c3a78` — because the backlog card records his six MACs
    colon-separated and WLED reports them bare."""
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[^0-9a-fA-F]", "", raw).lower()
    return cleaned if _HEX12.match(cleaned) else None


def mdns_name_for_mac(mac: str) -> Optional[str]:
    """WLED's own default mDNS name for this MAC. Derived, never stored
    separately — one identity, not two that can disagree."""
    normalized = normalize_mac(mac)
    if normalized is None:
        return None
    return f"wled-{normalized[-MDNS_SUFFIX_LEN:]}.local"


def mac_from_info(info: object) -> Optional[str]:
    """The MAC out of a WLED `json/info` body, normalized. None when the
    body is not a WLED's (no `mac`, or an unparseable one) — a device that
    will not say what it is never gets an identity invented for it."""
    if not isinstance(info, dict):
        return None
    return normalize_mac(info.get("mac"))


def looks_like_hostname(address: object) -> bool:
    """True for something that must be resolved (a `.local` name), False for
    a literal IP. `resolve_destination` returns a literal verbatim, so this
    is what tells a pin that was already an identity handle from one that
    only names a place."""
    if not isinstance(address, str) or not address:
        return False
    host = address.split(":", 1)[0].rstrip(".")
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


def subnet_candidates(address: object, limit: int = SWEEP_LIMIT) -> list[str]:
    """Every other host of the IPv4 /24 `address` sits on, nearest-first —
    a new DHCP lease usually lands close to the old one, so ordering by
    distance from the pin finds the common case in the first few reads.
    Empty for a hostname or an IPv6 address: there is no small, bounded
    neighbourhood to sweep, and inventing one would be a scan, not a
    lookup."""
    if not isinstance(address, str) or not address:
        return []
    host = address.split(":", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return []
    if ip.version != 4:
        return []
    network = ipaddress.ip_network(f"{ip}/24", strict=False)
    others = [str(h) for h in network.hosts() if str(h) != str(ip)]
    others.sort(key=lambda a: abs(int(ipaddress.ip_address(a)) - int(ip)))
    return others[:max(0, limit)]


@dataclass(frozen=True)
class Location:
    """Where a known identity actually is right now, and how we found it."""
    address: str
    via: str          # "pinned" | "mdns" | "peers" | "sweep"
    mac: str

    @property
    def moved(self) -> bool:
        return self.via != "pinned"


ReadMac = Callable[[str], Awaitable[Optional[str]]]
ResolveHost = Callable[[str], Awaitable[Optional[str]]]


async def locate(
    mac: str,
    *,
    pinned_address: Optional[str],
    read_mac: ReadMac,
    resolve_host: ResolveHost,
    peer_addresses: Sequence[str] = (),
    sweep: bool = True,
    sweep_limit: int = SWEEP_LIMIT,
    concurrency: int = SWEEP_CONCURRENCY,
) -> Optional[Location]:
    """The current address of the device with this MAC, or None.

    Cheapest-first, and every stage ends in the same MAC check (see the
    module docstring). Returns `via="pinned"` — the no-change answer — the
    moment the address we already have confirms itself, so the healthy case
    costs exactly one read and moves nothing.

    Never raises for an unreachable candidate: `read_mac`/`resolve_host`
    returning None IS the "not there" answer, and an exception from either
    is treated the same way. A caller that cannot reach anything gets None,
    which is honestly "we could not find it", not "it is dead"."""
    identity = normalize_mac(mac)
    if identity is None:
        return None

    tried: set[str] = set()

    async def check(address: Optional[str], via: str) -> Optional[Location]:
        if not address or address in tried:
            return None
        tried.add(address)
        try:
            found = await read_mac(address)
        except Exception as exc:                      # unreachable is normal
            _LOGGER.debug("identity: %s did not answer: %r", address, exc)
            return None
        if normalize_mac(found) == identity:
            return Location(address=address, via=via, mac=identity)
        return None

    async def resolve(hostname: Optional[str]) -> Optional[str]:
        if not hostname:
            return None
        try:
            return await resolve_host(hostname)
        except Exception as exc:
            _LOGGER.debug("identity: %s did not resolve: %r", hostname, exc)
            return None

    # 1. the pin we already have — the byte-identical path
    if pinned_address and not looks_like_hostname(pinned_address):
        hit = await check(pinned_address, "pinned")
        if hit is not None:
            return hit
    elif pinned_address:
        # already an identity handle; resolving it IS the pinned check
        resolved = await resolve(pinned_address)
        hit = await check(resolved, "pinned")
        if hit is not None:
            return hit

    # 2. mDNS, derived from the identity itself
    hit = await check(await resolve(mdns_name_for_mac(identity)), "mdns")
    if hit is not None:
        return hit

    # 3. addresses a reachable sibling already knows about
    for candidate in peer_addresses:
        hit = await check(candidate, "peers")
        if hit is not None:
            return hit

    # 4. the bounded neighbourhood of the old pin
    if sweep:
        candidates = [a for a in subnet_candidates(pinned_address, sweep_limit)
                      if a not in tried]
        hit = await _sweep(candidates, check, concurrency)
        if hit is not None:
            return hit
    return None


async def _sweep(candidates: Iterable[str], check, concurrency: int
                 ) -> Optional[Location]:
    """Read `candidates` `concurrency` at a time and stop at the first MAC
    match — in nearest-first order, so a lease that moved by two lands in
    the first batch and the remaining ~250 reads never happen."""
    batch: list[str] = []
    for address in candidates:
        batch.append(address)
        if len(batch) < max(1, concurrency):
            continue
        hit = await _sweep_batch(batch, check)
        if hit is not None:
            return hit
        batch = []
    if batch:
        return await _sweep_batch(batch, check)
    return None


async def _sweep_batch(batch: Sequence[str], check) -> Optional[Location]:
    results = await asyncio.gather(*(check(a, "sweep") for a in batch))
    for found in results:
        if found is not None:
            return found
    return None
