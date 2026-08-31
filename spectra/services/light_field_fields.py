"""THE FOUR FIELD KINDS — every spatial room effect his plan names, as the
same computation over the same measured footprints.

HIS INSTRUCTION, and why three of these exist without a UI: build ONLY the
Dim Wave, but build the INTERFACE for all four from day one. A field is a
scalar over the room, sampled through each emitter's footprint by
light_field.per_emitter_scalar into one number per emitter per tick. If the
interface only ever had to serve a 1-D wave, the honest storage would be
the axis profile alone — and the day the second effect arrived the whole
map would need re-capturing. Implode and Explode read x/y, so the full 2-D
grid is stored, and that is the entire argument for its existence.

  dim_wave        sine along the room's axis           -> a BRIGHTNESS gain
  hue_rotation    hue phase along the room's axis      -> DEGREES of hue
  implode         inward pulse from a picked point     -> a BRIGHTNESS gain
  explode         outward pulse from a picked point    -> a BRIGHTNESS gain

ONLY dim_wave is wired to the lights (spectra/services/room_effects.py).
The other three are pure functions with tests and nothing that writes: they
prove the interface serves them, they do not ship as features. Wiring one
is a new task with his say-so, not a flag flip here.

UNITS, stated once so no caller has to guess:
  axis position   0..1, floor -> ceiling (the room's two taps)
  wavelength      in axis units: 1.0 = one full cycle across the whole axis,
                  0.5 = two cycles. NOT metres — this map has no metres.
  speed           cycles per second the pattern TRAVELS along the axis.
                  Positive travels toward the ceiling.
  depth           0..1, how far the dimmest phase dips. depth=0 is exactly
                  1.0 everywhere (a byte-identical no-op, asserted, not
                  claimed); depth=1 reaches full black at the trough.

A field's own output for dim_wave/implode/explode is a GAIN in [1-depth, 1]
— never a brightness. What multiplies onto what, and where, is the room
effects layer's business, not this module's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from spectra.services.light_field import EmitterSamples

TWO_PI = 2.0 * math.pi
MIN_WAVELENGTH = 0.05
MAX_WAVELENGTH = 8.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


@dataclass(frozen=True)
class DimWave:
    """THE SLICE'S ONE EFFECT. A travelling cosine along the room's axis,
    expressed as a brightness gain.

        phase = 2*pi * (axis / wavelength - speed * t)
        gain  = 1 - depth * (1 - cos(phase)) / 2

    The crest sits at gain 1.0 (the room's own brightness, untouched) and
    the trough at 1 - depth, so the wave only ever takes light away. That is
    deliberate: a gain that could exceed 1 would push a fixture past what
    the show authored, which is not what "dim wave" means and would fight
    the brightness multiplier rather than compose with it."""

    wavelength: float = 1.0
    speed: float = 0.25
    depth: float = 0.6
    kind: str = "dim_wave"

    def __post_init__(self) -> None:
        object.__setattr__(self, "wavelength",
                           _clamp(float(self.wavelength), MIN_WAVELENGTH, MAX_WAVELENGTH))
        object.__setattr__(self, "speed", _clamp(float(self.speed), -4.0, 4.0))
        object.__setattr__(self, "depth", _clamp(float(self.depth), 0.0, 1.0))

    def __call__(self, s: EmitterSamples, t: float) -> np.ndarray:
        phase = TWO_PI * (s.axis / self.wavelength - self.speed * t)
        return 1.0 - self.depth * (1.0 - np.cos(phase)) * 0.5

    def phase_at(self, axis: float, t: float) -> float:
        """The wave's phase at one axis position — what a test asserts a
        measured phase LAG against, computed from the same expression the
        field itself uses rather than a second copy of the arithmetic."""
        return TWO_PI * (axis / self.wavelength - self.speed * t)


@dataclass(frozen=True)
class HueRotation:
    """NOT BUILT — the interface's second customer, proven pure.

    Same travelling phase as DimWave, but the value is DEGREES of hue
    rotation rather than a gain, because the machinery it would drive is the
    per-virtual colour rotate (spectra/services/color_rotate.py), which
    speaks degrees. Nothing writes this."""

    wavelength: float = 1.0
    speed: float = 0.25
    span_deg: float = 180.0
    kind: str = "hue_rotation"

    def __call__(self, s: EmitterSamples, t: float) -> np.ndarray:
        phase = TWO_PI * (s.axis / self.wavelength - self.speed * t)
        return self.span_deg * 0.5 * (1.0 - np.cos(phase))


@dataclass(frozen=True)
class RadialPulse:
    """NOT BUILT — implode and explode, the two kinds that read x/y and
    therefore justify storing the whole 2-D footprint.

    A ring of half-width `width` sweeping through the footprint plane from a
    picked point: `outward=False` implodes (the ring starts at the far edge
    and collapses onto the point), `outward=True` explodes. Distance is in
    the camera's own normalized frame — one pose, no metres, exactly the
    plan's "fully served by camera-space maps for one pose"."""

    cx: float = 0.5
    cy: float = 0.5
    speed: float = 0.5
    width: float = 0.2
    depth: float = 0.8
    outward: bool = True
    kind: str = "explode"

    def __call__(self, s: EmitterSamples, t: float) -> np.ndarray:
        d = np.hypot(s.x - self.cx, s.y - self.cy)
        travel = (self.speed * t) % 1.0
        radius = travel if self.outward else (1.0 - travel)
        near = np.clip(1.0 - np.abs(d - radius) / max(1e-6, self.width), 0.0, 1.0)
        return 1.0 - self.depth * (1.0 - near)


def implode(**kw) -> RadialPulse:
    kw.setdefault("kind", "implode")
    return RadialPulse(outward=False, **kw)


def explode(**kw) -> RadialPulse:
    kw.setdefault("kind", "explode")
    return RadialPulse(outward=True, **kw)


#: Every kind the interface serves, so a caller can enumerate them without a
#: second hand-written list. `built` says which one actually reaches lights.
KINDS = {
    "dim_wave": {"built": True, "value": "brightness gain 0..1",
                 "knobs": ["wavelength", "speed", "depth"]},
    "hue_rotation": {"built": False, "value": "hue rotation in degrees",
                     "knobs": ["wavelength", "speed", "span_deg"]},
    "implode": {"built": False, "value": "brightness gain 0..1",
                "knobs": ["cx", "cy", "speed", "width", "depth"]},
    "explode": {"built": False, "value": "brightness gain 0..1",
                "knobs": ["cx", "cy", "speed", "width", "depth"]},
}
