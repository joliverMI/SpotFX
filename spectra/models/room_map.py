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

GRANULARITY IS A PER-CAPTURE CHOICE (his own correction, 2026-08-31: "A
single device that spans the direction of the wave should be able to show
the effect. the tv mapper is wrapped around a tv. It should be able to run
a dimness wave vertically"). An emitter is a whole CARRIER (one
genuinely-driven virtual) or a contiguous PIXEL RANGE of it;
`spectra/services/emitters.py` owns the enumeration and the id shape, and is
the binding statement for both.

  whole carrier  emitter_id == the carrier id, `ranges` EMPTY.
  a pixel range  emitter_id == "tv-mapper:seg3[90-119]", `ranges` naming
                 (virtual_id, start, end) — the NEW id shape this docstring
                 always said a finer granularity would be.

A RANGE IS AN ADDRESSING FACT, NOT A POSITION. It is indices into the
virtual's own effect pixel buffer, read out of the segment configuration —
the same kind of fact `virtual_ids` already was, and the same kind the
render path uses to apply a per-pixel gain. It is never a coordinate, a
metre, or a place in the room. WHERE that range's light lands is still
measured with a camera and stored as a footprint, exactly as before: this
file's one idea is unchanged, only the size of the thing being photographed.

AN EMITTER THE CAMERA NEVER SAW IS STILL A RECORD (2026-08-31). His first
real map ran 22 emitters and stored 14: the far-side TV blocks and the
sconce spill outside the frame produced ~zero lit-minus-dark and simply did
not appear. Correct physics, silent record — nothing distinguished "never
ran" from "ran, and its light is not in this shot". Such an emitter is now
stored FOOTPRINT-LESS with `unseen=True` and a sentence, counted in the run
summary ("14 mapped, 8 unseen from this pose"). It is a FACT, not an error:
a second pose can see it later.

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

from pydantic import BaseModel, Field, field_validator, model_validator

# The stored grid, and it is UNCHANGED by the 2026-09-01 wire-frame raise.
# 64x36 is 16:9, and every frame size the wire declares
# (`spectra/services/capture_settings.PROFILES`: 320x180 up to 1920x1080) is
# a whole multiple of it — 5x for a map, 30x for the commissioning read — so
# the downsample is an exact box mean with nothing left over at any of them,
# and a grid derived from a 1080p frame is directly comparable with one
# derived from a 320x180 frame of the same scene.
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


class PixelRange(BaseModel):
    """A contiguous, INCLUSIVE range of one virtual's EFFECT pixels — an
    addressing fact from the device configuration, never a position. The
    same index space `fx/effects/pixelRange.py` lights during capture and
    `fx/virtual_gain_mask.py`'s gain mask is indexed by at render, so the
    two address the identical pixels with nothing to convert between."""
    virtual_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @property
    def length(self) -> int:
        return max(0, self.end - self.start + 1)


class EmitterFootprint(BaseModel):
    """One emitter's measured light field. `grid` is row-major
    GRID_H x GRID_W (see module docstring); it is stored as a flat list so
    the JSON stays one line per emitter rather than 36 nested arrays."""
    emitter_id: str                      # opaque: a carrier id, or a range id
    label: str = ""
    virtual_ids: list[str] = Field(default_factory=list)
    #: Which CARRIER (the virtual he runs effects on) this emitter belongs
    #: to. Empty when the emitter id IS the carrier id (whole-carrier
    #: granularity) — `carrier` below is the one place that is resolved.
    carrier_id: str = ""
    #: EMPTY means the whole of every virtual in `virtual_ids` (the
    #: whole-carrier shape). Otherwise the pixel ranges that were lit.
    ranges: list[PixelRange] = Field(default_factory=list)
    grid: list[float] = Field(default_factory=list)
    axis_profile: list[float] = Field(default_factory=list)
    weight: float = 0.0
    capture: CaptureContext = Field(default_factory=CaptureContext)
    #: TRUE when this emitter RAN and the camera saw nothing from that pose
    #: — a footprint-less record, kept deliberately. Before it existed such
    #: an emitter simply did not appear in the store, so nothing
    #: distinguished "never ran" from "ran, and its light is outside the
    #: frame" (his own first real map: 22 ran, 14 stored, 8 vanished). NOT an
    #: error and NOT a warning: a second pose can see it later. `grid` and
    #: `axis_profile` are empty here, so every reader that already gates on
    #: `mapped` skips it exactly as it skipped the absence.
    unseen: bool = False
    #: This emitter was measured TWICE in one run — the second time with an
    #: extended dark settle, after the first came out at ~zero. True on a
    #: MAPPED record too (the retry recovered it), which is what makes the
    #: retry a measurement rather than a guess.
    retried: bool = False
    #: The sentence for whatever this record's state needs saying — today
    #: only the unseen one (spectra/services/mapping_refusals.unseen_note).
    note: str = ""

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

    @property
    def carrier(self) -> str:
        """The carrier this footprint belongs to, for a reader that has only
        the footprint. A whole-carrier record carries no `carrier_id`
        because its emitter id IS the carrier id."""
        return self.carrier_id or self.emitter_id

    @property
    def whole_carrier(self) -> bool:
        return not self.ranges


class RoomMap(BaseModel):
    """One room: a name, the CARRIERS it contains, its axis calibration, and
    whatever footprints have been captured so far. A carrier listed in
    `carrier_ids` with no footprint is simply NOT MAPPED YET — the Room
    Builder shows that state rather than hiding it.

    A CARRIER is a genuinely-driven virtual — the thing he addresses when he
    runs an effect — not a fixture. Four of his seven fan out to several
    fixtures (tv-mapper reaches the backlight and both sconces), so a
    device-keyed room could not name the things he actually calibrates.
    spectra/services/carriers.py is the binding statement for what counts as
    one and why the picker asks that question rather than the /devices
    page's.

    MIGRATION FROM THE DEVICE-KEYED SHAPE: a stored room written before this
    re-key carries `device_ids`, and a device id is not a carrier id — there
    is no faithful conversion, and a footprint measured per device is not a
    carrier's footprint either. Such a room is RESET (its membership and its
    footprints dropped) with `migration_note` saying so, rather than
    silently reinterpreted. His only room was minutes old when this landed;
    a stated reset is honest where a guess would not be."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    carrier_ids: list[str] = Field(default_factory=list)
    axis: AxisCalibration = Field(default_factory=AxisCalibration)
    #: The granularity the page last ran a capture at, remembered so the
    #: control comes back where he left it. NOT a global setting and NOT
    #: what a run uses: every run takes its own granularity as an argument
    #: (his "per-capture choice"), and this only seeds the control.
    granularity: str = "auto"
    block_pixels: int = 30
    footprints: list[EmitterFootprint] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)
    #: Set by the device->carrier migration, and read by the Rooms page so
    #: the reset is something he is TOLD about rather than something he
    #: discovers by finding his room empty.
    migration_note: str = ""

    @model_validator(mode="before")
    @classmethod
    def _migrate_device_keyed(cls, data):
        """A pre-re-key room arrives keyed by device. Reset it, and say so."""
        if not isinstance(data, dict):
            return data
        if "device_ids" not in data or data.get("carrier_ids"):
            data.pop("device_ids", None)
            return data
        legacy = list(data.pop("device_ids") or [])
        if not legacy and not data.get("footprints"):
            return data
        data["carrier_ids"] = []
        data["footprints"] = []
        data["migration_note"] = (
            "This room was mapped by DEVICE before rooms were keyed by the "
            "things you actually run effects on. A device is not a carrier "
            "and its footprints are not a carrier's, so the room was reset "
            "rather than guessed at — pick its carriers and map it again "
            f"(it previously held: {', '.join(legacy) or 'no devices'}).")
        return data

    def footprint(self, emitter_id: str) -> Optional[EmitterFootprint]:
        for f in self.footprints:
            if f.emitter_id == emitter_id:
                return f
        return None

    def unseen_ids(self) -> list[str]:
        """The emitters that RAN and produced no usable light from the pose
        they ran at. Distinct from `unmapped_ids` (carriers nothing has been
        tried on yet) — this is the measured half of the same question."""
        return [f.emitter_id for f in self.footprints if f.unseen]

    def mapped_ids(self) -> list[str]:
        return [f.emitter_id for f in self.footprints if f.mapped]

    def mapped_carriers(self) -> list[str]:
        """The CARRIERS with at least one mapped emitter. Distinct from
        `mapped_ids` since a carrier mapped per segment contributes several
        emitter ids and none of them is the carrier id."""
        return sorted({f.carrier for f in self.footprints if f.mapped})

    def unmapped_ids(self) -> list[str]:
        mapped = set(self.mapped_carriers())
        return [c for c in self.carrier_ids if c not in mapped]

    def emitters_for_carrier(self, carrier_id: str) -> list[EmitterFootprint]:
        return [f for f in self.footprints if f.carrier == carrier_id]

    def drop_carrier_footprints(self, carrier_id: str) -> int:
        """Forget everything measured for one carrier.

        A capture run calls this before mapping that carrier, so a carrier
        always carries footprints from exactly ONE granularity: re-mapping a
        TV per segment must not leave last week's whole-carrier footprint
        beside the new ranges, where both would be driven and the fixture
        would be dimmed twice."""
        before = len(self.footprints)
        self.footprints = [f for f in self.footprints if f.carrier != carrier_id]
        dropped = before - len(self.footprints)
        if dropped:
            self.updated_at = time.time()
        return dropped

    def put_footprint(self, fp: EmitterFootprint) -> None:
        self.footprints = [f for f in self.footprints
                           if f.emitter_id != fp.emitter_id] + [fp]
        self.updated_at = time.time()
