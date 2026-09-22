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


# ═══ Phase 2 beat-snap wiring (2026-09-22) ════════════════════════════════

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_snap_env(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "spectra" / "testbed" / "analysis")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "spectra" / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "spectra" / "room_controls.json")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False


GEN_URI = "spotify:track:midsong-beat-snap"
STEM = "Snap Artist - Snap Song"


def _seed_song(scfg, *, tempo_bpm=120.0):
    """A section boundary at 2150ms, 150ms from a 500ms-spaced downbeat
    grid's 2000ms downbeat — well inside the one-beat cap."""
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": GEN_URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": GEN_URI,
        "tempo_bpm": tempo_bpm,
        "sections": [
            {"start_ms": 0, "end_ms": 2150, "label": "intro", "energy_rms": 0.1},
            {"start_ms": 2150, "end_ms": 20000, "label": "drop", "energy_rms": 0.9},
        ],
        "beats": [{"ms": i * 500, "is_downbeat": (i % 4 == 0)} for i in range(10)],
    }), encoding="utf-8")


def test_generation_snaps_onto_the_nearest_downbeat_by_default():
    from spectra import config as scfg
    from spectra.services import midsong_generator, trigger_store
    _seed_song(scfg)

    moments = midsong_generator.candidate_moments(GEN_URI)
    assert len(moments) == 1
    m = moments[0]
    assert m.timestamp_ms == 2000, "snapped from the raw 2150ms boundary onto the 2000ms downbeat"
    assert m.snap_grid == "librosa"
    assert m.snap_moved_ms == -150
    assert m.generator_key == "section:2150", "the key stays tied to the RAW section boundary"

    midsong_generator.generate_for_song(GEN_URI)
    [trig] = trigger_store.list_for_song(GEN_URI)
    assert trig.timestamp_ms == 2000
    assert trig.snap_grid == "librosa"
    assert trig.snap_moved_ms == -150
    assert trig.generator_key == "section:2150"


def test_snap_setting_off_leaves_the_raw_section_time():
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls
    _seed_song(scfg)
    room_controls.save_room_controls(
        room_controls.RoomControlState(midsong_snap_to_beat=False))

    [m] = midsong_generator.candidate_moments(GEN_URI)
    assert m.timestamp_ms == 2150, "unsnapped — the raw section-boundary time"
    assert m.snap_grid is None
    assert m.snap_moved_ms is None


def test_toggling_the_setting_updates_the_same_trigger_in_place():
    """The setting flip is a regular regeneration UPDATE, never a
    delete+re-add under a different key — the generator_key stays tied to
    the section's own raw boundary regardless of snapping."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls, trigger_store
    _seed_song(scfg)

    summary1 = midsong_generator.generate_for_song(GEN_URI)
    assert summary1 == {"moments": 1, "added": 1, "updated": 0, "deleted": 0,
                        "skipped_authored": 0}
    [trig_before] = trigger_store.list_for_song(GEN_URI)
    assert trig_before.timestamp_ms == 2000

    room_controls.save_room_controls(
        room_controls.RoomControlState(midsong_snap_to_beat=False))
    summary2 = midsong_generator.generate_for_song(GEN_URI)
    assert summary2 == {"moments": 1, "added": 0, "updated": 1, "deleted": 0,
                        "skipped_authored": 0}, (
        "the setting flip UPDATES the same trigger — never adds a new one "
        "or deletes and re-adds under a different generator_key")
    [trig_after] = trigger_store.list_for_song(GEN_URI)
    assert trig_after.id == trig_before.id
    assert trig_after.timestamp_ms == 2150
    assert trig_after.snap_grid is None


def test_regenerating_unchanged_is_still_a_pure_no_op_with_snapping_on():
    from spectra import config as scfg
    from spectra.services import midsong_generator
    _seed_song(scfg)
    midsong_generator.generate_for_song(GEN_URI)
    summary = midsong_generator.generate_for_song(GEN_URI)
    assert summary == {"moments": 1, "added": 0, "updated": 0, "deleted": 0,
                       "skipped_authored": 0}


def test_snap_cap_leaves_a_far_boundary_at_its_raw_section_time():
    from spectra import config as scfg
    from spectra.services import midsong_generator
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": GEN_URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": GEN_URI,
        "tempo_bpm": 120.0,
        "sections": [
            {"start_ms": 0, "end_ms": 2600, "label": "intro", "energy_rms": 0.1},
            {"start_ms": 2600, "end_ms": 20000, "label": "drop", "energy_rms": 0.9},
        ],
        # nearest downbeat is 2000ms, 600ms away — past the 500ms beat cap
        "beats": [{"ms": 0, "is_downbeat": True}, {"ms": 2000, "is_downbeat": True}],
    }), encoding="utf-8")
    [m] = midsong_generator.candidate_moments(GEN_URI)
    assert m.timestamp_ms == 2600
    assert m.snap_grid is None
