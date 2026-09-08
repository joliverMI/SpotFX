"""THE WINDOW — River powers the sconce mains, SPECTRA waits for the
fixtures, and the night is gated on the MEASUREMENT rather than on her 200.

NO NETWORK, NO LIVE ROOM, NO HOME ASSISTANT anywhere in this file.
`httpx.MockTransport` stands in for River's endpoint exactly as
`tests/test_pretake_ping.py` does; the fixtures are a fake network of
addresses that may or may not answer; the fx-live config is written into
`tmp_path`; the ownership record is repointed per test. The deploy-time
bearer is never read by anything here.

THE PROOFS, in the order the brief puts them:

  1. THE WIRE — `{event: "window_open"|"window_close", room_id, at_ms}` and
     the bearer, asserted against the real request the real client built,
     on the same endpoint and by the same transport the other two events
     already use.
  2. THE WAIT — the fixtures are read back until they answer: resolved, not
     resolved, and the RELOCATED case (a mains cycle is exactly when a WLED
     takes a new lease, and a fixture found only at its old address would
     abort a night whose sconces are lit and fine).
  3. FAIL-SOFT — a failed POST is reported AND STILL WAITED ON, because the
     fixtures are the honest answer either way.
  4. THE RUN-FLOW ORDER, on a recording harness: window_open → wait → take
     → release → window_close, proven at the wire.
  5. THE ABORT — sconces that never come up: no take, nothing left held.
  6. INERT when `SPECTRA_PRETAKE_URL` is unset: zero requests, zero probes,
     no marker, and a night byte-identical to the one before this existed.
  7. THE BOUNDARY this side still does not cross.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import measuring_session                    # noqa: E402
from fx import light_ownership as lo                      # noqa: E402
from spectra import config as scfg                        # noqa: E402
from spectra.services import (capture_queue, mapping_refusals,  # noqa: E402
                              night_run, night_take, night_window,
                              pretake_ping, sconce_wait)

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE

#: THE PRISTINE FUNCTIONS, captured at import. `_night` wraps each of these
#: with a recorder; two `_night` calls in one test would otherwise have the
#: second wrap the FIRST one's wrapper and write into the first one's log —
#: which is exactly how the inertness comparison below silently compared a
#: night against itself.
_REAL_POST = pretake_ping._post
_REAL_TAKE_ROOM = night_take.take_room


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    """Every test starts with no River, no remembered ping and an isolated
    ownership record. `SPECTRA_PRETAKE_*` are DELETED rather than set, so a
    test that wants the configured path has to say so — the inert case is
    the default here exactly as it is on a host that never heard of her."""
    for name in ("SPECTRA_PRETAKE_URL", "SPECTRA_PRETAKE_TOKEN",
                 "SPECTRA_PRETAKE_SETTLE_MS", "SPECTRA_WINDOW_WAIT_MS",
                 "SPECTRA_NIGHT_SELF_TAKE"):
        monkeypatch.delenv(name, raising=False)
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    pretake_ping.reset()
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE
    pretake_ping.reset()


def _configured(monkeypatch, *, url="http://river.invalid/ping",
                token="not-the-real-one", settle_ms=0, wait_ms=None):
    monkeypatch.setenv("SPECTRA_PRETAKE_URL", url)
    if token is not None:
        monkeypatch.setenv("SPECTRA_PRETAKE_TOKEN", token)
    monkeypatch.setenv("SPECTRA_PRETAKE_SETTLE_MS", str(settle_ms))
    if wait_ms is not None:
        monkeypatch.setenv("SPECTRA_WINDOW_WAIT_MS", str(wait_ms))


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


#: River's own confirmed answer shape (2026-09-06, against her live
#: endpoint). The window events ride the SAME contract, so the same body.
RIVER_OK = {"captured": True, "elapsed_s": 0.41, "result": "mains on"}


def _ok(seen=None, body=RIVER_OK, code=200):
    def handler(request):
        if seen is not None:
            seen.setdefault("posts", []).append({
                "url": str(request.url), "method": request.method,
                "auth": request.headers.get("authorization"),
                "body": json.loads(request.content.decode())})
        return httpx.Response(code, json=body)
    return handler


def _owner(owner):
    lo._save(lo.OwnershipRecord(owner=owner))


def _code_of(module) -> str:
    """A module's CODE with every comment and docstring removed.

    The source-level boundary assertions below have to look at what the
    module DOES, not at what it says about itself: this file's own prose
    talks about switches, activation and Home Assistant precisely because
    it is explaining why none of it happens, and a naive substring scan
    over the whole file would fail on its own documentation."""
    import io
    import tokenize

    kept: list = []
    with open(module.__file__, "r", encoding="utf-8") as fh:
        source = fh.read()
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.string.lstrip("rbfu")[:3] in (
                '"""', "'''"):
            continue                       # a docstring, not an instruction
        kept.append(tok.string)
    return " ".join(kept)


# ── the fake network the fixtures live on ──────────────────────────────────

class _Net:
    """Addresses that answer `json/info`, and when. Nothing here opens a
    socket; `sconce_wait.Probes` is the seam and this is what goes into it —
    `fx/device_identity.py`'s own posture, so every path is proven against a
    fake network and never against his."""

    def __init__(self, clock=None):
        self.clock = clock or (lambda: 0.0)
        #: address -> (mac | None, available_from_seconds)
        self.answers: dict = {}
        self.hosts: dict = {}
        self.nodes: dict = {}
        self.reads: list = []

    def at(self, address, mac=None, *, after=0.0):
        self.answers[address] = (mac, after)
        return self

    async def read_info(self, address):
        self.reads.append(address)
        row = self.answers.get(address)
        if row is None or self.clock() < row[1]:
            return None
        return {"mac": row[0]} if row[0] else {"ver": "0.14"}

    async def read_nodes(self, address):
        return list(self.nodes.get(address, []))

    async def resolve_host(self, hostname):
        return self.hosts.get(hostname)

    def probes(self):
        return sconce_wait.Probes(read_info=self.read_info,
                                  read_nodes=self.read_nodes,
                                  resolve_host=self.resolve_host)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def sleep(self, seconds):
        self.t += seconds


LEFT_MAC = "e08cfe5c3a78"
RIGHT_MAC = "e08cfe5c3a79"


def _fx_config(tmp_path, devices=None):
    """A minimal fx-live config on disk — the file the wait reads because
    there is no live host to ask before the room is taken."""
    devices = devices if devices is not None else [
        {"id": "sconce-kitchen-left", "type": "wled",
         "config": {"name": "Sconce Left", "ip_address": "192.168.40.110",
                    "hardware_id": LEFT_MAC}},
        {"id": "sconce-kitchen-right", "type": "wled",
         "config": {"name": "Sconce Right", "ip_address": "192.168.40.111",
                    "hardware_id": RIGHT_MAC}},
        {"id": "hues", "type": "hue",
         "config": {"name": "Hues", "ip_address": "192.168.40.2"}},
    ]
    d = tmp_path / "fx-live"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps(
        {"devices": devices, "virtuals": []}), encoding="utf-8")
    return d


# ── 1. THE WIRE ────────────────────────────────────────────────────────────

def test_window_open_posts_the_contracted_body_and_the_bearer(monkeypatch):
    """The event word is the ONLY thing that differs from the two pings this
    endpoint already carries — same URL (SPECTRA never appends a path of its
    own), same bearer, same three fields."""
    seen: dict = {}
    _configured(monkeypatch)
    before = int(time.time() * 1000)

    async def nothing():
        return sconce_wait.WaitResult(resolved=True, detail="fake")

    async def main():
        async with _client(_ok(seen)) as client:
            return await pretake_ping.open_window(client=client, wait=nothing)

    result = _run(main())
    after = int(time.time() * 1000)
    post = seen["posts"][0]

    assert post["method"] == "POST"
    assert post["url"] == "http://river.invalid/ping", \
        "SPECTRA appended a path of its own — the route is River's to name"
    assert post["auth"] == "Bearer not-the-real-one"
    assert set(post["body"]) == {"event", "room_id", "at_ms"}, post["body"]
    assert post["body"]["event"] == "window_open"
    assert post["body"]["room_id"] == pretake_ping.ROOM_ALL
    assert before <= post["body"]["at_ms"] <= after
    # Her answer is surfaced, not reduced to a boolean — the other events'
    # own rule, through the one `read_answer`.
    assert result.ping.status == pretake_ping.STATUS_SENT
    assert result.ping.captured is True
    assert result.ping.elapsed_s == 0.41


def test_window_close_posts_the_contracted_body(monkeypatch):
    seen: dict = {}
    _configured(monkeypatch)

    async def main():
        async with _client(_ok(seen)) as client:
            return await pretake_ping.close_window(client=client)

    result = _run(main())
    post = seen["posts"][0]
    assert set(post["body"]) == {"event", "room_id", "at_ms"}
    assert post["body"]["event"] == "window_close"
    assert post["body"]["room_id"] == "all"
    assert post["auth"] == "Bearer not-the-real-one"
    assert result.ping.status == pretake_ping.STATUS_SENT
    # A CLOSE WAITS FOR NOTHING, by design — see `close_window`'s docstring.
    assert result.resolved is None
    assert result.ok is True


def test_the_payload_builder_is_the_same_one_the_window_sends():
    assert pretake_ping.payload("all", 17, pretake_ping.EVENT_WINDOW_OPEN) \
        == {"event": "window_open", "room_id": "all", "at_ms": 17}
    assert pretake_ping.payload("all", 17, pretake_ping.EVENT_WINDOW_CLOSE) \
        == {"event": "window_close", "room_id": "all", "at_ms": 17}
    # AND THE TWO EXISTING EVENTS ARE UNTOUCHED — their tests assert this
    # wording and River renders it.
    assert pretake_ping.payload("all", 17) == {
        "event": "pre_take", "room_id": "all", "at_ms": 17}


def test_a_caller_may_name_a_room(monkeypatch):
    seen: dict = {}
    _configured(monkeypatch)

    async def nothing():
        return sconce_wait.WaitResult(resolved=True)

    async def main():
        async with _client(_ok(seen)) as client:
            await pretake_ping.open_window(room_id="kitchen", client=client,
                                           wait=nothing)
            await pretake_ping.close_window(room_id="kitchen", client=client)

    _run(main())
    assert [p["body"]["room_id"] for p in seen["posts"]] == \
        ["kitchen", "kitchen"]


# ── 2. THE WAIT — the measurement the 200 cannot make ──────────────────────

def test_the_wait_resolves_once_every_fixture_answers(tmp_path):
    """The sconces boot a few seconds after their mains come back. The wait
    polls until they answer and reports how long it took."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC, after=4.0)
    net.at("192.168.40.111", RIGHT_MAC, after=6.0)

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=30_000,
        probes=net.probes(), clock=clock, sleep=clock.sleep))

    assert result.resolved is True
    assert [u["id"] for u in result.up] == ["sconce-kitchen-left",
                                            "sconce-kitchen-right"]
    assert result.missing == []
    assert result.waited_s == 6.0
    assert "answered" in result.detail
    # THE HUE DEVICE IS NOT WATCHED. It is behind a bridge that answers
    # whether or not the bulb has power, so "did it come up" is not a
    # question this can ask of it.
    assert result.watched == ["sconce-kitchen-left", "sconce-kitchen-right"]


def test_a_fixture_that_never_answers_is_named_and_the_verdict_is_false(
        tmp_path):
    """THE ONLY VALUE THAT STOPS A NIGHT. It names the fixture and the pin
    it was asked at — never "something did not work"."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)          # left comes up
    # right never answers anywhere

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=10_000,
        probes=net.probes(), clock=clock, sleep=clock.sleep))

    assert result.resolved is False
    assert [m["id"] for m in result.missing] == ["sconce-kitchen-right"]
    assert result.missing[0]["pinned"] == "192.168.40.111"
    assert "Sconce Right" in result.detail
    assert result.waited_s <= 10.0 + sconce_wait.POLL_INTERVAL_S


def test_a_relocated_fixture_is_found_by_identity_not_by_its_old_address(
        tmp_path):
    """A MAINS CYCLE IS EXACTLY WHEN A WLED TAKES A NEW LEASE, so this is
    the case that would otherwise abort a night whose sconces are lit and
    fine — `fx/device_identity.py`'s founding defect, arriving through the
    one door this feature opens."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)
    # right moved: its pin is dead, its mDNS name resolves to the new place
    net.at("192.168.40.117", RIGHT_MAC)
    net.hosts["wled-5c3a79.local"] = "192.168.40.117"

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=10_000,
        probes=net.probes(), clock=clock, sleep=clock.sleep))

    assert result.resolved is True, \
        "a relocated sconce read as a dead one and would have aborted a night"
    assert result.relocated == [{"id": "sconce-kitchen-right",
                                 "name": "Sconce Right",
                                 "from": "192.168.40.111",
                                 "to": "192.168.40.117", "via": "mdns"}]


def test_a_neighbour_answering_at_the_old_address_is_never_mistaken_for_ours(
        tmp_path):
    """A name that resolves is a CANDIDATE, never an answer. Something else
    took the lease — it answers perfectly and its MAC is not ours, so the
    fixture is still missing rather than confidently found."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)
    net.at("192.168.40.111", "aabbccddeeff")   # a stranger at the old pin

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=4_000,
        probes=net.probes(), clock=clock, sleep=clock.sleep))

    assert result.resolved is False
    assert [m["id"] for m in result.missing] == ["sconce-kitchen-right"]


def test_a_fixture_with_no_stored_identity_is_asked_at_its_pin_and_learns_one(
        tmp_path):
    """It can only be asked where it lives — and when it answers, this is
    the one moment before the stack is up that its MAC can be learned, so
    the NEXT night has an identity to find it by
    (`WLEDDevice.learn_identity`'s own lazy discipline)."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)
    config_dir = _fx_config(tmp_path, [
        {"id": "sconce-kitchen-left", "type": "wled",
         "config": {"name": "Sconce Left", "ip_address": "192.168.40.110"}}])

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=config_dir, budget_ms=4_000, probes=net.probes(),
        clock=clock, sleep=clock.sleep))

    assert result.resolved is True
    assert result.learned == ["sconce-kitchen-left"]
    assert result.persisted == ["sconce-kitchen-left"]
    stored = json.loads((config_dir / "config.json").read_text())
    assert stored["devices"][0]["config"]["hardware_id"] == LEFT_MAC
    # AND NOTHING ELSE ABOUT HIS CONFIG MOVED.
    assert stored["devices"][0]["config"]["ip_address"] == "192.168.40.110"


def test_a_new_address_is_written_back_so_the_next_restart_finds_it(tmp_path):
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)
    net.at("192.168.40.117", RIGHT_MAC)
    net.hosts["wled-5c3a79.local"] = "192.168.40.117"
    config_dir = _fx_config(tmp_path)

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=config_dir, budget_ms=4_000, probes=net.probes(),
        clock=clock, sleep=clock.sleep))

    assert result.persisted == ["sconce-kitchen-right"]
    stored = json.loads((config_dir / "config.json").read_text())
    by_id = {d["id"]: d for d in stored["devices"]}
    assert by_id["sconce-kitchen-right"]["config"]["ip_address"] == \
        "192.168.40.117"
    assert by_id["sconce-kitchen-left"]["config"]["ip_address"] == \
        "192.168.40.110", "a fixture that never moved was rewritten"


def test_a_hostname_pin_is_never_replaced_with_a_literal_address(tmp_path):
    """`.local` IS an identity handle and two of his own devices are pinned
    that way today. Resolving one is the PINNED check, not a relocation —
    writing the resolved IP back would replace the handle with exactly the
    location pin `fx/device_identity.py` exists to end."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.117", LEFT_MAC)
    net.hosts["sconce-left.local"] = "192.168.40.117"
    config_dir = _fx_config(tmp_path, [
        {"id": "sconce-kitchen-left", "type": "wled",
         "config": {"name": "Sconce Left", "ip_address": "sconce-left.local",
                    "hardware_id": LEFT_MAC}}])

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=config_dir, budget_ms=4_000, probes=net.probes(),
        clock=clock, sleep=clock.sleep))

    assert result.resolved is True
    assert result.relocated == []
    assert result.persisted == []
    stored = json.loads((config_dir / "config.json").read_text())
    assert stored["devices"][0]["config"]["ip_address"] == "sconce-left.local"


def test_the_scope_narrows_which_fixtures_are_waited_for(tmp_path):
    """The fixtures waited for are exactly the fixtures the take brings up —
    one resolution, two consumers. A run scoped to the left sconce does not
    wait for a fixture it will never drive."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)

    result = _run(sconce_wait.wait_for_fixtures(
        device_ids=["sconce-kitchen-left"], config_dir=_fx_config(tmp_path),
        budget_ms=4_000, probes=net.probes(), clock=clock,
        sleep=clock.sleep))

    assert result.resolved is True
    assert result.watched == ["sconce-kitchen-left"]


def test_a_run_that_drives_no_wled_has_nothing_to_wait_for(tmp_path):
    """RESOLVED, and it says why. "Nothing to wait for" is not a failure —
    a run with no mains dependency must not be refused for not having one.
    """
    result = _run(sconce_wait.wait_for_fixtures(
        device_ids=["hues"], config_dir=_fx_config(tmp_path),
        budget_ms=4_000, probes=_Net().probes()))
    assert result.resolved is True
    assert result.watched == []
    assert "nothing to wait for" in result.detail


def test_a_zero_budget_is_the_documented_off_switch(tmp_path):
    """`resolved=None` — NOTHING WAS CHECKED, which is not the same as
    nothing came up. `witness.VERDICT_UNAVAILABLE`'s own three-state rule,
    and the field escape hatch if this wait ever misbehaves."""
    net = _Net()

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=0, probes=net.probes()))

    assert result.resolved is None
    assert net.reads == [], "a zero budget still probed the network"
    assert "SPECTRA_WINDOW_WAIT_MS=0" in result.detail
    # AND IT DOES NOT STOP A NIGHT.
    assert pretake_ping.WindowResult(resolved=None).ok is True


def test_the_budget_knob_clamps_and_falls_back(monkeypatch):
    assert scfg.window_wait_ms() == scfg.WINDOW_WAIT_MS_DEFAULT
    monkeypatch.setenv("SPECTRA_WINDOW_WAIT_MS", "not-a-number")
    assert scfg.window_wait_ms() == scfg.WINDOW_WAIT_MS_DEFAULT
    monkeypatch.setenv("SPECTRA_WINDOW_WAIT_MS", "9999999")
    assert scfg.window_wait_ms() == scfg.WINDOW_WAIT_MS_MAX
    monkeypatch.setenv("SPECTRA_WINDOW_WAIT_MS", "-5")
    assert scfg.window_wait_ms() == 0


def test_the_sweep_runs_once_at_the_end_and_never_every_poll(tmp_path):
    """A sweep is up to 254 probes. Running it every round would spend the
    whole budget on the cheapest-to-fail path, so the cheap rungs run every
    round and the sweep runs on the LAST one — which is also why a fixture
    only the sweep can find is still found before the night is refused."""
    clock = _Clock()
    net = _Net(clock)
    net.at("192.168.40.110", LEFT_MAC)
    net.at("192.168.40.119", RIGHT_MAC)          # only a sweep finds this

    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=6_000,
        probes=net.probes(), clock=clock, sleep=clock.sleep))

    assert result.resolved is True
    assert result.swept is True
    assert result.relocated[0]["via"] == "sweep"
    # AND THE SWEEP HAPPENED ONCE. A /24 is 253 other hosts; four rounds of
    # sweeping would be four times that many reads.
    assert net.reads.count("192.168.40.1") <= 1, \
        f"the subnet was swept more than once: {len(net.reads)} reads"


def test_an_unreadable_config_waits_for_nothing_rather_than_inventing_a_fault(
        tmp_path):
    """An unreadable fx-live config already refuses the take one gate
    further on; naming a fixture failure on top of that would send somebody
    to look at a sconce over a JSON error."""
    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=tmp_path / "nope", budget_ms=4_000,
        probes=_Net().probes()))
    assert result.resolved is True
    assert result.watched == []


def test_a_probe_that_blows_up_is_a_non_answer_never_an_exception(tmp_path):
    """This sits on the night's critical path. A network stack that raises
    must come back as "did not answer", never as an exception out of the
    wait."""
    class _Boom(_Net):
        async def read_info(self, address):
            raise OSError("the network is on fire")

    net = _Boom()
    result = _run(sconce_wait.wait_for_fixtures(
        config_dir=_fx_config(tmp_path), budget_ms=1_000,
        probes=net.probes(), clock=_Clock(), sleep=_Clock().sleep))
    assert result.resolved is False
    assert len(result.missing) == 2


def test_the_wait_never_writes_to_a_fixture(tmp_path):
    """IT DRIVES NOTHING. Every request it makes is a GET — it switches no
    light on, activates no virtual and takes no room. Asserted against the
    module's own source so a future write cannot be added quietly."""
    code = _code_of(sconce_wait)
    for forbidden in ("set_power_state", "set_brightness", "apply_writes",
                      "fx_seam", "activate", "light_ownership",
                      "run_handover", "json/state", "requests.post"):
        assert forbidden not in code, \
            f"the sconce wait reached for {forbidden!r} — it is a read"
    # AND THE ONLY READS IT MAKES ARE THE TWO WLED GETs.
    assert "read_info" in code and "read_node_addresses" in code


# ── 3. FAIL-SOFT ───────────────────────────────────────────────────────────

def test_a_failed_window_open_is_reported_and_the_fixtures_are_still_read(
        monkeypatch, tmp_path):
    """THE HEADLINE SPLIT. A refused or timed-out POST may still have
    ARRIVED, and the sconces themselves are the only honest answer either
    way — so the wait happens regardless and the night is gated on THAT.
    River being down is River's business; it may never be the reason a
    night with lit sconces does not run."""
    _configured(monkeypatch)
    waited: list = []

    def handler(request):
        raise httpx.ConnectError("connection refused")

    async def wait():
        waited.append(True)
        return sconce_wait.WaitResult(resolved=True, detail="both up")

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.open_window(client=client, wait=wait)

    result = _run(main())
    assert result.ping.status == pretake_ping.STATUS_FAILED
    assert "ConnectError" in result.ping.detail
    assert waited == [True], \
        "a failed POST skipped the read-back and lost the honest answer"
    assert result.resolved is True
    assert result.ok is True, "a down River endpoint refused a night"


@pytest.mark.parametrize("code", [201, 204, 301, 401, 404, 500, 503])
def test_a_non_200_is_failed_on_both_window_events(monkeypatch, code):
    """SUCCESS IS 200, HER WORD — the same equality check both other events
    are held to, through the one `read_answer`."""
    for event in (pretake_ping.EVENT_WINDOW_OPEN,
                  pretake_ping.EVENT_WINDOW_CLOSE):
        answer = pretake_ping.read_answer(code, RIVER_OK, event)
        assert answer.status == pretake_ping.STATUS_FAILED, (event, code)
        assert str(code) in answer.detail


def test_a_200_that_did_nothing_is_sent_and_still_says_so():
    """Her contract names 200 as success and enumerates the failures, so
    inventing a fourth verdict would be renegotiating it. The STATUS follows
    her word; the DETAIL says what she actually reported."""
    answer = pretake_ping.read_answer(
        200, {"captured": False, "result": "no mains switch"},
        pretake_ping.EVENT_WINDOW_OPEN)
    assert answer.status == pretake_ping.STATUS_SENT
    assert answer.captured is False
    assert "NOTHING" in answer.detail
    assert "mains" in answer.detail


def test_a_close_that_does_not_land_is_loud_and_still_drops_the_marker(
        monkeypatch, caplog):
    """`night_take.give_back`'s own rule: the paperwork is dropped either
    way, because a marker left behind would have a cold start days later
    announce a close for a window nobody remembers. What it must not be is
    SILENT."""
    _configured(monkeypatch)
    night_window.save_marker(run_id="n1", room_id="all")

    async def close_window(*, room_id="all"):
        return pretake_ping.WindowResult(
            event=pretake_ping.EVENT_WINDOW_CLOSE,
            ping=pretake_ping.PingResult(status=pretake_ping.STATUS_FAILED,
                                         detail="she answered 500"),
            detail="she answered 500")

    with caplog.at_level("CRITICAL"):
        record = _run(night_window.close_for_run(why="finished",
                                                 close_window=close_window))
    assert record["ping"]["status"] == pretake_ping.STATUS_FAILED
    assert night_window.holding() is False
    assert any("night window: closed" in r.getMessage()
               for r in caplog.records)


def test_nothing_here_ever_logs_the_token(monkeypatch, caplog):
    _configured(monkeypatch, url="http://user:secret@river.invalid/p",
                token="super-secret-bearer")

    def handler(request):
        raise httpx.ConnectError("nope")

    async def main():
        async with _client(handler) as client:
            return await pretake_ping.close_window(client=client)

    with caplog.at_level("DEBUG"):
        result = _run(main())
    text = result.detail + " " + " ".join(r.getMessage()
                                          for r in caplog.records)
    assert "super-secret-bearer" not in text
    assert "secret@" not in text


# ── 4/5. THE RUN FLOW — order, and the abort ───────────────────────────────

ITEMS = [{"kind": "map", "room_id": "lounge", "label": "lounge blocks"}]
EVENT = {"event": "sleep-window-start", "ts": "2026-09-08T01:00:00Z",
         "source": "home-assistant"}


def _night(monkeypatch, tmp_path, *, wait_result=None, take=True,
           river=True, wait_hook=None):
    """A whole night with every side recorded against one shared log, and
    River's endpoint recorded at the WIRE. Nothing here reaches a device, a
    bridge, a service or a systemctl."""
    from spectra.services import flare_preview_hold, handover as handover_mod
    from spectra.services import release as release_mod

    log: list = []
    seen: dict = {}
    if river:
        _configured(monkeypatch)
    else:
        monkeypatch.delenv("SPECTRA_PRETAKE_URL", raising=False)
    monkeypatch.setenv("SPECTRA_NIGHT_SELF_TAKE", "1")
    _owner(lo.RELEASED if take else lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)

    # ── River, at the wire ────────────────────────────────────────────────
    def handler(request):
        body = json.loads(request.content.decode())
        seen.setdefault("posts", []).append(body)
        log.append(f"post:{body['event']}")
        return httpx.Response(200, json=RIVER_OK)

    client_holder: dict = {}
    real_post = _REAL_POST

    async def post(url, room_id, at_ms, *, client=None, event="pre_take"):
        # THE REAL TRANSPORT, over the MockTransport client — captured
        # before the patch, or this would call itself forever.
        return await real_post(url, room_id, at_ms,
                               client=client_holder["client"], event=event)
    monkeypatch.setattr(pretake_ping, "_post", post)

    # ── the fixtures ──────────────────────────────────────────────────────
    async def wait_for_fixtures(**kw):
        log.append("wait")
        if wait_hook is not None:
            return await wait_hook()
        return wait_result if wait_result is not None else \
            sconce_wait.WaitResult(resolved=True, detail="both up")
    monkeypatch.setattr(sconce_wait, "wait_for_fixtures", wait_for_fixtures)

    # ── the take ──────────────────────────────────────────────────────────
    real_take = _REAL_TAKE_ROOM

    async def take_room(run_id, *, sides=None, run_handover=None, scope=None):
        async def handover(to_world, sides_, *, quiet=False, pretake=True,
                           **kw):
            log.append("take")
            lo._save(lo.OwnershipRecord(owner=to_world))
            return lo.load()
        return await real_take(run_id, sides={}, run_handover=handover,
                               scope=scope)
    monkeypatch.setattr(night_take, "take_room", take_room)

    # ── the release: the REAL announcement, a fake fade ───────────────────
    async def release_room(reason="x"):
        log.append("release")
        lo.release(reason)
        ping = await pretake_ping.after_release()
        return release_mod.ReleaseResult(
            record=lo.load(), from_world=lo.SPECTRA, verified=True,
            problems=[], release_ping=ping.as_dict())
    monkeypatch.setattr(release_mod, "release_room", release_room)

    # ── everything else a night touches, faked ────────────────────────────
    async def listing():
        return []

    async def price(items, now=None):
        return {"items": [], "total_seconds": 30.0, "window_seconds": 9999.0,
                "planned_end": time.time() + 9999,
                "planned_end_label": night_run.PLANNED_END_LABEL}

    async def run_queue(items, **kw):
        log.append("queue")
        return kw["run"]

    async def close_hold():
        return {"reverted": True}

    async def live_devices():
        return []

    monkeypatch.setattr(night_run, "_device_listing", listing)
    monkeypatch.setattr(night_run, "price_items", price)
    monkeypatch.setattr(night_run, "_live_devices", live_devices)
    monkeypatch.setattr(night_run, "run_fixture_rows",
                        lambda items, entries: [])
    monkeypatch.setattr(capture_queue, "run_queue", run_queue)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)
    monkeypatch.setattr(handover_mod, "production_sides",
                        lambda **kw: {}, raising=False)

    async def main():
        async with _client(handler) as client:
            client_holder["client"] = client
            run = await night_run.start(EVENT)
            if night_run._task is not None:
                await night_run._task
            return run

    return _run(main()), log, seen


def test_the_run_flow_order_open_wait_take_release_close(monkeypatch,
                                                         tmp_path):
    """THE WHOLE SEQUENCE, at the wire and at the sides:

        window_open → wait for the fixtures → TAKE (which fires the
        pre_take ping) → the queue → RELEASE (which fires released) →
        window_close

    Every one of those orderings is a correctness property. The window
    opens before anything is taken because the mains have to be on before
    the room goes dark; the wait sits between the ask and the take because
    her 200 is not a lit sconce; and the close comes AFTER the release
    because River restores his bedtime baseline into a room SPECTRA has
    already let go of, never one it is still holding."""
    run, log, seen = _night(monkeypatch, tmp_path)

    assert run.state == night_run.STATE_COMPLETE, run.detail
    assert [p["event"] for p in seen["posts"]] == [
        "window_open", "pre_take", "released", "window_close"], seen["posts"]
    assert log == ["post:window_open", "wait", "post:pre_take", "take",
                   "queue", "release", "post:released",
                   "post:window_close"], log
    # AND IT IS ON THE RECORD, both ends.
    assert run.window["ping"]["status"] == pretake_ping.STATUS_SENT
    assert run.window["resolved"] is True
    assert run.window["close"]["ping"]["status"] == pretake_ping.STATUS_SENT
    assert run.window["close"]["why"] == night_window.WHY_FINISHED
    stored = night_run.load_nights()[-1]
    assert stored["window"]["close"]["why"] == night_window.WHY_FINISHED
    # NOTHING IS LEFT HELD.
    assert night_window.holding() is False
    assert night_take.holding() is False


def test_the_window_opens_even_when_no_take_is_needed(monkeypatch, tmp_path):
    """The mains is about POWER, not about ownership: a night on a room
    SPECTRA already holds needs its sconces lit exactly as much as one that
    takes it."""
    run, log, seen = _night(monkeypatch, tmp_path, take=False)
    assert run.state == night_run.STATE_COMPLETE, run.detail
    assert [p["event"] for p in seen["posts"]] == ["window_open",
                                                   "window_close"]
    assert "take" not in log
    assert log[0] == "post:window_open" and log[1] == "wait"


def test_sconces_that_never_come_up_abort_the_night_and_hold_nothing(
        monkeypatch, tmp_path):
    """THE GATE. A room taken with a dark sconce measures the dark for four
    hours and calls the result a map — so this refuses instead, and the
    refusal takes no room, runs no queue, and closes the window it just
    opened so his away automations are not held for a night that is not
    going to happen."""
    dark = sconce_wait.WaitResult(
        resolved=False, budget_s=45.0,
        watched=["sconce-kitchen-left", "sconce-kitchen-right"],
        missing=[{"id": "sconce-kitchen-right", "name": "Sconce Right",
                  "pinned": "192.168.40.111", "hardware_id": RIGHT_MAC}])
    dark.detail = sconce_wait.describe(dark)
    run, log, seen = _night(monkeypatch, tmp_path, wait_result=dark)

    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == night_window.REFUSAL_SCONCES_DARK
    # THE ROOM WAS NEVER TAKEN, AND NOTHING RAN.
    assert "take" not in log and "queue" not in log and "release" not in log
    assert lo.load().owner == lo.RELEASED
    assert night_take.holding() is False
    # THE WINDOW WAS CLOSED AGAIN — nothing is left held.
    assert [p["event"] for p in seen["posts"]] == ["window_open",
                                                   "window_close"]
    assert night_window.holding() is False
    assert run.window["close"]["why"] == night_window.WHY_SCONCES_DARK
    # AND THE SENTENCE NAMES THE FIXTURE, WITH THE MAINS CHECK FIRST.
    assert "Sconce Right" in run.detail
    assert "light.dimmer_kitchen_sconce" in run.detail
    assert run.detail.index("light.dimmer_kitchen_sconce") < \
        run.detail.index("Sconce Right"), \
        "the mains check was buried under the technical detail"
    assert "hardware identity" in run.detail


def test_a_stop_arriving_while_the_window_opens_is_honoured(monkeypatch,
                                                            tmp_path):
    """THE WINDOW THIS BUILD CREATED. The fixture wait spends real seconds
    with no night yet for `capture_queue.stop()` to say no to, so a stop
    landing inside it can only be honoured here — and a touched house is his
    house whichever second of the start it lands in. Nothing has been taken
    at that point, so it costs him only the window, which goes straight
    back."""
    async def wait():
        # He reaches for a light while the sconces are still booting.
        night_run._stop_mark = time.monotonic()
        night_run._stop_source = "light-touched"
        return sconce_wait.WaitResult(resolved=True, detail="both up")

    run, log, seen = _night(monkeypatch, tmp_path, wait_hook=wait)

    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "stopped_during_take"
    assert "take" not in log and "queue" not in log
    assert lo.load().owner == lo.RELEASED
    assert [p["event"] for p in seen["posts"]] == ["window_open",
                                                   "window_close"]
    assert night_window.holding() is False


def test_the_abort_closes_the_window_right_after_the_room_goes_back(
        monkeypatch):
    """His away automations come off hold on the same "within seconds"
    promise the dark room is on, rather than waiting for the run task to
    finish closing out — and the reply says so, because the house acts on
    that response rather than on its next poll."""
    from spectra.services import flare_preview_hold, mapping_session
    from spectra.services import capture_runs as runs_mod

    closed: list = []

    async def close_window(*, room_id="all"):
        closed.append(room_id)
        return pretake_ping.WindowResult(
            event=pretake_ping.EVENT_WINDOW_CLOSE,
            ping=pretake_ping.PingResult(status=pretake_ping.STATUS_SENT),
            detail="River closed the window")
    monkeypatch.setattr(pretake_ping, "close_window", close_window)

    run = night_run.NightRun(id="live", state=night_run.STATE_RUNNING,
                             started=time.time())
    night_run.current = run
    night_window.save_marker(run_id=run.id, room_id="all")

    monkeypatch.setattr(mapping_session, "current", None)
    monkeypatch.setattr(runs_mod, "running", lambda: None)

    async def close_hold():
        return {"reverted": True}
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)

    body = _run(night_run.abort({"event": "sleep-ended"}, grace_s=0))

    assert body["closed_window"] is True
    assert closed == ["all"]
    assert night_window.holding() is False
    assert run.abort["closed_window"] is True
    assert run.window["close"]["why"] == night_window.WHY_ABORTED


def test_his_morning_routine_closes_the_window_as_an_ordinary_ending(
        monkeypatch):
    """`night_take.WHY_MORNING`'s own split, one pair over: a night that ran
    until his morning ran exactly as long as it was ever going to, and
    labelling that an abort is how a record stops being read."""
    from spectra.services import flare_preview_hold, mapping_session
    from spectra.services import capture_runs as runs_mod

    async def close_window(*, room_id="all"):
        return pretake_ping.WindowResult(
            ping=pretake_ping.PingResult(status=pretake_ping.STATUS_SENT))
    monkeypatch.setattr(pretake_ping, "close_window", close_window)

    run = night_run.NightRun(id="live", state=night_run.STATE_RUNNING,
                             started=time.time())
    night_run.current = run
    night_window.save_marker(run_id=run.id, room_id="all")
    monkeypatch.setattr(mapping_session, "current", None)
    monkeypatch.setattr(runs_mod, "running", lambda: None)

    async def close_hold():
        return {"reverted": True}
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)

    _run(night_run.abort({"event": mapping_refusals.MORNING_ROUTINE},
                         grace_s=0))
    assert run.window["close"]["why"] == night_window.WHY_MORNING


# ── 6. INERT when there is no River ────────────────────────────────────────

def test_unconfigured_sends_nothing_waits_for_nothing_and_marks_nothing():
    """PROVEN, NOT CLAIMED. A client that raises on any call and a wait that
    raises if reached are both handed in, so the inert path is asserted by
    construction rather than by counting."""
    class _Explode:
        async def post(self, *a, **kw):
            raise AssertionError("the unconfigured path sent a request")

        async def aclose(self):
            pass

    async def wait():
        raise AssertionError("the unconfigured path probed the network")

    result = _run(pretake_ping.open_window(client=_Explode(), wait=wait))
    assert result.ping.status == pretake_ping.STATUS_UNCONFIGURED
    assert result.resolved is None
    assert result.ok is True, \
        "a host with no River configured stopped running nights"
    assert "SPECTRA_PRETAKE_URL" in result.detail

    closed = _run(pretake_ping.close_window(client=_Explode()))
    assert closed.ping.status == pretake_ping.STATUS_UNCONFIGURED


def test_an_unconfigured_night_writes_no_marker_and_has_nothing_to_close():
    """The marker means exactly "River was asked to open a window and has
    not been told to close it" — so a host that asked her nothing writes no
    file at all, and every exit path's close is a single file stat."""
    async def open_window(*, room_id="all", device_ids=None):
        return pretake_ping.WindowResult(
            ping=pretake_ping.PingResult(
                status=pretake_ping.STATUS_UNCONFIGURED),
            resolved=None, detail="no River here")

    result = _run(night_window.open_for_run("n1", open_window=open_window))
    assert result.ok is True
    assert night_window.holding() is False

    async def close_window(**kw):
        raise AssertionError("a window that was never opened was closed")

    assert _run(night_window.close_for_run(
        why="finished", close_window=close_window)) == {}


def test_an_unconfigured_whole_night_is_byte_identical(monkeypatch,
                                                       tmp_path):
    """THE INERTNESS PROOF AT THE NIGHT, not at the client: the side-call
    sequence of an unconfigured night is compared against the same night
    with River configured and everything answering. The window's four
    entries are the ONLY difference — remove them and the two are equal."""
    with_river, log_with, _ = _night(monkeypatch, tmp_path)
    assert with_river.state == night_run.STATE_COMPLETE

    # A SECOND NIGHT IN ONE PROCESS. `capture_queue.new_run` installs the
    # live record and the fake `run_queue` never marks it done, so the
    # second start would decline as `already_running` — this is the test
    # harness putting the module back, not a production concern.
    capture_queue.current = None
    night_run.current = None
    night_run._task = None
    pretake_ping.reset()
    without, log_without, seen = _night(monkeypatch, tmp_path, river=False)

    assert without.state == night_run.STATE_COMPLETE
    assert without.window["resolved"] is None
    assert without.window["ping"]["status"] == \
        pretake_ping.STATUS_UNCONFIGURED
    assert seen.get("posts") in (None, []), \
        "an unconfigured night reached River"
    assert night_window.holding() is False, \
        "an unconfigured night wrote a marker for a window it never opened"
    # THE FOUR WIRE ENTRIES AND THE WAIT ARE THE ONLY DIFFERENCE. Strip
    # them and the two nights are the same night, step for step.
    assert [e for e in log_with if not e.startswith("post:")
            and e != "wait"] == log_without, (log_with, log_without)


# ── 7. THE PAIRING, AND THE CRASH ──────────────────────────────────────────

def test_the_marker_survives_this_process_and_the_cold_start_closes_it(
        monkeypatch):
    """A crash mid-night leaves River holding his away automations
    indefinitely with nothing visibly wrong for anyone to notice — the same
    class of loose end `night_take.recover_orphaned_take` exists for, on the
    other half of the same act. The marker on disk is the proof: this
    process cannot be the one that wrote it."""
    closed: list = []

    async def close_window(*, room_id="all"):
        closed.append(room_id)
        return pretake_ping.WindowResult(
            event=pretake_ping.EVENT_WINDOW_CLOSE,
            ping=pretake_ping.PingResult(status=pretake_ping.STATUS_SENT),
            detail="River closed the window")

    night_window.save_marker(run_id="crashed-night", room_id="all")
    assert night_window.holding() is True

    record = _run(night_window.recover_orphaned_window(
        close_window=close_window))
    assert record["recovered"] is True
    assert record["run_id"] == "crashed-night"
    assert record["why"] == night_window.WHY_CRASH
    assert closed == ["all"]
    assert night_window.holding() is False
    # AND IT IS A NO-OP ON EVERY ORDINARY START.
    assert _run(night_window.recover_orphaned_window(
        close_window=close_window)) == {}


def test_the_cold_start_closes_a_window_with_no_take_behind_it(monkeypatch):
    """GATED ON ITS OWN MARKER, never on the take's snapshot: a window can
    be open with no take at all — a night on a room SPECTRA already held
    still asks River for the mains."""
    posts: list = []

    async def close_window(*, room_id="all"):
        posts.append(room_id)
        return pretake_ping.WindowResult(
            event=pretake_ping.EVENT_WINDOW_CLOSE,
            ping=pretake_ping.PingResult(status=pretake_ping.STATUS_SENT))
    monkeypatch.setattr(pretake_ping, "close_window", close_window)

    night_window.save_marker(run_id="n1", room_id="all")
    assert night_take.holding() is False, "this test needs no take snapshot"

    out = _run(night_run.recover_orphaned_night())
    assert out["window"]["recovered"] is True
    assert posts == ["all"]


def test_the_close_is_idempotent(monkeypatch):
    """`night_run.abort` and the run task's own `_finish` both reach it, in
    an order nothing guarantees; the second finds no marker and is a no-op
    that says so."""
    calls: list = []

    async def close_window(*, room_id="all"):
        calls.append(room_id)
        return pretake_ping.WindowResult(
            ping=pretake_ping.PingResult(status=pretake_ping.STATUS_SENT))

    night_window.save_marker(run_id="n1", room_id="all")
    first = _run(night_window.close_for_run(why="finished",
                                            close_window=close_window))
    second = _run(night_window.close_for_run(why="finished",
                                             close_window=close_window))
    assert first["why"] == "finished"
    assert second == {}
    assert calls == ["all"], "the window was closed twice"


def test_opening_the_window_never_raises(monkeypatch):
    """A night must never fail to start over the window. `open_window` does
    not raise; this is the belt on top of those braces."""
    async def open_window(**kw):
        raise RuntimeError("a regression inside the announcement")

    result = _run(night_window.open_for_run("n1", open_window=open_window))
    assert result.ok is True
    assert result.resolved is None
    assert "RuntimeError" in result.detail
    assert night_window.holding() is False


# ── 8. THE BOUNDARY THIS SIDE STILL DOES NOT CROSS ─────────────────────────

def test_neither_module_has_a_home_assistant_path():
    """THE SCONCE MAINS RULE is untouched and untouchable from here: the
    only thing that leaves is a POST to a River service, and what she does
    with it is hers. `witness.py` states it as a prohibition and this is its
    mirror image on the two modules this feature adds."""
    for module in (night_window, sconce_wait):
        lowered = _code_of(module).lower()
        for forbidden in ("light.", "switch.", "/api/services",
                          "homeassistant", "home-assistant", "hass",
                          "scene.turn_on", "scene.create"):
            assert forbidden not in lowered, (
                f"{module.__name__} reached for {forbidden!r} — the house "
                f"lights are Home Assistant's, and River's alone to drive")
