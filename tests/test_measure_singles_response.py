"""The Singles camera-measurement instrument (scripts/measure_singles_response.py),
proven offline against a simulated room with KNOWN curves and delays — no
fixture, no camera, no network. The live run drives real lights and waits
for firstmate's go; this is what makes its numbers trustworthy when it
comes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "measure_singles_response", ROOT / "scripts" / "measure_singles_response.py")
m = importlib.util.module_from_spec(_spec)
sys.modules["measure_singles_response"] = m
_spec.loader.exec_module(m)


def test_every_hold_names_exactly_one_fixture_never_everything():
    acts = m.hold_actions([("porch-rail", "#ffffff"), ("hue-lights", None)])
    assert [a["params"]["target"] for a in acts] == [
        {"kind": "fixture", "id": "porch-rail"},
        {"kind": "fixture", "id": "hue-lights"}]
    assert acts[0]["params"]["state"] == "steady" and acts[0]["params"]["color"] == "#ffffff"
    assert acts[1]["params"]["state"] == "dark" and "color" not in acts[1]["params"]


def test_a_step_that_reached_more_than_its_fixture_stops_the_run():
    steps = [("porch-rail", "#ffffff")]
    m.check_run({"steps": [{"status": "applied", "devices": ["porch-rail"]}]}, steps)
    with pytest.raises(RuntimeError):
        m.check_run({"steps": [{"status": "applied",
                                "devices": ["porch-rail", "dining-table"]}]}, steps)
    with pytest.raises(RuntimeError):
        m.check_run({"steps": [{"status": "refused", "devices": []}]}, steps)


def test_the_simulated_room_gives_back_what_was_put_in():
    room = m.simulated_room()
    res = m.run(room, list(room.fixtures), trials=24)
    for d, f in room.fixtures.items():
        got = res["fixtures"][d]
        assert got["visible"]
        assert got["fit"]["gamma"] == pytest.approx(f.gamma, abs=0.1), d
        assert got["hysteresis"] < 0.02
    for p in res["pairs"]:
        a, b = room.fixtures[p["wled"]], room.fixtures[p["hue"]]
        # the half-way crossing: delay plus the smoothing's own ln2 x tau
        want = 1000 * ((b.delay_s + 0.693 * b.tau_s) - (a.delay_s + 0.693 * a.tau_s))
        assert p["hue_minus_wled_ms"] == pytest.approx(want, abs=60.0)
        assert p["hue_minus_wled_ms"] > 50.0      # Hue clearly later than WLED


def test_a_fixture_the_camera_cannot_see_is_named_not_guessed():
    room = m.simulated_room()
    room.fixtures["porch-rail"].gain = 0.0001
    res = m.run(room, ["porch-rail", "living-hues"], trials=4)
    assert res["fixtures"]["porch-rail"] == {"visible": False}
    assert res["pairs"] == []


def test_every_fixture_is_let_go_even_when_the_run_fails(monkeypatch):
    room = m.simulated_room()
    released = []
    monkeypatch.setattr(room, "release", released.append)

    def boom(*_a, **_k):
        raise RuntimeError("camera went away")

    monkeypatch.setattr(m, "_fresh_frames", boom)
    with pytest.raises(RuntimeError):
        m.run(room, list(room.fixtures))
    assert sorted(released) == sorted(room.fixtures)


def test_preflight_refuses_a_hue_area_held_by_hue_hold(monkeypatch):
    room = m.simulated_room()
    real = room.get

    def get(path):
        out = real(path)
        if path == "/api/light-show/targets":
            for t in out["fixtures"]:
                t["held_by_ambient"] = t["id"] == "living-hues"
        return out

    monkeypatch.setattr(room, "get", get)
    problems = m.preflight(room, list(room.fixtures))
    assert len(problems) == 1 and "living-hues" in problems[0]
    assert m.preflight(m.simulated_room(), list(room.fixtures)) == []


def test_preflight_refuses_a_fixture_someone_else_already_holds(monkeypatch):
    """The run lets every target go at the end; that must never drop a hold
    it did not put there."""
    room = m.simulated_room()
    real = room.get

    def get(path):
        out = real(path)
        if path == "/api/light-show/status":
            out["output"]["holds"] = [{"device": "dining-table", "state": "steady"}]
        return out

    monkeypatch.setattr(room, "get", get)
    problems = m.preflight(room, list(room.fixtures))
    assert len(problems) == 1 and "dining-table" in problems[0]


def test_fixtures_that_light_the_same_table_are_timed_where_each_dominates():
    """The dining table WLED and the dining bulbs light the same table: a
    shared region would read both in each crossing. Each is timed only where
    it dominates, and the delay still comes back."""
    room = m.simulated_room()
    room.fixtures = {"dining-table": room.fixtures["dining-table"],
                     "dining-hues": room.fixtures["dining-hues"]}
    room.fixtures["dining-hues"].region = (2, 12, 24, 40)   # overlaps x 24..28
    room._cmd = {d: [(-1e9, 0.0)] for d in room.fixtures}
    res = m.run(room, list(room.fixtures), trials=24)
    overlap = 6 * 4          # rows 2..8 x columns 24..28 lit by both
    for d in room.fixtures:
        f = res["fixtures"][d]
        assert f["exclusive_pixels"] == f["pixels"] - overlap, (d, f)
    (p,) = res["pairs"]
    a, b = room.fixtures["dining-table"], room.fixtures["dining-hues"]
    want = 1000 * ((b.delay_s + 0.693 * b.tau_s) - (a.delay_s + 0.693 * a.tau_s))
    assert p["hue_minus_wled_ms"] == pytest.approx(want, abs=60.0)


# ── the house Hue lift: only what was named, always put back ──────────────

AWAY = {"id": "away1", "name": "Away", "notes": "",
        "hue": [{"area": "living-hues", "look": "off", "kelvin": None, "color": None,
                 "brightness": 100.0},
                {"area": "dining-hues", "look": "off", "kelvin": None, "color": None,
                 "brightness": 100.0}],
        "fixtures": [{"target": {"kind": "everything", "id": None}, "off": True}],
        "updated_ms": 1}


def _away_room():
    room = m.simulated_room()
    room.mode = m.deepcopy(AWAY)
    return room


def test_the_lift_changes_only_the_named_areas_look():
    body, originals = m.lifted_mode(AWAY, ["dining-hues"])
    assert body["hue"][0] == AWAY["hue"][0]                 # the other area untouched
    assert body["hue"][1]["area"] == "dining-hues" and body["hue"][1]["look"] == "show"
    assert {k: v for k, v in body.items() if k != "hue"} == \
        {k: v for k, v in AWAY.items() if k != "hue"}
    assert originals == {"dining-hues": {"index": 1, "look": AWAY["hue"][1]}}
    assert m.restored_mode(body, originals) == AWAY
    # nothing held, nothing lifted
    assert m.lifted_mode(body, ["dining-hues"])[1] == {}


def test_the_restore_keeps_an_edit_someone_else_made_meanwhile():
    body, originals = m.lifted_mode(AWAY, ["dining-hues"])
    body["notes"] = "edited mid-run"
    body["hue"][0]["look"] = "hold"
    body["hue"][0]["kelvin"] = 2700
    back = m.restored_mode(body, originals)
    assert back["notes"] == "edited mid-run" and back["hue"][0]["kelvin"] == 2700
    assert back["hue"][1] == AWAY["hue"][1]


def test_a_lifted_run_measures_the_area_then_releases_then_restores(tmp_path):
    room = _away_room()
    events = []
    real_release, real_post = room.release, room.post
    room.release = lambda d: (events.append(("release", d)), real_release(d))[1]
    room.post = lambda p, b: (events.append(("post", b["hue"][1]["look"])), real_post(p, b))[1]
    rec = tmp_path / "lift.json"
    res = m.run(room, ["dining-table", "dining-hues"], lift=["dining-hues"],
                record_path=str(rec), trials=4)
    assert res["fixtures"]["dining-hues"]["visible"]          # the stream reached it
    assert res["restore"] == {"restored": True, "areas": ["dining-hues"],
                              "detail": "read back as before"}
    assert events[0] == ("post", "show")
    assert events[-1] == ("post", "off")
    assert {e for e in events[-3:-1]} == {("release", "dining-table"),
                                          ("release", "dining-hues")}
    assert {k: v for k, v in room.mode.items() if k != "updated_ms"} == \
        {k: v for k, v in AWAY.items() if k != "updated_ms"}
    assert not rec.exists()                                   # put back: record cleared


def test_the_record_is_on_disk_before_the_lift_lands(tmp_path):
    room = _away_room()
    rec = tmp_path / "lift.json"
    seen = []
    real_post = room.post
    room.post = lambda p, b: (seen.append(rec.exists()), real_post(p, b))[1]
    m.run(room, ["dining-hues"], lift=["dining-hues"], record_path=str(rec), trials=2)
    assert seen[0] is True


def test_the_look_is_put_back_even_when_the_run_fails(monkeypatch):
    room = _away_room()

    def boom(*_a, **_k):
        raise RuntimeError("camera went away")

    monkeypatch.setattr(m, "_fresh_frames", boom)
    with pytest.raises(RuntimeError):
        m.run(room, ["dining-hues"], lift=["dining-hues"])
    assert room.mode["hue"] == AWAY["hue"]


def test_a_house_mode_change_mid_run_stops_it_and_still_puts_back(monkeypatch):
    room = _away_room()
    real = m._fresh_frames
    calls = []

    def flip(r, n, settle):
        calls.append(1)
        if len(calls) == 3:                 # HA re-lands a held look mid-run
            r.mode["hue"][1]["look"] = "off"
        return real(r, n, settle)

    monkeypatch.setattr(m, "_fresh_frames", flip)
    with pytest.raises(RuntimeError, match="held again"):
        m.run(room, ["dining-table", "dining-hues"], lift=["dining-hues"], trials=2)
    assert room.mode["hue"] == AWAY["hue"]


def test_a_killed_run_can_be_put_back_from_its_record(tmp_path):
    room = _away_room()
    rec = tmp_path / "lift.json"
    m.lift_house_hue(room, ["dining-hues"], str(rec))        # ...and then the run dies
    assert room.mode["hue"][1]["look"] == "show"
    import json
    out = m.restore_house_hue(room, json.loads(rec.read_text()))
    assert out["restored"] and room.mode["hue"] == AWAY["hue"]


def test_an_area_streamed_with_bulbs_the_house_leaves_alone_is_refused():
    problems = m.preflight(m.simulated_room(), ["dining-table", "hue-lights"], ["hue-lights"])
    assert any("hue-lights" in p and "Ledge" in p for p in problems)


def test_apply_only_in_the_daytime_window():
    import time as _t
    at = lambda h, mi: _t.struct_time((2026, 10, 6, h, mi, 0, 1, 279, 1))
    assert not m.in_window(at(8, 29)) and m.in_window(at(8, 30))
    assert m.in_window(at(22, 29)) and not m.in_window(at(22, 30))


def test_the_delay_uses_the_cameras_real_frame_rate_not_its_nominal_one():
    """The kiosk stream runs ~4.2 fps against a nominal 5; timing frames at
    the nominal period would shrink every measured delay by a sixth."""
    room = m.simulated_room()
    room.fps = 4.2
    room.frame_period_s = 0.2          # what the room CLAIMS
    res = m.run(room, ["dining-table", "dining-hues"], trials=24)
    assert res["frame_period_s"] == pytest.approx(1 / 4.2, abs=0.01)
    a, b = room.fixtures["dining-table"], room.fixtures["dining-hues"]
    want = 1000 * ((b.delay_s + 0.693 * b.tau_s) - (a.delay_s + 0.693 * a.tau_s))
    assert res["pairs"][0]["hue_minus_wled_ms"] == pytest.approx(want, abs=60.0)
