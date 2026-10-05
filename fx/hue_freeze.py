"""HUE AREAS THAT COME UP FROZEN (SpotFX-authored; not fork code;
`fx/VENDOR.md` deviation #46).

A Hue area held over the bridge (Hue Hold, or a house mode's per-area look)
is a `HueDevice` whose entertainment stream is STOPPED (`set_frozen`): the
bulbs keep the colour the bridge REST writes gave them. Freeze state lives on
the device object, and a restart builds fresh objects — so for the second or
two between the new stack coming up and the Hue Hold gate re-freezing them,
the area STREAMED the show's render and seventeen bulbs blinked to it.

SPECTRA names the areas that were held when it stopped (house lighting's
restart snapshot) BEFORE the stack comes up; `HueDevice.activate` consumes
the name and comes up frozen — no entertainment session is ever started, the
bulbs keep their held look, and the gate's own reconcile moments later
confirms the hold (or unfreezes the area if the room has moved on).

ONE-SHOT, per device: a name is consumed by the activation it was meant for,
so a later activation (a virtual re-activating the device mid-show, after the
gate has deliberately unfrozen it) is never frozen by a stale entry. `clear()`
drops whatever was not consumed.

`fx/` may not import `spectra/`: SPECTRA pushes, this module never pulls.
"""
from __future__ import annotations

import threading
from typing import Iterable

_lock = threading.Lock()
_pending: set[str] = set()
#: names an activation actually consumed — SPECTRA checks these after its
#: Hue Hold gate has run, and unfreezes any the gate did not end up holding
_consumed: set[str] = set()


def set_pending(device_ids: Iterable[str]) -> set[str]:
    """Name the Hue devices that should come up frozen. Replaces wholesale."""
    global _pending
    with _lock:
        _pending = {str(d) for d in device_ids or ()}
        return set(_pending)


def consume(device_id: str) -> bool:
    """True (once) when `device_id` was named: its activation comes up
    frozen. Thread-safe — activation can run from the loop or a render
    thread."""
    with _lock:
        if device_id in _pending:
            _pending.discard(device_id)
            _consumed.add(device_id)
            return True
    return False


def pending() -> set[str]:
    return set(_pending)


def take_consumed() -> set[str]:
    """The devices that came up frozen since the last call (and forget
    them)."""
    global _consumed
    with _lock:
        out, _consumed = set(_consumed), set()
    return out


def clear() -> None:
    set_pending(())
    take_consumed()
