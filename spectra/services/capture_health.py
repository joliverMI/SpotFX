"""THE CAMERA HOST'S OWN HEALTH — so a dead capture machine is a READ from
SPECTRA's side, not a silence.

THE STANDING STANDARD THIS SERVES. `night_exit` draws DARK from UNKNOWN;
`witness` draws contaminated from witness_unavailable; `lever_selftest`
draws "we checked and it is broken" from "we could not check". All three
exist because a system that cannot say what it does not know will one day
say something it does not know. The camera host had the last remaining
version of that gap: `session_view()` reported `present: False` and the run
refused with `NO_SESSION`, and that is the SAME answer whether a client has
never existed, is being restarted this second, or has been off since
Tuesday. A person reading it has to go and look at a machine to find out
which.

So this module keeps the small durable record that makes absence answerable:
per capture machine, the last time it was here, the build it was running,
its declared placement, the camera it opened, whether its exposure locked,
and the LEVER SELF-TEST VERDICT it earned. When it is gone, the record is
what `health()` reports, with the machine named and the gap measured.

WHAT IT IS NOT. It gates nothing, and it never refuses anything: a
run's refusal is still `mapping_session.lock_refusal`'s and `NO_SESSION`,
unchanged, and nothing here is consulted before a light is driven. It is a
reporting surface, and a reporting surface that could refuse a run would be
a second implementation of the exposure gate wearing a different name.

IT IS ALSO NOT A HEARTBEAT. Nothing here polls, and nothing here decides a
client is dead: `present` is read from the live session at the moment
somebody asks, and everything else is the last thing that was WRITTEN when
something actually happened — a hello, a verdict, a close. So there is no
clock to be wrong, no task to supervise, and no window in which a machine
that is plainly connected reads as absent because a tick has not fired.

WHY THREE WRITE POINTS AND ONE FUNCTION. `note_session()` snapshots
whatever the session currently says and is called from `hello`, from the
lever self-test's own verdict cache, and from the session close. Three
callers, one snapshot: a record assembled from three partial writers would
eventually hold a version from one connection and a verdict from another,
which is precisely the kind of quietly-wrong row this module exists to
prevent.

WHAT COUNTS AS ONE MACHINE. The `host` a client declares in `hello`
(`--host`, defaulting to the machine's node name). It is the client's own
word for itself, exactly as `lock_refusal` already uses it to name the
machine it is talking to. A browser session declares no host and is
recorded under its user agent — a phone is a camera host too, and the point
of the record is to say WHICH one is missing.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Optional

from spectra import config as scfg
from spectra.services import capture_source, mapping_refusals

logger = logging.getLogger(__name__)

#: How many distinct camera machines are remembered. Small on purpose: this
#: answers "where is my camera host", not "every device that ever touched
#: SPECTRA", and an unbounded list of one-off browser sessions would bury
#: the one row a person is looking for. Oldest last-seen is evicted first.
MAX_CLIENTS = 12

#: The word a browser session is filed under when it declares no host.
UNNAMED = "an unnamed machine"


def _path(path=None):
    return path or scfg.CAPTURE_HEALTH_FILE


def load(path=None) -> list[dict]:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            return list(json.load(fh).get("clients") or [])
    except Exception:                                  # noqa: BLE001
        logger.exception("capture health: unreadable store %s", p)
        return []


def _save(rows: list[dict], path=None) -> None:
    p = _path(path)
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="capture-health", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"clients": rows}, fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── reading one session ────────────────────────────────────────────────────

def describe(session: Any) -> dict:
    """What a live session says about the machine holding it — duck-typed on
    purpose, so this module imports nothing from `mapping_session` and every
    test double is a valid argument."""
    hello = dict(getattr(session, "hello", None) or {})
    lock = getattr(session, "lock", None)
    verdict = getattr(session, "lever_verdict", None)
    row = {
        "host": str(hello.get("host") or "").strip() or _fallback_host(hello),
        "client": str(hello.get("client") or "") or "browser",
        "version": str(hello.get("client_version") or ""),
        "pose_name": str(hello.get("pose_name") or ""),
        "user_agent": str(hello.get("user_agent") or ""),
        "platform": dict(hello.get("platform") or {}),
        "camera": (dict(hello["camera"])
                   if isinstance(hello.get("camera"), dict) else {}),
        "session_id": str(getattr(session, "id", "") or ""),
        "pose_id": str(getattr(session, "pose_id", "") or ""),
        "locked": bool(getattr(lock, "locked", False)),
        # THE CAMERA'S OWN SENTENCE, when there is one. A client with no
        # camera still connects and says so, and that is the single most
        # useful thing this record can carry into the morning.
        "camera_error": str(getattr(lock, "camera_error", "") or ""),
        "lever": (verdict.as_dict() if hasattr(verdict, "as_dict") else {}),
    }
    return row


def _fallback_host(hello: dict) -> str:
    ua = str(hello.get("user_agent") or "").strip()
    return ua[:80] if ua else UNNAMED


# ── writing ────────────────────────────────────────────────────────────────

def note_session(session: Any, *, event: str = "seen", path=None,
                 now_ms: Optional[float] = None) -> dict:
    """Record what this session says, right now. Returns the stored row.

    `event` is recorded verbatim ("hello", "lever", "closed") so a reader
    can tell a client that connected and vanished from one that ran a
    self-test — it is never branched on here."""
    stamp = float(time.time() * 1000.0 if now_ms is None else now_ms)
    row = describe(session)
    rows = load(path)
    kept = [r for r in rows if r.get("host") != row["host"]]
    previous = next((r for r in rows if r.get("host") == row["host"]), {})
    row["first_seen_ms"] = previous.get("first_seen_ms") or stamp
    row["last_seen_ms"] = stamp
    row["last_event"] = event
    row["sessions"] = int(previous.get("sessions") or 0) + (
        1 if event == "hello" else 0)
    # A VERDICT SURVIVES A HELLO THAT DOES NOT CARRY ONE. A fresh session
    # has earned nothing yet (the cache is the session object, deliberately),
    # but "the last thing this camera proved about its own lever" is exactly
    # what a morning reader wants — kept with its own stamp so it is never
    # mistaken for this connection's.
    if not row["lever"] and previous.get("lever"):
        row["lever"] = dict(previous["lever"])
        row["lever_seen_ms"] = previous.get("lever_seen_ms")
    elif row["lever"]:
        row["lever_seen_ms"] = stamp
    kept.append(row)
    kept.sort(key=lambda r: r.get("last_seen_ms") or 0.0, reverse=True)
    try:
        _save(kept[:MAX_CLIENTS], path)
    except Exception:                                  # noqa: BLE001
        # A HEALTH RECORD THAT CANNOT BE WRITTEN MUST NOT TAKE A RUN DOWN.
        # This is reporting; the run's own gates are elsewhere and unchanged.
        logger.exception("capture health: could not write %s", _path(path))
    return row


# ── reading ────────────────────────────────────────────────────────────────

def health(session: Any = None, *, path=None,
           now_ms: Optional[float] = None) -> dict:
    """PRESENCE, ABSENCE OR NEVER — one shape for all three, so a reader
    never has to tell "not connected" from "we did not look".

    `session` is the live session or None; everything else comes from the
    record. `sentence` is `mapping_refusals`' own — this composes none."""
    stamp = float(time.time() * 1000.0 if now_ms is None else now_ms)
    rows = load(path)
    if session is not None:
        row = describe(session)
        stored = next((r for r in rows if r.get("host") == row["host"]), {})
        row["first_seen_ms"] = stored.get("first_seen_ms")
        row["last_seen_ms"] = stamp
        if not row["lever"] and stored.get("lever"):
            row["lever"] = dict(stored["lever"])
            row["lever_seen_ms"] = stored.get("lever_seen_ms")
        return {"present": True, "state": "present", "client": row,
                "absent_for_s": 0.0,
                "sentence": mapping_refusals.client_present(
                    row["host"], pose_name=row["pose_name"],
                    version=row["version"],
                    # `describe` already files a browser session under
                    # "browser"; the sentence says so rather than calling a
                    # phone the capture client.
                    browser=row["client"] != capture_source.NATIVE_CLIENT),
                "known": rows}
    if not rows:
        return {"present": False, "state": "never", "client": None,
                "absent_for_s": None,
                "sentence": mapping_refusals.client_never_seen(),
                "known": []}
    last = rows[0]
    gap = max(0.0, (stamp - float(last.get("last_seen_ms") or stamp)) / 1000.0)
    return {"present": False, "state": "absent", "client": last,
            "absent_for_s": round(gap, 1),
            "sentence": mapping_refusals.client_absent(
                str(last.get("host") or ""),
                pose_name=str(last.get("pose_name") or ""),
                version=str(last.get("version") or ""),
                absent_for_s=gap,
                last_seen=_stamp_words(last.get("last_seen_ms"))),
            "known": rows}


def _stamp_words(ms) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(float(ms) / 1000.0))
    except (TypeError, ValueError):
        return ""
