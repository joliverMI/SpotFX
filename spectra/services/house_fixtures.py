"""HOUSE LIGHTING phase 2 — THE FIXTURES HALF OF THE HOME ASSISTANT SEAM
(plan: /home/javi/fleet-spotfx/data/standard-lighting-plan/report.md §5;
River's asks R6, R9, R16). What Home Assistant tells Spectra about the
FIXTURES, and what Spectra then does to them:

  LEND       his TV strip goes to Hyperion while TV Music is OFF or a media
             source (Roku, Switch, Blu-ray) is on: Spectra stops streaming to
             it (fx/device_output WITHHELD — no packet leaves) and tells the
             WLED to leave realtime once ({"live": false}), and keeps driving
             the sconces on the same virtual. Back on return, in step. If the
             CURRENT MODE's own plan also wants the strip powered off, the
             lend is honoured only while Hyperion is confirmed actually
             streaming to it (`_hyperion_streaming`/`_refresh_hyperion`) —
             otherwise the strip is switched off like any other MODE OFF
             fixture, never left lit on nobody's signal (found 2026-10-05,
             the TV backlight incident).
  ON / OFF   a button (the crystal's paddle, the porch button) switches a
             WLED off: no stream, then {"live": false}, then {"on": false}.
             On: {"on": true}, THEN the stream — the order a powered-off WLED
             needs whatever its firmware does with a stream while off
             (spectra/services/night_power.py says why that is unknown).
             Power only: `{"on": …}` keeps the fixture's own brightness.

  BRIGHTNESS IS HOME ASSISTANT'S (2026-10-12, the Admiral's ruling,
             data/wled-bri-audit/report.md): "Home assistant can set the WLED
             global brightness of any of these lights, and spectra doesn't
             touch that value." Spectra NEVER sends a WLED's master `bri` —
             not on a power-on, not on a power-off, not on a drift check, not
             on a hand-back. What he sees is Spectra's own pixel brightness
             (mode Levels, the Light Show, the scene) x the WLED's own master
             brightness, which belongs to Home Assistant or the fixture's own
             web page. `fx/utils.py::WLED._wled_request` refuses a json/state
             body carrying `bri` (VENDOR #78), and
             tests/test_wled_never_writes_bri.py holds it statically too.
             The retired build (2026-10-05 to 10-12) held each fixture at a
             captured "ceiling", soft-powered it through bri 1, corrected
             drift every minute and handed a days-old bri back on release —
             and left three fixtures stuck at bri 1 the morning it was
             retired. None of that exists any more.

  POWER FOLLOWS THE MODE, NEVER RE-ASSERTED (D2a, same ruling). Spectra
             switches a WLED's power only when what the house asks of it
             CHANGES: a house mode change (the effective mode — a media
             overlay counts), a fixture's target changing (a lend, an
             override, mains on/off), or a take of a released room. Each
             write is recorded durably (`HouseState.power_applied`: device ->
             {mode, target, on}), so a Spectra restart under the same mode
             writes nothing. There is NO drift check: Home Assistant (or he)
             switching a WLED off stands until the next mode change.

  RECHECK    "I just powered the sconce mains": re-find the named fixtures by
             identity (a mains cycle is when a WLED takes a new DHCP lease),
             re-init a driver that never resolved, and re-apply the mode's
             power (never a brightness) the moment each one answers —
             seconds instead of the activation report's 30 s recheck.

  MAINS OFF  (phase 3) Home Assistant reports a fixture's mains switched off
             (his kitchen sconces on light.dimmer_kitchen_sconce, PUT
             /api/house/mains): no stream, no write, no drift check — and no
             SEARCH (activation_report.py skips it: no relocation, no /24
             sweep, no driver re-init). "Mains on" (or a recheck naming it)
             clears it and re-finds the fixture at once. In case that call
             is ever missed, its LAST address is knocked on once every
             MAINS_KNOCK_S (one json/info, never a sweep); an answer clears
             the report and says so.
  MODE OFF   (phase 3) a resting mode's `off` on a WLED: house.py fades it
             to black, then `house.mode_off_devices()` names it and it is
             switched off exactly like a button OFF — no stream at all. A
             Light Show Steady/Freeze hold on the fixture wins (a higher
             layer): it stays powered and streamed.

NO SOFT POWER (retired 2026-10-12). Phase 3 hid the WLED's own preset
by dropping `bri` to 1 around every switch; with brightness Home
Assistant's, that trick is gone. A switch-off is preceded by house.py's
own fade to black (the stream is withheld on that black frame), then
{"live": false} and {"on": false}; a power-on is {"on": true} with the
stream resuming the moment it lands. A WLED may briefly show its own
preset between the two — named in the PR for a room check rather than
hidden with a brightness write.

HAND-BACK (phase 3, power only since 2026-10-12). Before its FIRST power
write to a WLED this take, Spectra reads the fixture's power
(HouseState.pre_take, durable — it survives a restart that keeps the
picture); when the room is RELEASED it writes `{"on": <before>}` back
(read back) to the address it had — and only when Spectra's own last power
write left it different, so a fixture Spectra never switched is never
touched. Found 2026-10-05: a take left his dining table under-glow ON — it
had been off. The rule: a fixture that was off before a take is off after.
Only a release hands back: a handover to the older SpotFX process needs
the fixtures on, and a restart keeps the picture. No brightness is ever
handed back — Spectra never changed it.

═══ INERT UNLESS A MODE DRIVES THE ROOM ═══

Every request is RECORDED whatever the room's state (house_state.json — a
TV Music report while the room is released is still true later). It is ACTED
ON only while `house.layer_active()`: a mode is set, SPECTRA holds the room,
nothing is on standby. With no mode set nothing is withheld and no WLED is
written — the shipped state, byte-identical to phase 1. On standby (a
preview, a camera run, a night run) nothing moves at all and the output
layer's suspension streams every fixture (a capture must see what it
drives) — except a colour-set preview on its own, which keeps the withheld
set in force (show_output.suspension_reason). A fixture this process
switched OFF is switched back ON when the mode is cleared while SPECTRA
still holds the room — a streamed fixture that is powered off is a
dark-fixture fault, not a resting state.

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
#: Per-request budget for a power write or its read-back — the same 3 s
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
#: phase 3: a fixture reported mains-off has its last address knocked on
#: this often, in case Home Assistant's "mains on" was missed
MAINS_KNOCK_S = 600.0
#: phase 3: HAND-BACK — attempts per fixture before it is dropped (named)
HANDBACK_ATTEMPTS = 3
#: how often a TV strip's own `live` flag (is Hyperion actually streaming
#: to it right now) is re-read — one json/info per strip per this long,
#: never per tick.
HYPERION_CHECK_S = 5.0

TARGET_ON = "on"        # streamed, powered on (brightness is HA's)
TARGET_OFF = "off"      # withheld, {"on": false}
TARGET_LENT = "lent"    # withheld, {"live": false} once, nothing else
TARGET_UNPOWERED = "unpowered"  # withheld, nothing written: its mains are off

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


async def _default_post_ip(ip: str, payload: dict) -> None:
    from fx.utils import WLED
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _post_blocking, WLED(ip), dict(payload),
                               HTTP_TIMEOUT_S)


async def _default_get_ip(ip: str) -> dict:
    from fx.utils import WLED
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_state_blocking, WLED(ip),
                                      HTTP_TIMEOUT_S)


def _default_released() -> bool:
    from fx import light_ownership
    try:
        return light_ownership.load().owner == light_ownership.RELEASED
    except Exception:                                    # noqa: BLE001
        return False


async def _default_report_refresh() -> None:
    from spectra.services import activation_report
    await activation_report.recheck(retry_init=False)


async def _default_read_live(device_id: str) -> Optional[bool]:
    """Is a non-Spectra source (Hyperion) actually streaming realtime data
    to this device RIGHT NOW — `json/info`'s own `live` flag, read the same
    way `probe_device_live`/dark_fixture_watch.py already do. `None` when
    unconfirmed (unreachable, no driver yet) — the TV strip's own lend
    decision treats that the same as "not streaming" (the decision's own
    words: switch it off unless Hyperion is ACTUALLY streaming), never as
    a reason to assume it is."""
    from spectra.services.live_host import live
    read = await live.read_emission(device_id, read_state=False,
                                    http_timeout_s=HTTP_TIMEOUT_S,
                                    timeout_s=HTTP_TIMEOUT_S + 1.0)
    if not read.checkable or not read.reachable:
        return None
    return bool(read.live)


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
    post_ip: Callable[[str, dict], Awaitable[None]] = _default_post_ip
    get_ip: Callable[[str], Awaitable[dict]] = _default_get_ip
    released: Callable[[], bool] = _default_released
    read_live: Callable[[str], Awaitable[Optional[bool]]] = _default_read_live


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
    rechecks: dict = field(default_factory=dict)      # did -> status dict
    recheck_tasks: dict = field(default_factory=dict) # did -> task
    recheck_deadline: dict = field(default_factory=dict)
    #: None until the first pass, so that pass always pushes (a restart
    #: may have pre-installed a withheld set the live answer replaces)
    withheld_pushed: Optional[dict] = None
    last_reason: Optional[str] = None
    kick: Optional[asyncio.Event] = None
    #: phase 3: when each mains-off fixture was last knocked on
    knocked_at: dict = field(default_factory=dict)
    #: phase 3: HAND-BACK
    handback_task: Optional[asyncio.Task] = None
    handback_attempts: dict = field(default_factory=dict)
    handed_back: list = field(default_factory=list)
    #: TV strip id -> is Hyperion confirmed actually streaming to it right
    #: now (None = never confirmed either way — treated as "not streaming")
    hyperion_live: dict = field(default_factory=dict)
    hyperion_checked_at: dict = field(default_factory=dict)
    #: (ignored, winner) pairs already warned about this process life — see
    #: `_log_duplicate_ignored`. A duplicate device never stops being one
    #: tick to tick, so without this the warning would re-fire every pass.
    duplicate_logged: set = field(default_factory=set)


_rt = _Runtime()


def reset() -> None:
    """Tests: forget the module's memory (in-flight tasks are cancelled)."""
    global _rt, deps
    for _target, task in list(_rt.inflight.values()):
        task.cancel()
    for task in list(_rt.recheck_tasks.values()):
        task.cancel()
    if _rt.handback_task is not None:
        _rt.handback_task.cancel()
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


def _mode_key() -> str:
    """The EFFECTIVE house mode's id ("" for none) — what a power write is
    recorded against, so the next write is due only when it CHANGES (D2a).
    A media overlay (TV / TV paused) is a mode change like any other."""
    from spectra.services import house
    mode = house.current_mode()
    return mode.id if mode is not None else ""


def _power_due(did: str, target: str, mode_key: str) -> bool:
    """Is a write owed to this fixture now? Only when nothing is recorded
    (a fresh take, a mode just set), when its target changed (a lend, an
    override, mains on/off), or — for a power target — when the house mode
    changed since the last power write. Never on the clock: Home Assistant
    switching a WLED off stands until the next mode change."""
    rec = house_store.state().power_applied.get(did)
    if not isinstance(rec, dict):
        return True
    if rec.get("target") != target:
        return True
    return target in (TARGET_ON, TARGET_OFF) and rec.get("mode") != mode_key


def _was_withheld(did: str) -> bool:
    """Was the fixture last left withheld by this seam (off / lent / mains
    off)? A power-on from there keeps it withheld until the on lands."""
    rec = house_store.state().power_applied.get(did)
    prev = _rt.applied.get(did)
    targets = {rec.get("target") if isinstance(rec, dict) else None,
               prev.target if prev is not None else None}
    return bool(targets & {TARGET_OFF, TARGET_LENT, TARGET_UNPOWERED})


def _record_power(did: str, target: str, mode_key: str) -> None:
    st = house_store.state()
    on = {TARGET_ON: True, TARGET_OFF: False}.get(target)
    prev = st.power_applied.get(did)
    if on is None and isinstance(prev, dict) and target in (TARGET_LENT,
                                                            TARGET_UNPOWERED):
        # a lend / mains-off writes no power: what Spectra last switched it
        # to still stands, for the hand-back
        on = prev.get("on")
    st.power_applied[did] = {"mode": mode_key, "target": target, "on": on,
                             "at_ms": now_ms()}
    house_store.save_state()


def _forget_power(did: str) -> Optional[dict]:
    st = house_store.state()
    rec = st.power_applied.pop(did, None)
    if rec is not None:
        house_store.save_state()
    return rec


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


def set_mains(fixtures: list[str], on: bool, *, source: str = "ha") -> dict:
    """Home Assistant reports the MAINS supply of these fixtures switched
    (his kitchen sconces: light.dimmer_kitchen_sconce). OFF: recorded, and
    while a mode drives the room the fixtures get no stream and are not
    searched for. ON: the report is cleared and a recheck starts at once —
    the same as POST /api/house/recheck. Spectra never switches the mains
    itself (THE SCONCE MAINS RULE). Returns {"status", ...}: recorded /
    unchanged / invalid, plus the recheck's own answer when ON."""
    names = [str(f).strip() for f in (fixtures or []) if str(f).strip()]
    if not names:
        return {"status": "invalid", "reason": "name at least one fixture"}
    st = house_store.state()
    changed, unknown, ids = [], [], []
    for name in names:
        dev, why = resolve_fixture(name)
        if dev is None:
            unknown.append({"fixture": name, "reason": why})
            continue
        did = dev["id"]
        ids.append(did)
        if on and did in st.mains_off:
            st.mains_off.pop(did, None)
            changed.append(did)
        elif not on and did not in st.mains_off:
            st.mains_off[did] = now_ms()
            changed.append(did)
    if changed:
        house_store.save_state()
        _record("mains", {"devices": changed, "on": bool(on), "source": source})
        if not on:
            for did in changed:
                task = _rt.recheck_tasks.pop(did, None)
                if task is not None:
                    task.cancel()
                _rt.rechecks.pop(did, None)
        kick()
    out = {"status": "recorded" if changed else ("unchanged" if ids else "invalid"),
           "on": bool(on), "fixtures": ids, "changed": changed,
           "unknown": unknown, "acting": _acting(),
           "mains_off": dict(st.mains_off)}
    if not ids:
        out["reason"] = "none of the named fixtures exists"
    if on and ids:
        out["recheck"] = recheck(ids)
    return out


def _clear_mains_off(names: list[str], *, source: str) -> list[str]:
    st = house_store.state()
    cleared = []
    for name in names:
        dev, _why = resolve_fixture(str(name))
        if dev is not None and st.mains_off.pop(dev["id"], None) is not None:
            cleared.append(dev["id"])
    if cleared:
        house_store.save_state()
        _record("mains", {"devices": cleared, "on": True, "source": source})
        kick()
    return cleared


def _acting() -> bool:
    from spectra.services import house
    return house.layer_active()


# ── what the fixtures should be ────────────────────────────────────────────

def tv_strip_ids() -> list[str]:
    out = []
    for name in _settings().tv_strips:
        dev, _why = resolve_fixture(name)
        if dev is not None and dev["id"] not in out:
            out.append(dev["id"])
    return out


def _hyperion_streaming(did: str) -> bool:
    """Is Hyperion ACTUALLY streaming to this TV strip right now — read
    from the cache `_refresh_hyperion` keeps (never a live read here:
    `desired()` must stay off the event loop). Never confirmed (the cache
    has nothing for it yet) reads as False — the decision's own direction:
    a lend is honoured only while Hyperion is confirmed live, never on the
    strength of "we don't know"."""
    return bool(_rt.hyperion_live.get(did))


async def _refresh_hyperion(host) -> None:
    """Re-read each TV strip's own `live` flag (json/info) at most once
    every HYPERION_CHECK_S — not per tick, and only for strips that exist
    on the live host. Never raises; a failed read leaves the cache as it
    was (stale, not reset to "not streaming")."""
    now = deps.clock()
    for did in tv_strip_ids():
        dev = host.devices.get(did)
        if dev is None or not _controllable(dev):
            continue
        last = _rt.hyperion_checked_at.get(did, float("-inf"))
        if now - last < HYPERION_CHECK_S:
            continue
        _rt.hyperion_checked_at[did] = now
        try:
            live = await deps.read_live(did)
        except Exception:                                    # noqa: BLE001
            logger.exception("house fixtures: reading %s's live state failed", did)
            continue
        if live is not None:
            _rt.hyperion_live[did] = live


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


def _virtual_ids_by_device(host) -> dict[str, list[str]]:
    """device id -> every virtual id whose segments reach it, read off the
    live host — the reverse of show_output._virtual_devices(). `virtuals`
    is a registry (Virtuals), not a plain dict — iterate its ids, not
    `.items()`, matching `host.devices` elsewhere in this module."""
    out: dict[str, list[str]] = {}
    virtuals = getattr(host, "virtuals", None)
    if virtuals is None:
        return out
    for vid in list(virtuals):
        v = virtuals.get(vid)
        for seg in getattr(v, "_segments", None) or []:
            did = str(seg[0])
            out.setdefault(did, []).append(vid)
    return out


def _duplicate_ignore_map(host, scope_ids: list[str],
                          plan_named: set[str]) -> dict[str, str]:
    """did -> the in-scope device id it duplicates, for every row this seam
    must never act on because another in-scope row already speaks for the
    same physical fixture (sconce-flicker-tv-mode, 2026-10-07: the kitchen
    left sconce existed twice in the fx-live config — same MAC, one row
    backing a virtual and obeying TV mode's own off list, the other
    backing nothing and falling to the "Spectra holds it on" branch below;
    the two fought every 60 s drift check, and the right sconce followed
    the left one's power-on over its WLED sync group).

    A device WINS — is never the one skipped — when it backs a virtual the
    room's scene engine can address (device_usage's own ground truth);
    failing that (no device in the group backs anything), the device named
    in the CURRENT mode's own off/power-off plan wins. A group where
    neither applies is left alone: nothing here invents a preference that
    doesn't already exist. Virtual membership always outranks being named
    in a mode — an interim mode edit naming the duplicate too (the sconce's
    own 2026-10-07 TV-mode fix) changes nothing, so the duplicate stays
    skipped under every mode, not just the one that was hand-edited."""
    from spectra.services import device_usage

    virtuals_by_device = _virtual_ids_by_device(host)
    entries = []
    for did in scope_ids:
        dev = host.devices.get(did)
        entries.append({
            "id": did,
            "type": str(getattr(dev, "type", "") or "").lower(),
            "config": {"name": getattr(dev, "name", None)},
            "virtuals": virtuals_by_device.get(did, []),
        })
    annotated = {e["id"]: e for e in device_usage.annotate(entries)}

    def _group_winner(ids: list[str]) -> Optional[str]:
        used = sorted(d for d in ids if (annotated.get(d) or {}).get("in_use"))
        if used:
            return used[0]
        named = sorted(d for d in ids if d in plan_named)
        return named[0] if named else None

    ignore: dict[str, str] = {}

    groups: dict[str, list[str]] = {}
    for did in scope_ids:
        dev = host.devices.get(did)
        mac = getattr(dev, "hardware_id", None) if dev is not None else None
        if mac:
            groups.setdefault(mac, []).append(did)
    for ids in groups.values():
        if len(ids) < 2:
            continue
        winner = _group_winner(ids)
        if winner is None:
            continue
        for did in ids:
            if did != winner:
                ignore[did] = winner

    for did, entry in annotated.items():
        if did in ignore:
            continue
        dup = entry.get("duplicate_of")
        if dup and dup in annotated:
            ignore[did] = dup

    return ignore


def _log_duplicate_ignored(did: str, winner: str) -> None:
    """Warn once per (duplicate, winner) pair, not every tick — a
    duplicate device never stops being one, so logging it every pass would
    just reproduce the 60 s drift-check noise this fix removes."""
    key = (did, winner)
    if key in _rt.duplicate_logged:
        return
    _rt.duplicate_logged.add(key)
    logger.warning(
        "house fixtures: %s is a duplicate of %s (same hardware) — "
        "ignoring it; %s already speaks for this fixture", did, winner, winner)


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
    lent = lend_reasons(st)
    mode_off = house.mode_off_devices()
    power_off_pending = house.mode_power_off_scope()
    power_off_phase_active = house.mode_off_phase_active()
    strips = set(tv_strip_ids())
    scope_ids = _in_scope_devices(host)
    ignore = _duplicate_ignore_map(host, scope_ids,
                                   set(mode_off) | set(power_off_pending))
    out: dict[str, tuple[str, str]] = {}
    for did in scope_ids:
        winner = ignore.get(did)
        if winner is not None:
            _log_duplicate_ignored(did, winner)
            continue
        dev = host.devices.get(did)
        ov = st.fixtures.get(did)
        wants_off = did in mode_off or did in power_off_pending
        if did in st.mains_off:
            out[did] = (TARGET_UNPOWERED, "Home Assistant reports its mains off "
                                          "— not streamed to, not searched for")
        elif did in lent and (not wants_off or did not in strips
                               or _hyperion_streaming(did)):
            out[did] = (TARGET_LENT, lent[did])
        elif ov is not None and ov.power == "off" and _controllable(dev):
            out[did] = (TARGET_OFF, f"switched off ({ov.source or 'request'})")
        elif did in mode_off and _controllable(dev) and not _show_holds_visible(did):
            out[did] = (TARGET_OFF, f"house mode {mode_off[did]!r} has it off")
        elif (did in power_off_pending and _controllable(dev)
              and power_off_phase_active and not _show_holds_visible(did)):
            # The mode's plan powers this fixture off, but house.py's own
            # fade/off_ready hasn't landed it in `mode_off` yet — leave it
            # alone (no action) rather than guessing ON. Night rule: never
            # switch a fixture from off to on as a side effect.
            continue
        elif _controllable(dev):
            out[did] = (TARGET_ON, "streamed — its power follows the house "
                                   "mode; its brightness is Home Assistant's")
    return out


def _show_holds_visible(did: str) -> bool:
    """Does the Light Show hold this fixture Steady or Frozen (a picture a
    mode's "off" must not switch off)?"""
    try:
        from spectra.services import show_store
        hold = show_store.state().holds.get(did)
    except Exception:                                    # noqa: BLE001
        return False
    return hold is not None and hold.state in ("steady", "freeze")


def mains_off_acting() -> dict[str, int]:
    """device -> since (ms) for every fixture reported mains-off, while a
    mode drives the room (the only time it is acted on). activation_report
    reads it to leave those fixtures unsearched."""
    from spectra.services import house
    try:
        if not house.layer_active():
            return {}
        return dict(house_store.state().mains_off)
    except Exception:                                    # noqa: BLE001
        return {}


_WITHHELD_WORDS = {TARGET_OFF: "switched off", TARGET_UNPOWERED: "mains off"}


def _withheld_map(want: dict) -> dict[str, str]:
    out = {did: (f"lent: {why}" if t == TARGET_LENT else _WITHHELD_WORDS[t])
           for did, (t, why) in want.items()
           if t in (TARGET_LENT, TARGET_OFF, TARGET_UNPOWERED)}
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
        # room; the last withheld set stays as pushed (in force under a
        # colour preview alone, streamed anyway under every other hold).
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
        _maybe_hand_back()
        return
    await _refresh_hyperion(host)
    want = desired()
    _rt.last_reason = house.inactive_reason()
    now = deps.clock()
    scope = set(_in_scope_devices(host))

    # A fixture the seam no longer acts on (the mode was cleared, the
    # house switched off): a fixture this seam switched OFF goes back on —
    # that IS a mode change, the one moment power may move.
    st = house_store.state()
    pending_off = set(house.mode_power_off_scope() or ())
    for did in sorted((set(_rt.applied) | set(st.power_applied)) - set(want)):
        prev = _rt.applied.pop(did, None)
        rec = _forget_power(did)
        was_off = ((prev is not None and prev.target == TARGET_OFF)
                   or (isinstance(rec, dict) and rec.get("target") == TARGET_OFF))
        if was_off and did in scope and did not in pending_off:
            dev = host.devices.get(did)
            if dev is not None and _controllable(dev):
                _start(did, TARGET_ON, "handed back on — no mode drives it now",
                       host, owned=False, withhold_until_on=True)

    mode_key = _mode_key()
    for did, (target, why) in want.items():
        prev = _rt.applied.get(did)
        infl = _rt.inflight.get(did)
        if infl is not None:
            if infl[0] == target:
                continue
            infl[1].cancel()
            _rt.inflight.pop(did, None)
            _rt.pending_on.discard(did)
        if _power_due(did, target, mode_key):
            _start(did, target, why, host, owned=True, mode_key=mode_key,
                   withhold_until_on=_was_withheld(did))
        elif prev is None or prev.target != target:
            # Nothing owed (a restart under the same mode, say): the fixture
            # is left exactly as it is — never re-asserted.
            now_ms_ = now_ms()
            _rt.applied[did] = _Applied(
                target=target, outcome="kept",
                detail="left as it is — power is switched only when the "
                       "house mode changes", at=now, at_ms=now_ms_,
                last_check=now)
        elif (target == TARGET_UNPOWERED
              and now - _rt.knocked_at.get(did, prev.at) >= MAINS_KNOCK_S):
            _rt.knocked_at[did] = now
            _start_knock(did)
    for did in list(_rt.knocked_at):
        if did not in want or want[did][0] != TARGET_UNPOWERED:
            _rt.knocked_at.pop(did, None)
    _push_withheld(want)


def _start(did: str, target: str, why: str, host, *, owned: bool,
           withhold_until_on: bool = False, mode_key: str = "") -> None:
    dev = host.devices.get(did)
    if dev is None:
        return
    if target == TARGET_ON and withhold_until_on:
        _rt.pending_on.add(did)
    task = asyncio.get_running_loop().create_task(
        _transition(did, dev, target, why, owned=owned, mode_key=mode_key),
        name=f"house-fixture-{did}")
    _rt.inflight[did] = (target, task)


def _start_knock(did: str) -> None:
    if did in _rt.inflight:
        return
    task = asyncio.get_running_loop().create_task(
        _knock(did), name=f"house-fixture-knock-{did}")
    _rt.inflight[did] = (TARGET_UNPOWERED, task)


async def _knock(did: str) -> None:
    """One json/info at a mains-off fixture's last address. An answer means
    its mains are on after all (Home Assistant's call was missed): clear the
    report, say so, and re-find it. Silence changes nothing."""
    try:
        try:
            ok, _why = await deps.reachable(did)
        except Exception:                                # noqa: BLE001
            ok = False
        if not ok:
            return
        st = house_store.state()
        if did not in st.mains_off:
            return
        st.mains_off.pop(did, None)
        house_store.save_state()
        logger.warning("house fixtures: %s answered although Home Assistant "
                       "reported its mains off — treating its mains as on "
                       "(was the 'mains on' call missed?)", did)
        _record("mains", {"device": did, "on": True,
                          "source": "spectra (it answered)"})
        _rt.applied.pop(did, None)
        kick()
    finally:
        cur = _rt.inflight.get(did)
        if cur is not None and cur[1] is asyncio.current_task():
            _rt.inflight.pop(did, None)


async def _write_confirmed(dev, payload: dict, check: Callable[[dict], bool]
                           ) -> tuple[str, str, Optional[dict]]:
    """POST `payload`, read json/state back, retry a refusal. (outcome,
    detail, last state read) — landed / unconfirmed / failed: "we could not
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
                error = f"the fixture reports on={last.get('on')}"
        if attempt < WRITE_ATTEMPTS - 1:
            await deps.sleep(WRITE_SPACING_S)
    if accepted and last is None:
        return "unconfirmed", error, None
    return "failed", error, last


async def _transition(did: str, dev, target: str, why: str, *, owned: bool,
                      mode_key: str = "") -> None:
    """Carry out ONE change of what the house asks of a fixture. Power only
    — `{"on": …}` / `{"live": false}`; a WLED's master brightness is Home
    Assistant's and is never in a payload here (module docstring)."""
    outcome, detail = "sent", ""
    if owned and target in (TARGET_ON, TARGET_OFF):
        await _remember_before(did, dev)
    try:
        if target == TARGET_UNPOWERED:
            # Its mains are off: there is nothing to write to and nothing to
            # read back. The withheld set (pushed this pass) is the act.
            outcome = "withheld"
        elif target == TARGET_LENT:
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
            # stream is already withheld (on house.py's faded-to-black
            # frame); this ends realtime, then powers the fixture down.
            try:
                await deps.post(dev, {"live": False})
            except Exception as exc:                     # noqa: BLE001
                detail = f"leaving realtime failed ({type(exc).__name__})"
            outcome, more, _last = await _write_confirmed(
                dev, {"on": False}, lambda s: s.get("on") is False)
            detail = "; ".join(x for x in (detail, more) if x)
        else:   # TARGET_ON
            outcome, detail, _last = await _write_confirmed(
                dev, {"on": True}, lambda s: s.get("on") is True)
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
        # Recorded whatever the outcome: a write that did not land is NOT
        # retried on the clock (D2a — nothing is re-asserted); the status
        # names it, and the next mode change writes again.
        _record_power(did, target, mode_key)
    level = logging.WARNING if outcome == "failed" else logging.INFO
    logger.log(level, "house fixtures: %s -> %s (%s): %s%s", did, target, why,
               outcome, f" — {detail}" if detail else "")
    _record("fixture_" + target, {"device": did, "why": why, "outcome": outcome,
                                  "detail": detail})
    kick()


# ── hand-back: what a fixture was before Spectra took it over ──────────────

async def _remember_before(did: str, dev) -> None:
    """Read a WLED's POWER before Spectra's FIRST power write to it
    (HAND-BACK). An unreadable fixture records nothing — there is nothing
    honest to hand back. The first reading wins until it is handed back.
    Its brightness is not recorded: Spectra never changes it, so there is
    nothing of it to give back."""
    st = house_store.state()
    if did in st.pre_take or not _controllable(dev):
        return
    ip = getattr(getattr(dev, "wled", None), "ip_address", None)
    if not ip:
        return
    try:
        state = await deps.get_state(dev)
    except Exception:                                    # noqa: BLE001
        return
    on = state.get("on")
    if not isinstance(on, bool):
        return
    st.pre_take[did] = {"on": on, "ip": str(ip), "at_ms": now_ms()}
    house_store.save_state()


def _maybe_hand_back() -> None:
    st = house_store.state()
    if not deps.released():
        return
    if not st.pre_take:
        if st.power_applied:
            # A take of a released room is a fresh start: the next mode
            # writes its power again.
            st.power_applied.clear()
            house_store.save_state()
        return
    task = _rt.handback_task
    if task is not None and not task.done():
        return
    _rt.handback_task = asyncio.get_running_loop().create_task(
        _hand_back(), name="house-fixture-hand-back")


async def _hand_back() -> None:
    """The room was released: put every WLED's POWER back where it was
    before Spectra took it over — only where Spectra's own last power write
    left it different (a fixture Spectra never switched is never touched).
    `{"on": …}` only: no brightness, ever. Each write is read back; a
    fixture that does not confirm is retried on later passes, then dropped
    and named."""
    st = house_store.state()
    for did, before in sorted(st.pre_take.items()):
        if not deps.released():
            return
        ip = before.get("ip")
        payload: dict = {"on": bool(before.get("on"))}
        rec = st.power_applied.get(did)
        last_on = rec.get("on") if isinstance(rec, dict) else None
        if last_on is None or last_on is payload["on"]:
            # Spectra's own last switch left it as it was before the take
            # (or Spectra never switched it): nothing of ours to undo.
            st.pre_take.pop(did, None)
            st.power_applied.pop(did, None)
            _rt.handback_attempts.pop(did, None)
            continue
        outcome, detail = "failed", "no address recorded"
        if ip:
            try:
                await deps.post_ip(ip, payload)
                state = await deps.get_ip(ip)
                if state.get("on") is payload["on"]:
                    outcome, detail = "landed", ""
                else:
                    detail = f"the fixture reports on={state.get('on')}"
            except Exception as exc:                     # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
        tries = _rt.handback_attempts.get(did, 0) + 1
        if outcome == "landed" or tries >= HANDBACK_ATTEMPTS or not ip:
            st.pre_take.pop(did, None)
            st.power_applied.pop(did, None)
            _rt.handback_attempts.pop(did, None)
            entry = {"at_ms": now_ms(), "device": did, "set": payload,
                     "outcome": outcome, "detail": detail}
            _rt.handed_back.append(entry)
            del _rt.handed_back[:-MAX_RECENT]
            level = logging.INFO if outcome == "landed" else logging.WARNING
            logger.log(level, "house fixtures: handed %s back after the release "
                       "(%s): %s%s", did, payload, outcome,
                       f" — {detail}" if detail else "")
            _record("fixture_handed_back", entry)
        else:
            _rt.handback_attempts[did] = tries
    if not st.pre_take:
        st.power_applied.clear()
    house_store.save_state()


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
    activation report's own 30 s recheck already does. The mode's power is
    re-applied only while a mode drives the room; brightness never is."""
    from spectra.services import show_output
    refusal = show_output.ownership_refusal()
    host = deps.host()
    names = [f for f in (fixtures or []) if str(f).strip()]
    if not names:
        return {"status": "invalid", "reason": "name at least one fixture"}
    # "I just powered the sconce mains" says the mains are ON — a fact
    # recorded whatever the room's state (phase 3: it ends a mains-off).
    _clear_mains_off(names, source="recheck")
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
                # Its power is whatever its boot preset says: forget what we
                # last applied so the next pass writes the mode's power
                # again (never a brightness — that stays Home Assistant's).
                _rt.applied.pop(did, None)
                _forget_power(did)
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
    want = desired()
    fixtures = []
    host = deps.host()
    ids = set(want) | set(_rt.applied) | set(st.fixtures) | set(st.mains_off)
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
        "brightness_owner": "home_assistant",
        "tv_music": st.tv_music,
        "fixtures": fixtures,
        "withheld": device_output.withheld(),
        "power_applied": {d: dict(r) for d, r in st.power_applied.items()},
        "rechecks": dict(_rt.rechecks),
        "mains_off": dict(st.mains_off),
        "pre_take": {d: {k: v for k, v in b.items() if k in ("on", "at_ms")}
                     for d, b in st.pre_take.items()},
        "handed_back": list(reversed(_rt.handed_back[-5:])),
    }
