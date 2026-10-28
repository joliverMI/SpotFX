"""THE DROP FLOOR (the Admiral, 2026-10-06: "drop sequences only get
generated if the final energy value for the post drop or during drop
section is at least the drop floor. so quiet songs or sections don't
accidentally get drops"), on the number the top bar shows. Since
2026-10-28 that number is ENERGY (spectra/services/energy.py): the song's
normalized section energy with the Mark math (x 0.8 x the song's scale, an
unmarked song capped at 0.75), read with the look-ahead every drop takes.
`drop_detector.final_energy_at` IS `energy.energy_at(..., look_ahead=True)`.
The floor value itself is re-set for the new scale by
scripts/energy_parity.py (the plan's D5). Synthetic songs only; the store
is isolated per test by conftest's `_isolated_drop_sequences`."""
from __future__ import annotations

import pytest

import drop_synth

URI = "spotify:track:dropfloor1"
BEAT = 500.0


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    drop_synth.reset_index()
    yield
    drop_synth.reset_index()


# ── the detector itself ─────────────────────────────────────────────────

def test_a_quiet_post_drop_section_is_excluded_at_the_default_floor():
    """A real break/return landing in the song's quietest section (Energy 0
    on the song's own scale) is removed — named, not silently dropped."""
    from spectra.services import drop_detector as dd
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[
        (0, 43, 0.98), (43, 100, 0.60),   # the drop lands in the quieter second
    ])
    det = dd.detect_uri(URI)
    assert det.sequences == []
    assert len(det.excluded) == 1
    exc = det.excluded[0]
    assert exc.drop_ms == pytest.approx(drop_synth.DROP_S * 1000, abs=2 * dd.FRAME_MS)
    assert "below the drop floor" in exc.reason
    assert "0.00" in exc.reason and "0.70" in exc.reason


def test_a_loud_post_drop_section_clears_a_floor_its_energy_reaches():
    """The loud section is 1.0 on the song's own scale; with the Mark math
    an unmarked song reaches 0.8 x its scale, and a song marked 1.25 reaches
    the full 1.0 — over the default 0.7."""
    from spectra.services import drop_detector as dd
    from spectra.services import intensity_scale_marks
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[
        (0, 43, 0.60), (43, 100, 0.98),   # the drop lands well inside the second
    ])
    intensity_scale_marks.set_mark(URI, 1.25)
    det = dd.detect_uri(URI)
    assert len(det.sequences) == 1
    assert det.sequences[0].drop_ms == pytest.approx(drop_synth.DROP_S * 1000,
                                                      abs=2 * dd.FRAME_MS)
    assert det.excluded == []


def test_an_unknown_energy_never_gates_a_drop():
    """No stored section energy at all (drop_synth's own default) is
    UNKNOWN, never 'below the floor' — the existing synthetic-song test
    suite (which never writes section energy) must keep passing."""
    from spectra.services import drop_detector as dd
    drop_synth.one_drop_song(_shapes_dir(), URI)
    det = dd.detect_uri(URI)
    assert len(det.sequences) == 1
    assert det.excluded == []


def test_a_zero_floor_gates_nothing():
    from spectra.services import drop_detector as dd
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[(0, 100, 0.01)])
    det = dd.detect_uri(URI, drop_floor=0.0)
    assert len(det.sequences) == 1


def test_final_energy_at_is_energy_with_the_look_ahead():
    """The top bar's number: the section's place on the song's own scale,
    with the Mark math, looking ahead to the next section edge."""
    from spectra.services import drop_detector as dd, energy
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[
        (0, 43, 0.3), (43, 100, 0.8),
    ])
    drop_ms = int(drop_synth.DROP_S * 1000)
    assert dd.final_energy_at(URI, drop_ms) == energy.energy_at(URI, drop_ms, look_ahead=True)
    factor, marked = energy.song_factor(URI)
    assert dd.final_energy_at(URI, drop_ms) == pytest.approx(energy.mark_math(1.0, factor, marked))
    # 1.5 s before the louder section's edge, the drop reads the louder section
    assert dd.final_energy_at(URI, 43_000 - 1_500) == pytest.approx(energy.mark_math(1.0, factor, marked))
    assert energy.energy_at(URI, 43_000 - 1_500) == pytest.approx(0.0)


def test_a_manual_mark_moves_the_floor_reading():
    """The Mark is part of Energy now: marking the song up raises the
    reading the floor compares against (capped at 1.0 for a marked song)."""
    from spectra.services import drop_detector as dd
    from spectra.services import intensity_scale_marks
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[
        (0, 43, 0.3), (43, 100, 0.8),
    ])
    drop_ms = int(drop_synth.DROP_S * 1000)
    unmarked = dd.final_energy_at(URI, drop_ms)
    intensity_scale_marks.set_mark(URI, 2.0)
    marked = dd.final_energy_at(URI, drop_ms)
    assert unmarked < 0.75 and marked == pytest.approx(1.0)


# ── his own edits survive the floor ────────────────────────────────────

def test_a_confirmed_sequence_survives_a_floor_raised_past_it():
    """A sequence he confirmed, THEN a floor raised so the fresh detection
    excludes it, stays in the merged view as his — orphaned, not gone."""
    from spectra.services import drop_sequences as ds, room_controls
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[
        (0, 43, 0.3), (43, 100, 0.8),   # clears a 0.0 floor, not a 0.9 one
    ])
    room_controls.save_room_controls(
        room_controls.load_room_controls().model_copy(update={"drop_floor": 0.0}))
    first = ds.ensure_detected(URI)
    assert first["status"] == "detected" and first["sequences"] == 1
    key = ds.stored(URI)["detected"]["sequences"][0]["key"]
    ds.confirm(URI, key)

    room_controls.save_room_controls(
        room_controls.load_room_controls().model_copy(update={"drop_floor": 0.9}))
    again = ds.ensure_detected(URI)
    assert again["status"] == "detected"
    assert ds.stored(URI)["detected"]["sequences"] == []   # the fresh detect found nothing

    v = ds.view(URI)
    seqs = [s for s in v["sequences"] if s["key"] == key]
    assert len(seqs) == 1
    assert seqs[0]["state"] == "confirmed"
    assert seqs[0]["detection_lost"] is True


def test_an_added_sequence_is_never_touched_by_the_floor():
    from spectra.services import drop_sequences as ds, room_controls
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[(0, 100, 0.1)])
    room_controls.save_room_controls(
        room_controls.load_room_controls().model_copy(update={"drop_floor": 0.9}))
    ds.ensure_detected(URI)
    assert ds.stored(URI)["detected"]["sequences"] == []    # the real drop is gated out
    added_key = ds.add(URI, 70_000, lull_ms=68_000, charge_ms=60_000, fill=False)
    v = ds.view(URI)
    added = [s for s in v["sequences"] if s["key"] == added_key]
    assert len(added) == 1 and added[0]["state"] == "added"
    # re-running detection (e.g. his own re-detect press) still leaves it
    assert ds.ensure_detected(URI, force=True)["status"] == "detected"
    v2 = ds.view(URI)
    assert any(s["key"] == added_key for s in v2["sequences"])


# ── the stamp ────────────────────────────────────────────────────────────

def test_changing_the_drop_floor_goes_stale_and_re_detects():
    from spectra.services import drop_sequences as ds, room_controls
    drop_synth.one_drop_song(_shapes_dir(), URI, energy_sections=[(0, 100, 0.5)])
    first = ds.ensure_detected(URI)
    assert first["status"] == "detected"
    assert ds.ensure_detected(URI)["status"] == "fresh"
    stamp = ds.stored(URI)["detected"]["stamp"]

    room_controls.save_room_controls(
        room_controls.load_room_controls().model_copy(update={"drop_floor": 0.4}))
    again = ds.ensure_detected(URI)
    assert again["status"] == "detected" and again["stamp"] != stamp
    # 0.5 clears a 0.4 floor
    assert len(ds.stored(URI)["detected"]["sequences"]) == 1


def test_the_stamp_distinguishes_two_floors_at_the_same_tier_thresholds():
    from spectra.services import drop_sequences as ds
    drop_synth.one_drop_song(_shapes_dir(), URI)
    inputs = ds.song_inputs(URI)
    a = ds.stamp_for(URI, _controls(0.7), inputs=inputs)
    b = ds.stamp_for(URI, _controls(0.5), inputs=inputs)
    assert a != b


def _controls(drop_floor: float):
    from spectra.services.room_controls import RoomControlState
    return RoomControlState(drop_floor=drop_floor)


def _shapes_dir():
    from spectra import config as scfg
    return scfg.AUDIO_SHAPES_DIR
