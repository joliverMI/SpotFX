"""Absorb Music's bar (services/absorb_bar.py, report §8.1-§8.2), against real
files in a temp shapes directory: a sidecar, an npz with real timestamps, a
librosa json — every reason a song is re-captured, and the one shape that is
skipped. `scripts/check_absorb_classify.py` runs the same bar against his own
library, read-only."""
from __future__ import annotations

import json

import numpy as np
import pytest

from services import absorb_bar

HEAD_MAX = 1000


@pytest.fixture
def shapes(tmp_path, monkeypatch):
    import config
    import services.audio_analyzer as aa
    d = tmp_path / "audio_shapes"
    d.mkdir()
    for mod in (config, aa, absorb_bar):
        monkeypatch.setattr(mod, "AUDIO_SHAPES_DIR", d)
    # a fresh, empty index for this directory
    monkeypatch.setattr(aa, "_audio_shape_index", {})
    monkeypatch.setattr(aa, "_audio_shape_index_built", [False])
    monkeypatch.setattr(aa, "_index_files", {})
    monkeypatch.setattr(aa, "_index_dir_mtime_ns", [None])
    monkeypatch.setattr(aa, "_index_built_at", [0.0])
    monkeypatch.setattr(aa, "_index_racy", [False])

    def make(n, *, first_ts=0, duration=200_000, complete=True, failed=False,
             npz=True, librosa_version=3, librosa_json=True, needs_recapture=False,
             sidecar_first=None):
        stem = f"Artist - Song {n}"
        uri = f"spotify:track:bar{n:03d}"
        meta = {"spotify_uri": uri, "title": f"Song {n}", "artist": "Artist",
                "duration_ms": duration, "sample_interval_ms": 23,
                "npz_file": f"{stem}.npz", "capture_complete": complete,
                "capture_failed": failed, "librosa_version": librosa_version,
                "needs_recapture": needs_recapture}
        if sidecar_first is not None:
            meta["first_timestamp_ms"] = sidecar_first
        (d / f"{stem}.json").write_text(json.dumps(meta))
        if npz:
            ts = np.arange(first_ts, first_ts + 20_000, 23, dtype=np.int32)
            np.savez_compressed(d / f"{stem}.npz", timestamps_ms=ts,
                                rms_total=np.zeros(len(ts), dtype=np.float32))
        if librosa_json:
            (d / f"{stem}.librosa.json").write_text("{}")
        return uri

    return make


def _kind(uri, force=False):
    v = absorb_bar.classify(uri, HEAD_MAX, force)
    return v.kind, v.reasons


def test_a_complete_analysed_shape_with_its_head_is_skipped(shapes):
    assert _kind(shapes(1, first_ts=0)) == ("skip", [])
    assert _kind(shapes(2, first_ts=-40)) == ("skip", [])        # a hair early is fine
    assert _kind(shapes(3, first_ts=1000)) == ("skip", [])       # the bar is inclusive


def test_a_missing_head_is_a_recapture(shapes):
    assert _kind(shapes(1, first_ts=1001)) == ("recapture", ["headless"])
    assert _kind(shapes(2, first_ts=9_000)) == ("recapture", ["headless"])


def test_a_shape_that_starts_past_the_song_renders_nothing(shapes):
    assert _kind(shapes(1, first_ts=300_000, duration=200_000)) == \
        ("recapture", ["renders_nothing"])


def test_no_shape_and_failed_shapes_are_fresh(shapes):
    assert _kind("spotify:track:never") == ("fresh", ["no_shape"])
    assert _kind(shapes(1, complete=False, failed=True, npz=False)) == \
        ("fresh", ["failed_before"])
    assert _kind(shapes(2, complete=False, npz=False)) == ("fresh", ["incomplete"])


@pytest.mark.parametrize("kw, reason", [
    ({"npz": False}, "no_npz"),
    ({"librosa_version": 1}, "no_librosa"),
    ({"librosa_json": False}, "no_librosa"),
    ({"needs_recapture": True}, "needs_recapture"),
])
def test_each_other_failure_of_the_bar_is_a_recapture(shapes, kw, reason):
    kind, reasons = _kind(shapes(1, **kw))
    assert kind == "recapture" and reason in reasons


def test_the_sidecars_own_head_wins_over_the_npz(shapes):
    u = shapes(1, first_ts=5_000, sidecar_first=0)
    v = absorb_bar.classify(u, HEAD_MAX)
    assert v.kind == "skip"
    assert absorb_bar.read_facts(u).head_source == "sidecar"
    u2 = shapes(2, first_ts=5_000)
    assert absorb_bar.read_facts(u2).head_source == "npz"


def test_force_recapture_turns_a_skip_into_a_recapture(shapes):
    u = shapes(1, first_ts=0)
    assert _kind(u, force=True) == ("recapture", ["force_recapture"])
    assert _kind(shapes(2, first_ts=9_000), force=True) == ("recapture", ["headless"])


def test_has_head_is_the_bar_without_the_force_tag(shapes):
    ok, v = absorb_bar.has_head(shapes(1, first_ts=200), HEAD_MAX)
    assert ok and v.head_ms == 200
    ok, v = absorb_bar.has_head(shapes(2, first_ts=6_000), HEAD_MAX)
    assert not ok and v.reasons == ["headless"]


def test_missing_ms_orders_the_worst_heads_first(shapes):
    fresh = absorb_bar.classify("spotify:track:none", HEAD_MAX)
    big = absorb_bar.classify(shapes(1, first_ts=60_000), HEAD_MAX)
    small = absorb_bar.classify(shapes(2, first_ts=2_000), HEAD_MAX)
    nothing = absorb_bar.classify(shapes(3, first_ts=300_000), HEAD_MAX)
    assert nothing.missing_ms == 200_000
    assert big.missing_ms > small.missing_ms
    assert fresh.missing_ms >= 1
