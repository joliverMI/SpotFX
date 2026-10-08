"""PER-VIRTUAL PULSE MODULATION — the Light Show's hand on the Pulse effect
(SpotFX-authored; not fork code; `fx/VENDOR.md` deviation #66).

The Admiral, 2026-10-08: "modulate a few things on the 'pulse' effect.
1. Overall reactivity. 1 is max, 0 is none. 2. ... the brightness floor and
ceiling". SPECTRA's Light Show holds these per VIRTUAL (spectra/services/
show_mods.py); `fx/effects/pulse.py` reads them once per rendered frame.

WHAT EACH ONE MEANS (pulse.py's own docstring is the binding statement for
how they land):

  reactivity  0..1 — multiplies the light's live-audio hit pulse (the
              depth x envelope term). 1 = untouched, 0 = no hit pulse at all.
  floor       0..1 — the effect's level (EYE scale, the same 0..1 scale as
              its rest/depth settings) never goes below this.
  ceiling     0..1 — ... and never above this.

A MODULATION IS NOT A CONFIG WRITE. Writing Pulse's own params would fight
every scene fire (which rewrites them), the Pulse feed and the param
watchdog (which restores a non-baseline param after 30 s). This is a side
channel the effect reads, like `fx/device_output.py` one layer down.

THE IDLE PATH IS ONE DICT LOOKUP: `get()` returns None for a virtual with
no entry, and pulse.py then renders byte-identically to before this module
existed (asserted in tests/test_pulse_modulation.py).

RAMPS: a new value is reached linearly over `fade_s`, evaluated per read
against the injectable clock (no ticker, `device_output`'s shape). A ramp
starts from wherever the previous ramp had got to, so a hold ending mid-fade
never jumps. An entry back at identity with its ramp finished is pruned by
`prune()` (SPECTRA's supervisor calls it).

SUSPENSION: while a preview, capture or night run holds the room SPECTRA
suspends this, exactly as it suspends the per-device output layer: every
read answers None (untouched) and every target is kept.

`fx/` may not import `spectra/`: SPECTRA pushes, this module never pulls.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Mod:
    reactivity: float = 1.0
    floor: float = 0.0
    ceiling: float = 1.0

    def is_identity(self) -> bool:
        return self.reactivity == 1.0 and self.floor == 0.0 and self.ceiling == 1.0


IDENTITY = Mod()


@dataclass(frozen=True)
class _Ramp:
    start: Mod
    end: Mod
    t0: float
    dur: float

    def at(self, now: float) -> Mod:
        if self.dur <= 0.0 or now >= self.t0 + self.dur:
            return self.end
        s = max(0.0, (now - self.t0) / self.dur)

        def lerp(a: float, b: float) -> float:
            return a + (b - a) * s

        return Mod(lerp(self.start.reactivity, self.end.reactivity),
                   lerp(self.start.floor, self.end.floor),
                   lerp(self.start.ceiling, self.end.ceiling))

    def done(self, now: float) -> bool:
        return self.dur <= 0.0 or now >= self.t0 + self.dur


_lock = threading.Lock()
_ramps: dict[str, _Ramp] = {}
_suspended = False
_clock: Callable[[], float] = time.monotonic


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def set_mod(virtual_id: str, *, reactivity: float = 1.0, floor: float = 0.0,
            ceiling: float = 1.0, fade_s: float = 0.0) -> None:
    """Head toward these values over `fade_s`, from wherever this virtual's
    modulation is right now. Identity values are a legitimate target (a
    hold ending fades back through them, then `prune()` drops the entry)."""
    end = Mod(_clamp01(reactivity), _clamp01(floor), _clamp01(ceiling))
    now = _clock()
    with _lock:
        cur = _ramps.get(virtual_id)
        start = cur.at(now) if cur is not None else IDENTITY
        new = dict(_ramps)
        new[virtual_id] = _Ramp(start, end, now, max(0.0, float(fade_s)))
        globals()["_ramps"] = new


def get(virtual_id: Optional[str]) -> Optional[Mod]:
    """The modulation to apply to this virtual's Pulse NOW, or None (no
    entry, or suspended). Render threads: a dict read and a lerp."""
    if _suspended or virtual_id is None:
        return None
    r = _ramps.get(virtual_id)
    if r is None:
        return None
    return r.at(_clock())


def clear(virtual_id: Optional[str] = None) -> None:
    """Drop one virtual's entry at once (or every entry)."""
    with _lock:
        if virtual_id is None:
            globals()["_ramps"] = {}
        elif virtual_id in _ramps:
            new = dict(_ramps)
            new.pop(virtual_id, None)
            globals()["_ramps"] = new


def prune() -> list[str]:
    """Drop entries that have finished fading back to identity."""
    now = _clock()
    with _lock:
        gone = [v for v, r in _ramps.items() if r.done(now) and r.end.is_identity()]
        if gone:
            globals()["_ramps"] = {v: r for v, r in _ramps.items() if v not in gone}
    return gone


def suspend(flag: bool) -> None:
    global _suspended
    _suspended = bool(flag)


def suspended() -> bool:
    return _suspended


def snapshot() -> dict[str, dict]:
    now = _clock()
    return {v: {"reactivity": round(m.reactivity, 4), "floor": round(m.floor, 4),
                "ceiling": round(m.ceiling, 4)}
            for v, m in ((v, r.at(now)) for v, r in _ramps.items())}


def set_clock(clock: Callable[[], float]) -> None:
    """Tests."""
    global _clock
    _clock = clock
