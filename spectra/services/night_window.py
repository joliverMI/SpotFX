"""THE WINDOW — River powers the mains, SPECTRA waits for the fixtures, and
whoever opened it closes it.

────────────────────────────────────────────────────────────────────────────
WHAT THIS EXISTS FOR (2026-09-08)
────────────────────────────────────────────────────────────────────────────

The kitchen sconces run off a MAINS SWITCH that is Home Assistant's and
River's alone to drive (`witness.SCONCE_MAINS_ENTITY`, and THE SCONCE MAINS
RULE — nothing in SPECTRA turns it on and nothing in SPECTRA ever turns it
off). Until tonight, powering it before a night depended on a human relaying
the request; the night of 2026-09-08 stalled for exactly that reason, with
supervision down between 20:29 and 06:05 and nobody to relay.

River removed the dependency by adding two events to the endpoint SPECTRA
already announces takes and releases on:

    window_open   power the sconce mains, hold his away automations
    window_close  restore his bedtime baseline, drop that hold

`spectra/services/pretake_ping.py` sends both — SAME URL, SAME bearer, SAME
body shape, SAME reading of her answer as `pre_take` and `released`. This
module is what a NIGHT does with them: when to open one, what must be true
before the room is taken, and the pairing that guarantees one is never left
open.

────────────────────────────────────────────────────────────────────────────
A 200 IS NOT A LIT SCONCE — THE GATE IS THE MEASUREMENT
────────────────────────────────────────────────────────────────────────────

River answering 200 says SHE ACTED. It does not say the mains came up, that
a controller booted, or that anything on this network can reach it. So the
open is two acts and the night is gated on the SECOND one:

    1. the POST                  fail-soft, reported, NEVER a reason to
                                 refuse a night on its own
    2. the fixtures, read back   `spectra/services/sconce_wait.py` — and
                                 THIS is what stops a night

That split is the whole point. A failed POST with sconces that are already
powered is a night that runs; a cheerful 200 with a sconce that never comes
up is a night that REFUSES, rather than one that measures a dark room for
four hours and calls the result a map. It is `docs/SPECTRA_SPEC.md` §64's
own rule — the bridge 2xx's a write whether or not the bulb took it — one
service further out.

────────────────────────────────────────────────────────────────────────────
UNCONFIGURED IS INERT, AND THAT IS LOAD-BEARING
────────────────────────────────────────────────────────────────────────────

With `SPECTRA_PRETAKE_URL` unset — the state of any host that has never
heard of River — NOTHING happens here: no POST, no probe, no marker file,
no gate. A night is byte-identical to the one before this module existed.

That is not tidiness, it is correctness: nobody asked for the mains to be
powered on such a host, so the fixtures may legitimately be dark, and
refusing the night because they are would turn "no River configured" into
"your sconces are broken" — inventing a fault out of a thing we never did.
Every other unavailability in this seam draws the same line
(`witness.VERDICT_UNAVAILABLE`, `night_exit`'s DARK vs UNKNOWN).

────────────────────────────────────────────────────────────────────────────
THE PAIRING — an open window is never left open
────────────────────────────────────────────────────────────────────────────

An open window HOLDS HIS AWAY AUTOMATIONS. Leaving one open is a house that
quietly stops behaving like his house, with nothing in it visibly wrong. So
the close is not attached to any one happy path:

    the night ends, any way at all   `night_run._finish`, after the room has
                                     been given back — the order is the
                                     semantics, exactly as it is for the
                                     give-back: River restores a baseline
                                     into a room SPECTRA has already let go
                                     of, never one it is still holding
    the sconces never came up        `night_run.start` closes it immediately
                                     and declines — "do not take, do not
                                     leave anything held"
    a CRASH                          `recover_orphaned_window()`, from the
                                     cold start, beside the take's own
                                     recovery

WHICH IS WHY THERE IS A DURABLE MARKER (`config.NIGHT_WINDOW_FILE`, atomic
tmp+replace, `night_take.py`'s own restart-survival shape). Its presence at
a cold start is the one thing that can say a crashed night left River
holding — an in-memory flag could never survive to say it. It is written
ONLY when a `window_open` was actually SENT, so the unconfigured path above
writes nothing at all and `holding()` means exactly "River was asked to open
a window and has not been told to close it".

A CLOSE THAT DOES NOT LAND STILL DROPS THE MARKER, and says so loudly.
`night_take.give_back`'s own rule: a release that cannot be verified is
REPORTED and the snapshot is still dropped, because a marker left behind
would have a cold start days later announce a close for a window nobody
remembers. What protects him from a genuinely lost close is River's own
morning routine, which is the outer net for this seam as it is for every
other part of it.

────────────────────────────────────────────────────────────────────────────
WHAT THIS SIDE STILL CANNOT DO
────────────────────────────────────────────────────────────────────────────

IT DRIVES NO HOME ASSISTANT ENTITY. There is no HA path here, no entity
named, and no second route into his house — the only thing that leaves is
one POST to a River service, and what she does with it is hers. THE SCONCE
MAINS RULE is untouched and untouchable from here, and
`tests/test_window_ping.py` asserts it against this module's own source.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Optional

from spectra import config as scfg
from spectra.services import pretake_ping

logger = logging.getLogger(__name__)

#: Why a window was closed — LABELS for a log line and a record, never a
#: branch. `night_take.WHY_*`'s own discipline.
WHY_FINISHED = "finished"
WHY_ABORTED = "aborted"
WHY_MORNING = "morning-routine"
WHY_SCONCES_DARK = "sconces-did-not-come-up"
WHY_CRASH = "crash-recovery"

#: The machine word a night declines under when its fixtures never answered.
REFUSAL_SCONCES_DARK = "sconces_did_not_come_up"


def _marker_path(path=None):
    return path or scfg.NIGHT_WINDOW_FILE


def _atomic_write(path, body: dict) -> None:
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(path)) or ".",
                               prefix="night-window", suffix=".tmp")
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


def save_marker(*, run_id: str, room_id: str, path=None) -> dict:
    body = {"run_id": run_id, "room_id": room_id, "opened_at": time.time()}
    _atomic_write(_marker_path(path), body)
    return body


def load_marker(path=None) -> Optional[dict]:
    p = _marker_path(path)
    try:
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except Exception:                                   # noqa: BLE001
        logger.exception("night window: unreadable marker %s", p)
        return None
    return body or None


def clear_marker(path=None) -> bool:
    """Drop the marker. Never raises: this runs on every exit path of every
    night, and a night must not fail to close out because a file vanished
    between the check and the unlink."""
    try:
        os.unlink(_marker_path(path))
        return True
    except OSError:
        return False


def holding(path=None) -> bool:
    """Whether River is holding a window open for us RIGHT NOW, according to
    the durable record.

    A STAT, NOT A PARSE — `night_take.holding()`'s own reason: this answers
    the question a cold start and every exit path ask, and the PRESENCE of
    the file is the whole question there. A marker that will not parse is
    still proof a window was opened, and the window outranks the paperwork.
    """
    try:
        return os.stat(_marker_path(path)).st_size > 0
    except OSError:
        return False


async def open_for_run(run_id: str, *, scope: Any = None,
                       room_id: str = pretake_ping.ROOM_ALL,
                       open_window=None) -> pretake_ping.WindowResult:
    """OPEN THE WINDOW FOR THIS NIGHT — ask River for the mains and the
    hold, then wait for the run's own fixtures. Never raises.

    `scope` is the `take_scope.ScopeOutcome` this night resolved (or None,
    the whole room): the SAME object the take is narrowed by, so the
    fixtures waited for are exactly the fixtures brought up. An unscoped
    night waits for every WLED in the config — the widening direction, and
    the same one `take_scope` itself takes when it cannot narrow.

    THE MARKER IS WRITTEN ONLY IF SOMETHING WAS SENT. Unconfigured, this
    returns a result whose `resolved` is None and whose `ok` is True,
    writes no file, and leaves the night exactly as it was."""
    narrowed = getattr(scope, "scope", None)
    device_ids = (sorted(narrowed.device_ids) if narrowed is not None
                  else None)
    open_window = open_window or pretake_ping.open_window
    try:
        result = await open_window(room_id=room_id, device_ids=device_ids)
    except Exception as exc:                            # noqa: BLE001
        # `open_window` does not raise; this is the belt on top of the
        # braces, because a night must never fail to start over the window.
        logger.exception("night window: opening the window raised")
        return pretake_ping.WindowResult(
            event=pretake_ping.EVENT_WINDOW_OPEN, resolved=None,
            detail=f"The window could not be opened ({type(exc).__name__}: "
                   f"{exc}) — the night carries on without it.")
    if result.ping.status != pretake_ping.STATUS_UNCONFIGURED:
        try:
            save_marker(run_id=run_id, room_id=room_id)
        except Exception:                               # noqa: BLE001
            # LOUD, AND STILL NOT FATAL. Without the marker, nothing on the
            # way out will close this window and River holds his away
            # automations until her own morning routine — worth shouting
            # about, and not worth losing the night over. A storage failure
            # here means `save_night` is about to fail too, so the night is
            # already unrecordable rather than newly broken.
            logger.critical(
                "night window: the window is OPEN and its marker could not "
                "be written — nothing will close it automatically; River's "
                "morning routine is the net", exc_info=True)
    if result.ping.status == pretake_ping.STATUS_UNCONFIGURED:
        # NOT "opened" — nothing was. Saying so plainly is what keeps a host
        # with no River from reading, at breakfast, like one whose window
        # opened and whose fixtures were never checked.
        logger.info("night window: no window for night %s — %s", run_id,
                    result.detail)
    elif result.ok:
        logger.warning("night window: opened for night %s — %s", run_id,
                       result.detail)
    else:
        logger.critical("night window: THE FIXTURES DID NOT COME UP for "
                        "night %s — %s", run_id, result.detail)
    return result


async def close_for_run(*, why: str, run_id: str = "",
                        close_window=None) -> dict:
    """CLOSE THE WINDOW IF THIS NIGHT OPENED ONE — River restores his
    bedtime baseline and drops the automation hold. Never raises.

    GATED ON THE MARKER, exactly as `night_take.give_back` is gated on its
    snapshot: this closes what this seam opened, and a night that opened
    nothing (an unconfigured host, or a decline before the window) returns
    `{}` having done nothing at all.

    IDEMPOTENT. `night_run.abort` and the run task's own `_finish` both
    reach it, in an order nothing guarantees; the second finds no marker and
    is a no-op that says so.

    CALL IT AFTER THE ROOM HAS GONE BACK. She restores a baseline into a
    room SPECTRA has already let go of — announcing it while the stack is
    still painting his fixtures is the pre-take's own ordering mistake
    pointed the other way."""
    if not holding():
        return {}
    marker = load_marker() or {}
    room_id = str(marker.get("room_id") or pretake_ping.ROOM_ALL)
    close_window = close_window or pretake_ping.close_window
    try:
        result = await close_window(room_id=room_id)
        record = result.as_dict()
    except Exception as exc:                            # noqa: BLE001
        logger.exception("night window: closing the window raised")
        record = {"event": pretake_ping.EVENT_WINDOW_CLOSE,
                  "ping": {"status": pretake_ping.STATUS_FAILED,
                           "detail": f"{type(exc).__name__}: {exc}"},
                  "resolved": None, "ok": True, "fixtures": {},
                  "detail": f"The window close raised ({type(exc).__name__}: "
                            f"{exc})."}
    # DROPPED REGARDLESS — see the module docstring. A marker left behind
    # would have a cold start days later announce a close for a window
    # nobody remembers.
    clear_marker()
    record["why"] = why
    record["run_id"] = run_id or str(marker.get("run_id") or "")
    record["opened_at"] = marker.get("opened_at", 0.0)
    sent = (record.get("ping") or {}).get("status") == pretake_ping.STATUS_SENT
    (logger.warning if sent else logger.critical)(
        "night window: closed (%s) — %s", why, record.get("detail", ""))
    return record


async def recover_orphaned_window(*, close_window=None) -> dict:
    """A WINDOW LEFT OPEN BY A CRASH — closed at the cold start, beside the
    take's own recovery.

    The marker on disk is the proof: this process cannot be the one that
    wrote it. Without this, a crash mid-night leaves River holding his away
    automations indefinitely, with nothing visibly wrong for anyone to
    notice — the same class of loose end `night_take.recover_orphaned_take`
    exists for, on the other half of the same act.

    A no-op with nothing on disk, which is every ordinary start."""
    if not holding():
        return {}
    marker = load_marker() or {}
    held_for = max(0.0, time.time() - float(marker.get("opened_at") or 0.0))
    logger.critical("night window: ORPHANED OPEN WINDOW found at startup "
                    "(night %s, open %.0fs) — closing it",
                    marker.get("run_id") or "?", held_for)
    record = await close_for_run(why=WHY_CRASH,
                                 run_id=str(marker.get("run_id") or ""),
                                 close_window=close_window)
    record["recovered"] = True
    record["held_for_s"] = round(held_for, 1)
    return record
