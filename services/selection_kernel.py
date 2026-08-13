"""SPECTRA selection kernel — pure functions, no I/O, no engine state.

Only the decision-neutral pieces live here today (report Part 4, "buildable
immediately"): curve evaluation and the wheel-travel geometry that carries the
binding rainbow exemption. Nothing here is wired to the trigger engine.

DECLARED CONTRACTS, NOT YET IMPLEMENTED (awaiting the owner's answers):
  compose(entry, intensity, genre, prev_scene) -> float
      TODO(decision selection-algorithm / weighting-structure): the
      recommended shape is curve(intensity) × genre_mult × affinity_mult with
      zero as a hard veto, but the composition function is a shipped-semantics
      commitment and stays unwritten until decided.
  sample(scores) -> candidate  and the fallback ladder
      TODO(decision selection-algorithm): weighted proportional draw + the
      deterministic all-zero ladder (drop affinity → drop genre → re-admit
      current → uniform; scenes end at "stay", flares at "fire nothing").
  Colour-set / flare selector instances
      TODO(decision colorset-flare-mechanism): whether they ride this kernel
      and how palette-sync translates into a wheel-travel factor.

Executable spec: scripts/check_sequencer.py
"""
from __future__ import annotations

from models.sequencer import CurvePoint

WHEEL_HALF_TURN_DEG = 180.0


def curve_eval(points: list[CurvePoint], x: float) -> float:
    """Piecewise-linear curve height at x.

    - Clamped flat outside the outer points (a 1-point curve is a constant —
      one flat point ≡ scalar weight).
    - Points share sorted x; equal x is a step discontinuity, and at exactly
      that x the LATER point wins. This makes the legacy energy_floor gate an
      exact 3-point curve: [(0,0), (f,0), (f,w)] is 0 below f, w from f up.
    """
    if not points:
        raise ValueError("curve_eval needs at least one point")
    if x < points[0].x:
        return points[0].y
    for i in range(len(points) - 1, -1, -1):
        if points[i].x <= x:
            if points[i].x == x or i == len(points) - 1:
                return points[i].y
            nxt = points[i + 1]
            t = (x - points[i].x) / (nxt.x - points[i].x)
            return points[i].y + t * (nxt.y - points[i].y)
    return points[0].y


def wheel_travel_deg(from_deg: float | None, to_deg: float | None) -> float | None:
    """Shortest arc between two wheel positions, 0–180°.

    None when either side has no position — a rainbow set (chromatic span >
    180°, services/color_wheel.py) or an achromatic set. That None IS the
    binding rainbow exemption: such sets are everywhere and nowhere on the
    wheel and sit outside every rotation-flavored mechanic.
    """
    if from_deg is None or to_deg is None:
        return None
    d = abs(from_deg - to_deg) % 360.0
    return min(d, 360.0 - d)


def wheel_travel_mult(points: list[CurvePoint], from_deg: float | None,
                      to_deg: float | None) -> float:
    """Wheel-travel likelihood factor; rainbow/achromatic sets are neutral ×1.0.

    The travel axis maps 0–180° onto the curve's 0–1 x-axis. Whether colour
    sets use this factor at all is open (TODO(decision
    colorset-flare-mechanism)); the exemption below is binding regardless and
    must hold wherever sets appear.
    """
    travel = wheel_travel_deg(from_deg, to_deg)
    if travel is None:
        return 1.0
    return curve_eval(points, travel / WHEEL_HALF_TURN_DEG)
