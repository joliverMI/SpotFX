"""THE ROOM LIGHT-FIELD MAP — what each emitter's light DOES to the room,
never where its LEDs are.

THE ONE IDEA, his own sentence, and the reason this file exists: "the map
not necessarily know where the LEDs are, but where they shine." Every
field below is a MEASUREMENT of light landing in a room as a camera saw
it. Nothing here is, or may become, a fixture coordinate, an LED index, a
pixel position, or a metre. If a future change starts solving for where a
strip physically is, it has left this design — the whole point is that a
sconce's spill onto the ceiling and the floor is captured for free by
photographing what it lights, and a coordinate model would throw exactly
that away.

WHAT IS STORED, per emitter (spectra/services/light_field.py derives it):

  footprint      GRID_H x GRID_W (36x64) relative luminance, 0..1, in
                 CAMERA SPACE. "Relative" is load-bearing: a phone cannot
                 give absolute units, so these numbers are only ever
                 compared against OTHER footprints from the SAME pose and
                 the SAME locked exposure — which is what capture_ctx
                 records, and why an unlocked exposure is refused outright
                 rather than silently producing a map that re-scaled
                 mid-run.
  axis_profile   the footprint collapsed onto the room's own axis (floor ->
                 ceiling for the slice), AXIS_BINS long. A projection of
                 the same measurement, not a second one.
  weight         the footprint's total relative luminance — "how much light
                 this fixture lands in this room", the free input for the
                 later brightness-balancing idea.
  capture_ctx    pose id, exposure/white-balance lock state, timestamps,
                 and the honesty flags (saturation, frame counts). A
                 footprint is comparable ONLY to others carrying the same
                 pose id and a locked exposure; this is what lets a reader
                 tell.

DEVICE GRANULARITY ONLY in this slice: one emitter == one device (his two
sconces are two emitters). `EmitterFootprint.emitter_id` is the device id
and `virtual_ids` records which virtuals were lit to produce it, so a
later per-segment granularity is a NEW emitter id shape, not a rewrite of
this one.

THE AXIS IS TWO TAPS, NOT A COORDINATE SYSTEM. AxisCalibration is two
points a human tapped on the capture screen — "that's the floor", "that's
the ceiling" — in normalized frame coordinates. Projection onto the
floor->ceiling vector gives every footprint sample an axis position in
0..1. That is a direction in the camera's own image, deliberately not a
metric height: the slice's fence excludes metric coordinates, and a
travelling wave only ever needs an ordering along a direction.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# The stored grid. 64x36 is 16:9, matching the ~320x180 greyscale frames the
# phone uploads: one grid cell is a 5x5 block of frame pixels, so the
# downsample is an exact box mean with nothing left over.
GRID_W = 64
GRID_H = 36
#: Bins in the axis projection. Coarser than the grid on purpose — the axis
#: profile is a 1-D summary for reading and for the axis fields, never the
#: thing an effect samples (that is the full 2-D footprint, which is WHY the
#: grid is stored and not just this).
AXIS_BINS = 32


class Point(BaseModel):
    """A point in NORMALIZED CAMERA-FRAME coordinates: x 0..1 left->right,
    y 0..1 top->bottom. Not metres, not a room coordinate — where it landed
    in the picture."""
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class AxisCalibration(BaseModel):
    """The room's chosen effect axis, as two taps on the capture screen.
    `floor` is axis position 0.0 and `ceiling` is 1.0; every footprint
    sample's axis position is its projection onto that vector, clipped to
    [0, 1]. Vertical is the slice's case (the two taps sit one above the
    other) but the projection is general, so no second code path is needed
    when a horizontal axis is asked for."""
    kind: str = "vertical"
    floor: Optional[Point] = None
    ceiling: Optional[Point] = None

    @property
    def calibrated(self) -> bool:
        if self.floor is None or self.ceiling is None:
            return False
        return (self.floor.x, self.floor.y) != (self.ceiling.x, self.ceiling.y)


class CaptureContext(BaseModel):
    """Honesty metadata — the reason a reader can tell whether two
    footprints may be compared at all.

    `pose_id` changes whenever the phone moves (a new mapping run gets a
    new one); `exposure_locked`/`white_balance_locked` record what the
    browser actually confirmed, not what was requested. A run cannot even
    start without both locked (spectra/services/mapping_session.py refuses
    by name), so a stored False means the record predates that gate or was
    written by a test — either way, do not compare it."""
    pose_id: str = ""
    exposure_locked: bool = False
    white_balance_locked: bool = False
    exposure_mode: str = ""
    white_balance_mode: str = ""
    captured_at: float = Field(default_factory=time.time)
    dark_frames: int = 0
    lit_frames: int = 0
    #: fraction of LIT frame pixels at the camera's ceiling (255). Anything
    #: above a few percent means the footprint's bright core is clipped and
    #: its SHAPE is still usable while its WEIGHT understates the fixture.
    saturated_fraction: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    notes: str = ""


class EmitterFootprint(BaseModel):
    """One emitter's measured light field. `grid` is row-major
    GRID_H x GRID_W (see module docstring); it is stored as a flat list so
    the JSON stays one line per emitter rather than 36 nested arrays."""
    emitter_id: str                      # device id, this slice's granularity
    label: str = ""
    virtual_ids: list[str] = Field(default_factory=list)
    grid: list[float] = Field(default_factory=list)
    axis_profile: list[float] = Field(default_factory=list)
    weight: float = 0.0
    capture: CaptureContext = Field(default_factory=CaptureContext)

    @field_validator("grid")
    @classmethod
    def _grid_shape(cls, v: list[float]) -> list[float]:
        if v and len(v) != GRID_W * GRID_H:
            raise ValueError(
                f"footprint grid must be {GRID_H}x{GRID_W} = {GRID_W * GRID_H} "
                f"values (got {len(v)})")
        return v

    @property
    def mapped(self) -> bool:
        return bool(self.grid) and self.weight > 0.0


class RoomMap(BaseModel):
    """One room: a name, the devices it contains, its axis calibration, and
    whatever footprints have been captured so far. A device listed in
    `device_ids` with no footprint is simply NOT MAPPED YET — the Room
    Builder shows that state rather than hiding it."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    device_ids: list[str] = Field(default_factory=list)
    axis: AxisCalibration = Field(default_factory=AxisCalibration)
    footprints: list[EmitterFootprint] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)

    def footprint(self, emitter_id: str) -> Optional[EmitterFootprint]:
        for f in self.footprints:
            if f.emitter_id == emitter_id:
                return f
        return None

    def mapped_ids(self) -> list[str]:
        return [f.emitter_id for f in self.footprints if f.mapped]

    def unmapped_ids(self) -> list[str]:
        mapped = set(self.mapped_ids())
        return [d for d in self.device_ids if d not in mapped]

    def put_footprint(self, fp: EmitterFootprint) -> None:
        self.footprints = [f for f in self.footprints
                           if f.emitter_id != fp.emitter_id] + [fp]
        self.updated_at = time.time()
