"""PER-DEVICE OUTPUT CONTROL — the one place a whole fixture is made dark,
steady, frozen, dimmed or flashed (SpotFX-authored; not fork code;
`fx/VENDOR.md` deviation #41).

WHY HERE. Scenes address CATEGORIES, and three of his four driven virtuals
fan out to several real fixtures (tv-mapper → TV backlight + both kitchen
sconces; single-color-effect → dining table + porch rail; hues → both Hue
areas). Nothing upstream of the device can darken ONE sconce: deactivating a
virtual evicts neighbours (#29/#37), an effect-config brightness write is per
virtual and fights the watchdog, and the per-virtual gain mask is applied
BEFORE a copy-mapped virtual expands. The device flush is the first point
where one fixture's frame exists on its own, so that is where this lives:
`Device.update_pixels`, between `assemble_frame()` and `_flush_timed()`.

IT COMPOSES, IT NEVER FIGHTS. Everything upstream — the show's own render,
the room brightness dimmer (scaled into effect writes at the seam), a room
effect's multiplicative gain (a brightness write or a per-pixel mask at frame
assembly) — has already shaped the frame this module receives. A Level is one
more multiply on that frame; Dark is a multiply by zero; a Flash mixes toward
a colour. STEADY replaces the picture with a colour, so it would ignore the
dimmer and a running wave — unless they are handed in, which is what
`set_scale_provider` is for: SPECTRA pushes a callable answering "what gain is
the room applying to this device right now" (dimmer × any room-effect gain),
and a steady colour is multiplied by it. The show is never paused: it keeps
rendering underneath every state, so returning a fixture to SHOW fades back
into a frame that is already in step with the music.

THE IDLE PATH IS ONE DICT CHECK. With nothing set — the shipped state, and
the state every frame is in whenever no Light Show holds a fixture — `apply()`
returns the SAME frame object it was handed. Byte-identical, asserted in
tests/test_device_output_landing.py.

NEVER IN PLACE. `assemble_frame()` can hand back the device's own `_pixels`
buffer, which every virtual writes into next frame; a multiply in place would
compound frame after frame. Every non-idle result is a new array.

RAMPS ARE EVALUATED PER RENDERED FRAME against the injectable clock, so a
fade is as smooth as the render loop and needs no ticker. A target is an
immutable value replaced wholesale (copy-on-write) by the setters, which run
on SPECTRA's event loop; the render threads only ever read the current dict.
Per-device runtime (the "fading from" picture, the frozen frame, the last
output) is touched only by that device's own render thread.

SUSPENSION. `suspend(True)` makes `apply()` pass every frame through
untouched while keeping every target — SPECTRA sets it while a preview,
capture or night run holds the room, because a fixture the show holds dark
would otherwise make a mapping run record it as unseen. Lifting it resumes
exactly where the targets say.

`fx/` may not import `spectra/`: SPECTRA pushes, this module never pulls
(the shape of fx/device_timing.py).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np

STATE_SHOW = "show"
STATE_STEADY = "steady"
STATE_FREEZE = "freeze"
STATE_DARK = "dark"
STATES = (STATE_SHOW, STATE_STEADY, STATE_FREEZE, STATE_DARK)

#: A Level above 100% brightens; anything already at full clips. 2.0 is the
#: ceiling the Light Show's own Level action declares.
MAX_LEVEL = 2.0

_lock = threading.Lock()
_targets: dict[str, "Target"] = {}
_runtime: dict[str, "_Runtime"] = {}
_suspended = False
_clock: Callable[[], float] = time.monotonic
_scale_provider: Optional[Callable[[str], float]] = None


@dataclass(frozen=True)
class Flash:
    color: tuple            # (r, g, b) 0-255
    amount: float           # 0..1 peak mix toward `color`
    start: float            # clock seconds
    attack_s: float
    hold_s: float
    decay_s: float

    def mix(self, now: float) -> float:
        t = now - self.start
        if t < 0:
            return 0.0
        if t < self.attack_s:
            return self.amount * (t / self.attack_s)
        t -= self.attack_s
        if t < self.hold_s:
            return self.amount
        t -= self.hold_s
        if t < self.decay_s:
            return self.amount * (1.0 - t / self.decay_s)
        return 0.0

    def done(self, now: float) -> bool:
        return now >= self.start + self.attack_s + self.hold_s + self.decay_s


@dataclass(frozen=True)
class Target:
    """What one device should look like. Immutable; replaced wholesale."""
    state: str = STATE_SHOW
    color: Optional[tuple] = None          # STEADY's colour
    state_seq: int = 0                     # bumps on every set_state
    state_set_at: float = 0.0
    state_fade_s: float = 0.0
    level: float = 1.0                     # where the level is heading
    level_from: float = 1.0                # where it was when it was set
    level_set_at: float = 0.0
    level_fade_s: float = 0.0
    flash: Optional[Flash] = None

    def level_at(self, now: float) -> float:
        if self.level_fade_s <= 0.0:
            return self.level
        w = (now - self.level_set_at) / self.level_fade_s
        if w >= 1.0:
            return self.level
        if w <= 0.0:
            return self.level_from
        return self.level_from + (self.level - self.level_from) * w

    def state_weight(self, now: float) -> float:
        if self.state_fade_s <= 0.0:
            return 1.0
        return max(0.0, min(1.0, (now - self.state_set_at) / self.state_fade_s))

    def identity_at(self, now: float) -> bool:
        """True when this target no longer changes a single pixel — the
        condition prune() removes it on."""
        return (self.state == STATE_SHOW and self.state_weight(now) >= 1.0
                and self.level == 1.0 and self.level_at(now) == 1.0
                and (self.flash is None or self.flash.done(now)))


@dataclass
class _Runtime:
    seen_seq: int = -1
    from_state: str = STATE_SHOW
    from_color: Optional[tuple] = None
    from_frame: Optional[np.ndarray] = None   # a frozen picture to fade from
    cur_frozen: Optional[np.ndarray] = None   # FREEZE's own captured picture
    last_out: Optional[np.ndarray] = None
    settled: bool = True


# ── configuration pushed in by SPECTRA ─────────────────────────────────────

def set_clock(clock: Callable[[], float]) -> None:
    global _clock
    _clock = clock


def reset_clock() -> None:
    set_clock(time.monotonic)


def now() -> float:
    return _clock()


def set_scale_provider(fn: Optional[Callable[[str], float]]) -> None:
    """Install the "what gain is the room applying to this device" callable
    a STEADY colour is multiplied by. None = 1.0. Called from the render
    thread, so it must be cheap and must never raise (a raise is caught and
    read as 1.0)."""
    global _scale_provider
    _scale_provider = fn


def suspend(on: bool) -> None:
    global _suspended
    _suspended = bool(on)


def suspended() -> bool:
    return _suspended


# ── setters (SPECTRA's event loop) ─────────────────────────────────────────

def _put(device_id: str, target: Target) -> None:
    global _targets
    with _lock:
        new = dict(_targets)
        new[device_id] = target
        _targets = new


def target(device_id: str) -> Optional[Target]:
    return _targets.get(device_id)


def set_state(device_id: str, state: str, *, color: Optional[tuple] = None,
              fade_s: float = 0.0) -> Target:
    if state not in STATES:
        raise ValueError(f"unknown output state {state!r}")
    if state == STATE_STEADY:
        if color is None:
            raise ValueError("steady needs a colour")
        color = tuple(float(max(0, min(255, c))) for c in color)
    prev = _targets.get(device_id) or Target()
    t = now()
    new = replace(prev, state=state, color=color if state == STATE_STEADY else None,
                  state_seq=prev.state_seq + 1, state_set_at=t,
                  state_fade_s=max(0.0, float(fade_s)))
    _put(device_id, new)
    return new


def set_level(device_id: str, level: float, *, fade_s: float = 0.0) -> Target:
    level = max(0.0, min(MAX_LEVEL, float(level)))
    prev = _targets.get(device_id) or Target()
    t = now()
    new = replace(prev, level=level, level_from=prev.level_at(t), level_set_at=t,
                  level_fade_s=max(0.0, float(fade_s)))
    _put(device_id, new)
    return new


def flash(device_id: str, *, color: tuple = (255, 255, 255), amount: float = 1.0,
          attack_s: float = 0.05, hold_s: float = 0.1,
          decay_s: float = 0.4) -> Target:
    prev = _targets.get(device_id) or Target()
    f = Flash(color=tuple(float(max(0, min(255, c))) for c in color),
              amount=max(0.0, min(1.0, float(amount))), start=now(),
              attack_s=max(0.0, float(attack_s)), hold_s=max(0.0, float(hold_s)),
              decay_s=max(0.0, float(decay_s)))
    new = replace(prev, flash=f)
    _put(device_id, new)
    return new


def clear(device_id: str) -> None:
    """Drop a device's target outright — its frames pass through untouched
    from the next frame. An abrupt hand-back; a fade back is set_state(SHOW)
    and set_level(1.0) with a fade, then prune()."""
    global _targets
    with _lock:
        if device_id in _targets:
            new = dict(_targets)
            new.pop(device_id, None)
            _targets = new
    _runtime.pop(device_id, None)


def clear_all() -> None:
    global _targets
    with _lock:
        _targets = {}
    _runtime.clear()


def prune() -> list[str]:
    """Remove every target that no longer changes a pixel (settled back to
    SHOW at 100% with no flash in flight). Returns the ids removed."""
    t = now()
    gone = [d for d, tg in _targets.items() if tg.identity_at(t)]
    for d in gone:
        clear(d)
    return gone


def snapshot() -> dict[str, dict]:
    """A plain-data view for status surfaces."""
    t = now()
    out = {}
    for d, tg in _targets.items():
        out[d] = {"state": tg.state, "color": list(tg.color) if tg.color else None,
                  "state_weight": round(tg.state_weight(t), 3),
                  "level": round(tg.level_at(t), 3), "level_target": tg.level,
                  "flashing": bool(tg.flash and not tg.flash.done(t))}
    return out


# ── the render-thread half ─────────────────────────────────────────────────

def _scale(device_id: str) -> float:
    fn = _scale_provider
    if fn is None:
        return 1.0
    try:
        v = float(fn(device_id))
    except Exception:                       # noqa: BLE001 - never kill a frame
        return 1.0
    return v if v >= 0.0 else 0.0


def _render(state: str, color, frozen, frame: np.ndarray, device_id: str) -> np.ndarray:
    if state == STATE_SHOW:
        return frame
    if state == STATE_DARK:
        return np.zeros_like(frame, dtype=float)
    if state == STATE_STEADY:
        out = np.empty(frame.shape, dtype=float)
        out[...] = np.asarray(color, dtype=float) * _scale(device_id)
        return out
    # FREEZE
    if frozen is not None and frozen.shape == frame.shape:
        return frozen
    return frame


def apply(device_id: str, frame):
    """The per-frame hook. Returns `frame` itself when nothing applies."""
    if not _targets or _suspended:            # the idle path
        return frame
    tg = _targets.get(device_id)
    if tg is None:
        return frame
    t = now()
    rt = _runtime.get(device_id)
    if rt is None:
        rt = _runtime[device_id] = _Runtime()
    base = np.asarray(frame, dtype=float)

    if rt.seen_seq != tg.state_seq:
        # A NEW STATE. Fade from whatever is on the fixture: if the previous
        # transition had settled, from its own state (a SHOW keeps tracking
        # the live frame through the fade); if it was mid-fade, from a
        # frozen copy of the last frame actually sent.
        if rt.seen_seq >= 0 and not rt.settled and rt.last_out is not None:
            rt.from_state, rt.from_color = STATE_FREEZE, None
            rt.from_frame = rt.last_out
        elif rt.seen_seq >= 0:
            rt.from_frame = rt.cur_frozen
        else:
            rt.from_state, rt.from_color, rt.from_frame = STATE_SHOW, None, None
        rt.cur_frozen = None
        if tg.state == STATE_FREEZE:
            rt.cur_frozen = (np.array(rt.last_out, copy=True)
                             if rt.last_out is not None
                             and rt.last_out.shape == base.shape
                             else np.array(base, copy=True))
        rt.seen_seq = tg.state_seq

    w = tg.state_weight(t)
    cur = _render(tg.state, tg.color, rt.cur_frozen, base, device_id)
    if w >= 1.0:
        out = cur
        if not rt.settled:
            rt.settled = True
        rt.from_state, rt.from_color, rt.from_frame = (
            tg.state, tg.color, rt.cur_frozen)
    else:
        rt.settled = False
        prev = _render(rt.from_state, rt.from_color, rt.from_frame, base, device_id)
        out = prev + (cur - prev) * w

    lvl = tg.level_at(t)
    if lvl != 1.0:
        out = out * lvl
    if tg.flash is not None:
        a = tg.flash.mix(t)
        if a > 0.0:
            out = out + (np.asarray(tg.flash.color, dtype=float) - out) * a
    out = np.clip(out, 0.0, 255.0)          # always a new array
    rt.last_out = out
    return out
