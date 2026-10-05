"""PER-DEVICE FRAME-RATE CAPS — a runtime ceiling on how often a fixture is
rendered and sent (SpotFX-authored; not fork code; `fx/VENDOR.md`
deviation #43).

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

`fx/` may not import `spectra/`: SPECTRA pushes, this module never pulls
(the shape of fx/device_timing.py and fx/device_output.py).
"""
from __future__ import annotations

import threading
from typing import Iterable, Optional

_lock = threading.Lock()
_caps: dict[str, float] = {}


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
    set_caps({})


def caps() -> dict[str, float]:
    return dict(_caps)


def active() -> bool:
    return bool(_caps)


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
