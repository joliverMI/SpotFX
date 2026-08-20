"""The two-dimensional drift gradient (owner ask 2026-08-20, `data/
two-dimensional-drift-gradient-and-rainb-imfg/HIS-VERBATIM-WORDS.md`):

  X is time — as time passes, the drift's colour picker moves steadily
  along x (and still jumps on flares, unrelated to this axis — see
  drift_conductor.py's module docstring, "gradient drift" section).
  Y is intensity — as intensity scales, the picker moves along y.
  Vertices only at the top (y=1) and bottom (y=0) edges for now, mapping
  LINEARLY between them. Explicitly NOT a rotation control (his own
  pre-emption).

Storage grammar: each edge is stored as the SAME "#rrggbb solid or
linear-gradient(...)" string every colour value in this app already uses
(entry.color_value, a colour set's gradient param, etc.) — so each edge
reuses the existing ColorGradientPicker widget verbatim ("the UI should be
very similar to the current gradient picker, just make it a square"): the
square's top edge IS a ColorGradientPicker strip, its bottom edge is a
second one, and the interior is the bilinear fill between them. A CSS
gradient stop's position (0-100%) IS one of his "vertices" along that edge.

Parsing/sampling is a local reimplementation, not an import of spot-effects'
services/gradient_interpolation.py — nothing under spectra/ imports
spot-effects runtime internals (AGENTS.md); spectra/services/color_rotate.py
established the same local-reimplementation precedent for the identical
string grammar.
"""
from __future__ import annotations

import re
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

_HEX_RE = re.compile(r'^#([0-9a-fA-F]{6})$')
_GRADIENT_RE = re.compile(r'^linear-gradient\(([^,]+),(.+)\)$', re.IGNORECASE)
_STOP_RE = re.compile(
    r'(#[0-9a-fA-F]{6}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))\s*([\d.]+)%?',
    re.IGNORECASE)
_RGB_RE = re.compile(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
                     re.IGNORECASE)

XMode = Literal["loop", "bounce"]


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    return (int(h[1:3], 16) / 255.0, int(h[3:5], 16) / 255.0,
            int(h[5:7], 16) / 255.0)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    clamp = lambda v: max(0, min(255, round(v * 255)))
    return f"#{clamp(r):02x}{clamp(g):02x}{clamp(b):02x}"


def _normalize_stop_color(color_str: str) -> Optional[str]:
    if _HEX_RE.match(color_str):
        return color_str.lower()
    m = _RGB_RE.match(color_str)
    if m:
        return "#%02x%02x%02x" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _lerp_hex(a: str, b: str, t: float) -> str:
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t)


def parse_stops(value: Optional[str]) -> list[tuple[float, str]]:
    """One edge's stored value -> sorted [(x 0..1, "#rrggbb"), ...]. A bare
    solid hex is a single stop at x=0.0 (fills the whole edge — sample_edge
    clamps outside a stop's range to its nearest neighbour). Unparseable or
    empty -> []."""
    value = (value or "").strip()
    if not value:
        return []
    if _HEX_RE.match(value):
        return [(0.0, value.lower())]
    m = _GRADIENT_RE.match(value)
    if not m:
        return []
    stops: list[tuple[float, str]] = []
    for color_str, pos in _STOP_RE.findall(m.group(2)):
        norm = _normalize_stop_color(color_str)
        if norm is None:
            continue
        stops.append((max(0.0, min(1.0, float(pos) / 100.0)), norm))
    stops.sort(key=lambda s: s[0])
    return stops


def sample_edge(value: Optional[str], x: float) -> Optional[str]:
    """The edge's colour at fraction x (0..1). None when the edge has no
    usable stops (unauthored)."""
    stops = parse_stops(value)
    if not stops:
        return None
    if len(stops) == 1 or x <= stops[0][0]:
        return stops[0][1]
    if x >= stops[-1][0]:
        return stops[-1][1]
    for (xa, ca), (xb, cb) in zip(stops, stops[1:]):
        if xa <= x <= xb:
            span = xb - xa
            t = 0.0 if span <= 0.0 else (x - xa) / span
            return _lerp_hex(ca, cb, t)
    return stops[-1][1]   # unreachable given the bounds checks above


def sample(top: Optional[str], bottom: Optional[str], x: float, y: float
          ) -> Optional[str]:
    """The gradient's colour at (x=time phase 0..1, y=intensity 0..1).
    y=1 is the top edge, y=0 the bottom — linear between them, exactly his
    stated spec ("the gradient maps linearly to these vertices"). None only
    when NEITHER edge has usable stops."""
    top_c = sample_edge(top, x)
    bot_c = sample_edge(bottom, x)
    if top_c is None:
        return bot_c
    if bot_c is None:
        return top_c
    return _lerp_hex(bot_c, top_c, max(0.0, min(1.0, y)))


def advance_x(x: float, direction: int, delta: float, mode: XMode
             ) -> tuple[float, int]:
    """Advance the time-position by delta (>=0), honouring loop (wrap into
    [0,1)) or bounce (reflect at 0/1, flipping direction — "part of the
    setting stored with the gradient is whether to bounce or loop along the
    x-axis"). direction is only meaningful for bounce; loop ignores it and
    always returns 1."""
    if mode == "loop":
        return (x + delta) % 1.0, 1
    pos = x + delta * direction
    while pos > 1.0 or pos < 0.0:
        if pos > 1.0:
            pos = 2.0 - pos
            direction = -1
        else:
            pos = -pos
            direction = 1
    return pos, direction


class GradientProfile(BaseModel):
    """One named, saved 2D drift gradient — stored/picked exactly like a
    sequencer CurveProfile (spectra/services/gradient2d_store.py)."""
    id:     str = Field(default_factory=lambda: str(uuid.uuid4()))
    name:   str
    top:    str = "#ffffff"     # y=1 edge — his example: high intensity -> yellows/oranges
    bottom: str = "#0000ff"     # y=0 edge — his example: low intensity -> blues
    x_mode: XMode = "loop"
