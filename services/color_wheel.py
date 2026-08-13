"""Color Set wheel position (design answer 2): circular mean of FG gradient-stop
hues weighted by saturation×value; chromatic span > 180° → rainbow, no position.
Backgrounds excluded — census showed they disagree with gradient identity by
67.7° mean (report §4c). Computation only; rotation UX is a later increment.
"""
from __future__ import annotations

import colorsys
import math

from models.color_set import ColorSetCard
from models.scene_v2 import ColorWheelPosition
from services.gradient_interpolation import _HEX_FULL_RE, _hex_to_rgb, _parse_linear

_ACHROMATIC_WEIGHT = 0.05   # below this s×v a stop has no hue vote
RAINBOW_SPAN_DEG = 180.0


def _stop_hexes(value: str | None) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    if _HEX_FULL_RE.match(value):
        return [value]
    parsed = _parse_linear(value)
    if parsed:
        return [c for c, _pos in parsed[1]]
    return []   # unparseable formats vote nothing


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
