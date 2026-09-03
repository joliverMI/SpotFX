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

A REACHABLE-BUT-BROKEN CLIENT MUST NEVER LOOK LIKE A HEALTHY ONE (2026-09-02).
The record began with three states — `never`, `absent`, `present` — and
`present` was the whole of "a client is connected", which is a claim that
was doing more work than it could carry. The client already CONNECTS when it
cannot do its job (`session.py`: a machine with no camera says so rather
than dying quietly on a laptop nobody is watching), so a host whose camera
does not exist, whose exposure will not lock, or whose lever self-test
failed reported EXACTLY what a working one reports. Someone reading
`camera_host` saw "connected" and went looking somewhere else.

So there are FOUR states now, and the fourth is `impaired`: connected, and
saying it cannot do the job. Three things about it:

  * **`present` stays a boolean fact about the SOCKET**, true for
    `impaired` as well, because the client IS there — every existing reader
    of that field keeps the answer it already had. Only `state` and
    `sentence` change, and `unable` carries the client's OWN reason.
  * **NOT-YET IS NOT CANNOT.** A camera that has not reported its lock state
    is settling, which is the ordinary first seconds of every session; only
    a lock that was REPORTED and did not lock counts (`lock.reported`, the
    same discriminator `mapping_session.lock_refusal` already draws). A
    state that flapped through `impaired` on every healthy startup would be
    ignored inside a week.
  * **IT STILL GATES NOTHING.** A run's refusal is `lock_refusal`'s and
    `NO_SESSION`'s, unchanged and computed elsewhere; this only means the
    same fact is now READABLE from the status surface instead of having to
    be inferred from a missing map at 3am.
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

#: The four states. `IMPAIRED` is present-but-unable — see the module
#: docstring for why it is separate from PRESENT and why it is not a gate.
STATE_NEVER = "never"
STATE_ABSENT = "absent"
STATE_PRESENT = "present"
STATE_IMPAIRED = "impaired"


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
        # WHETHER THE CAMERA HAS SPOKEN AT ALL YET. The discriminator
        # between a session settling (ordinary, every startup) and one that
        # reported and will not lock (a fault) — `unable()` below is the
        # only reader, and without this it could not tell them apart.
        "lock_reported": bool(getattr(lock, "reported", False)),
        "lever": (verdict.as_dict() if hasattr(verdict, "as_dict") else {}),
    }
    # THE SESSION'S OWN REFUSAL SENTENCE, asked of the session rather than
    # composed here — `mapping_session.lock_refusal` is its author and this
    # module has never had a second copy of it. Duck-typed like everything
    # else here, so every test double stays a valid argument.
    refusal = getattr(session, "refusal", None)
    if callable(refusal):
        try:
            row["refusal"] = str(refusal() or "")
        except Exception:                              # noqa: BLE001
            logger.debug("capture health: a session would not state its "
                         "refusal", exc_info=True)
            row["refusal"] = ""
    else:
        row["refusal"] = ""
    return row


def unable(row: dict) -> str:
    """WHY THIS CONNECTED CLIENT CANNOT DO THE JOB, or "" when it can.

    Its answer is always the CLIENT'S OWN reason, never one composed here,
    and the three conditions are checked in the order a reader would want
    them: no camera at all beats a camera that will not lock, which beats a
    camera whose lever was measured not to work.

    A LOCK THAT HAS NOT BEEN REPORTED YET IS NOT A FAULT. That is a session
    in its first seconds, and treating it as one would put every healthy
    startup through `impaired` — see the module docstring."""
    if row.get("camera_error"):
        return str(row["camera_error"])
    if row.get("lock_reported") and not row.get("locked"):
        return (str(row.get("refusal") or "")
                or "this camera reported its state and it is not locked")
    verdict = dict(row.get("lever") or {})
    # ONLY A MEASUREMENT REFUSES. `refuses` is the Verdict's own property
    # and it is False for `unprovable`/`unproven` on purpose — "we could not
    # check" is not "we checked and it is broken", and reading the raw
    # verdict word here would quietly overrule that rule.
    if verdict.get("refuses") or (verdict.get("verdict")
                                  in mapping_refusals.LEVER_REFUSING):
        return (str(verdict.get("reason") or "")
                or f"the camera's lever self-test came back "
                   f"{verdict.get('verdict')}")
    return ""


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
        browser = row["client"] != capture_source.NATIVE_CLIENT
        # PRESENT-BUT-UNABLE IS ITS OWN ANSWER. `present` stays True either
        # way — the socket is a fact — so nothing that already read that
        # field changes; what changes is that "connected" no longer implies
        # "working", which it never actually did.
        reason = unable(row)
        if reason:
            return {"present": True, "state": STATE_IMPAIRED, "client": row,
                    "absent_for_s": 0.0, "unable": reason,
                    "sentence": mapping_refusals.client_impaired(
                        row["host"], reason, pose_name=row["pose_name"],
                        version=row["version"], browser=browser),
                    "known": rows}
        return {"present": True, "state": STATE_PRESENT, "client": row,
                "absent_for_s": 0.0, "unable": "",
                "sentence": mapping_refusals.client_present(
                    row["host"], pose_name=row["pose_name"],
                    version=row["version"],
                    # `describe` already files a browser session under
                    # "browser"; the sentence says so rather than calling a
                    # phone the capture client.
                    browser=browser),
                "known": rows}
    if not rows:
        return {"present": False, "state": STATE_NEVER, "client": None,
                "absent_for_s": None, "unable": "",
                "sentence": mapping_refusals.client_never_seen(),
                "known": []}
    last = rows[0]
    gap = max(0.0, (stamp - float(last.get("last_seen_ms") or stamp)) / 1000.0)
    return {"present": False, "state": STATE_ABSENT, "client": last,
            "absent_for_s": round(gap, 1), "unable": "",
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
