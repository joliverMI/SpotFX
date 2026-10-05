"""PER-DEVICE FRAME-RATE CAPS — a runtime ceiling on how often a fixture is
rendered and sent (SpotFX-authored; not fork code; `fx/VENDOR.md`
deviations #43 and #47).

WHY. A virtual renders at the minimum of its devices' configured
`refresh_rate` (fx/virtuals.py `Virtual.refresh_rate`) and every rendered
frame is flushed — a DDP packet set per frame, no change detection. Two
single-pixel fixtures at 62 fps were 37% of his room's packets with no music
playing (data/standard-lighting-plan/report.md §6). House lighting's calm
modes do not need that rate, so SPECTRA pushes a CAP per device and the
render loop sleeps to the lower of the two.

ONLY EVER LOWERS. `effective_rate` returns `min(configured, cap)`; a cap
above the configured rate changes nothing (his crystal's 30 stands — the
caps can only slow it). No cap anywhere — the shipped state — returns the
configured rate untouched through one dict check.

THE SIBLING TRADE, stated: the cap acts on the VIRTUAL's render loop, so a
virtual spanning several devices (his `tv-mapper`: TV backlight + both
kitchen sconces) runs at the lowest cap among them. Per-device pacing that
lets siblings run at their own rate is a separate, later change (the idea in
open PR #58).

PARKING (#47, house lighting phase 3). A virtual NONE of whose devices takes
its frames renders at `PARKED_FPS` instead of its full rate while SPECTRA has
parking switched on (`set_park_idle`). "Takes no frames" is read LIVE, on the
render thread, from the device objects themselves:

  * a DUMMY device                (his `radial-dummy`: a whole Strips-category
                                  virtual at 62 fps that lights nothing)
  * a WITHHELD device             (fx/device_output.py #44: lent to Hyperion,
                                  switched off, its mains off) — and only
                                  while withholding is in force, i.e. never
                                  during a capture's suspension
  * a FROZEN Hue area             (held over the bridge: its stream is stopped
                                  and fx/devices/hue.py drops every frame)
  * an INACTIVE device            (a driver that never came up: update_pixels
                                  refuses it)

so un-withholding a fixture, unfreezing a Hue area or a driver coming up
returns the virtual to its full rate on its very next frame — no supervisor
lag, nothing to clobber. A virtual with at least one emitting device is never
parked (the sibling rule again, in the safe direction).

WHY NOT ZERO. A parked virtual still renders and flushes PARKED_FPS frames a
second. The render-plane dead-man (spectra/services/frame_watchdog.py, and
the liveness contract's `healthy`) requires every ACTIVE virtual to flush a
frame within live_host.STALE_AFTER_S (2 s); 2 frames/s keeps a 1.5 s margin.
Deactivating the virtual instead is worse twice over: it reads as an
activation gap, and the facade's write repair (#29) re-activates it on the
next scene fire that writes its category.

BELOW THE SLEEP TABLE. The render loop turns a rate into a sleep through the
vendored `fx/utils.py fps_to_sleep_interval`, whose table starts at 10 fps:
every rate at or below it sleeps one table step (91 ms, ~11 fps). So a cap of
10 used to give ~11 fps and a park at 2 fps would have given ~11 too.
`sleep_interval()` answers 1/rate for a rate this module lowered to
TABLE_MIN_FPS or below; above it the vendored table is used unchanged.

`fx/` may not import `spectra/`: SPECTRA pushes, this module never pulls
(the shape of fx/device_timing.py and fx/device_output.py).
"""
from __future__ import annotations

import threading
from typing import Iterable, Optional

from fx import device_output

_lock = threading.Lock()
_caps: dict[str, float] = {}

#: frames/s a virtual that lights nothing renders at while parking is on —
#: see WHY NOT ZERO above (live_host.STALE_AFTER_S is 2.0 s).
PARKED_FPS = 2.0
_park_idle = False
#: the lowest rate the vendored fps→sleep table resolves (BELOW THE SLEEP
#: TABLE above)
TABLE_MIN_FPS = 10.0


def set_caps(caps: Optional[dict]) -> dict[str, float]:
    """Replace every cap wholesale. A missing, zero or negative cap is no
    cap. Returns what is now in force."""
    global _caps
    new = {}
    for did, fps in (caps or {}).items():
        try:
            v = float(fps)
        except (TypeError, ValueError):
            continue
        if v > 0:
            new[str(did)] = v
    with _lock:
        _caps = new
    return dict(new)


def clear() -> None:
    """Drop every cap AND switch parking off (the shipped state)."""
    global _park_idle
    set_caps({})
    _park_idle = False


def caps() -> dict[str, float]:
    return dict(_caps)


def set_park_idle(on: bool) -> None:
    """Switch parking on or off (see PARKING above). SPECTRA's house layer
    turns it on while a mode drives the room."""
    global _park_idle
    _park_idle = bool(on)


def park_idle() -> bool:
    return _park_idle


def active() -> bool:
    return bool(_caps) or _park_idle


def cap_for(device_ids: Iterable[str]) -> Optional[float]:
    """The lowest cap among these devices, or None."""
    table = _caps
    if not table:
        return None
    found = [table[d] for d in device_ids if d in table]
    return min(found) if found else None


def effective_rate(rate, device_ids: Iterable[str]):
    """The rate a virtual over these devices should render at. Returns
    `rate` itself (the same object) when nothing caps it."""
    if not _caps or not rate:
        return rate
    cap = cap_for(device_ids)
    if cap is None or cap >= rate:
        return rate
    return cap


def takes_no_frames(device) -> bool:
    """Does this device take none of a virtual's frames right now? (Render
    thread; never raises — an unreadable device counts as taking frames.)"""
    try:
        if str(getattr(device, "type", "") or "") == "dummy":
            return True
        did = getattr(device, "id", None)
        if did is not None and device_output.is_withheld(did):
            return True
        if getattr(device, "frozen", False) is True:
            return True
        is_active = getattr(device, "is_active", None)
        if callable(is_active) and not is_active():
            return True
    except Exception:                                    # noqa: BLE001
        return False
    return False


def idle(devices) -> bool:
    """True when the virtual over these devices lights nothing: there is at
    least one device and none of them takes frames."""
    devices = list(devices or ())
    if not devices:
        return False
    return all(takes_no_frames(d) for d in devices)


def rate_for(rate, devices):
    """The render loop's one call: the configured rate, lowered by any cap
    on these devices, and parked when parking is on and none of them takes
    frames. Returns `rate` itself when nothing applies."""
    if not rate or not (_caps or _park_idle):
        return rate
    devices = list(devices or ())
    out = effective_rate(rate, (getattr(d, "id", None) for d in devices))
    if _park_idle and idle(devices) and PARKED_FPS < out:
        out = PARKED_FPS
    if out < rate and out < PARKED_FPS:
        # No cap takes a virtual below the parked rate: the render-plane
        # dead-man's 2 s margin (WHY NOT ZERO) holds for every cap too.
        out = min(rate, PARKED_FPS)
    return out


def sleep_interval(rate) -> Optional[float]:
    """The render loop's sleep for a rate at or below the vendored table's
    floor (1/rate), or None to use the table (see BELOW THE SLEEP TABLE)."""
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return None
    if 0.0 < r <= TABLE_MIN_FPS:
        return 1.0 / r
    return None
