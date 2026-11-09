"""The Sung words lane through the real app: the engine registry, the routes,
the one clock it draws on, the songs it must flag rather than draw as aligned,
and that it reaches nothing in the show."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import numpy as np
import pytest

URI = "spotify:track:lyricslane1"
STEM = "Artist - Song"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TESTBED_DIR", tmp_path / "spectra" / "testbed")
    monkeypatch.setattr(scfg, "TESTBED_AUDIO_DIR", tmp_path / "spectra" / "testbed" / "audio")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "spectra" / "testbed" / "analysis")
    monkeypatch.setattr(scfg, "TESTBED_PINNED_FILE", tmp_path / "spectra" / "testbed" / "pinned_audio.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTIONS_FILE", tmp_path / "spectra" / "testbed" / "promotions.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTED_IDS_FILE", tmp_path / "spectra" / "testbed" / "promoted_ids.json")
    (tmp_path / "profiles").mkdir()
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _trigger(timestamp_ms, kind, **extra):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(URI, SpectraTrigger(timestamp_ms=timestamp_ms, action={"kind": kind, **extra}))


CAPTURE_OFFSET_MS = 5000.0


def _word(text, ms, end_ms, line, slip=0.0, norm=None):
    """`ms` on the capture's labels; `wav_ms` where that sits in the WAV,
    `slip` being how far the labels have parted from the naive position."""
    wav_ms = ms - CAPTURE_OFFSET_MS - slip
    return {"w": text, "n": norm or text.lower().strip(",."), "line": line, "ms": ms, "end_ms": end_ms,
            "wav_ms": wav_ms, "end_wav_ms": wav_ms + (end_ms - ms), "conf": 0.5}


def _words(slip=0.0):
    """A hook sung four times, with 'red' held on a downbeat each time."""
    out = []
    t = 10_000.0
    line = 0
    for _ in range(4):
        out.append(_word("the", t, t + 150, line, slip))
        out.append(_word("red,", t + 200, t + 1200, line, slip))
        out.append(_word("light", t + 1300, t + 1500, line, slip))
        line += 1
        out.append(_word("verse", t + 1800, t + 2000, line, slip, norm=f"verse{line}"))
        out.append(_word("goes", t + 2100, t + 2300, line, slip, norm=f"goes{line}"))
        line += 1
        t += 4000.0
    return out


def _capture(scfg):
    d = scfg.AUDIO_SHAPES_DIR
    (d / f"{STEM}.json").write_text(json.dumps({"spotify_uri": URI}))
    (d / f"{STEM}.wav").write_bytes(b"RIFF" + b"\0" * 400)
    stamps = np.arange(int(CAPTURE_OFFSET_MS), 60_000, 11)
    np.savez(d / f"{STEM}.npz", timestamps_ms=stamps, rms_total=np.full(len(stamps), 0.1),
             rms_mid=np.full(len(stamps), 0.1))
    beats = [{"ms": 5000.0 + i * 250.0, "is_downbeat": i % 16 == 0} for i in range(200)]
    (d / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI, "tempo_bpm": 120.0,
        "sections": [{"start_ms": 0, "end_ms": 50_000, "label": "a", "energy_rms": 0.5}],
        "beats": beats,
    }))


def _sidecar(scfg, words):
    d = scfg.AUDIO_SHAPES_DIR
    wav_stat = (d / f"{STEM}.wav").stat()
    doc = {
        "schema": "spotfx.lyrics.v2", "uri": URI, "stem": STEM, "lang": "eng",
        "provenance": "lrclib_synced", "mode": "line_anchored", "flags": [],
        "stamp": {"capture_offset_ms": CAPTURE_OFFSET_MS, "wav_bytes": wav_stat.st_size,
                  "wav_mtime_ns": wav_stat.st_mtime_ns,
                  "label_map": {"npz_sha256": hashlib.sha256((d / f"{STEM}.npz").read_bytes()).hexdigest()}},
        "lines": [], "words": words,
    }
    (d / f"{STEM}.lyrics.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _song(slip=0.0):
    from spectra import config as scfg
    _capture(scfg)
    _trigger(10_000, "fire_response", event_class="flare")
    _trigger(14_000, "fire_scene", scene_id=None)
    return _sidecar(scfg, _words(slip))


def _marks(client, sensitivity=None):
    q = f"&emphasis_sensitivity={sensitivity}" if sensitivity is not None else ""
    return client.get(f"/api/testbed/engine-marks?uri={URI}&engine=lyrics&mark_kind=emphasis{q}").json()


def test_the_engine_is_listed_from_a_stat_without_parsing_the_words(monkeypatch):
    from spectra.services import analysis_reader
    _song()

    def _no_parse(*a, **k):
        raise AssertionError("the song listing parsed a word timeline")
    monkeypatch.setattr(analysis_reader, "lyrics_for_stem", _no_parse)
    row = next(s for s in _client().get("/api/testbed/songs").json() if s["uri"] == URI)
    assert row["engines"]["lyrics"]["available"] is True
    assert row["engines"]["lyrics"]["mark_count"] is None


def test_a_song_with_no_word_timeline_is_not_available():
    from spectra import config as scfg
    _capture(scfg)
    _trigger(10_000, "fire_response", event_class="flare")
    client = _client()
    row = next(s for s in client.get("/api/testbed/songs").json() if s["uri"] == URI)
    assert row["engines"]["lyrics"]["available"] is False
    body = client.get(f"/api/testbed/lyrics?uri={URI}").json()
    assert body["status"] == "none" and body["words"] == [] and body["note"]
    assert _marks(client)["available"] is False


def test_the_lyrics_route_gives_every_word_with_a_score_and_the_clock():
    _song()
    body = _client().get(f"/api/testbed/lyrics?uri={URI}").json()
    assert body["status"] == "ok"
    assert len(body["words"]) == 20
    assert all(set(w) == {"word", "line", "ms", "end_ms", "score"} for w in body["words"])
    assert body["clock"]["lane_clock"] == "capture_label"
    assert body["clock"]["flagged"] is False
    assert body["clock"]["max_slip_ms"] == 0.0


def test_emphasized_marks_carry_the_word_and_why_and_leave_room_for_a_label():
    _song()
    body = _marks(_client())
    assert body["available"] is True
    picked = body["estimate"]
    assert picked and all(m["label"] for m in picked)
    assert "red" in {m["label"] for m in picked}, "printed without its comma"
    detail = picked[0]["detail"]
    assert set(detail["features"]) == {"loud", "held", "beat", "line_end", "hook"}
    assert detail["matched_label"] is None


@pytest.mark.parametrize("raw,shown", [
    ("life,", "life"), ("¿Qué?", "Qué"), ("rock'n'roll", "rock'n'roll"), ("...", "..."),
])
def test_a_printed_word_sheds_only_the_punctuation_at_its_edges(raw, shown):
    from spectra.services import lyrics_timeline
    assert lyrics_timeline.display_word(raw) == shown


def test_the_slider_changes_what_is_picked_and_nothing_is_stored():
    from spectra import config as scfg
    doc = _song()
    client = _client()
    before = (scfg.AUDIO_SHAPES_DIR / f"{STEM}.lyrics.json").read_bytes()
    few = len(_marks(client, 0.3)["estimate"])
    many = len(_marks(client, 0.9)["estimate"])
    assert 0 <= few < many
    assert len(_marks(client, 1.0)["estimate"]) == len(doc["words"])
    assert (scfg.AUDIO_SHAPES_DIR / f"{STEM}.lyrics.json").read_bytes() == before


def test_a_bad_sensitivity_is_refused():
    _song()
    resp = _client().get(f"/api/testbed/engine-marks?uri={URI}&engine=lyrics"
                         "&mark_kind=emphasis&emphasis_sensitivity=2")
    assert resp.status_code == 422


def test_a_word_and_a_flare_at_the_same_moment_draw_at_the_same_number():
    """THE CLOCK RULE. The lane's marks are at the word's own label, not
    shifted by the capture offset the way a WAV-time engine's marks are, so
    a word and a trigger with the same stored number coincide on the page
    and in the room. (A capture offset of 5000 ms is in play here.)"""
    _song()
    client = _client()
    picked = _marks(client, 1.0)["estimate"]
    assert {m["time_ms"] for m in picked} == {w["ms"] for w in _words()}
    assert min(m["time_ms"] for m in picked) == 10_000.0
    flares = client.get(f"/api/testbed/marks?uri={URI}").json()["flares"]
    assert flares[0]["timestamp_ms"] == 10_000


def test_a_clean_song_is_scored_against_his_marks():
    _song()
    body = _client().get(f"/api/testbed/compare?uri={URI}&engine=lyrics&mark_kind=emphasis"
                         "&reference=flares&tolerance_ms=500&emphasis_sensitivity=1").json()
    assert body["metrics"]["n_reference"] == 1
    assert body["metrics"]["n_matched"] == 1


def test_a_song_whose_audio_slips_against_its_labels_is_flagged_and_not_scored():
    _song(slip=1500.0)
    client = _client()
    clock = client.get(f"/api/testbed/lyrics?uri={URI}").json()["clock"]
    assert clock["flagged"] is True
    assert clock["max_slip_ms"] == 1500.0
    assert "1.5 s" in clock["note"]
    body = client.get(f"/api/testbed/compare?uri={URI}&engine=lyrics&mark_kind=emphasis"
                      "&reference=flares&tolerance_ms=500&emphasis_sensitivity=1").json()
    assert body["metrics"] is None
    assert body["clock"]["flagged"] is True
    assert body["estimate"]  # the words still come back, just not scored


def test_just_inside_the_slip_limit_is_not_flagged():
    from spectra.services import lyrics_timeline
    _song(slip=lyrics_timeline.SLIP_FLAG_MS - 1.0)
    assert _client().get(f"/api/testbed/lyrics?uri={URI}").json()["clock"]["flagged"] is False


def test_a_recapture_makes_the_words_stale_and_they_are_not_drawn():
    from spectra import config as scfg
    _song()
    npz = scfg.AUDIO_SHAPES_DIR / f"{STEM}.npz"
    npz.write_bytes(npz.read_bytes() + b"recaptured")
    client = _client()
    body = client.get(f"/api/testbed/lyrics?uri={URI}").json()
    assert body["status"] == "stale" and body["words"] == []
    assert "npz_changed" in body["note"]
    assert _marks(client)["available"] is False


def test_a_wav_removed_by_retention_does_not_make_the_words_stale():
    """The WAV cap deletes older WAVs on purpose; the labels live in the
    `.npz`, which is kept."""
    from spectra import config as scfg
    _song()
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.wav").unlink()
    assert _client().get(f"/api/testbed/lyrics?uri={URI}").json()["status"] == "ok"


def test_a_malformed_timeline_is_reported_not_raised():
    from spectra import config as scfg
    _capture(scfg)
    _trigger(10_000, "fire_response", event_class="flare")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.lyrics.json").write_text(json.dumps({"schema": "nope"}))
    body = _client().get(f"/api/testbed/lyrics?uri={URI}").json()
    assert body["status"] == "invalid" and body["note"]


def test_a_mark_from_this_lane_cannot_be_pushed_to_his_real_triggers():
    _song()
    client = _client()
    from spectra.services import trigger_store
    before = len(trigger_store.list_for_song(URI))
    resp = client.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 10_000,
        "action": {"kind": "fire_response", "event_class": "flare"},
        "source_engine": "lyrics", "source_mark_kind": "emphasis", "confirmed": True,
    })
    assert resp.status_code == 422
    assert "read-only" in resp.json()["detail"]
    assert len(trigger_store.list_for_song(URI)) == before
    assert client.get(f"/api/testbed/promotions?uri={URI}").json()[-1]["reason"] == "read_only_engine"


def test_reading_the_lane_writes_nothing():
    from spectra import config as scfg
    _song()
    client = _client()

    def snapshot():
        roots = [scfg.AUDIO_SHAPES_DIR, scfg.TRIGGERS_FILE.parent]
        return {p: p.stat().st_mtime_ns for r in roots for p in r.rglob("*") if p.is_file()}
    before = snapshot()
    client.get(f"/api/testbed/lyrics?uri={URI}")
    _marks(client, 0.7)
    client.get(f"/api/testbed/compare?uri={URI}&engine=lyrics&mark_kind=emphasis&reference=flares&tolerance_ms=500")
    assert snapshot() == before


_SHOW_BOUNDARY_DRIVER = textwrap.dedent('''
    import json
    import sys

    import spectra.services.engine
    import spectra.services.trigger_engine
    import spectra.services.scene_response
    import spectra.services.fx_seam

    print(json.dumps({
        "lyrics_timeline": "spectra.services.lyrics_timeline" in sys.modules,
        "lyrics_emphasis": "spectra.services.lyrics_emphasis" in sys.modules,
        "lyrics_sidecar": "spectra.services.lyrics_sidecar" in sys.modules,
    }))
''')


def test_nothing_in_the_show_can_reach_the_lyrics_modules():
    """The ruling: no flares, no colour changes, nothing in the show. Proven
    in a FRESH interpreter (the light-mode cold-start precedent): a warm
    pytest process has already imported the lyrics modules via this file's
    own earlier tests, so an in-process sys.modules check would pass
    regardless of whether the show's own engine modules ever reach them."""
    proc = subprocess.run([sys.executable, "-c", _SHOW_BOUNDARY_DRIVER],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not out["lyrics_timeline"], (
        "importing the show's own engine modules pulled in lyrics_timeline")
    assert not out["lyrics_emphasis"], (
        "importing the show's own engine modules pulled in lyrics_emphasis")
    assert not out["lyrics_sidecar"], (
        "importing the show's own engine modules pulled in lyrics_sidecar")


def test_the_sidecar_index_skips_a_word_timeline_without_parsing_it(monkeypatch):
    """storage/audio_shapes is scanned as *.json on every index miss, on the
    event-loop thread; 400 word timelines must not be parsed there."""
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _song()
    (scfg.AUDIO_SHAPES_DIR / "Other.lyrics.json").write_text("{ deliberately not json")
    read = []
    original = pathlib.Path.read_text

    def spy(self, *a, **k):
        read.append(self.name)
        return original(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "read_text", spy)
    analysis_reader._build_index()
    assert not [name for name in read if name.endswith(".lyrics.json")]
    assert analysis_reader.stem_for_uri(URI) == STEM


def test_the_spot_effects_sidecar_index_skips_it_too(tmp_path, monkeypatch):
    import services.audio_analyzer as aa
    d = tmp_path / "shapes"
    d.mkdir()
    (d / "A - B.json").write_text(json.dumps({"spotify_uri": "spotify:track:ab"}))
    (d / "A - B.lyrics.json").write_text("{ deliberately not json")
    monkeypatch.setattr(aa, "AUDIO_SHAPES_DIR", d)
    monkeypatch.setattr(aa, "_audio_shape_index", {})
    monkeypatch.setattr(aa, "_index_files", {})
    aa._build_shape_index()
    assert aa._audio_shape_index == {"spotify:track:ab": "A - B"}
    assert "A - B.lyrics.json" not in aa._index_files


def test_the_engine_is_on_the_no_shift_list():
    from spectra.services import testbed_engines
    assert testbed_engines.ENGINE_LYRICS in testbed_engines.SONG_TIME_ENGINES
