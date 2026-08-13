"""Colour Set wheel position (design answer 2) — SPECTRA port of
spot-effects services/color_wheel.py, same math: circular mean of FG
gradient-stop hues weighted by saturation×value; chromatic span > 180° →
rainbow, no position. The gradient parsing helpers are inlined from
services/gradient_interpolation (the only pieces this needs).
"""
from __future__ import annotations

import colorsys
import math
import re

from spectra.models.scene import ColorWheelPosition
from spectra.services.color_sets import ColorSetCard

_HEX_FULL_RE = re.compile(r'^#([0-9a-fA-F]{6})$')
_STOP_RE = re.compile(
    r'(#[0-9a-fA-F]{6}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))\s+([\d.]+%?)',
    re.IGNORECASE)

_ACHROMATIC_WEIGHT = 0.05   # below this s×v a stop has no hue vote
RAINBOW_SPAN_DEG = 180.0


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    return int(h[1:3], 16) / 255.0, int(h[3:5], 16) / 255.0, int(h[5:7], 16) / 255.0


def _stop_hexes(value: str | None) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    if _HEX_FULL_RE.match(value):
        return [value]
    m = re.match(r'linear-gradient\(([^,]+),(.+)\)$', value, re.IGNORECASE)
    if not m:
        return []
    out: list[str] = []
    for color_str, _pos in _STOP_RE.findall(m.group(2)):
        if _HEX_FULL_RE.match(color_str):
            out.append(color_str)
        else:
            rgb = re.match(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
                           color_str, re.IGNORECASE)
            if rgb:
                out.append(f"#{int(rgb.group(1)):02x}{int(rgb.group(2)):02x}"
                           f"{int(rgb.group(3)):02x}")
    return out


def _weighted_hues(card: ColorSetCard) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for entry in card.entries:
        for hex_color in _stop_hexes(entry.color_value):
            h, s, v = colorsys.rgb_to_hsv(*_hex_to_rgb(hex_color))
            weight = s * v
            if weight >= _ACHROMATIC_WEIGHT:
                out.append((h * 360.0, weight))
    return out


def _chromatic_span_deg(hues: list[float]) -> float:
    # Smallest arc containing every hue = 360 − largest wrap-around gap.
    if len(hues) < 2:
        return 0.0
    ordered = sorted(h % 360.0 for h in hues)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    gaps.append(360.0 - ordered[-1] + ordered[0])
    return 360.0 - max(gaps)


def wheel_position(card: ColorSetCard) -> ColorWheelPosition:
    stops = _weighted_hues(card) if card.kind == "set" else []
    if not stops:
        return ColorWheelPosition(set_id=card.id)

    span = _chromatic_span_deg([h for h, _w in stops])
    total_w = sum(w for _h, w in stops)
    x = sum(w * math.cos(math.radians(h)) for h, w in stops) / total_w
    y = sum(w * math.sin(math.radians(h)) for h, w in stops) / total_w
    resultant = math.hypot(x, y)

    if span > RAINBOW_SPAN_DEG:
        return ColorWheelPosition(
            set_id=card.id, position_deg=None, rainbow=True,
            span_deg=round(span, 1), resultant=round(resultant, 3))

    position = math.degrees(math.atan2(y, x)) % 360.0
    return ColorWheelPosition(
        set_id=card.id, position_deg=round(position, 1), rainbow=False,
        span_deg=round(span, 1), resultant=round(resultant, 3))


def wheel_positions(cards: list[ColorSetCard]) -> dict[str, ColorWheelPosition]:
    return {c.id: wheel_position(c) for c in cards if c.kind == "set"}
