"""
SpotFX — Gradient / color interpolation helpers.

Provides interpolate_gradient(start, end, t) which smoothly blends between
two CSS gradient strings or hex color strings.

Supported formats:
  - Solid hex: #RRGGBB
  - Linear gradient: linear-gradient(Xdeg, #color P%, ...)

Unsupported formats (radial, conic, rgb(), named colors) fall back to an
instant switch at t >= 0.5.
"""
from __future__ import annotations
import re

# Match a bare #RRGGBB hex color
_HEX_FULL_RE = re.compile(r'^#([0-9a-fA-F]{6})$')

# Match a color stop inside a gradient: color followed by a position
# Accepts #RRGGBB or rgb(...) color values
_STOP_RE = re.compile(
    r'(#[0-9a-fA-F]{6}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))\s+([\d.]+%?)',
    re.IGNORECASE,
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    return int(h[1:3], 16) / 255.0, int(h[3:5], 16) / 255.0, int(h[5:7], 16) / 255.0


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return f"#{max(0, min(255, int(round(r * 255)))):02x}" \
           f"{max(0, min(255, int(round(g * 255)))):02x}" \
           f"{max(0, min(255, int(round(b * 255)))):02x}"


def _lerp_color(a: str, b: str, t: float) -> str:
    """Linear interpolate between two #RRGGBB hex strings. t=0 → a, t=1 → b."""
    ar, ag, ab_ = _hex_to_rgb(a)
    br, bg, bb  = _hex_to_rgb(b)
    return _rgb_to_hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab_ + (bb - ab_) * t)


_ACHROMATIC = 0.05  # below this saturation/value a colour has no usable hue


def _lerp_color_hue(a: str, b: str, t: float) -> str:
    """Interpolate two #RRGGBB hex strings by rotating around the hue wheel
    (HSV, shortest arc) instead of the straight RGB line — red→cyan sweeps
    through neighbouring hues rather than desaturating through grey. When one
    end is achromatic (grey/black/white, hue undefined) it adopts the other
    end's hue so the blend fades saturation in place."""
    import colorsys
    h1, s1, v1 = colorsys.rgb_to_hsv(*_hex_to_rgb(a))
    h2, s2, v2 = colorsys.rgb_to_hsv(*_hex_to_rgb(b))
    if s1 < _ACHROMATIC or v1 < _ACHROMATIC:
        h1 = h2
    if s2 < _ACHROMATIC or v2 < _ACHROMATIC:
        h2 = h1
    dh = ((h2 - h1 + 0.5) % 1.0) - 0.5
    return _rgb_to_hex(*colorsys.hsv_to_rgb(
        (h1 + dh * t) % 1.0, s1 + (s2 - s1) * t, v1 + (v2 - v1) * t
    ))


def _normalize_stop_color(color_str: str) -> str | None:
    """Convert a stop color to #RRGGBB. Returns None if format not supported."""
    color_str = color_str.strip()
    if _HEX_FULL_RE.match(color_str):
        return color_str.upper()
    # rgb(r, g, b) → #RRGGBB
    m = re.match(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', color_str, re.IGNORECASE)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _parse_linear(s: str) -> tuple[str, list[tuple[str, str]]] | None:
    """
    Parse "linear-gradient(angle, color pos, ...)" into (angle, [(hex_color, pos), ...]).
    Returns None if the string can't be parsed or any stop color can't be normalized.
    """
    m = re.match(r'linear-gradient\(([^,]+),(.+)\)$', s.strip(), re.IGNORECASE)
    if not m:
        return None
    angle = m.group(1).strip()
    stops_raw = _STOP_RE.findall(m.group(2))
    if len(stops_raw) < 2:
        return None
    stops: list[tuple[str, str]] = []
    for color_str, pos in stops_raw:
        norm = _normalize_stop_color(color_str)
        if norm is None:
            return None  # Unsupported color format in stop
        stops.append((norm, pos))
    return angle, stops


def _encode_linear(angle: str, stops: list[tuple[str, str]]) -> str:
    return "linear-gradient(" + angle + ", " + ", ".join(f"{c} {p}" for c, p in stops) + ")"


# ── Public API ────────────────────────────────────────────────────────────────

def _rotate_hex(h: str, degrees: float) -> str:
    """Rotate a #RRGGBB color around the hue wheel by `degrees` (sign = direction).
    Saturation and value are preserved, so grays/white/black pass through."""
    import colorsys
    r, g, b = _hex_to_rgb(h)
    hue, s, v = colorsys.rgb_to_hsv(r, g, b)
    hue = (hue + degrees / 360.0) % 1.0
    return _rgb_to_hex(*colorsys.hsv_to_rgb(hue, s, v))


def rotate_color_string(value: str, degrees: float) -> str | None:
    """Rotate a color value — solid #RRGGBB or linear-gradient string — around
    the hue wheel by `degrees`. Every gradient stop rotates by the same amount,
    so the gradient's internal relationships are preserved. Returns None when
    the format isn't supported (caller should skip the param)."""
    value = (value or "").strip()
    if _HEX_FULL_RE.match(value):
        return _rotate_hex(value, degrees)
    parsed = _parse_linear(value)
    if parsed:
        angle, stops = parsed
        return _encode_linear(angle, [(_rotate_hex(c, degrees), p) for c, p in stops])
    return None


def representative_hue(values: list[str | None]) -> float | None:
    """Best-effort dominant hue (degrees 0..360) for a Color Set, used by
    Palette Sync to line up member picks across Groups. Tries each candidate
    string in order (card swatch first, then entry FG values) and returns the
    hue of the first one that yields a usable answer:

      - solid #RRGGBB / rgb(): its own hue, if saturated enough to have one
      - linear-gradient: circular mean of its saturated stops — skipped when
        the stops disagree too much (e.g. a rainbow has no dominant hue)

    Near-greys/black/white contribute nothing. Returns None when no candidate
    resolves — the caller falls back to non-synced behavior."""
    import colorsys
    import math

    def _hues(hexes: list[str]) -> list[float]:
        out = []
        for h in hexes:
            r, g, b = _hex_to_rgb(h)
            hue, s, v = colorsys.rgb_to_hsv(r, g, b)
            if s >= 0.25 and v >= 0.15:
                out.append(hue * 360.0)
        return out

    def _circular_mean(hues: list[float]) -> tuple[float, float]:
        """(mean_degrees, resultant_length 0..1 — 1 = full agreement)."""
        x = sum(math.cos(math.radians(h)) for h in hues) / len(hues)
        y = sum(math.sin(math.radians(h)) for h in hues) / len(hues)
        return math.degrees(math.atan2(y, x)) % 360.0, math.hypot(x, y)

    for value in values:
        value = (value or "").strip()
        if not value:
            continue
        norm = _normalize_stop_color(value)
        if norm:
            hues = _hues([norm])
            if hues:
                return hues[0]
            continue
        parsed = _parse_linear(value)
        if parsed:
            hues = _hues([c for c, _ in parsed[1]])
            if not hues:
                continue
            mean, agreement = _circular_mean(hues)
            if agreement >= 0.5:
                return mean
    return None


def hue_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues in degrees (0..180)."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def interpolate_gradient(
    start: str, end: str, t: float, hue_blend: bool = False
) -> str:
    """
    Interpolate between two gradient or color strings.

    t=0.0 returns start exactly; t=1.0 returns end exactly.
    Intermediate values produce a blended result.

    hue_blend: rotate colours around the hue wheel (HSV shortest arc) instead
    of the straight RGB line — matches LedFX's transition_blend="hue".

    Fallback: if the format can't be parsed, returns start for t<0.5 and end for t>=0.5.
    """
    if t <= 0.0:
        return start
    if t >= 1.0:
        return end

    lerp = _lerp_color_hue if hue_blend else _lerp_color
    start = start.strip()
    end   = end.strip()

    # Both solid hex colors
    if _HEX_FULL_RE.match(start) and _HEX_FULL_RE.match(end):
        return lerp(start, end, t)

    # Both linear gradients
    a = _parse_linear(start)
    b = _parse_linear(end)
    if a and b:
        a_angle, a_stops = a
        _,       b_stops = b
        n = len(a_stops)
        # Map end stops by index — if end has fewer stops, repeat the last one
        b_colors = [b_stops[min(i, len(b_stops) - 1)][0] for i in range(n)]
        new_stops = [
            (lerp(a_stops[i][0], b_colors[i], t), a_stops[i][1])
            for i in range(n)
        ]
        return _encode_linear(a_angle, new_stops)

    # Unsupported format — instant switch
    return end if t >= 0.5 else start
