"""THE PRE-TAKE PING — announced before the room is touched, waited on, and
never able to stop a take.

NO NETWORK, NO LIVE ROOM, NO HOME ASSISTANT anywhere in this file:
`httpx.MockTransport` stands in for River's service exactly as
`tests/test_witness.py` does for her change service, the writer sides are
fakes that record WHEN they were called against one shared log, and the
ownership record is repointed into `tmp_path`. The deploy-time bearer is
never read by anything here.

THE PROOFS, in the order the brief puts them:

  1. THE ORDERING, on BOTH take paths — the ping lands strictly before the
     first act that could change a fixture (`quiesce` on the interactive
     handover, and every side call plus the snapshot file on the night's own
     take). This is the correctness property: River's watch has to read his
     room in the state SPECTRA found it, so a ping that fires after the
     first write is worth nothing at all. Each ordering test has its RED
     control: the same rig with the ping moved after the writes fails it.
  2. THE SETTLE happens BETWEEN the ping and the take, and is the configured
     duration.
  3. FAIL-SOFT — endpoint down, 500, 401-with-no-token: the take still
     commits and the outcome is REPORTED, `failed`, never swallowed.
  4. INERT when `SPECTRA_PRETAKE_URL` is unset: zero requests, zero sleeps,
     and a take whose side-call sequence is byte-identical to the same take
     with the module absent.
  5. THE WIRE — `{event, room_id, at_ms}` and the bearer, asserted against
     the real request the real client built.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import light_ownership as lo
from spectra import config
from spectra.services import handover as handover_mod
from spectra.services import night_take, pretake_ping


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    """Every test starts with no remembered ping and an isolated ownership
    record. `SPECTRA_PRETAKE_*` are DELETED rather than set, so a test that
    wants the configured path has to say so — the inert case is the default
    here exactly as it is on his host."""
    monkeypatch.delenv("SPECTRA_PRETAKE_URL", raising=False)
    monkeypatch.delenv("SPECTRA_PRETAKE_TOKEN", raising=False)
    monkeypatch.delenv("SPECTRA_PRETAKE_SETTLE_MS", raising=False)
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    pretake_ping.reset()
    yield
    pretake_ping.reset()


def _configured(monkeypatch, *, url="http://river.invalid/pre-take",
                token="not-the-real-one", settle_ms=None):
    monkeypatch.setenv("SPECTRA_PRETAKE_URL", url)
    if token is not None:
        monkeypatch.setenv("SPECTRA_PRETAKE_TOKEN", token)
    if settle_ms is not None:
        monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", str(settle_ms))


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


#: RIVER'S OWN CONFIRMED ANSWER (2026-09-06, against her live endpoint):
#: HTTP 200 carrying whether she captured, how long it took her, and her own
#: word for the result. Written once here so every spec below drives the
#: shape the deployed service actually returns.
RIVER_OK = {"captured": True, "elapsed_s": 0.41, "result": "scene created"}


#: A sentinel, so a spec can genuinely send a JSON `null` body without it
#: being read as "use the default" — which it was, and the test that wanted
#: `null` silently passed against RIVER_OK until it did not.
_DEFAULT = object()


def _ok(seen=None, body=_DEFAULT, code=200):
    def handler(request):
        if seen is not None:
            import json as _json
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = _json.loads(request.content.decode())
        return httpx.Response(code,
                              json=RIVER_OK if body is _DEFAULT else body)
    return handler


# ── the fakes: writer sides that record WHEN, against one shared log ───────

class _RecordingSide:
    """A `WriterSide` that touches nothing and writes its every call into a
    shared, ordered log — which is where the ordering assertions actually
    live. Nothing here reaches a device, a bridge or a service."""

    def __init__(self, name, log, *, quiesced=True, active=True):
        self.name = name
        self.log = log
        self._quiesced = quiesced
        self._active = active

    async def readiness_problems(self):
        self.log.append(f"{self.name}:readiness")
        return []

    async def quiesce(self):
        self.log.append(f"{self.name}:quiesce")

    async def verify_quiesced(self):
        self.log.append(f"{self.name}:verify_quiesced")
        return self._quiesced

    async def activate(self):
        self.log.append(f"{self.name}:activate")

    async def verify_active(self):
        self.log.append(f"{self.name}:verify_active")
        return self._active

    async def deactivate(self):
        self.log.append(f"{self.name}:deactivate")


def _sides(log):
    return {lo.SPOT_EFFECTS: _RecordingSide(lo.SPOT_EFFECTS, log),
            lo.SPECTRA: _RecordingSide(lo.SPECTRA, log)}


def _logging_ping(log, monkeypatch, *, status=pretake_ping.STATUS_SENT):
    """`before_take` replaced by one that writes to the shared log AND
    records the ownership record AS IT STOOD when the announcement went out
    — used where the test is about WHEN the announcement happened, not about
    what crossed the wire. The real call's own behaviour is proven against
    `httpx.MockTransport` further down.

    The captured record is the second, independent ordering assertion: at
    announcement time nothing may have moved, INCLUDING the record itself,
    which is what "River reads the room SPECTRA found" actually means."""
    seen: dict = {}

    async def before_take(*, room_id=pretake_ping.ROOM_ALL, **kw):
        log.append("ping")
        seen["record"] = lo.load()
        result = pretake_ping.PingResult(status=status, room_id=room_id,
                                         at_ms=int(time.time() * 1000))
        pretake_ping._last = result
        return result
    monkeypatch.setattr(pretake_ping, "before_take", before_take)
    return seen


def _first_write(log):
    """The index of the first entry that could have changed a fixture. A
    readiness check runs `systemctl cat` and reads a config file; quiesce is
    where the current writer is actually stopped, which the room can see."""
    touching = ("quiesce", "activate", "deactivate", "snapshot")
    for i, entry in enumerate(log):
        if any(entry.endswith(":" + t) or entry == t for t in touching):
            return i
    return len(log)


# ── 1. THE ORDERING — the correctness property, on both take paths ─────────

def test_the_interactive_take_pings_before_it_touches_a_fixture(monkeypatch):
    """`run_handover` toward SPECTRA. The ping must precede QUIESCE, not
    merely precede activation: stopping the current writer is already a
    change to his room, and a snapshot taken after it is a snapshot of a
    room SPECTRA has begun to move."""
    log: list[str] = []
    seen = _logging_ping(log, monkeypatch)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))

    record = _run(handover_mod.run_handover(lo.SPECTRA, _sides(log),
                                            grace_s=0))

    assert record.owner == lo.SPECTRA
    assert "ping" in log, "the take was never announced to River"
    assert log.index("ping") < _first_write(log), (
        f"the ping landed after SPECTRA had begun changing the room: {log}")
    # AND NOTHING HAD MOVED, including the record: River is being asked to
    # photograph a room still fully under its previous owner.
    assert seen["record"].owner == lo.SPOT_EFFECTS
    assert seen["record"].handover is None, \
        "the take was announced with the handover already in flight"


def test_the_ordering_instrument_discriminates(monkeypatch):
    """THE INSTRUMENT'S OWN CONTROL — `_first_write` has to be able to fail,
    or every ordering assertion above is decoration.

    The source-level control was run by hand and is recorded here so nobody
    has to trust the assertion alone: moving `before_take` in
    `handover.run_handover` to just before `light_ownership.commit`, and in
    `night_take.take_room` to after the handover returns, turns
    `test_the_interactive_take_pings_before_it_touches_a_fixture`,
    `test_the_night_take_pings_before_the_snapshot_and_before_any_side` and
    `test_a_failed_ping_does_not_stop_the_interactive_take` RED — verified
    2026-09-06, on this rig, before the code was restored."""
    late = ["spectra:readiness", "spot-effects:quiesce", "ping"]
    assert _first_write(late) == 1
    with pytest.raises(AssertionError):
        assert late.index("ping") < _first_write(late)
    early = ["spectra:readiness", "ping", "spot-effects:quiesce"]
    assert early.index("ping") < _first_write(early)


def test_the_night_take_pings_before_the_snapshot_and_before_any_side(
        monkeypatch, tmp_path):
    """`night_take.take_room` — the self-taking night. Its own first acts
    are the snapshot file and the quiet handover; the announcement precedes
    BOTH, so River reads a room nothing has begun to move and so a spec's
    fake handover cannot hide the ping by standing in for it."""
    log: list[str] = []
    seen = _logging_ping(log, monkeypatch)
    monkeypatch.setattr(night_take.scfg, "NIGHT_TAKE_FILE",
                        tmp_path / "night-take.json")
    lo._save(lo.OwnershipRecord(owner=lo.RELEASED))

    real_save = night_take.save_snapshot

    def save_snapshot(**kw):
        log.append("snapshot")
        return real_save(**kw)
    monkeypatch.setattr(night_take, "save_snapshot", save_snapshot)

    seen_kw: dict = {}

    async def handover(to_world, sides, *, quiet=False, pretake=True, **kw):
        seen_kw.update(quiet=quiet, pretake=pretake)
        log.append("handover")
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()

    result = _run(night_take.take_room("night-1", sides={},
                                       run_handover=handover))

    assert result.took is True
    assert log[0] == "ping", f"the night moved before it announced: {log}"
    assert log.index("ping") < log.index("snapshot") < log.index("handover")
    assert seen_kw["quiet"] is True
    assert seen_kw["pretake"] is False, (
        "the night let run_handover announce a SECOND time — one take, one "
        "ping")
    assert result.pretake["status"] == pretake_ping.STATUS_SENT
    assert seen["record"].owner == lo.RELEASED, \
        "the night announced a take that had already begun"


def test_a_night_take_that_is_not_taking_never_announces(monkeypatch,
                                                         tmp_path):
    """A room SPECTRA does not hold is not taken, so there is nothing to
    photograph and nothing to announce — the refusal path must be silent."""
    log: list[str] = []
    _logging_ping(log, monkeypatch)
    monkeypatch.setattr(night_take.scfg, "NIGHT_TAKE_FILE",
                        tmp_path / "night-take.json")
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))

    async def handover(*a, **kw):
        raise AssertionError("a take was attempted on a held room")

    result = _run(night_take.take_room("night-1", sides={},
                                       run_handover=handover))
    assert result.refusal == "not_released"
    assert log == [], f"a refused take announced itself: {log}"


def test_giving_the_room_back_never_pings(monkeypatch):
    """A handover TOWARD spot-effects is a give-back, not a take. There is
    no pre-take state of ours to photograph, and River's own restore owns
    that end — announcing one would ask her to snapshot a room we are in the
    middle of handing over."""
    log: list[str] = []
    _logging_ping(log, monkeypatch)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    record = _run(handover_mod.run_handover(lo.SPOT_EFFECTS, _sides(log),
                                            grace_s=0))
    assert record.owner == lo.SPOT_EFFECTS
    assert "ping" not in log, f"a give-back announced a take: {log}"


def test_a_refused_handover_never_announces(monkeypatch):
    """The readiness gate refuses BEFORE the record moves and before any
    quiesce — the room stays untouched under its current owner. Announcing a
    take that will not happen would make River snapshot and restore for
    nothing, and would spend the settle on a no-op."""
    log: list[str] = []
    _logging_ping(log, monkeypatch)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))
    sides = _sides(log)

    async def problems():
        log.append("spectra:readiness")
        return ["the fx-live config is missing"]
    sides[lo.SPECTRA].readiness_problems = problems

    with pytest.raises(handover_mod.HandoverRefused):
        _run(handover_mod.run_handover(lo.SPECTRA, sides, grace_s=0))
    assert "ping" not in log, f"a refused handover announced a take: {log}"
    assert lo.load().owner == lo.SPOT_EFFECTS


# ── 2. THE SETTLE sits BETWEEN the ping and the take ───────────────────────

def test_the_settle_happens_between_the_ping_and_the_take(monkeypatch):
    """River's watch needs a window in which the room is still as SPECTRA
    found it. The wait is the configured duration and it is spent AFTER the
    POST and BEFORE the first write — measured by ordering, not by a clock,
    so the spec costs nothing in wall time."""
    log: list[str] = []
    slept: list[float] = []
    _configured(monkeypatch, settle_ms=2500)

    async def sleep(seconds):
        log.append(f"settle:{seconds}")
        slept.append(seconds)

    def handler(request):
        log.append("posted")
        return httpx.Response(200, json=RIVER_OK)

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client, sleep=sleep)

    result = _run(main())
    assert result.status == pretake_ping.STATUS_SENT
    assert log == ["posted", "settle:2.5"], log
    assert result.settled_ms == 2500


def test_the_settle_default_and_its_clamp(monkeypatch):
    """The default is the shipped 1.5s; a malformed value falls back to it
    and an absurd one is clamped, because this number sits on the critical
    path of taking his room and a typo must not park it."""
    assert config.pretake_settle_ms() == config.PRETAKE_SETTLE_MS_DEFAULT
    monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", "not-a-number")
    assert config.pretake_settle_ms() == config.PRETAKE_SETTLE_MS_DEFAULT
    monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", "999999")
    assert config.pretake_settle_ms() == config.PRETAKE_SETTLE_MS_MAX
    monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", "-5")
    assert config.pretake_settle_ms() == 0
    monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", "0")
    assert config.pretake_settle_ms() == 0


def test_a_zero_settle_sends_and_does_not_wait(monkeypatch):
    """Zero is legal and means "announce, do not wait" — the knob's own way
    of saying River's watch is fast enough, without turning the ping off."""
    slept: list[float] = []
    _configured(monkeypatch, settle_ms=0)

    async def sleep(seconds):
        slept.append(seconds)

    async def main():
        async with _client(_ok()) as client:
            return await pretake_ping.before_take(client=client, sleep=sleep)

    assert _run(main()).status == pretake_ping.STATUS_SENT
    assert slept == []


# ── 3. FAIL-SOFT — it can delay a take, it can never refuse one ────────────

@pytest.mark.parametrize("code", [201, 204, 301, 401, 404, 500, 503])
def test_a_non_200_is_reported_and_the_take_proceeds(monkeypatch, code):
    """SUCCESS IS 200, HER WORD — not "any 2xx". A 201 or a 204 from
    something that is not her endpoint must never read as a captured
    snapshot, which is why the check is equality and not a range."""
    _configured(monkeypatch, settle_ms=0)

    def handler(request):
        return httpx.Response(code, json={"error": "no"})

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client)

    result = _run(main())
    assert result.status == pretake_ping.STATUS_FAILED
    assert result.http_status == code
    assert str(code) in result.detail
    assert result.configured is True


def test_an_unreachable_endpoint_is_reported_and_never_raises(monkeypatch):
    _configured(monkeypatch, settle_ms=0)

    def handler(request):
        raise httpx.ConnectError("connection refused")

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client)

    result = _run(main())
    assert result.status == pretake_ping.STATUS_FAILED
    assert result.http_status is None
    assert "ConnectError" in result.detail


def test_a_failed_ping_still_settles(monkeypatch):
    """A refused or timed-out POST MAY STILL HAVE ARRIVED — a read timeout
    says nothing about whether River received the request and started her
    scene. Skipping the settle on a failure would race the one snapshot this
    exists to protect, to save a second and a half."""
    slept: list[float] = []
    _configured(monkeypatch, settle_ms=1200)

    def handler(request):
        raise httpx.ReadTimeout("she did not answer in time")

    async def sleep(seconds):
        slept.append(seconds)

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client, sleep=sleep)

    result = _run(main())
    assert result.status == pretake_ping.STATUS_FAILED
    assert slept == [1.2], "a failed ping skipped the settle and raced River"
    assert result.settled_ms == 1200


def test_a_failed_ping_does_not_stop_the_interactive_take(monkeypatch):
    """THE HEADLINE FAIL-SOFT PROPERTY. River's endpoint being down is
    River's business; it may never be the reason SPECTRA cannot take his
    room. The handover commits and the outcome is on the record."""
    log: list[str] = []
    _configured(monkeypatch, settle_ms=0)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))

    async def post(url, room_id, at_ms, *, client=None):
        log.append("ping")
        return pretake_ping._Answer(
            pretake_ping.STATUS_FAILED, None,
            "River's pre-take endpoint could not be reached (ConnectError) "
            "— her snapshot watch was not told this take was starting")
    monkeypatch.setattr(pretake_ping, "_post", post)

    record = _run(handover_mod.run_handover(lo.SPECTRA, _sides(log),
                                            grace_s=0))
    assert record.owner == lo.SPECTRA, "a down River endpoint refused a take"
    assert log.index("ping") < _first_write(log)
    assert pretake_ping.last().status == pretake_ping.STATUS_FAILED


def test_a_failed_ping_does_not_stop_the_night_take(monkeypatch, tmp_path):
    _configured(monkeypatch, settle_ms=0)
    monkeypatch.setattr(night_take.scfg, "NIGHT_TAKE_FILE",
                        tmp_path / "night-take.json")
    lo._save(lo.OwnershipRecord(owner=lo.RELEASED))

    async def post(url, room_id, at_ms, *, client=None):
        return pretake_ping._Answer(pretake_ping.STATUS_FAILED, 500,
                                    "she answered 500")
    monkeypatch.setattr(pretake_ping, "_post", post)

    async def handover(to_world, sides, *, quiet=False, pretake=True, **kw):
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()

    result = _run(night_take.take_room("night-1", sides={},
                                       run_handover=handover))
    assert result.took is True, "a down River endpoint declined a night"
    assert result.pretake["status"] == pretake_ping.STATUS_FAILED
    assert result.as_dict()["pretake"]["http_status"] == 500


# ── 4. INERT when the URL is unset — the shipped state ─────────────────────

def test_unconfigured_sends_nothing_and_waits_for_nothing():
    """PROVEN, NOT CLAIMED. No request is possible (a client that raises on
    ANY call is handed in) and no sleep is possible (a sleep that raises is
    handed in) — so the inert path is asserted by construction rather than
    by counting."""
    class _Explode:
        async def post(self, *a, **kw):
            raise AssertionError("the unconfigured path sent a request")

        async def aclose(self):
            pass

    async def sleep(seconds):
        raise AssertionError("the unconfigured path waited")

    result = _run(pretake_ping.before_take(client=_Explode(), sleep=sleep))
    assert result.status == pretake_ping.STATUS_UNCONFIGURED
    assert result.settled_ms == 0
    assert result.configured is False
    assert "SPECTRA_PRETAKE_URL" in result.detail


def test_an_unconfigured_interactive_take_is_byte_identical(monkeypatch):
    """THE INERTNESS PROOF AT THE TAKE, not at the client: the side-call
    sequence of an unconfigured take is compared against the same take with
    the ping call removed from `run_handover` entirely. Equal means this
    feature changed nothing about how his room changes hands."""
    with_feature: list[str] = []
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))
    _run(handover_mod.run_handover(lo.SPECTRA, _sides(with_feature),
                                   grace_s=0))

    without: list[str] = []
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))
    # `pretake=False` is the same code path a take took before this module
    # existed: the call is not made at all.
    _run(handover_mod.run_handover(lo.SPECTRA, _sides(without), grace_s=0,
                                   pretake=False))

    assert with_feature == without, (
        f"an unconfigured take is not the take it used to be:\n"
        f"  with: {with_feature}\n  without: {without}")


def test_an_unconfigured_night_take_is_still_a_take(monkeypatch, tmp_path):
    monkeypatch.setattr(night_take.scfg, "NIGHT_TAKE_FILE",
                        tmp_path / "night-take.json")
    lo._save(lo.OwnershipRecord(owner=lo.RELEASED))

    async def handover(to_world, sides, *, quiet=False, pretake=True, **kw):
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()

    result = _run(night_take.take_room("night-1", sides={},
                                       run_handover=handover))
    assert result.took is True
    assert result.pretake["status"] == pretake_ping.STATUS_UNCONFIGURED
    assert result.pretake["settled_ms"] == 0


def test_unconfigured_is_the_default_on_a_host_that_never_heard_of_it():
    assert pretake_ping.configured() is False
    assert config.pretake_url() == ""


# ── 5. THE WIRE — the payload shape and the bearer ─────────────────────────

def test_the_post_carries_the_contracted_body_and_the_bearer(monkeypatch):
    seen: dict = {}
    _configured(monkeypatch, settle_ms=0)
    before = int(time.time() * 1000)

    async def main():
        async with _client(_ok(seen)) as client:
            return await pretake_ping.before_take(client=client)

    result = _run(main())
    after = int(time.time() * 1000)

    assert seen["method"] == "POST"
    assert seen["url"] == "http://river.invalid/pre-take", (
        "SPECTRA appended a path of its own — the route is River's to name")
    assert seen["auth"] == "Bearer not-the-real-one"
    assert set(seen["body"]) == {"event", "room_id", "at_ms"}, seen["body"]
    assert seen["body"]["event"] == "pre_take"
    assert seen["body"]["room_id"] == pretake_ping.ROOM_ALL
    assert before <= seen["body"]["at_ms"] <= after
    assert result.at_ms == seen["body"]["at_ms"]
    # HER ANSWER IS SURFACED, not reduced to a boolean.
    assert result.status == pretake_ping.STATUS_SENT
    assert result.captured is True
    assert result.elapsed_s == 0.41
    assert result.river_result == "scene created"
    assert result.as_dict()["captured"] is True
    assert result.as_dict()["elapsed_s"] == 0.41


def test_her_answer_is_surfaced_rather_than_reduced(monkeypatch):
    """`captured` and `elapsed_s` reach the take's own reported outcome.
    "River answered and captured in 0.4s" and "River answered and captured
    nothing" are different facts about his room and a status word alone
    cannot hold both."""
    _configured(monkeypatch, settle_ms=0)

    async def main(body):
        async with _client(_ok(body=body)) as client:
            return await pretake_ping.before_take(client=client)

    good = _run(main(RIVER_OK))
    assert (good.status, good.captured, good.elapsed_s) == (
        pretake_ping.STATUS_SENT, True, 0.41)
    assert "0.41" in good.detail


def test_a_200_that_captured_nothing_is_sent_and_still_says_so(monkeypatch):
    """HER CONTRACT NAMES 200 AS SUCCESS and enumerates the failures, so
    inventing a fourth verdict for `captured: false` would be renegotiating
    it. The STATUS follows her word; the DETAIL and the record say what she
    actually reported, so a take with no snapshot behind it is a READ."""
    _configured(monkeypatch, settle_ms=0)
    body = {"captured": False, "elapsed_s": 0.02, "result": "no scene"}

    async def main():
        async with _client(_ok(body=body)) as client:
            return await pretake_ping.before_take(client=client)

    result = _run(main())
    assert result.status == pretake_ping.STATUS_SENT
    assert result.captured is False
    assert "captured" in result.detail.lower()
    assert "NOTHING" in result.detail
    assert result.as_dict()["captured"] is False


def test_a_200_that_does_not_say_is_unconfirmed_never_a_no(monkeypatch):
    """`None` means SHE DID NOT SAY. Rendering that as "she said no" is the
    same class of lie as `witness_unavailable` collapsing onto `clean` — one
    direction invents a failure, the other invents a success."""
    _configured(monkeypatch, settle_ms=0)

    async def main(body):
        async with _client(_ok(body=body)) as client:
            return await pretake_ping.before_take(client=client)

    for body in ({}, {"result": "ok"}, ["not an object"], None):
        result = _run(main(body))
        assert result.status == pretake_ping.STATUS_SENT, body
        assert result.captured is None, body
        assert "unconfirmed" in result.detail, body


def test_a_200_with_a_body_that_is_not_json_still_landed(monkeypatch):
    """The request reached her; only her answer is unreadable. A landed ping
    with an unreadable body is not a failed ping."""
    _configured(monkeypatch, settle_ms=0)

    def handler(request):
        return httpx.Response(200, text="OK")

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client)

    result = _run(main())
    assert result.status == pretake_ping.STATUS_SENT
    assert result.captured is None


def test_the_answer_reading_is_one_function_a_spec_can_drive():
    """Split out from the transport for `witness.parse_rows`' own reason:
    the wire's reading has ONE definition, so a spec cannot pass against a
    second copy that has drifted from what the take actually does."""
    ok = pretake_ping.read_answer(200, RIVER_OK)
    assert ok.status == pretake_ping.STATUS_SENT
    assert (ok.captured, ok.elapsed_s, ok.river_result) == (
        True, 0.41, "scene created")
    for code in (201, 204, 302, 400, 401, 500):
        assert pretake_ping.read_answer(code, RIVER_OK).status == \
            pretake_ping.STATUS_FAILED, code
    # a bool is not an elapsed time, however much `isinstance` would like it
    assert pretake_ping.read_answer(200, {"elapsed_s": True}).elapsed_s is None


def test_the_bearer_accessor_mirrors_the_witness_exactly(monkeypatch):
    """`witness.witness_token()`'s shape, one module over: `os.getenv` at
    CALL TIME, empty when unset, never cached — so rotating the secret is an
    environment edit and a restart, with no module global able to keep
    serving the old one. The file it is loaded from at deploy lives outside
    this repository, exactly as the witness bearer's does."""
    import inspect
    from spectra.services import witness

    assert pretake_ping.pretake_token() == ""
    monkeypatch.setenv("SPECTRA_PRETAKE_TOKEN", "first")
    assert pretake_ping.pretake_token() == "first"
    monkeypatch.setenv("SPECTRA_PRETAKE_TOKEN", "rotated")
    assert pretake_ping.pretake_token() == "rotated", \
        "the bearer was cached — a rotation would not take"
    # the same shape, asserted rather than described
    assert "os.getenv" in inspect.getsource(config.pretake_token)
    assert "os.getenv" in inspect.getsource(witness.witness_token)


def test_the_endpoint_address_is_never_baked_into_the_repository():
    """Her endpoint is on the house network at a DHCP-reachable address, and
    a default here would be the pinned-by-location defect
    `fx/device_identity.py` exists to end one layer down: the day she moves,
    a default would keep announcing takes into an address that no longer
    means anything and every ping would report `failed` for a reason nobody
    would look for in the code.

    Asserted at the BEHAVIOUR — an unconfigured host resolves to nothing at
    all — and then at the source of the resolver itself, so a default cannot
    be reintroduced quietly. The address is recorded in prose in
    `config.pretake_url`'s docstring, which is where a deploy fact belongs."""
    import inspect

    assert config.pretake_url() == ""
    assert pretake_ping.pretake_url() == ""
    body = inspect.getsource(config.pretake_url)
    body = body.split('"""', 2)[2] if body.count('"""') >= 2 else body
    assert "192.168" not in body and "8098" not in body, \
        f"an address was baked into the resolver: {body}"
    assert 'os.getenv("SPECTRA_PRETAKE_URL", "")' in body


def test_the_payload_builder_is_the_same_one_the_take_sends():
    """One definition of the wire shape, so a spec cannot pass against a
    second copy that has drifted from what actually goes out."""
    assert pretake_ping.payload("all", 17) == {
        "event": "pre_take", "room_id": "all", "at_ms": 17}


def test_a_caller_may_name_a_room(monkeypatch):
    """The field is caller-supplied so a future room-scoped take needs no
    wire change and no conversation — both take paths pass ROOM_ALL today
    because a take is of the whole room."""
    seen: dict = {}
    _configured(monkeypatch, settle_ms=0)

    async def main():
        async with _client(_ok(seen)) as client:
            return await pretake_ping.before_take(room_id="living-room",
                                                  client=client)

    assert _run(main()).room_id == "living-room"
    assert seen["body"]["room_id"] == "living-room"


def test_a_missing_token_still_sends_and_names_it(monkeypatch):
    """The inertness gate is the URL ALONE. A missing bearer is a VISIBLE
    401 whose sentence says the token is unset — never a silent skip that
    would look exactly like a host with no River at all."""
    seen: dict = {}
    _configured(monkeypatch, token=None, settle_ms=0)
    monkeypatch.delenv("SPECTRA_PRETAKE_TOKEN", raising=False)

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(401)

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client)

    result = _run(main())
    assert seen["auth"] is None
    assert result.status == pretake_ping.STATUS_FAILED
    assert "SPECTRA_PRETAKE_TOKEN" in result.detail


def test_nothing_here_ever_logs_the_token(monkeypatch, caplog):
    """`witness.py`'s rule, kept on the write side: the token and the URL's
    own credentials never reach a log line, only the exception class."""
    _configured(monkeypatch, url="http://user:secret@river.invalid/p",
                token="super-secret-bearer", settle_ms=0)

    def handler(request):
        raise httpx.ConnectError("nope")

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.before_take(client=client)

    with caplog.at_level("DEBUG"):
        result = _run(main())
    text = result.detail + " " + " ".join(r.getMessage() for r in caplog.records)
    assert "super-secret-bearer" not in text
    assert "secret@" not in text


# ── the reporting surface — visible, never fatal ───────────────────────────

def _armed_route(monkeypatch, sides):
    """The armed handover route pointed at recording sides. Nothing here
    reaches a device, a service or a systemctl."""
    from spectra.api import ownership as ownership_api

    monkeypatch.setenv("SPECTRA_HANDOVER_ARMED", "1")
    monkeypatch.setattr(handover_mod, "production_sides",
                        lambda **kw: sides)
    monkeypatch.setattr(ownership_api.handover_svc, "production_sides",
                        lambda **kw: sides, raising=False)
    return ownership_api


def test_the_armed_route_reports_the_ping_on_a_committed_take(monkeypatch):
    """`run_handover` returns an `OwnershipRecord` and has nowhere to hand
    the outcome back, so the route reads `pretake_ping.last()` — exactly the
    way it reads `activation_report.current()` for a partial take."""
    from spectra.api.ownership import HandoverRequest, post_handover

    log: list[str] = []
    _configured(monkeypatch, settle_ms=0)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))
    sides = _sides(log)

    async def post(url, room_id, at_ms, *, client=None):
        return pretake_ping.read_answer(200, RIVER_OK)
    monkeypatch.setattr(pretake_ping, "_post", post)
    _armed_route(monkeypatch, sides)

    async def main():
        return await post_handover(HandoverRequest(to=lo.SPECTRA))

    body = _run(main())
    assert body["result"] == "committed"
    assert body["pretake"]["status"] == pretake_ping.STATUS_SENT
    assert body["pretake"]["captured"] is True
    assert body["pretake"]["elapsed_s"] == 0.41


def test_a_give_back_never_wears_a_previous_takes_ping(monkeypatch):
    """`last()` describes the LAST announcement, so reporting it for a
    direction that does not announce would put a stale, unrelated status on
    a give-back. The route asks only for a take."""
    from spectra.api.ownership import HandoverRequest, post_handover

    log: list[str] = []
    pretake_ping._last = pretake_ping.PingResult(
        status=pretake_ping.STATUS_SENT, room_id=pretake_ping.ROOM_ALL)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    _armed_route(monkeypatch, _sides(log))

    async def main():
        return await post_handover(HandoverRequest(to=lo.SPOT_EFFECTS))

    body = _run(main())
    assert body["result"] == "committed"
    assert "pretake" not in body, \
        "a give-back wore a previous take's announcement"


def test_a_failed_take_still_reports_the_ping_it_sent(monkeypatch):
    """The ping fires ahead of quiesce, so a take that then fails HAS
    announced itself and River may be holding a snapshot of a room that
    never changed hands. She restores it either way; saying so is what stops
    that from being a silent loose end."""
    from spectra.api.ownership import HandoverRequest, post_handover
    import json as _json

    log: list[str] = []
    _configured(monkeypatch, settle_ms=0)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))
    sides = _sides(log)
    sides[lo.SPECTRA] = _RecordingSide(lo.SPECTRA, log, active=False)

    async def post(url, room_id, at_ms, *, client=None):
        return pretake_ping.read_answer(200, RIVER_OK)
    monkeypatch.setattr(pretake_ping, "_post", post)
    _armed_route(monkeypatch, sides)

    async def main():
        return await post_handover(HandoverRequest(to=lo.SPECTRA))

    resp = _run(main())
    body = _json.loads(bytes(resp.body))
    assert resp.status_code == 502
    assert body["result"] == "failed-landed-single-owner"
    assert body["pretake"]["status"] == pretake_ping.STATUS_SENT
    assert lo.load().owner == lo.SPOT_EFFECTS, "the take did not land back"


def test_a_refused_handover_reports_no_ping_because_it_sent_none(monkeypatch):
    """The two refusal paths sit BEFORE the announcement, so there is
    nothing to report and nothing was asked of River."""
    from spectra.api.ownership import HandoverRequest, post_handover
    import json as _json

    log: list[str] = []
    _configured(monkeypatch, settle_ms=0)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))
    sides = _sides(log)

    async def problems():
        return ["the fx-live config is missing"]
    sides[lo.SPECTRA].readiness_problems = problems

    async def post(url, room_id, at_ms, *, client=None):
        raise AssertionError("a refused handover announced a take")
    monkeypatch.setattr(pretake_ping, "_post", post)
    _armed_route(monkeypatch, sides)

    async def main():
        return await post_handover(HandoverRequest(to=lo.SPECTRA))

    resp = _run(main())
    body = _json.loads(bytes(resp.body))
    assert resp.status_code == 412
    assert "pretake" not in body


# ── the boundary this module does not cross ────────────────────────────────

def test_this_side_still_has_no_home_assistant_path():
    """`witness.py` states it as a prohibition and this is its mirror image:
    the ONLY thing here is a POST to a River service. No entity is named, no
    HA API is reached, and THE SCONCE MAINS RULE is untouchable from here."""
    body = Path(pretake_ping.__file__).read_text().split('"""', 2)[2]
    lowered = body.lower()
    for forbidden in ("light.", "switch.", "/api/services",
                      "homeassistant", "home-assistant", "hass",
                      "scene.turn_on", "scene.create"):
        assert forbidden not in lowered, \
            f"the pre-take ping reached for {forbidden!r} — the house " \
            f"lights are Home Assistant's, and River's alone to drive"
