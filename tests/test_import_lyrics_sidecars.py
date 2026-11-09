"""scripts/import_lyrics_sidecars.py: a word timeline is copied beside its
song only while the audio it was aligned against is unchanged, every refusal
is by name, and `flagged/` is never read."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pytest

from spectra.services import lyrics_sidecar

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "import_lyrics_sidecars", REPO / "scripts" / "import_lyrics_sidecars.py")
importer = importlib.util.module_from_spec(_spec)
sys.modules["import_lyrics_sidecars"] = importer  # a dataclass reads its own module
_spec.loader.exec_module(importer)

STEM = "Artist - Song"
URI = "spotify:track:importtest"


def _sidecar(*, wav, npz, flags=None, schema=lyrics_sidecar.SCHEMA, stem=STEM, uri=URI, words=None):
    stat = wav.stat()
    return {
        "schema": schema, "uri": uri, "stem": stem, "lrclib_id": 7, "lang": "eng",
        "provenance": "lrclib_synced", "mode": "line_anchored", "flags": flags or [],
        "stamp": {
            "capture_offset_ms": 1000,
            "wav_bytes": stat.st_size, "wav_mtime_ns": stat.st_mtime_ns,
            "label_map": {"npz_sha256": hashlib.sha256(npz.read_bytes()).hexdigest()},
        },
        "lines": [{"line": 0, "text": "red light", "lrc_ms": 500}],
        "words": words if words is not None else [
            {"w": "red", "n": "red", "line": 0, "ms": 2000.0, "end_ms": 2300.0,
             "wav_ms": 1000.0, "end_wav_ms": 1300.0, "conf": 0.5},
            {"w": "light", "n": "light", "line": 0, "ms": 2400.0, "end_ms": 2900.0,
             "wav_ms": 1400.0, "end_wav_ms": 1900.0, "conf": 0.5},
        ],
    }


@pytest.fixture
def world(tmp_path):
    shapes = tmp_path / "audio_shapes"
    shapes.mkdir()
    source = tmp_path / "holding"
    source.mkdir()
    wav = shapes / f"{STEM}.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 400)
    npz = shapes / f"{STEM}.npz"
    np.savez(npz, timestamps_ms=np.arange(0, 3000, 11), rms_mid=np.ones(273), rms_total=np.ones(273))
    (shapes / f"{STEM}.json").write_text(json.dumps({"spotify_uri": URI}))
    analysis = shapes / f"{STEM}.librosa.json"
    analysis.write_text(json.dumps({"beats": []}))
    os.chmod(analysis, 0o640)

    def place(doc=None, **kw):
        sidecar = doc if doc is not None else _sidecar(wav=wav, npz=npz, **kw)
        (source / f"{STEM}.lyrics.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
        return sidecar

    return shapes, source, wav, npz, place


def _one(world, **kw):
    shapes, source, *_ = world
    return importer.import_one(STEM, source, shapes, **kw)


def _dest(world):
    return world[0] / f"{STEM}.lyrics.json"


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(world):
    world[4]()
    assert _one(world, apply=False).outcome == importer.OUTCOME_WOULD_IMPORT
    assert not _dest(world).exists()


def test_apply_copies_it_beside_the_analysis_with_provenance_kept(world):
    placed = world[4]()
    assert _one(world, apply=True).outcome == importer.OUTCOME_IMPORTED
    stored = json.loads(_dest(world).read_text(encoding="utf-8"))
    for key in ("words", "stamp", "lrclib_id", "provenance", "mode", "lang", "uri"):
        assert stored[key] == placed[key]
    src = world[1] / f"{STEM}.lyrics.json"
    assert stored["imported"]["source_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert stored["imported"]["source_file"] == str(src)
    assert stored["imported"]["importer"] == importer.IMPORTER_NAME
    assert stored["imported"]["at"].endswith("Z")


def test_the_copy_takes_the_analysis_files_mode_and_leaves_no_temp_behind(world):
    world[4]()
    _one(world, apply=True)
    assert (_dest(world).stat().st_mode & 0o777) == 0o640
    assert [p.name for p in world[0].iterdir() if ".tmp" in p.name] == []


def test_a_second_run_changes_nothing(world):
    world[4]()
    _one(world, apply=True)
    before = _dest(world).read_bytes(), _dest(world).stat().st_mtime_ns
    assert _one(world, apply=True).outcome == importer.OUTCOME_UNCHANGED
    assert (_dest(world).read_bytes(), _dest(world).stat().st_mtime_ns) == before


def test_a_new_alignment_of_the_same_capture_replaces_the_old_copy(world):
    placed = world[4]()
    _one(world, apply=True)
    placed["lrclib_id"] = 8
    world[4](placed)
    assert _one(world, apply=True).outcome == importer.OUTCOME_IMPORTED
    assert json.loads(_dest(world).read_text(encoding="utf-8"))["lrclib_id"] == 8


@pytest.mark.parametrize("mutate,reason", [
    (lambda w, n: w.write_bytes(b"RIFF" + b"\0" * 500), "wav_changed"),
    (lambda w, n: os.utime(w, ns=(1, 1)), "wav_changed"),
    (lambda w, n: w.unlink(), "wav_missing"),
    (lambda w, n: n.write_bytes(n.read_bytes() + b"x"), "npz_changed"),
    (lambda w, n: n.unlink(), "npz_missing"),
])
def test_a_changed_capture_is_refused_by_name(world, mutate, reason):
    world[4]()
    mutate(world[2], world[3])
    out = _one(world, apply=True)
    assert out.outcome == importer.OUTCOME_REFUSED
    assert reason in out.reasons
    assert not _dest(world).exists()


def test_a_flagged_sidecar_is_refused(world):
    world[4](flags=["weak_scan_contrast"])
    out = _one(world, apply=True)
    assert out.outcome == importer.OUTCOME_REFUSED
    assert "flagged_by_the_alignment_job" in out.reasons


def test_the_flagged_folder_is_never_read(world):
    shapes, source, *_ = world
    flagged = source / "flagged"
    flagged.mkdir()
    (flagged / f"{STEM}.flagged.json").write_text("{ this is not JSON and must not be parsed")
    out = importer.import_one(STEM, source, shapes, apply=True)
    assert out.outcome == importer.OUTCOME_FLAGGED
    assert not _dest(world).exists()


def test_pointing_it_at_the_flagged_folder_is_refused(world):
    _, source, *_ = world
    flagged = source / "flagged"
    flagged.mkdir()
    with pytest.raises(SystemExit, match="flagged"):
        importer.main(["--source", str(flagged), "--shapes-dir", str(world[0]), "--all"])


def test_the_old_schema_is_refused(world):
    world[4](schema="spotfx.lyrics.v1")
    out = _one(world, apply=True)
    assert out.outcome == importer.OUTCOME_REFUSED
    assert f"schema_not_{lyrics_sidecar.SCHEMA}" in out.reasons


def test_a_sidecar_for_a_different_recording_is_refused(world):
    world[4](uri="spotify:track:someoneelse")
    assert "uri_does_not_match_capture" in _one(world, apply=True).reasons


def test_a_filename_that_disagrees_with_the_sidecar_is_refused(world):
    world[4](stem="Other - Thing")
    assert "stem_does_not_match_filename" in _one(world, apply=True).reasons


def test_a_song_with_no_analysis_to_sit_beside_is_refused(world):
    (world[0] / f"{STEM}.librosa.json").unlink()
    world[4]()
    assert "no_librosa_analysis" in _one(world, apply=True).reasons


def test_a_song_not_in_the_holding_directory_says_so(world):
    assert _one(world, apply=True).outcome == importer.OUTCOME_NOT_IN_SOURCE


def test_unparseable_source_is_refused_by_name(world):
    (world[1] / f"{STEM}.lyrics.json").write_text("{ nope")
    out = _one(world, apply=True)
    assert out.outcome == importer.OUTCOME_REFUSED
    assert out.reasons[0].startswith("unreadable")


@pytest.mark.parametrize("words,reason", [
    ([], "no_words"),
    ([{"w": "a", "n": "a", "line": 0, "ms": 5.0, "end_ms": 1.0, "wav_ms": 0.0, "end_wav_ms": 1.0}],
     "word_ends_before_it_starts"),
    ([{"w": "a", "n": "a", "line": 0, "ms": 5.0}], "word_missing_times"),
    ([{"n": "a", "line": 0, "ms": 5.0, "end_ms": 6.0, "wav_ms": 0.0, "end_wav_ms": 1.0}], "word_missing_text"),
    ([{"w": "a", "n": "a", "line": 0, "ms": 9.0, "end_ms": 10.0, "wav_ms": 0.0, "end_wav_ms": 1.0},
      {"w": "b", "n": "b", "line": 0, "ms": 1.0, "end_ms": 2.0, "wav_ms": 0.0, "end_wav_ms": 1.0}],
     "words_out_of_order"),
])
def test_malformed_words_are_refused_by_name(world, words, reason):
    world[4](words=words)
    assert reason in _one(world, apply=True).reasons


def test_the_command_is_a_dry_run_unless_told_otherwise(world, capsys):
    shapes, source, _, _, place = world
    place()
    assert importer.main(["--source", str(source), "--shapes-dir", str(shapes), "--all"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "would_import" in out and "nothing written" in out
    assert not _dest(world).exists()
    assert importer.main(["--source", str(source), "--shapes-dir", str(shapes), "--all", "--apply"]) == 0
    assert _dest(world).exists()


def test_a_songs_file_selects_exactly_those_songs(world, tmp_path):
    shapes, source, _, _, place = world
    place()
    songs = tmp_path / "songs.json"
    songs.write_text(json.dumps({"songs": [{"stem": STEM}]}))
    assert importer.main(["--source", str(source), "--shapes-dir", str(shapes),
                          "--songs", str(songs), "--apply"]) == 0
    assert _dest(world).exists()
