"""THE RELEASE PING — announced the moment the room is actually let go,
never able to change whether it was.

NO NETWORK, NO LIVE ROOM, NO HOME ASSISTANT anywhere in this file.
`httpx.MockTransport` stands in for River's service exactly as
`tests/test_pretake_ping.py` does for the other edge of the same boundary,
every release step is a fake that records WHEN it was called against one
shared log, and the ownership record is repointed into `tmp_path`. The
deploy-time bearer is never read by anything here.

THE PROOFS, in the order the brief puts them:

  1. THE ORDERING — the ping lands strictly AFTER the Hue fade, which is the
     step that actually takes his bulbs down and therefore the first instant
     "released" is a true statement. It also lands BEFORE the live stack is
     torn down, so River's bridge-direct restore has the room while SPECTRA
     finishes letting go behind it. The ordering instrument has its own RED
     control, `test_pretake_ping.py::test_the_ordering_instrument_
     discriminates`' discipline: an assertion that cannot fail is decoration.
  2. IT FIRES WHETHER THE FADE WORKED OR NOT. A fade that failed is the case
     where his room needs her restore most; gating the telling on it would
     withhold the announcement from exactly the release that needs it.
  3. FAIL-SOFT, AND STRONGER THAN THE PRE-TAKE'S. Non-200, unreachable,
     timeout: every one is REPORTED and none of them raises, and — the
     headline property — a room that genuinely released still reports
     `verified=True` with the ping on the side. Whether the room let go is a
     question about his fixtures; whether River heard is a question about
     her watch, and collapsing the two would make a dark room read as a
     failed release.
  4. INERT when `SPECTRA_PRETAKE_URL` is unset: zero requests, and a release
     whose whole step sequence is byte-identical to the same release with
     the announcement removed entirely.
  5. A RELEASED → RELEASED NO-OP ANNOUNCES NOTHING. Nothing was let go, so
     there is nothing to say, and `release_ping` is empty rather than a
     fabricated "sent".
  6. THE WIRE — `{"event": "released", "room_id": "all", "at_ms": <int>}`,
     the bearer, and the SAME URL the pre-take uses, asserted against the
     real request the real client built.
  7. THE PRE-TAKE IS UNTOUCHED — its own wording is byte-identical, its
     `last()` slot cannot be overwritten by a release, and the shared
     builders still have exactly one definition each.
  8. THE SENTENCE A PERSON READS AT 2AM, and the API surface. A failed
     announcement must not wear the device steps' own consequence ("this
     device may still be lit"), which would send whoever read it to look at
     a fixture that is fine; and the route reports whether River was told on
     BOTH the 200 and the 207, beside the verification rather than inside
     it.
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
from spectra.services import pretake_ping
from spectra.services import release as release_svc


def _run(coro):
    return asyncio.run(coro)


_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """UNCONFIGURED IS THE DEFAULT HERE, exactly as it is on his host — a
    spec that wants River present has to say so. The ownership record is
    repointed and restored, `test_release.py`'s own rule: it is a module
    global and a leaked HANDING_OVER record poisons every later file."""
    monkeypatch.delenv("SPECTRA_PRETAKE_URL", raising=False)
    monkeypatch.delenv("SPECTRA_PRETAKE_TOKEN", raising=False)
    monkeypatch.delenv("SPECTRA_PRETAKE_SETTLE_MS", raising=False)
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    pretake_ping.reset()
    yield
    pretake_ping.reset()
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


def _configured(monkeypatch, *, url="http://river.invalid/pretake",
                token="not-the-real-one"):
    monkeypatch.setenv("SPECTRA_PRETAKE_URL", url)
    if token is not None:
        monkeypatch.setenv("SPECTRA_PRETAKE_TOKEN", token)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


#: RIVER'S OWN ANSWER SHAPE, the one `tests/test_pretake_ping.py` records
#: against her live endpoint. The release event rides the same contract.
RIVER_OK = {"captured": True, "elapsed_s": 0.41, "result": "restored"}


def _ledfx_unit_stopped(monkeypatch) -> None:
    """Verification's cheap path (`tests/test_release.py`'s helper): the
    external LedFX unit reports not running, so `_verify_released()` never
    re-reads virtuals over HTTP."""
    from spectra.services import handover as handover_svc

    async def fake_systemctl(*args):
        return 0, "inactive"

    monkeypatch.setattr(handover_svc, "_systemctl", fake_systemctl)


def _fake_release_steps(monkeypatch, log, *, still_on=None, fade_raises=False):
    """Every step of a release replaced by one that writes its name into a
    shared, ordered log — which is where the ordering assertions actually
    live. Nothing here reaches a device, a bridge or a service. The
    announcement itself is deliberately NOT faked: it is the thing under
    test, and it is driven against `httpx.MockTransport` below."""

    async def fake_fade():
        log.append("fade")
        if fade_raises:
            raise RuntimeError("the bridge did not answer")
        return {"devices": ["hue-lights"], "failed": [],
                "still_on": list(still_on or [])}

    async def fake_devices():
        log.append("spectra_devices")

    async def fake_ledfx():
        log.append("ledfx_virtuals")
        return []

    monkeypatch.setattr(release_svc, "_fade_hue_before_release", fake_fade)
    monkeypatch.setattr(release_svc, "_release_spectra_devices", fake_devices)
    monkeypatch.setattr(release_svc, "_release_ledfx_virtuals", fake_ledfx)
    _ledfx_unit_stopped(monkeypatch)


def _river(monkeypatch, log, handler=None, *, seen=None):
    """The announcement wired to a real `pretake_ping.after_release` over a
    mock transport, logging WHEN it went out. The production wrapper is what
    is replaced, not the module: `after_release` itself runs for real, so
    the payload, the bearer and the fail-soft behaviour under test are the
    shipped ones."""
    def _default(request):
        return httpx.Response(200, json=RIVER_OK)

    inner = handler or _default

    def recording(request):
        log.append("ping")
        if seen is not None:
            import json as _json
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = _json.loads(request.content.decode())
        return inner(request)

    async def announce():
        async with _client(recording) as client:
            return await pretake_ping.after_release(client=client)

    monkeypatch.setattr(release_svc, "_announce_release", announce)


def _fade_index(log):
    """The index of the step that actually lets his bulbs go. Announcing
    before it would be announcing a release that has not happened."""
    return log.index("fade")


# ── 1. THE ORDERING — after the fade, before the teardown ──────────────────

def test_the_release_announces_itself_right_after_the_hue_fade(monkeypatch):
    """THE CORRECTNESS PROPERTY. The fade freezes the entertainment stream
    and takes the bulbs down; only then is "released" a true statement, and
    only then does River's bridge-direct restore have an uncontested room to
    write into. Announcing earlier would ask her to restore over a stream
    still painting his fixtures."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)
    _river(monkeypatch, log)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    result = _run(release_svc.release_room("spec: ordering"))

    assert result.record.owner == lo.RELEASED
    assert "ping" in log, "the release was never announced to River"
    assert log == ["fade", "ping", "spectra_devices", "ledfx_virtuals"], log
    assert _fade_index(log) < log.index("ping"), (
        f"River was told the room was released before it was: {log}")
    assert log.index("ping") < log.index("spectra_devices"), (
        "the announcement waited for the whole stack to tear down — her "
        "restore should have the room while SPECTRA finishes letting go")
    assert result.release_ping["status"] == pretake_ping.STATUS_SENT


def test_the_ordering_instrument_discriminates():
    """THE INSTRUMENT'S OWN CONTROL — the ordering assertion has to be able
    to fail, or the test above is decoration.

    The source-level control was run by hand and is recorded here so nobody
    has to trust the assertion alone: moving the `_announce_release` call in
    `release.release_room` to ABOVE the fade turns
    `test_the_release_announces_itself_right_after_the_hue_fade` RED, and
    removing it entirely turns that test and
    `test_the_wire_carries_the_released_event_and_the_bearer` RED — verified
    2026-09-07, on this rig, before the code was restored."""
    early = ["ping", "fade", "spectra_devices"]
    with pytest.raises(AssertionError):
        assert _fade_index(early) < early.index("ping")
    late = ["fade", "spectra_devices", "ledfx_virtuals", "ping"]
    with pytest.raises(AssertionError):
        assert late.index("ping") < late.index("spectra_devices")
    good = ["fade", "ping", "spectra_devices"]
    assert _fade_index(good) < good.index("ping") < good.index(
        "spectra_devices")


# ── 2. IT FIRES WHETHER THE FADE WORKED OR NOT ─────────────────────────────

def test_a_fade_that_raised_still_announces_the_release(monkeypatch):
    """A fade that blew up is the case where his room needs River's restore
    MOST — the bulbs may be sitting on SPECTRA's last frame with nothing
    else coming to take them off it. Gating the telling on the fade's own
    success would withhold it from exactly that release."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log, fade_raises=True)
    _river(monkeypatch, log)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    result = _run(release_svc.release_room("spec: fade failed"))

    assert result.record.owner == lo.RELEASED
    assert log == ["fade", "ping", "spectra_devices", "ledfx_virtuals"], log
    assert result.release_ping["status"] == pretake_ping.STATUS_SENT


def test_a_bulb_that_stayed_on_still_announces_the_release(monkeypatch):
    """The same rule one layer down: the fade's own read-back found a light
    that never confirmed off. The release is still a release, River still
    restores, and the unverified verdict is reported beside the ping rather
    than instead of it."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log, still_on=["Standing Lamp"])
    _river(monkeypatch, log)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    result = _run(release_svc.release_room("spec: a bulb stayed on"))

    assert result.verified is False
    assert any("Standing Lamp" in p for p in result.problems)
    assert result.release_ping["status"] == pretake_ping.STATUS_SENT
    assert not any("River" in p or "ping" in p for p in result.problems), (
        "the announcement leaked into the release's own problem list")


# ── 3. FAIL-SOFT — it can never make a real release read as a failed one ───

@pytest.mark.parametrize("code", [201, 204, 301, 401, 404, 500, 503])
def test_a_non_200_is_reported_and_the_release_still_stands(monkeypatch, code):
    """SUCCESS IS 200, HER WORD, on this event as on the other one."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)
    _river(monkeypatch, log,
           lambda request: httpx.Response(code, json={"error": "no"}))
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    result = _run(release_svc.release_room(f"spec: she answered {code}"))

    assert result.record.owner == lo.RELEASED
    assert result.verified is True, (
        "a River outage made a genuinely released room read as unverified")
    assert result.problems == []
    assert result.release_ping["status"] == pretake_ping.STATUS_FAILED
    assert result.release_ping["http_status"] == code
    assert "release" in result.release_ping["detail"]


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout("she did not answer in time"),
])
def test_an_unreachable_river_never_raises_and_never_unverifies(monkeypatch,
                                                                exc):
    """THE HEADLINE FAIL-SOFT PROPERTY, and it is stronger here than on the
    pre-take: the release has ALREADY HAPPENED by the time this POST goes
    out, so a ping that did not land cannot change anything about it. His
    room is dark; saying otherwise because River's watch is down would be
    the report lying about his fixtures."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)

    def handler(request):
        raise exc

    _river(monkeypatch, log, handler)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    result = _run(release_svc.release_room("spec: River is down"))

    assert result.record.owner == lo.RELEASED
    assert result.verified is True
    assert result.problems == []
    assert result.release_ping["status"] == pretake_ping.STATUS_FAILED
    assert result.release_ping["http_status"] is None
    assert type(exc).__name__ in result.release_ping["detail"]
    # and the whole rest of the release ran, in order, behind it
    assert log == ["fade", "ping", "spectra_devices", "ledfx_virtuals"], log


def test_an_announcement_that_raises_outright_cannot_stop_a_release(
        monkeypatch):
    """`after_release` never raises, which is why nothing above has to catch
    it — but `release_room` still runs it at the same `_best_effort`
    altitude as every other cleanup step, so a future regression there costs
    a missing field and never his panic handle."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)

    async def explode():
        log.append("ping")
        raise RuntimeError("a regression inside the announcement")

    monkeypatch.setattr(release_svc, "_announce_release", explode)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    result = _run(release_svc.release_room("spec: the ping itself broke"))

    assert result.record.owner == lo.RELEASED
    assert result.verified is True
    assert result.release_ping == {}
    assert log == ["fade", "ping", "spectra_devices", "ledfx_virtuals"], log


def test_after_release_itself_never_raises(monkeypatch):
    """The property the wrapper above relies on, asserted directly against
    every failure shape River's endpoint can produce."""
    _configured(monkeypatch)

    def boom(request):
        raise httpx.ConnectError("nope")

    async def main(handler):
        async with _client(handler) as client:
            return await pretake_ping.after_release(client=client)

    for handler in (boom,
                    lambda r: httpx.Response(500),
                    lambda r: httpx.Response(200, text="not json"),
                    lambda r: httpx.Response(200, json=RIVER_OK)):
        result = _run(main(handler))
        assert isinstance(result, pretake_ping.PingResult)
        assert result.status in (pretake_ping.STATUS_SENT,
                                 pretake_ping.STATUS_FAILED)


# ── 4. INERT when the URL is unset — the shipped state ─────────────────────

def test_unconfigured_sends_nothing_at_all():
    """PROVEN BY CONSTRUCTION, not by counting: a client that raises on ANY
    call is handed in, so the inert path cannot have sent a request."""
    class _Explode:
        async def post(self, *a, **kw):
            raise AssertionError("the unconfigured path sent a request")

        async def aclose(self):
            pass

    result = _run(pretake_ping.after_release(client=_Explode()))
    assert result.status == pretake_ping.STATUS_UNCONFIGURED
    assert result.configured is False
    assert result.settled_ms == 0
    assert "SPECTRA_PRETAKE_URL" in result.detail
    assert "release" in result.detail


def test_an_unconfigured_release_is_byte_identical(monkeypatch, tmp_path):
    """THE INERTNESS PROOF AT THE RELEASE, not at the client: an
    unconfigured release is run A/B against one whose announcement has been
    replaced by the literal pre-feature shape — no call, nothing returned —
    and their step sequences and outcomes are compared. Equal means this
    feature changed nothing about how his room is let go on a host that has
    never heard of River, which is every host until the env is provisioned.

    The real `_announce_release` runs on the A side: the inertness under
    test is `after_release`'s own, not a fake standing in for it."""
    with_feature: list[str] = []
    _fake_release_steps(monkeypatch, with_feature)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    a = _run(release_svc.release_room("spec: unconfigured"))

    without: list[str] = []
    _fake_release_steps(monkeypatch, without)

    async def never_announced():
        return None                      # the pre-feature shape, exactly

    monkeypatch.setattr(release_svc, "_announce_release", never_announced)
    lo.OWNERSHIP_FILE = tmp_path / "ownership-2.json"
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    b = _run(release_svc.release_room("spec: unconfigured, again"))

    assert with_feature == without == ["fade", "spectra_devices",
                                       "ledfx_virtuals"], with_feature
    assert (a.verified, a.problems, a.record.owner) == \
           (b.verified, b.problems, b.record.owner)
    assert a.verified is True and a.problems == []
    # the ONE difference, and it is a read on the record, never a step
    assert a.release_ping["status"] == pretake_ping.STATUS_UNCONFIGURED
    assert b.release_ping == {}


def test_unconfigured_is_the_default_on_a_host_that_never_heard_of_river():
    from spectra import config
    assert pretake_ping.configured() is False
    assert config.pretake_url() == ""


# ── 5. A RELEASED → RELEASED NO-OP ANNOUNCES NOTHING ───────────────────────

def test_an_already_released_room_is_never_announced(monkeypatch):
    """Nothing was let go, so there is nothing to say. A second press must
    not fire a restore in his house for a room that has been dark all along
    — and `release_ping` says so by being EMPTY rather than by carrying a
    fabricated status nobody sent."""
    log: list[str] = []
    _configured(monkeypatch)
    lo.release("first press")
    _fake_release_steps(monkeypatch, log)
    _river(monkeypatch, log)

    result = _run(release_svc.release_room("second press"))

    assert result.record.owner == lo.RELEASED
    assert result.verified is True
    assert log == [], f"an already-released room announced itself: {log}"
    assert result.release_ping == {}
    assert pretake_ping.last_release() is None


def test_a_refused_mid_handover_release_announces_nothing(monkeypatch):
    """`light_ownership.release` refuses outright while a handover is in
    flight, before any step runs — so nothing was released and nothing may
    be announced."""
    log: list[str] = []
    _configured(monkeypatch)
    lo.begin_handover(lo.SPECTRA)
    _fake_release_steps(monkeypatch, log)
    _river(monkeypatch, log)

    with pytest.raises(lo.OwnershipError):
        _run(release_svc.release_room("spec: mid-handover"))
    assert log == [], f"a refused release announced itself: {log}"


# ── 6. THE WIRE ────────────────────────────────────────────────────────────

def test_the_wire_carries_the_released_event_and_the_bearer(monkeypatch):
    """THE PAYLOAD FIRSTMATE HAS TO HAND RIVER, asserted against the real
    request the real client built — same URL, same bearer, one field
    different."""
    log: list[str] = []
    seen: dict = {}
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)
    _river(monkeypatch, log, seen=seen)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    before = int(time.time() * 1000)

    result = _run(release_svc.release_room("spec: the wire"))
    after = int(time.time() * 1000)

    assert seen["method"] == "POST"
    assert seen["url"] == "http://river.invalid/pretake", (
        "SPECTRA appended a path of its own — the route is River's to name, "
        "and the release rides the endpoint she already published")
    assert seen["auth"] == "Bearer not-the-real-one"
    assert set(seen["body"]) == {"event", "room_id", "at_ms"}, seen["body"]
    assert seen["body"]["event"] == "released"
    assert seen["body"]["room_id"] == "all"
    assert isinstance(seen["body"]["at_ms"], int)
    assert before <= seen["body"]["at_ms"] <= after
    assert result.release_ping["at_ms"] == seen["body"]["at_ms"]
    # HER ANSWER IS SURFACED, not reduced to a boolean.
    assert result.release_ping["captured"] is True
    assert result.release_ping["elapsed_s"] == 0.41
    assert result.release_ping["river_result"] == "restored"


def test_the_payload_builder_is_the_same_one_the_release_sends():
    """One definition of the wire shape for BOTH events, so a spec cannot
    pass against a second copy that has drifted from what goes out."""
    assert pretake_ping.payload("all", 17, pretake_ping.EVENT_RELEASED) == {
        "event": "released", "room_id": "all", "at_ms": 17}
    assert pretake_ping.payload("all", 17) == {
        "event": "pre_take", "room_id": "all", "at_ms": 17}


def test_a_caller_may_name_a_room_on_the_release_too(monkeypatch):
    seen: dict = {}
    _configured(monkeypatch)

    def handler(request):
        import json as _json
        seen["body"] = _json.loads(request.content.decode())
        return httpx.Response(200, json=RIVER_OK)

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.after_release(room_id="living-room",
                                                    client=client)

    assert _run(main()).room_id == "living-room"
    assert seen["body"]["room_id"] == "living-room"


def test_the_release_never_settles(monkeypatch):
    """The pre-take waits so River can read a room about to change; here the
    change is done. `after_release` has no `sleep` seam at all — asserted at
    the signature, so the wait cannot be reintroduced without this going
    red — and a configured settle is spent on the take path only."""
    import inspect

    monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", "5000")
    _configured(monkeypatch)
    assert "sleep" not in inspect.signature(
        pretake_ping.after_release).parameters
    assert "sleep" in inspect.signature(pretake_ping.before_take).parameters

    async def main():
        async with _client(lambda r: httpx.Response(200, json=RIVER_OK)) \
                as client:
            return await pretake_ping.after_release(client=client)

    started = time.monotonic()
    result = _run(main())
    assert result.settled_ms == 0
    assert time.monotonic() - started < 1.0, "the release ping waited"


# ── 7. THE PRE-TAKE IS UNTOUCHED ───────────────────────────────────────────

def test_a_release_never_overwrites_the_last_take(monkeypatch):
    """`last()`'s contract is "the last TAKE" and the armed handover route
    reads it. One shared slot would let a release land there and put a
    release's words on a take's own response, so the two edges of the room
    keep one slot each."""
    _configured(monkeypatch)
    taken = pretake_ping.PingResult(status=pretake_ping.STATUS_SENT,
                                    room_id=pretake_ping.ROOM_ALL,
                                    detail="a take's own words")
    pretake_ping._last = taken

    async def main():
        async with _client(lambda r: httpx.Response(200, json=RIVER_OK)) \
                as client:
            return await pretake_ping.after_release(client=client)

    released = _run(main())
    assert pretake_ping.last() is taken, \
        "a release overwrote the last take's announcement"
    assert pretake_ping.last_release() is released
    assert pretake_ping.reset() is None
    assert pretake_ping.last() is None and pretake_ping.last_release() is None


def test_the_pre_take_wording_is_byte_identical(monkeypatch):
    """The wording table is a refactor of WHERE these sentences live, never
    of what they say. Pinned verbatim, because `tests/test_pretake_ping.py`
    asserts fragments of them and River's own operators read them."""
    w = pretake_ping.words(pretake_ping.EVENT_PRE_TAKE)
    assert w.endpoint == "River's pre-take endpoint"
    assert w.not_told == \
        "her snapshot watch was not told this take was starting"
    assert w.acted == "River captured the pre-take state"
    assert w.did_nothing == (
        "River answered 200 and reported that she captured NOTHING — this "
        "take has no pre-take snapshot behind it")
    assert w.unconfirmed == (
        "River's pre-take endpoint answered 200 without saying whether it "
        "captured — the ping landed, the snapshot is unconfirmed")
    assert w.unconfigured == (
        "the pre-take ping is not configured on this host "
        "(SPECTRA_PRETAKE_URL), so River's snapshot watch was not told this "
        "take was starting")
    # and the pre-take reading is still reached with no event argument
    assert pretake_ping.read_answer(500, None).detail == (
        "River's pre-take endpoint answered 500 rather than 200 — her "
        "snapshot watch was not told this take was starting")


def test_the_release_wording_speaks_about_a_release(monkeypatch):
    """A release wearing the pre-take's sentences would send whoever read it
    to look at the wrong end of the evening — "her snapshot watch was not
    told this take was starting" is a lie about a release."""
    detail = pretake_ping.read_answer(503, None,
                                      pretake_ping.EVENT_RELEASED).detail
    assert "release" in detail and "restore watch" in detail
    assert "take" not in detail and "snapshot" not in detail
    none = pretake_ping.read_answer(200, {},
                                    pretake_ping.EVENT_RELEASED).detail
    assert "restore is unconfirmed" in none
    nothing = pretake_ping.read_answer(200, {"captured": False},
                                       pretake_ping.EVENT_RELEASED).detail
    assert "NOTHING" in nothing and "restore" in nothing


def test_an_unknown_event_falls_back_rather_than_raising():
    """This module's whole posture is that it can never be the reason a take
    or a release fails, and that has to include a caller passing an event
    word nobody has written sentences for yet."""
    assert pretake_ping.words("something-new") is \
        pretake_ping.words(pretake_ping.EVENT_PRE_TAKE)
    assert pretake_ping.read_answer(500, None, "something-new").status == \
        pretake_ping.STATUS_FAILED


def test_the_event_vocabulary_is_closed_and_small():
    """`night_take.EVENT_TAKEN`'s discipline: River renders these words, and
    a vocabulary that grows quietly is a contract that breaks quietly."""
    assert set(pretake_ping.WORDS) == {"pre_take", "released"}
    assert pretake_ping.EVENT_RELEASED == "released"


# ── the failure sentence, and the API surface ──────────────────────────────

def test_a_failed_announcement_never_blames_a_fixture(monkeypatch, caplog):
    """`_best_effort`'s default sentence is "this device may still be lit
    until its own timeout" — TRUE of a fade or a device teardown, and a LIE
    about a POST to River that would send whoever read it at 2am to look at
    a fixture that is perfectly fine. Every step here says what ITS OWN
    failure costs."""
    log: list[str] = []
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)

    async def explode():
        raise RuntimeError("a regression inside the announcement")

    monkeypatch.setattr(release_svc, "_announce_release", explode)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    with caplog.at_level("ERROR"):
        result = _run(release_svc.release_room("spec: the sentence"))

    said = [r.getMessage() for r in caplog.records
            if "river release ping" in r.getMessage()]
    assert said, "a failed announcement said nothing at all"
    assert "may still be lit" not in said[0], said[0]
    assert "restore watch" in said[0] and "IS released" in said[0], said[0]
    assert result.verified is True


def test_a_failed_fade_still_says_the_fixture_may_be_lit(monkeypatch, caplog):
    """The other half of the same rule, so the fix above cannot have been a
    blanket reword: a fade that failed genuinely CAN leave a bulb lit, and
    that sentence is byte-identical to what this module has always logged."""
    log: list[str] = []
    _fake_release_steps(monkeypatch, log, fade_raises=True)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    with caplog.at_level("ERROR"):
        _run(release_svc.release_room("spec: the other sentence"))

    said = [r.getMessage() for r in caplog.records
            if "hue release fade" in r.getMessage()]
    assert said, "a failed fade said nothing at all"
    assert said[0] == ("release: best-effort spectra hue release fade "
                       "failed — released stands, this device may still be "
                       "lit until its own timeout"), said[0]


def test_the_api_reports_whether_river_was_told(monkeypatch):
    """`release_ping` on BOTH shapes of the route's answer. A press that
    released the room and could not tell River is still a 200 `released`:
    conflating the two would put a River outage in the ownership bar's
    "these lights may still be lit" warning."""
    from spectra.api.ownership import post_release

    log: list[str] = []
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log)
    _river(monkeypatch, log,
           lambda request: httpx.Response(500, json={"error": "no"}))
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    body = _run(post_release())
    assert body["result"] == "released"
    assert body["release_ping"]["status"] == pretake_ping.STATUS_FAILED
    assert body["release_ping"]["http_status"] == 500


def test_the_api_reports_the_ping_on_an_unverified_release_too(monkeypatch):
    """The 207 shape carries it as well — River's answer and his fixtures'
    are two separate readings and a reader gets both, whichever way the
    verification went."""
    from spectra.api.ownership import post_release
    import json as _json

    log: list[str] = []
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)
    _configured(monkeypatch)
    _fake_release_steps(monkeypatch, log, still_on=["Standing Lamp"])
    _river(monkeypatch, log)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    resp = _run(post_release())
    body = _json.loads(bytes(resp.body))
    assert resp.status_code == 207
    assert body["result"] == "released-unverified"
    assert any("Standing Lamp" in p for p in body["problems"])
    assert body["release_ping"]["status"] == pretake_ping.STATUS_SENT


# ── the boundary this module does not cross ────────────────────────────────

def test_the_release_ping_still_has_no_home_assistant_path():
    """The release announcement is the same posture as the pre-take: a POST
    to a RIVER SERVICE, which then decides what to do in HA. THE SCONCE
    MAINS RULE is untouched and untouchable from here — this side drives no
    entity, names none, and could not turn a fixture on or off if asked."""
    for module in (pretake_ping, release_svc):
        body = Path(module.__file__).read_text().split('"""', 2)[2]
        lowered = body.lower()
        for forbidden in ("/api/services", "homeassistant", "home-assistant",
                          "hass", "scene.turn_on", "scene.create"):
            assert forbidden not in lowered, (
                f"{module.__name__} reached for {forbidden!r} — the house "
                f"lights are Home Assistant's, and River's alone to drive")
