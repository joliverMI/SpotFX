"""PER-VIRTUAL GAIN MASK — a multiplicative float array applied to one
virtual's assembled frame (SpotFX-authored; not fork code).

WHY IT EXISTS. The room light-field layer used to apply ONE brightness
number per virtual, so a gain could not vary ALONG a strip. The owner's
own correction: "A single device that spans the direction of the wave
should be able to show the effect. the tv mapper is wrapped around a tv.
It should be able to run a dimness wave vertically." A wave that reaches
only whole fixtures cannot do that; a per-pixel gain can.

WHAT THIS MODULE IS. A process-global map from virtual id to a float
array, one entry per EFFECT pixel of that virtual, plus nothing else. It
is deliberately dumb and dependency-free for the same reason
fx/device_timing.py is: `fx/` is the shared library and may not import
anything under `spectra/`, so SPECTRA owns the meaning of the numbers
(spectra/services/room_effects.py derives them from measured footprints)
and PUSHES them in here. Nothing in fx/ reads a store, and nothing here
knows what a footprint, a room or a wave is.

THE ONE APPLICATION POINT is `fx/virtuals.py::Virtual.assemble_frame`,
immediately after the two multiplies the fork already does
(`max_brightness`, then the global brightness) — see `fx/VENDOR.md`
deviation #25. That is the layer the device driver reads and the layer the
device preview taps (`Event.VIRTUAL_UPDATE` is fired from the same
assembled frame), so a mask is visible in exactly the places the light is.

    no masks installed  =>  `_masks` is empty  =>  mask_for() returns None
                            on a dict truth check and assemble_frame's
                            branch is not taken: the path is byte-identical
                            to the fork's. Asserted, not claimed —
                            scripts/check_room_effect_mask.py.

UNITS AND SHAPE. A mask value is a plain multiplier, clamped by the caller
to whatever range it means; this module clamps nothing and interprets
nothing. Its LENGTH must equal the virtual's effective pixel count (the
number of rows in the assembled frame). A mask whose length does not match
is SKIPPED rather than resampled — a silently stretched gain would be a
wave at the wrong wavelength, which is worse than no wave — and the skip
is counted (`stats()`) so the mismatch is visible instead of mysterious.

A VIRTUAL WITH NO MASK IS NEVER GIVEN A DEFAULT ONE. "No entry" and "an
all-ones mask" are the same to the light and different to a reader: the
first says nothing is driving this virtual per-pixel, the second says
something is and has chosen 1.0.
"""
from __future__ import annotations

import threading
from typing import Mapping, Optional

import numpy as np

_lock = threading.Lock()
_masks: dict[str, np.ndarray] = {}
_skipped_length_mismatch = 0
_last_mismatch: Optional[dict] = None


def _as_mask(values) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    return arr


def apply_masks(masks: Mapping[str, object]) -> dict[str, int]:
    """Install the COMPLETE set of masks, replacing whatever was there.

    Whole-set replacement rather than per-virtual edits is deliberate: the
    caller (a room-effect tick) computes every driven virtual's mask
    together from one field evaluation, and a stale leftover entry for a
    virtual that has stopped being driven would keep dimming it forever.
    Returns {virtual_id: length} for what was installed."""
    clean: dict[str, np.ndarray] = {}
    for vid, values in (masks or {}).items():
        if not vid or values is None:
            continue
        arr = _as_mask(values)
        if arr.size == 0:
            continue
        clean[str(vid)] = arr
    with _lock:
        _masks.clear()
        _masks.update(clean)
    return {vid: int(arr.size) for vid, arr in clean.items()}


def set_mask(virtual_id: str, values) -> None:
    """Install or drop ONE virtual's mask (`None` drops it)."""
    with _lock:
        if values is None:
            _masks.pop(virtual_id, None)
            return
        arr = _as_mask(values)
        if arr.size == 0:
            _masks.pop(virtual_id, None)
        else:
            _masks[virtual_id] = arr


def mask_for(virtual_id: str) -> Optional[np.ndarray]:
    """This virtual's mask, or None. The empty-map short-circuit is the hot
    path — every rendered frame of every virtual calls this."""
    if not _masks:                       # the overwhelmingly common case
        return None
    return _masks.get(virtual_id)


def note_length_mismatch(virtual_id: str, mask_len: int, frame_len: int) -> None:
    """Record a mask that did not fit the frame it was handed. Called from
    the one application point; kept here so the counter and the map live
    together and `fx/virtuals.py`'s deviation stays two lines."""
    global _skipped_length_mismatch, _last_mismatch
    _skipped_length_mismatch += 1
    _last_mismatch = {"virtual_id": virtual_id, "mask": mask_len,
                      "frame": frame_len}


def lengths() -> dict[str, int]:
    with _lock:
        return {vid: int(arr.size) for vid, arr in _masks.items()}


def stats() -> dict:
    return {"masked_virtuals": sorted(_masks),
            "lengths": lengths(),
            "skipped_length_mismatch": _skipped_length_mismatch,
            "last_mismatch": _last_mismatch}


def clear() -> None:
    """Forget every mask (a run stopping, tests, the live stack going down)."""
    with _lock:
        _masks.clear()
