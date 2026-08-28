"""PER-DEVICE FLUSH DELAY — the one place a device's frames are held back
(SpotFX-authored; not fork code).

The owner's report: "Different devices seem to have different network and
physical latencies... Let's add an ability to tune the per device settings
so that they are timed equally. Maybe each device needs a timing offset
(stick with the convention that negative is that it fires earlier)."

WHAT THIS MODULE IS. A process-global map from device id to a NON-NEGATIVE
delay in seconds, plus the arithmetic that derives it from his authored
offsets. It is deliberately dumb and dependency-free: `fx/` is the shared
library, so it may not import anything under `spectra/` — SPECTRA owns the
stored offsets (spectra/services/device_settings.py) and PUSHES them in
here via apply_offsets(). Nothing in fx/ reads a store.

THE ARITHMETIC, AND WHY IT IS A DELAY AND NOT AN ADVANCE.

    delay_i = offset_i - min_j(offset_j)          (>= 0 by construction)

A fixture can only be made to WAIT. Nothing can send a frame to a light
before the renderer has drawn it, so "device A fires earlier" is only ever
implementable as "every other device fires later". Subtracting the minimum
offset is exactly that translation, and it has the property the owner's
sign convention needs: the RELATIVE spacing he authored is preserved and
the whole set is anchored so the earliest device is never delayed at all.

    all offsets equal (including the shipped all-zero default)
        => every delay is 0 => the flush path is byte-identical to before
           this module existed. Asserted, not claimed:
           tests/test_device_timing_landing.py.

SIGN FAMILY — OFFSET, NOT LEAD. `timing_offset_ms` is OFFSET family:
NEGATIVE = fires EARLIER, positive = fires later, 0 = unchanged. Same
convention (and the same word) as FlareKind.trigger_offset_ms,
SceneV2.trigger_offset_ms and SpectraTrigger.trigger_offset_ms. It is NOT
the LEAD family (RoomControlState.av_sync_lead_ms, positive = earlier).
The two families are never added with the same sign anywhere — see
docs/SPECTRA_TIMING_CONVENTIONS.md, which carries this quantity's own row.

RELATIVE ONLY. This never moves the room as a whole: the minimum-offset
device is always delayed by exactly 0, so the fastest light keeps landing
where it lands today and the others are slowed to meet it. Absolute
alignment of the WHOLE room against the sound remains the job of the room
lead (RoomControlState.av_sync_lead_ms, applied once at the trigger poll in
spectra/services/engine.py) — untouched by this module and by everything it
feeds.

THE CLOCK is injectable (`set_clock`) for exactly one reason: the landing
instrument steps the renderer under a fake clock and must be able to move
the flush deadline with it. Production never calls it.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Mapping

# The delay a single device can be asked to hold, in ms. Derived, not
# tuned: SPECTRA clamps each authored offset to +/- OFFSET_LIMIT_MS, so the
# widest spread two devices can express is twice that.
OFFSET_LIMIT_MS = 1000
MAX_DELAY_MS = 2 * OFFSET_LIMIT_MS

# Hard ceiling on frames held per device, so a mis-set delay can never grow
# an unbounded queue of pixel arrays. At 60 fps, MAX_DELAY_MS is 120 frames;
# this leaves headroom and still bounds the memory. Overflow releases the
# OLDEST frame immediately (the delay degrades, the stream never stalls).
MAX_BUFFERED_FRAMES = 256

_lock = threading.Lock()
_offsets: dict[str, int] = {}
_delays: dict[str, float] = {}
_clock: Callable[[], float] = time.monotonic


def apply_offsets(offsets: Mapping[str, int]) -> dict[str, float]:
    """Install his authored per-device offsets (ms, OFFSET family) and
    return the derived per-device delays (seconds, >= 0).

    The caller decides WHICH devices participate — the minimum is taken
    over exactly the keys handed in, so a device absent from the mapping is
    not part of the equalization at all and gets no delay. SPECTRA passes
    the live host's own device ids with 0 filled in for the unset ones
    (spectra/services/device_settings.push_offsets), which is what makes a
    single negative offset delay every OTHER real device rather than
    delaying nothing."""
    clean: dict[str, int] = {}
    for device_id, raw in (offsets or {}).items():
        if not device_id:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        clean[str(device_id)] = max(-OFFSET_LIMIT_MS, min(OFFSET_LIMIT_MS, value))
    base = min(clean.values()) if clean else 0
    delays = {did: (value - base) / 1000.0 for did, value in clean.items()}
    with _lock:
        _offsets.clear()
        _offsets.update(clean)
        _delays.clear()
        _delays.update({did: d for did, d in delays.items() if d > 0.0})
    return delays


def delay_s(device_id: str) -> float:
    """The delay this device's frames are held for, in seconds. 0.0 for a
    device with no entry — the shipped default and the hot path."""
    if not _delays:                      # the overwhelmingly common case
        return 0.0
    return _delays.get(device_id, 0.0)


def offsets() -> dict[str, int]:
    with _lock:
        return dict(_offsets)


def delays_ms() -> dict[str, int]:
    with _lock:
        return {did: int(round(d * 1000)) for did, d in _delays.items()}


def clear() -> None:
    """Forget every offset (tests, and the live stack going down)."""
    with _lock:
        _offsets.clear()
        _delays.clear()


def now() -> float:
    return _clock()


def set_clock(fn: Callable[[], float] | None) -> None:
    """Test seam only — see the module docstring. None restores
    time.monotonic."""
    global _clock
    _clock = fn or time.monotonic
