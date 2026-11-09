"""The emphasis score (spectra/services/lyrics_emphasis.py): each of the five
things he ruled on, the combination, the sensitivity slider, and that the
function stays pure."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from spectra.services import lyrics_emphasis as le

REPO = pathlib.Path(__file__).resolve().parent.parent


def _word(text, ms, end_ms, line=0, wav_ms=None, norm=None):
    return {"w": text, "n": norm if norm is not None else text.lower(), "line": line,
            "ms": float(ms), "end_ms": float(end_ms),
            "wav_ms": float(ms if wav_ms is None else wav_ms), "conf": 0.5}


def _row(n, gap=400.0, dur=200.0, line=None, text="la"):
    return [_word(f"{text}{i}", i * gap, i * gap + dur, line=(i if line is None else line),
                  norm=f"{text}{i}") for i in range(n)]


def _flat_frames(length_ms=60_000, level=0.1, step=10):
    stamps = np.arange(0.0, float(length_ms), float(step))
    return le.Frames(stamps, np.full_like(stamps, level))


def _with_loud_region(frames, start_ms, end_ms, level):
    rms = frames.rms.copy()
    rms[(frames.timestamps_ms >= start_ms) & (frames.timestamps_ms < end_ms)] = level
    return le.Frames(frames.timestamps_ms, rms)


def _by_index(scored, i):
    return next(s for s in scored if s.index == i)


def test_a_word_sung_well_over_its_neighbours_earns_full_loudness():
    words = _row(13)
    level = 0.1 * (10 ** (le.LOUD_FULL_DB / 20))
    frames = _with_loud_region(_flat_frames(), words[6]["ms"], words[6]["end_ms"], level)
    scored = le.score_words(words, frames, [])
    assert _by_index(scored, 6).features.loud == pytest.approx(1.0, abs=0.02)
    assert _by_index(scored, 2).features.loud == 0.0


def test_a_long_notes_fading_tail_does_not_count_against_it():
    """The first three quarters of this word are loud and the end has faded."""
    words = _row(13, gap=1000.0, dur=800.0)
    start, end = words[6]["ms"], words[6]["end_ms"]
    loud = 0.1 * (10 ** (le.LOUD_FULL_DB / 20))
    frames = _with_loud_region(_flat_frames(), start, start + 0.76 * (end - start), loud)
    assert _by_index(le.score_words(words, frames, []), 6).features.loud == pytest.approx(1.0, abs=0.02)


def test_a_quieter_word_earns_nothing_for_loudness():
    words = _row(13)
    frames = _with_loud_region(_flat_frames(), words[6]["ms"], words[6]["end_ms"], 0.02)
    assert _by_index(le.score_words(words, frames, []), 6).features.loud == 0.0


def test_a_word_held_three_times_its_neighbours_earns_full_marks():
    words = _row(13, gap=800.0, dur=200.0)
    words[6]["end_ms"] = words[6]["ms"] + 600.0
    assert _by_index(le.score_words(words, None, []), 6).features.held == pytest.approx(1.0)


def test_a_long_word_is_not_held_for_being_long():
    """Time per letter: eighteen letters in 600 ms is a quick word."""
    words = _row(13, gap=800.0, dur=200.0)
    words[6].update(n="supercalifragilist", end_ms=words[6]["ms"] + 600.0)
    assert _by_index(le.score_words(words, None, []), 6).features.held == 0.0


def test_a_word_too_short_to_hold_scores_nothing_however_quick_the_rest():
    words = _row(13, gap=100.0, dur=20.0)
    words[6]["end_ms"] = words[6]["ms"] + 150.0
    assert le.HELD_MIN_MS > 150.0
    assert _by_index(le.score_words(words, None, []), 6).features.held == 0.0


def _beats(start=0.0, gap=500.0, n=16):
    return [{"ms": start + i * gap, "is_downbeat": i % 4 == 0} for i in range(n)]


def test_on_the_downbeat_earns_more_than_on_a_weak_beat():
    words = [_word("a", 2000, 2200, wav_ms=2000), _word("b", 2500, 2700, wav_ms=2500, line=1),
             _word("c", 3000, 3200, wav_ms=3000, line=2)]
    scored = le.score_words(words, None, _beats())
    assert _by_index(scored, 0).features.beat == pytest.approx(le.DOWNBEAT_STRENGTH)
    assert _by_index(scored, 1).features.beat == pytest.approx(le.OTHER_BEAT_STRENGTH)
    assert _by_index(scored, 2).features.beat == pytest.approx(le.MID_BAR_STRENGTH)


def test_off_the_beat_earns_nothing():
    words = [_word("a", 2250, 2400, wav_ms=2250)]
    assert le.score_words(words, None, _beats())[0].features.beat == 0.0


def test_the_beat_test_uses_the_wavs_position_not_the_label():
    """Beats are positions in the WAV. On a capture whose labels have drifted
    from the WAV, comparing the label with a beat would be a different moment."""
    on_the_wav = [_word("a", 9000, 9200, wav_ms=2000)]
    assert le.score_words(on_the_wav, None, _beats())[0].features.beat == pytest.approx(1.0)
    only_the_label = [_word("a", 2000, 2200, wav_ms=9100)]
    assert le.score_words(only_the_label, None, _beats())[0].features.beat == 0.0


def test_a_tight_beat_window_scales_with_a_fast_song():
    fast = _beats(gap=250.0)
    window = le.BEAT_WINDOW_FRACTION * 250.0
    inside = [_word("a", 2000 + window - 1, 2200, wav_ms=2000 + window - 1)]
    outside = [_word("a", 2000 + window + 1, 2200, wav_ms=2000 + window + 1)]
    assert le.score_words(inside, None, fast)[0].features.beat > 0.0
    assert le.score_words(outside, None, fast)[0].features.beat == 0.0


def test_only_the_last_word_of_a_line_is_a_line_end():
    words = [_word("a", 0, 100, line=0), _word("b", 200, 300, line=0), _word("c", 400, 500, line=1)]
    scored = le.score_words(words, None, [])
    assert [s.features.line_end for s in scored] == [0.0, 1.0, 1.0]


def _song(*lines):
    words = []
    t = 0.0
    for line_no, text in enumerate(lines):
        for token in text.split():
            words.append(_word(token, t, t + 100.0, line=line_no))
            t += 200.0
        t += 400.0
    return words


def test_a_word_in_a_repeated_line_earns_hook_marks():
    words = _song("red light tonight", "a verse goes here", "red light tonight",
                  "another verse line", "red light tonight", "red light tonight")
    scored = le.score_words(words, None, [])
    assert next(s for s in scored if s.norm == "red").features.hook == pytest.approx(1.0)
    assert next(s for s in scored if s.norm == "verse").features.hook == 0.0


def test_a_word_that_is_also_all_over_the_verses_loses_hook_marks():
    """"the" sings in the hook but mostly elsewhere, with no word list needed."""
    words = _song("red the light", "the verse the verse", "red the light",
                  "the words the words", "red the light", "red the light")
    scored = le.score_words(words, None, [])
    red = next(s for s in scored if s.norm == "red")
    the = next(s for s in scored if s.norm == "the" and s.line == 0)
    assert red.features.hook > the.features.hook > 0.0


def test_a_line_sung_once_is_no_hook():
    words = _song("once only here", "and this once")
    assert all(s.features.hook == 0.0 for s in le.score_words(words, None, []))


def test_spanish_goes_through_the_same_arithmetic():
    words = _song("corazon rojo", "otra linea aqui", "corazon rojo", "corazon rojo")
    scored = le.score_words(words, None, [])
    assert next(s for s in scored if s.norm == "rojo").features.hook > 0.0


def test_the_weights_add_to_one_so_a_score_is_zero_to_one():
    total = le.WEIGHT_LOUD + le.WEIGHT_HELD + le.WEIGHT_BEAT + le.WEIGHT_LINE_END + le.WEIGHT_HOOK
    assert total == pytest.approx(1.0)


def test_the_score_is_exactly_the_weighted_features():
    words = _song("red light tonight", "red light tonight", "red light tonight", "red light tonight")
    words[0]["end_ms"] = words[0]["ms"] + 600.0
    for s in le.score_words(words, _flat_frames(), _beats()):
        f = s.features
        expected = (le.WEIGHT_LOUD * f.loud + le.WEIGHT_HELD * f.held + le.WEIGHT_BEAT * f.beat
                    + le.WEIGHT_LINE_END * f.line_end + le.WEIGHT_HOOK * f.hook)
        assert s.score == pytest.approx(expected, abs=1e-3)
        assert 0.0 <= s.score <= 1.0


def test_higher_sensitivity_picks_more_words_never_fewer():
    words = _song("red light tonight", "a verse goes here", "red light tonight",
                  "another verse line", "red light tonight", "red light tonight")
    words[0]["end_ms"] = words[0]["ms"] + 500.0
    scored = le.score_words(words, _flat_frames(), _beats(gap=200.0, n=60))
    previous = -1
    for s in np.arange(0.0, 1.0001, 0.05):
        n = len(le.emphasized(scored, float(s)))
        assert n >= previous
        previous = n
    assert len(le.emphasized(scored, 1.0)) == len(scored)


def test_sensitivity_is_clamped_and_none_means_the_default():
    assert le.threshold_for(2.0) == 0.0
    assert le.threshold_for(-1.0) == 1.0
    assert le.threshold_for(None) == pytest.approx(1.0 - le.DEFAULT_SENSITIVITY)


def test_no_frames_and_no_beats_is_no_marks_for_those_never_an_error():
    words = _song("red light tonight", "red light tonight")
    scored = le.score_words(words, None, [])
    assert len(scored) == len(words)
    assert all(s.features.loud == 0.0 and s.features.beat == 0.0 for s in scored)


def test_a_word_in_a_hole_in_the_capture_is_not_measured():
    words = _row(13)
    frames = le.Frames(np.array([0.0, 1.0]), np.array([0.5, 0.5]))
    assert _by_index(le.score_words(words, frames, []), 6).features.loud == 0.0


def test_no_words_is_no_scores():
    assert le.score_words([], None, []) == []


def test_it_is_deterministic():
    words = _song("red light tonight", "a verse goes here", "red light tonight")
    frames = _flat_frames()
    assert le.score_words(words, frames, _beats()) == le.score_words(words, frames, _beats())


_PURITY_DRIVER = textwrap.dedent('''
    import builtins
    import json
    import socket
    import sys

    import numpy as np
    from spectra.services import lyrics_emphasis as le

    before_import = {
        name: name in sys.modules
        for name in ("torch", "torchaudio", "soundfile", "sounddevice", "whisper")
    }

    def _blocked_open(*a, **k):
        raise AssertionError("score_words touched the filesystem")

    class _BlockedSocket:
        def __init__(self, *a, **k):
            raise AssertionError("score_words touched the network")

    builtins.open = _blocked_open
    socket.socket = _BlockedSocket

    def word(text, ms, end_ms, line):
        return {"w": text, "n": text.lower(), "line": line, "ms": float(ms),
                "end_ms": float(end_ms), "wav_ms": float(ms), "conf": 0.5}

    words = [word("w%d" % i, i * 400.0, i * 400.0 + 200.0, i) for i in range(6)]
    stamps = np.arange(0.0, 6000.0, 10.0)
    frames = le.Frames(stamps, np.full_like(stamps, 0.1))
    beats = [{"ms": i * 500.0} for i in range(10)]

    scored = le.score_words(words, frames, beats)

    print(json.dumps({
        "before_import": before_import,
        "scored_count": len(scored),
        "word_count": len(words),
    }))
''')


def test_the_score_itself_imports_nothing_that_could_load_a_model_or_play_audio():
    """The ruling: a pure function, no model, no audio playback, no file or
    network I/O. Proven in a FRESH interpreter (a warm pytest process may
    have already imported torch/soundfile/etc. via unrelated collected
    tests, which would make an in-process sys.modules check meaningless)
    by importing just this module and then calling score_words with
    builtins.open and socket.socket patched to raise -- it still returns a
    score for every word, so nothing in it reaches disk or the network."""
    proc = subprocess.run([sys.executable, "-c", _PURITY_DRIVER],
                          cwd=REPO, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not any(out["before_import"].values()), out["before_import"]
    assert out["scored_count"] == out["word_count"] == 6
