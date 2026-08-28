"""SPECTRA's own per-device record — the settings a device carries that the
vendored LedFX device config has no place for.

ONE FIELD TODAY, by design: `timing_offset_ms`. The shape is a record per
device id, not a bare `{id: int}` map, precisely so the next per-device
quantity the room needs — a position for a 3D map, a brightness or colour
trim — is an ADDED FIELD on this model with a default, not a rewrite of the
store and everything that reads it. Those fields are NOT built here; the
shape is what makes them cheap later.

SIGN LAW (OFFSET family, his own words: "stick with the convention that
negative is that it fires earlier"):

    timing_offset_ms < 0   this device fires EARLIER than the others
    timing_offset_ms > 0   this device fires LATER
    timing_offset_ms == 0  unchanged — the shipped default for every device

Same family and same sign as FlareKind.trigger_offset_ms,
SceneV2.trigger_offset_ms and SpectraTrigger.trigger_offset_ms. It is NOT
the LEAD family (RoomControlState.av_sync_lead_ms, positive = earlier); the
two are never added with the same sign anywhere. See
docs/SPECTRA_TIMING_CONVENTIONS.md.

Only RELATIVE differences between devices are meaningful: the engine
translates the authored set into per-device delays by subtracting the
smallest offset (fx/device_timing.py), so shifting every device by the same
amount changes nothing at all. Aligning the whole room against the sound is
the room lead's job, not this field's.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# A device asked to wait a full second is already far past any real network
# or fixture latency; the clamp exists so a fat-fingered value cannot park a
# fixture seconds behind the room. Mirrored in fx.device_timing.OFFSET_LIMIT_MS.
OFFSET_LIMIT_MS = 1000


class DeviceSettings(BaseModel):
    """SPECTRA's record for one device id. Every field has a default, so a
    device with no stored record and a device with a default record are the
    same thing at the lights."""

    timing_offset_ms: int = Field(
        0, ge=-OFFSET_LIMIT_MS, le=OFFSET_LIMIT_MS,
        description="Negative fires this device EARLIER than the rest of the "
                    "room, positive later, 0 unchanged. Relative only.")

    @property
    def is_default(self) -> bool:
        return self == DeviceSettings()
