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
    analysis_reader._capture_offset_cache.clear()


GEN_URI = "spotify:track:midsong-beat-snap"
STEM = "Snap Artist - Snap Song"


def _seed_song(scfg, *, tempo_bpm=120.0):
    """A section boundary at 2150ms, 150ms from a 500ms-spaced downbeat
    grid's 2000ms downbeat — well inside the one-beat cap. A FLAT
    rms_bass (no jumps, never quiet) so R3's rhythmic-edge search (2026-
    09-23) finds nothing and these Phase-2-focused fixtures still exercise
    only the R1 downbeat-snap fallback they were written for."""
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": GEN_URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": GEN_URI,
        "tempo_bpm": tempo_bpm,
        "sections": [
            {"start_ms": 0, "end_ms": 2150, "label": "intro", "energy_rms": 0.1},
            {"start_ms": 2150, "end_ms": 20000, "label": "drop", "energy_rms": 0.9},
        ],
        "beats": [{"ms": i * 500, "is_downbeat": (i % 4 == 0), "rms_bass": 0.5}
                 for i in range(10)],
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


# ═══ FRAME FIX (2026-09-23, data/transition-alignment-plan/report.md) ═════


def _seed_npz_offset(scfg, stem: str, offset_ms: int) -> None:
    """A capture-offset sidecar whose WAV sample 0 sits `offset_ms` into
    song time — testbed_audio.capture_offset_ms's own source."""
    import numpy as np
    np.savez(scfg.AUDIO_SHAPES_DIR / f"{stem}.npz",
              timestamps_ms=np.array([offset_ms, offset_ms + 100, offset_ms + 200]),
              rms_total=np.array([0.1, 0.2, 0.1]))


def test_frame_fix_moves_a_cue_later_by_exactly_the_capture_offset():
    """The report's own §2.1 formula: a section boundary at WAV time
    raw_ms fires `raw_ms + capture_offset_ms` in song time — snap
    disabled here so the frame effect is isolated (matching the report's
    own "Frame fixed" column, which is measured with Phase 2's separate
    beat-snap feature turned off)."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls
    _seed_song(scfg)
    room_controls.save_room_controls(
        room_controls.RoomControlState(midsong_snap_to_beat=False))
    _seed_npz_offset(scfg, STEM, 3000)

    [m] = midsong_generator.candidate_moments(GEN_URI, snap_enabled=False)
    assert m.timestamp_ms == 2150 + 3000, (
        "the cue fires 3000ms LATER in song time than its raw, WAV-time "
        "section boundary (2150ms)")
    assert m.generator_key == "section:2150", (
        "generator_key stays keyed on the RAW, unshifted WAV-time "
        "start_ms — a recapture changing the offset must UPDATE this "
        "same trigger in place, never orphan it under a new key")
    assert m.snap_grid is None and m.snap_moved_ms is None


def test_zero_capture_offset_is_a_no_op():
    """No npz sidecar at all (an unanalyzed capture, or a song whose
    recording genuinely started at song time 0) must reproduce EXACTLY
    the pre-fix placement — capture_offset_ms_or_zero returns 0."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, testbed_audio
    _seed_song(scfg)
    assert testbed_audio.capture_offset_ms_or_zero(GEN_URI) == 0

    [m] = midsong_generator.candidate_moments(GEN_URI)
    # Byte-identical to test_generation_snaps_onto_the_nearest_downbeat_by_default
    # above (default snap ON, offset 0): unaffected by this fix.
    assert m.timestamp_ms == 2000
    assert m.snap_grid == "librosa"
    assert m.snap_moved_ms == -150
    assert m.generator_key == "section:2150"


def test_frame_fix_shifts_the_snap_grid_identically_so_the_snap_still_lands():
    """beat_snap's own comparison stays single-frame (its "ONE FRAME, NO
    SHIFT" docstring) — the grid this caller hands it has been shifted by
    the identical offset, so a cue that would have snapped in WAV time
    still snaps by the same relative distance in song time, just `offset`
    ms later than an unshifted snap would have landed."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls
    _seed_song(scfg)  # raw boundary 2150ms, nearest librosa downbeat 2000ms
    room_controls.save_room_controls(
        room_controls.RoomControlState(midsong_snap_to_beat=True))
    _seed_npz_offset(scfg, STEM, 5000)

    [m] = midsong_generator.candidate_moments(GEN_URI)
    assert m.timestamp_ms == 2000 + 5000, (
        "the snapped downbeat (2000ms in the WAV/analysis frame) shifted "
        "into song time by the same 5000ms offset")
    assert m.snap_grid == "librosa"
    assert m.snap_moved_ms == -150, (
        "the relative distance moved by snapping is unaffected by the "
        "frame shift — only the absolute placement moved")
    assert m.generator_key == "section:2150"


def test_shift_song_grid_helper_is_identity_at_zero_offset():
    from spectra.services import beat_snap
    from spectra.services.midsong_generator import _shift_song_grid
    grid = beat_snap.SongGrid("librosa", [0, 1000, 2000], 500.0)
    assert _shift_song_grid(grid, 0) is grid
    assert _shift_song_grid(None, 1234) is None


def test_shift_song_grid_helper_shifts_every_downbeat():
    from spectra.services import beat_snap
    from spectra.services.midsong_generator import _shift_song_grid
    grid = beat_snap.SongGrid("librosa", [0, 1000, 2000], 500.0)
    shifted = _shift_song_grid(grid, 3692)
    assert shifted.downbeats == [3692, 4692, 5692]
    assert shifted.grid_name == "librosa"
    assert shifted.beat_length_ms == 500.0


# ═══ DENSITY + KNOB PLUMBING (2026-09-23, PLACEMENT RULE R3) ══════════════


def _seed_density_song(scfg, *, n_boundaries=20, tempo_bpm=120.0):
    """`n_boundaries` mid-song sections at 1000ms spacing (1000, 2000, ...,
    n*1000), plus the song's own opening at 0. Beats are spaced 500ms
    apart so each boundary lands exactly on an even beat index; each
    boundary's own beat carries a DISTINCT, ISOLATED bass-energy step
    (rms_bass[2i] = i, its odd neighbours 0) so
    rhythmic_edges.bass_step_at(boundary_ms) == i for the i-th boundary
    (1-indexed) — the density ranking's own strength score. Returns the
    list of (raw_ms, strength) pairs in chronological order."""
    n_beats = n_boundaries * 2 + 2
    rms_bass = [0.0] * n_beats
    pairs = []
    for i in range(1, n_boundaries + 1):
        beat_idx = i * 2
        rms_bass[beat_idx] = float(i)
        pairs.append((i * 1000, float(i)))
    beats = [{"ms": j * 500, "is_downbeat": False, "rms_bass": rms_bass[j]}
            for j in range(n_beats)]
    sections = [{"start_ms": 0, "end_ms": 1000, "label": "intro", "energy_rms": 0.1}]
    for i in range(1, n_boundaries + 1):
        sections.append({"start_ms": i * 1000, "end_ms": (i + 1) * 1000,
                         "label": "section", "energy_rms": 0.5})
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": GEN_URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": GEN_URI, "tempo_bpm": tempo_bpm, "sections": sections, "beats": beats,
    }), encoding="utf-8")
    return pairs


def test_density_cap_keeps_the_strongest_n_candidates(monkeypatch):
    """The RANKING itself — with the rate->count resolution patched out to
    a fixed N, matching the old flat transition_max_per_song semantics —
    see resolve_transition_count's own arithmetic tests below for the
    rate/duration/factor formula itself."""
    from spectra import config as scfg
    from spectra.services import midsong_generator
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: 5)
    pairs = _seed_density_song(scfg, n_boundaries=20)  # strengths 1..20

    moments = midsong_generator.candidate_moments(
        GEN_URI, snap_enabled=False, window_beats=1, sensitivity=1.5,
        direction="both", transitions_per_minute=1)

    assert len(moments) == 5, "only the 5 strongest candidates survive"
    kept_raw_ms = sorted(int(m.generator_key.split(":")[1]) for m in moments)
    expected = sorted(raw_ms for raw_ms, strength in pairs if strength > 15)  # top 5: 16..20
    assert kept_raw_ms == expected, (
        "the survivors are exactly the 5 boundaries with the largest "
        "bass-energy step size, not an arbitrary 5")


def test_density_cap_output_stays_chronologically_ordered(monkeypatch):
    from spectra import config as scfg
    from spectra.services import midsong_generator
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: 5)
    _seed_density_song(scfg, n_boundaries=20)
    moments = midsong_generator.candidate_moments(
        GEN_URI, snap_enabled=False, window_beats=1, sensitivity=1.5,
        direction="both", transitions_per_minute=1)
    timestamps = [m.timestamp_ms for m in moments]
    assert timestamps == sorted(timestamps), (
        "kept candidates are restored to chronological order after ranking")


def test_density_cap_is_a_no_op_when_fewer_candidates_exist_than_the_cap(monkeypatch):
    from spectra import config as scfg
    from spectra.services import midsong_generator
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: 12)
    _seed_density_song(scfg, n_boundaries=3)
    moments = midsong_generator.candidate_moments(
        GEN_URI, snap_enabled=False, window_beats=1, sensitivity=1.5,
        direction="both", transitions_per_minute=1)
    assert len(moments) == 3


def test_candidate_moments_reads_the_three_room_control_knobs_when_unset(monkeypatch):
    """Passing no window_beats/sensitivity/transitions_per_minute
    explicitly reads the live RoomControlState — proven by setting a room
    default rate that (through the patched identity resolver below) caps
    density well below the raw candidate count and confirming it actually
    takes effect."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: int(rate))
    _seed_density_song(scfg, n_boundaries=20)
    room_controls.save_room_controls(room_controls.RoomControlState(
        midsong_snap_to_beat=False, transition_window_beats=1,
        transition_edge_sensitivity=1.5, transitions_per_minute=6))
    moments = midsong_generator.candidate_moments(GEN_URI)
    assert len(moments) == 6, "the room's own transitions_per_minute took effect"


def test_explicit_transitions_per_minute_overrides_the_room_default(monkeypatch):
    from spectra import config as scfg
    from spectra.services import midsong_generator, room_controls
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: int(rate))
    _seed_density_song(scfg, n_boundaries=20)
    room_controls.save_room_controls(room_controls.RoomControlState(
        transitions_per_minute=6))
    moments = midsong_generator.candidate_moments(
        GEN_URI, snap_enabled=False, window_beats=1, sensitivity=1.5,
        transitions_per_minute=10)
    assert len(moments) == 10, "an explicit override wins over the room default"


def test_resolve_transition_count_is_rate_times_duration_times_factor(monkeypatch):
    """The actual arithmetic (2026-09-25, the Admiral's order): total =
    round(rate * duration_minutes * effective_intensity_scale_factor),
    clamped to [1, RESULT_CAP_PER_SONG]. effective_intensity_scale_factor
    is patched to an exact 1.0 here so the formula is checked on its own,
    without intensity_scale's own genre/bass-rank resolution (covered by
    that module's own tests) folded in."""
    from spectra.services import midsong_generator
    monkeypatch.setattr(midsong_generator, "effective_intensity_scale_factor",
                        lambda uri: 1.0)
    sections = [{"start_ms": 0, "end_ms": 180_000}]  # exactly 3 minutes
    assert midsong_generator.resolve_transition_count(
        GEN_URI, sections, transitions_per_minute=8.0) == 24
    assert midsong_generator.resolve_transition_count(
        GEN_URI, sections, transitions_per_minute=10.0) == 30


def test_resolve_transition_count_scales_with_the_intensity_scale_factor(monkeypatch):
    """His own addendum: "scale the value with the mark percentage for
    that song" — a hyped (higher-factor) song earns proportionally more
    transitions at the same rate and duration."""
    from spectra.services import midsong_generator
    sections = [{"start_ms": 0, "end_ms": 120_000}]  # 2 minutes
    monkeypatch.setattr(midsong_generator, "effective_intensity_scale_factor",
                        lambda uri: 0.5)
    half = midsong_generator.resolve_transition_count(
        GEN_URI, sections, transitions_per_minute=8.0)
    monkeypatch.setattr(midsong_generator, "effective_intensity_scale_factor",
                        lambda uri: 2.0)
    quadruple = midsong_generator.resolve_transition_count(
        GEN_URI, sections, transitions_per_minute=8.0)
    assert half == 8   # round(8 * 2 * 0.5)
    assert quadruple == 32  # round(8 * 2 * 2.0)


def test_resolve_transition_count_never_goes_below_one(monkeypatch):
    """Even a near-silent rate on a very short song still keeps one cue —
    his own requirement, unconditional."""
    from spectra.services import midsong_generator
    monkeypatch.setattr(midsong_generator, "effective_intensity_scale_factor",
                        lambda uri: 0.3)
    sections = [{"start_ms": 0, "end_ms": 3_000}]  # 3 seconds
    assert midsong_generator.resolve_transition_count(
        GEN_URI, sections, transitions_per_minute=1.0) == 1


def test_resolve_transition_count_is_capped_at_the_sanity_ceiling(monkeypatch):
    """An absurdly long track at a maxed-out rate is clamped, never left
    to silently blow past a usable density."""
    from spectra.services import midsong_generator
    monkeypatch.setattr(midsong_generator, "effective_intensity_scale_factor",
                        lambda uri: 2.0)
    sections = [{"start_ms": 0, "end_ms": 3_600_000}]  # 60 minutes
    assert midsong_generator.resolve_transition_count(
        GEN_URI, sections, transitions_per_minute=30.0) == midsong_generator.RESULT_CAP_PER_SONG


def test_generated_cue_provenance_records_an_edge_label():
    """A candidate placed onto a rhythmic edge carries "edge:up"/"edge:down"
    provenance, distinct from the downbeat grids' "librosa"/"beat_this" —
    visible on the Review page exactly like Phase 2's own snap_grid."""
    from spectra import config as scfg
    from spectra.services import midsong_generator
    tempo_bpm = 120.0
    step_ms = 60000.0 / tempo_bpm
    # a real bass_up step at beat 20 (10000ms); a section boundary 2 beats
    # (1000ms) away should move onto it under a generous window.
    half = 40
    rms_bass = [0.1] * 20 + [1.0] * 20
    beats = [{"ms": i * step_ms, "is_downbeat": False, "rms_bass": rms_bass[i]}
            for i in range(half)]
    boundary_ms = int(20 * step_ms - 2 * step_ms)
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": GEN_URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": GEN_URI, "tempo_bpm": tempo_bpm,
        "sections": [
            {"start_ms": 0, "end_ms": boundary_ms, "label": "intro", "energy_rms": 0.1},
            {"start_ms": boundary_ms, "end_ms": 20000, "label": "drop", "energy_rms": 0.9},
        ],
        "beats": beats,
    }), encoding="utf-8")

    [m] = midsong_generator.candidate_moments(
        GEN_URI, window_beats=8, sensitivity=0.5, direction="both", transitions_per_minute=8)
    assert m.snap_grid == "edge:up"
    assert m.timestamp_ms == int(round(20 * step_ms))
    assert m.snap_moved_ms == int(round(20 * step_ms)) - boundary_ms
