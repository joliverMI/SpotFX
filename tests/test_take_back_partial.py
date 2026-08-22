"""THE TOLERANT TAKE-BACK — owner ruling 2026-08-21: "one unreachable
device must not be able to keep his entire room dark."

What happened, read off his live ownership record and journal (never his
data — read-only): six take-backs from `released` in one night aborted on
`dining-table`, a WLED whose mDNS name `wled-8a3534.local` would not
resolve ("could not confirm live state: ValueError('WLED None: Failed to
connect')"), each abort tearing down the twenty devices that HAD come up;
the morning before, the same abort on two kitchen sconces with VALID
addresses that merely answered too slowly ("WLED 192.168.40.110: Failed to
connect"). Aborting never saved the unreachable light; it only darkened the
rest.

The proofs here, NONE of which touch his stored data, his device list, or
his network (a disposable fx-live config per test, reserved/loopback
addresses only, silence_audio, open_audio=False throughout):

  1. POLICY, on fake sides (the orchestrator's own rule, fast):
     a. coming back FROM RELEASED, a PARTIAL activation (stack up, some
        expected virtuals driving, a device unconfirmed) COMMITS — the
        to-side is never deactivated, owner lands spectra, and the record's
        own history note names the skipped device;
     b. the SAME partial outcome on a handover FROM A RUNNING WORLD still
        aborts with the strict rollback (to-side released, from-side
        restored) — the scope is bounded to the way back from released;
     c. a HARD failure from released (stack never up / not one expected
        virtual driving) still aborts back to released — committing over a
        wholly dark stack is the order-8 defect, not a partial room.
  2. THE REAL PIPELINE — the exact failure class he hit: a real FxHost with
     two working (dummy) devices and one real `wled`-type device whose
     address is a GENUINELY unresolvable name (`dining-table.invalid` —
     RFC 6761 reserves `.invalid` to never resolve, deterministically,
     offline), wired the way his `single-color-effect` virtual spans
     `porch-rail` + `dining-table`, driven through the REAL armed API
     route: the take-back commits (HTTP 200, result "committed-partial"),
     every dummy-backed light is driving, the report names "Dining Table"
     with the SAME raw reason tonight's record carries, the liveness
     endpoint stays healthy (virtual-level) while carrying the additive
     `activation` report, GET /ownership carries it, and the history note
     names it.
  3. THE OTHER REAL CLASS — "merely slow": a `wled` device with a VALID,
     resolvable address (loopback) that never answers HTTP inside the
     probe window (the WLED client is patched to time out — no port-80
     dependency, no packets off-host) is skipped the same way, named by
     its address, and the take-back commits.
  4. STATUS HONESTY after commit: the recheck re-asks a still-dark light
     (last-checked age moves, the driver's own re-initialization is
     retried for a never-resolved address), and the moment a light
     confirms it is marked recovered — and a recovered unresolved light is
     genuinely ACTIVATED (driving), not just relabelled.
  5. Teardown clears the report; a torn-down stack reports nothing.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless, light_ownership as lo
from spectra.services import activation_report
from spectra.services.handover import (ActivationOutcome, HandoverFailed,
                                       SpectraSide, run_handover)
from spectra.services.live_host import LiveLights, live

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE
_EFFECT = {"type": "singleColor", "config": {"color": "#000080"}}

# His real dining-table device entry's SHAPE (storage/spectra/fx-live/
# config.json, read-only) — every key as seeded, only the address replaced
# by a name the standards reserve to never resolve. Not his data: a
# disposable fixture, written under tmp_path.
UNRESOLVABLE_ADDRESS = "dining-table.invalid"


def _run(coro):
    return asyncio.run(coro)


def _own_file(tmp_path) -> None:
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"


@pytest.fixture(autouse=True)
def _restore_ownership_file():
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


@pytest.fixture(autouse=True)
def _no_topology_restriction(monkeypatch):
    """live_host._restrict_to_genuinely_driven reads the room's category
    topology + scene store off real storage; a worktree carrying his
    real device_categories.json would intersect this fixture's virtuals
    away to nothing. The documented absent-ground-truth fallback (raw
    declared set) is what a fixture room needs."""
    from spectra.services import room_topology
    monkeypatch.setattr(room_topology, "genuinely_driven_virtual_ids",
                        lambda: set())


@pytest.fixture(autouse=True)
def _fast_device_probe(monkeypatch):
    """SpectraSide.verify_active() polls device_gaps() up to the real
    25 s DEVICE_LIVE_DEADLINE_S (WLEDs genuinely rise slowly); a fixture
    whose dark device can never rise only needs the poll shape, not the
    wait."""
    monkeypatch.setattr(live, "device_gaps", functools.partial(
        LiveLights.device_gaps, live,
        timeout_s=0.5, deadline_s=0.6, poll_interval_s=0.1))


# ── fakes for the policy proofs ─────────────────────────────────────────────

class RecordedSide:
    def __init__(self, name):
        self.name = name
        self.calls = []
        self.running = True

    async def readiness_problems(self):
        return []

    async def quiesce(self):
        self.calls.append("quiesce")
        self.running = False

    async def verify_quiesced(self):
        self.calls.append("verify_quiesced")
        return not self.running

    async def activate(self):
        self.calls.append("activate")
        self.running = True

    async def verify_active(self):
        self.calls.append("verify_active")
        return self.running

    async def deactivate(self):
        self.calls.append("deactivate")
        self.running = False


class OutcomeSide(RecordedSide):
    """A to-side whose verify_active() is False with a structured outcome —
    the shape the real SpectraSide exposes via activation_outcome()."""

    def __init__(self, name, outcome: ActivationOutcome):
        super().__init__(name)
        self.outcome = outcome

    async def verify_active(self):
        self.calls.append("verify_active")
        return self.outcome.ok

    def verification_detail(self):
        return self.outcome.detail

    def activation_outcome(self):
        return self.outcome


PARTIAL_OUTCOME = ActivationOutcome(
    ok=False, stack_up=True,
    expected_ids=frozenset({"crystal-mapper", "tv-mapper", "single-color"}),
    device_gaps={"dining-table": "could not confirm live state: "
                                 "ValueError('WLED None: Failed to connect')"},
    detail="1 device(s) unconfirmed (dining-table: could not confirm live "
           "state: ValueError('WLED None: Failed to connect'))")


# ── 1. policy ───────────────────────────────────────────────────────────────

def test_partial_activation_from_released_commits_and_names_the_device(tmp_path):
    _own_file(tmp_path)
    lo.release("test: owner let go")
    spectra_side = OutcomeSide(lo.SPECTRA, PARTIAL_OUTCOME)
    sides = {lo.SPOT_EFFECTS: RecordedSide(lo.SPOT_EFFECTS),
             lo.SPECTRA: spectra_side}

    async def main():
        record = await run_handover(lo.SPECTRA, sides, grace_s=0)
        assert record.owner == lo.SPECTRA
        assert record.handover is None
        # The to-side stays UP — never deactivated on a partial outcome.
        assert spectra_side.calls == ["activate", "verify_active"]
        # The from-world was released: nothing to quiesce, nothing restored.
        assert sides[lo.SPOT_EFFECTS].calls == []
        # The durable record itself names what was skipped.
        last = record.history[-1]
        assert last["event"] == "handover_commit"
        assert "PARTIAL" in last["detail"]
        assert "dining-table" in last["detail"]

    _run(main())


def test_same_partial_outcome_from_a_running_world_still_rolls_back(tmp_path):
    """Scope is bounded: a handover FROM a running show keeps its strict
    all-or-nothing rollback — there a working show is genuinely at risk
    and there is a real from-world to land on."""
    _own_file(tmp_path)
    assert lo.load().owner == lo.SPOT_EFFECTS
    spot = RecordedSide(lo.SPOT_EFFECTS)
    spectra_side = OutcomeSide(lo.SPECTRA, PARTIAL_OUTCOME)
    sides = {lo.SPOT_EFFECTS: spot, lo.SPECTRA: spectra_side}

    async def main():
        with pytest.raises(HandoverFailed, match="dining-table"):
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        assert lo.load().owner == lo.SPOT_EFFECTS
        assert lo.load().handover is None
        # Strict rollback, unchanged: partial new writer released FIRST,
        # then the old one restored.
        assert spectra_side.calls == ["activate", "verify_active", "deactivate"]
        assert spot.calls == ["quiesce", "verify_quiesced", "activate"]

    _run(main())


@pytest.mark.parametrize("outcome,label", [
    (ActivationOutcome(ok=False, stack_up=False,
                       expected_ids=frozenset({"a", "b"}),
                       virtual_gaps={"a": "live stack not active",
                                     "b": "live stack not active"},
                       detail="stack never came up"),
     "stack never came up"),
    (ActivationOutcome(ok=False, stack_up=True,
                       expected_ids=frozenset({"a", "b"}),
                       virtual_gaps={"a": "not flushing frames",
                                     "b": "missing from the live host"},
                       detail="not one expected virtual driving"),
     "not one expected virtual driving"),
])
def test_hard_failure_from_released_still_aborts_to_released(tmp_path, outcome, label):
    _own_file(tmp_path)
    lo.release("test: owner let go")
    spectra_side = OutcomeSide(lo.SPECTRA, outcome)
    sides = {lo.SPOT_EFFECTS: RecordedSide(lo.SPOT_EFFECTS),
             lo.SPECTRA: spectra_side}

    async def main():
        assert not outcome.partial, label
        with pytest.raises(HandoverFailed):
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        assert lo.load().owner == lo.RELEASED
        assert spectra_side.calls[-1] == "deactivate"

    _run(main())


def test_outcome_partial_predicate():
    full = ActivationOutcome(ok=True, stack_up=True,
                             expected_ids=frozenset({"a"}))
    assert not full.partial
    one_up = ActivationOutcome(ok=False, stack_up=True,
                               expected_ids=frozenset({"a", "b"}),
                               virtual_gaps={"b": "not flushing frames"})
    assert one_up.partial and one_up.up_ids == frozenset({"a"})
    devices_only = ActivationOutcome(ok=False, stack_up=True,
                                     expected_ids=frozenset({"a"}),
                                     device_gaps={"d": "could not confirm"})
    assert devices_only.partial


# ── 2./3. the real pipeline ─────────────────────────────────────────────────

def _write_room(config_dir: Path, *, dark_device: dict) -> None:
    """A fixture room in the SHAPE of his: two working lights (dummy
    devices — the headless harness's real render path, zero hardware),
    and one real `wled`-type device sharing a virtual with one of them,
    exactly how his `single-color-effect` spans `porch-rail` +
    `dining-table`. `dark_device` is the wled entry under test."""
    from fx.consts import CONFIGURATION_VERSION

    os.makedirs(config_dir, exist_ok=True)
    config = {
        "configuration_version": CONFIGURATION_VERSION,
        "devices": [
            {"id": "crystal", "type": "dummy",
             "config": {"name": "crystal", "pixel_count": 32}},
            {"id": "porch-rail", "type": "dummy",
             "config": {"name": "porch-rail", "pixel_count": 16}},
            dark_device,
        ],
        "virtuals": [
            {"id": "crystal-mapper", "is_device": "crystal",
             "auto_generated": False,
             "config": {"name": "crystal-mapper", "mapping": "span"},
             "segments": [["crystal", 0, 31, False]],
             "effect": _EFFECT},
            {"id": "single-color-effect", "is_device": None,
             "auto_generated": False,
             "config": {"name": "Single Color Effect", "mapping": "span"},
             "segments": [["porch-rail", 0, 15, False],
                          [dark_device["id"], 0, 0, False]],
             "effect": _EFFECT},
        ],
    }
    (config_dir / "config.json").write_text(json.dumps(config))


def _dining_table(address: str) -> dict:
    return {"id": "dining-table", "type": "wled",
            "config": {"center_offset": 0, "create_segments": False,
                       "icon_name": "wled", "ip_address": address,
                       "name": "Dining Table", "pixel_count": 1,
                       "refresh_rate": 62, "rgbw_led": True,
                       "sync_mode": "DDP", "timeout": 1}}


async def _teardown():
    from spectra.services import engine
    engine.go_dark()
    facade.set_host(None)
    if live.active:
        await live.deactivate()


async def _take_back_via_api(monkeypatch, sides):
    """Drive the REAL armed route, not run_handover directly — the
    response shape is part of what he sees."""
    from spectra.api.ownership import HandoverRequest, post_handover
    from spectra.services import handover as handover_svc
    monkeypatch.setenv("SPECTRA_HANDOVER_ARMED", "1")
    monkeypatch.setattr(handover_svc, "production_sides", lambda: sides)
    # The route calls run_handover with the real 5 s Hue-release grace;
    # nothing here holds a Hue session, so skip the wait (the route and
    # the orchestrator are otherwise untouched).
    real_run_handover = handover_svc.run_handover
    monkeypatch.setattr(handover_svc, "run_handover",
                        functools.partial(real_run_handover, grace_s=0))
    return await post_handover(HandoverRequest(to=lo.SPECTRA))


async def _liveness():
    from spectra.api.ownership import get_liveness
    resp = await get_liveness()
    return resp.status_code, json.loads(bytes(resp.body))


def test_real_unresolvable_wled_does_not_darken_the_room(tmp_path, monkeypatch, caplog):
    """The exact class of 2026-08-21 19:21-19:26: a WLED whose name does
    not resolve. Real FxHost, real WLED driver, real SpectraSide, real API
    route. The address is `dining-table.invalid` — never resolvable by
    standard (RFC 6761), so the vendored driver ends exactly where his
    did: no destination, `WLED None`, 'Failed to connect'."""
    caplog.set_level("CRITICAL", logger="spectra.services.handover")
    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    _write_room(config_dir, dark_device=_dining_table(UNRESOLVABLE_ADDRESS))
    lo.release("test: owner let go")                       # from_world = released
    spot = RecordedSide(lo.SPOT_EFFECTS)
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)
    sides = {lo.SPOT_EFFECTS: spot, lo.SPECTRA: side}

    async def main():
        try:
            resp = await _take_back_via_api(monkeypatch, sides)
            # Not a 502/abort: the room came up.
            assert isinstance(resp, dict), getattr(resp, "body", resp)
            assert resp["result"] == "committed-partial"
            assert resp["owner"] == lo.SPECTRA
            assert lo.load().owner == lo.SPECTRA
            assert spot.calls == []                        # nothing to quiesce/restore

            # HIS SHOW CAME UP ON EVERYTHING ELSE: both working lights are
            # active and flushing fresh frames — including the virtual
            # that SHARES segments with the dark device.
            assert live.active
            assert live.activation_gaps() == {}
            assert live.host.virtuals.get("crystal-mapper").active
            assert live.host.virtuals.get("single-color-effect").active
            assert await live.wait_fresh(timeout_s=5.0)
            # The dark device itself: genuinely unresolved (the real
            # driver's state), inactive (the render loop skips it per
            # flush — it can only dim the room, never corrupt it).
            dark = live.host.devices.get("dining-table")
            assert dark is not None and dark._destination is None
            assert not dark.is_active()

            # HE CAN SEE WHICH DEVICE WAS SKIPPED AND WHY — in the response:
            act = resp["activation"]
            assert act["partial"] is True
            assert act["devices_total"] == 3 and act["devices_skipped"] == 1
            assert act["up_virtuals"] == act["expected_virtuals"] == 2
            [skipped] = act["skipped"]
            assert skipped["device_id"] == "dining-table"
            assert skipped["name"] == "Dining Table"
            assert skipped["kind"] == activation_report.KIND_UNRESOLVED
            assert skipped["address"] == UNRESOLVABLE_ADDRESS
            assert "did not resolve" in skipped["why"]
            assert skipped["still_dark"] is True
            # …with the SAME raw reason his live record carries tonight.
            assert skipped["reason"] == ("could not confirm live state: "
                                         "ValueError('WLED None: Failed to connect')")
            assert "Dining Table" in act["summary"]

            # …on GET /ownership (what the bar polls every 4 s):
            from spectra.api.ownership import get_ownership
            own = await get_ownership()
            assert own["activation"]["skipped"][0]["name"] == "Dining Table"
            # …in the record's own durable history note:
            assert own["history"][-1]["event"] == "handover_commit"
            assert "PARTIAL" in own["history"][-1]["detail"]
            assert "Dining Table" in own["history"][-1]["detail"]
            assert "did not resolve" in own["history"][-1]["detail"]
            # …on the liveness endpoint — additive, and NOT part of healthy:
            status, body = await _liveness()
            assert status == 200 and body["healthy"]
            assert body["activation_gaps"] == {}
            assert body["activation"]["partial"] is True
            assert body["activation"]["skipped"][0]["name"] == "Dining Table"
            assert body["activation"]["devices_still_dark"] == 1
            # …and loudly in the log.
            assert any("PARTIAL TAKE-BACK" in r.message
                       for r in caplog.records if r.levelname == "CRITICAL")

            # 4. STATUS HONESTY: a recheck re-asks; the name still does not
            # resolve, so it stays dark — but the age moves and the driver's
            # own initialization was retried (the only path by which a
            # never-resolved light can ever join later).
            report = activation_report.current()
            before = report.skipped["dining-table"].last_checked_wall
            await asyncio.sleep(0.01)
            await activation_report.recheck(probe_timeout_s=0.5)
            entry = report.skipped["dining-table"]
            assert entry.still_dark
            assert entry.last_checked_wall > before
            assert entry.retries == 1
            assert dark._destination is None               # .invalid stays unresolved

            # Now the light is "fixed": the driver's own re-initialization
            # succeeds (modelled — a real WLED cannot answer on this box;
            # loopback destination, nothing leaves the host) → the recheck
            # marks it RECOVERED and the device is genuinely ACTIVATED.
            class _Live:
                async def get_info(self):
                    return {"live": True, "lip": "127.0.0.1", "fps": 41}

                async def release_realtime(self):
                    return None

            async def fixed_init():
                dark._destination = "127.0.0.1"
                dark.wled = _Live()
                dark.setup_subdevice()
                dark.subdevice._destination = "127.0.0.1"

            monkeypatch.setattr(dark, "async_initialize", fixed_init)
            await activation_report.recheck(probe_timeout_s=0.5)
            assert not entry.still_dark and entry.recovered_wall is not None
            assert entry.retries == 2
            assert dark.is_active()                        # driving, not relabelled
            assert activation_report.current().still_dark == []
            own = await get_ownership()
            assert own["activation"]["devices_still_dark"] == 0
            assert own["activation"]["skipped"][0]["still_dark"] is False
            assert "came back" in own["activation"]["summary"]
        finally:
            await _teardown()
        # 5. a torn-down stack reports nothing.
        assert activation_report.current() is None
        assert activation_report.status() is None

    _run(main())


def test_real_slow_wled_with_valid_address_is_skipped_not_fatal(tmp_path, monkeypatch):
    """The 2026-08-20 09:47 class: valid, resolvable addresses that merely
    answered too slowly ('WLED 192.168.40.110: Failed to connect'). The
    address here is loopback (resolves, nothing leaves the host) and the
    WLED HTTP client is patched to behave as a non-answering device — a
    timeout surfacing as the vendored 'Failed to connect' — so this never
    depends on what may be listening on port 80."""
    from fx import utils as fx_utils

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    _write_room(config_dir, dark_device=_dining_table("127.0.0.1"))

    async def slow_request(method, ip_address, endpoint, timeout=0.5, **kw):
        await asyncio.sleep(0.02)
        raise ValueError(f"WLED {ip_address}: Failed to connect")

    monkeypatch.setattr(fx_utils.WLED, "_wled_request",
                        staticmethod(slow_request))
    lo.release("test: owner let go")
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)
    sides = {lo.SPOT_EFFECTS: RecordedSide(lo.SPOT_EFFECTS), lo.SPECTRA: side}

    async def main():
        try:
            resp = await _take_back_via_api(monkeypatch, sides)
            assert isinstance(resp, dict) and resp["result"] == "committed-partial"
            assert lo.load().owner == lo.SPECTRA
            assert live.active and live.activation_gaps() == {}
            assert await live.wait_fresh(timeout_s=5.0)
            dark = live.host.devices.get("dining-table")
            # Resolved (valid address) — this device IS being sent frames;
            # it just never confirmed. Named by address, kind unreachable.
            assert dark._destination == "127.0.0.1"
            [skipped] = resp["activation"]["skipped"]
            assert skipped["kind"] == activation_report.KIND_UNREACHABLE
            assert skipped["address"] == "127.0.0.1"
            assert "127.0.0.1" in skipped["why"]
            assert skipped["reason"] == ("could not confirm live state: "
                                         "ValueError('WLED 127.0.0.1: Failed to connect')")
            # A recheck on a RESOLVED device never re-initializes the
            # driver (it is already being driven) — it only re-asks.
            await activation_report.recheck(probe_timeout_s=0.5)
            entry = activation_report.current().skipped["dining-table"]
            assert entry.still_dark and entry.retries == 0
            # …and the moment it answers live=true, it is recovered.
            async def answers(method, ip_address, endpoint, timeout=0.5, **kw):
                class R:
                    ok = True
                    def json(self):
                        return {"live": True, "lip": "127.0.0.1", "fps": 41}
                return R()
            monkeypatch.setattr(fx_utils.WLED, "_wled_request",
                                staticmethod(answers))
            await activation_report.recheck(probe_timeout_s=0.5)
            assert not entry.still_dark
        finally:
            await _teardown()

    _run(main())


def test_full_activation_from_released_is_a_plain_commit(tmp_path, monkeypatch):
    """Nothing skipped → result "committed" (unchanged), report non-partial."""
    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir), initial_effect=_EFFECT)
    lo.release("test: owner let go")
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)
    sides = {lo.SPOT_EFFECTS: RecordedSide(lo.SPOT_EFFECTS), lo.SPECTRA: side}

    async def main():
        try:
            resp = await _take_back_via_api(monkeypatch, sides)
            assert isinstance(resp, dict) and resp["result"] == "committed"
            assert "activation" not in resp
            assert lo.load().owner == lo.SPECTRA
            assert "PARTIAL" not in lo.load().history[-1]["detail"]
            # A full take-back records no report of its own (only the
            # tolerant path and resume do) — GET /ownership carries None.
            from spectra.api.ownership import get_ownership
            assert (await get_ownership())["activation"] is None
        finally:
            await _teardown()

    _run(main())


def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice
    assert _LazySounddevice._module is None
