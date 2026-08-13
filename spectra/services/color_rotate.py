"""Hue rotation for colour values — the colour journey's mechanical half.

The conductor's colour creep and the room walk advance the wheel by Δ°, and
the palette must move WITH the wheel: every chromatic stop of the active
colours rotates by the same Δ, saturation and value untouched (background
and accent rotate together — one story, one delta). Achromatic stops are
naturally fixed points (hue rotation of grey is the identity in RGB).

Accepted forms: solid "#rrggbb" and "linear-gradient(<direction>, <stops>)"
with hex or rgb() stops — the exact vocabulary the compiler and colour sets
emit. Anything else returns unchanged: an unknown colour string must never
crash a leg, and not rotating is the visible, debuggable failure.
"""
from __future__ import annotations

import colorsys
import re

_HEX_RE = re.compile(r'^#([0-9a-fA-F]{6})$')
_GRADIENT_RE = re.compile(r'^linear-gradient\(([^,]+),(.+)\)$', re.IGNORECASE)
_STOP_RE = re.compile(
    r'(#[0-9a-fA-F]{6}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))\s*([\d.]+%?)?',
    re.IGNORECASE)
_RGB_RE = re.compile(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
                     re.IGNORECASE)


def rotate_hex(hex_color: str, delta_deg: float) -> str:
    r = int(hex_color[1:3], 16) / 255.0
    g = int(hex_color[3:5], 16) / 255.0
    b = int(hex_color[5:7], 16) / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r2, g2, b2 = colorsys.hsv_to_rgb((h + delta_deg / 360.0) % 1.0, s, v)
    return "#%02x%02x%02x" % (round(r2 * 255), round(g2 * 255), round(b2 * 255))


def _rotate_stop_color(color_str: str, delta_deg: float) -> str:
    if _HEX_RE.match(color_str):
        return rotate_hex(color_str, delta_deg)
    m = _RGB_RE.match(color_str)
    if m:
        as_hex = "#%02x%02x%02x" % (int(m.group(1)), int(m.group(2)),
                                    int(m.group(3)))
        return rotate_hex(as_hex, delta_deg)
    return color_str


def rotate_color_value(value: str | None, delta_deg: float) -> str | None:
    """Rotate a colour value's hues by delta_deg. Solid hex and
    linear-gradient strings rotate; None/empty/unknown pass through."""
    if not value or delta_deg == 0.0:
        return value
    value = value.strip()
    if _HEX_RE.match(value):
        return rotate_hex(value, delta_deg)
    m = _GRADIENT_RE.match(value)
    if not m:
        return value
    direction, stops_str = m.group(1).strip(), m.group(2)
    stops = []
    for color_str, pos in _STOP_RE.findall(stops_str):
        rotated = _rotate_stop_color(color_str, delta_deg)
        stops.append(f"{rotated} {pos}".strip())
    if not stops:
        return value
    return f"linear-gradient({direction}, {', '.join(stops)})"
