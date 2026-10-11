"""THE LIVE BACKGROUND FADES — one duration, one colour path (SpotFX-authored,
fx/VENDOR.md #68; the Admiral, 2026-10-11: "when the live background changes
due to a turning on or off of the light/dark mode, it should fade. The fade
timing should be default 1s, but when I do it from a light show, i should be
able to set the timing in the step ... This fade should also apply for when
we are in hybrid and the background changes, it should fade (and colors
should fade by rotation around wheel ...").

What fades: the RENDERED background of an effect — its background_color
times its background_brightness — which `Effect._advance_bg_fade` walks
toward each new target frame by frame. The effect's CONFIG still changes
instantly (it is the target); only the light on the fixture travels.

The path is the colour wheel, never a straight RGB line: hue takes the
shortest way round, saturation and value interpolate alongside it.
Achromatic endpoints, where hue is undefined:

  * BLACK (or nearly: value < ACHROMATIC) adopts the other end's hue AND
    saturation, so a fade to/from black is a pure brightness ramp in that
    colour — dark mode switching on dims the background in its own colour,
    never through grey or another hue.
  * GREY / WHITE (saturation < ACHROMATIC, still lit) adopts only the other
    end's hue and keeps its own saturation, so white -> red passes through
    pink and never through a different hue. (fx.effects.hue_tween_fields,
    the param-tween helper, adopts saturation for every achromatic end,
    which is right for black and a jump for white — this module does not
    share that rule.)

The duration is `duration_s()`: a per-call override (a ContextVar, so it
follows one asyncio task and anything it hands to `asyncio.to_thread`, and
never leaks into a concurrent scene fire) or else the process default
SPECTRA pushes from its room setting `background_fade_s` (1.0 s until
pushed). 0 means instant. `fx/` may not import `spectra/`, so the setting is
PUSHED here, never pulled.

A change that is ITSELF a fade — a param tween at least FOLLOW_MIN_S long,
i.e. a scene fire's crossfade or a flare's colour ramp — keeps its own
authored timing: the live background follows that tween frame by frame
instead of fading again on top of it (see `Effect._apply_config`'s
bg_follow). Only a change that would otherwise land in one frame (an
instant write, a 1 ms jump) takes this module's duration.
"""
from __future__ import annotations

import colorsys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

import numpy as np

DEFAULT_S = 1.0
MAX_S = 10.0
#: below this saturation (or value) a colour has no meaningful hue
ACHROMATIC = 0.05
#: a param tween at least this long is a fade of its own — the live
#: background follows it rather than fading again on top of it
FOLLOW_MIN_S = 0.05

_default_s: float = DEFAULT_S
_override: ContextVar[Optional[float]] = ContextVar("background_fade_s", default=None)


def _clamp(seconds: float) -> float:
    return max(0.0, min(MAX_S, float(seconds)))


def set_default_s(seconds: float) -> None:
    """The room's own fade length (SPECTRA's background_fade_s)."""
    global _default_s
    _default_s = _clamp(seconds)


def default_s() -> float:
    return _default_s


def duration_s() -> float:
    """The fade length a background change made RIGHT NOW takes."""
    o = _override.get()
    return _default_s if o is None else o


@contextmanager
def fading(seconds: Optional[float]) -> Iterator[None]:
    """Every background change made inside this block (in this task) fades
    over `seconds` instead of the default. None leaves the default."""
    if seconds is None:
        yield
        return
    token = _override.set(_clamp(seconds))
    try:
        yield
    finally:
        _override.reset(token)


def _hsv(rgb) -> tuple[float, float, float]:
    r, g, b = (float(c) / 255.0 for c in np.clip(np.asarray(rgb, dtype=float), 0, 255))
    return colorsys.rgb_to_hsv(r, g, b)


def path(start_rgb, target_rgb) -> tuple[np.ndarray, np.ndarray]:
    """(hsv_start, hsv_delta) for a wheel path from start to target (RGB
    0..255): the colour at progress t is hsv_start + t * hsv_delta, hue
    taken mod 1. See the module docstring for the achromatic rules."""
    hs, ss, vs = _hsv(start_rgb)
    ht, st, vt = _hsv(target_rgb)
    s_black, t_black = vs < ACHROMATIC, vt < ACHROMATIC
    s_grey, t_grey = s_black or ss < ACHROMATIC, t_black or st < ACHROMATIC
    if s_grey and not t_grey:
        hs = ht
    elif t_grey and not s_grey:
        ht = hs
    if s_black and not t_black:
        ss = st
    elif t_black and not s_black:
        st = ss
    dh = ((ht - hs + 0.5) % 1.0) - 0.5
    return np.array([hs, ss, vs]), np.array([dh, st - ss, vt - vs])


def at(hsv_start: np.ndarray, hsv_delta: np.ndarray, t: float) -> np.ndarray:
    """The RGB (0..255 floats) a wheel path reaches at progress t (0..1)."""
    h, s, v = hsv_start + min(max(t, 0.0), 1.0) * hsv_delta
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(max(s, 0.0), 1.0), min(max(v, 0.0), 1.0))
    return np.array([r, g, b], dtype=float) * 255.0
