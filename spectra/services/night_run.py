"""THE NIGHT RUN — Home Assistant pushes one event when he has been asleep
for half an hour, and the declared capture queue works through the night.

THE BOTTLENECK THIS REMOVES, one layer above the one `capture_queue` removed:
that module took the PRESSING out of a capture run; this takes the STAYING
UP out of it. Every overnight run so far began with him personally setting a
session up before bed, so every capture experiment still queued behind his
evenings. His `Sleeping` helper going on for thirty continuous minutes is a
better signal than a person, and Home Assistant already has it.

    POST /api/night-run/start   {"event": "sleep-window-start", "ts": ...,
                                 "source": "home-assistant"}
    POST /api/night-run/abort   {"event": "sleep-ended" | ..., "ts": ...}
    GET  /api/night-run/fixtures    the two lists the morning backstop needs
    GET/PUT /api/night-run/queue    the declaration

HE PUSHES; WE NEVER POLL. Nothing in this module or its route reaches out to
Home Assistant, on any cadence, for any reason. The events arrive and the
reads are answered. That was an explicit instruction and it is also the
whole reason the seam is cheap enough to leave running.

────────────────────────────────────────────────────────────────────────────
THE BOUNDARY — the one thing in this file that is not negotiable.
────────────────────────────────────────────────────────────────────────────

A START EVENT ARRIVING WHILE SPECTRA DOES NOT ALREADY HOLD THE ROOM IS
DECLINED, by name, recorded, and nothing else happens. It does not take the
room. It does not request a handover. It does not queue itself behind one.
The Admiral's word, embedded on the order: the night trigger gets NO
room-take exception, ever — "it does not help itself to his room while he
sleeps. That boundary is worth more than an occasional missed night."

A DECLINE IS A NORMAL RECORDED OUTCOME, not an error and not a failure. It
is written to `night_runs.json` with `mapping_refusals.night_not_owned`'s
own sentence, which is what makes "did last night run?" a read rather than a
silence indistinguishable from the seam being broken. Home Assistant is told
nothing beyond the refusal; River's own takeover queue records the miss.

────────────────────────────────────────────────────────────────────────────
WHAT IT REUSES, AND WHY IT ADDS NO GATE OF ITS OWN
────────────────────────────────────────────────────────────────────────────

Everything a run does goes through `capture_runs`, exactly as the button and
the daytime queue do: the exposure lock, the ownership refusal, the hold
ceiling, the one-run-at-a-time lock, the pose rules. There is no "night
mode" a run behaves differently under, and this module can acquire no
capability a person pressing Start does not have. That is deliberate and it
is the same reasoning `capture_runs`' own docstring gives for existing.

The queue is `capture_queue`'s, run through `run_queue` (rather than
`start`) so completion is a plain await instead of something to watch.

ABORT is `mapping_session`'s own `run_abort` plus `capture_queue.stop()`
plus `flare_preview_hold.close_hold()` — three pieces of existing machinery,
no fourth invented. Setting `run_abort` is what stops the run in flight at
its next emitter boundary WITH ITS PARTIALS KEPT (`room_mapping` checks it
before every capture and reports `partial`); `stop()` is what keeps the
remaining items from starting; `close_hold()` is what actually hands his
room back. A short bounded grace lets the run land its own revert first,
because that is the tidier of the two paths — and then the hold is closed
regardless, because "a touched house is his house" outranks tidiness.

────────────────────────────────────────────────────────────────────────────
TWO THINGS THIS OWNS THAT NOTHING ELSE DID
────────────────────────────────────────────────────────────────────────────

POWER (`night_power.py`): at 1am his fixtures may be switched off, and a
capture of an unlit fixture is a photograph, not a footprint. The run turns
on exactly the fixtures it is about to drive and puts his switch back in a
`finally` — the `fixture_brightness.owned` pattern, one layer down. That
module's docstring carries what was ESTABLISHED about a powered-off WLED
under a realtime stream and, more importantly, what was not.

THE HONEST EXIT (`night_exit.py`): at the end of every night — normal, ended
by his morning, AND aborted — every fixture is read back AT THE EMITTED
LIGHT and the report names what is dark, what still emits and why. A mode
read is not verification. This is the standard's first application and the
report is part of the run record, not a log line.

────────────────────────────────────────────────────────────────────────────
TWO THINGS THIS DELIBERATELY DOES NOT OWN
────────────────────────────────────────────────────────────────────────────

THE HOUSE LIGHTS ARE HOME ASSISTANT'S. His house has an HA scene "Dark
Music" that darkens everything EXCEPT the SPECTRA-controlled fixtures;
River's side fires it before sending start and restores it after the run
ends. NOTHING HERE FIRES A HOUSE SCENE, touches a house light, or assumes
one is off. The envelope is somebody else's act.

And it is NOT a substitute for checking, by the captain's explicit order:
the emitted-light verification stays mandatory, and a fixture found
emitting at exit is NAMED whether it is one the run drove, one the Dark-mode
shield exempts, or one of the house's that the envelope was supposed to have
darkened. An envelope that is believed rather than read is exactly the "the
setting is not the light" failure this exit report exists for.

NOTHING HERE KNOWS WHERE THE CAMERA IS. The capture client runs on a small
remote machine near the camera (Raspberry Pi class), not on the SPECTRA
host, and reaches this process over the network like the phone always did.
There is no localhost, no hostname and no address anywhere on this path — a
session is whatever connected, and `capture_runs.session_view()` is the only
thing asked about it. Do not bake one in.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Optional

from spectra import config as scfg
from spectra.services import capture_queue, capture_runs, mapping_refusals

logger = logging.getLogger(__name__)

#: Nights kept in the store. Each record is bounded by construction (per-item
#: summaries from `capture_queue`, one exit row per fixture), so this is a
#: history depth rather than a size guard — the same reasoning
#: `capture_queue.MAX_STORED_QUEUES` carries.
MAX_STORED_NIGHTS = 60

#: How long an abort waits for the run in flight to notice `run_abort` and
#: land its own revert before the hold is closed out from under it. Short on
#: purpose: the binding requirement is "restore his chosen dark state within
#: seconds", and letting the run finish its current emitter is a nicety, not
#: the promise.
ABORT_GRACE_S = 4.0
ABORT_POLL_S = 0.2

#: THE HARD PLANNED END — his Home Assistant morning routine runs the
#: morning flag at 05:30 HOUSE TIME and the BLINDS OPEN around 05:40.
#: Daylight in the frame is a capture CONTAMINANT, not merely an
#: interruption, so this is a bound and not a preference: no capture work is
#: ever scheduled past it, and a declared queue that cannot fit inside the
#: remaining window is refused by name before the room goes dark.
#:
#: HOUSE TIME, not UTC and not the process's locale — a systemd unit's TZ is
#: not a fact about his house. Same zone `spectra/services/sonic_usage.py`
#: anchors its own week to, for the same reason.
HOUSE_TZ = "America/New_York"
PLANNED_END_HOUR = 5
PLANNED_END_MINUTE = 30
#: What the record and every refusal call it, so the sentence and the field
#: cannot describe two different times.
PLANNED_END_LABEL = "05:30 house time"

STATE_RUNNING = "running"
STATE_COMPLETE = "complete"
STATE_ABORTED = "aborted"
#: HIS MORNING ROUTINE ended it — a PLANNED, ordinary ending, deliberately
#: not folded into `aborted`. See `mapping_refusals.night_ended_by_morning`
#: for why the two are different facts.
STATE_ENDED_BY_MORNING = "ended_by_morning"
STATE_DECLINED = "declined"
STATE_FAILED = "failed"


def _queue_path(path=None):
    return path or scfg.NIGHT_QUEUE_FILE


def _runs_path(path=None):
    return path or scfg.NIGHT_RUNS_FILE


def _atomic_write(path, body: dict) -> None:
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(path)) or ".",
                               prefix="night-run", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── the declaration ────────────────────────────────────────────────────────

def declared(path=None) -> bool:
    """Whether a night queue is declared, WITHOUT parsing it. On the
    `engine.status()` poll path, which answers every few seconds — the
    presence of a file is the whole question there."""
    p = _queue_path(path)
    try:
        return os.stat(p).st_size > 0
    except OSError:
        return False


def load_declaration(path=None) -> Optional[dict]:
    """The night queue he declared in advance, or None.

    A DECLARATION, not a composition: the list is fixed while he is awake
    and has hours to fix a typo in it, rather than being assembled by
    something at 1am on the item nobody reads. `capture_queue.parse_items`
    is the one validator, so a night queue and a daytime queue cannot drift
    into two dialects."""
    p = _queue_path(path)
    try:
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except Exception:                                   # noqa: BLE001
        logger.exception("night run: unreadable night queue %s", p)
        return None
    if not (body or {}).get("items"):
        return None
    return body


def save_declaration(label: str, items: list[dict], path=None) -> dict:
    """Store a declared night queue, VALIDATED FIRST. Raises ValueError with
    `capture_queue`'s own sentence when the list will not parse — refusing a
    typo at declaration is the entire reason this is declared ahead."""
    capture_queue.parse_items(items)                    # refuses, or returns
    body = {"label": str(label or ""), "items": list(items),
            "declared_at": time.time()}
    _atomic_write(_queue_path(path), body)
    return body


def clear_declaration(path=None) -> bool:
    p = _queue_path(path)
    if not os.path.exists(p):
        return False
    os.unlink(p)
    return True


# ── the record ─────────────────────────────────────────────────────────────

@dataclass
class NightRun:
    id: str
    state: str
    #: The event that started (or declined) this night, verbatim.
    trigger: dict = field(default_factory=dict)
    started: float = 0.0
    ended: float = 0.0
    #: `mapping_refusals`' own sentence when this night declined or aborted.
    detail: str = ""
    #: the machine word — "not_owned", "no_declared_queue", "already_running"
    refusal: str = ""
    label: str = ""
    #: The fixtures this run took: [{id, name, address, virtuals}].
    fixtures: list[dict] = field(default_factory=list)
    #: What `night_power.owned` did, per fixture.
    power: dict = field(default_factory=dict)
    #: What the declared queue was priced at, and against how much of the
    #: night was left — the planned-end bound, recorded whether it passed
    #: or refused.
    price: dict = field(default_factory=dict)
    #: THE HARD PLANNED END this night was measured against.
    planned_end: float = 0.0
    #: The queue record, as `capture_queue.QueueRun.as_dict()` writes it.
    queue: dict = field(default_factory=dict)
    #: THE HONEST EXIT — every fixture read back at the emitted light.
    exit_report: dict = field(default_factory=dict)
    #: Aborted nights only: who touched what.
    abort: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"run_id": self.id, "state": self.state,
                "trigger": dict(self.trigger), "started": self.started,
                "ended": self.ended, "detail": self.detail,
                "refusal": self.refusal, "label": self.label,
                "fixtures": list(self.fixtures), "power": dict(self.power),
                "price": dict(self.price), "planned_end": self.planned_end,
                "planned_end_label": PLANNED_END_LABEL,
                "queue": dict(self.queue), "exit": dict(self.exit_report),
                "abort": dict(self.abort)}


def load_nights(path=None) -> list[dict]:
    p = _runs_path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            return list(json.load(fh).get("nights") or [])
    except Exception:                                   # noqa: BLE001
        logger.exception("night run: unreadable store %s", p)
        return []


def save_night(run: NightRun, path=None) -> dict:
    """Write this night's record, replacing its own entry in place.

    Written at EVERY transition (declined, started, each queue item via the
    queue's own persist, aborted, finished) rather than at the end, for
    `capture_queue.save_queue`'s own reason: nobody is watching, so a night
    killed by a reboot has still explained everything it did."""
    p = _runs_path(path)
    body = run.as_dict()
    kept = [n for n in load_nights(p) if n.get("run_id") != run.id]
    kept = (kept + [body])[-MAX_STORED_NIGHTS:]
    _atomic_write(p, {"nights": kept})
    return body


# ── the one live night ─────────────────────────────────────────────────────

current: Optional[NightRun] = None
_task: Optional[asyncio.Task] = None


def running() -> bool:
    return current is not None and current.state == STATE_RUNNING


#: A tiny mtime-keyed cache for the DISK path of `last_night`, and only for
#: it. `engine.status()` is polled every few seconds by his own page AND by
#: River's HA sensors, and this store holds up to `MAX_STORED_NIGHTS`
#: records each carrying an exit report per fixture — re-parsing all of that
#: on every poll is real work for an answer that only changes when a night
#: transitions. The live in-memory record always wins over this, so the
#: cache can never serve a stale answer for a night this process is running.
_disk_cache: dict = {"key": None, "night": None}


def last_night() -> Optional[dict]:
    """The current night, or the most recent one on disk. The export reads
    this: "the CURRENT/most-recent run" is one question, not two."""
    if current is not None:
        return current.as_dict()
    p = _runs_path()
    try:
        stat = os.stat(p)
        key = (str(p), stat.st_mtime_ns, stat.st_size)
    except OSError:
        _disk_cache["key"], _disk_cache["night"] = None, None
        return None
    if _disk_cache["key"] != key:
        nights = load_nights(p)
        _disk_cache["key"] = key
        _disk_cache["night"] = nights[-1] if nights else None
    return _disk_cache["night"]


# ── resolving what a night will touch ──────────────────────────────────────

def _owner() -> str:
    from fx import light_ownership
    return light_ownership.load().owner


def spectra_owns() -> bool:
    from fx import light_ownership
    return _owner() == light_ownership.SPECTRA


def _entry_row(entry: dict) -> dict:
    """One fixture, in the shape Home Assistant maps to an entity: a stable
    id, the name the fixture answers to, and the address it lives at."""
    cfg = (entry or {}).get("config") or {}
    return {"id": entry.get("id"),
            "name": cfg.get("name") or entry.get("name") or entry.get("id"),
            "address": cfg.get("ip_address") or cfg.get("destination") or "",
            "type": entry.get("type"),
            "virtuals": list(entry.get("virtuals") or [])}


async def _device_listing() -> list[dict]:
    from spectra.services import device_console
    listing = await device_console.list_devices()
    return list(listing.get("devices") or [])


def run_fixture_rows(items, device_entries: list[dict]) -> list[dict]:
    """Exactly the fixtures the declared queue will drive.

    Resolved item -> room -> the room's CARRIERS -> the devices those
    carriers' segments name, through `carriers.devices_by_carrier` — the one
    definition of that mapping in this app, reversed out of the device
    listing's own `virtuals` field, so this can never disagree with what the
    /devices page shows.

    A carrier is used rather than a virtual because a carrier is the thing
    his rooms are keyed by and four of his seven fan out to several fixtures
    at once (spectra/services/carriers.py). A run that SUBSTITUTES a direct
    virtual for a copy-mapped carrier still lights the same physical
    fixtures, so the list is unchanged by that substitution."""
    from spectra.services import carriers, light_field
    by_carrier = carriers.devices_by_carrier(device_entries)
    seen: dict[str, dict] = {}
    for item in items or []:
        room = light_field.get_room(getattr(item, "room_id", "") or "")
        if room is None:
            continue
        for carrier_id in room.carrier_ids:
            for entry in by_carrier.get(carrier_id) or []:
                did = str(entry.get("id") or "")
                if did and did not in seen:
                    seen[did] = _entry_row(entry)
    return [seen[k] for k in sorted(seen)]


def shielded_devices(device_entries: list[dict]) -> dict[str, list[str]]:
    """device id -> the shielded virtual(s) that exempt it from Dark mode,
    computed from the LIVE shield configuration every single time.

    NEVER A HARDCODED LIST. His Dark-mode shield
    (`dark_light_shield_categories`, default "Singles") is a setting he is
    still deciding about, and the whole value of exporting this is that his
    decision reaches River's morning backstop automatically rather than by
    somebody remembering to edit two repositories. It resolves through
    `dark_light._shielded_set`, which is the same function the reconcile
    itself uses — so the export cannot describe a shield the room is not
    actually keeping."""
    from spectra.services import dark_light, room_controls
    rc = room_controls.load_room_controls()
    shielded = dark_light._shielded_set(rc.dark_light_shield_categories,
                                        rc.dark_light_shield_virtuals)
    out: dict[str, list[str]] = {}
    for entry in device_entries or []:
        hit = sorted(set(entry.get("virtuals") or []) & shielded)
        if hit:
            out[str(entry.get("id") or "")] = hit
    return out


async def fixtures_export() -> dict:
    """THE MORNING BACKSTOP'S SCOPE, in one read, and it is deliberately two
    lists rather than one.

    `fixtures` is what the current/most-recent night actually took. That
    alone was not enough on 2026-09-01: he woke to lit fixtures that no run
    had ever touched, because Dark mode never clamps the shielded ones and
    nobody had told either captain that. `standing_lit_under_dark` is that
    hole, named, computed live. Turning off exactly these two lists is a
    complete morning scope; turning off only the first is the gap he already
    fell into."""
    entries = await _device_listing()
    night = last_night() or {}
    shielded = shielded_devices(entries)
    by_id = {str(e.get("id") or ""): e for e in entries}
    return {
        "run_id": night.get("run_id"),
        "state": night.get("state"),
        "started": night.get("started"),
        "ended": night.get("ended"),
        "fixtures": list(night.get("fixtures") or []),
        "standing_lit_under_dark": [
            {**_entry_row(by_id[did]), "shielded_via": vids}
            for did, vids in sorted(shielded.items()) if did in by_id],
        "exit": dict(night.get("exit") or {}),
    }


#: The states in which a night is over. `active` is derived from this ONE
#: set so nothing downstream has to enumerate them a second time.
ENDED_STATES = (STATE_COMPLETE, STATE_ABORTED, STATE_ENDED_BY_MORNING,
                STATE_DECLINED, STATE_FAILED)


def status_brief() -> dict:
    """What `GET /api/engine/status` carries.

    THIS IS A TRIGGER, NOT A DASHBOARD FIELD (River's binding note): the
    house restores its own "Dark Music" envelope off the run's state here,
    so an ended or aborted state has to land PROMPTLY and UNAMBIGUOUSLY.

    PROMPTLY: it reads the live in-memory record, which `abort()` stamps
    synchronously BEFORE its own network work (the fixture read-backs) and
    which `_finish` stamps as soon as the room is handed back, ahead of
    building the exit report. So the state flips when the room is his again,
    not when the paperwork is done.

    UNAMBIGUOUSLY: `active` is one boolean derived from `ENDED_STATES`, so
    nothing on the house side has to enumerate our state words or guess what
    a new one means; `ended_by_morning` separates the ordinary ending from an
    interruption without changing what `active` says."""
    night = last_night()
    if not night:
        return {"state": "idle", "active": False, "run_id": None,
                "started": None, "ended": None, "ended_by_morning": False,
                "declared": declared(),
                "planned_end": planned_end_at(),
                "planned_end_label": PLANNED_END_LABEL}
    state = night.get("state")
    return {"state": state, "active": state == STATE_RUNNING,
            "run_id": night.get("run_id"),
            "started": night.get("started"), "ended": night.get("ended"),
            "ended_by_morning": state == STATE_ENDED_BY_MORNING,
            "detail": night.get("detail") or "",
            "declared": declared(),
            "planned_end": night.get("planned_end") or planned_end_at(),
            "planned_end_label": PLANNED_END_LABEL}


# ── the hard planned end, and pricing a queue against it ───────────────────

def planned_end_at(now: Optional[float] = None) -> float:
    """The next `PLANNED_END_HOUR:PLANNED_END_MINUTE` in HOUSE time, as an
    epoch timestamp.

    "Next" is the whole subtlety: a night starts before midnight and runs
    past it, so the bound is tomorrow's 05:30 when the event arrives in the
    evening and TODAY's when it arrives at 02:00. Computed in the house's own
    zone so a DST boundary lands where his morning actually does rather than
    an hour out — `zoneinfo` handles the arithmetic; this must never be a
    fixed number of seconds added to a timestamp."""
    tz = ZoneInfo(HOUSE_TZ)
    local = datetime.fromtimestamp(now if now is not None else time.time(), tz)
    end = local.replace(hour=PLANNED_END_HOUR, minute=PLANNED_END_MINUTE,
                        second=0, microsecond=0)
    if end <= local:
        end = (local + timedelta(days=1)).replace(
            hour=PLANNED_END_HOUR, minute=PLANNED_END_MINUTE,
            second=0, microsecond=0)
    return end.timestamp()


def seconds_until_planned_end(now: Optional[float] = None) -> float:
    now = now if now is not None else time.time()
    return max(0.0, planned_end_at(now) - now)


async def price_items(items, *, now: Optional[float] = None) -> dict:
    """What the declared queue costs, in seconds, priced ONCE before
    anything is held.

    PRICED ONCE, AT THE TOP, deliberately: a map item's estimate comes from
    its room's own PLAN, and a plan resolved mid-run would be reading a room
    whose virtuals are currently showing the capture lamp rather than his
    show. So every item is priced before the first hold opens, and the
    per-item bound check (`fits_guard`) then spends those stored numbers
    rather than asking again.

    A MAP item is priced by the production estimator
    (`room_mapping.run_estimate_s`) against its room's real emitter count at
    this run's own settle/capture values — the same function the plan line
    he reads before pressing uses, not a second arithmetic.

    A COMMISSION item is priced at a NAMED NOMINAL
    (`commissioning.NOMINAL_PASS_S` per target per repeat) because its real
    cost depends on a pattern count this side cannot resolve without the
    stored composition. THE NOMINAL IS USED FOR THE PLANNED-END BOUND ONLY
    and never for the hold ceiling, which each run still computes for itself
    from its real plan. Said out loud rather than presented as precision it
    does not have.

    An item that CANNOT be priced (a room that no longer exists, a live read
    that fails) is priced at 0 with its reason recorded — never at a guessed
    number, and never fatally: `capture_runs` will refuse it on its own terms
    a moment later, with a better sentence than anything invented here."""
    from spectra.services import commissioning, light_field, room_mapping

    rows: list[dict] = []
    total = 0.0
    deps = None
    scope: list[str] = []
    for item in items or []:
        row = {"name": item.name, "kind": item.kind, "room_id": item.room_id,
               "seconds": 0.0, "basis": "", "note": ""}
        try:
            if item.kind == capture_runs.KIND_COMMISSION:
                targets = max(1, len(item.targets or []) or 1)
                row["seconds"] = round(
                    commissioning.NOMINAL_PASS_S * targets
                    * max(1, int(item.repeat or 1)), 1)
                row["basis"] = "nominal"
                row["note"] = ("a commissioning pass is priced at a nominal "
                               "for the planned-end bound only, never for "
                               "the hold ceiling")
            else:
                room = light_field.get_room(item.room_id)
                if room is None:
                    row["note"] = "no such room — priced at nothing"
                else:
                    if deps is None:
                        deps = room_mapping.production_deps(None)
                        scope = await room_mapping.live_virtual_ids(
                            deps.get_virtuals)
                    g, block = capture_runs.run_granularity(
                        room, item.granularity, item.block_pixels)
                    plan = await room_mapping.resolve_plan(room, deps, scope,
                                                           g, block)
                    row["seconds"] = room_mapping.run_estimate_s(
                        len(plan.emitters),
                        room_mapping.clamp_settle(item.dark_settle_s,
                                                  room_mapping.DARK_SETTLE_S),
                        room_mapping.clamp_capture(item.dark_capture_s,
                                                   room_mapping.DARK_CAPTURE_S),
                        room_mapping.clamp_settle(item.lit_settle_s,
                                                  room_mapping.LIT_SETTLE_S),
                        room_mapping.clamp_capture(item.lit_capture_s,
                                                   room_mapping.LIT_CAPTURE_S))
                    row["basis"] = f"{len(plan.emitters)} emitters"
        except Exception as exc:                        # noqa: BLE001
            logger.info("night run: could not price %s: %s", item.name, exc)
            row["note"] = (f"could not be priced ({type(exc).__name__}) — "
                           f"priced at nothing; the run itself will refuse "
                           f"it on its own terms if it cannot go ahead")
        total += row["seconds"]
        rows.append(row)
    now = now if now is not None else time.time()
    return {"items": rows, "total_seconds": round(total, 1),
            "window_seconds": round(seconds_until_planned_end(now), 1),
            "planned_end": planned_end_at(now),
            "planned_end_label": PLANNED_END_LABEL}


def fits_guard(price: dict, *, clock=time.time):
    """The per-item veto `capture_queue.run_queue` asks before each item.

    THE BOUND IS CHECKED PER ITEM, not once at the top, because "never
    schedule capture work past his morning" is about when each item STARTS.
    A queue that fitted at 01:00 has not necessarily got room for item six at
    05:28, and an item started then would run into the blinds opening."""
    by_name = {row["name"]: float(row.get("seconds") or 0.0)
               for row in price.get("items") or []}

    def guard(item) -> Optional[str]:
        now = clock()
        remaining = seconds_until_planned_end(now)
        need = by_name.get(item.name, 0.0)
        if need <= 0.0:
            # Unpriced: the bound cannot judge it, so it does not veto it.
            # `capture_runs` still applies every real gate, and the abort at
            # his morning still ends it with its partials kept.
            return None
        if need <= remaining:
            return None
        return mapping_refusals.night_item_will_not_fit(
            item.name, need, remaining, PLANNED_END_LABEL, 1)

    return guard


# ── starting ───────────────────────────────────────────────────────────────

def _decline(trigger: dict, refusal: str, detail: str,
             price: Optional[dict] = None) -> NightRun:
    run = NightRun(id=uuid.uuid4().hex[:12], state=STATE_DECLINED,
                   trigger=dict(trigger), started=time.time(),
                   ended=time.time(), detail=detail, refusal=refusal,
                   price=dict(price or {}), planned_end=planned_end_at())
    save_night(run)
    logger.warning("night run: DECLINED (%s) — %s", refusal, detail)
    return run


async def start(trigger: dict) -> NightRun:
    """A sleep-window start event. Returns the night's record either way —
    a decline is a record, not an exception, because that is what makes the
    boundary safe to leave armed."""
    global current, _task

    owner = _owner()
    if not spectra_owns():
        # THE BOUNDARY. Read first, before anything else is resolved or
        # touched, so a declined night cannot have had a side effect.
        return _decline(trigger, "not_owned",
                        mapping_refusals.night_not_owned(owner))
    if running():
        return _decline(trigger, "already_running",
                        mapping_refusals.night_already_running(
                            current.id if current else "?"))
    if capture_queue.running():
        # Not this seam's queue — somebody started one from the page or the
        # command line. It holds the same room and the same camera, so a
        # night started over the top of it would be two runs fighting; and
        # stopping HIS queue to run ours would be helping ourselves to more
        # than the room.
        return _decline(trigger, "already_running",
                        "The night run declined: a capture queue is already "
                        "running (started outside this seam), so it was left "
                        "alone. Nothing about the room was touched.")
    declaration = load_declaration()
    if declaration is None:
        return _decline(trigger, "no_declared_queue",
                        mapping_refusals.NO_DECLARED_NIGHT_QUEUE)
    try:
        items = capture_queue.parse_items(declaration["items"])
    except ValueError as exc:
        # A declaration that parsed when he wrote it and does not now (a
        # hand-edited file, a renamed field) is still a decline with a
        # sentence, never a 3am traceback.
        return _decline(trigger, "no_declared_queue",
                        f"{mapping_refusals.NO_DECLARED_NIGHT_QUEUE} "
                        f"(the stored declaration no longer parses: {exc})")

    # PRICED BEFORE ANYTHING IS HELD, against the hard planned end. A queue
    # that cannot finish before his morning routine (and the blinds opening
    # just after it) does not start: daylight in the frame is a contaminant,
    # so this is a bound, not a preference.
    price = await price_items(items)
    if price["total_seconds"] > price["window_seconds"]:
        return _decline(trigger, "will_not_fit",
                        mapping_refusals.night_will_not_fit(
                            price["total_seconds"], price["window_seconds"],
                            PLANNED_END_LABEL),
                        price=price)

    entries = await _device_listing()
    run = NightRun(id=uuid.uuid4().hex[:12], state=STATE_RUNNING,
                   trigger=dict(trigger), started=time.time(),
                   label=str(declaration.get("label") or ""),
                   fixtures=run_fixture_rows(items, entries),
                   price=price, planned_end=price["planned_end"])
    current = run
    save_night(run)
    logger.warning("night run %s: starting %d declared item(s) over %d "
                   "fixture(s), priced at %.0fs of a %.0fs window to %s",
                   run.id, len(items), len(run.fixtures),
                   price["total_seconds"], price["window_seconds"],
                   PLANNED_END_LABEL)
    _task = asyncio.create_task(_work(run, items), name="spectra-night-run")
    return run


async def _live_devices() -> list:
    """The LIVE driver objects — the only thing that can be asked a firmware
    state, exactly as `room_mapping.production_deps.fixture_devices` reads
    them."""
    from spectra.services.live_host import live
    host = getattr(live, "host", None)
    if host is None:
        return []
    return list(host.devices.values())


async def _work(run: NightRun, items) -> None:
    """The night itself. Never raises past here: an unattended caller gets a
    record, and the record says what happened."""
    global current
    run_ids = {str(f.get("id")) for f in run.fixtures}
    # Held outside the try so the record carries what `owned()` did on EVERY
    # path — including the failing one, where the restores that land in its
    # own `finally` are exactly what a reader needs to know about.
    held: list = []
    try:
        devices = await _live_devices()
        mine = [d for d in devices
                if str(getattr(d, "id", "") or "") in run_ids]
        from spectra.services import night_power
        async with night_power.owned(mine) as power:
            held.append(power)
            run.power = power.as_dict()
            save_night(run)
            queue_run = capture_queue.new_run(list(items), label=run.label)
            await capture_queue.run_queue(
                list(items), label=run.label, run=queue_run,
                save=_queue_persist(run),
                # NEVER SCHEDULE PAST HIS MORNING. Checked before EVERY
                # item, not once at the top: a queue that fitted at 01:00
                # has not necessarily got room for item six at 05:28.
                guard=fits_guard(run.price))
            run.queue = queue_run.as_dict()
    except Exception as exc:                            # noqa: BLE001
        logger.exception("night run %s: failed", run.id)
        run.state = STATE_FAILED
        run.detail = (f"The night run stopped on an unexpected error "
                      f"({type(exc).__name__}: {exc}). Anything measured "
                      f"before that is kept in its own store.")
    finally:
        # Read AFTER the context has exited, on every path: the restores
        # only land in `owned()`'s own finally, and a record that stopped at
        # the pre-restore snapshot would understate what happened to his
        # fixtures on exactly the night it mattered most.
        if held:
            run.power = held[0].as_dict()
        await _finish(run)


def _queue_persist(run: NightRun):
    """The queue writes its own record after every item; this piggybacks the
    night's record onto the same moment, so both files agree at every
    boundary rather than the night's being a stale copy until the end."""
    def persist(queue_run) -> dict:
        body = capture_queue.save_queue(queue_run)
        run.queue = queue_run.as_dict()
        save_night(run)
        return body
    return persist


async def _finish(run: NightRun) -> None:
    """Close the night out: hand the room back, read every fixture BACK AT
    THE LIGHT, and write the record. Runs on the normal path and the abort
    path alike — an exit report only produced when things went well would be
    exactly the report nobody needs."""
    from spectra.services import flare_preview_hold
    try:
        await flare_preview_hold.close_hold()
    except Exception:                                   # noqa: BLE001
        logger.exception("night run %s: the final hold close failed", run.id)
    if run.state == STATE_RUNNING:
        run.state = STATE_COMPLETE
        run.detail = run.detail or "The night's declared queue finished."
    run.ended = run.ended or time.time()
    try:
        report = (await build_exit(run)).as_dict()
        report["witness"] = witness_summary(run)
        run.exit_report = report
    except Exception:                                   # noqa: BLE001
        logger.exception("night run %s: the exit report failed", run.id)
        run.exit_report = {
            "verified_at_the_light": False,
            "summary": ("The fixtures could not be read back at the end of "
                        "this run, so nothing here says whether the room is "
                        "dark. Check it.")}
    save_night(run)
    logger.warning("night run %s: %s — %s", run.id, run.state,
                   (run.exit_report or {}).get("summary", ""))


def witness_summary(run: NightRun) -> dict:
    """WHAT THE CONTAMINATION WITNESS SAID ABOUT THIS NIGHT, on the exit
    report, because River's instruction is explicit: an unavailable witness
    is NAMED there rather than left as a silence.

    `unclaimed` is the number that matters and it is deliberately not folded
    into `clean`: a capture nobody could check is KEPT and makes NO CLEAN
    CLAIM. "We could not check" and "we checked and it was fine" are
    different facts and only one of them is evidence — the same distinction
    this report already draws between a fixture that reads DARK and one that
    could not be read at all."""
    from spectra.services import witness as witness_mod
    totals = {"clean": 0, "contaminated": 0, "unclaimed": 0}
    for item in (run.queue or {}).get("items") or []:
        counts = ((item.get("run") or {}).get("witness")) or {}
        for key in totals:
            totals[key] += int(counts.get(key) or 0)
    configured = witness_mod.configured()
    if not configured:
        line = ("No contamination witness is configured on this host, so "
                "nothing checked whether the house changed light during "
                "these captures. Every capture is kept and none of them "
                "claims to be clean.")
    elif totals["contaminated"]:
        line = (f"{totals['contaminated']} capture(s) were taken while the "
                f"house changed light and were re-taken; {totals['clean']} "
                f"came back clean" +
                (f"; {totals['unclaimed']} could not be checked and make no "
                 f"clean claim." if totals["unclaimed"] else "."))
    elif totals["unclaimed"]:
        line = (f"{totals['unclaimed']} capture(s) could not be checked "
                f"against the house's own record — they are KEPT and stamped "
                f"and make no clean claim; {totals['clean']} came back "
                f"clean.")
    else:
        line = (f"All {totals['clean']} capture(s) were checked against the "
                f"house's own record and nothing outside this run's fixtures "
                f"changed light while they were taken.")
    return {"configured": configured, "summary": line, **totals}


async def build_exit(run: NightRun):
    """THE HONEST EXIT for this night — `night_exit.build` wired to the live
    room. Kept as its own function so a test can drive it against a headless
    pipeline without starting a night."""
    from spectra.services import night_exit
    from spectra.services.live_host import live
    entries = await _device_listing()
    devices = {str(getattr(d, "id", "") or ""): d
               for d in await _live_devices()}
    return await night_exit.build(
        device_entries=entries, devices_by_id=devices,
        run_device_ids={str(f.get("id")) for f in run.fixtures},
        shielded_devices=shielded_devices(entries),
        host=getattr(live, "host", None))


# ── aborting ───────────────────────────────────────────────────────────────

async def abort(trigger: dict, *, grace_s: float = ABORT_GRACE_S,
                sleep=asyncio.sleep, clock=time.monotonic) -> dict:
    """THE ONE STOP ENDPOINT — three different facts arriving through it.

    A TOUCHED HOUSE IS HIS HOUSE: `Sleeping` went off, or he reached for a
    light. Home Assistant forwards both here, and they are the same act.

    HIS MORNING ROUTINE (`event: "morning-routine"`, ~05:50 daily) arrives
    here too, does exactly the same three things to the room, and is
    RECORDED AS A DIFFERENT OUTCOME: `ended_by_morning`, an ordinary ending.
    It is what stopped SPECTRA at 05:50 on 2026-09-01 with nobody pressing
    anything, and a night that ran until his morning ran exactly as long as
    it was ever going to. Folding it into `aborted` would make every
    ordinary night read as an incident, which is how a record stops being
    read.

    THIS SIDE HAS NO PLANNED-END CONCEPT OF ITS OWN, stated rather than
    invented: the queue walks a declared list and each run is bounded by the
    hold's own ceiling; nothing here schedules against a clock, so there is
    no dawn line to teach about his morning. His morning routine IS the hard
    end bound, and it arrives as this event.

    THE ORDER IS THE SEMANTICS, and each step is existing machinery:

      1. `session.run_abort` — the run in flight stops at its next capture
         boundary and reports `partial` WITH ITS FOOTPRINTS KEPT
         (`room_mapping` checks this before every emitter). Set first,
         because a run that stops itself reverts the room tidily.
      2. `capture_queue.stop()` — nothing further starts.
      3. a SHORT bounded grace for (1) to land, then
      4. `close_hold()` REGARDLESS. The promise is his dark room back within
         seconds, not a tidy run; the hold's revert is idempotent, so doing
         it here when the run already did costs nothing.

    Then his power state goes back (the `night_power.owned` context exits on
    the run task's own way out) and the exit report is read at the light.

    Returns immediately-useful facts rather than the whole record: an
    unattended caller fired this and is not going to read a 40kB body."""
    from spectra.services import capture_runs as runs_mod
    from spectra.services import flare_preview_hold, mapping_session

    source = str(trigger.get("event") or trigger.get("source") or "")
    by_morning = source == mapping_refusals.MORNING_ROUTINE
    detail = (mapping_refusals.night_ended_by_morning() if by_morning
              else mapping_refusals.night_aborted(source))
    end_state = STATE_ENDED_BY_MORNING if by_morning else STATE_ABORTED
    was_running = running()

    sess = mapping_session.current
    told_run = False
    if sess is not None and not sess.closed and sess.run_abort is None:
        sess.run_abort = detail
        told_run = True
    stopped_queue = capture_queue.stop()

    # Give the run in flight its chance to land its own revert, bounded.
    deadline = clock() + max(0.0, grace_s)
    while runs_mod.running() is not None and clock() < deadline:
        await sleep(ABORT_POLL_S)
    landed = runs_mod.running() is None

    reverted = await flare_preview_hold.close_hold()

    run = current
    if run is not None and run.state == STATE_RUNNING:
        run.state = end_state
        run.detail = detail
        run.ended = time.time()
        run.abort = {"trigger": dict(trigger), "told_run": told_run,
                     "stopped_queue": stopped_queue,
                     "run_landed_itself": landed,
                     "hold_reverted_here": bool(reverted.get("reverted"))}
        save_night(run)

    return {"aborted": was_running, "state": end_state,
            "ended_by_morning": by_morning, "detail": detail,
            "run_id": run.id if run is not None else None,
            "told_run": told_run, "stopped_queue": stopped_queue,
            "run_landed_itself": landed,
            "hold_reverted_here": bool(reverted.get("reverted")),
            # The exit report is read at the LIGHT and takes real network
            # reads of every fixture; it lands on the RECORD (and on
            # GET /night-run/fixtures) as the run task finishes closing out,
            # rather than holding this response open past its "within
            # seconds" promise. "pending" is honest; a fabricated empty
            # report would not be.
            "exit": (run.exit_report if run is not None and run.exit_report
                     else "pending")}
