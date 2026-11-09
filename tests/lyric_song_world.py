"""A song on disk for the lyric-label tests: a capture, its analysis and a word
timeline, the same shape the importer leaves. Invented words."""
from __future__ import annotations

import hashlib
import json

import numpy as np

URI = "spotify:track:lyricmatches1"
STEM = "Artist - Song"
OFFSET = 5000.0

LINES = [
    "the red light",        # hook
    "azul sobre el mar",
    "the red light",        # hook again
    "don't you know",
]


def word(text, ms, end_ms, line, norm=None):
    wav_ms = ms - OFFSET
    return {"w": text, "n": norm if norm is not None else text.lower().strip(",."),
            "line": line, "ms": ms, "end_ms": end_ms, "wav_ms": wav_ms,
            "end_wav_ms": wav_ms + (end_ms - ms), "conf": 0.5}


def words(lines=LINES, start=10_000.0, gap=400.0):
    out = []
    t = start
    for line_no, text in enumerate(lines):
        for token in text.split():
            out.append(word(token, t, t + 300.0, line_no))
            t += gap
        t += 800.0
    return out


def capture(scfg, stem=STEM, uri=URI):
    d = scfg.AUDIO_SHAPES_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.json").write_text(json.dumps({"spotify_uri": uri}))
    (d / f"{stem}.wav").write_bytes(b"RIFF" + b"\0" * 400)
    stamps = np.arange(int(OFFSET), 60_000, 11)
    np.savez(d / f"{stem}.npz", timestamps_ms=stamps, rms_total=np.full(len(stamps), 0.1),
             rms_mid=np.full(len(stamps), 0.1))
    beats = [{"ms": 5000.0 + i * 250.0, "is_downbeat": i % 16 == 0} for i in range(100)]
    (d / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": uri, "tempo_bpm": 120.0,
        "sections": [{"start_ms": 0, "end_ms": 50_000, "label": "a", "energy_rms": 0.5}],
        "beats": beats,
    }))


def sidecar(scfg, word_list, stem=STEM, uri=URI):
    d = scfg.AUDIO_SHAPES_DIR
    wav_stat = (d / f"{stem}.wav").stat()
    doc = {
        "schema": "spotfx.lyrics.v2", "uri": uri, "stem": stem, "lang": "eng",
        "provenance": "lrclib_synced", "mode": "line_anchored", "flags": [],
        "stamp": {"capture_offset_ms": OFFSET, "wav_bytes": wav_stat.st_size,
                  "wav_mtime_ns": wav_stat.st_mtime_ns,
                  "label_map": {"npz_sha256": hashlib.sha256(
                      (d / f"{stem}.npz").read_bytes()).hexdigest()}},
        "lines": [], "words": word_list,
    }
    (d / f"{stem}.lyrics.json").write_text(json.dumps(doc), encoding="utf-8")


def song(scfg, word_list=None, stem=STEM, uri=URI):
    capture(scfg, stem, uri)
    sidecar(scfg, words() if word_list is None else word_list, stem, uri)


def color_sets(scfg, cards=None):
    cards = cards if cards is not None else [
        {"id": "red1", "name": "Blood Red", "kind": "set",
         "entries": [{"color_kind": "solid", "color_value": "#ff0000"}]},
        {"id": "blue1", "name": "Mid - Ice", "kind": "set",
         "entries": [{"color_kind": "gradient",
                      "color_value": "linear-gradient(90deg, #0000ff 0%, #00ffff 100%)"}]},
    ]
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps({c["id"]: c for c in cards}), encoding="utf-8")


def isolate(tmp_path, monkeypatch, scfg, analysis_reader):
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    (tmp_path / "profiles").mkdir(exist_ok=True)
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
