"""DID THE FIXTURES ACTUALLY COME UP? — the measurement the window's own
200 cannot make.

River powers the sconce mains off SPECTRA's `window_open` event
(`spectra/services/pretake_ping.py`). Her answer says SHE ACTED. It does
not say a sconce is powered, that its controller booted, or that anything
on this network can reach it — and a night that takes the room on the
strength of a 200 measures a dark fixture and calls the result a map. This
module is the read-back: the run's own WLED fixtures are asked, directly,
until they answer or the budget runs out.

It is the same discipline as `docs/SPECTRA_SPEC.md` §64 one service further
out — his Hue bridge 2xx's a write whether or not the bulb took it, so
`ambient.py` reads every light back; River answers 200 whether or not the
mains came up, so this reads every fixture back.

────────────────────────────────────────────────────────────────────────────
A FIXTURE IS FOUND BY WHAT IT IS, NEVER BY WHERE IT WAS
────────────────────────────────────────────────────────────────────────────

A MAINS CYCLE IS EXACTLY WHEN A WLED TAKES A NEW DHCP LEASE. So polling the
stored `ip_address` is the one thing this must not do on its own:
`fx/device_identity.py` is the binding statement for why — a device pinned
by location is INDISTINGUISHABLE FROM A DEAD ONE the moment it moves, and
here that confusion would abort a night whose sconces are lit and fine.

Every fixture carrying a `hardware_id` is therefore located by
`device_identity.locate()`: the pin first (confirmed by reading the MAC
back, so a neighbour answering at the old address is never mistaken for
ours), then WLED's own mDNS name derived from that same MAC, then addresses
a sibling that IS up already knows about, and only at the very end a bounded
sweep of the old pin's /24. A fixture with NO stored identity can only be
asked at its pin — and when it answers, its MAC is LEARNED and written back,
so the next night has an identity to find it by. That is
`WLEDDevice.learn_identity`'s own lazy discipline, from the one place that
gets to see a `json/info` before the stack is up.

THE SWEEP RUNS ONCE, AT THE END. It is up to 254 probes; running it every
poll would spend the whole budget on the cheapest-to-fail path. So the
cheap rungs run every round and the sweep runs on the LAST round only —
which means the stated ceiling is the budget PLUS one sweep, exactly the
way `fixture_brightness.RESTORE_BUDGET_S` is the budget plus one attempt.

────────────────────────────────────────────────────────────────────────────
THREE ANSWERS, AND THE MIDDLE ONE IS THE ONLY ONE THAT STOPS A NIGHT
────────────────────────────────────────────────────────────────────────────

    resolved=True    every watched fixture answered (or there were none to
                     watch — a run that drives no WLED has no mains
                     dependency, and saying so is not the same as failing)
    resolved=False   at least one never answered inside the whole budget.
                     THE ONLY VALUE A CALLER REFUSES ON.
    resolved=None    NOTHING WAS WAITED FOR — a zero budget, the documented
                     off switch. "We did not check" is not "we checked and
                     it is broken": `witness.VERDICT_UNAVAILABLE`'s own
                     three-state rule, and `night_exit`'s DARK vs UNKNOWN.

────────────────────────────────────────────────────────────────────────────
WHAT IT NEVER DOES
────────────────────────────────────────────────────────────────────────────

IT DRIVES NOTHING. Every request it makes is a `GET /json/info` or
`GET /json/nodes` — a read. It switches no light on, changes no brightness,
activates no virtual and takes no room. THE SCONCE MAINS RULE is untouched:
no Home Assistant entity is named or reached from here, and the only reason
a sconce's mains moves at all is that RIVER moved it, off an event this
side merely sent.

IT NEVER FABRICATES AN ADDRESS. A device that will not answer is reported
missing, by name, with the pin it was asked at — never given a guessed
address and never assumed dead. And it persists a relocation ONLY while
SPECTRA does not hold the live stack: with a host up, `fx.facade`'s own
writes own that file, and a second writer racing it is how a config gets
half-written. A relocated fixture is still FOUND either way; persisting is
what saves the next restart from having to find it again.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from spectra import config as scfg

logger = logging.getLogger(__name__)

#: The device types this waits on. WLED is the only networked fixture class
#: that can be asked "are you there" over plain HTTP before anything is
#: activated — a Hue bulb is behind a bridge that answers whether or not the
#: bulb has power, and a dummy has nothing to answer with.
WATCHED_TYPES = ("wled",)

#: How often the pending fixtures are re-asked. Two seconds: a WLED that has
#: just had its mains restored takes seconds to boot and associate, and a
#: tighter loop would only spend the budget faster on the same answer.
POLL_INTERVAL_S = 2.0

#: One probe's own budget — deliberately `fx.devices.wled`'s identity-probe
#: timeout rather than a second, looser number, so this asks in exactly the
#: way the take's own relocation asks.
PROBE_TIMEOUT_S = 0.5


@dataclass(frozen=True)
class Fixture:
    """One fixture to wait for, as the stored config describes it."""
    device_id: str
    name: str
    pinned: str
    hardware_id: str = ""


@dataclass
class WaitResult:
    """What the room's own fixtures said back. `resolved` is the whole
    verdict; everything else is why."""

    resolved: Optional[bool] = None
    detail: str = ""
    waited_s: float = 0.0
    budget_s: float = 0.0
    #: device ids this waited on, in config order
    watched: list = field(default_factory=list)
    #: [{id, name, address, via}] — answered, and where
    up: list = field(default_factory=list)
    #: [{id, name, pinned, hardware_id}] — never answered
    missing: list = field(default_factory=list)
    #: [{id, name, from, to, via}] — answered somewhere other than its pin
    relocated: list = field(default_factory=list)
    #: ids whose MAC was learned here for the first time
    learned: list = field(default_factory=list)
    #: ids whose stored config was updated on disk
    persisted: list = field(default_factory=list)
    #: whether the last-resort subnet sweep was reached
    swept: bool = False

    def as_dict(self) -> dict:
        return {"resolved": self.resolved, "detail": self.detail,
                "waited_s": round(self.waited_s, 2),
                "budget_s": round(self.budget_s, 2),
                "watched": list(self.watched), "up": list(self.up),
                "missing": list(self.missing),
                "relocated": list(self.relocated),
                "learned": list(self.learned),
                "persisted": list(self.persisted), "swept": self.swept}


# ── reading the stored config ──────────────────────────────────────────────

def _config_path(config_dir: Optional[Any] = None) -> Path:
    return Path(str(config_dir or scfg.FX_LIVE_CONFIG_DIR)) / "config.json"


def load_stored(config_dir: Optional[Any] = None) -> dict:
    """The fx-live config, or `{}` when it cannot be read. `{}` is treated
    by every caller as "nothing to wait for", never as "no fixtures exist":
    an unreadable config already refuses the take one gate further on
    (`handover.SpectraSide.readiness_problems`), and inventing a fixture
    failure on top of that would name the wrong problem."""
    try:
        raw = json.loads(_config_path(config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("sconce wait: fx-live config unreadable (%s): %s",
                       _config_path(config_dir), exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def fixtures_from(raw: dict,
                  device_ids: Optional[Iterable[str]] = None) -> list[Fixture]:
    """The watched fixtures of this config, narrowed to `device_ids` when
    the caller named a scope.

    `device_ids=None` means the WHOLE config — the widening direction, and
    the same one `take_scope.resolve()` takes when it cannot narrow: waiting
    for a fixture the run will not drive costs a moment, and skipping one it
    WILL drive costs the night."""
    wanted = None if device_ids is None else {str(d) for d in device_ids}
    out: list[Fixture] = []
    for entry in raw.get("devices") or []:
        if not isinstance(entry, dict):
            continue
        device_id = str(entry.get("id") or "")
        if not device_id or str(entry.get("type") or "") not in WATCHED_TYPES:
            continue
        if wanted is not None and device_id not in wanted:
            continue
        cfg = entry.get("config") or {}
        out.append(Fixture(
            device_id=device_id,
            name=str(cfg.get("name") or entry.get("name") or device_id),
            pinned=str(cfg.get("ip_address") or ""),
            hardware_id=str(cfg.get("hardware_id") or "")))
    return out


# ── the probes (reads only — see the module docstring) ─────────────────────

async def _read_info(address: str) -> Optional[dict]:
    """One `GET /json/info`, or None. `fx.devices.wled.read_info` verbatim,
    in a thread — ONE definition of this read, so the wait asks in exactly
    the way `device_identity.locate`'s own confirmation step does. The
    import is local so this module stays cheap for a host that never waits
    for anything."""
    from fx.devices.wled import read_info
    return await asyncio.to_thread(read_info, address, PROBE_TIMEOUT_S)


async def _read_nodes(address: str) -> list:
    from fx.devices.wled import read_node_addresses
    return await asyncio.to_thread(read_node_addresses, address,
                                   PROBE_TIMEOUT_S)


async def _resolve_host(hostname: str) -> Optional[str]:
    """A hostname to an address, or None. `WLEDDevice._resolve_host`'s own
    shape: a name that does not resolve is an ordinary "not this way", not
    an error to report."""
    try:
        return await asyncio.to_thread(socket.gethostbyname,
                                       hostname.rstrip("."))
    except (socket.gaierror, OSError, UnicodeError):
        return None


@dataclass
class Probes:
    """The I/O seam, so every path here is proven against a fake network and
    never against his — `fx/device_identity.py`'s own posture."""
    read_info: Any = _read_info
    read_nodes: Any = _read_nodes
    resolve_host: Any = _resolve_host


async def _locate(fixture: Fixture, probes: Probes, *, peers: list,
                  sweep: bool):
    """Where this fixture actually is, or None. Identity when we have one,
    the pin alone when we do not."""
    from fx import device_identity

    async def read_mac(address):
        return device_identity.mac_from_info(await probes.read_info(address))

    if fixture.hardware_id:
        return await device_identity.locate(
            fixture.hardware_id, pinned_address=fixture.pinned or None,
            read_mac=read_mac, resolve_host=probes.resolve_host,
            peer_addresses=tuple(peers), sweep=sweep)
    if not fixture.pinned:
        return None
    info = await probes.read_info(fixture.pinned)
    if info is None:
        return None
    # IT ANSWERED, so this is the one moment its identity can be learned
    # before the stack is up. A body with no readable MAC is still "up" —
    # the fixture answered — it simply stays pinned by address.
    mac = device_identity.mac_from_info(info)
    return device_identity.Location(address=fixture.pinned, via="pinned",
                                    mac=mac or "")


# ── persisting what we found ───────────────────────────────────────────────

def _stack_is_live() -> bool:
    try:
        from spectra.services.live_host import live
        return getattr(live, "host", None) is not None
    except Exception:                                   # noqa: BLE001
        return False


def persist(updates: dict, *, config_dir: Optional[Any] = None) -> list:
    """Write learned identities and new addresses back into the fx-live
    config. `updates` is `{device_id: {"ip_address": ..., "hardware_id":
    ...}}`; only genuinely-changed fields are written and nothing is written
    at all when nothing changed.

    REFUSED WHILE THE LIVE STACK IS UP. With a host running, `fx.facade`'s
    own writes own this file and a second writer racing it is how a config
    gets half-written — and a fixture whose address we found is DRIVEN
    either way, because `WLEDDevice._contact` falls back to the same
    identity path. Persisting only saves the next restart the search."""
    if not updates:
        return []
    if _stack_is_live():
        logger.info("sconce wait: not persisting %s — the live stack owns "
                    "the fx-live config while it is up", sorted(updates))
        return []
    path = _config_path(config_dir)
    raw = load_stored(config_dir)
    entries = raw.get("devices")
    if not isinstance(entries, list):
        return []
    changed: list = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        wanted = updates.get(str(entry.get("id") or ""))
        if not wanted:
            continue
        cfg = entry.get("config")
        if not isinstance(cfg, dict):
            continue
        if all(cfg.get(k) == v for k, v in wanted.items()):
            continue
        cfg.update(wanted)
        changed.append(str(entry.get("id")))
    if not changed:
        return []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name,
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(raw, fh, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:                            # noqa: BLE001
        # NEVER FATAL. A fixture that was found is found; failing the wait
        # because the bookkeeping would not write would refuse a night over
        # a file permission.
        logger.warning("sconce wait: could not persist %s: %r", changed, exc)
        return []
    logger.warning("sconce wait: persisted address/identity for %s", changed)
    return changed


# ── the wait ───────────────────────────────────────────────────────────────

async def wait_for_fixtures(*, device_ids: Optional[Iterable[str]] = None,
                            budget_ms: Optional[int] = None,
                            poll_s: float = POLL_INTERVAL_S,
                            config_dir: Optional[Any] = None,
                            probes: Optional[Probes] = None,
                            clock=time.monotonic,
                            sleep=asyncio.sleep) -> WaitResult:
    """WAIT UNTIL THE RUN'S OWN WLED FIXTURES ANSWER, or say which did not.

    Never raises: an unreadable config, an unreachable network and a fixture
    that has been unplugged all come back as a `WaitResult` the caller
    reports and decides on. Reads only — see the module docstring."""
    budget_s = max(0.0, (scfg.window_wait_ms() if budget_ms is None
                         else int(budget_ms)) / 1000.0)
    raw = load_stored(config_dir)
    fixtures = fixtures_from(raw, device_ids)
    watched = [f.device_id for f in fixtures]

    if budget_s <= 0:
        # THE DOCUMENTED OFF SWITCH. Nothing is checked, so nothing is
        # claimed and nothing is refused — a night runs exactly as it did
        # before this feature existed.
        return WaitResult(resolved=None, budget_s=0.0, watched=watched,
                          detail=("The window was opened and no fixture was "
                                  "waited for (SPECTRA_WINDOW_WAIT_MS=0), so "
                                  "nothing here says whether they came up."))
    if not fixtures:
        return WaitResult(
            resolved=True, budget_s=budget_s, watched=[],
            detail=("No WLED fixture is in this run's scope, so there was "
                    "nothing to wait for — this run has no mains "
                    "dependency."))

    started = clock()
    deadline = started + budget_s
    pending = {f.device_id: f for f in fixtures}
    up: dict = {}
    relocated: list = []
    learned: list = []
    updates: dict = {}
    swept = False

    probes = probes or Probes()
    while True:
        # THE SWEEP IS THE LAST ROUND'S ALONE — see the module docstring.
        last_round = clock() + poll_s > deadline
        # SNAPSHOT BEFORE THE GATHER. `pending` is mutated below as
        # fixtures come up, so pairing results against a live view of it
        # would attribute one fixture's answer to another.
        batch = list(pending.values())
        peers = await _peers([up[k] for k in up], probes)
        found = await asyncio.gather(*(
            _check(f, probes, peers=peers,
                   sweep=last_round and bool(f.hardware_id))
            for f in batch))
        swept = swept or (last_round and any(f.hardware_id for f in batch))
        for fixture, location in zip(batch, found):
            if location is None:
                continue
            up[fixture.device_id] = {
                "id": fixture.device_id, "name": fixture.name,
                "address": location.address, "via": location.via}
            pending.pop(fixture.device_id, None)
            entry: dict = {}
            # `.moved` AND NOT AN ADDRESS COMPARISON. A fixture pinned by a
            # `.local` name resolves to a literal IP with `via="pinned"` —
            # it has not moved, and writing that IP back would replace the
            # identity handle he deliberately configured with the very kind
            # of location pin `fx/device_identity.py` exists to end.
            if location.moved and location.address:
                relocated.append({"id": fixture.device_id,
                                  "name": fixture.name,
                                  "from": fixture.pinned,
                                  "to": location.address,
                                  "via": location.via})
                entry["ip_address"] = location.address
            if location.mac and not fixture.hardware_id:
                learned.append(fixture.device_id)
                entry["hardware_id"] = location.mac
            if entry:
                updates[fixture.device_id] = entry
        if not pending or last_round:
            break
        await sleep(poll_s)

    waited = max(0.0, clock() - started)
    persisted = persist(updates, config_dir=config_dir)
    missing = [{"id": f.device_id, "name": f.name, "pinned": f.pinned,
                "hardware_id": f.hardware_id} for f in pending.values()]
    result = WaitResult(
        resolved=not missing, waited_s=waited, budget_s=budget_s,
        watched=watched, up=[up[k] for k in watched if k in up],
        missing=missing, relocated=relocated, learned=learned,
        persisted=persisted, swept=swept)
    result.detail = describe(result)
    if missing:
        logger.critical("sconce wait: %s did not answer in %.0fs — %s",
                        ", ".join(m["name"] for m in missing), waited,
                        "the room must not be taken dark")
    else:
        logger.warning("sconce wait: %d fixture(s) up in %.1fs%s",
                       len(up), waited,
                       f" ({len(relocated)} relocated)" if relocated else "")
    return result


async def _check(fixture: Fixture, probes: Probes, *, peers: list,
                 sweep: bool):
    try:
        return await _locate(fixture, probes, peers=peers, sweep=sweep)
    except Exception as exc:                            # noqa: BLE001
        # A probe that blew up is a non-answer, never an exception out of a
        # wait that sits on the night's critical path.
        logger.debug("sconce wait: %s probe failed: %r", fixture.device_id,
                     exc)
        return None


async def _peers(up_rows: list, probes: Optional[Probes]) -> list:
    """Addresses the fixtures that ARE up already know about — WLEDs
    discover each other, so one answering sconce can name the one that
    moved. A handful of candidates instead of a subnet."""
    if not up_rows:
        return []
    probes = probes or Probes()
    out: list = []
    for row in up_rows:
        try:
            for address in await probes.read_nodes(row.get("address") or ""):
                if address and address not in out:
                    out.append(address)
        except Exception:                               # noqa: BLE001
            continue
    return out


def describe(result: WaitResult) -> str:
    """The sentence a person reads at breakfast. Says what came up, what did
    not, and — when a fixture moved — that it moved, because a relocation
    found tonight is the thing that would have read as a dead sconce."""
    total = len(result.watched)
    if not result.missing:
        line = (f"All {total} fixture(s) answered "
                f"{result.waited_s:.0f}s after the window opened.")
        if result.relocated:
            moved = ", ".join(f"{r['name']} moved to {r['to']} "
                              f"(found via {r['via']})"
                              for r in result.relocated)
            line += f" {moved}."
        return line
    names = ", ".join(m["name"] for m in result.missing)
    return (f"{len(result.missing)} of {total} fixture(s) never answered "
            f"within {result.budget_s:.0f}s: {names}.")
