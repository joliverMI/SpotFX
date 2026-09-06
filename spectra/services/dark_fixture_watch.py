"""THE DARK FIXTURE WATCH — a light we are streaming to that is not lit.

His report, twice, on the same fixture and with the same blind spot under
it (backlog `spectra-tv-backlight-dark-recurring`, standing order 12):

  * 2026-08-15 — `tv-backlight` reported `on=false` while SPECTRA streamed
    to it at ~54 fps. The engine was writing light data into a switched-off
    fixture, and every health reading we serve said FINE: the liveness
    endpoint 200-healthy, `activation_gaps` empty, `devices[].online` true,
    frames flowing. He found it BY EYE.
  * 2026-09-06 — the same fixture went UNREACHABLE the instant SPECTRA took
    the room, and came back the moment she released. That one WAS named,
    but only because it happened during activation. The same fixture
    dropping ten minutes into a show is invisible to every surface in this
    codebase, forever, because nothing re-asks a device that was confirmed
    once.

WHAT WAS ACTUALLY BLIND, precisely — three separate things, each of which
looks like health:

  1. `probe_device_live` (the one device-level read we had) asks WLED's
     `json/info` for `live` and nothing else. `live` means "realtime data
     is arriving", which is TRUE of a fixture that is switched off and
     showing nothing. His exact 2026-08-15 state passes that check.
  2. Nothing re-probes a CONFIRMED device. `activation_report.recheck()`
     re-asks only the devices already named dark AT ACTIVATION
     (`report.still_dark`) — by construction it can never notice a light
     that was fine and then went.
  3. `devices[].online` on the liveness payload is `Device._online`, which
     for a DDP/UDP fixture is set True at construction and only ever
     cleared by an `OSError` from `sendto` — which a UDP unicast to a dead
     host does not raise on Linux. It is not a reachability signal at all;
     it reads healthy over a fixture that has been off the network for
     hours.

THE CLAIM THIS MODULE MAKES, and why it is narrow on purpose: for every
fixture SPECTRA IS PUSHING FRAMES AT RIGHT NOW
(`live_host.LiveLights.streaming_device_ids` — a virtual that is active AND
flushing fresh frames, onto a device that is active), read back what the
fixture says it is doing and name it when the answer is "nothing". Being
streamed is the precondition that turns a dark light into a FAULT rather
than an ordinary off light: a fixture nobody is writing to is allowed to be
off, and a virtual that stopped flushing is `activation_gaps`' business,
already named there. The two detections therefore cannot both claim the
same silence.

FOUR NAMED KINDS, each claiming only what its read established, told apart
because the next step differs for each:
  unreachable    it did not reply to our HTTP read within `HTTP_TIMEOUT_S`
                 (his 2026-09-06 shape). That is ALL this kind claims: a
                 controller too busy taking the stream to answer looks the
                 same from here as one off the network, and whether the
                 light is lit cannot be read until it answers — so its
                 sentence says "not answering", never "dark".
  not-receiving  it answers, and says our stream is not arriving
  switched-off   it takes our stream and is OFF at its own firmware (his
                 2026-08-15 shape)
  blacked-out    it takes our stream with master brightness 0

IT NEVER WRITES. Detection is the whole deliverable, by the backlog's own
ruling ("BUILD THE DETECTION, NOT THE CURE"). It does not power a fixture
on, does not lower a refresh rate, does not re-initialize a driver and does
not release the room. Repair paths already exist and are owned elsewhere
(`activation_report.recheck` re-inits a driver that never resolved;
`device_relocation` re-finds a fixture that moved); a second, differently-
motivated writer reaching for the same fixtures is how two mechanisms start
fighting over one light. What this module produces is a sentence on a
status surface and a CRITICAL log line — which is exactly what was missing
the night he had to notice by eye.

WHERE IT SHOWS UP (the surfaces that reported healthy over his dark light):
  * `GET /spectra/api/liveness` → `dark_fixtures` — ADDITIVE and
    INFORMATIONAL, and deliberately NEVER part of `healthy`. That is the
    activation report's own established rule and it is load-bearing: the
    fleet's external checker and the systemd dead-man read this, and one
    unreachable fixture must not restart-loop the SPECTRA process. A
    restart would not fix a fixture that is off at its own firmware, and it
    WOULD darken the twenty lights that are working — the exact trade the
    owner already ruled on for partial activation (2026-08-21).
  * `GET /spectra/api/ownership` → `dark_fixtures` — the room bar polls
    this every 4 s and renders it next to the activation strip, which is
    where he already looks for "which light is not working".
  * `GET /spectra/api/engine/status` → `dark_fixtures`.
  * A CRITICAL log line on every fault raised, a WARNING when one clears.

THRESHOLD — `FAULT_AFTER_S` = 60 s over at least `MIN_BAD_READS` = 3
consecutive reads, swept every `SWEEP_INTERVAL_S` = 30 s, so a genuine
fault is named within 90 s worst case and a fixture is never accused on one
noisy read. Justified rather than picked: a WLED coming up under a real
take-back has been measured taking 6.2-6.4 s to raise its own `live` flag
(`live_host.DEVICE_LIVE_DEADLINE_S`'s own note), his bridge and fixtures
routinely lose a single request under a write burst
(`AMBIENT_WRITE_STAGGER_MS`'s history), and a fixture rebooting into its
own firmware show takes a few seconds — 60 s is an order of magnitude
above all three, and short enough that a dropped light is named inside one
song rather than one evening. A kind CHANGE (unreachable → switched-off)
does NOT restart the clock: the claim being made is "this fixture has been
dark continuously for X", which stays true across a change in HOW it is
dark; the currently-reported kind is simply the latest read's.

AN UNKNOWN READING NEVER CLEARS A NAMED FAULT. Only a read that positively
says lit does. A fixture that answers `json/info` but loses its `json/state`
reply — a single dropped request, ordinary for a controller under a write
burst, which is the very condition this watch exists for — is neither
evidence of light nor of darkness: it is listed as unchecked for that
sweep and the suspicion (or fault) stands untouched, clock and all. A lost
`json/info` in the same sweep is judged unreachable and CONTINUES the
clock; a lost `json/state` must therefore not reset it either, or the
switched-off kind could never ripen on a fixture that drops one request
in three. Two cases DO drop the claim, because in them we are no longer
making it: a fixture that has genuinely stopped being checkable (not a
WLED, or a driver with no client) and a fixture SPECTRA has stopped
streaming to. The reader itself raising is the most unknown reading there
is and is treated the same way: listed as unchecked, nothing touched.

THE BUDGET THAT DECIDES `unreachable` IS `HTTP_TIMEOUT_S`, and it binds
because it is handed to the vendored transport explicitly
(`WLED._wled_request(timeout=)`, still the unmodified production
transport). That transport's own default is 0.5 s, and a budget that only
bounded the outer wait would never bind — the first shipped version
declared 3 s and decided at 0.5 s. `READ_TIMEOUT_S` is the whole
two-request read's outer bound, nothing more. `probe_device_live` keeps
the vendored default so the activation gate's timing is byte-identical.

THE SUMMARY LINE COUNTS ONLY READS THAT POSITIVELY SAID LIT as "confirmed
lit". A fixture reading dark inside the ripening window is accounted for
as "reading dark or not answering, not yet named" from its first bad read
— never folded into the lit count while its clock runs — and that clause
is built from the STANDING suspicions, not from this sweep's reads, so a
watched fixture stays in the sentence across a lost reply exactly as it
stays in `watching`. Two different absences get two different words:
"not checkable" is said only of a device that genuinely cannot be asked
(not a WLED, or a driver with no client — a property of the device, and
the claim is dropped because we can no longer make it), while a lost
reply or a reader crash on a fixture we CAN ask is "unchecked this sweep"
— a transient miss on a light we are actively watching, which touches
nothing.

WHEN IT STANDS DOWN ENTIRELY, and every suspicion is dropped:
  * the live stack is down, or the ownership record does not say SPECTRA
    owns — we are not streaming to anything and have no standing to
    comment on his fixtures;
  * a colour-set preview or a flare-preview hold is active — which is also
    how EVERY capture run, room mapping, commissioning pass and room effect
    holds the room (`flare_preview_hold.open_program_hold`), and those
    deliberately move a fixture's power and brightness
    (`night_power.py`, `fixture_brightness.py`). Reporting a fault over a
    run's own choreography would be an accusation about our own behaviour;
  * the engine is dark (the recording executor) — the quiet take of the
    self-taking night (`night_take.py`) drives a legitimately black room
    with `night_power` moving fixture power underneath it. That window has
    its own honest read-back at the end (`night_exit.py`), which is the
    right instrument for it.

ROOT CAUSE, as far as an offline investigation honestly reaches: NOTHING in
the SPECTRA write path distinguishes his .236 from the WLEDs that survive
the same take. `WLEDDevice.flush` -> `DDPDevice.flush` -> `send_out` is one
code path with no per-device branch; the packet shape is a pure function of
`pixel_count` (560 px = 2 DDP datagrams a frame, ~120/s and ~100 KB/s at the
default 60 fps) and his larger fixtures push strictly MORE through the same
code without dropping. The fault tracks the STREAM — it arrives on
activation and clears on release — which is a controller saturating, not a
wrong address or a malformed packet. What DID change on our side is the
RATE, and for a good reason: before the S3 process split the render threads
were frozen by the other process's GIL bursts, and the split restored them
to their configured rate. So the lever is the per-device `refresh_rate`
already in `Device.CONFIG_SCHEMA` and already editable on `/devices` — no
throttle was invented next to a knob that works. Its trade, named:
`Virtual.refresh_rate` is a `min` over the virtual's devices, so slowing his
`tv-backlight` also slows every other fixture on the same copy-mapped
virtual (the sibling-capping problem open PR #58 is about).

ADJACENT FINDING, REPORTED AND NOT FIXED HERE (it is ownership logic, out
of this task's scope, and deserves its own card): `ownership_reconciler.
_foreign_wled_sources` reads `wled.get_state()` and tests
`wled_state.get("live")` — but WLED reports `live` under `json/info` ONLY,
never under `json/state` (`fx/VENDOR.md` #8, verified against real devices
2026-08-14). That check is therefore dead: it can never see a foreign
realtime writer. Same family as this defect — a surface reporting fine
because it is asking the wrong endpoint.

Module-level state, no DI seam for the state itself (the param_watchdog.py
shape); `tests/conftest.py`'s autouse fixture calls `reset()`, and the
`Deps` dataclass is the injection seam for everything a sweep reads.
Executable proof: `tests/test_dark_fixture_watch.py`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_S = 30.0
FAULT_AFTER_S = 60.0
MIN_BAD_READS = 3
HTTP_TIMEOUT_S = 3.0
READ_TIMEOUT_S = 2 * HTTP_TIMEOUT_S + 1.0
RECENT_EVENTS = 50

KIND_UNREACHABLE = "unreachable"
KIND_NOT_RECEIVING = "not-receiving"
KIND_SWITCHED_OFF = "switched-off"
KIND_BLACKED_OUT = "blacked-out"

#: The clause each kind contributes to the sentence he reads. The fixture's
#: own name and address are filled in around it by `_describe`.
_KIND_CLAUSE = {
    KIND_UNREACHABLE: ("is not answering at {where} — no reply to SPECTRA "
                       "within {budget:g}s — while SPECTRA is streaming to "
                       "it; whether it is lit cannot be read until it "
                       "answers"),
    KIND_NOT_RECEIVING: ("answers at {where} but reports it is NOT receiving "
                         "SPECTRA's stream, while SPECTRA is streaming to it"),
    KIND_SWITCHED_OFF: ("is taking SPECTRA's stream at {where} but is "
                        "switched OFF at the fixture — the light is dark "
                        "while the show plays"),
    KIND_BLACKED_OUT: ("is taking SPECTRA's stream at {where} but its master "
                       "brightness is 0 — the light is dark while the show "
                       "plays"),
}


@dataclass
class Suspicion:
    """One fixture currently reading dark-while-streamed, and for how long.
    Becomes a FAULT (named on every surface) once it has held for
    FAULT_AFTER_S across at least MIN_BAD_READS consecutive reads."""
    device_id: str
    name: str
    address: Optional[str]
    kind: str
    why: str
    reason: str                       # the read's own words, verbatim
    first_bad_wall: float
    last_bad_wall: float
    reads: int = 1
    faulted_wall: Optional[float] = None

    @property
    def dark_for_s(self) -> float:
        return self.last_bad_wall - self.first_bad_wall

    @property
    def faulted(self) -> bool:
        return self.faulted_wall is not None

    def ripe(self) -> bool:
        return (self.reads >= MIN_BAD_READS
                and self.dark_for_s >= FAULT_AFTER_S)

    def to_json(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        return {
            "device_id": self.device_id,
            "name": self.name,
            "address": self.address,
            "kind": self.kind,
            "why": self.why,
            "reason": self.reason,
            "reads": self.reads,
            "dark_for_s": round(self.dark_for_s, 1),
            "first_seen_age_s": round(now - self.first_bad_wall, 1),
            "last_checked_age_s": round(now - self.last_bad_wall, 1),
            "faulted": self.faulted,
            "faulted_age_s": (round(now - self.faulted_wall, 1)
                              if self.faulted_wall is not None else None),
        }


@dataclass
class Deps:
    """Everything one sweep reads. `production_deps()` wires the real
    singletons; tests hand in the headless rig or plain fakes. NOTHING
    here writes — see the module docstring."""
    #: The devices SPECTRA is pushing frames at right now.
    streaming_device_ids: Callable[[], set]
    #: One fixture's own account of itself — live_host.LiveLights.read_emission.
    read_emission: Callable[..., Any]
    #: (name, address) for a device id, for the sentence he reads.
    describe_device: Callable[[str], tuple]
    #: Why the sweep must not run right now, or None.
    gate: Callable[[], Optional[str]]
    clock: Callable[[], float] = time.time


# ── module state ───────────────────────────────────────────────────────────

_suspects: dict[str, Suspicion] = {}
_events: deque = deque(maxlen=RECENT_EVENTS)
_faults_total = 0
_last_sweep: Optional[dict] = None
_last_sweep_wall: Optional[float] = None


def reset() -> None:
    global _faults_total, _last_sweep, _last_sweep_wall
    _suspects.clear()
    _events.clear()
    _faults_total = 0
    _last_sweep = None
    _last_sweep_wall = None


# ── the judgement (pure) ───────────────────────────────────────────────────

def judge(read) -> Optional[str]:
    """The kind of darkness this read describes, or None when the fixture
    is fine — or when we could not tell. Pure, so the rule can be proven
    without a room.

    `checkable` False (not a WLED, no client yet) and an absent state read
    are BOTH "no opinion", never a pass: this module reports what it could
    not check rather than counting it healthy, the same distinction
    `night_exit` draws between DARK and UNKNOWN."""
    if read is None or not getattr(read, "checkable", False):
        return None
    if not read.reachable:
        return KIND_UNREACHABLE
    if read.live is False:
        return KIND_NOT_RECEIVING
    if read.on is False:
        return KIND_SWITCHED_OFF
    if read.on is True and read.brightness is not None and read.brightness <= 0:
        return KIND_BLACKED_OUT
    return None


def _describe(kind: str, name: str, address: Optional[str]) -> str:
    where = address or "its address"
    return f"{name} " + _KIND_CLAUSE[kind].format(where=where,
                                                  budget=HTTP_TIMEOUT_S)


def _reason(read, kind: str) -> str:
    if kind == KIND_UNREACHABLE:
        return f"no answer within {HTTP_TIMEOUT_S:g}s: {read.error}"
    return (f"live={read.live} on={read.on} bri={read.brightness}"
            + (f" lip={read.source_ip}" if read.source_ip else ""))


# ── the sweep ──────────────────────────────────────────────────────────────

async def sweep(deps: Deps) -> dict:
    """One pass. Returns what it saw, and records/clears faults. Never
    raises for a fixture's sake: the reader itself failing is the most
    unknown reading there is, listed as unchecked and touching nothing."""
    global _last_sweep, _last_sweep_wall

    now = deps.clock()
    blocked = deps.gate()
    if blocked is not None:
        # Through _clear, not a bare .clear(): a fault that was NAMED must
        # not vanish off his strip without a line saying what took it away.
        for device_id in list(_suspects):
            _clear(device_id, now, f"the watch stood down — {blocked}")
        _suspects.clear()
        _last_sweep = {"gate": blocked, "streaming": 0, "checked": 0,
                       "lit": 0, "unchecked": [], "uncheckable": [],
                       "dark": []}
        _last_sweep_wall = now
        return _last_sweep

    streaming = sorted(deps.streaming_device_ids())
    reads = await asyncio.gather(
        *(deps.read_emission(device_id, READ_TIMEOUT_S,
                             http_timeout_s=HTTP_TIMEOUT_S)
          for device_id in streaming),
        return_exceptions=True)

    unchecked: list[str] = []
    uncheckable: list[str] = []
    dark: list[str] = []
    for device_id, read in zip(streaming, reads):
        if isinstance(read, BaseException):
            # The reader itself failed us, not the fixture. Say so; do not
            # convict a light on our own error, and do not absolve one.
            logger.warning("dark fixture watch: read of %s failed: %r",
                           device_id, read)
            unchecked.append(device_id)
            continue
        kind = judge(read)
        if kind is None:
            if not getattr(read, "checkable", False):
                uncheckable.append(device_id)
                _clear(device_id, now, "it can no longer be checked")
            elif not read.state_read:
                unchecked.append(device_id)
            else:
                _clear(device_id, now, "it reads lit again")
            continue
        dark.append(device_id)
        _mark(device_id, kind, read, now, deps)

    # A fixture we have stopped streaming to is no longer a claim we make.
    for device_id in [d for d in _suspects if d not in streaming]:
        _clear(device_id, now, "SPECTRA is no longer streaming to it")

    checked = len(streaming) - len(unchecked) - len(uncheckable)
    _last_sweep = {
        "gate": None,
        "streaming": len(streaming),
        "checked": checked,
        "lit": checked - len(dark),
        "unchecked": unchecked,
        "uncheckable": uncheckable,
        "dark": dark,
    }
    _last_sweep_wall = now
    return _last_sweep


def _mark(device_id: str, kind: str, read, now: float, deps: Deps) -> None:
    global _faults_total
    name, address = deps.describe_device(device_id)
    why = _describe(kind, name, address)
    reason = _reason(read, kind)
    suspect = _suspects.get(device_id)
    if suspect is None:
        _suspects[device_id] = suspect = Suspicion(
            device_id=device_id, name=name, address=address, kind=kind,
            why=why, reason=reason, first_bad_wall=now, last_bad_wall=now)
    else:
        # The clock does NOT restart on a changed kind — see the module
        # docstring: the claim is continuous darkness, not one shape of it.
        suspect.name, suspect.address = name, address
        suspect.kind, suspect.why, suspect.reason = kind, why, reason
        suspect.last_bad_wall = now
        suspect.reads += 1
    if suspect.faulted or not suspect.ripe():
        return
    suspect.faulted_wall = now
    _faults_total += 1
    _events.append({"at_wall_ms": int(now * 1000), "event": "raised",
                    "device_id": device_id, "name": name, "kind": kind,
                    "why": why, "reason": reason,
                    "dark_for_s": round(suspect.dark_for_s, 1)})
    logger.critical(
        "DARK FIXTURE: %s — %s (%s; %s). SPECTRA has been streaming to it "
        "and reading this back for %.0fs. Nothing is being written to "
        "fix this: see GET /spectra/api/liveness → dark_fixtures.",
        device_id, why, kind, reason, suspect.dark_for_s)


def _clear(device_id: str, now: float, how: str) -> None:
    suspect = _suspects.pop(device_id, None)
    if suspect is None:
        return
    if not suspect.faulted:
        return
    _events.append({"at_wall_ms": int(now * 1000), "event": "cleared",
                    "device_id": device_id, "name": suspect.name,
                    "kind": suspect.kind, "how": how,
                    "dark_for_s": round(suspect.dark_for_s, 1)})
    logger.warning(
        "dark fixture RECOVERED: %s (%s) — %s after %.0fs dark",
        suspect.name, device_id, how, suspect.dark_for_s)


# ── production wiring ──────────────────────────────────────────────────────

def _production_gate() -> Optional[str]:
    from fx import light_ownership
    from spectra.services import engine, flare_preview_hold, preview_pause
    from spectra.services.live_host import live
    if not live.active:
        return "live stack down"
    if light_ownership.load().owner != light_ownership.SPECTRA:
        return "spectra does not own the lights"
    if engine.executor.mode != "facade":
        return "engine dark (recording executor)"
    if preview_pause.active():
        return "preview active"
    if flare_preview_hold.active():
        return "flare preview hold active"
    return None


def _production_describe(device_id: str) -> tuple:
    """(name, address) off the live driver — the same shape
    `activation_report._describe` reads, so one light is called the same
    thing on both strips."""
    from spectra.services.live_host import live
    device = live.host.devices.get(device_id) if live.host is not None else None
    if device is None:
        return device_id, None
    cfg = getattr(device, "_config", None) or {}
    name = cfg.get("name") or getattr(device, "name", device_id) or device_id
    address = getattr(device, "_destination", None) or cfg.get("ip_address")
    return name, address


def production_deps() -> Deps:
    from spectra.services.live_host import live
    return Deps(
        streaming_device_ids=live.streaming_device_ids,
        read_emission=live.read_emission,
        describe_device=_production_describe,
        gate=_production_gate,
    )


# ── status surfaces ────────────────────────────────────────────────────────

def faults() -> list[Suspicion]:
    return [s for s in _suspects.values() if s.faulted]


def status() -> dict:
    """Full shape for GET /spectra/api/ownership and the engine status."""
    now = time.time()
    ripe = sorted(faults(), key=lambda s: s.name)
    watching = sorted((s for s in _suspects.values() if not s.faulted),
                      key=lambda s: s.name)
    return {
        "faults": [s.to_json(now) for s in ripe],
        "fault_count": len(ripe),
        "watching": [s.to_json(now) for s in watching],
        "faults_total": _faults_total,
        "recent": list(_events)[-10:],
        "last_sweep": _last_sweep,
        "last_sweep_age_s": (round(now - _last_sweep_wall, 1)
                             if _last_sweep_wall is not None else None),
        "sweep_interval_s": SWEEP_INTERVAL_S,
        "fault_after_s": FAULT_AFTER_S,
        "summary": summary(),
    }


def summary() -> str:
    ripe = sorted(faults(), key=lambda s: s.name)
    sweep = _last_sweep or {}
    pending = sorted(s.device_id for s in _suspects.values() if not s.faulted)
    unchecked = sorted(sweep.get("unchecked") or [])
    uncheckable = sorted(sweep.get("uncheckable") or [])
    clauses = []
    if pending:
        clauses.append(f"{len(pending)} reading dark or not answering, not "
                       f"yet named ({', '.join(pending)})")
    if unchecked:
        clauses.append(f"{len(unchecked)} unchecked this sweep "
                       f"({', '.join(unchecked)})")
    if uncheckable:
        clauses.append(f"{len(uncheckable)} not checkable "
                       f"({', '.join(uncheckable)})")
    if ripe:
        named = (f"{len(ripe)} fixture(s) dark or not answering while streamed: "
                 + "; ".join(f"{s.name} ({s.why})" for s in ripe))
        return "; ".join([named, *clauses])
    if _last_sweep is None:
        return "not swept yet"
    if sweep.get("gate"):
        return f"standing down — {sweep['gate']}"
    return ", ".join(
        [f"{sweep.get('lit', 0)} streamed fixture(s) confirmed lit", *clauses])


def liveness_summary() -> dict:
    """Compact, additive slice for GET /spectra/api/liveness. INFORMATIONAL
    ONLY — never part of `healthy`, see the module docstring."""
    now = time.time()
    ripe = sorted(faults(), key=lambda s: s.name)
    return {
        "fault_count": len(ripe),
        "faults": [
            {"device_id": s.device_id, "name": s.name, "kind": s.kind,
             "why": s.why, "dark_for_s": round(s.dark_for_s, 1),
             "last_checked_age_s": round(now - s.last_bad_wall, 1)}
            for s in ripe],
        "watching": [s.device_id for s in _suspects.values() if not s.faulted],
        "unchecked": list((_last_sweep or {}).get("unchecked") or []),
        "uncheckable": list((_last_sweep or {}).get("uncheckable") or []),
        "last_sweep_age_s": (round(now - _last_sweep_wall, 1)
                             if _last_sweep_wall is not None else None),
        "gate": (_last_sweep or {}).get("gate"),
        "summary": summary(),
    }


async def run_supervised() -> None:
    """Own asyncio task in spectra/app.py's lifespan (the 2026-08-12 lesson:
    monitoring must not die with the monitored). Idle-cheap: the gate
    returns at once whenever SPECTRA is not driving the room herself."""
    while True:
        try:
            await sweep(production_deps())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("dark fixture watch sweep crashed (retrying): %r",
                         exc)
        await asyncio.sleep(SWEEP_INTERVAL_S)
