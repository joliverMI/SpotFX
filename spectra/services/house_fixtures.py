"""HOUSE LIGHTING phase 2 — THE FIXTURES HALF OF THE HOME ASSISTANT SEAM
(plan: /home/javi/fleet-spotfx/data/standard-lighting-plan/report.md §5;
River's asks R6, R9, R16). What Home Assistant tells Spectra about the
FIXTURES, and what Spectra then does to them:

  LEND       his TV strip goes to Hyperion while TV Music is OFF or a media
             source (Roku, Switch, Blu-ray) is on: Spectra stops streaming to
             it (fx/device_output WITHHELD — no packet leaves) and tells the
             WLED to leave realtime once ({"live": false}), and keeps driving
             the sconces on the same virtual. Back on return, in step.
  ON / OFF   a button (the crystal's paddle, the porch button) switches a
             WLED off: no stream, then {"on": false}. On: {"on": true} (and
             the owned brightness), THEN the stream — the order a powered-off
             WLED needs whatever its firmware does with a stream while off
             (spectra/services/night_power.py says why that is unknown).
  BRIGHTNESS Spectra owns every streamed WLED's master brightness while a
             mode drives the room: `owned_brightness` (255) and power on,
             written on entry and RE-ASSERTED when a read-back shows it
             drifted — a Home Assistant brightness write, a sconce that
             rebooted on its boot preset. Each correction is NAMED (status,
             log, fire history), because a fight with a stray HA writer is
             exactly what River's cutover needs to see.
  RECHECK    "I just powered the sconce mains": re-find the named fixtures by
             identity (a mains cycle is when a WLED takes a new DHCP lease),
             re-init a driver that never resolved, and re-apply the power /
             brightness the moment each one answers — seconds instead of the
             activation report's 30 s recheck.

═══ INERT UNLESS A MODE DRIVES THE ROOM ═══

Every request is RECORDED whatever the room's state (house_state.json — a
TV Music report while the room is released is still true later). It is ACTED
ON only while `house.layer_active()`: a mode is set, SPECTRA holds the room,
nothing is on standby. With no mode set nothing is withheld and no WLED is
written — the shipped state, byte-identical to phase 1. On standby (a
preview, a camera run, a night run) nothing moves at all and the output
layer's suspension streams every fixture (a capture must see what it
drives). A fixture this process switched OFF is switched back ON when the
mode is cleared while SPECTRA still holds the room — a streamed fixture that
is powered off is a dark-fixture fault, not a resting state.

═══ THE TAKE SCOPE HOLDS (PR 317) ═══

Only fixtures the current take reaches (show_output._real_devices, the
host's own scope) are ever withheld, written, rechecked or lit by the voice.
A request naming one outside it is recorded and REPORTED as outside the
take, never acted on.

═══ OFF THE EVENT LOOP ═══

`fx.utils.WLED`'s calls are `async def` wrappers around BLOCKING `requests`;
every write and read here runs on a worker thread through that unmodified
transport (live_host._read_wled_blocking's own pattern), so a dead or
saturated fixture costs a worker its timeout, never the loop that drives the
bridge poll and the trigger tick. One transition per fixture at a time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from spectra.models.house_mode import FixtureOverride, now_ms
from spectra.services import house_store

logger = logging.getLogger(__name__)

TICK_S = 1.0
#: How often a fixture Spectra holds on/off and at the owned brightness is
#: read back for drift. One json/state GET per fixture per minute.
DRIFT_CHECK_S = 60.0
#: Per-request budget for a control write or its read-back — the same 3 s
#: fx.utils.WLED_BRIGHTNESS_TIMEOUT_S binds (VENDOR #34): .236 saturates
#: under its own stream and refuses at 0.5 s.
HTTP_TIMEOUT_S = 3.0
WRITE_ATTEMPTS = 3
WRITE_SPACING_S = 0.4
#: A recheck keeps asking for this long: a sconce needs a few seconds to
#: boot and join Wi-Fi after its mains come on.
RECHECK_WINDOW_S = 45.0
RECHECK_EVERY_S = 3.0
MAX_RECENT = 12

TARGET_ON = "on"        # streamed, powered on, owned brightness
TARGET_OFF = "off"      # withheld, {"on": false}
TARGET_LENT = "lent"    # withheld, {"live": false} once, nothing else

CONTROLLABLE_TYPES = {"wled"}

_UNSET = object()


# ── the transport (worker threads) ─────────────────────────────────────────

def _post_blocking(wled, payload: dict, timeout: float):
    import requests
    response = asyncio.run(wled._wled_request(
        requests.post, wled.ip_address, "json/state", json=payload,
        timeout=timeout))
    try:
        return response.json()
    except ValueError:
        return None


def _get_state_blocking(wled, timeout: float) -> dict:
    import requests
    response = asyncio.run(wled._wled_request(
        requests.get, wled.ip_address, "json/state", timeout=timeout))
    body = response.json()
    if not isinstance(body, dict):
        raise TypeError(f"json/state returned {type(body).__name__}")
    return body


async def _default_post(device, payload: dict) -> None:
    wled = getattr(device, "wled", None)
    if wled is None:
        raise RuntimeError("its driver never reached the fixture (no address)")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _post_blocking, wled, dict(payload),
                               HTTP_TIMEOUT_S)


async def _default_get(device) -> dict:
    wled = getattr(device, "wled", None)
    if wled is None:
        raise RuntimeError("its driver never reached the fixture (no address)")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_state_blocking, wled,
                                      HTTP_TIMEOUT_S)


def _default_host():
    from spectra.services.live_host import live
    return live.host


async def _default_relocate(device, host) -> bool:
    """Find a fixture by identity; True when it moved (and was adopted)."""
    from spectra.services import device_relocation
    location = await device_relocation.reconcile(device, host=host)
    return bool(location is not None and location.moved)


async def _default_reinit(device) -> bool:
    from spectra.services import activation_report
    return await activation_report._retry_driver_init(device)


async def _default_reachable(device_id: str) -> tuple[bool, str]:
    from spectra.services.live_host import live
    read = await live.read_emission(device_id, read_state=False,
                                    http_timeout_s=HTTP_TIMEOUT_S,
                                    timeout_s=HTTP_TIMEOUT_S + 1.0)
    if not read.checkable:
        return False, "its driver has no address to ask yet"
    if not read.reachable:
        return False, read.error or "no answer"
    return True, ""


async def _default_report_refresh() -> None:
    from spectra.services import activation_report
    await activation_report.recheck(retry_init=False)


@dataclass
class Deps:
    post: Callable[[Any, dict], Awaitable[None]] = _default_post
    get_state: Callable[[Any], Awaitable[dict]] = _default_get
    host: Callable[[], Any] = _default_host
    relocate: Callable[[Any, Any], Awaitable[bool]] = _default_relocate
    reinit: Callable[[Any], Awaitable[bool]] = _default_reinit
    reachable: Callable[[str], Awaitable[tuple]] = _default_reachable
    report_refresh: Callable[[], Awaitable[None]] = _default_report_refresh
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


deps = Deps()


# ── runtime ────────────────────────────────────────────────────────────────

@dataclass
class _Applied:
    target: str
    outcome: str = "pending"        # landed / unconfirmed / failed / sent
    detail: str = ""
    at: float = 0.0
    at_ms: int = 0
    last_check: float = 0.0


@dataclass
class _Runtime:
    applied: dict = field(default_factory=dict)       # did -> _Applied
    inflight: dict = field(default_factory=dict)      # did -> (target, task)
    #: devices whose power-on write is in flight: still withheld until it
    #: lands, so the stream never resumes onto a fixture still switched off
    pending_on: set = field(default_factory=set)
    corrections: list = field(default_factory=list)
    rechecks: dict = field(default_factory=dict)      # did -> status dict
    recheck_tasks: dict = field(default_factory=dict) # did -> task
    recheck_deadline: dict = field(default_factory=dict)
    #: None until the first pass, so that pass always pushes (a restart
    #: may have pre-installed a withheld set the live answer replaces)
    withheld_pushed: Optional[dict] = None
    last_reason: Optional[str] = None
    kick: Optional[asyncio.Event] = None


_rt = _Runtime()


def reset() -> None:
    """Tests: forget the module's memory (in-flight tasks are cancelled)."""
    global _rt, deps
    for _target, task in list(_rt.inflight.values()):
        task.cancel()
    for task in list(_rt.recheck_tasks.values()):
        task.cancel()
    _rt = _Runtime()
    deps = Deps()


def kick() -> None:
    """Ask the supervisor for a pass now (a request just changed something).
    Safe from any coroutine; a no-op before the supervisor exists."""
    ev = _rt.kick
    if ev is not None:
        ev.set()


# ── naming fixtures ────────────────────────────────────────────────────────

def _stored_devices() -> list[dict]:
    from spectra import config as scfg
    path = scfg.FX_LIVE_CONFIG_DIR / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return []
    out = []
    for d in raw.get("devices") or []:
        if isinstance(d, dict) and d.get("id"):
            out.append({"id": str(d["id"]), "type": d.get("type"),
                        "name": (d.get("config") or {}).get("name")})
    return out


def _known_devices() -> list[dict]:
    """[{id, type, name}] — the live host's devices, else the stored config's
    (a request while the room is released still names a real fixture)."""
    host = deps.host()
    if host is not None:
        out = []
        for did in list(host.devices):
            dev = host.devices.get(did)
            out.append({"id": str(did), "type": getattr(dev, "type", None),
                        "name": getattr(dev, "name", None)})
        return out
    return _stored_devices()


def resolve_fixture(name_or_id: str) -> tuple[Optional[dict], Optional[str]]:
    """({id, type, name}, None) or (None, why). By id, then by name ignoring
    case — never a guess between two."""
    key = (name_or_id or "").strip()
    if not key:
        return None, "no fixture named"
    devices = [d for d in _known_devices() if not str(d["id"]).startswith("gap-")]
    hit = next((d for d in devices if d["id"] == key), None)
    if hit is not None:
        return hit, None
    low = key.lower()
    named = [d for d in devices if (d.get("name") or "").strip().lower() == low]
    if len(named) == 1:
        return named[0], None
    if len(named) > 1:
        return None, (f"{key!r} names {len(named)} fixtures "
                      f"({', '.join(d['id'] for d in named)}) — use the id")
    return None, (f"no fixture called {key!r} (known: "
                  f"{', '.join(sorted(d['id'] for d in devices))})")


def _settings():
    return house_store.load_library().settings


def _in_scope_devices(host) -> list[str]:
    from spectra.services import show_output
    return show_output._real_devices(host)


def _controllable(dev) -> bool:
    return str(getattr(dev, "type", "") or "").lower() in CONTROLLABLE_TYPES


# ── what Home Assistant tells us ───────────────────────────────────────────

def _record(kind: str, detail: dict) -> None:
    try:
        from spectra.services import fire_history
        fire_history.record_fire("house", kind, detail)
    except Exception:                                    # noqa: BLE001
        logger.exception("house fixtures: fire-history write failed")


def set_fixture(fixture: str, *, power: Any = _UNSET, lent_to: Any = _UNSET,
                source: str = "ha") -> dict:
    """Record what was asked of one fixture. `power` "on"/"off"/None (None =
    the mode decides), `lent_to` a name or None; an argument left out is
    left alone. Returns {"status", "fixture", ...}: recorded / unchanged /
    unknown_fixture / invalid. Acted on by the supervisor when a mode drives
    the room (kicked here, so it lands within a pass)."""
    dev, why = resolve_fixture(fixture)
    if dev is None:
        return {"status": "unknown_fixture", "fixture": fixture, "reason": why}
    did = dev["id"]
    if power is not _UNSET and power not in (None, "on", "off"):
        return {"status": "invalid", "fixture": did,
                "reason": "state must be \"on\" or \"off\""}
    if (power == "off" and str(dev.get("type") or "").lower()
            not in CONTROLLABLE_TYPES):
        return {"status": "invalid", "fixture": did,
                "reason": (f"{did} is a {dev.get('type')} fixture — only a WLED "
                           f"can be switched off here; a Hue area follows the "
                           f"mode's Hue looks")}
    if lent_to is not _UNSET and lent_to is not None:
        lent_to = str(lent_to).strip() or None
    st = house_store.state()
    cur = st.fixtures.get(did) or FixtureOverride()
    new = cur.model_copy()
    if power is not _UNSET:
        new.power = power
    if lent_to is not _UNSET:
        new.lent_to = lent_to
    if (new.power, new.lent_to) == (cur.power, cur.lent_to) and did in st.fixtures:
        return {"status": "unchanged", "fixture": did, **_fixture_view(did)}
    new.source = source
    new.since_ms = now_ms()
    if new.power is None and new.lent_to is None:
        st.fixtures.pop(did, None)
    else:
        st.fixtures[did] = new
    house_store.save_state()
    _record("fixture", {"device": did, "power": new.power,
                        "lent_to": new.lent_to, "source": source})
    kick()
    return {"status": "recorded", "fixture": did, **_fixture_view(did)}


def set_tv_music(on: bool, *, source: str = "ha") -> dict:
    """Home Assistant's TV Music switch. OFF lends the TV strip(s) to
    Hyperion; ON (with no media source on) takes them back."""
    st = house_store.state()
    on = bool(on)
    if st.tv_music is on:
        return {"status": "unchanged", "tv_music": on, "tv_strip": tv_strip_status()}
    st.tv_music = on
    st.tv_music_ms = now_ms()
    house_store.save_state()
    _record("tv_music", {"on": on, "source": source})
    kick()
    return {"status": "recorded", "tv_music": on, "tv_strip": tv_strip_status()}


# ── what the fixtures should be ────────────────────────────────────────────

def tv_strip_ids() -> list[str]:
    out = []
    for name in _settings().tv_strips:
        dev, _why = resolve_fixture(name)
        if dev is not None and dev["id"] not in out:
            out.append(dev["id"])
    return out


def lend_reasons(st=None) -> dict[str, str]:
    """device -> why it is lent, whatever the room's state (the FACT; whether
    it is acted on is the gate's business)."""
    from spectra.services import house
    st = st or house_store.state()
    out: dict[str, str] = {}
    strips = tv_strip_ids()
    if st.tv_music is False:
        for did in strips:
            out[did] = "TV Music is off — Hyperion drives the strip"
    if house.media_active(st):
        for did in strips:
            out.setdefault(did, f"the {st.media_source or 'media centre'} is "
                                f"{st.media_state} — Hyperion drives the strip")
    for did, ov in st.fixtures.items():
        if ov.lent_to:
            out.setdefault(did, f"lent to {ov.lent_to}")
    return out


def desired() -> dict[str, tuple[str, str]]:
    """device -> (target, why) for every in-scope fixture the seam acts on
    RIGHT NOW. Empty when no mode drives the room."""
    from spectra.services import house
    if not house.layer_active():
        return {}
    host = deps.host()
    if host is None:
        return {}
    st = house_store.state()
    settings = _settings()
    lent = lend_reasons(st)
    out: dict[str, tuple[str, str]] = {}
    for did in _in_scope_devices(host):
        dev = host.devices.get(did)
        ov = st.fixtures.get(did)
        if did in lent:
            out[did] = (TARGET_LENT, lent[did])
        elif ov is not None and ov.power == "off" and _controllable(dev):
            out[did] = (TARGET_OFF, f"switched off ({ov.source or 'request'})")
        elif _controllable(dev) and settings.own_brightness:
            out[did] = (TARGET_ON, f"Spectra holds it on at brightness "
                                   f"{settings.owned_brightness}")
    return out


def _withheld_map(want: dict) -> dict[str, str]:
    out = {did: (f"lent: {why}" if t == TARGET_LENT else "switched off")
           for did, (t, why) in want.items() if t in (TARGET_LENT, TARGET_OFF)}
    for did in _rt.pending_on:
        out.setdefault(did, "powering on")
    return out


def _push_withheld(want: dict) -> None:
    from fx import device_output
    wm = _withheld_map(want)
    if wm != _rt.withheld_pushed:
        device_output.set_withheld(wm)
        _rt.withheld_pushed = wm


# ── the supervisor ─────────────────────────────────────────────────────────

async def tick() -> None:
    """One pass: work out what every fixture should be, push the withheld
    set, start a write for every fixture whose target changed, and read back
    the ones due a drift check. Never raises."""
    try:
        await _tick()
    except Exception:                                    # noqa: BLE001
        logger.exception("house fixtures: tick failed")


async def _tick() -> None:
    from spectra.services import house, show_output
    kind, _reason = house.gate()
    if kind == "standby":
        # Nothing moves while a preview / camera run / night run holds the
        # room; the output layer's suspension already streams everything.
        _rt.last_reason = house.inactive_reason()
        return
    host = deps.host()
    room_ours = show_output.ownership_refusal() is None and host is not None
    if not room_ours:
        # Released / not ours / stack down: nothing to act on and nothing
        # to hand back — the release path let go of every fixture.
        _rt.applied.clear()
        _rt.pending_on.clear()
        for _t, task in list(_rt.inflight.values()):
            task.cancel()
        _rt.inflight.clear()
        _push_withheld({})
        _rt.last_reason = house.inactive_reason()
        return
    want = desired()
    _rt.last_reason = house.inactive_reason()
    now = deps.clock()
    scope = set(_in_scope_devices(host))

    # A fixture the seam no longer acts on: hand back what WE changed.
    for did in list(_rt.applied):
        if did in want:
            continue
        prev = _rt.applied.pop(did)
        if prev.target == TARGET_OFF and did in scope:
            dev = host.devices.get(did)
            if dev is not None and _controllable(dev):
                _start(did, TARGET_ON, "handed back on — no mode drives it now",
                       host, owned=False, withhold_until_on=True)

    for did, (target, why) in want.items():
        prev = _rt.applied.get(did)
        infl = _rt.inflight.get(did)
        if infl is not None:
            if infl[0] == target:
                continue
            infl[1].cancel()
            _rt.inflight.pop(did, None)
            _rt.pending_on.discard(did)
        if prev is None or prev.target != target:
            from_stream = prev is None or prev.target == TARGET_ON
            _start(did, target, why, host, owned=True,
                   withhold_until_on=not from_stream)
        elif (target in (TARGET_ON, TARGET_OFF)
              and now - prev.last_check >= DRIFT_CHECK_S):
            prev.last_check = now
            _start_check(did, target, host)
    _push_withheld(want)


def _start(did: str, target: str, why: str, host, *, owned: bool,
           withhold_until_on: bool = False) -> None:
    dev = host.devices.get(did)
    if dev is None:
        return
    if target == TARGET_ON and withhold_until_on:
        _rt.pending_on.add(did)
    task = asyncio.get_running_loop().create_task(
        _transition(did, dev, target, why, owned=owned),
        name=f"house-fixture-{did}")
    _rt.inflight[did] = (target, task)


def _start_check(did: str, target: str, host) -> None:
    dev = host.devices.get(did)
    if dev is None or did in _rt.inflight:
        return
    task = asyncio.get_running_loop().create_task(
        _drift_check(did, dev, target), name=f"house-fixture-check-{did}")
    _rt.inflight[did] = (target, task)


async def _write_confirmed(dev, payload: dict, check: Callable[[dict], bool]
                           ) -> tuple[str, str, Optional[dict]]:
    """POST `payload`, read json/state back, retry a refusal. (outcome,
    detail, last state read) — landed / unconfirmed / failed, the three
    fixture_brightness.Delivery draws, for the same reason: "we could not
    check" is a different fact from "it did not take"."""
    accepted = False
    last: Optional[dict] = None
    error = ""
    for attempt in range(WRITE_ATTEMPTS):
        try:
            await deps.post(dev, payload)
            accepted = True
        except Exception as exc:                         # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        else:
            try:
                last = await deps.get_state(dev)
            except Exception as exc:                     # noqa: BLE001
                last = None
                error = f"read-back failed ({type(exc).__name__}: {exc})"
            else:
                if check(last):
                    return "landed", "", last
                error = (f"the fixture reports on={last.get('on')} "
                         f"bri={last.get('bri')}")
        if attempt < WRITE_ATTEMPTS - 1:
            await deps.sleep(WRITE_SPACING_S)
    if accepted and last is None:
        return "unconfirmed", error, None
    return "failed", error, last


async def _transition(did: str, dev, target: str, why: str, *, owned: bool) -> None:
    settings = _settings()
    outcome, detail = "sent", ""
    try:
        if target == TARGET_LENT:
            if not _controllable(dev):
                # Nothing to tell a non-WLED fixture; no stream is the lend.
                outcome = "withheld"
            else:
                try:
                    await deps.post(dev, {"live": False})
                    outcome = "sent"
                except Exception as exc:                 # noqa: BLE001
                    outcome, detail = "failed", f"{type(exc).__name__}: {exc}"
        elif target == TARGET_OFF:
            # RELEASE FIRST, THEN OFF — an off issued under a live stream
            # does not stick (night_power.py's one observed fact). The
            # stream is already withheld; this ends realtime, then powers
            # the fixture down.
            try:
                await deps.post(dev, {"live": False})
            except Exception as exc:                     # noqa: BLE001
                detail = f"leaving realtime failed ({type(exc).__name__})"
            outcome, more, _last = await _write_confirmed(
                dev, {"on": False}, lambda s: s.get("on") is False)
            detail = "; ".join(x for x in (detail, more) if x)
        else:   # TARGET_ON
            payload: dict = {"on": True}
            if owned and settings.own_brightness:
                payload["bri"] = int(settings.owned_brightness)
            want_bri = payload.get("bri")
            outcome, detail, _last = await _write_confirmed(
                dev, payload,
                lambda s: s.get("on") is True and (want_bri is None
                                                   or s.get("bri") == want_bri))
    except asyncio.CancelledError:
        _rt.pending_on.discard(did)
        raise
    finally:
        if target == TARGET_ON:
            # The power-on write has had its go (landed or not): the stream
            # resumes either way — withholding forever over a slow
            # read-back would be worse than the stream finding it on.
            _rt.pending_on.discard(did)
        cur = _rt.inflight.get(did)
        if cur is not None and cur[1] is asyncio.current_task():
            _rt.inflight.pop(did, None)
    now = deps.clock()
    if target == TARGET_ON and not owned:
        # A hand-back: nothing to hold afterwards.
        _rt.applied.pop(did, None)
    else:
        _rt.applied[did] = _Applied(target=target, outcome=outcome, detail=detail,
                                    at=now, at_ms=now_ms(), last_check=now)
    level = logging.WARNING if outcome == "failed" else logging.INFO
    logger.log(level, "house fixtures: %s -> %s (%s): %s%s", did, target, why,
               outcome, f" — {detail}" if detail else "")
    _record("fixture_" + target, {"device": did, "why": why, "outcome": outcome,
                                  "detail": detail})
    kick()


async def _drift_check(did: str, dev, target: str) -> None:
    """Read json/state back; re-assert power (and the owned brightness) if
    something else moved it. An unreadable fixture is left alone — unknown
    never acts."""
    settings = _settings()
    try:
        try:
            state = await deps.get_state(dev)
        except Exception:                                # noqa: BLE001
            return
        found_on, found_bri = state.get("on"), state.get("bri")
        if target == TARGET_OFF:
            if found_on is not True:
                return
            payload, check = {"on": False}, (lambda s: s.get("on") is False)
        else:
            want_bri = int(settings.owned_brightness) if settings.own_brightness else None
            if found_on is True and (want_bri is None or found_bri == want_bri):
                return
            payload = {"on": True}
            if want_bri is not None:
                payload["bri"] = want_bri
            check = (lambda s: s.get("on") is True
                     and (want_bri is None or s.get("bri") == want_bri))
        outcome, detail, _last = await _write_confirmed(dev, payload, check)
        entry = {"at_ms": now_ms(), "device": did, "target": target,
                 "found": {"on": found_on, "bri": found_bri},
                 "set": payload, "outcome": outcome, "detail": detail}
        _rt.corrections.append(entry)
        del _rt.corrections[:-MAX_RECENT]
        logger.warning("house fixtures: %s drifted (on=%s bri=%s) — something "
                       "else wrote it; re-asserted %s: %s", did, found_on,
                       found_bri, payload, outcome)
        _record("fixture_corrected", entry)
        applied = _rt.applied.get(did)
        if applied is not None:
            applied.outcome, applied.detail = outcome, detail
    finally:
        cur = _rt.inflight.get(did)
        if cur is not None and cur[1] is asyncio.current_task():
            _rt.inflight.pop(did, None)


async def run_supervised() -> None:
    """Own task in spectra/app.py's lifespan. Also expires a stale voice
    overlay and keeps the restart snapshot current — the seam's small
    housekeeping, on the same clock."""
    from spectra.services import house_restart, house_voice
    _rt.kick = asyncio.Event()
    while True:
        await tick()
        try:
            house_voice.expire()
        except Exception:                                # noqa: BLE001
            logger.exception("house fixtures: voice expiry failed")
        try:
            house_restart.maybe_persist()
        except Exception:                                # noqa: BLE001
            logger.exception("house fixtures: restart snapshot failed")
        ev = _rt.kick
        try:
            await asyncio.wait_for(ev.wait(), timeout=TICK_S)
        except asyncio.TimeoutError:
            pass
        ev.clear()


# ── recheck ("I just powered the sconce mains") ────────────────────────────

def recheck(fixtures: list[str]) -> dict:
    """Start (or extend) a recheck of each named fixture. Returns at once —
    Home Assistant's automation never waits on a fixture booting. Needs
    SPECTRA to hold the room with its stack up (the recheck re-inits a
    driver); it does NOT need a mode — it only does sooner what the
    activation report's own 30 s recheck already does. Power and brightness
    are re-applied only while a mode drives the room."""
    from spectra.services import show_output
    refusal = show_output.ownership_refusal()
    host = deps.host()
    names = [f for f in (fixtures or []) if str(f).strip()]
    if not names:
        return {"status": "invalid", "reason": "name at least one fixture"}
    if refusal or host is None:
        return {"status": "skipped",
                "reason": refusal or "SPECTRA's live light stack is not up"}
    scope = set(_in_scope_devices(host))
    started, unknown, outside = [], [], []
    deadline = deps.clock() + RECHECK_WINDOW_S
    for name in names:
        dev, why = resolve_fixture(name)
        if dev is None:
            unknown.append({"fixture": name, "reason": why})
            continue
        did = dev["id"]
        if did not in scope:
            outside.append(did)
            continue
        _rt.recheck_deadline[did] = deadline
        task = _rt.recheck_tasks.get(did)
        if task is None or task.done():
            _rt.rechecks[did] = {"state": "rechecking", "since_ms": now_ms(),
                                 "attempts": 0}
            _rt.recheck_tasks[did] = asyncio.get_running_loop().create_task(
                _recheck_one(did), name=f"house-recheck-{did}")
        started.append(did)
    return {"status": "rechecking" if started else "nothing_to_recheck",
            "fixtures": started, "unknown": unknown, "outside_take": outside,
            "window_s": RECHECK_WINDOW_S}


async def _recheck_one(did: str) -> None:
    attempts = 0
    t0 = deps.clock()
    try:
        while True:
            host = deps.host()
            dev = host.devices.get(did) if host is not None else None
            if dev is None:
                _rt.rechecks[did] = {"state": "gone", "since_ms": now_ms(),
                                     "attempts": attempts,
                                     "reason": "the fixture left the live stack"}
                return
            attempts += 1
            moved = False
            try:
                moved = await deps.relocate(dev, host)
            except Exception:                            # noqa: BLE001
                logger.debug("house recheck: %s relocation failed", did,
                             exc_info=True)
            if moved or getattr(dev, "_destination", None) is None:
                try:
                    await deps.reinit(dev)
                except Exception:                        # noqa: BLE001
                    logger.debug("house recheck: %s re-init failed", did,
                                 exc_info=True)
            ok, why = await deps.reachable(did)
            if ok:
                # Its power and brightness are whatever its boot preset
                # says: forget what we last applied so the next pass writes
                # the mode's again.
                _rt.applied.pop(did, None)
                _rt.rechecks[did] = {
                    "state": "found", "at_ms": now_ms(), "attempts": attempts,
                    "after_s": round(deps.clock() - t0, 1), "moved": moved,
                    "address": getattr(dev, "_destination", None)}
                logger.warning("house recheck: %s answered after %.1fs%s", did,
                               deps.clock() - t0, " (it had moved)" if moved else "")
                try:
                    await deps.report_refresh()
                except Exception:                        # noqa: BLE001
                    logger.debug("house recheck: report refresh failed",
                                 exc_info=True)
                kick()
                return
            if deps.clock() >= _rt.recheck_deadline.get(did, 0.0):
                _rt.rechecks[did] = {"state": "not_found", "at_ms": now_ms(),
                                     "attempts": attempts, "reason": why}
                logger.warning("house recheck: %s did not answer in %.0fs: %s",
                               did, RECHECK_WINDOW_S, why)
                return
            _rt.rechecks[did] = {"state": "rechecking", "attempts": attempts,
                                 "last_reason": why}
            await deps.sleep(RECHECK_EVERY_S)
    finally:
        cur = _rt.recheck_tasks.get(did)
        if cur is asyncio.current_task():
            _rt.recheck_tasks.pop(did, None)


# ── status ─────────────────────────────────────────────────────────────────

def _fixture_view(did: str) -> dict:
    st = house_store.state()
    ov = st.fixtures.get(did)
    applied = _rt.applied.get(did)
    return {"override": ov.model_dump() if ov is not None else None,
            "applied": ({"target": applied.target, "outcome": applied.outcome,
                         "detail": applied.detail, "at_ms": applied.at_ms}
                        if applied is not None else None)}


def tv_strip_status() -> dict:
    from fx import device_output
    from spectra.services import house
    strips = tv_strip_ids()
    lent = lend_reasons()
    withheld = device_output.withheld()
    acting = house.layer_active()
    why = next((lent[d] for d in strips if d in lent), None)
    if why is None:
        owner = "spectra"
    elif acting:
        owner = "hyperion"
    else:
        owner = "hyperion (recorded — no mode drives the room, so Spectra is not acting on it)"
    return {"devices": strips, "owner": owner, "why": why,
            "streaming": [d for d in strips if d not in withheld]}


def status() -> dict:
    from fx import device_output
    from spectra.services import house
    st = house_store.state()
    settings = _settings()
    want = desired()
    fixtures = []
    host = deps.host()
    ids = set(want) | set(_rt.applied) | set(st.fixtures)
    for did in sorted(ids):
        t = want.get(did)
        dev = host.devices.get(did) if host is not None else None
        fixtures.append({"device": did,
                         "name": getattr(dev, "name", None) or did,
                         "target": t[0] if t else None,
                         "why": t[1] if t else None,
                         "in_flight": did in _rt.inflight,
                         **_fixture_view(did)})
    return {
        "acting": house.layer_active(),
        "reason": house.inactive_reason(),
        "own_brightness": settings.own_brightness,
        "owned_brightness": settings.owned_brightness,
        "tv_music": st.tv_music,
        "fixtures": fixtures,
        "withheld": device_output.withheld(),
        "corrections": list(reversed(_rt.corrections[-5:])),
        "rechecks": dict(_rt.rechecks),
    }
