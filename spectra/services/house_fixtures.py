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
             WLED off: no stream, then {"on": false}. On: {"on": true} (and
             the preserved ceiling brightness below), THEN the stream — the
             order a powered-off WLED needs whatever its firmware does with
             a stream while off (spectra/services/night_power.py says why
             that is unknown).
  BRIGHTNESS (REWORKED 2026-10-06, Admiral order: the crystal kept getting
             set to 100% in Home Assistant, far too bright — HIS brightness
             is the ceiling, nothing may raise it. REWORKED AGAIN the SAME
             night: see "BRIGHTNESS IS NEVER ADOPTED" below.) Spectra never
             WRITES a WLED's master brightness upward. Before its first
             write to a fixture this take it reads the brightness already
             there — his own last setting, via Home Assistant or the
             fixture's own boot preset — and that reading
             (`HouseState.pre_take[did]["bri"]`) is the CEILING for the rest
             of the take, capped further only by `owned_brightness` if he
             has set that lower (default 255 = no extra cap). A power-on
             restores exactly that ceiling value, never a forced 255. A
             fixture read back AT OR BELOW its ceiling — including a fresh,
             lower Home Assistant brightness write — is left alone. A
             reading ABOVE the ceiling is always corrected back down
             (`_drift_check`) — never adopted as a new ceiling, whatever its
             cause. Each correction is still NAMED (status, log, fire
             history).

  BRIGHTNESS IS NEVER ADOPTED (fixed 2026-10-06, the night of the
             crystal-255 incident — PR fm/crystal-255-followup). The FIRST
             version of this rework (above) adopted an overshoot with "no
             reboot evidence" as his own deliberate Home Assistant raise,
             on the theory that absence of a reboot proves deliberate
             intent. The very first night it shipped, the crystal's bri
             rose from his 34 to 255 with no reboot — and River's own HA
             trace proved Home Assistant never touched it (no scene, no
             automation, an empty logbook, a silent pretake endpoint) while
             a grep of Spectra's own `house fixtures:` log showed no
             `_transition`/`_write_confirmed` write of any kind landed on
             the fixture in that window either. So "no reboot evidence" is
             not evidence of a deliberate raise — it is silence, from
             EITHER side, and silence must never be read as his word.
             `_drift_check` now corrects EVERY overshoot back down,
             reboot-explained or not — there is no third path that adopts
             anything. `_looks_like_our_own_echo`/`_rt.written_bri` track
             every bri value Spectra itself has written this take purely so
             the correction's own log line can say whether the overshoot
             looks like Spectra's own lingering value (e.g. a ceiling that
             was fine until `owned_brightness` tightened under it) or a
             value nobody here ever asked for — diagnostic only, it changes
             nothing about the correction itself.

             SPECTRA HAS NO HA READ PATH — checked, not assumed, before
             shipping the always-correct-down rule above. Spectra talks to
             Home Assistant in exactly one direction: HA calls IN
             (`PUT /api/house/mode`, the fixture/mains/tv_music reports
             above) — grep-confirmed zero references anywhere in this repo
             to an outbound HA client, token, or base URL. So a genuinely
             deliberate HA brightness raise cannot be told apart from
             anything else here; adopting ANY raise as his automatically,
             the way the first rework did, is what adopted the one HA
             never made. A later follow-up that lets a real HA raise stand
             without waiting on the next reboot needs Spectra to read
             `light.crystal_dining_room`'s (etc.) own HA state back —
             not built here.

             THE REMAINING CANDIDATES for the 2026-10-06 21:45:49 raise,
             and what each would have left behind: a WLED-side PRESET
             (button/IR remote/macro) would show as `json/state`'s `"ps"`
             holding a non -1 id at the moment, but WLED keeps no log of a
             preset firing and clearing itself, so this is unprovable after
             the fact either way. The NIGHTLIGHT timer (`"nl"`) ramps
             TOWARD its own configured target (`tbri`), which is 0 on this
             fixture — it dims, it does not explain a rise to 255,
             regardless of whether it ever fired. A UDP SYNC PEER (WLED's
             native port-21324 broadcast, `recv.bri` on this fixture) was
             checked live: crystal's own sync group (1) has no peer with
             `send.en` true — `porch-rail`/`tv-backlight` (its only
             group-1 peers) both have sync sending off; the sconces DO
             send but sit in group 2, which WLED's group bitmask keeps
             from reaching a group-1 receiver — ruled out as far as the
             CURRENT config can show (WLED keeps no received-sync log
             either). The external LedFX SERVICE was ruled out directly:
             `ledfx.service` is disabled, was `inactive` with no
             `ActiveEnterTimestamp` and has zero journal entries across
             the whole incident window — and `ownership_reconciler.py`
             would have CRITICAL-logged a foreign writer on this device,
             which never appears. What is left, matching firstmate's own
             "or the user's" phrasing and leaving zero forensic trace on
             either HA's or Spectra's side by construction (WLED's JSON
             API keeps no request log or client IP at all): THE WLED APP
             OR ITS OWN WEB UI, used directly on the LAN, bypassing both
             Home Assistant and Spectra.
  RECHECK    "I just powered the sconce mains": re-find the named fixtures by
             identity (a mains cycle is when a WLED takes a new DHCP lease),
             re-init a driver that never resolved, and re-apply the power /
             brightness the moment each one answers — seconds instead of the
             activation report's 30 s recheck.

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

SOFT POWER (phase 3). Spectra manages the switch, so a switch-off first
drops `bri` to SOFT_BRI under the (withheld, so frozen) last frame, then
leaves realtime, then switches off — the WLED's own preset never shows at
full brightness between the two. A power-on from withheld writes
`{"on": true, "bri": SOFT_BRI}`, lets the stream resume, and only then
raises `bri` back to the preserved CEILING (never a forced 255): the preset
is never seen at full either. Both apply only while Spectra owns the
brightness; with ownership off the phase 2 sequence is unchanged.

HAND-BACK (phase 3). Before its FIRST write to a WLED this take, Spectra
reads the fixture's power and brightness (HouseState.pre_take, durable — it
survives a restart that keeps the picture) — this reading is BOTH the
ceiling above and what gets handed back; when the room is RELEASED it
writes them back (`{"on": …, "bri": …}`, read back) to the address it had,
after the release's own `{"live": false}`. Found 2026-10-05: a take left his
dining table under-glow ON at full — it had been off, and River's restore
does not capture it. The rule: a fixture that was off before a take is off
after. Only a release hands back: a handover to the older SpotFX process
needs the fixtures on, and a restart keeps the picture.

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
#: phase 3: SOFT POWER — the master brightness a fixture passes through on
#: its way off or on, and how long the stream runs at it before the owned
#: brightness is written (several frames even at a 10 fps cap)
SOFT_BRI = 1
SOFT_ON_SETTLE_S = 0.3
#: phase 3: a fixture reported mains-off has its last address knocked on
#: this often, in case Home Assistant's "mains on" was missed
MAINS_KNOCK_S = 600.0
#: phase 3: HAND-BACK — attempts per fixture before it is dropped (named)
HANDBACK_ATTEMPTS = 3
#: how often a TV strip's own `live` flag (is Hyperion actually streaming
#: to it right now) is re-read — one json/info per strip per this long,
#: never per tick.
HYPERION_CHECK_S = 5.0

TARGET_ON = "on"        # streamed, powered on, owned brightness
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


def _get_info_blocking(wled, timeout: float) -> dict:
    """json/info, not json/state — `uptime` (ms since boot) only ever shows
    up there, the same split dark_fixture_watch.py / live_host.py already
    document for `live`."""
    import requests
    response = asyncio.run(wled._wled_request(
        requests.get, wled.ip_address, "json/info", timeout=timeout))
    body = response.json()
    if not isinstance(body, dict):
        raise TypeError(f"json/info returned {type(body).__name__}")
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


async def _default_get_info(device) -> dict:
    wled = getattr(device, "wled", None)
    if wled is None:
        raise RuntimeError("its driver never reached the fixture (no address)")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_info_blocking, wled,
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
    get_info: Callable[[Any], Awaitable[dict]] = _default_get_info
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
    corrections: list = field(default_factory=list)
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
    #: device -> the last `json/info` uptime (ms since boot) seen for it —
    #: diagnostic only (`_rebooted_since_last_check`'s docstring says why it
    #: no longer gates adoption). Seeded at the fixture's first remembered
    #: reading.
    uptime_ms: dict = field(default_factory=dict)
    #: device -> set of bri values SPECTRA ITSELF has written this take
    #: (`_remember_written_bri`) — so a drift correction can tell its own
    #: lingering echo apart from a value it never authored, in the log
    #: only; brightness is never adopted either way (see `_drift_check`).
    written_bri: dict = field(default_factory=dict)


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


def _brightness_ceiling(did: str, settings) -> Optional[int]:
    """The brightness Spectra may hold this fixture at for the rest of this
    take — HIS OWN level (`pre_take`, read before Spectra's first write),
    capped further only by `owned_brightness` if he has set that lower.

    Never a value to force upward: `None` means "nothing captured yet, so
    don't touch brightness at all" — the same "unknown never acts" rule
    this module already applies to an unreadable fixture elsewhere."""
    if not settings.own_brightness:
        return None
    st = house_store.state()
    pre = st.pre_take.get(did)
    his_level = pre.get("bri") if pre else None
    if not isinstance(his_level, int) or his_level <= 0:
        return None
    return min(his_level, int(settings.owned_brightness))


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
    mode_off = house.mode_off_devices()
    power_off_pending = house.mode_power_off_scope()
    power_off_phase_active = house.mode_off_phase_active()
    strips = set(tv_strip_ids())
    out: dict[str, tuple[str, str]] = {}
    for did in _in_scope_devices(host):
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
        elif _controllable(dev) and settings.own_brightness:
            ceiling = _brightness_ceiling(did, settings)
            if ceiling is not None:
                why = f"Spectra holds it on, never above his own brightness ({ceiling})"
            else:
                why = "Spectra holds it on"
            out[did] = (TARGET_ON, why)
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
        elif (target == TARGET_UNPOWERED
              and now - _rt.knocked_at.get(did, prev.at) >= MAINS_KNOCK_S):
            _rt.knocked_at[did] = now
            _start_knock(did)
    for did in list(_rt.knocked_at):
        if did not in want or want[did][0] != TARGET_UNPOWERED:
            _rt.knocked_at.pop(did, None)
    _push_withheld(want)


def _start(did: str, target: str, why: str, host, *, owned: bool,
           withhold_until_on: bool = False) -> None:
    dev = host.devices.get(did)
    if dev is None:
        return
    if target == TARGET_ON and withhold_until_on:
        _rt.pending_on.add(did)
    task = asyncio.get_running_loop().create_task(
        _transition(did, dev, target, why, owned=owned,
                    soft=(withhold_until_on and owned)),
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


async def _transition(did: str, dev, target: str, why: str, *, owned: bool,
                      soft: bool = False) -> None:
    settings = _settings()
    outcome, detail = "sent", ""
    soft = soft and owned and settings.own_brightness
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
            # stream is already withheld; this ends realtime, then powers
            # the fixture down. SOFT POWER: while Spectra owns the master
            # brightness it first drops it under the frozen last frame, so
            # the WLED's own preset never shows at full in between.
            if owned and settings.own_brightness:
                # Only a fixture that is ON is dimmed first: a bare "bri"
                # write turns an OFF WLED on (its JSON API reads a
                # brightness above zero as "on"). Unreadable = skip the dim.
                try:
                    current = await deps.get_state(dev)
                except Exception:                        # noqa: BLE001
                    current = None
                if current is not None and current.get("on") is True:
                    try:
                        await deps.post(dev, {"bri": SOFT_BRI})
                    except Exception as exc:             # noqa: BLE001
                        detail = f"soft dim failed ({type(exc).__name__})"
            try:
                await deps.post(dev, {"live": False})
            except Exception as exc:                     # noqa: BLE001
                detail = "; ".join(x for x in (
                    detail, f"leaving realtime failed ({type(exc).__name__})") if x)
            outcome, more, _last = await _write_confirmed(
                dev, {"on": False}, lambda s: s.get("on") is False)
            detail = "; ".join(x for x in (detail, more) if x)
        else:   # TARGET_ON
            payload: dict = {"on": True}
            if owned:
                ceiling = _brightness_ceiling(did, settings)
                if ceiling is not None:
                    payload["bri"] = ceiling
                    _remember_written_bri(did, ceiling)
            want_bri = payload.get("bri")
            if soft:
                # SOFT POWER: on at the soft brightness, let the stream back
                # (pending_on cleared), and only then the preserved ceiling —
                # the WLED's own preset is never seen at full.
                s_out, s_detail, _s = await _write_confirmed(
                    dev, {"on": True, "bri": SOFT_BRI},
                    lambda s: s.get("on") is True)
                if s_out != "landed":
                    detail = f"soft power-on {s_out}: {s_detail}"
                _rt.pending_on.discard(did)
                await deps.sleep(SOFT_ON_SETTLE_S)
            outcome, more, _last = await _write_confirmed(
                dev, payload,
                lambda s: s.get("on") is True and (want_bri is None
                                                   or s.get("bri") == want_bri))
            detail = "; ".join(x for x in (detail, more) if x)
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


async def _rebooted_since_last_check(did: str, dev) -> bool:
    """Has this WLED's own `json/info` uptime reset or dropped since the
    last time this module read it. DIAGNOSTIC ONLY — see the 2026-10-06
    night correction below for why it no longer gates anything. Never
    checked before, or unreadable, reads as "no reboot seen" (the weaker
    claim), not as evidence either way.

    Called on EVERY drift check for a fixture Spectra holds on, not only
    when an overshoot is found, so the baseline never goes stale for the
    rest of the take."""
    try:
        info = await deps.get_info(dev)
    except Exception:                                    # noqa: BLE001
        return False
    uptime = info.get("uptime")
    if not isinstance(uptime, (int, float)):
        return False
    prev = _rt.uptime_ms.get(did)
    _rt.uptime_ms[did] = uptime
    return prev is not None and uptime < prev


def _looks_like_our_own_echo(did: str, found_bri: int) -> bool:
    """Is `found_bri` a value SPECTRA ITSELF is on record having written to
    this fixture this take (`_rt.written_bri`, populated by every landed
    bri write in `_transition`/`_drift_check`) — our own prior ceiling,
    lingering after `owned_brightness` tightened, or any other value we
    ourselves are the author of. This is NEVER evidence of a deliberate
    outside (Home Assistant or his own) action; a correction must not
    read our own echo back to ourselves as his word."""
    return found_bri in _rt.written_bri.get(did, ())


def _remember_written_bri(did: str, value: int) -> None:
    seen = _rt.written_bri.setdefault(did, set())
    seen.add(value)


async def _drift_check(did: str, dev, target: str) -> None:
    """Read json/state back; re-assert power if something else moved it.

    BRIGHTNESS IS NEVER ADOPTED — fixed 2026-10-06, the night of the
    crystal-255 incident. The earlier shape ("no reboot evidence behind an
    overshoot means it is his own deliberate Home Assistant raise, adopt
    it") was proven, the same evening, to adopt a raise HOME ASSISTANT DID
    NOT MAKE (River's own HA trace: no scene, no automation, the logbook
    silent, the pretake endpoint silent) and that SPECTRA'S OWN logged
    write path never made either (grepped against the live journal: no
    `_transition`/`_write_confirmed` write of any kind landed on the
    fixture in the window the overshoot appeared in). With no channel that
    can tell "Home Assistant/the user changed this" from "something else
    did", the absence of a reboot is not evidence of EITHER — it is
    silence, and silence must not be read as his word. So an overshoot
    above the preserved ceiling is ALWAYS corrected back down, whether or
    not a reboot explains it; the two are distinguished only in the log
    and in `_looks_like_our_own_echo`'s diagnostic note, never in the
    action taken. A reading AT OR BELOW the ceiling, including a fresh,
    lower Home Assistant brightness write, is still his and is never
    fought back up. An unreadable fixture is left alone — unknown never
    acts."""
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
            rebooted = await _rebooted_since_last_check(did, dev)
            ceiling = _brightness_ceiling(did, settings)
            over_ceiling = (ceiling is not None and isinstance(found_bri, int)
                           and found_bri > ceiling)
            if found_on is True and not over_ceiling:
                return
            payload = {"on": True}
            want_bri = ceiling
            if want_bri is not None:
                payload["bri"] = want_bri
                _remember_written_bri(did, want_bri)
            check = (lambda s: s.get("on") is True
                     and (want_bri is None or s.get("bri") == want_bri))
            if over_ceiling:
                echo = _looks_like_our_own_echo(did, found_bri)
                logger.warning(
                    "house fixtures: %s read %s above its ceiling (%s) — %s; "
                    "correcting it back down, never adopting it", did,
                    found_bri, ceiling,
                    "a value Spectra itself wrote earlier this take, now "
                    "past a tightened cap" if echo else
                    ("no reboot evidence behind it" if not rebooted
                     else "a reboot's own boot preset"))
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


# ── hand-back: what a fixture was before Spectra took it over ──────────────

async def _remember_before(did: str, dev) -> None:
    """Read a WLED's power and brightness before Spectra's FIRST write to it
    (HAND-BACK). An unreadable fixture records nothing — there is nothing
    honest to hand back. The first reading wins until it is handed back."""
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
    on, bri = state.get("on"), state.get("bri")
    if not isinstance(on, bool):
        return
    st.pre_take[did] = {"on": on, "bri": bri if isinstance(bri, int) and bri > 0 else None,
                        "ip": str(ip), "at_ms": now_ms()}
    house_store.save_state()
    # Seed the reboot baseline from the SAME take-start moment, so the
    # first later overshoot already has something to compare against
    # rather than defaulting to "never checked" (see _rebooted_since_
    # last_check). Best-effort: a fixture that can't answer json/info
    # still gets its on/bri ceiling above.
    try:
        info = await deps.get_info(dev)
    except Exception:                                    # noqa: BLE001
        return
    uptime = info.get("uptime")
    if isinstance(uptime, (int, float)):
        _rt.uptime_ms[did] = uptime


def _maybe_hand_back() -> None:
    st = house_store.state()
    if not st.pre_take or not deps.released():
        return
    task = _rt.handback_task
    if task is not None and not task.done():
        return
    _rt.handback_task = asyncio.get_running_loop().create_task(
        _hand_back(), name="house-fixture-hand-back")


async def _hand_back() -> None:
    """The room was released: put every WLED Spectra took over back to the
    power and brightness it had before. Each write is read back; a fixture
    that does not confirm is retried on later passes, then dropped and
    named."""
    st = house_store.state()
    for did, before in sorted(st.pre_take.items()):
        if not deps.released():
            return
        ip = before.get("ip")
        payload: dict = {"on": bool(before.get("on"))}
        if before.get("bri"):
            # with "on": false a brightness is remembered for the next "on"
            payload["bri"] = int(before["bri"])
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
    activation report's own 30 s recheck already does. Power and brightness
    are re-applied only while a mode drives the room."""
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
        "own_brightness": settings.own_brightness,
        "owned_brightness": settings.owned_brightness,
        "tv_music": st.tv_music,
        "fixtures": fixtures,
        "withheld": device_output.withheld(),
        "corrections": list(reversed(_rt.corrections[-5:])),
        "rechecks": dict(_rt.rechecks),
        "mains_off": dict(st.mains_off),
        "pre_take": {d: {k: v for k, v in b.items() if k != "ip"}
                     for d, b in st.pre_take.items()},
        "handed_back": list(reversed(_rt.handed_back[-5:])),
    }
