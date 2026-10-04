"""RE-ANALYSIS — the stamp on generated cues, the refresh of one song on its
next play, and the dry-run-first library refresh (Sonic + HTTP). The
Admiral, 2026-10-04: "a settings and analysis-version stamp on analysed
cues, with background refresh of a song on its next play when the stamp is
stale. A Sonic 'refresh analysed triggers' command (all songs or one): dry
run first, one batched write inside SPECTRA, backup, generated rows only,
logged."

Every safety rule the plan names is a test here: generated rows only, never
seed a song holding only his triggers, never put back a cue he edited or
deleted, back up first, and a before/after diff that restores anything the
write was not meant to change.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.models.trigger import FireResponseAction, FireSceneAction, SpectraTrigger

SONG_A = "spotify:track:refresh-a"
SONG_B = "spotify:track:refresh-b"
SONG_MINE = "spotify:track:refresh-only-mine"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysed_refresh, analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "testbed" / "analysis")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "spectra" / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "spectra" / "room_controls.json")
    monkeypatch.setattr(scfg, "INTENSITY_SCALE_MARKS_FILE", tmp_path / "spectra" / "marks.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "spectra" / "scenes.json")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    (tmp_path / "spectra").mkdir()
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    analysis_reader._capture_offset_cache.clear()
    monkeypatch.setattr(analysed_refresh, "_last_plan", None)
    monkeypatch.setattr(analysed_refresh, "_YIELD_S", 0.0)
    yield tmp_path


def _write_analysis(uri, stem, sections, analyzed_at="2026-09-01T00:00:00+00:00"):
    from spectra import config as scfg
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(json.dumps({"spotify_uri": uri}))
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(json.dumps(
        {"spotify_uri": uri, "analyzed_at": analyzed_at, "sections": sections}))
    from spectra.services import analysis_reader
    analysis_reader._index_built = False


def _sections(*boundaries, end=120_000):
    marks = [0, *boundaries, end]
    energies = [0.2, 0.9, 0.4, 0.7, 0.3, 0.8, 0.5]
    return [{"start_ms": a, "end_ms": b, "energy_rms": energies[i % len(energies)]}
            for i, (a, b) in enumerate(zip(marks, marks[1:]))]


def _set_controls(**changes):
    from spectra.services import room_controls
    state = room_controls.load_room_controls().model_copy(update=changes)
    room_controls.save_room_controls(state)


def _authored(ts, kind="fire_scene"):
    action = (FireSceneAction(intensity=0.6) if kind == "fire_scene"
              else FireResponseAction(event_class="flare", intensity=0.4))
    return SpectraTrigger(timestamp_ms=ts, action=action)


def _raw():
    from spectra import config as scfg
    return json.loads(scfg.TRIGGERS_FILE.read_text())


def _gen(uri):
    from spectra.services import trigger_store
    return [t for t in trigger_store.list_for_song(uri) if t.source == "generated"]


# ── the stamp ──────────────────────────────────────────────────────────────

def test_generation_stamps_every_cue_in_one_write(monkeypatch):
    from spectra.services import midsong_generator, trigger_store
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000, 80_000))
    saves = []
    real = trigger_store._save_raw
    monkeypatch.setattr(trigger_store, "_save_raw", lambda d: (saves.append(1), real(d)))
    out = midsong_generator.generate_for_song(SONG_A)
    assert out["added"] == 3 and len(saves) == 1, "one batched write, not one per cue"
    stamp = midsong_generator.generator_stamp(SONG_A)
    assert {t.generator_stamp for t in _gen(SONG_A)} == {stamp}


def test_the_stamp_moves_with_settings_version_and_analysis(monkeypatch):
    from spectra.services import midsong_generator
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000))
    base = midsong_generator.generator_stamp(SONG_A)
    assert midsong_generator.generator_stamp(SONG_A) == base, "deterministic"
    _set_controls(transitions_per_minute=3.0)
    rate = midsong_generator.generator_stamp(SONG_A)
    assert rate != base, "a settings change marks the song stale"
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000), analyzed_at="2026-10-01T00:00:00+00:00")
    reanalysed = midsong_generator.generator_stamp(SONG_A)
    assert reanalysed != rate, "a re-analysis of the song marks it stale"
    monkeypatch.setattr(midsong_generator, "GENERATOR_VERSION", "test-bump")
    assert midsong_generator.generator_stamp(SONG_A) != reanalysed, \
        "a generator version bump marks every song stale"


# ── one song, on its next play ─────────────────────────────────────────────

def test_a_fresh_song_is_left_alone(monkeypatch):
    from spectra.services import midsong_generator, trigger_store
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000))
    midsong_generator.generate_for_song(SONG_A)
    saves = []
    monkeypatch.setattr(trigger_store, "_save_raw", lambda d: saves.append(1))
    assert midsong_generator.refresh_song_if_stale(SONG_A)["status"] == "fresh"
    assert saves == []


def test_a_stale_song_is_replanned_and_his_triggers_are_untouched():
    from spectra.services import midsong_generator, trigger_store
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000, 80_000))
    midsong_generator.generate_for_song(SONG_A)
    mine = _authored(33_000)
    trigger_store.upsert(SONG_A, mine)
    mine_raw = [r for r in _raw()[SONG_A] if r["id"] == mine.id][0]
    # a re-analysis moves one boundary and drops another
    _write_analysis(SONG_A, "a", _sections(21_000, 80_000),
                    analyzed_at="2026-10-02T00:00:00+00:00")
    out = midsong_generator.refresh_song_if_stale(SONG_A)
    assert out["status"] == "refreshed"
    assert {t.generator_key for t in _gen(SONG_A)} == {"section:21000", "section:80000"}
    assert [r for r in _raw()[SONG_A] if r["id"] == mine.id] == [mine_raw], \
        "his own trigger is byte-identical"
    assert midsong_generator.refresh_song_if_stale(SONG_A)["status"] == "fresh"


def test_rows_from_before_the_stamp_existed_read_as_stale():
    from spectra.services import midsong_generator, trigger_store
    _write_analysis(SONG_A, "a", _sections(20_000))
    trigger_store.upsert(SONG_A, SpectraTrigger(
        timestamp_ms=20_000, source="generated", generator_key="section:20000",
        action=FireSceneAction(intensity=1.0)))
    assert midsong_generator.refresh_song_if_stale(SONG_A)["status"] == "refreshed"
    assert _gen(SONG_A)[0].generator_stamp is not None


def test_a_song_holding_only_his_triggers_is_never_seeded():
    from spectra.services import midsong_generator, trigger_store
    _write_analysis(SONG_MINE, "mine", _sections(20_000, 50_000))
    trigger_store.upsert(SONG_MINE, _authored(10_000))
    before = _raw()
    out = midsong_generator.refresh_song_if_stale(SONG_MINE)
    assert out["status"] == "skipped"
    assert _raw() == before


def test_an_unreadable_analysis_keeps_the_stored_cues():
    from spectra import config as scfg
    from spectra.services import midsong_generator
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000))
    midsong_generator.generate_for_song(SONG_A)
    before = _raw()
    (scfg.AUDIO_SHAPES_DIR / "a.librosa.json").write_text("{ not json")
    _set_controls(transitions_per_minute=3.0)
    out = midsong_generator.refresh_song_if_stale(SONG_A)
    assert out["status"] == "skipped" and _raw() == before


def test_cues_he_edited_or_deleted_are_never_put_back():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    from spectra.services import analysed_claims, midsong_generator
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000, 80_000))
    midsong_generator.generate_for_song(SONG_A)
    cues = sorted(_gen(SONG_A), key=lambda t: t.timestamp_ms)
    client = TestClient(create_app())
    edited = json.loads(cues[0].model_copy(update={"timestamp_ms": 22_000}).model_dump_json())
    assert client.post(f"/api/triggers?uri={SONG_A}", json=edited).status_code == 200
    assert client.delete(f"/api/triggers/{cues[1].id}?uri={SONG_A}").status_code == 200
    assert analysed_claims.claimed_keys(SONG_A) == {cues[0].generator_key, cues[1].generator_key}

    _set_controls(transitions_per_minute=29.0)   # stale → re-plan on next play
    assert midsong_generator.refresh_song_if_stale(SONG_A)["status"] == "refreshed"
    keys = {t.generator_key for t in _gen(SONG_A)}
    assert keys == {cues[2].generator_key}, "neither claimed moment came back"
    from spectra.services import trigger_store
    mine = trigger_store.get(SONG_A, cues[0].id)
    assert mine.source == "authored" and mine.timestamp_ms == 22_000
    assert midsong_generator.generate_for_song(SONG_A)["added"] == 0, \
        "an explicit ⟳ Generate respects the claims too"


# ── the trigger engine's first-play edge ───────────────────────────────────

def test_first_play_schedules_a_refresh_only_for_songs_with_analysed_cues():
    from spectra.services.trigger_engine import TriggerEngine
    store = {
        SONG_A: [SpectraTrigger(timestamp_ms=1, source="generated",
                                generator_key="section:1",
                                action=FireSceneAction())],
        SONG_MINE: [_authored(5)],
    }
    calls = {"generate": [], "refresh": []}

    async def gen(uri):
        calls["generate"].append(uri)

    async def refresh(uri):
        calls["refresh"].append(uri)
        return {"status": "refreshed"}

    async def run():
        eng = TriggerEngine(list_triggers=lambda u: store.get(u, []),
                            auto_generate=gen, auto_refresh=refresh)
        eng._uri = SONG_A
        eng._flare_plan_uri = SONG_A
        eng._flare_triggers = ["stale-plan"]
        for uri in (SONG_A, SONG_MINE, "spotify:track:empty"):
            eng.maybe_auto_generate(uri)
        await asyncio.sleep(0.02)
        return eng

    eng = asyncio.run(run())
    assert calls == {"generate": ["spotify:track:empty"], "refresh": [SONG_A]}
    assert eng._flare_plan_uri is None and eng._flare_triggers == [], \
        "a re-planned playing song drops its cached flare plan"


# ── the library refresh ────────────────────────────────────────────────────

def _seed_library():
    from spectra.services import midsong_generator, trigger_store
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000, 80_000))
    _write_analysis(SONG_B, "b", _sections(30_000, 60_000))
    _write_analysis(SONG_MINE, "mine", _sections(20_000, 50_000))
    midsong_generator.generate_for_song(SONG_A)
    midsong_generator.generate_for_song(SONG_B)
    trigger_store.upsert(SONG_A, _authored(41_000, "fire_response"))
    trigger_store.upsert(SONG_MINE, _authored(10_000))


def test_the_dry_run_writes_nothing_and_the_apply_needs_its_plan_id(tmp_path):
    from spectra import config as scfg
    from spectra.services import analysed_refresh
    _seed_library()
    _write_analysis(SONG_A, "a", _sections(25_000, 80_000), analyzed_at="2026-10-03")
    before_bytes = scfg.TRIGGERS_FILE.read_bytes()
    report = analysed_refresh.plan()
    assert report["status"] == "dry_run"
    assert scfg.TRIGGERS_FILE.read_bytes() == before_bytes, "a dry run writes nothing"
    assert report["songs"]["scanned"] == 2, "the song holding only his triggers is not a target"
    assert report["songs"]["to_change"] == 1 and report["cues"]["added"] == 1
    assert analysed_refresh.apply(None)["status"] == "refused"
    assert analysed_refresh.apply("not-the-plan")["status"] == "refused"
    assert scfg.TRIGGERS_FILE.read_bytes() == before_bytes


def test_the_apply_backs_up_writes_once_and_changes_only_planned_generated_rows(monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysed_refresh, trigger_store
    _seed_library()
    _write_analysis(SONG_A, "a", _sections(25_000, 80_000), analyzed_at="2026-10-03")
    old = _raw()
    old_bytes = scfg.TRIGGERS_FILE.read_bytes()
    report = analysed_refresh.plan()
    saves = []
    real = trigger_store._save_raw
    monkeypatch.setattr(trigger_store, "_save_raw", lambda d: (saves.append(1), real(d)))
    result = analysed_refresh.apply(report["plan_id"])
    assert result["status"] == "applied" and result["verified"] and result["restored"] == 0
    assert len(saves) == 1, "one write for the whole library"
    from pathlib import Path
    assert Path(result["backup"]).read_bytes() == old_bytes, "the backup is the store as it was"
    new = _raw()
    assert new[SONG_MINE] == old[SONG_MINE] and new[SONG_B] == old[SONG_B]
    own_old = [r for r in old[SONG_A] if r.get("source") != "generated"]
    own_new = [r for r in new[SONG_A] if r.get("source") != "generated"]
    assert own_new == own_old
    assert {t.generator_key for t in _gen(SONG_A)} == {"section:25000", "section:80000"}
    assert analysed_refresh.apply(report["plan_id"])["status"] == "refused", \
        "a plan applies once"
    log = analysed_refresh.load_log()
    assert [e["kind"] for e in log] == ["dry_run", "apply"]


def test_a_song_that_changed_since_the_dry_run_is_left_as_it_is():
    from spectra.services import analysed_refresh, trigger_store
    _seed_library()
    _write_analysis(SONG_A, "a", _sections(25_000, 80_000), analyzed_at="2026-10-03")
    _write_analysis(SONG_B, "b", _sections(35_000), analyzed_at="2026-10-03")
    report = analysed_refresh.plan()
    assert report["songs"]["to_change"] == 2
    gen_b = _gen(SONG_B)[0]
    trigger_store.delete(SONG_B, gen_b.id)   # he removes a cue between dry run and yes
    after_edit = _raw()[SONG_B]
    result = analysed_refresh.apply(report["plan_id"])
    assert result["songs"] == {"applied": 1, "changed_since_dry_run": 1}
    assert result["changed_since_dry_run"] == [SONG_B]
    assert _raw()[SONG_B] == after_edit


def test_anything_the_write_was_not_meant_to_change_is_put_back(monkeypatch):
    from spectra.services import analysed_refresh
    _seed_library()
    _write_analysis(SONG_A, "a", _sections(25_000, 80_000), analyzed_at="2026-10-03")
    old = _raw()
    report = analysed_refresh.plan()
    real = analysed_refresh._rebuild

    def corrupting(rows, merge):
        out = real(rows, merge)
        for r in out:
            if r.get("source") != "generated":
                r = dict(r)
        out = [dict(r, timestamp_ms=1) if r.get("source") != "generated" else r for r in out]
        return out

    monkeypatch.setattr(analysed_refresh, "_rebuild", corrupting)
    result = analysed_refresh.apply(report["plan_id"])
    assert result["restored"] == 1
    assert _raw()[SONG_A] == old[SONG_A], "the song whose own rows changed was put back whole"


def test_one_song_scope_and_a_song_of_only_his_triggers_is_refused():
    from spectra.services import analysed_refresh
    _seed_library()
    assert analysed_refresh.plan(SONG_MINE)["status"] == "refused"
    report = analysed_refresh.plan(SONG_B)
    assert report["status"] == "dry_run" and report["songs"]["scanned"] == 1
    assert analysed_refresh.apply(report["plan_id"])["status"] == "refused", \
        "a one-song plan is not applied as a library plan"
    assert analysed_refresh.apply(report["plan_id"], SONG_B)["status"] == "applied"


def test_sonic_and_http_reach_the_same_dry_run():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    from spectra.services import settings_agent
    _seed_library()
    assert "refresh_analysed_triggers" in settings_agent.ALL_OPERATIONS
    via_sonic = asyncio.run(settings_agent._dispatch("refresh_analysed_triggers", {}))
    assert via_sonic["status"] == "dry_run"
    client = TestClient(create_app())
    body = client.post("/api/triggers/refresh-analysed", json={}).json()
    assert body["status"] == "dry_run"
    applied = client.post("/api/triggers/refresh-analysed",
                          json={"dry_run": False, "plan_id": body["plan_id"]}).json()
    assert applied["status"] == "applied"
    assert client.get("/api/triggers/refresh-analysed/log").json()["entries"][-1]["kind"] == "apply"


def test_a_capture_offset_past_the_song_end_keeps_the_stored_cues(monkeypatch):
    """Ten of his captures carry an offset past the track's own length
    (flagged needs_recapture=offset_past_end); re-placing their cues by it
    would move every one after the song ends."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, testbed_audio
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000))
    midsong_generator.generate_for_song(SONG_A)
    before = _raw()
    (scfg.AUDIO_SHAPES_DIR / "a.json").write_text(json.dumps(
        {"spotify_uri": SONG_A, "duration_ms": 120_000}))
    monkeypatch.setattr(testbed_audio, "capture_offset_ms_or_zero", lambda uri: 804_716)
    _set_controls(transitions_per_minute=3.0)
    out = midsong_generator.refresh_song_if_stale(SONG_A)
    assert out["status"] == "skipped" and "end" in out["reason"]
    assert _raw() == before


def test_an_offset_that_would_run_the_capture_past_the_end_keeps_the_cues(monkeypatch):
    """A whole-song WAV claiming to start 163s in (his real 7E6bhc...) is the
    same impossibility one step removed; a small ordinary offset is not."""
    from spectra import config as scfg
    from spectra.services import midsong_generator, testbed_audio
    _write_analysis(SONG_A, "a", _sections(20_000, 50_000, end=120_000))
    (scfg.AUDIO_SHAPES_DIR / "a.json").write_text(json.dumps(
        {"spotify_uri": SONG_A, "duration_ms": 121_000}))
    monkeypatch.setattr(testbed_audio, "capture_offset_ms_or_zero", lambda uri: 60_000)
    assert midsong_generator.capture_offset_past_end(SONG_A)
    monkeypatch.setattr(testbed_audio, "capture_offset_ms_or_zero", lambda uri: 6_000)
    assert not midsong_generator.capture_offset_past_end(SONG_A)
