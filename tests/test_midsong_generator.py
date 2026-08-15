"""Unit proof for midsong_generator._normalized_intensities' 2026-08-15 edge
trim (module docstring's EDGE TRIM section): a cold open / fade-out no
longer sets the min-max floor, and the trimmed edge sections themselves
clamp to [0, 1] instead of being floored like a middle section.

Pure function, no I/O — sections are plain dicts, no storage fixtures.
"""
from __future__ import annotations

from spectra.services.midsong_generator import (EDGE_TRIM_MS, INTENSITY_FLOOR,
                                                 _normalized_intensities)


def _sec(start_ms, end_ms, energy_rms):
    return {"start_ms": start_ms, "end_ms": end_ms, "energy_rms": energy_rms}


def test_quiet_middle_section_reads_low_once_the_cold_open_is_trimmed():
    """The exact complaint: a near-silent 10s cold open used to set the
    floor for the whole song, so a genuinely quiet 20s passage in the
    middle landed far above INTENSITY_FLOOR. Trimming the open out of the
    lo/hi calculation lets that middle passage read near-zero instead."""
    sections = [
        _sec(0, 15_000, 0.02),         # cold open — EDGE (start < 15s)
        _sec(15_000, 35_000, 0.10),    # quiet verse, genuinely the middle's floor
        _sec(35_000, 60_000, 0.35),    # build
        _sec(60_000, 100_000, 0.90),   # drop
        _sec(100_000, 120_000, 0.05),  # fade-out — EDGE (end > duration-15s)
    ]
    out = _normalized_intensities(sections)
    assert out[1] == INTENSITY_FLOOR, (
        "the quiet verse IS the middle's floor once the cold open is "
        "excluded — it should land at the floor, not compressed upward "
        "by the cold open's even-lower value")
    assert out[3] == 1.0, "the drop remains the middle's ceiling"
    assert 0.0 < out[2] < out[3], "the build sits between floor and ceiling"


def test_edge_sections_clamp_to_zero_instead_of_going_negative():
    """A cold open quieter than the trimmed middle's own floor would
    normalize negative under the middle-derived lo/hi — clamped to exactly
    0, not floored like a middle section (his words: they'd 'probably be
    negative after the normalization')."""
    sections = [
        _sec(0, 15_000, 0.0),          # silent open — quieter than any middle value
        _sec(15_000, 45_000, 0.20),
        _sec(45_000, 70_000, 0.80),
        _sec(70_000, 90_000, 0.0),     # silent tail
    ]
    out = _normalized_intensities(sections)
    assert out[0] == 0.0, "the silent open clamps to true zero, no floor"
    assert out[3] == 0.0, "the silent tail clamps to true zero, no floor"
    assert out[1] == INTENSITY_FLOOR, "the middle's own quietest point still gets the floor"


def test_loud_edge_section_is_not_forced_to_zero():
    """An edge section louder than anything in the middle clamps at 1.0,
    not forced to zero — the clamp is a ceiling/floor on the computed
    value, never a blanket override of the edge sections."""
    sections = [
        _sec(0, 15_000, 1.0),          # a hot cold-open, louder than the middle
        _sec(15_000, 50_000, 0.20),
        _sec(50_000, 70_000, 0.30),
        _sec(70_000, 90_000, 0.5),     # tail filler, itself EDGE (end > duration-15s)
    ]
    out = _normalized_intensities(sections)
    assert out[0] == 1.0, (
        "a genuinely loud edge section clamps at the ceiling (1.0), not "
        "forced to zero — the raw stretch here (8.0, since it's far above "
        "the middle's own tiny 0.20-0.30 range) proves the clamp actually "
        "engaged rather than coincidentally landing at 1.0")


def test_track_shorter_than_double_the_trim_falls_back_to_pre_trim_behavior():
    """No middle survives trimming both ends of a track under ~2x
    EDGE_TRIM_MS — falls back to the ORIGINAL (untrimmed) algorithm for
    that song rather than degrading to an all-zero/all-floored result."""
    sections = [
        _sec(0, 10_000, 0.1),
        _sec(10_000, 20_000, 0.9),
    ]
    assert 20_000 < 2 * EDGE_TRIM_MS, "sanity: this fixture is under the fallback threshold"
    out = _normalized_intensities(sections)
    # Pre-trim formula: lo=0.1, hi=0.9, span=0.8 -> FLOOR + stretch*(1-FLOOR)
    assert out[0] == round(INTENSITY_FLOOR, 3)
    assert out[1] == 1.0


def test_zero_span_still_falls_back_to_flat_half():
    out = _normalized_intensities([_sec(0, 5_000, 0.5), _sec(5_000, 10_000, 0.5)])
    assert out == [0.5, 0.5]


def test_empty_sections_returns_empty():
    assert _normalized_intensities([]) == []
