"""PRE-DROPS IN THE STORE, THE VIEW AND THE TEST BED (predrop plan step 3;
drop_sequences.py's PRE-DROPS section is the binding statement): the stamp
carries the pre-drop version; a detection moved by the re-anchor keeps the
overrides made against it and asks nothing when it moved to HIS drop; the
view names the pre-drop and its kind; his own drops' pre-drops are worked
out only on the read-through path; and the test bed's Pre-drops lane.
The store is isolated per test by conftest's _isolated_drop_sequences."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from spectra import config

FIXTURES = Path(__file__).parent / "fixtures" / "predrop"
URI = "spotify:track:predropview1"
ECD = "spotify:track:3E8WZzcp6nscGt9YvBX9MW"
PRE = {"ms": 69537, "kind": "spike", "lead_ms": 813, "score": 1.154, "tier": "confident"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(config, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(config, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    _reset()
    yield
    _reset()


def _reset():
    from spectra.services import analysis_reader, drop_detector, drop_sequences
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    drop_detector.reset_memo()
    drop_sequences.reset()


def _store(seqs: list[dict], overrides: dict | None = None, *, uri: str = URI,
           beat: float = 383.117) -> None:
    from spectra.services import drop_sequences as ds

    def fn(entry):
        entry["detected"] = {
            "uri": uri, "detector_version": "2", "confident_score": 1.0,
            "suggested_score": 0.7, "tempo_bpm": 60000 / beat, "beat_ms": beat,
            "captured_from_ms": 0, "captured_to_ms": 200_000, "duration_ms": 200_000,
            "stamp": "test", "excluded": [],
            "sequences": [{"score": 1.057, "tier": "confident", "break_beats": 3.0,
                           "step": 1.0, "rise": 0.9, "path": "step", "loud_before": True,
                           "capped": False, "notes": [], **q} for q in seqs]}
        if overrides is not None:
            entry["overrides"] = overrides
    ds._mutate(uri, fn)


def _moved(**extra) -> dict:
    """Eyes Cut Deeper drop 1 as v2 detects it: moved off the clap."""
    return {"key": "drop:70350", "drop_ms": 70350, "lull_ms": 64440, "charge_ms": 58484,
            "reanchored_from": 69584, "pre_drop": dict(PRE), **extra}


HIS_EDIT = {"drop:69584": {"detected": {"drop_ms": 69584, "lull_ms": 64440,
                                        "charge_ms": 58484, "score": 1.057,
                                        "tier": "confident"},
                           "state": "confirmed", "drop_ms": 70350}}


def _view():
    from spectra.services import drop_sequences as ds
    return ds.view(URI, triggers=[])


def _one(v):
    (s,) = v["sequences"]
    return s


# ── the stamp ───────────────────────────────────────────────────────────────

def test_the_stamp_carries_the_pre_drop_version(monkeypatch):
    from spectra.services import drop_sequences as ds
    from spectra.services import predrop_detector, room_controls
    controls = room_controls.RoomControlState()
    inputs = {"analyzed_at": "x", "tempo_bpm": 120, "n_beats": 10, "shape": [1, 0, 1, 0.0],
              "duration_ms": 1}
    a = ds.stamp_for(URI, controls, inputs=inputs)
    monkeypatch.setattr(predrop_detector, "PREDROP_VERSION", "test-next")
    assert ds.stamp_for(URI, controls, inputs=inputs) != a


# ── a drop the re-anchor moved ──────────────────────────────────────────────

def test_his_edit_keeps_pairing_with_the_moved_drop_and_asks_nothing():
    _store([_moved()], HIS_EDIT)
    s = _one(_view())
    assert (s["key"], s["detected_key"]) == ("drop:69584", "drop:70350")
    assert s["drop_ms"] == 70350 and s["state"] == "edited"
    assert not s["needs_review"] and not s["detection_lost"]
    assert (s["lull_ms"], s["charge_ms"]) == (64440, 58484)


def test_the_pairing_reads_where_the_drop_was_found_not_only_where_it_is():
    # two beats at 300 ms is 600: the moved drop alone (766 ms off) would
    # leave his edit an orphan — where it was found pairs it
    _store([_moved()], HIS_EDIT, beat=300.0)
    s = _one(_view())
    assert s["detected_key"] == "drop:70350" and not s["detection_lost"]
    _store([_moved(reanchored_from=None)], HIS_EDIT, beat=300.0)
    lost = [q for q in _view()["sequences"] if q["key"] == "drop:69584"]
    assert lost and lost[0]["detection_lost"]


def test_a_drop_he_confirmed_in_place_still_asks_when_it_moves():
    edit = {"drop:69584": {**HIS_EDIT["drop:69584"]}}
    edit["drop:69584"].pop("drop_ms")                 # confirmed where it was
    _store([_moved()], edit)
    s = _one(_view())
    assert s["state"] == "confirmed" and s["needs_review"]
    assert any("not 69584 ms" in n for n in s["notes"])


def test_an_edit_on_the_moved_drop_lands_on_his_own_override():
    from spectra.services import drop_sequences as ds
    _store([_moved()], HIS_EDIT, beat=300.0)
    res = ds.apply_edit(URI, "dismiss", key="drop:70350")
    assert set(res.after["overrides"]) == {"drop:69584"}
    assert res.after["overrides"]["drop:69584"]["state"] == "dismissed"


# ── the view names the pre-drop ─────────────────────────────────────────────

def test_the_view_names_the_pre_drop_and_its_kind():
    _store([_moved()], HIS_EDIT)
    s = _one(_view())
    assert (s["pre_drop_ms"], s["pre_drop_auto"], s["pre_drop_kind"], s["pre_drop_tier"],
            s["pre_drop_score"]) == (69537, 69537, "spike", "confident", 1.154)
    # he confirmed this drop before the pre-drop was found, so it is not his
    # yet: it waits for his tick (nothing plays from a pre-drop in step 4)
    assert s["parts"]["pre_drop"] == "waiting"


def test_a_drop_with_none_says_nothing():
    _store([_moved(pre_drop=None)])
    s = _one(_view())
    assert s["pre_drop_ms"] is None and s["pre_drop_kind"] is None
    assert s["pre_drop_auto"] is None


def test_an_automatic_pre_drop_left_behind_by_his_drop_is_left_out():
    edit = {"drop:69584": {**HIS_EDIT["drop:69584"], "drop_ms": 69400}}
    _store([_moved()], edit)
    s = _one(_view())
    assert s["pre_drop_ms"] is None and s["pre_drop_auto"] == 69537
    assert any("pre-drop left out" in n for n in s["notes"])


def test_nothing_plays_from_a_pre_drop_yet():
    from spectra.services import drop_firing
    _store([_moved()], HIS_EDIT)
    (seq,) = drop_firing.firing_sequences(_view())
    assert seq.pre_drop_ms is None
    assert [c for c, _ in seq.members()] == ["charge", "lull", "drop"]


# ── his own drops ───────────────────────────────────────────────────────────

@pytest.fixture()
def ecd_song(tmp_path):
    shutil.copytree(FIXTURES / "ecd", config.AUDIO_SHAPES_DIR)
    _reset()
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(ECD, SpectraTrigger(
        timestamp_ms=70350, action={"kind": "fire_response", "event_class": "drop"}))
    return ECD


def test_his_drops_pre_drop_is_worked_out_on_the_read_through_path_only(ecd_song):
    from spectra.services import drop_sequences as ds
    from spectra.services import room_controls
    room_controls.save_room_controls(room_controls.RoomControlState(drop_floor=0.1))
    assert ds.ensure_detected(ecd_song)["status"] == "detected"
    (g,) = ds.view(ecd_song)["authored"]
    assert "pre_drop" not in g                      # not worked out yet, never "none"
    body = ds.view_with_detection(ecd_song)
    (g,) = body["authored"]
    assert g["pre_drop"]["kind"] == "spike" and abs(g["pre_drop"]["ms"] - 69584) <= 100
    (g,) = ds.view(ecd_song)["authored"]            # memoised for the plain view
    assert g["pre_drop"]["kind"] == "spike"


def test_his_drop_with_no_pre_drop_is_a_known_none(ecd_song):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import drop_sequences as ds
    from spectra.services import trigger_store
    trigger_store.upsert(ecd_song, SpectraTrigger(
        timestamp_ms=120000, action={"kind": "fire_response", "event_class": "drop"}))
    groups = ds.view_with_detection(ecd_song)["authored"]
    late = next(g for g in groups if g["drop"]["timestamp_ms"] == 120000)
    assert "pre_drop" in late and late["pre_drop"] is None


# ── the test bed's Pre-drops lane ───────────────────────────────────────────

def test_the_pre_drops_lane_draws_each_kind_with_its_glyph(ecd_song):
    from spectra.services import testbed_engines as te
    marks = te.marks_for(te.ENGINE_PREDROPS, ecd_song, confident_score=1.0,
                         suggested_score=0.7, floor_score=0.1)
    near = [m for m in marks if abs(m.time_ms - 69537) <= 100]
    assert {m.kind for m in near} == {"pre_drop", "spike"}   # once as each, not twice
    assert len(near) == 2
    assert all(m.glyph == "spike" and m.tier == "confident" for m in near)
    assert "the detected drop at 70350 ms" in near[0].label
    assert {m.glyph for m in marks} <= {"spike", "intro"}
    assert te.ENGINE_PREDROPS in te.SONG_TIME_ENGINES


def test_the_lane_is_listed_and_its_payload_carries_glyph_and_tier(ecd_song):
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    from spectra.services import testbed_engines as te
    assert te.availability_for(ecd_song)[te.ENGINE_PREDROPS]["available"]
    c = TestClient(create_app())       # no lifespan: the routes alone
    r = c.get("/api/testbed/engine-marks", params={
        "uri": ecd_song, "engine": "predrops", "mark_kind": "spike",
        "confident_score": 1.0, "suggested_score": 0.7, "floor_score": 0.1})
    assert r.status_code == 200
    est = r.json()["estimate"]
    assert est and all(m["glyph"] == "spike" and m["tier"] for m in est)
    drops = c.get("/api/testbed/engine-marks", params={
        "uri": ecd_song, "engine": "drops", "mark_kind": "drop",
        "floor_score": 0.1}).json()["estimate"]
    assert drops and all("glyph" not in m and "tier" not in m for m in drops)


REPO = Path(__file__).resolve().parent.parent
_ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not _ESBUILD.exists() or shutil.which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_the_lane_draws_each_kind_as_its_glyph():
    """scripts/check_testbed_predrop_lane.mjs renders the real EngineLane
    over its real imports; this runs it on every full test run."""
    import subprocess
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_testbed_predrop_lane.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout
