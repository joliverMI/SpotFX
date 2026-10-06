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
    res = m.run(room, ["porch-rail", "hue-lights"], trials=4)
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
                t["held_by_ambient"] = t["id"] == "hue-lights"
        return out

    monkeypatch.setattr(room, "get", get)
    problems = m.preflight(room, list(room.fixtures))
    assert len(problems) == 1 and "hue-lights" in problems[0]
    assert m.preflight(m.simulated_room(), list(room.fixtures)) == []
