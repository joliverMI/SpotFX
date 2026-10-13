"""The end-of-play whole-song check (services/whole_song_check.py) and the
re-save withholding (xcorr_sweep.SweepEvaluator.stronger_elsewhere) —
data/lock-investigation/report.md §5.4, §8 recs 1 and 4.

Fixtures: tests/whole_song_world.py (his two failing songs' real stored
shapes, a live capture synthesised the way the report's §5.4 vote measured
it). Nothing here touches live storage or a live process."""
from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from services import whole_song_check as wsc
from services.xcorr_sweep import SweepConfig, SweepEvaluator
from tests import whole_song_world as W

CFG = wsc.WholeSongConfig()


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    monkeypatch.setattr(wsc, "_STORE_PATH", tmp_path / "whole_song_checks.json")


def _vote(song, *, truth=None, saved=None, seed=0, **live_kw):
    name, _title, true_ms, twin_ms = song
    ts, sq, raw = W.load_fixture(name)
    frames = W.live_frames(ts, raw, true_ms if truth is None else truth, seed=seed, **live_kw)
    return wsc.whole_song_vote(ts, sq, frames,
                               saved_offset_ms=twin_ms if saved is None else saved)


# ── 1. The two songs the engine could not correct ────────────────────────────

@pytest.mark.parametrize("song", [W.EL_EFECTO, W.PONLE_DEMBOW], ids=lambda s: s[1])
def test_the_whole_song_corrects_the_twin_the_engine_kept_resaving(song):
    _n, _t, true_ms, twin_ms = song
    vote = _vote(song)
    d = wsc.decide(vote, CFG)
    assert d.action == wsc.CORRECTED, d.reason
    assert d.offset_ms == true_ms
    assert vote.winner_bin_ms == true_ms
    assert vote.vote_fraction >= 0.9
    assert vote.median_r_winner >= 0.85
    # The twin he was stuck on scores like the report measured it (0.53-0.56).
    assert vote.median_r_saved < 0.65
    assert str(twin_ms) in d.reason.replace("+", "")


# ── 2. A song already right is never moved ───────────────────────────────────

@pytest.mark.parametrize("song", [W.EL_EFECTO, W.PONLE_DEMBOW], ids=lambda s: s[1])
@pytest.mark.parametrize("jitter", [0, -200, 150, 500])
@pytest.mark.parametrize("seed", [1, 2])
def test_a_song_already_right_is_never_moved(song, jitter, seed):
    _n, _t, true_ms, _twin = song
    vote = _vote(song, saved=true_ms + jitter, seed=seed)
    d = wsc.decide(vote, CFG)
    assert d.action in (wsc.AGREES, wsc.SMALL_MOVE), d.reason
    assert d.offset_ms is None


def test_a_saved_offset_that_scores_as_well_as_the_winner_is_not_replaced():
    vote = _vote(W.EL_EFECTO)
    # Pretend the saved offset scored as well as the winner: no lead, no move.
    vote.median_r_saved = vote.median_r_winner - 0.05
    assert wsc.decide(vote, CFG).action == wsc.NOT_AHEAD


# ── 3. A twin-ambiguous vote changes nothing ─────────────────────────────────

@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_twin_ambiguous_song_splits_its_vote_and_is_left_alone(seed):
    ts, sq, raw = W.periodic_shape()
    frames = W.live_frames(ts, raw, 1000, seed=seed)
    vote = wsc.whole_song_vote(ts, sq, frames, saved_offset_ms=-3000)
    d = wsc.decide(vote, CFG)
    assert d.action == wsc.NO_CLEAR_MAJORITY, d.reason
    assert d.offset_ms is None
    assert vote.vote_fraction < 0.5


def test_red_control_without_the_majority_gate_the_twin_song_would_move():
    """The harness can fail: with the majority gate collapsed, the same
    ambiguous vote WOULD rewrite the offset — so the gate is what holds."""
    ts, sq, raw = W.periodic_shape()
    vote = wsc.whole_song_vote(ts, sq, W.live_frames(ts, raw, 1000, seed=0),
                               saved_offset_ms=-3000)
    loose = wsc.WholeSongConfig(min_vote_fraction=0.0, min_median_r=0.0, min_r_margin=-1.0)
    assert wsc.decide(vote, loose).action == wsc.CORRECTED


# ── 4. Other refusals ─────────────────────────────────────────────────────────

def test_a_play_skipped_early_cannot_testify_about_the_whole_song():
    vote = _vote(W.EL_EFECTO, until_ms=50_000)
    assert wsc.decide(vote, CFG).action == wsc.TOO_FEW_WINDOWS


def test_a_noisy_room_below_the_strength_floor_is_left_alone():
    vote = _vote(W.PONLE_DEMBOW, noise=3.0, seed=4)
    d = wsc.decide(vote, CFG)
    assert d.action != wsc.CORRECTED, d.reason


def test_a_user_verified_offset_is_reported_never_saved():
    d = wsc.decide(_vote(W.EL_EFECTO), CFG, verification="user_verified")
    assert d.action == wsc.USER_VERIFIED
    assert d.offset_ms is None


def test_no_frames_is_no_vote():
    ts, sq, _raw = W.load_fixture("el_efecto")
    assert wsc.whole_song_vote(ts, sq, [], saved_offset_ms=0) is None


# ── 5. Cadence ────────────────────────────────────────────────────────────────

def test_cadence_every_unlocked_play_and_every_nth_locked_one():
    assert wsc.should_check(locked=False, locked_plays_since_check=0, cfg=CFG)
    assert not wsc.should_check(locked=True, locked_plays_since_check=3, cfg=CFG)
    assert wsc.should_check(locked=True, locked_plays_since_check=4, cfg=CFG)
    never = wsc.WholeSongConfig(locked_every=0)
    assert not wsc.should_check(locked=True, locked_plays_since_check=99, cfg=never)
    off = wsc.WholeSongConfig(enabled=False)
    assert not wsc.should_check(locked=False, locked_plays_since_check=0, cfg=off)


# ── 6. Settings ───────────────────────────────────────────────────────────────

def test_every_setting_is_a_real_config_field_with_its_shipped_default():
    from config import Settings
    fields = Settings.model_fields
    for key in wsc.SETTINGS:
        assert key in fields, key
    s = Settings()
    cfg = wsc.WholeSongConfig.from_settings(s)
    assert cfg == wsc.WholeSongConfig()
    assert s.xcorr_withhold_resave_min_repeats == 3
    assert SweepConfig.from_settings(s).withhold_resave_min_repeats == 3


@pytest.mark.parametrize("patch", [
    {"nope": 1},
    {"xcorr_whole_song_enabled": "yes"},
    {"xcorr_whole_song_min_r": 1.5},
    {"xcorr_whole_song_min_windows": 2.5},
    {"xcorr_whole_song_locked_every": -1},
    {"xcorr_whole_song_min_vote_fraction": True},
    {},
])
def test_bad_settings_are_refused_by_name(patch):
    with pytest.raises(wsc.SettingRejected):
        wsc.validate_patch(patch)


def test_good_settings_are_coerced():
    assert wsc.validate_patch({"xcorr_whole_song_min_windows": 20.0,
                               "xcorr_whole_song_min_r": 0.75,
                               "xcorr_whole_song_enabled": False}) == {
        "xcorr_whole_song_min_windows": 20, "xcorr_whole_song_min_r": 0.75,
        "xcorr_whole_song_enabled": False}


def test_settings_route_round_trip_persists_and_refuses(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from config import settings
    from routers import lock_history_router, settings_router
    monkeypatch.setattr(settings_router, "SETTINGS_FILE", tmp_path / "settings.json")
    for k in wsc.SETTINGS:
        monkeypatch.setattr(settings, k, getattr(settings, k))
    app = FastAPI()
    app.include_router(lock_history_router.router)
    c = TestClient(app)
    r = c.put("/api/lock-history/whole-song/settings",
              json={"xcorr_whole_song_locked_every": 2})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["xcorr_whole_song_locked_every"] == 2
    assert settings.xcorr_whole_song_locked_every == 2
    assert json.loads((tmp_path / "settings.json").read_text())[
        "xcorr_whole_song_locked_every"] == 2
    bad = c.put("/api/lock-history/whole-song/settings", json={"xcorr_whole_song_min_r": 9})
    assert bad.status_code == 422 and "xcorr_whole_song_min_r" in bad.text
    got = c.get("/api/lock-history/whole-song").json()
    assert got["entries"] == [] and got["settings"]["xcorr_whole_song_locked_every"] == 2


# ── 7. The service: the correction actually lands where the next play loads ──

def _service_world(tmp_path, monkeypatch, *, verification="auto_verified",
                   setlist_history=None):
    import services.auto_offset_service as aos
    from models.audio_shape import AudioShapeMeta
    side = tmp_path / "song.json"
    meta = {
        "spotify_uri": "spotify:track:elefecto", "title": "El Efecto",
        "artist": "Rauw Alejandro", "npz_file": "song.npz", "duration_ms": 217142,
        "capture_complete": True, "timestamp_offset_ms": 325,
        "offset_quality": 0.4, "offset_verification": verification,
        "sample_interval_ms": 12,
    }
    if setlist_history is not None:
        meta["setlist_offsets"] = {"sl1": {
            "timestamp_offset_ms": setlist_history[0],
            "history": [{"offset_ms": o} for o in setlist_history]}}
    try:
        AudioShapeMeta(**meta)
    except Exception as exc:   # pragma: no cover — schema drift guard
        pytest.fail(f"sidecar fixture no longer matches AudioShapeMeta: {exc}")
    side.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(aos, "AUDIO_SHAPES_DIR", tmp_path)
    monkeypatch.setattr(aos, "load_audio_shape_meta",
                        lambda _u: AudioShapeMeta(**json.loads(side.read_text())))
    applied = []
    engine = SimpleNamespace(
        apply_save=lambda *a, **k: applied.append((a, k)) or False,
        systemic_residual_for=lambda *a, **k: pytest.fail("whole-song must not feed the learner"),
    )
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(engine=engine))
    return aos, side, applied


def _run(aos, *, frames, setlist_id=None, locked=False):
    ts, sq, _raw = W.load_fixture("el_efecto")
    svc = aos.AutoOffsetService()
    ctx = aos.PlayContext(setlist_id=setlist_id, polled_duration_ms=217142, track=None)
    return asyncio.run(svc._run_whole_song_check(
        uri="spotify:track:elefecto", title="El Efecto", artist="Rauw Alejandro",
        locked=locked, frames=frames, stored_ts=ts, stored_bands=sq,
        play_context=ctx, cfg=wsc.WholeSongConfig()))


def _frames(truth=11750, seed=0):
    ts, _sq, raw = W.load_fixture("el_efecto")
    return W.live_frames(ts, raw, truth, seed=seed)


def test_the_service_saves_the_correction_the_next_play_loads(tmp_path, monkeypatch):
    aos, side, applied = _service_world(tmp_path, monkeypatch)
    d = _run(aos, frames=_frames())
    assert d.action == wsc.CORRECTED
    stored = json.loads(side.read_text())
    assert stored["timestamp_offset_ms"] == 11750
    assert stored["offset_history"][0]["source"] == wsc.SOURCE
    # The next play loads exactly this (trigger_engine's default-path base).
    from models.audio_shape import AudioShapeMeta
    assert aos._stored_base_offset(AudioShapeMeta(**stored), None) == 11750
    log = wsc.recent()
    assert log[0]["action"] == wsc.CORRECTED and log[0]["saved"] is True
    assert (log[0]["old_offset_ms"], log[0]["new_offset_ms"]) == (325, 11750)
    assert log[0]["wins"] >= 0.9 * log[0]["n_windows"]


def test_a_set_list_slot_history_is_replaced_so_the_median_moves(tmp_path, monkeypatch):
    aos, side, _ = _service_world(tmp_path, monkeypatch,
                                  setlist_history=[325, 300, 350, 325, 550])
    d = _run(aos, frames=_frames(), setlist_id="sl1")
    assert d.action == wsc.CORRECTED
    slot = json.loads(side.read_text())["setlist_offsets"]["sl1"]
    assert [h["offset_ms"] for h in slot["history"]] == [11750]
    from models.audio_shape import AudioShapeMeta
    assert aos._stored_base_offset(AudioShapeMeta(**json.loads(side.read_text())), "sl1") == 11750


def test_stored_base_offset_mirrors_resolve_shape_offsets_setlist_bias_fallback(monkeypatch):
    """A Set List that is active but has never seen this track falls back
    to the track's own default offset plus that Set List's recent-deltas
    bias — services/trigger_engine.py's _resolve_shape_offset third branch,
    lines 218-225. _stored_base_offset must mirror it exactly (base only,
    no systemic bias or perception trim layered on top)."""
    import services.auto_offset_service as aos
    from services import setlist_store, trigger_engine
    from models.audio_shape import AudioShapeMeta
    from models.setlist import Setlist

    monkeypatch.setattr(
        setlist_store, "get_by_id",
        lambda sid: Setlist(id=sid, recent_offset_deltas=[500, 700, 600]))

    meta = AudioShapeMeta(
        spotify_uri="spotify:track:unseen", title="Unseen", artist="Someone",
        npz_file="song.npz", duration_ms=200000, capture_complete=True,
        timestamp_offset_ms=325, offset_quality=0.4,
        offset_verification="auto_verified", sample_interval_ms=12,
        perception_trim_ms=50,
    )

    expected_bias = trigger_engine._setlist_delta_bias("sl-unseen")
    assert expected_bias == 600  # median of [500, 600, 700]
    assert aos._stored_base_offset(meta, "sl-unseen") == 325 + expected_bias

    # Perception trim must NOT be layered in here — only in
    # trigger_engine._resolve_shape_offset's own return.
    assert aos._stored_base_offset(meta, "sl-unseen") == 925

    # No Set List history at all (recent_offset_deltas has fewer than 2
    # entries) means zero bias — falls back to the plain track default.
    monkeypatch.setattr(
        setlist_store, "get_by_id",
        lambda sid: Setlist(id=sid, recent_offset_deltas=[500]))
    assert aos._stored_base_offset(meta, "sl-unseen") == 325


def test_the_service_leaves_a_right_song_untouched(tmp_path, monkeypatch):
    aos, side, applied = _service_world(tmp_path, monkeypatch)
    before = side.read_text()
    d = _run(aos, frames=_frames(truth=325))
    assert d.action == wsc.AGREES
    assert side.read_text() == before and applied == []
    assert wsc.recent()[0]["action"] == wsc.AGREES and wsc.recent()[0]["saved"] is None


def test_the_service_never_saves_over_a_user_verified_offset(tmp_path, monkeypatch):
    aos, side, applied = _service_world(tmp_path, monkeypatch, verification="user_verified")
    before = side.read_text()
    d = _run(aos, frames=_frames())
    assert d.action == wsc.USER_VERIFIED
    assert side.read_text() == before and applied == []


def test_schedule_skips_a_play_too_short_to_judge_and_counts_locked_plays(tmp_path, monkeypatch):
    aos, _side, _ = _service_world(tmp_path, monkeypatch)
    svc = aos.AutoOffsetService()
    ran = []

    async def fake_run(self, **kw):
        ran.append(kw)

    monkeypatch.setattr(aos.AutoOffsetService, "_run_whole_song_check", fake_run)
    ts, sq, _raw = W.load_fixture("el_efecto")
    meta = SimpleNamespace(title="El Efecto", artist="x")
    ctx = aos.PlayContext(setlist_id=None, polled_duration_ms=0, track=None)
    long_frames = _frames()
    short_frames = [f for f in long_frames if f[0] < 40_000]

    async def go():
        out = []
        for locked, fr in [(False, short_frames), (False, long_frames),
                           (True, long_frames), (True, long_frames), (True, long_frames),
                           (True, long_frames)]:
            t = svc._schedule_whole_song_check(
                uri="u", meta=meta, locked=locked, frames=fr,
                stored_ts=ts, stored_bands=sq, play_context=ctx)
            if t is not None:
                await t
            out.append(t is not None)
        return out

    assert asyncio.run(go()) == [False, True, False, False, False, True]
    assert all(kw["play_context"] is ctx for kw in ran)


# ── 8. The sweep schedules it after its own final save ───────────────────────

def test_the_real_sweep_schedules_the_check_after_its_final_save(monkeypatch, tmp_path):
    from tests import sweep_world_driver as D
    mod = D.current_module()
    seen = []

    def record(self, **kw):
        seen.append(dict(kw, saves_before=len(trace_holder[0].saves)
                         if trace_holder else None))

    trace_holder: list = []
    real_trace_init = D.Trace.__init__

    def keep(self, *a, **k):
        real_trace_init(self, *a, **k)
        trace_holder.append(self)

    monkeypatch.setattr(D.Trace, "__init__", keep)
    monkeypatch.setattr(mod.AutoOffsetService, "_schedule_whole_song_check", record)
    trace = D.run_world(mod, D.mayday_world(), monkeypatch, tmp_path,
                        settings_over={"xcorr_whole_song_enabled": True})
    assert len(seen) == 1
    call = seen[0]
    assert call["uri"] == D.URI
    assert call["saves_before"] == len(trace.saves)       # after the final save
    assert call["frames"] and call["frames"][-1][0] > 200_000   # the whole play
    assert call["play_context"].setlist_id is None


# ── 9. Rec. 4: never re-save a capped value over a stronger repeated find ────

def _evaluator(min_repeats=3):
    cfg = SweepConfig(
        global_threshold=0.50, old_correlating_floor=0.50, old_correlating_margin=0.20,
        save_confirm_tol_ms=300, save_min_confirm=2.0, save_min_confirm_anti=1.5,
        save_min_quality=0.50, single_save_r=0.78, single_save_q=0.70,
        single_save_far_r=0.90, single_save_far_q=0.85, far_jump_ms=1000,
        engine_snap_far_jump_ms=1000, engine_snap_far_jump_q=0.85, lock_q=0.70,
        lock_agree_windows=3, withhold_resave_min_repeats=min_repeats)
    return SweepEvaluator(cfg, uri="u", verification="auto_verified",
                          play_type="natural", seed_offset_ms=1525)


def _ponle_play(ev):
    """Ponle Dembow 18:42: the engine sat on +1,225 (OLD r 0.60-0.70) while
    seven windows found +6,225 at r 0.77-0.84 — never 0.20 ahead of OLD, so
    OLD won every window and the cluster fallback re-saved +1,225."""
    for i, (old_r, new_r) in enumerate([(0.70, 0.78), (0.62, 0.80), (0.66, 0.81),
                                        (0.60, 0.77), (0.65, 0.84), (0.68, 0.82),
                                        (0.64, 0.79)]):
        ev.process_window(
            40_000 + i * 6000, 45_000 + i * 6000, difficulty=0.9,
            new_result=(6225, new_r), old_r=old_r, stored_offset_ms=1225,
            stored_quality=0.6, engine_current_offset_ms=1225,
            engine_play_best_quality=0.6, envelope_exempt=True)
    return ev.finalize()


def test_red_control_without_withholding_the_capped_value_is_resaved():
    assert _ponle_play(_evaluator(min_repeats=0)).disk_save[0] == 1225


def test_the_capped_value_is_not_resaved_over_a_stronger_repeated_find():
    ev = _evaluator()
    final = _ponle_play(ev)
    assert final.disk_save is None
    assert ev.withheld_save["offset_ms"] == 6225
    assert ev.withheld_save["count"] == 7
    assert ev.withheld_save["save_offset_ms"] == 1225


def test_a_clean_lock_still_saves():
    ev = _evaluator()
    for i in range(5):
        ev.process_window(
            40_000 + i * 6000, 45_000 + i * 6000, difficulty=0.9,
            new_result=(1225, 0.90), old_r=0.89, stored_offset_ms=1225,
            stored_quality=0.6, engine_current_offset_ms=1225,
            engine_play_best_quality=0.6)
    assert ev.finalize().disk_save[0] == 1225


def test_finds_that_merely_beat_a_stale_loaded_offset_never_count_against_the_save():
    """Early windows beating the stale LOADED offset on the way to this very
    lock are not evidence against saving the lock."""
    ev = _evaluator()
    for i in range(4):     # engine still on the stale loaded +1525
        ev.process_window(
            10_000 + i * 6000, 15_000 + i * 6000, difficulty=0.9,
            new_result=(6225, 0.85), old_r=0.30, stored_offset_ms=1525,
            stored_quality=0.6, engine_current_offset_ms=1525,
            engine_play_best_quality=0.0)
    for i in range(4):     # then locked on +6225
        ev.process_window(
            40_000 + i * 6000, 45_000 + i * 6000, difficulty=0.9,
            new_result=(6225, 0.88), old_r=0.87, stored_offset_ms=6225,
            stored_quality=0.6, engine_current_offset_ms=6225,
            engine_play_best_quality=0.8)
    assert ev.finalize().disk_save[0] == 6225
    assert ev.withheld_save is None


# ── 10. The executable spec runs green ───────────────────────────────────────

def test_the_executable_spec_passes():
    import subprocess
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, str(repo / "scripts" / "check_whole_song_check.py")],
                         cwd=repo, capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-2000:]
    assert "ALL CHECKS PASSED" in out.stdout


# ── 11. A seek or a pause is not a new offset ────────────────────────────────

def test_timeline_watch_breaks_on_a_seek_a_pause_and_a_song_change():
    tw = wsc.TimelineWatch()
    for ms in range(0, 30_000, 1000):
        tw.note(ms, ms + 400.0, same_song_playing=True)       # steady 400 ms drift
    assert tw.break_ms is None
    tw.note(31_000, 31_000 + 400.0 + 10_000, same_song_playing=True)   # 10 s scrub
    assert tw.break_ms == 31_000 and tw.reason.startswith("seek")
    paused = wsc.TimelineWatch()
    paused.note(5_000, 5_400.0, same_song_playing=True)
    paused.note(6_000, None, same_song_playing=False)
    assert paused.break_ms == 6_000
    frames = [(t, 0.0, 0.0, 0.0, 0.0) for t in range(0, 40_000, 500)]
    assert max(f[0] for f in tw.trim(frames)) < 30_000


def test_a_scrubbed_play_would_vote_for_the_scrub_without_the_watch():
    """RED CONTROL for the guard: scrub 3 s forward 30 s into El Efecto and
    the frames after the scrub vote for truth + 3 s. Trimmed at the break,
    the first 30 s are too short to judge — nothing is changed."""
    ts, sq, raw = W.load_fixture("el_efecto")
    pre = [f for f in W.live_frames(ts, raw, 11750) if f[0] < 30_000]
    post = [(t - 3_000, *rest) for t, *rest in W.live_frames(ts, raw, 11750, seed=3)
            if t >= 33_000]
    scrubbed = pre + post
    bad = wsc.decide(wsc.whole_song_vote(ts, sq, scrubbed, saved_offset_ms=11750), CFG)
    assert bad.action == wsc.CORRECTED and bad.offset_ms == 11750 + 3_000
    tw = wsc.TimelineWatch()
    for f in scrubbed[::86]:
        progress = f[0] + 400.0 + (3_000 if f[0] >= 30_000 else 0)
        tw.note(f[0], progress, same_song_playing=True)
    kept = tw.trim(scrubbed)
    assert kept[-1][0] < 30_000
    assert wsc.decide(wsc.whole_song_vote(ts, sq, kept, saved_offset_ms=11750),
                      CFG).action == wsc.TOO_FEW_WINDOWS
