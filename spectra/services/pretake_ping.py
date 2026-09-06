"""THE PRE-TAKE PING — one POST to River, at the start of every take of the
room, so his house can photograph itself BEFORE SPECTRA changes a fixture.

WHAT IT IS FOR. River holds a Home-Assistant snapshot watch: before a night
prepares his house she `scene.create`s the pre-preparation state and restores
it byte-identically afterwards (the seam's own snapshot refinement). Her
existing trigger fires on "is ambient running", which tracks the NIGHT, not
the TAKE — so an ATTENDED take (he presses the ownership bar, or the armed
handover route runs) moves his lights with no snapshot behind them. The
owner's chosen fix is this: SPECTRA announces every take, at its start,
before it has touched anything, and then WAITS a moment so she can read.

    POST {SPECTRA_PRETAKE_URL}
    Authorization: Bearer {SPECTRA_PRETAKE_TOKEN}
    {"event": "pre_take", "room_id": "<id>", "at_ms": <epoch ms>}
    → 200 {"captured": <bool>, "elapsed_s": <float>, "result": <str>}

SPECTRA CONFORMS TO RIVER'S CONTRACT AND DOES NOT RENEGOTIATE IT — the
posture `witness.py` takes with her change service and `transcription.py`
takes with the Whisper bridge. Her endpoint is DEPLOYED and this shape is
confirmed against it (2026-09-06). The configured value is the FULL endpoint
URL, so the route is hers to name and this side never appends a path of its
own; the address it carries at deploy is hers to move, which is exactly why
it is an environment value here and NOT a default in this repository.

**SUCCESS IS HTTP 200, HER WORD, NOT "any 2xx".** Anything else — another
status, a transport error, a timeout — is `failed`, fail-soft. Her answer's
`captured` and `elapsed_s` are SURFACED on the result (and so on the take's
own record) rather than reduced to a boolean: "River answered and captured
in 0.4s" and "River answered and captured nothing" are different facts about
his room, and a status word alone cannot hold both.

A 200 SAYING `captured: false` IS STILL `sent`, AND IT IS STILL LOUD. Her
contract names 200 as success and enumerates the failures (non-200, error,
timeout, unconfigured); inventing a fourth verdict she has not defined would
be renegotiating it. So the STATUS follows her word and the DETAIL and the
log say what she actually reported — the outcome carries `captured`, so a
snapshot that did not happen is a read on the record, never a silence.

────────────────────────────────────────────────────────────────────────────
THIS IS THE MIRROR IMAGE OF THE WITNESS, AND THE BOUNDARY IS THE SAME
────────────────────────────────────────────────────────────────────────────

The witness READS River. This WRITES to her — one small POST — and that is
the only difference. In particular it changes NOTHING about the rule
`witness.py` states as a hard prohibition: SPECTRA has no Home Assistant
write access, no HA path, and no second route into his house. This is a POST
to a RIVER SERVICE, which then decides what (if anything) to do in HA. THE
SCONCE MAINS RULE is untouched and untouchable from here: this module drives
no entity, names none, and could not turn a light on or off if asked to.

────────────────────────────────────────────────────────────────────────────
FAIL-SOFT, ALWAYS. IT CAN DELAY A TAKE; IT CAN NEVER REFUSE ONE.
────────────────────────────────────────────────────────────────────────────

`before_take()` NEVER RAISES. Unconfigured, unreachable, refused, timed out,
malformed — every one of them comes back as a `PingResult` the caller
reports, and the take proceeds. Three statuses, and the middle one is the
point:

    sent            River answered 2xx; her watch has been told
    failed          she was asked and it did not land — SAID OUT LOUD on
                    the take's own result, never swallowed
    unconfigured    `SPECTRA_PRETAKE_URL` is unset: nothing was sent and
                    nothing was waited for

The three exist for the reason `witness.VERDICT_UNAVAILABLE` exists and
`night_exit` separates DARK from UNKNOWN: "we did not ask" and "we asked and
it failed" are different facts about his room, and collapsing them would let
a deploy that never provisioned the URL read exactly like a River outage.

WHY A FAILED PING STILL SETTLES. The wait happens after a SUCCESSFUL **OR
ATTEMPTED** ping, and only the `unconfigured` case skips it. A refused or
timed-out POST may still have ARRIVED — a read timeout says nothing about
whether River received the request and started her scene — so skipping the
settle on a failure would be racing the one snapshot this exists to protect,
to save a second and a half. The one case where nothing can possibly have
arrived is the one where nothing was sent, and that is the case that skips.

────────────────────────────────────────────────────────────────────────────
UNSET URL == INERT, AND THAT IS THE SHIPPED STATE
────────────────────────────────────────────────────────────────────────────

With `SPECTRA_PRETAKE_URL` absent every take is byte-identical to the one
before this module existed: no request, no `asyncio.sleep`, no import of
httpx, and a result whose only effect is a field on the take's record. It is
proven rather than claimed (`tests/test_pretake_ping.py` drives both take
paths unconfigured and asserts zero sleeps and zero requests), because
"inert by default" is the whole reason this could land before River's
endpoint exists.

────────────────────────────────────────────────────────────────────────────
`room_id`, STATED RATHER THAN INVENTED
────────────────────────────────────────────────────────────────────────────

The field is on the wire because the contract names it, and it is supplied
BY THE CALLER. Neither take path is scoped to a room today: a take is of THE
lights, whole, and SPECTRA's only room ids are the light-field map's random
hex (`spectra/models/room_map.py`), which would mean nothing to River. So
both callers pass `ROOM_ALL` — a stable, honest word saying "the whole room"
— rather than a fabricated id or a light-field id that does not describe
what was taken. The parameter exists so a future room-scoped take needs no
wire change and no conversation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from spectra import config

logger = logging.getLogger(__name__)

#: The event word on the wire. Closed and small, `night_take.EVENT_TAKEN`'s
#: own discipline: River renders it, and a vocabulary that grows quietly is a
#: contract that breaks quietly.
EVENT_PRE_TAKE = "pre_take"

#: What both take paths pass as `room_id` — see the docstring's own section.
#: A take is of the whole room; this says so instead of inventing an id.
ROOM_ALL = "all"

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_UNCONFIGURED = "unconfigured"

#: Bounded, and TIGHTER than the witness's, because this one sits on the
#: critical path of taking his room where the witness's overlaps a capture's
#: own settle. Worst case ~5s of connect+read, inside the grace every take
#: already spends releasing the Hue session.
CONNECT_TIMEOUT_S = 2.0
READ_TIMEOUT_S = 3.0
WRITE_TIMEOUT_S = 2.0
POOL_TIMEOUT_S = 1.0


@dataclass
class PingResult:
    """One take's announcement, in the shape a take result carries it.
    `status` is the word a program branches on; `detail` is the sentence a
    person reads."""

    status: str = STATUS_UNCONFIGURED
    detail: str = ""
    at_ms: int = 0
    room_id: str = ""
    #: How long the take actually waited after the ping, in ms. Zero on the
    #: unconfigured path, which is what makes "no settle when inert" a
    #: readable fact rather than an argument.
    settled_ms: int = 0
    #: River's own status code when she answered at all. `None` means the
    #: request never got an answer (or was never sent).
    http_status: Optional[int] = None
    #: HER ANSWER, surfaced rather than reduced. `captured` is whether she
    #: took the snapshot, `elapsed_s` how long it took her, `river_result`
    #: her own word for it (named apart from OUR `status` so a reader is
    #: never in doubt whose verdict they are looking at). `None`/empty means
    #: she did not say — which is not the same as saying no.
    captured: Optional[bool] = None
    elapsed_s: Optional[float] = None
    river_result: str = ""
    announce: list = field(default_factory=list)

    @property
    def sent(self) -> bool:
        return self.status == STATUS_SENT

    @property
    def configured(self) -> bool:
        return self.status != STATUS_UNCONFIGURED

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail,
                "at_ms": self.at_ms, "room_id": self.room_id,
                "settled_ms": self.settled_ms,
                "http_status": self.http_status,
                "captured": self.captured, "elapsed_s": self.elapsed_s,
                "river_result": self.river_result}


#: The most recent announcement, for surfaces that cannot be handed the
#: result directly — `handover.run_handover` returns an `OwnershipRecord`,
#: so the armed API route reads it from here to put the outcome in its own
#: response. Exactly `activation_report.current()`'s pattern, and read with
#: the same care: it describes the LAST take, so a caller must only report
#: it for a take it just performed.
_last: Optional[PingResult] = None


def last() -> Optional[PingResult]:
    return _last


def reset() -> None:
    """Drop the remembered result. For tests and for a cold start; nothing
    in production needs it, since every `before_take()` replaces it."""
    global _last
    _last = None


#: RIVER'S OWN SUCCESS CODE, her word: 200 exactly, never "any 2xx". A
#: redirect or a 204 from something that is not her endpoint must not read
#: as a captured snapshot.
SUCCESS_STATUS = 200


def pretake_url() -> str:
    """Base of the announcement — `witness.witness_url()`'s exact shape, one
    module over. Read at call time; the definition lives in
    `spectra/config.py` so every SPECTRA environment knob has one home."""
    return config.pretake_url()


def pretake_token() -> str:
    """The bearer, from the environment ONLY — `witness.witness_token()`
    mirrored exactly: never logged, never recorded, never read from a file
    by this code. It is loaded into the environment at deploy from a file
    that lives outside this repository, the way the witness bearer is."""
    return config.pretake_token()


def configured() -> bool:
    """Whether there is an endpoint to announce to at all. URL ONLY — a
    missing token is a VISIBLE 401, not silence (see `config.pretake_token`)."""
    return bool(pretake_url())


def payload(room_id: str, at_ms: int) -> dict:
    """The body, verbatim as the contract names it. Built here so the wire
    shape has ONE definition and a test can assert against the same function
    the take actually sends."""
    return {"event": EVENT_PRE_TAKE, "room_id": room_id, "at_ms": at_ms}


async def before_take(*, room_id: str = ROOM_ALL,
                      client: Optional[Any] = None,
                      sleep=None) -> PingResult:
    """ANNOUNCE THE TAKE, THEN WAIT — call this before anything touches a
    fixture. Never raises.

    The ordering is the whole correctness property: River's watch must be
    able to read his room in the state SPECTRA found it, so the only place
    this call is correct is ahead of the first write. `handover.run_handover`
    and `night_take.take_room` each call it as their first light-affecting
    act, and `tests/test_pretake_ping.py` proves the ordering on both.

    `sleep` is the settle's injection seam (the tests count and measure it
    rather than spending real seconds); production uses `asyncio.sleep`."""
    global _last
    at_ms = int(time.time() * 1000)
    url = pretake_url()
    if not url:
        # INERT. Nothing sent, nothing waited for, no httpx import — the
        # shipped state, and byte-identical to a take before this existed.
        result = PingResult(
            status=STATUS_UNCONFIGURED, at_ms=at_ms, room_id=room_id,
            detail="the pre-take ping is not configured on this host "
                   "(SPECTRA_PRETAKE_URL), so River's snapshot watch was "
                   "not told this take was starting")
        _last = result
        return result

    answer = await _post(url, room_id, at_ms, client=client)
    settle_ms = config.pretake_settle_ms()
    if settle_ms > 0:
        # AFTER A SUCCESSFUL **OR ATTEMPTED** PING — a failed POST may still
        # have arrived, and racing the snapshot to save 1.5s is the wrong
        # trade. See the module docstring.
        await (sleep or asyncio.sleep)(settle_ms / 1000.0)
    result = PingResult(status=answer.status, detail=answer.detail,
                        at_ms=at_ms, room_id=room_id, settled_ms=settle_ms,
                        http_status=answer.http_status,
                        captured=answer.captured, elapsed_s=answer.elapsed_s,
                        river_result=answer.river_result)
    result.announce.append({"event": EVENT_PRE_TAKE, "at_ms": at_ms,
                            "room_id": room_id, "status": answer.status,
                            "captured": answer.captured})
    if answer.status == STATUS_SENT and answer.captured is not False:
        logger.warning("pre-take ping: River told (room=%s, captured=%s, "
                       "elapsed=%ss, settle=%dms)", room_id, answer.captured,
                       answer.elapsed_s, settle_ms)
    else:
        # LOUD, NEVER FATAL — and loud for BOTH shapes of bad news: a ping
        # that did not land, and one that landed on a River who says she
        # captured nothing. The take carries on either way; this is the line
        # that stops a missing snapshot from being invisible afterwards.
        logger.error("pre-take ping — the take proceeds and River's snapshot "
                     "watch may NOT hold this room's pre-take state: %s",
                     answer.detail)
    _last = result
    return result


@dataclass
class _Answer:
    """What one POST came back with, before the settle is priced in."""
    status: str
    http_status: Optional[int] = None
    detail: str = ""
    captured: Optional[bool] = None
    elapsed_s: Optional[float] = None
    river_result: str = ""


def read_answer(status_code: int, body: Any) -> _Answer:
    """HER ANSWER → our record. Split out from the transport so the wire's
    own reading has ONE definition a spec can drive directly, the way
    `witness.parse_rows` is separable from `witness._get`.

    SUCCESS IS EXACTLY 200 (her word). A 200 whose body is not the object
    she documents is still a landed ping — the request reached her — and
    simply carries no `captured`: `None` means SHE DID NOT SAY, which this
    module is careful never to render as "she said no"."""
    if status_code != SUCCESS_STATUS:
        return _Answer(
            STATUS_FAILED, status_code,
            f"River's pre-take endpoint answered {status_code} rather than "
            f"{SUCCESS_STATUS} — her snapshot watch was not told this take "
            f"was starting")
    captured = elapsed_s = None
    river_result = ""
    if isinstance(body, dict):
        if isinstance(body.get("captured"), bool):
            captured = body["captured"]
        raw_elapsed = body.get("elapsed_s")
        if isinstance(raw_elapsed, (int, float)) \
                and not isinstance(raw_elapsed, bool):
            elapsed_s = float(raw_elapsed)
        river_result = str(body.get("result") or "")
    if captured is True:
        detail = (f"River captured the pre-take state"
                  + (f" in {elapsed_s}s" if elapsed_s is not None else "")
                  + (f" ({river_result})" if river_result else ""))
    elif captured is False:
        detail = ("River answered 200 and reported that she captured "
                  "NOTHING — this take has no pre-take snapshot behind it"
                  + (f" ({river_result})" if river_result else ""))
    else:
        detail = ("River's pre-take endpoint answered 200 without saying "
                  "whether it captured — the ping landed, the snapshot is "
                  "unconfirmed")
    return _Answer(STATUS_SENT, status_code, detail, captured, elapsed_s,
                   river_result)


async def _post(url: str, room_id: str, at_ms: int, *,
                client: Optional[Any] = None) -> _Answer:
    """One authenticated POST. Never logs the token or the URL's own
    credentials, and never lets a transport exception escape — a caller of
    this module catches nothing, because nothing is raised."""
    import httpx

    headers = {}
    token = pretake_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S,
            write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S))
    try:
        resp = await client.post(url, json=payload(room_id, at_ms),
                                 headers=headers)
        try:
            body = resp.json()
        except Exception:                               # noqa: BLE001
            body = None
        answer = read_answer(resp.status_code, body)
        if answer.status == STATUS_FAILED and not token:
            answer.detail += (" (no SPECTRA_PRETAKE_TOKEN is set on this "
                              "host, so no bearer was sent)")
        return answer
    except Exception as exc:                            # noqa: BLE001
        # Deliberately the exception CLASS only: the configured URL can
        # carry credentials and the token must never reach a log line.
        return _Answer(
            STATUS_FAILED, None,
            f"River's pre-take endpoint could not be reached "
            f"({type(exc).__name__}) — her snapshot watch was not told "
            f"this take was starting")
    finally:
        if own:
            await client.aclose()
