"""SPECTRA S3 — the OFFLINE HANDOVER PROOF: the full quiesce → activate →
commit sequence and its reverse run against fakes and the headless harness,
with the merge-scout §4d failure modes landing single-owner. NO live
handover, no real device, no audio hardware (silence_audio + an injected
fake capture source).

The proofs:
  1. the full cycle on the REAL SpectraSide: a dummy-device FxHost activates
     under the step-gated grant, its render thread's frame flushes drive the
     liveness endpoint healthy, the engine swaps to the facade executor, the
     Stage-2 audio hub feeds the hub melbank — and the reverse handover
     tears it all down and lands back at spot-effects, provably dark;
  2. the split-brain tripwire and per-virtual staleness turn the liveness
     endpoint 503;
  3. never-two-writers on a room bus that RAISES on a second holder — the
     whole cycle completes without the bus ever seeing two writers;
  4. Hue DTLS exclusivity + the multi-second handshake: a session-release
     cooldown inside the handshake budget succeeds after retries; past the
     budget the handover fails and LANDS at the old owner with the partial
     new writer released;
  5. a lying quiesce (stop claimed, outputs still running) never lets the
     new writer start — verification is independent of the claim;
  6. the armed latch: the handover API refuses unarmed.
  7. the READINESS GATE (order-8): a missing/empty/unusable fx-live config
     REFUSES the handover before the old owner is quiesced — the room stays
     untouched, the refusal names the seeder command; the reverse direction
     equally refuses when the LedFX service unit is missing.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless, light_ownership as lo

VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _own_file(tmp_path) -> None:
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"


class FakeAudioSource:
    """Stands in for LiveDeviceSource: same open/close surface, zero
    hardware. Captures the allow_device flag to prove the wiring passes it
    explicitly and nowhere else."""

    def __init__(self, hub):
        self.hub = hub
        self.opened = False
        self.allow_seen = None

    def open(self, *, allow_device: bool = False) -> None:
        self.allow_seen = allow_device
        if not allow_device:
            raise RuntimeError("refused without allow_device")
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def is_open(self) -> bool:
        return self.opened


class RecordedSide:
    """A minimal cooperative writer side (the fake spot-effects world)."""

    def __init__(self, name):
        self.name = name
        self.calls = []
        self.running = True

    async def readiness_problems(self):
        self.calls.append("readiness_problems")
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


async def _liveness():
    from spectra.api.ownership import get_liveness
    resp = await get_liveness()
    return resp.status_code, json.loads(bytes(resp.body))


# ── proof 1+2: the full cycle on the real SpectraSide ────────────────────────

def test_full_handover_cycle_on_the_harness(tmp_path):
    from spectra.services import engine
    from spectra.services.handover import SpectraSide, run_handover
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(
        str(config_dir),
        initial_effect={"type": "singleColor", "config": {"color": "#000080"}},
    )
    audio_box = []

    def audio_factory(hub):
        src = FakeAudioSource(hub)
        audio_box.append(src)
        return src

    spot = RecordedSide(lo.SPOT_EFFECTS)
    spectra_side = SpectraSide(config_dir=str(config_dir),
                               audio_source_factory=audio_factory)
    sides = {lo.SPOT_EFFECTS: spot, lo.SPECTRA: spectra_side}

    async def main():
        try:
            # Forward: spot-effects → spectra.
            record = await run_handover(lo.SPECTRA, sides, grace_s=0)
            assert record.owner == lo.SPECTRA
            # verify_quiesced runs twice: once to pass the quiesce gate, once
            # more immediately before commit (report gate e4i) to catch a
            # from-world resurrect in the verify→commit window.
            assert spot.calls == ["quiesce", "verify_quiesced", "verify_quiesced"]

            # The engine is LIVE on the facade executor, pointed at the
            # live host the grant admitted.
            assert engine.executor.mode == "facade"
            assert engine.conductor.executor is engine.executor
            assert engine.responses.executor is engine.executor
            assert live.active and (await facade.get_host()) is live.host

            # The audio hub took over: the fake capture source was opened
            # with the explicit allow_device flag, and pushed PCM reaches
            # the hub-fed melbank through the pump task.
            src = audio_box[0]
            assert src.opened and src.allow_seen is True
            assert live.host.audio is live.melbank
            live.hub.push(np.zeros(2048, dtype=np.float32))
            await asyncio.sleep(0.15)
            assert live.melbank.frames_ingested >= 2  # 2048 // 735

            # The liveness endpoint: healthy, live, per-virtual fresh —
            # frame-flush stamps from the REAL render thread.
            status, body = await _liveness()
            assert status == 200 and body["healthy"]
            assert body["state"] == "live" and body["owner"] == lo.SPECTRA
            assert body["virtuals"][VID]["fresh"]
            assert body["virtuals"][VID]["last_flush_age_s"] is not None
            assert body["devices"][headless.DEFAULT_DEVICE_ID]["online"]

            # Split-brain tripwire: a live stack without ownership is 503.
            rec = lo.load()
            rec.owner = lo.SPOT_EFFECTS
            lo._save(rec)
            status, body = await _liveness()
            assert status == 503 and body["state"] == "split-brain"
            rec.owner = lo.SPECTRA
            lo._save(rec)

            # Per-virtual staleness: pause the render loop (frames stop
            # flushing while the virtual stays active) → stale → 503.
            virtual = live.host.virtuals.get(VID)
            virtual._paused = True
            await asyncio.sleep(2.3)  # > STALE_AFTER_S
            status, body = await _liveness()
            assert status == 503 and not body["virtuals"][VID]["fresh"]
            virtual._paused = False
            assert await live.wait_fresh(timeout_s=5.0)

            # Reverse: spectra → spot-effects. The stack tears down, the
            # engine goes dark, the old world is restored.
            record = await run_handover(lo.SPOT_EFFECTS, sides, grace_s=0)
            assert record.owner == lo.SPOT_EFFECTS
            assert engine.executor.mode == "recording"
            assert not live.active and facade._host is None
            assert not src.opened
            assert spot.calls[-2:] == ["activate", "verify_active"]

            status, body = await _liveness()
            assert status == 200 and body["healthy"]
            assert body["state"] == "dark" and body["virtuals"] == {}
        finally:
            engine.go_dark()
            facade.set_host(None)
            if live.active:
                await live.deactivate()

    _run(main())


# ── proofs 3-5: the room bus (never two writers, §4d failure modes) ──────────

class RoomBus:
    """The room's exclusive resources. acquire() RAISES on a second holder —
    reaching the end of a test proves no step ever put two writers on the
    room. Releasing the Hue session arms a cooldown: the bridge holds the
    slot for N further acquire attempts (the multi-second release/handshake
    cost, merge-scout §4d)."""

    def __init__(self, hue_cooldown: int = 0):
        self.holders: dict[str, str] = {}
        self.hue_cooldown = 0
        self.hue_cooldown_after_release = hue_cooldown
        self.max_worlds_holding = 0

    def _account(self):
        worlds = set(self.holders.values())
        self.max_worlds_holding = max(self.max_worlds_holding, len(worlds))
        assert len(worlds) <= 1, f"SPLIT OWNERSHIP: {self.holders}"

    def acquire(self, resource: str, world: str) -> None:
        if resource in self.holders:
            raise RuntimeError(
                f"{resource} already held by {self.holders[resource]}")
        if resource == "hue-dtls" and self.hue_cooldown > 0:
            self.hue_cooldown -= 1
            raise RuntimeError("hue bridge: session not yet released")
        self.holders[resource] = world
        self._account()

    def release(self, resource: str, world: str) -> None:
        if self.holders.get(resource) == world:
            del self.holders[resource]
            if resource == "hue-dtls":
                self.hue_cooldown = self.hue_cooldown_after_release


class BusSide:
    RESOURCES = ("hue-dtls", "ddp-sender")

    def __init__(self, name, bus, *, holds=False, lie_on_quiesce=False,
                 handshake_budget=3):
        self.name = name
        self.bus = bus
        self.lie_on_quiesce = lie_on_quiesce
        self.handshake_budget = handshake_budget
        if holds:
            for r in self.RESOURCES:
                bus.acquire(r, name)

    async def readiness_problems(self):
        return []

    async def quiesce(self):
        if self.lie_on_quiesce:
            return  # claims success; releases nothing
        for r in self.RESOURCES:
            self.bus.release(r, self.name)

    async def verify_quiesced(self):
        # Independent of the quiesce call's claim: consult the room itself.
        return all(self.bus.holders.get(r) != self.name
                   for r in self.RESOURCES)

    async def activate(self):
        for attempt in range(self.handshake_budget):
            try:
                self.bus.acquire("hue-dtls", self.name)
                break
            except RuntimeError:
                await asyncio.sleep(0)  # next handshake attempt
        else:
            raise RuntimeError("DTLS handshake budget exhausted")
        self.bus.acquire("ddp-sender", self.name)

    async def verify_active(self):
        return all(self.bus.holders.get(r) == self.name
                   for r in self.RESOURCES)

    async def deactivate(self):
        for r in self.RESOURCES:
            self.bus.release(r, self.name)


def _bus_sides(bus, **spectra_kw):
    return {
        lo.SPOT_EFFECTS: BusSide(lo.SPOT_EFFECTS, bus, holds=True),
        lo.SPECTRA: BusSide(lo.SPECTRA, bus, **spectra_kw),
    }


def test_never_two_writers_through_the_full_cycle(tmp_path):
    from spectra.services.handover import run_handover

    _own_file(tmp_path)
    bus = RoomBus()
    sides = _bus_sides(bus)

    async def main():
        record = await run_handover(lo.SPECTRA, sides, grace_s=0)
        assert record.owner == lo.SPECTRA
        assert bus.holders == {"hue-dtls": lo.SPECTRA,
                               "ddp-sender": lo.SPECTRA}
        record = await run_handover(lo.SPOT_EFFECTS, sides, grace_s=0)
        assert record.owner == lo.SPOT_EFFECTS
        assert bus.holders == {"hue-dtls": lo.SPOT_EFFECTS,
                               "ddp-sender": lo.SPOT_EFFECTS}
        # The bus raises on any second holder, and at no instant did more
        # than one world hold ANY room resource.
        assert bus.max_worlds_holding == 1

    _run(main())


def test_hue_release_cooldown_within_handshake_budget(tmp_path):
    from spectra.services.handover import run_handover

    _own_file(tmp_path)
    bus = RoomBus(hue_cooldown=2)  # released session frees on the 3rd try
    sides = _bus_sides(bus, handshake_budget=3)

    async def main():
        record = await run_handover(lo.SPECTRA, sides, grace_s=0)
        assert record.owner == lo.SPECTRA
        assert bus.holders["hue-dtls"] == lo.SPECTRA

    _run(main())


def test_hue_handshake_budget_exhausted_lands_old_owner(tmp_path):
    from spectra.services.handover import HandoverFailed, run_handover

    _own_file(tmp_path)
    # The bridge holds the released session far past SPECTRA's handshake
    # budget. The restored old writer is the real LedFX service, whose
    # hardened Hue driver retries persistently (serialized handshakes,
    # flush-level reconnect) — modeled as a much larger budget.
    bus = RoomBus(hue_cooldown=99)
    sides = {
        lo.SPOT_EFFECTS: BusSide(lo.SPOT_EFFECTS, bus, holds=True,
                                 handshake_budget=200),
        lo.SPECTRA: BusSide(lo.SPECTRA, bus, handshake_budget=3),
    }

    async def main():
        with pytest.raises(HandoverFailed):
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        # Landed single-owner: record back at spot-effects, the old writer
        # re-holds the room, the new one released everything it had.
        assert lo.load().owner == lo.SPOT_EFFECTS
        assert lo.load().handover is None
        assert bus.holders == {"hue-dtls": lo.SPOT_EFFECTS,
                               "ddp-sender": lo.SPOT_EFFECTS}
        assert bus.max_worlds_holding == 1

    _run(main())


def test_lying_quiesce_never_starts_second_writer(tmp_path):
    from spectra.services.handover import HandoverFailed, run_handover

    _own_file(tmp_path)
    bus = RoomBus()
    sides = {
        lo.SPOT_EFFECTS: BusSide(lo.SPOT_EFFECTS, bus, holds=True,
                                 lie_on_quiesce=True),
        lo.SPECTRA: BusSide(lo.SPECTRA, bus),
    }

    async def main():
        with pytest.raises(HandoverFailed):
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        # Verification consulted the ROOM, caught the lie, and the new
        # writer never attempted the bus: still exactly one holder.
        assert lo.load().owner == lo.SPOT_EFFECTS
        assert bus.holders == {"hue-dtls": lo.SPOT_EFFECTS,
                               "ddp-sender": lo.SPOT_EFFECTS}
        assert bus.max_worlds_holding == 1

    _run(main())


class ResurrectingSide:
    """Quiesces honestly (the FIRST verify_quiesced passes the gate), then
    something OUTSIDE this orchestrator's control — systemd's Wants=, an
    operator `systemctl start`, a stray watchdog — restarts it before
    commit. Models the two-writers incident's actual mechanism: a
    resurrect that bypasses this orchestrator entirely, not a lying
    quiesce call (see test_lying_quiesce_never_starts_second_writer for
    that, different, failure)."""
    name = lo.SPOT_EFFECTS

    def __init__(self):
        self.calls = []
        self._verify_count = 0

    async def readiness_problems(self):
        return []

    async def quiesce(self):
        self.calls.append("quiesce")

    async def verify_quiesced(self):
        self.calls.append("verify_quiesced")
        self._verify_count += 1
        # First check (the quiesce gate) passes; the second (immediately
        # before commit, report gate e4i) finds it back.
        return self._verify_count == 1

    async def activate(self):
        self.calls.append("activate")

    async def verify_active(self):
        self.calls.append("verify_active")
        return True

    async def deactivate(self):
        self.calls.append("deactivate")


def test_resurrect_before_commit_aborts(tmp_path, caplog):
    """Report gate e4i (two-writers incident, 2026-08-13): a from-world
    resurrect landing in the verify→commit gap must abort the handover
    instead of committing sole ownership over a second writer."""
    from spectra.services.handover import HandoverFailed, run_handover

    caplog.set_level("CRITICAL", logger="spectra.services.handover")
    _own_file(tmp_path)
    spot = ResurrectingSide()
    spectra_side = RecordedSide(lo.SPECTRA)
    sides = {lo.SPOT_EFFECTS: spot, lo.SPECTRA: spectra_side}

    async def main():
        with pytest.raises(HandoverFailed, match="resurrected"):
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        # Landed back single-owner at the world that's actually still
        # writing (spot-effects — the resurrect is reality), never
        # committed spectra as sole owner while a second writer paints.
        assert lo.load().owner == lo.SPOT_EFFECTS
        assert lo.load().handover is None
        # The new writer's partial activation was released, not left up.
        assert spectra_side.calls[-1] == "deactivate"
        # quiesce, the quiesce-gate check, the pre-commit re-check that
        # caught the resurrect, then the best-effort "restore" (harmless —
        # it was already back).
        assert spot.calls == ["quiesce", "verify_quiesced", "verify_quiesced",
                              "activate"]

    _run(main())
    assert any("resurrected" in r.message for r in caplog.records
               if r.levelname == "CRITICAL")


# ── proof 6: the armed latch ─────────────────────────────────────────────────

def test_handover_api_refuses_unarmed(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from spectra.api.ownership import HandoverRequest, post_handover

    _own_file(tmp_path)
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)

    async def main():
        with pytest.raises(HTTPException) as exc:
            await post_handover(HandoverRequest(to=lo.SPECTRA))
        assert exc.value.status_code == 403
        # The record never moved — an unarmed request is inert.
        assert lo.load().owner == lo.SPOT_EFFECTS
        assert not lo.OWNERSHIP_FILE.exists()

    _run(main())


def test_handover_api_armed_but_already_owner_is_409(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from spectra.api.ownership import HandoverRequest, post_handover

    _own_file(tmp_path)
    monkeypatch.setenv("SPECTRA_HANDOVER_ARMED", "1")

    async def main():
        with pytest.raises(HTTPException) as exc:
            await post_handover(HandoverRequest(to=lo.SPOT_EFFECTS))
        assert exc.value.status_code == 409

    _run(main())


# ── proof 7: the readiness gate (order-8 — refuse BEFORE quiesce) ────────────

def _refusal_sides(tmp_path, config_dir):
    from spectra.services.handover import SpectraSide

    spot = RecordedSide(lo.SPOT_EFFECTS)
    return spot, {lo.SPOT_EFFECTS: spot,
                  lo.SPECTRA: SpectraSide(config_dir=str(config_dir),
                                          open_audio=False)}


def _assert_refused_room_untouched(tmp_path, spot, exc):
    # The old owner was never quiesced — not one call reached its side —
    # and the ownership record never moved (the file was never written).
    assert spot.calls == []
    assert lo.load().owner == lo.SPOT_EFFECTS
    assert not lo.OWNERSHIP_FILE.exists()
    # The refusal names the missing preparation and the seeder command.
    from spectra.services.handover import FX_LIVE_SEED_COMMAND
    assert FX_LIVE_SEED_COMMAND in str(exc.value)


def test_missing_fx_live_config_refuses_before_quiesce(tmp_path):
    from spectra.services.handover import HandoverRefused, run_handover

    _own_file(tmp_path)
    spot, sides = _refusal_sides(tmp_path, tmp_path / "never-seeded")

    async def main():
        with pytest.raises(HandoverRefused) as exc:
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        _assert_refused_room_untouched(tmp_path, spot, exc)

    _run(main())


def test_empty_fx_live_config_refuses_before_quiesce(tmp_path):
    from spectra.services.handover import HandoverRefused, run_handover

    _own_file(tmp_path)
    config_dir = tmp_path / "fx-live"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"devices": [], "virtuals": []}))
    spot, sides = _refusal_sides(tmp_path, config_dir)

    async def main():
        with pytest.raises(HandoverRefused) as exc:
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        _assert_refused_room_untouched(tmp_path, spot, exc)

    _run(main())


def test_zero_usable_virtuals_refuses_before_quiesce(tmp_path):
    """Devices exist but none of a vendored driver type backs any virtual —
    the host would skip them all and activate empty-handed."""
    from spectra.services.handover import HandoverRefused, run_handover

    _own_file(tmp_path)
    config_dir = tmp_path / "fx-live"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "devices": [{"id": "strip", "type": "not-a-vendored-driver",
                     "config": {"name": "strip", "pixel_count": 64}}],
        "virtuals": [{"id": "strip", "config": {"name": "strip"},
                      "segments": [["strip", 0, 63, False]]}],
    }))
    spot, sides = _refusal_sides(tmp_path, config_dir)

    async def main():
        with pytest.raises(HandoverRefused) as exc:
            await run_handover(lo.SPECTRA, sides, grace_s=0)
        _assert_refused_room_untouched(tmp_path, spot, exc)

    _run(main())


def test_seeded_config_passes_readiness(tmp_path):
    from spectra.services.handover import SpectraSide

    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))
    side = SpectraSide(config_dir=str(config_dir), open_audio=False)
    assert _run(side.readiness_problems()) == []


def test_handover_api_armed_but_unseeded_is_412(tmp_path, monkeypatch):
    from spectra import config as spectra_config
    from spectra.api.ownership import HandoverRequest, post_handover

    _own_file(tmp_path)
    monkeypatch.setenv("SPECTRA_HANDOVER_ARMED", "1")
    monkeypatch.setattr(spectra_config, "FX_LIVE_CONFIG_DIR",
                        tmp_path / "never-seeded")

    async def main():
        resp = await post_handover(HandoverRequest(to=lo.SPECTRA))
        body = json.loads(bytes(resp.body))
        assert resp.status_code == 412
        assert body["result"] == "refused-preparation-missing"
        assert "seed_spectra_fx_live" in body["error"]
        # Room untouched: record never moved, never even written.
        assert lo.load().owner == lo.SPOT_EFFECTS
        assert not lo.OWNERSHIP_FILE.exists()

    _run(main())


def test_reverse_handover_refuses_on_missing_ledfx_unit(monkeypatch):
    from spectra.services import handover as handover_svc

    async def fake_systemctl(*args):
        assert args == ("cat", "ledfx")
        return 1, "No files found for ledfx.service."

    monkeypatch.setattr(handover_svc, "_systemctl", fake_systemctl)
    side = handover_svc.SpotEffectsSide()
    problems = _run(side.readiness_problems())
    assert problems and "ledfx" in problems[0]

    async def ok_systemctl(*args):
        return 0, "# ledfx.service"

    monkeypatch.setattr(handover_svc, "_systemctl", ok_systemctl)
    assert _run(side.readiness_problems()) == []


# ── offline guarantee ────────────────────────────────────────────────────────

def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
