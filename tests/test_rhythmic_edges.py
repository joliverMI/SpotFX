"""spectra/services/rhythmic_edges.py — bass-energy rhythmic edge detection
for the music-analysis test bed's tuning loop
(data/transition-alignment-plan/report.md section 4, ship task 2).

Synthetic rms_bass fixtures only, per the ship task's own acceptance bar —
no live storage, no WAV. The report's own real-song reproduction
(section 2.3's "Bass energy jumps up/down" rows) is a separate,
read-only-against-live-storage offline measurement
(scripts/check_transition_alignment.py), not a pytest concern."""
from __future__ import annotations

import json

import pytest

from spectra.services import rhythmic_edges as re


def _beats(n: int, step_ms: float = 500.0) -> list[float]:
    return [i * step_ms for i in range(n)]


def test_fewer_than_two_beats_or_mismatched_lengths_returns_every_kind_empty():
    assert re.edges_for_beats([], []) == {k: [] for k in re.KINDS}
    assert re.edges_for_beats([0.0], [0.1]) == {k: [] for k in re.KINDS}
    result = re.edges_for_beats([0.0, 500.0, 1000.0], [0.1, 0.2])
    assert result == {k: [] for k in re.KINDS}


def test_a_clean_bass_step_up_is_detected_and_positioned_at_the_jump_beat():
    beats = _beats(40)
    rms = [0.1] * 20 + [1.0] * 20  # a sustained step, not a one-beat blip
    result = re.edges_for_beats(beats, rms, sensitivity=0.5)
    assert result[re.KIND_BASS_UP] == [beats[20]]
    assert result[re.KIND_BASS_DOWN] == []


def test_a_clean_bass_step_down_is_detected_and_positioned_at_the_drop_beat():
    beats = _beats(40)
    rms = [1.0] * 20 + [0.1] * 20
    result = re.edges_for_beats(beats, rms, sensitivity=0.5)
    assert result[re.KIND_BASS_DOWN] == [beats[20]]
    assert result[re.KIND_BASS_UP] == []


def test_a_flat_signal_produces_no_up_or_down_edges():
    beats = _beats(30)
    rms = [0.4] * 30
    result = re.edges_for_beats(beats, rms)
    assert result[re.KIND_BASS_UP] == []
    assert result[re.KIND_BASS_DOWN] == []


def test_a_mid_song_quiet_run_produces_a_gap_stop_and_gap_resume_pair():
    beats = _beats(60)
    rms = [0.5] * 60
    for i in range(20, 30):  # a 10-beat quiet run, well clear of both ends
        rms[i] = 0.001
    result = re.edges_for_beats(beats, rms, window_beats=8)
    assert result[re.KIND_GAP_STOP] == [beats[20]]
    assert result[re.KIND_GAP_RESUME] == [beats[30]]


def test_a_quiet_run_shorter_than_window_beats_is_not_a_gap():
    beats = _beats(40)
    rms = [0.5] * 40
    for i in range(10, 13):  # only 3 quiet beats
        rms[i] = 0.001
    result = re.edges_for_beats(beats, rms, window_beats=8)
    assert result[re.KIND_GAP_STOP] == []
    assert result[re.KIND_GAP_RESUME] == []


def test_window_beats_is_the_gap_run_length_threshold_and_only_affects_gap_kinds():
    """The report's own §2.3 reproduction bar is scoped to bass_up/
    bass_down only — window_beats must never move those, only the gap
    kinds' run-length requirement (see the module docstring's "TWO
    KNOBS" section)."""
    beats = _beats(60)
    rms = [0.1] * 20 + [1.0] * 40  # a sustained up step at beat 20
    for i in range(5, 10):  # an unrelated 5-beat quiet dip before the step
        rms[i] = 0.001
    loose = re.edges_for_beats(beats, rms, window_beats=4, sensitivity=0.5)
    strict = re.edges_for_beats(beats, rms, window_beats=8, sensitivity=0.5)
    assert loose[re.KIND_GAP_STOP] == [beats[5]]  # 5 >= 4: a gap
    assert strict[re.KIND_GAP_STOP] == []         # 5 < 8: not a gap
    # bass_up/bass_down are identical regardless of window_beats.
    assert loose[re.KIND_BASS_UP] == strict[re.KIND_BASS_UP]
    assert loose[re.KIND_BASS_DOWN] == strict[re.KIND_BASS_DOWN]
    assert beats[20] in loose[re.KIND_BASS_UP]


def test_sensitivity_is_the_up_down_jump_threshold_and_does_not_move_gap_kinds():
    beats = _beats(60)
    rms = [0.5] * 30 + [0.75] * 30  # a moderate sustained step (0.5 -> 0.75)
    for i in range(10, 20):  # an unrelated 10-beat gap
        rms[i] = 0.001
    loose = re.edges_for_beats(beats, rms, sensitivity=0.3, window_beats=8)
    strict = re.edges_for_beats(beats, rms, sensitivity=1.2, window_beats=8)
    assert beats[30] in loose[re.KIND_BASS_UP]
    assert strict[re.KIND_BASS_UP] == []  # too small a step at 1.2x
    assert loose[re.KIND_GAP_STOP] == strict[re.KIND_GAP_STOP] == [beats[10]]


def _updown_beats_and_rms():
    """A clean sustained step up at beat 20 (10000ms) and a clean sustained
    step down at beat 60 (30000ms), no quiet stretch anywhere — isolates
    the direction knob's effect on bass_up/bass_down alone (empirically
    verified: this fixture produces no gap_stop/gap_resume marks)."""
    beats = _beats(120)
    rms = [0.1] * 20 + [1.0] * 40 + [0.1] * 60
    return beats, rms


def _gap_beats_and_rms():
    """A single quiet run (beats 30-39) inside a steady baseline — its
    onset/resume are themselves sharp steps, so they ALSO register as
    bass_down/bass_up at the same two timestamps (empirically verified) —
    exactly the "gap is a special case of down then up" shape the report
    itself describes (§2.3)."""
    beats = _beats(80)
    rms = [0.5] * 30 + [0.001] * 10 + [0.5] * 40
    return beats, rms


def test_direction_both_is_the_default_and_returns_every_kind_unfiltered():
    beats, rms = _updown_beats_and_rms()
    default = re.edges_for_beats(beats, rms)
    explicit_both = re.edges_for_beats(beats, rms, direction=re.DIRECTION_BOTH)
    assert default == explicit_both
    assert default[re.KIND_BASS_UP] == [beats[20]]
    assert default[re.KIND_BASS_DOWN] == [beats[60]]

    gbeats, grms = _gap_beats_and_rms()
    gap_both = re.edges_for_beats(gbeats, grms, window_beats=8)
    assert gap_both[re.KIND_GAP_STOP] == [gbeats[30]]
    assert gap_both[re.KIND_GAP_RESUME] == [gbeats[40]]


def test_direction_up_keeps_only_bass_up_and_gap_resume():
    beats, rms = _updown_beats_and_rms()
    up = re.edges_for_beats(beats, rms, direction=re.DIRECTION_UP)
    assert up[re.KIND_BASS_UP] == [beats[20]]
    assert up[re.KIND_BASS_DOWN] == []

    gbeats, grms = _gap_beats_and_rms()
    gap_up = re.edges_for_beats(gbeats, grms, window_beats=8, direction=re.DIRECTION_UP)
    assert gap_up[re.KIND_GAP_RESUME] == [gbeats[40]]
    assert gap_up[re.KIND_GAP_STOP] == []


def test_direction_down_keeps_only_bass_down_and_gap_stop():
    beats, rms = _updown_beats_and_rms()
    down = re.edges_for_beats(beats, rms, direction=re.DIRECTION_DOWN)
    assert down[re.KIND_BASS_DOWN] == [beats[60]]
    assert down[re.KIND_BASS_UP] == []

    gbeats, grms = _gap_beats_and_rms()
    gap_down = re.edges_for_beats(gbeats, grms, window_beats=8, direction=re.DIRECTION_DOWN)
    assert gap_down[re.KIND_GAP_STOP] == [gbeats[30]]
    assert gap_down[re.KIND_GAP_RESUME] == []


@pytest.mark.parametrize("value,expected", [
    ("both", "both"), ("up", "up"), ("down", "down"),
    ("sideways", re.DEFAULT_DIRECTION), (None, re.DEFAULT_DIRECTION),
    ("", re.DEFAULT_DIRECTION),
])
def test_clamp_direction(value, expected):
    assert re.clamp_direction(value) == expected


@pytest.mark.parametrize("value,expected", [
    (0, re.MIN_WINDOW_BEATS), (-5, re.MIN_WINDOW_BEATS),
    (100, re.MAX_WINDOW_BEATS), (8, 8), (8.6, 9),
    (None, re.DEFAULT_WINDOW_BEATS), ("nope", re.DEFAULT_WINDOW_BEATS),
])
def test_clamp_window_beats(value, expected):
    assert re.clamp_window_beats(value) == expected


@pytest.mark.parametrize("value,expected", [
    (0.0, re.MIN_SENSITIVITY), (-1.0, re.MIN_SENSITIVITY),
    (99.0, re.MAX_SENSITIVITY), (0.5, 0.5),
    (None, re.DEFAULT_SENSITIVITY), ("nope", re.DEFAULT_SENSITIVITY),
])
def test_clamp_sensitivity(value, expected):
    assert re.clamp_sensitivity(value) == expected


def test_default_knobs_are_inside_the_documented_bounds():
    assert re.MIN_WINDOW_BEATS <= re.DEFAULT_WINDOW_BEATS <= re.MAX_WINDOW_BEATS
    assert re.MIN_SENSITIVITY <= re.DEFAULT_SENSITIVITY <= re.MAX_SENSITIVITY
    assert re.DEFAULT_DIRECTION in re.DIRECTIONS


@pytest.fixture()
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False


URI = "spotify:track:rhythmicedges1"


def _seed(scfg, beats: list[dict]):
    stem = "Artist - RhythmicEdgesSong"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(
        json.dumps({"spotify_uri": URI, "beats": beats}), encoding="utf-8")


def test_edges_for_uri_is_none_when_no_analysis_exists(_isolated):
    assert re.edges_for_uri("spotify:track:unknown") is None


def test_edges_for_uri_reads_beats_and_rms_bass_off_the_librosa_sidecar(_isolated):
    from spectra import config as scfg
    beats = [{"ms": i * 500.0, "rms_bass": 0.1} for i in range(40)]
    beats[20]["rms_bass"] = 1.0
    _seed(scfg, beats)
    edges = re.edges_for_uri(URI)
    assert edges is not None
    assert {m.time_ms for m in edges[re.KIND_BASS_UP]} == {10000.0}
    for kind, marks in edges.items():
        assert all(m.kind == kind for m in marks)


def test_edges_for_uri_sorts_out_of_order_beats_before_detecting(_isolated):
    from spectra import config as scfg
    ordered = [{"ms": i * 500.0, "rms_bass": 0.1} for i in range(40)]
    ordered[20]["rms_bass"] = 1.0
    shuffled = ordered[20:] + ordered[:20]  # out of ms order on disk
    _seed(scfg, shuffled)
    edges = re.edges_for_uri(URI)
    assert {m.time_ms for m in edges[re.KIND_BASS_UP]} == {10000.0}


def test_edges_for_uri_forwards_the_knobs(_isolated):
    from spectra import config as scfg
    beats = [{"ms": i * 500.0, "rms_bass": 0.5} for i in range(30)]
    for i in range(10, 15):
        beats[i]["rms_bass"] = 0.001  # a 5-beat quiet run
    _seed(scfg, beats)
    loose = re.edges_for_uri(URI, window_beats=4)
    strict = re.edges_for_uri(URI, window_beats=8)
    assert len(loose[re.KIND_GAP_STOP]) == 1
    assert len(strict[re.KIND_GAP_STOP]) == 0


def test_edges_for_uri_forwards_direction(_isolated):
    from spectra import config as scfg
    beats = [{"ms": i * 500.0, "rms_bass": 0.1} for i in range(40)]
    for i in range(20, 40):
        beats[i]["rms_bass"] = 1.0  # a sustained up step at beat 20
    _seed(scfg, beats)
    both = re.edges_for_uri(URI, direction=re.DIRECTION_BOTH)
    up = re.edges_for_uri(URI, direction=re.DIRECTION_UP)
    down = re.edges_for_uri(URI, direction=re.DIRECTION_DOWN)
    assert {m.time_ms for m in both[re.KIND_BASS_UP]} == {10000.0}
    assert {m.time_ms for m in up[re.KIND_BASS_UP]} == {10000.0}
    assert down[re.KIND_BASS_UP] == []
