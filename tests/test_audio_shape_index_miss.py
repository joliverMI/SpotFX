"""A lookup MISS on the audio-shape index must be cheap
(services/audio_analyzer.py, report data/absorb-music-plan §4.2 / §14 item 1).

Before: every miss re-globbed and json-parsed EVERY sidecar — 142 ms for his
~1,260, 3,294 times on 2026-10-13, 468 s of event-loop blocking. Now a miss
refreshes only when the directory's own mtime moved (a new sidecar is a new
directory entry), when the last look was racy, or when the backstop interval
has passed — and a refresh parses only sidecars whose (mtime, size) moved.

Every test drives the real module against a temp directory of real sidecars;
the only instrumentation is a counter around the module's own `json.loads`
and `os.scandir`, so "did it rescan" and "did it re-parse" are measured, not
inferred."""
from __future__ import annotations

import json
import os
import time
import types

import pytest

import services.audio_analyzer as aa

OLD_NS = time.time_ns() - 3600 * 1_000_000_000  # an hour ago: never racy


class _Counters:
    def __init__(self) -> None:
        self.loads = 0
        self.scans = 0


@pytest.fixture
def shapes(tmp_path, monkeypatch):
    d = tmp_path / "audio_shapes"
    d.mkdir()
    monkeypatch.setattr(aa, "AUDIO_SHAPES_DIR", d)
    # A fresh, never-built index for this module, restored afterwards.
    monkeypatch.setattr(aa, "_audio_shape_index", {})
    monkeypatch.setattr(aa, "_audio_shape_index_built", [False])
    # raising=False: these exist only since the fix, and the same file is
    # run against the pre-fix module as its red control.
    monkeypatch.setattr(aa, "_index_files", {}, raising=False)
    monkeypatch.setattr(aa, "_index_dir_mtime_ns", [None], raising=False)
    monkeypatch.setattr(aa, "_index_built_at", [0.0], raising=False)
    monkeypatch.setattr(aa, "_index_racy", [False], raising=False)

    counters = _Counters()
    real_loads, real_scandir = json.loads, os.scandir

    def counting_loads(*a, **k):
        counters.loads += 1
        return real_loads(*a, **k)

    def counting_scandir(*a, **k):
        counters.scans += 1
        return real_scandir(*a, **k)

    monkeypatch.setattr(aa, "json", types.SimpleNamespace(loads=counting_loads, dumps=json.dumps))
    monkeypatch.setattr(aa, "os", types.SimpleNamespace(scandir=counting_scandir), raising=False)
    return d, counters


def _sidecar(d, stem, uri, *, mtime_ns=OLD_NS):
    p = d / f"{stem}.json"
    p.write_text(json.dumps({"spotify_uri": uri, "title": stem, "artist": "a",
                             "duration_ms": 1000, "sample_interval_ms": 11,
                             "npz_file": f"{stem}.npz"}))
    os.utime(p, ns=(mtime_ns, mtime_ns))
    return p


def _settle_dir(d, mtime_ns=OLD_NS):
    """Put the directory's own mtime in the past, as a quiet directory has."""
    os.utime(d, ns=(mtime_ns, mtime_ns))


def _library(d, n=40):
    for i in range(n):
        _sidecar(d, f"Artist - Song {i:03d}", f"spotify:track:s{i:03d}")
    # Neither of these is an audio-shape sidecar; both carry a spotify_uri.
    (d / "Artist - Song 000.librosa.json").write_text(json.dumps({"spotify_uri": "spotify:track:s000"}))
    (d / "Artist - Song 001.json.bak").write_text(json.dumps({"spotify_uri": "spotify:track:bak"}))
    _settle_dir(d)


def test_first_lookup_builds_the_whole_index_once(shapes):
    d, c = shapes
    _library(d)
    assert aa._shape_filename_for("spotify:track:s007") == "Artist - Song 007"
    assert c.scans == 1
    assert c.loads == 40          # every audio-shape sidecar, nothing else
    assert aa._shape_filename_for("spotify:track:bak") is None
    assert aa._audio_shape_index["spotify:track:s000"] == "Artist - Song 000"  # not the .librosa.json


def test_repeated_misses_on_an_unchanged_directory_do_not_rescan(shapes):
    """THE DEFECT: each of these used to be a full glob + 40 json parses."""
    d, c = shapes
    _library(d)
    assert aa.load_audio_shape_meta("spotify:track:nope") is None
    scans, loads = c.scans, c.loads

    for _ in range(50):
        assert aa.load_audio_shape_meta("spotify:track:nope") is None
        assert aa.flag_needs_recapture("spotify:track:nope", "x") is False
        assert aa.clear_needs_recapture("spotify:track:nope") is False

    assert c.scans == scans
    assert c.loads == loads


def test_a_new_sidecar_is_found_on_the_next_miss_parsing_only_itself(shapes):
    d, c = shapes
    _library(d)
    assert aa._shape_filename_for("spotify:track:new") is None
    loads = c.loads

    # Written by another process: this one's index never heard of it, but it
    # is a new directory entry, so the directory's mtime moves.
    _sidecar(d, "Artist - New", "spotify:track:new")
    meta = aa.load_audio_shape_meta("spotify:track:new")
    assert meta is not None and meta.spotify_uri == "spotify:track:new"
    # One parse to index the new sidecar, one to read it for the meta — the
    # 40 unchanged sidecars were stat'ed, not re-read.
    assert c.loads - loads == 2


def test_the_interval_backstop_refreshes_without_reparsing_unchanged_sidecars(shapes):
    d, c = shapes
    _library(d)
    assert aa._shape_filename_for("spotify:track:nope") is None
    scans, loads = c.scans, c.loads

    # A sidecar rewritten IN PLACE with a different URI moves no directory
    # entry, so only the interval can catch it.
    p = d / "Artist - Song 005.json"
    p.write_text(json.dumps({"spotify_uri": "spotify:track:renamed"}))
    os.utime(p, ns=(OLD_NS + 5_000, OLD_NS + 5_000))
    _settle_dir(d)
    assert aa._shape_filename_for("spotify:track:renamed") is None   # inside the interval
    assert c.scans == scans

    aa._index_built_at[0] -= aa._INDEX_MISS_RESCAN_INTERVAL_S + 1
    assert aa._shape_filename_for("spotify:track:renamed") == "Artist - Song 005"
    assert c.scans == scans + 1
    assert c.loads - loads == 1   # only the rewritten one
    assert aa._shape_filename_for("spotify:track:s005") is None


def test_a_racy_directory_still_finds_a_sidecar_that_left_its_mtime_unchanged(shapes):
    """A filesystem with coarse timestamps can create a file in the same tick
    as the last look, leaving the directory mtime identical. A look whose
    directory mtime was that recent is distrusted until a calmer look."""
    d, c = shapes
    _library(d)
    now = time.time_ns()
    _settle_dir(d, now)            # the directory changed "just now"
    assert aa._shape_filename_for("spotify:track:nope") is None
    assert aa._index_racy[0] is True

    _sidecar(d, "Artist - Same Tick", "spotify:track:tick")
    _settle_dir(d, now)            # coarse clock: the mtime did not move
    assert aa._shape_filename_for("spotify:track:tick") == "Artist - Same Tick"

    # Once a look sees a quiet directory, misses are free again.
    _settle_dir(d)
    aa._build_shape_index()
    assert aa._index_racy[0] is False
    scans = c.scans
    assert aa._shape_filename_for("spotify:track:nope") is None
    assert c.scans == scans


def test_a_refresh_rebinds_the_index_rather_than_clearing_it(shapes):
    """A worker thread may be reading the index while another refreshes it;
    clearing it in place makes every song read as a miss for that moment."""
    d, _c = shapes
    _library(d)
    aa._build_shape_index()
    before = aa._audio_shape_index
    snapshot = dict(before)
    _sidecar(d, "Artist - Later", "spotify:track:later")
    aa._build_shape_index()
    assert aa._audio_shape_index is not before
    assert before == snapshot
    assert aa._audio_shape_index["spotify:track:later"] == "Artist - Later"


def test_a_deleted_sidecar_leaves_the_index_on_the_next_refresh(shapes):
    d, _c = shapes
    _library(d)
    assert aa._shape_filename_for("spotify:track:s010") == "Artist - Song 010"
    (d / "Artist - Song 010.json").unlink()
    aa._build_shape_index()
    assert "spotify:track:s010" not in aa._audio_shape_index


def test_an_in_process_save_is_a_hit_without_any_refresh(shapes, monkeypatch):
    d, c = shapes
    _library(d)
    aa._build_shape_index()
    scans = c.scans
    from config import settings
    monkeypatch.setattr(settings, "audio_chunk_size", 512)
    rec = aa.AudioShapeRecorder("spotify:track:fresh", "Fresh", "Artist", 1000)
    for i in range(5):
        rec.ingest(aa.AudioFrame(i * 10, 0.1, 0.1, 0.1, 0.1))
    rec.save()
    assert aa._shape_filename_for("spotify:track:fresh") == "Artist - Fresh"
    assert c.scans == scans
