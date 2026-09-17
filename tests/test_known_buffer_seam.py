"""THE RULED SEAM — the show clock, LOCK-GATED (firstmate, 2026-09-17).

    show_clock_ms = effective_position_ms + av_sync_lead_ms - compensation_ms

    compensation_ms = 0                            gate shut   -> "gate"
                    = 0                            lock present -> "lock"
                    = effective_value - reference  otherwise    -> "applied"

THE MEASURED FACT THE RULING RESTS ON, so nobody has to re-derive it: the
xcorr lock correlates against `snapcast.monitor`, and `snapcast.monitor` is
the monitor of the sink `snapclient` plays INTO — speaker time, downstream
of the snapserver buffer, the network, the snapclient, and therefore
downstream of the source-side segment River publishes. So a locked song
already absorbs this buffer and a delta on top would correct the same
milliseconds twice; an unlocked song absorbs none of it, because
`bridge.effective_position_ms()` is then the raw Spotify position.

The unconditional delta was REJECTED for exactly that double correction.
"""
from __future__ import annotations

import time

import pytest

from spectra import config as scfg
from spectra.services import av_sync_lead
from spectra.services import known_buffer as kb
from spectra.services import room_controls as rc


@pytest.fixture(autouse=True)
def _room(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    rc.save_room_controls(rc.RoomControlState(known_buffer_source_url="http://river"))


def _reading(value, **over):
    body = {"effects_fire_later_by_ms": value, "t_ms": int(time.time() * 1000),
            "source": "measured", "epoch": 0, "floor_clamped": False,
            "governed": True, "floor_ms": 500}
    body.update(over)
    return body


def _ungated(value, **over):
    return kb.record(_reading(value, **over))


# ── the three answers ───────────────────────────────────────────────────
def test_gate_shut_subtracts_nothing_and_says_gate():
    kb.record(_reading(500, floor_clamped=True, governed=False))
    state = kb.state(lock=False)
    assert state["compensation_ms"] == 0
    assert state["compensation_reason"] == "gate"
    assert state["applied"] is False
    assert kb.compensation_ms() == 0


def test_a_present_lock_subtracts_nothing_and_says_lock():
    """The lock taps speaker time, so it is ALREADY tracking this buffer.
    A delta here is the double correction the ruling rejects."""
    _ungated(900)
    _ungated(1400, t_ms=int(time.time() * 1000) + 1)
    state = kb.state(lock=True)
    assert state["compensation_ms"] == 0
    assert state["compensation_reason"] == "lock"
    assert state["applied"] is False
    assert "audio lock is already tracking it" in state["sentence"]


def test_no_lock_applies_the_reference_based_delta_both_ways():
    """Worked, both signs. Reference 900 (the first ungated reading).
         grows to 1200 -> +300: fire 300 ms LATER
         drains to 620 -> -280: fire 280 ms less late"""
    now = int(time.time() * 1000)
    _ungated(900, t_ms=now)
    assert kb.state(lock=False)["reference_ms"] == 900
    assert kb.state(lock=False)["compensation_ms"] == 0

    _ungated(1200, t_ms=now + 1000)
    state = kb.state(lock=False)
    assert (state["compensation_ms"], state["compensation_reason"]) == (300, "applied")
    assert "300 ms later" in state["sentence"]

    _ungated(620, t_ms=now + 2000, epoch=1, discontinuity=True)
    state = kb.state(lock=False)
    assert (state["compensation_ms"], state["compensation_reason"]) == (-280, "applied")
    assert "280 ms less late" in state["sentence"]


def test_an_unknowable_lock_is_treated_as_present():
    """The safe direction: applying a delta on top of a lock that is
    quietly still running is the failure this seam exists to avoid."""
    _ungated(900)
    _ungated(1200, t_ms=int(time.time() * 1000) + 1)
    assert kb.compensation(kb._reading, rc.load_room_controls(),
                           kb._reference_ms, None, "fresh") == (0, "lock")


# ── the transitions: no smoothing, either way ───────────────────────────
def test_a_lock_dropping_mid_song_applies_the_delta_at_once():
    now = int(time.time() * 1000)
    _ungated(900, t_ms=now)
    _ungated(1200, t_ms=now + 1000)
    assert kb.state(lock=True)["compensation_ms"] == 0
    # the lock's absorption vanished with it — the full delta, immediately,
    # with nothing in between.
    assert kb.state(lock=False)["compensation_ms"] == 300


def test_a_lock_appearing_returns_the_compensation_to_zero_at_once():
    now = int(time.time() * 1000)
    _ungated(900, t_ms=now)
    _ungated(1200, t_ms=now + 1000)
    assert kb.state(lock=False)["compensation_ms"] == 300
    assert kb.state(lock=True)["compensation_ms"] == 0
    assert kb.state(lock=True)["compensation_reason"] == "lock"


def test_no_value_is_ever_produced_between_the_two_states():
    """Structural, not sampled: compensation() is a pure function of the
    lock flag, so there is no third answer it could interpolate to."""
    now = int(time.time() * 1000)
    _ungated(900, t_ms=now)
    _ungated(1200, t_ms=now + 1000)
    st = rc.load_room_controls()
    seen = {kb.compensation(kb._reading, st, kb._reference_ms, lock, "fresh")
            for lock in (True, False, None)}
    assert seen == {(0, "lock"), (300, "applied")}


# ── the formula, at the one application point ───────────────────────────
def test_the_show_clock_subtracts_because_the_families_are_opposite():
    """LEAD family positive = EARLIER; this term positive = LATER. Adding
    them with one sign would silently invert one of the two."""
    assert av_sync_lead.show_clock_ms(10_000, 120, 0) == 10_120
    assert av_sync_lead.show_clock_ms(10_000, 120, 300) == 9_820     # 300 LATER
    assert av_sync_lead.show_clock_ms(10_000, 120, -280) == 10_400   # less late
    assert av_sync_lead.show_clock_ms(10_000, -38, 300) == 9_662


def test_the_new_term_defaults_to_byte_identical_behaviour():
    for position in (0, 1, 10_000, 250_000):
        for lead in (None, 0, -38, 120, -2000, 2000):
            assert (av_sync_lead.show_clock_ms(position, lead)
                    == av_sync_lead.show_clock_ms(position, lead, 0))
    assert av_sync_lead.show_clock_ms(None, 120, 900) is None


def test_the_compensation_falls_to_zero_rather_than_breaking_the_clock(monkeypatch):
    """A fault anywhere in this feature must cost the correction, never the
    clock: the trigger poll ticks on every song, every 200 ms."""
    monkeypatch.setattr(kb, "_settings", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert kb.compensation_ms() == 0


def test_the_missing_state_subtracts_nothing_even_though_the_floor_applies():
    """The FLOOR is what the value READS as; it is not a delta to subtract.
    Missing means nothing has been heard, which is never a reason to move
    his show clock."""
    assert kb.state(lock=False)["state"] == "missing"
    assert kb.state(lock=False)["effects_fire_later_by_ms"] == 500
    assert kb.state(lock=False)["compensation_ms"] == 0
    assert kb.compensation_ms() == 0


# ── the reason reaches the raw series too ───────────────────────────────
def test_the_raw_series_records_which_answer_each_reading_produced():
    _ungated(900)
    rows = kb.read_log()
    assert rows[-1]["compensation_reason"] in ("applied", "lock")
    assert "effects_fire_later_by_ms" in rows[-1]


# ── and the lead is untouched by all of it ──────────────────────────────
def test_av_sync_lead_semantics_and_bounds_are_unchanged():
    assert (av_sync_lead.LEAD_MIN_MS, av_sync_lead.LEAD_MAX_MS) == (-2000, 2000)
    assert rc.field_bounds("av_sync_lead_ms") == (-2000, 2000)
    assert rc.RoomControlState().av_sync_lead_ms is None
    assert av_sync_lead.direction_sentence(120).startswith("Lights will fire 120 ms EARLIER")
