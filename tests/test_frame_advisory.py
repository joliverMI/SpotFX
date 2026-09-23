"""services/frame_advisory.py — the Ship 2 frame-mismatch advisory's own
rule, in isolation (data/false-lock-continued-search/report.md §4).
"""
from __future__ import annotations

from services import frame_advisory


def test_evaluate_is_silent_without_a_hard_lock():
    result = frame_advisory.evaluate(
        locked=False, lock_offset_ms=5000, has_authored_triggers=True, band_ms=0,
    )
    assert result.suspect is False
    assert result.distance_ms is None


def test_evaluate_is_silent_with_no_band_to_compare_against():
    """A fresh session's very first lock, with the systemic learner not yet
    confident, has nothing to judge distance against — never a guess."""
    result = frame_advisory.evaluate(
        locked=True, lock_offset_ms=5000, has_authored_triggers=True, band_ms=None,
    )
    assert result.suspect is False
    assert result.distance_ms is None


def test_evaluate_is_silent_for_a_generated_only_song():
    """No hand-placed marks to be in the wrong frame."""
    result = frame_advisory.evaluate(
        locked=True, lock_offset_ms=5000, has_authored_triggers=False, band_ms=0,
    )
    assert result.suspect is False


def test_evaluate_fires_past_the_threshold():
    result = frame_advisory.evaluate(
        locked=True, lock_offset_ms=4274, has_authored_triggers=True, band_ms=-600,
    )
    assert result.distance_ms == 4874
    assert result.suspect is True


def test_evaluate_stays_quiet_inside_the_threshold():
    result = frame_advisory.evaluate(
        locked=True, lock_offset_ms=-475, has_authored_triggers=True, band_ms=-600,
    )
    assert result.distance_ms == 125
    assert result.suspect is False


def test_evaluate_boundary_is_strictly_greater_than():
    band = 0
    result = frame_advisory.evaluate(
        locked=True, lock_offset_ms=frame_advisory.FRAME_SUSPECT_DISTANCE_MS,
        has_authored_triggers=True, band_ms=band,
    )
    assert result.suspect is False  # exactly at threshold — not past it
    result2 = frame_advisory.evaluate(
        locked=True, lock_offset_ms=frame_advisory.FRAME_SUSPECT_DISTANCE_MS + 1,
        has_authored_triggers=True, band_ms=band,
    )
    assert result2.suspect is True


def test_room_band_prefers_the_systemic_center_when_confident():
    band = frame_advisory.room_band_ms(
        systemic_center_ms=-286, systemic_confidence=0.60,
        session_locked_offsets_ms=[4269, 4125],
    )
    assert band == -286


def test_room_band_falls_back_to_session_median_when_not_confident():
    band = frame_advisory.room_band_ms(
        systemic_center_ms=-286, systemic_confidence=0.10,
        session_locked_offsets_ms=[-475, -725, -900],
    )
    assert band == -725


def test_room_band_is_none_with_nothing_to_offer():
    band = frame_advisory.room_band_ms(
        systemic_center_ms=None, systemic_confidence=0.0,
        session_locked_offsets_ms=[],
    )
    assert band is None
