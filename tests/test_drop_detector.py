"""The drop detector (spectra/services/drop_detector.py) on SYNTHETIC audio
shapes — never his storage. The port's fidelity to the plan's testbed on
the four real songs is held by scripts/check_drop_detector.py; these hold
the rules themselves: where a drop, its lull and its charge land, what is
not a drop, and the guards."""
from __future__ import annotations

import os
import time

import pytest

import drop_synth

URI = "spotify:track:dropsynth1"
BEAT = 500.0   # 120 bpm


@pytest.fixture(autouse=True)
def _shapes(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    drop_synth.reset_index()
    yield
    drop_synth.reset_index()


def _shapes_dir():
    from spectra import config as scfg
    return scfg.AUDIO_SHAPES_DIR


def test_a_break_and_a_bigger_return_is_a_confident_drop_with_its_lull_and_charge():
    from spectra.services import drop_detector as dd
    drop_synth.one_drop_song(_shapes_dir(), URI)
    det = dd.detect_uri(URI)
    assert len(det.sequences) == 1
    s = det.sequences[0]
    # on the bass spike that ends the break (onset frame, within two frames)
    assert abs(s.drop_ms - drop_synth.DROP_S * 1000) <= 2 * dd.FRAME_MS
    assert s.tier == dd.TIER_CONFIDENT
    assert s.score >= dd.CONFIDENT_SCORE
    assert s.path == "step" and s.loud_before
    assert s.break_beats == pytest.approx(8.0, abs=0.1)
    # the last hit before the break is short, so the lull is where the bass stops
    assert abs(s.lull_ms - 40000) <= BEAT
    # nothing stands out in the build: 10 beats before the lull, on a beat
    assert s.charge_ms == pytest.approx(s.lull_ms - 10 * BEAT, abs=BEAT / 2)
    assert s.charge_ms < s.lull_ms < s.drop_ms
    assert s.key == f"drop:{s.drop_ms}"


def test_every_time_is_song_time_on_a_capture_that_starts_mid_song():
    """The shape is already in song time; the beats are shifted by the
    capture's first sample. A mid-song capture finds the same drop."""
    from spectra.services import drop_detector as dd
    drop_synth.one_drop_song(_shapes_dir(), URI, offset_ms=5000)
    det = dd.detect_uri(URI)
    assert det.captured_from_ms == 5000
    s = det.sequences[0]
    assert abs(s.drop_ms - drop_synth.DROP_S * 1000) <= 2 * dd.FRAME_MS
    assert abs(s.lull_ms - 40000) <= BEAT
    # the charge sits on one of the song's beats (song time, not recording time)
    assert s.charge_ms % int(BEAT) == 0


def test_an_intros_first_bass_entry_is_not_a_drop():
    """loud -> quiet -> loud: a bass entry after a bass-less INTRO has
    nothing loud before its break and is rejected by design."""
    from spectra.services import drop_detector as dd
    drop_synth.write_song(_shapes_dir(), URI, [
        ("quiet", 0, 30, 0.01), ("loud", 30, 90, 1.0), ("loud", 90, 100, 0.5)])
    det = dd.detect_uri(URI)
    assert det.sequences == []


def test_a_steady_song_has_no_drop():
    from spectra.services import drop_detector as dd
    drop_synth.write_song(_shapes_dir(), URI, [("loud", 0, 100, 0.7)])
    assert dd.detect_uri(URI).sequences == []


def test_a_double_hit_drop_lands_on_the_first_spike():
    """His rule: "the drop should be on the FIRST bass/beat spike"."""
    from spectra.services import drop_detector as dd
    drop_synth.write_song(_shapes_dir(), URI, [
        ("loud", 0, 40, 0.55), ("quiet", 40, 44, 0.01),
        ("loud", 44, 80, 1.0), ("loud", 80, 100, 0.5)],
        double_hit_at_s=(44.0,))
    s = dd.detect_uri(URI).sequences[0]
    assert abs(s.drop_ms - (44000 - 0.25 * BEAT)) <= 2 * dd.FRAME_MS


def test_a_drop_in_the_first_or_last_15_seconds_is_excluded_and_said_so():
    from spectra.services import drop_detector as dd
    drop_synth.write_song(_shapes_dir(), URI, [
        ("loud", 0, 6, 0.55), ("quiet", 6, 10, 0.01), ("loud", 10, 60, 1.0)])
    det = dd.detect_uri(URI)
    assert det.sequences == []
    assert len(det.excluded) == 1
    assert abs(det.excluded[0].drop_ms - 10000) <= 2 * dd.FRAME_MS
    assert "15 s" in det.excluded[0].reason


def test_the_two_tiers_follow_the_thresholds():
    from spectra.services import drop_detector as dd
    drop_synth.one_drop_song(_shapes_dir(), URI)
    analysis = dd.analyse(URI)
    score = dd.detect(analysis).sequences[0].score
    above = dd.detect(analysis, confident_score=score + 0.1, suggested_score=score - 0.1)
    assert above.sequences[0].tier == dd.TIER_SUGGESTED
    neither = dd.detect(analysis, confident_score=score + 0.2, suggested_score=score + 0.1)
    assert neither.sequences == []
    assert dd.tier_for(0.8, 0.7, 1.0) == dd.TIER_CONFIDENT     # inverted: never hidden
    assert dd.tier_for(0.69, 0.7, 1.0) is None


def test_the_cap_demotes_the_weakest_confident_drops_and_says_why():
    """One confident sequence per 45 s of song, strongest first."""
    from spectra.services import drop_detector as dd
    sections = [("loud", 0, 20, 0.5)]
    t = 20
    for level in (1.0, 0.95, 0.9):
        sections += [("quiet", t, t + 4, 0.01), ("loud", t + 4, t + 24, level)]
        t += 24
    sections.append(("loud", t, t + 20, 0.5))
    drop_synth.write_song(_shapes_dir(), URI, sections, duration_ms=90_000)
    det = dd.detect_uri(URI)
    assert dd.confident_cap(90_000) == 2
    tiers = [s.tier for s in det.sequences]
    assert tiers.count(dd.TIER_CONFIDENT) == 2
    demoted = [s for s in det.sequences if s.capped]
    assert len(demoted) == 1 and demoted[0].tier == dd.TIER_SUGGESTED
    assert "one per 45 s" in demoted[0].notes[0]
    weakest = min(det.sequences, key=lambda s: s.score)
    assert weakest.capped


def _seq(drop, lull, charge):
    from spectra.services import drop_detector as dd
    return dd.DetectedSequence(key=dd.drop_key(drop), drop_ms=drop, lull_ms=lull,
                               charge_ms=charge, score=1.0, tier=dd.TIER_CONFIDENT,
                               break_beats=2.0, step=1.0, rise=1.0, path="step",
                               loud_before=True)


def test_spacing_moves_a_charge_out_of_the_previous_drops_two_bars():
    from spectra.services import drop_detector as dd
    a = _seq(10_000, 9_000, 6_000)
    b = _seq(20_000, 18_000, 12_000)          # charge inside 10 000 + 8 beats = 14 000
    dd.apply_spacing([a, b], BEAT)
    assert (a.charge_ms, a.lull_ms) == (6_000, 9_000)
    assert b.charge_ms == 14_000 and b.lull_ms == 18_000
    assert "moved" in b.notes[0]


def test_spacing_takes_lull_and_charge_when_the_lull_is_inside_the_tail():
    from spectra.services import drop_detector as dd
    a = _seq(10_000, 9_000, 6_000)
    b = _seq(15_000, 13_500, 11_000)          # lull inside 14 000
    dd.apply_spacing([a, b], BEAT)
    assert (b.lull_ms, b.charge_ms) == (None, None)
    assert "left out" in b.notes[0]


def test_spacing_drops_a_charge_with_no_room_left_before_its_lull():
    from spectra.services import drop_detector as dd
    a = _seq(10_000, 9_000, 6_000)
    b = _seq(16_000, 14_100, 12_000)          # moved charge 14 000 is < 200 ms before the lull
    dd.apply_spacing([a, b], BEAT)
    assert b.charge_ms is None and b.lull_ms == 14_100


def test_unavailable_songs_say_why():
    from spectra.services import drop_detector as dd
    with pytest.raises(dd.Unavailable, match="no captured audio shape"):
        dd.detect_uri("spotify:track:nothing")
    stem = drop_synth.one_drop_song(_shapes_dir(), URI)
    (_shapes_dir() / f"{stem}.npz").unlink()
    drop_synth.reset_index()
    with pytest.raises(dd.Unavailable, match="audio shape is missing"):
        dd.detect_uri(URI)


def test_analysis_is_memoised_and_a_recapture_is_seen_at_once():
    from spectra.services import drop_detector as dd
    stem = drop_synth.one_drop_song(_shapes_dir(), URI)
    first = dd.analyse(URI)
    assert dd.analyse(URI) is first
    npz = _shapes_dir() / f"{stem}.npz"
    later = time.time() + 5
    os.utime(npz, (later, later))
    assert dd.analyse(URI) is not first
