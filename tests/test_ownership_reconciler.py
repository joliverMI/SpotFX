"""Continuous record-vs-reality reconciler — offline proof (report gate e3,
two-writers incident 2026-08-13, owner-ruled prevention build).

Covers both halves: spectra/services/ownership_reconciler.py (while spectra
owns: ledfx.service must be inactive, no foreign WLED realtime source) and
services/spectra_liveness_reconciler.py (while spot-effects owns: SPECTRA's
liveness must not be live/split-brain). Both directions of violation
detection, the escalation knob's off-by-default posture and its armed
behavior, and graceful degradation when a signal can't be read at all
(never treated as proof of a violation).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import light_ownership as lo

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _restore_ownership_file():
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


def _own_file(tmp_path) -> None:
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"


# ── spectra-side: check() ────────────────────────────────────────────────────

def test_check_vacuous_when_spectra_does_not_own(tmp_path, monkeypatch):
    from spectra.services import ownership_reconciler as recon

    _own_file(tmp_path)  # default record: spot-effects owns

    async def boom():
        raise AssertionError("must not check ledfx when spectra doesn't own")

    monkeypatch.setattr(recon, "_ledfx_service_active", boom)

    result = _run(recon.check())
    assert result.violated is False
    assert result.reasons == []


def test_check_flags_ledfx_active_while_spectra_owns(tmp_path, monkeypatch):
    from spectra.services import ownership_reconciler as recon

    _own_file(tmp_path)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    async def active():
        return True

    async def no_foreign():
        return []

    monkeypatch.setattr(recon, "_ledfx_service_active", active)
    monkeypatch.setattr(recon, "_foreign_wled_sources", no_foreign)

    result = _run(recon.check())
    assert result.violated is True
    assert "ledfx.service" in result.reasons[0]


def test_check_flags_foreign_wled_source_while_spectra_owns(tmp_path, monkeypatch):
    from spectra.services import ownership_reconciler as recon

    _own_file(tmp_path)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    async def inactive():
        return False

    async def foreign():
        return ["crystal (lip=10.0.0.99)"]

    monkeypatch.setattr(recon, "_ledfx_service_active", inactive)
    monkeypatch.setattr(recon, "_foreign_wled_sources", foreign)

    result = _run(recon.check())
    assert result.violated is True
    assert "crystal" in result.reasons[0]


def test_check_clean_when_both_conditions_hold(tmp_path, monkeypatch):
    from spectra.services import ownership_reconciler as recon

    _own_file(tmp_path)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    async def inactive():
        return False

    async def no_foreign():
        return []

    monkeypatch.setattr(recon, "_ledfx_service_active", inactive)
    monkeypatch.setattr(recon, "_foreign_wled_sources", no_foreign)

    result = _run(recon.check())
    assert result.violated is False


def test_foreign_wled_sources_ignores_own_ip_and_unreachable_devices(monkeypatch):
    """The "foreign" test is IP-based (own host vs someone else's), and an
    unreachable device is skipped, not flagged — it can't be painting
    anything if we can't even reach it."""
    from spectra.services import ownership_reconciler as recon

    class FakeDevice:
        def __init__(self, id, wled):
            self.id = id
            self.wled = wled

    class FakeWLED:
        def __init__(self, state=None, raises=False):
            self._state = state
            self._raises = raises

        async def get_state(self):
            if self._raises:
                raise ConnectionError("unreachable")
            return self._state

    class FakeHost:
        def __init__(self, devices):
            self.devices = {d.id: d for d in devices}

    class FakeLive:
        def __init__(self, host):
            self.host = host

    import fx.utils as fx_utils
    monkeypatch.setattr(fx_utils, "get_local_ip", lambda: "10.0.0.5")

    devices = [
        FakeDevice("own-source", FakeWLED({"live": True, "lip": "10.0.0.5"})),
        FakeDevice("idle", FakeWLED({"live": False, "lip": None})),
        FakeDevice("rogue", FakeWLED({"live": True, "lip": "192.168.1.50"})),
        FakeDevice("unreachable", FakeWLED(raises=True)),
        FakeDevice("not-wled", None),
    ]
    fake_live = FakeLive(FakeHost(devices))

    import spectra.services.live_host as live_host_module
    monkeypatch.setattr(live_host_module, "live", fake_live)

    foreign = _run(recon._foreign_wled_sources())
    assert foreign == ["rogue (lip=192.168.1.50)"]


# ── spectra-side: _tick() escalation knob ────────────────────────────────────

def test_tick_alarms_but_does_not_escalate_when_unarmed(tmp_path, monkeypatch, caplog):
    from spectra.services import ownership_reconciler as recon

    caplog.set_level("CRITICAL", logger="spectra.services.ownership_reconciler")
    _own_file(tmp_path)
    monkeypatch.delenv("SPECTRA_RECONCILER_ESCALATE", raising=False)
    recon._alarmed = False
    recon._violation_streak = 0

    async def violated():
        return recon.ReconcileResult(violated=True, reasons=["ledfx.service is active"])

    escalated = []

    async def fake_escalate(reasons):
        escalated.append(reasons)

    monkeypatch.setattr(recon, "check", violated)
    monkeypatch.setattr(recon, "_escalate", fake_escalate)

    for _ in range(recon.ESCALATE_AFTER_TICKS + 3):
        _run(recon._tick())

    assert escalated == []
    assert any("VIOLATION" in r.message for r in caplog.records)


def test_tick_escalates_after_sustained_violation_when_armed(tmp_path, monkeypatch):
    from spectra.services import ownership_reconciler as recon

    _own_file(tmp_path)
    monkeypatch.setenv("SPECTRA_RECONCILER_ESCALATE", "1")
    recon._alarmed = False
    recon._violation_streak = 0

    async def violated():
        return recon.ReconcileResult(violated=True, reasons=["ledfx.service is active"])

    escalated = []

    async def fake_escalate(reasons):
        escalated.append(reasons)

    monkeypatch.setattr(recon, "check", violated)
    monkeypatch.setattr(recon, "_escalate", fake_escalate)

    for _ in range(recon.ESCALATE_AFTER_TICKS - 1):
        _run(recon._tick())
    assert escalated == []  # not sustained long enough yet

    _run(recon._tick())
    assert len(escalated) == 1


def test_escalate_calls_release_room(tmp_path, monkeypatch):
    from spectra.services import ownership_reconciler as recon

    _own_file(tmp_path)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    released = []

    async def fake_release(reason):
        released.append(reason)
        return lo.load()

    import spectra.services.release as release_module
    monkeypatch.setattr(release_module, "release_room", fake_release)

    _run(recon._escalate(["ledfx.service is active"]))
    assert len(released) == 1
    assert "ledfx.service is active" in released[0]


# ── spot-effects side: _spectra_liveness / _tick ─────────────────────────────

def test_spot_side_tick_noop_when_not_owner(tmp_path, monkeypatch):
    from services import spectra_liveness_reconciler as recon

    _own_file(tmp_path)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))

    async def boom():
        raise AssertionError("must not poll SPECTRA when not spot-effects owner")

    monkeypatch.setattr(recon, "_spectra_liveness", boom)
    _run(recon._tick())  # must not raise


def test_spot_side_flags_live_and_split_brain(tmp_path, monkeypatch, caplog):
    from services import spectra_liveness_reconciler as recon

    caplog.set_level("CRITICAL", logger="services.spectra_liveness_reconciler")
    _own_file(tmp_path)  # default: spot-effects owns
    recon._alarmed = False
    recon._violation_streak = 0

    for state in ("live", "split-brain"):
        caplog.clear()

        async def body(state=state):
            return {"state": state, "owner": "spectra"}

        monkeypatch.setattr(recon, "_spectra_liveness", body)
        _run(recon._tick())
        assert any("VIOLATION" in r.message for r in caplog.records), state


def test_spot_side_clean_states_never_alarm(tmp_path, monkeypatch, caplog):
    from services import spectra_liveness_reconciler as recon

    caplog.set_level("CRITICAL", logger="services.spectra_liveness_reconciler")
    _own_file(tmp_path)
    recon._alarmed = False
    recon._violation_streak = 0

    for state in ("dark", "released", "switching"):
        caplog.clear()

        async def body(state=state):
            return {"state": state, "owner": "spot-effects"}

        monkeypatch.setattr(recon, "_spectra_liveness", body)
        _run(recon._tick())
        assert not any(r.levelname == "CRITICAL" for r in caplog.records), state


def test_spot_side_unreachable_spectra_is_not_a_violation(tmp_path, monkeypatch, caplog):
    from services import spectra_liveness_reconciler as recon

    caplog.set_level("CRITICAL", logger="services.spectra_liveness_reconciler")
    _own_file(tmp_path)
    recon._alarmed = False
    recon._violation_streak = 0

    async def unreachable():
        return None

    monkeypatch.setattr(recon, "_spectra_liveness", unreachable)
    _run(recon._tick())
    assert not any(r.levelname == "CRITICAL" for r in caplog.records)
