"""spectra/services/testbed_beatthis.py — the guarded beat_this call, run
only offline (scripts/testbed_precompute.py). This host genuinely doesn't
have the `beat_this` package installed, so
test_unavailable_raises_a_named_error proves the REAL current behaviour,
not a mocked one; test_compute_marks_parses_beats_and_downbeats proves the
parsing/normalization logic against a fake module standing in for it."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def test_unavailable_raises_a_named_error_not_a_crash():
    from spectra.services import testbed_beatthis
    with pytest.raises(testbed_beatthis.BeatThisUnavailable):
        testbed_beatthis.compute(Path("/nonexistent.wav"))


def test_compute_marks_parses_beats_and_downbeats(monkeypatch):
    """A downbeat time also appears in beats_s (beat_this's own convention
    — testbed_beatthis.py's own docstring) so it must be tagged
    'downbeat', not double-counted as a separate 'beat' mark."""
    fake_inference = types.ModuleType("beat_this.inference")

    class FakeFile2Beats:
        def __init__(self, checkpoint_path, device, dbn):
            assert dbn is False, "dbn must stay False -- no madmom pulled in"
            self.checkpoint_path = checkpoint_path
            self.device = device

        def __call__(self, wav_path):
            beats = [0.5, 1.0, 1.5, 2.0]
            downbeats = [0.5, 2.0]
            return beats, downbeats

    fake_inference.File2Beats = FakeFile2Beats
    fake_beat_this = types.ModuleType("beat_this")
    fake_beat_this.inference = fake_inference
    monkeypatch.setitem(sys.modules, "beat_this", fake_beat_this)
    monkeypatch.setitem(sys.modules, "beat_this.inference", fake_inference)

    from spectra.services import testbed_beatthis
    marks = testbed_beatthis.compute_marks_ms(Path("/fake.wav"))

    downbeat_times = sorted(m["time_ms"] for m in marks if m["kind"] == "downbeat")
    beat_times = sorted(m["time_ms"] for m in marks if m["kind"] == "beat")
    assert downbeat_times == [500.0, 2000.0]
    assert beat_times == [1000.0, 1500.0]
    assert len(marks) == 4  # every beat_s time appears exactly once
