"""THE ENERGY PARITY LIST (scripts/energy_parity.py, the Energy plan's D5):
each gate's new value passes the same share of moments on the new scale as
its old value did on the old one; the likelihood curves move point by point
the same way; the wheel-travel curve and any profile it or a flare entry
shares are left alone. Pure functions on made-up libraries — the script's
own run is a dry run against a copy of his storage."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "energy_parity.py"
_spec = importlib.util.spec_from_file_location("energy_parity", _PATH)
ep = importlib.util.module_from_spec(_spec)
sys.modules["energy_parity"] = ep          # a dataclass needs its module registered
_spec.loader.exec_module(ep)


def test_the_new_value_passes_the_same_share():
    old = [0.5, 0.6, 0.7, 0.8, 0.9]           # today 0.7 passes 3 of 5
    new = [0.1, 0.2, 0.3, 0.4, 0.5]           # the same moments on the new scale
    share = ep.share_at_or_above(old, [1] * 5, 0.7)
    assert share == pytest.approx(0.6)
    assert ep.matching_threshold(new, [1] * 5, share) == pytest.approx(0.3)
    assert ep.matching_threshold(new, [1] * 5, 0.0) == 1.0
    assert ep.matching_threshold(new, [1] * 5, 1.0) == 0.0


def test_song_time_is_weighted_by_duration():
    # one long quiet section and one short loud one
    vals, weights = [0.2, 0.9], [9.0, 1.0]
    assert ep.share_at_or_above(vals, weights, 0.5) == pytest.approx(0.1)


def test_parity_reports_every_gate_on_its_own_moments():
    old = {"drops": ([0.8, 0.9, 0.5], [1, 1, 1]), "time": ([0.5, 0.95], [1, 1]),
           "stretched": ([0.2, 1.0], [1, 1]), "edges": ([0.3, 0.7, 0.9], [1, 1, 1])}
    new = {"drops": ([0.4, 0.5, 0.1], [1, 1, 1]), "time": ([0.2, 0.6], [1, 1]),
           "edges": ([0.1, 0.35, 0.5], [1, 1, 1])}
    today = {"drop_shock_min_energy": 0.7, "drop_floor": 0.1,
             "pulse_flash_min_energy": 0.8, "rainbow_select_limit": 0.9,
             "drop_switch_hit_threshold": 0.6}
    gates = {g.key: g for g in ep.parity(old, new, today)}
    assert gates["drop_shock_min_energy"].new == pytest.approx(0.4)
    assert gates["drop_floor"].new == 0.0 and gates["drop_floor"].share == 1.0
    assert gates["rainbow_select_limit"].new == pytest.approx(0.6)
    assert gates["drop_switch_hit_threshold"].new == pytest.approx(0.35), \
        "the meld's big hit: two of three boundaries pass on either scale"


def test_the_old_stretch_is_the_planners_own():
    secs = [{"start_ms": 0, "end_ms": 15_000, "energy_rms": 0.1},
            {"start_ms": 15_000, "end_ms": 30_000, "energy_rms": 0.4},
            {"start_ms": 30_000, "end_ms": 45_000, "energy_rms": 0.8},
            {"start_ms": 45_000, "end_ms": 60_000, "energy_rms": 0.6}]
    out = ep.old_stretch(secs)
    assert out[0] == 0.0, "a quiet intro clamps (no floor at the edges)"
    assert out[1] == pytest.approx(0.05) and out[2] == pytest.approx(1.0)
    assert ep.old_stretch([{"start_ms": 0, "end_ms": 60_000, "energy_rms": 0.3},
                           {"start_ms": 60_000, "end_ms": 90_000, "energy_rms": 0.3}]) == [0.5, 0.5]


def test_curves_move_point_by_point_and_the_wheel_curve_is_left_alone():
    mapping = [(0.0, 0.0), (0.5, 0.25), (1.0, 0.6)]
    assert ep.remap_x(0.75, mapping) == pytest.approx(0.425)
    config = {
        "entries": {"scene-a": {"curve_ref": "lift", "inline_points": None},
                    "scene-b": {"curve_ref": None,
                                "inline_points": [{"x": 0.0, "y": 1}, {"x": 1.0, "y": 3}]}},
        "color_set_entries": {"set-a": {"curve_ref": "wheel", "inline_points": None}},
        "flare_entries": {"flare-a": {"curve_ref": "shared", "inline_points": None}},
        "wheel_travel_curve": "wheel",
    }
    curves = {"lift": {"id": "lift", "points": [{"x": 0.5, "y": 1}, {"x": 1.0, "y": 2}]},
              "wheel": {"id": "wheel", "points": [{"x": 0.5, "y": 1}]},
              "shared": {"id": "shared", "points": [{"x": 0.5, "y": 1}]}}
    new_config, new_curves, notes = ep.remap_sequencer(config, curves, mapping)
    assert [p["x"] for p in new_curves["lift"]["points"]] == pytest.approx([0.25, 0.6])
    assert new_curves["wheel"] == curves["wheel"], "the wheel-travel curve's x is degrees"
    assert new_curves["shared"] == curves["shared"]
    assert [p["x"] for p in new_config["entries"]["scene-b"]["inline_points"]] == pytest.approx([0.0, 0.6])
    assert config["entries"]["scene-b"]["inline_points"][1]["x"] == 1.0, "the input is not changed"
    assert any("wheel" in n for n in notes)


def test_the_curve_mapping_is_monotone_from_zero():
    old = ([0.1, 0.4, 0.7, 1.0], [1, 1, 1, 1])
    new = ([0.05, 0.2, 0.35, 0.5], [1, 1, 1, 1])
    m = ep.curve_mapping(old, new)
    assert m[0] == (0.0, 0.0)
    ys = [y for _, y in m]
    assert ys == sorted(ys) and ys[-1] <= 0.5


def test_apply_needs_an_explicit_target():
    with pytest.raises(SystemExit):
        ep.main(["--storage-root", "/nonexistent", "--apply"])


class FakeSpectra:
    """The three routes the script reaches, in memory, logging every call."""

    def __init__(self):
        self.room = {"drop_shock_min_energy": 0.7, "drop_floor": 0.1,
                     "pulse_flash_min_energy": 0.8, "rainbow_select_limit": 0.9,
                     "drop_switch_hit_threshold": 0.6, "av_sync_lead_ms": 57}
        self.config = {"entries": {"s": {"curve_ref": "lift", "inline_points": None}},
                       "color_set_entries": {}, "flare_entries": {}, "wheel_travel_curve": None}
        self.curves = {"lift": {"id": "lift", "points": [{"x": 0.5, "y": 1}, {"x": 1.0, "y": 2}]}}
        self.log = []

    def __call__(self, url, method="GET", body=None):
        import copy
        route = url.split("/api/", 1)[1]
        self.log.append((method, route))
        if method == "GET":
            return copy.deepcopy({"room-controls": self.room, "sequencer/config": self.config,
                                  "sequencer/curves": self.curves}[route])
        if route == "room-controls":
            self.room.update(body)               # a partial update, like the real route
        elif route == "sequencer/curves":
            self.curves = copy.deepcopy(body)
        else:
            self.config = copy.deepcopy(body)
        return {"status": "saved"}


def test_apply_backs_up_first_and_restore_puts_back_exactly(tmp_path, monkeypatch):
    fake = FakeSpectra()
    monkeypatch.setattr(ep, "_call", fake)
    storage = tmp_path / "root" / "storage" / "spectra"
    storage.mkdir(parents=True)
    (storage / "room_controls.json").write_text('{"drop_floor": 0.1}')
    (storage / "sequencer.json").write_text('{"curves": {}}')
    before = (dict(fake.room), dict(fake.config), dict(fake.curves))
    gates = [ep.Gate("drop_shock_min_energy", "drops", 0.7, 0.69, 0.32, 10),
             ep.Gate("drop_floor", "drops", 0.1, 1.0, 0.0, 10),
             ep.Gate("pulse_flash_min_energy", "time", 0.8, 0.53, 0.32, 10),
             ep.Gate("rainbow_select_limit", "time", 0.9, 0.33, 0.44, 10),
             ep.Gate("drop_switch_hit_threshold", "edges", 0.6, 0.4, 0.3, 10)]
    mapping = [(0.0, 0.0), (0.5, 0.28), (1.0, 0.58)]
    target = tmp_path / "backup"
    saved = ep.backup("http://spectra", tmp_path / "root", target)
    first_write = len(fake.log)
    assert all(m == "GET" for m, _ in fake.log[:first_write]), "nothing written before the backup"
    assert sorted(saved["files"]) == ["room_controls.json", "sequencer.json"]
    assert (target / "room_controls.json").read_text() == '{"drop_floor": 0.1}'
    ep.apply("http://spectra", gates, mapping)
    assert fake.room["drop_shock_min_energy"] == 0.32 and fake.room["rainbow_select_limit"] == 0.44
    assert fake.room["drop_switch_hit_threshold"] == 0.3
    assert fake.room["av_sync_lead_ms"] == 57, "only the five gates move"
    assert [p["x"] for p in fake.curves["lift"]["points"]] == pytest.approx([0.28, 0.58])
    ep.restore("http://spectra", target)
    assert (fake.room, fake.config, fake.curves) == before


def test_restore_needs_an_explicit_target():
    with pytest.raises(SystemExit):
        ep.main(["--restore", "/nonexistent"])
