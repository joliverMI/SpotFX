"""Correct colour conversions for PREVIEWING a Hue bulb that is currently
HELD at a colour temperature / colour / brightness, never sent to a bulb
(the bridge gets `mirek`/`xy` directly — see ambient.py/house.py).

Found 2026-10-06 (the Admiral: "the hues are showing a yellow green,
despite being set to a white (k) setting... I am looking at the preview,
not the actual lights"): a Hue device stays `frozen` while house lighting
(or plain Ambient) holds it over REST (`fx/devices/hue.py` — "The driving
virtual stays ACTIVE and rendering — only this device's output is muted").
The device-preview pipeline (`preview_stream.py`/`device_preview.py`) taps
the virtual's own rendered pixel buffer (`Event.VIRTUAL_UPDATE`), which
never stops computing while frozen — so the preview was showing whatever
the room's ordinary show happens to paint on that virtual right now,
completely unrelated to the REST colour actually on the bulb. On his
"hues" virtual this is structural, not incidental: it is a single-pixel
COPY-mapped virtual shared by every Hue bulb across both entertainment
areas (`tests/test_preview_layout.py`'s `hue-lights`/`dining-hues`
fixture), so even a correct render of the live show could never show two
different areas at two different held colours — only reading the HELD
LOOK itself (not the render) can.

`spectra/services/preview_layout.py` is the wiring: for a live Hue
fixture, it resolves `house.hue_directive()` (and, when the house layer
is not driving it, `ambient`'s own plain Hold state) into the exact
`(area, kind, mirek, color, brightness)` look tuple ambient.py itself
sends to the bridge, and converts THAT — never the stream — into the hex
this module returns. `None` means "not held — draw the live render as
before" (a `"show"` look, or no look at all).

TWO CONVERSIONS, BOTH CORRECT, BOTH TESTED AGAINST A BLACKBODY RESULT:

- `kelvin_to_rgb` is the Tanner Helland blackbody-radiation FIT, the exact
  algorithm `spectra/web/src/house/houseSummary.ts`'s `kelvinToHex` already
  uses for the mode-editor's own swatch (verified correct there — a plain
  naive bug would read as a no-op change here, so this module's own tests
  assert the SAME numeric result that function would give, not just "looks
  plausible"). Mirek is converted with `1_000_000 / mirek` before calling
  this, matching the bridge's own CLIP v2 `color_temperature.mirek` unit.
- `xy_to_rgb` is CIE xy -> XYZ -> the SAME Philips wide-gamut D65 matrix
  `ambient.py::_hex_to_xy` already uses (inverted — that function's own
  module docstring names it "ported from services/ambient_mode.py,
  unchanged") -> gamma-encoded sRGB, with out-of-gamut channels scaled down
  (never clipped) so a saturated point keeps its hue instead of smearing
  white into it. Not reached by the house/ambient paths today (they only
  ever carry mirek or an authored hex colour, never a raw xy reading), but
  kept correct and tested for the day something DOES hand this a bridge
  xy reading — the naive bug this whole investigation was checking for is
  treating x and y as raw R/G fractions directly, which is exactly what
  the (0.5163, 0.4145) acceptance case below is here to catch.
"""
from __future__ import annotations

import math
from typing import Optional

Look = tuple  # (area, kind, mirek, color, brightness) — see ambient.py/house.py

# Inverse of the forward matrix in ambient.py::_hex_to_xy (computed once via
# numpy.linalg.inv — see this module's own PR for the derivation; the two
# must always be exact inverses of one another, never independently tuned).
_XYZ_TO_RGB = (
    (1.65649365, -0.35485223, -0.25503781),
    (-0.70719583, 1.65539867, 0.03615257),
    (0.05171353, -0.12136503, 1.01153022),
)


def _clamp255(v: float) -> int:
    return max(0, min(255, round(v)))


def kelvin_to_rgb(kelvin: float) -> tuple[int, int, int]:
    """Tanner Helland's blackbody fit — byte-identical algorithm to
    `houseSummary.ts::kelvinToHex`. Never sent to a bulb; a swatch only."""
    t = max(1000.0, min(40000.0, kelvin)) / 100.0
    if t <= 66:
        r = 255.0
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
    if t <= 66:
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307
    return _clamp255(r), _clamp255(g), _clamp255(b)


def _gamma_encode(c: float) -> float:
    c = max(0.0, c)
    return 1.055 * (c ** (1 / 2.4)) - 0.055 if c > 0.0031308 else 12.92 * c


def xy_to_rgb(x: float, y: float, brightness: float = 1.0) -> tuple[int, int, int]:
    """CIE xy (plus a luminance `brightness` in [0, 1]) -> sRGB, through the
    Hue bridge's own wide-gamut matrix. `y<=0` (degenerate) is black, not a
    divide-by-zero."""
    if y <= 0:
        return (0, 0, 0)
    big_x = (brightness / y) * x
    big_z = (brightness / y) * (1 - x - y)
    lin = [sum(_XYZ_TO_RGB[row][col] * v
               for col, v in enumerate((big_x, brightness, big_z)))
           for row in range(3)]
    lin = [max(0.0, c) for c in lin]
    peak = max(lin + [1.0])
    lin = [c / peak for c in lin]
    srgb = [_gamma_encode(c) for c in lin]
    return tuple(_clamp255(c * 255) for c in srgb)  # type: ignore[return-value]


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, IndexError):
        return (255, 255, 255)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{_clamp255(c):02x}" for c in rgb)


def scale_rgb(rgb: tuple[int, int, int], fraction: float) -> tuple[int, int, int]:
    fraction = max(0.0, min(1.0, fraction))
    return tuple(_clamp255(c * fraction) for c in rgb)  # type: ignore[return-value]


def held_hex_for_look(look: Optional[Look]) -> Optional[str]:
    """The hex colour a held Hue bulb actually shows, from the SAME look
    tuple ambient.py sends to the bridge — `None` when this look does not
    hold the bulb at all (a `"show"` look, or no look resolved), so the
    caller keeps drawing the live render unchanged."""
    if look is None:
        return None
    _area, kind, mirek, color, brightness = look
    if kind == "off":
        return "#000000"
    if kind != "hold":
        return None
    fraction = max(0.0, min(100.0, float(brightness or 0.0))) / 100.0
    base = kelvin_to_rgb(1_000_000.0 / mirek) if mirek else hex_to_rgb(color or "#ffffff")
    return rgb_to_hex(scale_rgb(base, fraction))
