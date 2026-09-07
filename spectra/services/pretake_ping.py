"""THE TWO BOUNDARY PINGS — one POST to River at each edge of SPECTRA
holding his room. PRE-TAKE, at the start of every take, so his house can
photograph itself BEFORE SPECTRA changes a fixture. RELEASED, the moment the
panic release has finished letting the fixtures go, so her restore fires off
a STATEMENT that it happened rather than off a sensor she has to infer it
from. ONE endpoint, ONE bearer, ONE wire shape, one transport, one reading
of her answer — the `event` word is the only field that differs, which is
exactly why this is one module and not two.

WHAT THE PRE-TAKE IS FOR. River holds a Home-Assistant snapshot watch:
before a night prepares his house she `scene.create`s the pre-preparation
state and restores it byte-identically afterwards (the snapshot refinement
the seam names). Her existing trigger fired on "is ambient running", which
tracks the NIGHT, not the TAKE — so an ATTENDED take (he presses the
ownership bar, or the armed handover route runs) moved his lights with no
snapshot behind them. The owner's chosen fix is this: SPECTRA announces
every take, at its start, before it has touched anything, and then WAITS a
moment so she can read.

    POST {SPECTRA_PRETAKE_URL}
    Authorization: Bearer {SPECTRA_PRETAKE_TOKEN}
    {"event": "pre_take", "room_id": "<id>", "at_ms": <epoch ms>}
    → 200 {"captured": <bool>, "elapsed_s": <float>, "result": <str>}

WHAT THE RELEASE PING IS FOR. The other edge of the same boundary. River is
building a bridge-direct, byte-exact capture and restore of all 17 Hue
bulbs; the restore has to fire when SPECTRA has actually LET GO, and her
only trigger for that was the same ambient-mode sensor — an inference about
the NIGHT, not a statement about the RELEASE. So the panic release announces
itself the instant its Hue fade has finished, on the SAME endpoint and the
SAME bearer, one field different:

    {"event": "released", "room_id": "<id>", "at_ms": <epoch ms>}

AND IT DOES NOT SETTLE. The pre-take waits because River has to read a room
that is about to change; a release has already happened, there is nothing
left to protect from a race, and River restores on her own schedule. A wait
here would buy nothing and hold the panic handle open for it.

WHAT ANNOUNCES A RELEASE IS `release.release_room()`, AND ONLY THAT — which
is every way SPECTRA actually lets go of the room: his panic press, the
reconciler's armed escalation, and the night's own give-back, all of which
already funnel through that one function. A HANDOVER back to spot-effects
is deliberately NOT one of them and never announces: the room is not
released there, it has a new writer, and telling River to restore over a
world that is about to start painting his fixtures is the pre-take's own
ordering mistake pointed the other way.

SPECTRA CONFORMS TO RIVER'S CONTRACT AND DOES NOT RENEGOTIATE IT — the
posture `witness.py` takes with her change service and `transcription.py`
takes with the Whisper bridge. Her endpoint is DEPLOYED and this shape is
confirmed against it (2026-09-06). The configured value is the FULL endpoint
URL, so the route is hers to name and this side never appends a path of its
own; the address it carries at deploy is hers to move, which is exactly why
it is an environment value here and NOT a default in this repository.

**SUCCESS IS HTTP 200, HER WORD, NOT "any 2xx"** — on both events; the two
share one reading of her answer (`read_answer`) so a release can never be
judged by a second, drifted copy of it. Anything else — another status, a
transport error, a timeout — is `failed`, fail-soft. Her answer's `captured`
and `elapsed_s` are SURFACED on the result (and so on the take's or the
release's own record) rather than reduced to a boolean: "River answered and
captured in 0.4s" and "River answered and captured nothing" are different
facts about his room, and a status word alone cannot hold both.

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
FAIL-SOFT, ALWAYS. IT CAN DELAY A TAKE; IT CAN NEVER REFUSE OR UNDO ONE.
────────────────────────────────────────────────────────────────────────────

`before_take()` AND `after_release()` NEVER RAISE. Unconfigured, unreachable,
refused, timed out, malformed — every one of them comes back as a
`PingResult` the caller reports, and the take (or the release) proceeds
exactly as it would have. On the release side that property is stronger
still, because the release has ALREADY HAPPENED by the time the ping goes
out: a ping that did not land is a fact about River's watch and must never
be folded into whether the room really let go — `release.ReleaseResult`
carries it beside `verified`, never inside it. Three statuses, and the
middle one is the point:

    sent            River answered 2xx; her watch has been told
    failed          she was asked and it did not land — SAID OUT LOUD on
                    the take's own result, never swallowed
    unconfigured    `SPECTRA_PRETAKE_URL` is unset: nothing was sent (and,
                    on the pre-take, nothing was waited for)

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

With `SPECTRA_PRETAKE_URL` absent every take AND every release is
byte-identical to the one before this module existed: no request, no
`asyncio.sleep`, no import of httpx, and a result whose only effect is a
field on the outcome record. It is proven rather than claimed
(`tests/test_pretake_ping.py` drives both take paths unconfigured and
asserts zero sleeps and zero requests; `tests/test_release_ping.py` does the
same for the release and compares its whole step sequence against a release
with the call removed), because "inert by default" is the whole reason each
of these could land before River's own half was finished.

────────────────────────────────────────────────────────────────────────────
`room_id`, STATED RATHER THAN INVENTED
────────────────────────────────────────────────────────────────────────────

The field is on the wire because the contract names it, and it is supplied
BY THE CALLER. No take path and no release path is scoped to a room today: a
take is of THE lights, whole, and SPECTRA's only room ids are the
light-field map's random hex (`spectra/models/room_map.py`), which would
mean nothing to River. So every caller passes `ROOM_ALL` — a stable, honest
word saying "the whole room" — rather than a fabricated id or a light-field
id that does not describe what was taken or given back. The parameter exists
so a future room-scoped take needs no wire change and no conversation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from spectra import config

logger = logging.getLogger(__name__)

#: The event words on the wire. Closed and small, `night_take.EVENT_TAKEN`'s
#: own discipline: River renders them, and a vocabulary that grows quietly is
#: a contract that breaks quietly. There are exactly two, one per edge of
#: SPECTRA holding the room.
EVENT_PRE_TAKE = "pre_take"
EVENT_RELEASED = "released"

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

#: The most recent RELEASE announcement, kept SEPARATELY rather than sharing
#: `_last`. A single slot would let a release overwrite the take result the
#: armed handover route reads back, so the two edges of the room get one
#: slot each and `last()`'s existing contract — "the last TAKE" — is exactly
#: what it always was.
_last_release: Optional[PingResult] = None


def last() -> Optional[PingResult]:
    """The last PRE-TAKE announcement. Unchanged: a release never lands
    here, so no caller of this can be handed a release by surprise."""
    return _last


def last_release() -> Optional[PingResult]:
    """The last RELEASE announcement. `release.release_room` is handed its
    own result directly and does not need this; it exists for a surface that
    cannot be — the same reason `last()` does."""
    return _last_release


def reset() -> None:
    """Drop the remembered results, BOTH of them. For tests and for a cold
    start; nothing in production needs it, since every `before_take()` /
    `after_release()` replaces its own."""
    global _last, _last_release
    _last = None
    _last_release = None


#: RIVER'S OWN SUCCESS CODE, her word: 200 exactly, never "any 2xx". A
#: redirect or a 204 from something that is not her endpoint must not read
#: as a captured snapshot.
SUCCESS_STATUS = 200


@dataclass(frozen=True)
class _Words:
    """THE SENTENCES A PERSON READS, one set per event.

    The two pings share one endpoint, one bearer, one transport and one
    reading of her answer — only the WORDS differ, because "her snapshot
    watch was not told this take was starting" is a lie about a release and
    would send whoever read it to look at the wrong end of the evening. So
    the wording is a table rather than a second copy of `read_answer`: there
    is still exactly one function that reads her answer, and a spec drives
    the same one the room does.

    THE PRE-TAKE STRINGS ARE FROZEN BYTE FOR BYTE. They predate the release
    ping and `tests/test_pretake_ping.py` asserts several of them; this table
    is a refactor of where they live, never of what they say."""

    #: How the endpoint is NAMED in a sentence. The release path says "ping
    #: endpoint" rather than "release endpoint" on purpose: it is the SAME
    #: configured URL, and a second name would imply a second address a
    #: reader could go looking for in the unit file.
    endpoint: str
    #: The "…and so she was not told" clause, for every failure shape.
    not_told: str
    #: Sentence-start when she answered 200 and said she acted.
    acted: str
    #: The whole sentence when she answered 200 and said she did not.
    did_nothing: str
    #: The whole sentence when she answered 200 and did not say either way.
    unconfirmed: str
    #: The whole sentence on the inert path — no URL, nothing sent.
    unconfigured: str
    #: The prefix on this event's own log lines.
    log: str


WORDS = {
    EVENT_PRE_TAKE: _Words(
        endpoint="River's pre-take endpoint",
        not_told="her snapshot watch was not told this take was starting",
        acted="River captured the pre-take state",
        did_nothing="River answered 200 and reported that she captured "
                    "NOTHING — this take has no pre-take snapshot behind it",
        unconfirmed="River's pre-take endpoint answered 200 without saying "
                    "whether it captured — the ping landed, the snapshot is "
                    "unconfirmed",
        unconfigured="the pre-take ping is not configured on this host "
                     "(SPECTRA_PRETAKE_URL), so River's snapshot watch was "
                     "not told this take was starting",
        log="pre-take ping"),
    EVENT_RELEASED: _Words(
        endpoint="River's ping endpoint",
        not_told="her restore watch was not told this release completed",
        acted="River acted on the release",
        did_nothing="River answered 200 and reported that she did NOTHING — "
                    "this release has no restore behind it",
        unconfirmed="River's ping endpoint answered 200 without saying "
                    "whether it acted — the ping landed, the restore is "
                    "unconfirmed",
        unconfigured="the River ping is not configured on this host "
                     "(SPECTRA_PRETAKE_URL), so River's restore watch was "
                     "not told this release completed",
        log="release ping"),
}


def words(event: str) -> _Words:
    """The wording for an event, falling back to the pre-take's rather than
    raising: this module's whole posture is that it can never be the reason
    a take or a release fails, and that has to include a caller passing an
    event word nobody has written sentences for yet."""
    return WORDS.get(event, WORDS[EVENT_PRE_TAKE])


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


def payload(room_id: str, at_ms: int,
            event: str = EVENT_PRE_TAKE) -> dict:
    """The body, verbatim as the contract names it. Built here so the wire
    shape has ONE definition and a test can assert against the same function
    the take actually sends.

    `event` DEFAULTS TO THE PRE-TAKE so the take path is byte-identical to
    what it was before the release ping existed — the same reason `_post`
    and `read_answer` take it as a defaulted keyword rather than a required
    argument."""
    return {"event": event, "room_id": room_id, "at_ms": at_ms}


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
            detail=words(EVENT_PRE_TAKE).unconfigured)
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


async def after_release(*, room_id: str = ROOM_ALL,
                        client: Optional[Any] = None) -> PingResult:
    """ANNOUNCE THAT THE ROOM HAS BEEN LET GO — call this once the release
    has actually finished letting the fixtures go. Never raises.

    `release.release_room()` calls it immediately after its Hue fade, which
    is the first instant the statement is TRUE: the entertainment stream is
    frozen and the bulbs have been taken down, so River's bridge-direct
    restore has an uncontested room to write into while SPECTRA finishes
    tearing the rest of the stack down behind it. Announcing any earlier
    would be announcing a release that had not happened.

    THERE IS NO SETTLE, and its absence is the design, not an omission. The
    pre-take waits because River must read a room that is ABOUT to change;
    here the change is already done and there is no race left to lose — a
    wait would only hold the panic handle open while nothing was protected.
    So `settled_ms` is always 0, and there is no `sleep` seam to inject.

    IT CANNOT UNDO A RELEASE, AND IT MUST NOT BE ABLE TO RE-COLOUR ONE. The
    result is carried BESIDE `ReleaseResult.verified`, never folded into it:
    whether the room really let go is a question about his fixtures, and a
    ping that did not land is a question about River's watch. Collapsing the
    two would make a genuinely dark room read as an unverified release."""
    global _last_release
    at_ms = int(time.time() * 1000)
    url = pretake_url()
    if not url:
        # INERT — the shipped state. Nothing sent, no httpx import, and a
        # release whose every other step is exactly what it always was.
        result = PingResult(
            status=STATUS_UNCONFIGURED, at_ms=at_ms, room_id=room_id,
            detail=words(EVENT_RELEASED).unconfigured)
        _last_release = result
        return result

    answer = await _post(url, room_id, at_ms, client=client,
                         event=EVENT_RELEASED)
    result = PingResult(status=answer.status, detail=answer.detail,
                        at_ms=at_ms, room_id=room_id, settled_ms=0,
                        http_status=answer.http_status,
                        captured=answer.captured, elapsed_s=answer.elapsed_s,
                        river_result=answer.river_result)
    result.announce.append({"event": EVENT_RELEASED, "at_ms": at_ms,
                            "room_id": room_id, "status": answer.status,
                            "captured": answer.captured})
    if answer.status == STATUS_SENT and answer.captured is not False:
        logger.warning("release ping: River told (room=%s, acted=%s, "
                       "elapsed=%ss)", room_id, answer.captured,
                       answer.elapsed_s)
    else:
        # LOUD, NEVER FATAL. The room HAS been released either way; this is
        # the line that stops "River never restored" from being a mystery
        # the next morning instead of a sentence in the journal.
        logger.error("release ping — the room IS released and River's "
                     "restore watch may NOT have been told: %s",
                     answer.detail)
    _last_release = result
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


def read_answer(status_code: int, body: Any,
                event: str = EVENT_PRE_TAKE) -> _Answer:
    """HER ANSWER → our record, for EITHER event. Split out from the
    transport so the wire's own reading has ONE definition a spec can drive
    directly, the way `witness.parse_rows` is separable from `witness._get`
    — and kept as one function across both pings so a release can never be
    read by a second, drifted copy of this logic.

    SUCCESS IS EXACTLY 200 (her word). A 200 whose body is not the object
    she documents is still a landed ping — the request reached her — and
    simply carries no `captured`: `None` means SHE DID NOT SAY, which this
    module is careful never to render as "she said no"."""
    w = words(event)
    if status_code != SUCCESS_STATUS:
        return _Answer(
            STATUS_FAILED, status_code,
            f"{w.endpoint} answered {status_code} rather than "
            f"{SUCCESS_STATUS} — {w.not_told}")
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
        detail = (w.acted
                  + (f" in {elapsed_s}s" if elapsed_s is not None else "")
                  + (f" ({river_result})" if river_result else ""))
    elif captured is False:
        detail = (w.did_nothing
                  + (f" ({river_result})" if river_result else ""))
    else:
        detail = w.unconfirmed
    return _Answer(STATUS_SENT, status_code, detail, captured, elapsed_s,
                   river_result)


async def _post(url: str, room_id: str, at_ms: int, *,
                client: Optional[Any] = None,
                event: str = EVENT_PRE_TAKE) -> _Answer:
    """One authenticated POST, for either event. Never logs the token or the
    URL's own credentials, and never lets a transport exception escape — a
    caller of this module catches nothing, because nothing is raised.

    `event` is a DEFAULTED keyword so the pre-take's call site is unchanged
    and every existing spec that stands a fake in for this function keeps
    working against the signature it was written for."""
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
        resp = await client.post(url, json=payload(room_id, at_ms, event),
                                 headers=headers)
        try:
            body = resp.json()
        except Exception:                               # noqa: BLE001
            body = None
        answer = read_answer(resp.status_code, body, event)
        if answer.status == STATUS_FAILED and not token:
            answer.detail += (" (no SPECTRA_PRETAKE_TOKEN is set on this "
                              "host, so no bearer was sent)")
        return answer
    except Exception as exc:                            # noqa: BLE001
        # Deliberately the exception CLASS only: the configured URL can
        # carry credentials and the token must never reach a log line.
        w = words(event)
        return _Answer(
            STATUS_FAILED, None,
            f"{w.endpoint} could not be reached "
            f"({type(exc).__name__}) — {w.not_told}")
    finally:
        if own:
            await client.aclose()
