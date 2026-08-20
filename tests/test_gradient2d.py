"""The two-dimensional drift gradient's pure model/sampling logic
(spectra/models/gradient2d.py) — owner ask 2026-08-20. No live access; pure
functions only, no storage isolation needed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.gradient2d import (GradientProfile, advance_x,
                                       parse_stops, sample, sample_edge)


# ── parse_stops / sample_edge ───────────────────────────────────────────────

def test_solid_hex_is_a_single_stop_at_zero():
    assert parse_stops("#ff0000") == [(0.0, "#ff0000")]


def test_empty_and_none_parse_to_no_stops():
    assert parse_stops("") == []
    assert parse_stops(None) == []


def test_unparseable_value_parses_to_no_stops():
    assert parse_stops("not a colour") == []


def test_gradient_stops_sorted_and_normalized():
    stops = parse_stops("linear-gradient(90deg, #0000ff 0%, #ff0000 100%)")
    assert stops == [(0.0, "#0000ff"), (1.0, "#ff0000")]


def test_sample_edge_solid_fills_whole_edge():
    assert sample_edge("#123456", 0.0) == "#123456"
    assert sample_edge("#123456", 0.5) == "#123456"
    assert sample_edge("#123456", 1.0) == "#123456"


def test_sample_edge_clamps_outside_stop_range():
    value = "linear-gradient(90deg, #0000ff 20%, #ff0000 80%)"
    assert sample_edge(value, 0.0) == "#0000ff"
    assert sample_edge(value, 1.0) == "#ff0000"


def test_sample_edge_linear_between_stops():
    value = "linear-gradient(90deg, #000000 0%, #ffffff 100%)"
    mid = sample_edge(value, 0.5)
    r = int(mid[1:3], 16)
    assert 120 <= r <= 135   # ~0x80, allow rounding slack


def test_sample_edge_none_when_unauthored():
    assert sample_edge("", 0.5) is None
    assert sample_edge(None, 0.5) is None


# ── sample (2D) ──────────────────────────────────────────────────────────────

def test_sample_y1_is_top_y0_is_bottom():
    assert sample("#ffff00", "#0000ff", 0.5, 1.0) == "#ffff00"
    assert sample("#ffff00", "#0000ff", 0.5, 0.0) == "#0000ff"


def test_sample_linear_between_edges():
    mid = sample("#ffffff", "#000000", 0.5, 0.5)
    r = int(mid[1:3], 16)
    assert 120 <= r <= 135


def test_sample_falls_back_to_whichever_edge_is_authored():
    assert sample("#ff0000", "", 0.5, 0.0) == "#ff0000"
    assert sample("", "#0000ff", 0.5, 1.0) == "#0000ff"
    assert sample("", "", 0.5, 0.5) is None


def test_sample_respects_x_within_each_edge_independently():
    top = "linear-gradient(90deg, #ff0000 0%, #ffff00 100%)"
    bottom = "linear-gradient(90deg, #0000ff 0%, #00ffff 100%)"
    assert sample(top, bottom, 0.0, 1.0) == "#ff0000"
    assert sample(top, bottom, 1.0, 1.0) == "#ffff00"
    assert sample(top, bottom, 0.0, 0.0) == "#0000ff"
    assert sample(top, bottom, 1.0, 0.0) == "#00ffff"


# ── advance_x (loop / bounce) ────────────────────────────────────────────────

def test_advance_x_loop_wraps():
    x, d = advance_x(0.9, 1, 0.2, "loop")
    assert abs(x - 0.1) < 1e-9
    assert d == 1


def test_advance_x_loop_ignores_direction_input_and_output():
    x, d = advance_x(0.5, -1, 0.1, "loop")
    assert abs(x - 0.6) < 1e-9
    assert d == 1


def test_advance_x_bounce_reflects_at_upper_bound():
    x, d = advance_x(0.9, 1, 0.3, "bounce")
    assert abs(x - 0.8) < 1e-9   # 0.9 + 0.3 = 1.2 -> reflect -> 0.8
    assert d == -1


def test_advance_x_bounce_reflects_at_lower_bound():
    x, d = advance_x(0.1, -1, 0.3, "bounce")
    assert abs(x - 0.2) < 1e-9   # 0.1 - 0.3 = -0.2 -> reflect -> 0.2
    assert d == 1


def test_advance_x_bounce_stays_in_bounds_over_many_steps():
    x, d = 0.0, 1
    for _ in range(200):
        x, d = advance_x(x, d, 0.37, "bounce")
        assert -1e-9 <= x <= 1.0 + 1e-9
        assert d in (1, -1)


# ── GradientProfile ──────────────────────────────────────────────────────────

def test_gradient_profile_defaults():
    profile = GradientProfile(name="Test")
    assert profile.x_mode == "loop"
    assert profile.id
    assert profile.top and profile.bottom
