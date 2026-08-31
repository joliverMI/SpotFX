"""EMITTER ENUMERATION — how one capture run decides WHAT counts as an
emitter, at the granularity chosen for that run.

HIS OWN CORRECTION, verbatim, and the reason this module exists: "A single
device that spans the direction of the wave should be able to show the
effect. the tv mapper is wrapped around a tv. It should be able to run a
dimness wave vertically." The first slice fenced an emitter to a whole
DEVICE, so a wave over a strip wrapped round a television could only ever
dim the whole television at once. His original spec had said "individual
and grouped leds" all along.

WHAT AN EMITTER IS NOW: a device, OR a contiguous PIXEL RANGE of one of
that device's virtuals. `EmitterFootprint.emitter_id` was always opaque
(spectra/models/room_map.py's docstring says so, and says a per-segment
granularity is a NEW ID SHAPE rather than a rewrite) — so nothing about
the map schema, the derivation, `per_emitter_scalar` or the pages changes
here. Only the enumeration is new, and the two things it needs to name:

  device granularity   emitter_id == the device id, `ranges` empty.
                       BYTE-IDENTICAL to the shipped slice, including the
                       stored id, so every footprint already captured keeps
                       working and re-mapping is not required.
  sub-device           emitter_id == f"{device}:seg{n}[{start}-{end}]",
                       `ranges` naming (virtual_id, start, end).

THE GUARDRAIL THAT DOES NOT MOVE. A range is an ADDRESSING FACT read out
of the virtual's own segment configuration — the same kind of fact
`virtual_ids` already was — and it is indices into that virtual's effect
pixel buffer. It is NEVER a position in the room. Nothing in this module,
or anything it feeds, stores or derives a coordinate, a metre, or a
fixture location; where a range's light LANDS is still measured with a
camera and nothing else. If a change here starts computing where a
segment physically is, it has left the design.

THE THREE GRANULARITIES, and the fourth word that picks between them:

  "device"    one emitter per device (the shipped behaviour)
  "segment"   one emitter per CONFIGURED SEGMENT of each of the device's
              virtuals — the addressing the config already carries. A
              TV wrap is usually four runs; a strip built as one segment
              is one emitter, which is why "block" exists too.
  "block"     one emitter per BLOCK of `block_pixels` consecutive effect
              pixels. The granularity that subdivides regardless of how
              the config happens to be segmented — the one that gives a
              wrapped TV a real vertical resolution.
  "auto"      per device: "device" for a fixture whose virtuals are a
              single point of light (Hue bulbs, one-pixel virtuals) and
              for anything that cannot be lit in parts (below), "segment"
              for everything else. This is the shipped default and is
              exactly his "default segment for strips, device for Hue" —
              resolved PER DEVICE at enumeration time, never a global
              setting.

WHAT CANNOT BE SPLIT, and is reported rather than silently mapped whole:

  * a COPY-mapping virtual renders one segment's worth of pixels and
    copies it to every segment, so "light segment 2 alone" is not a thing
    that exists there — every segment would light. Such a virtual is
    enumerated whole.
  * a virtual with one effect pixel has nothing to divide.

PIXEL SPACE. Ranges are in the virtual's EFFECT pixel space — what an
effect renders into and what `Virtual.assemble_frame` returns, which is
`ceil(pixel_count / grouping)`. That is the same space
`fx/effects/pixelRange.py` lights and the same space
`fx/virtual_gain_mask.py`'s mask is indexed by, so the capture and the
render path address the identical pixels with no conversion between them.
Gap-device segments still occupy their pixels in that buffer (the fork's
`_segments_by_device` advances `data_start` through them), so this module
walks them the same way rather than compacting them out.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from spectra.models.room_map import PixelRange

logger = logging.getLogger(__name__)

GRANULARITIES = ("auto", "device", "segment", "block")
DEFAULT_GRANULARITY = "auto"
#: The default block size, in effect pixels. Chosen so a 560-pixel TV wrap
#: comes out around 19 emitters (~75 s of mapping) rather than 560 — a
#: capture run costs about four seconds per emitter, so the block size is
#: really a trade between vertical resolution and how long he stands still.
DEFAULT_BLOCK_PIXELS = 30
MIN_BLOCK_PIXELS = 1
MAX_BLOCK_PIXELS = 4096
#: Per emitter, on top of the four protocol waits: opening this emitter's
#: own hold (a snapshot read) and reverting it afterwards. Measured against
#: the shipped copy's "about four seconds per fixture", not tuned.
HOLD_OVERHEAD_S = 0.6
#: A hard ceiling on emitters per RUN. Not a tuning knob: at ~4 s each,
#: 120 emitters is already eight minutes of a dark room, and anything past
#: that is a mis-set block size rather than an intention.
MAX_EMITTERS_PER_RUN = 120
#: Device types whose "pixels" are a single lamp — "auto" never splits one.
POINT_DEVICE_TYPES = frozenset({"hue"})


# `PixelRange` is the STORED model's own type (spectra/models/room_map.py),
# imported rather than redefined: a second definition of the same three
# fields is exactly the "defined twice" drift this codebase has been bitten
# by before, and it would need a conversion at every hand-off between the
# enumeration and the footprint it produces.


@dataclass(frozen=True)
class Emitter:
    """One thing a capture run lights on its own.

    `ranges` EMPTY means the whole of every virtual in `virtual_ids` — the
    device-granularity case, and the shape every already-stored footprint
    has."""
    emitter_id: str
    device_id: str
    label: str
    virtual_ids: list[str] = field(default_factory=list)
    ranges: list[PixelRange] = field(default_factory=list)
    note: str = ""

    @property
    def whole_device(self) -> bool:
        return not self.ranges


# ── reading the live virtual map ───────────────────────────────────────────

def effective_pixel_count(virtual: dict) -> int:
    """The number of pixels an EFFECT renders for this virtual — the
    fork's own `ceil(pixel_count / group_size)` (fx/virtuals.py), computed
    from the same two fields `GET /api/virtuals` already returns, so no new
    read primitive is needed and the HTTP and in-process transports agree."""
    pixels = int((virtual or {}).get("pixel_count") or 0)
    grouping = ((virtual or {}).get("config") or {}).get("grouping")
    try:
        group = int(grouping)
    except (TypeError, ValueError):
        group = 1
    if group < 1:
        group = 1
    return int(math.ceil(pixels / group)) if pixels > 0 else 0


def _mapping(virtual: dict) -> str:
    return str(((virtual or {}).get("config") or {}).get("mapping") or "span")


def device_segment_ranges(virtual_id: str, virtual: dict,
                          device_id: str) -> list[PixelRange]:
    """The virtual-effect-pixel ranges the CONFIGURED SEGMENTS of
    `device_id` occupy in `virtual_id`'s buffer.

    Mirrors the fork's `Virtual._segments_by_device` walk exactly: every
    segment advances `data_start` by its own width, gap devices included
    (their pixels are rendered and simply not displayed), and only the
    segments naming this device become ranges. Grouping is applied at the
    end, in the same `ceil` the effect buffer itself uses."""
    grouping = ((virtual or {}).get("config") or {}).get("grouping")
    try:
        group = max(1, int(grouping))
    except (TypeError, ValueError):
        group = 1
    total = effective_pixel_count(virtual)
    out: list[PixelRange] = []
    data_start = 0
    for segment in (virtual or {}).get("segments") or []:
        if not isinstance(segment, (list, tuple)) or len(segment) < 3:
            continue
        seg_device, seg_start, seg_end = segment[0], int(segment[1]), int(segment[2])
        width = seg_end - seg_start + 1
        if width <= 0:
            continue
        if seg_device == device_id:
            lo = data_start // group
            hi = (data_start + width - 1) // group
            hi = min(hi, total - 1) if total else hi
            if total and lo <= hi:
                out.append(PixelRange(virtual_id=virtual_id, start=lo, end=hi))
        data_start += width
    return out


def _blocks(virtual_id: str, length: int, block_pixels: int) -> list[PixelRange]:
    """`length` effect pixels cut into blocks of `block_pixels`. The LAST
    block absorbs the remainder rather than being a short one of its own —
    a two-pixel tail emitter would cost a full four-second capture to
    measure almost nothing."""
    if length <= 0:
        return []
    size = max(MIN_BLOCK_PIXELS, min(MAX_BLOCK_PIXELS, int(block_pixels)))
    count = max(1, length // size)
    out: list[PixelRange] = []
    for i in range(count):
        lo = i * size
        hi = (length - 1) if i == count - 1 else (lo + size - 1)
        out.append(PixelRange(virtual_id=virtual_id, start=lo, end=hi))
    return out


def _splittable(virtual: dict) -> tuple[bool, str]:
    """Whether this virtual can be lit in PARTS at all, with the reason it
    cannot when it cannot — reported, never silently mapped whole."""
    if _mapping(virtual) != "span":
        return False, ("this virtual copies one effect onto every segment, so "
                       "a single segment cannot be lit on its own")
    if effective_pixel_count(virtual) <= 1:
        return False, "this virtual is a single point of light"
    return True, ""


def resolve_granularity(granularity: str, device_type: str,
                        virtuals: dict[str, dict]) -> str:
    """"auto" -> the granularity THIS device actually gets. Every other
    value is returned unchanged; an unknown one falls back to the default
    rather than raising, because it arrives off a wire."""
    granularity = (granularity or DEFAULT_GRANULARITY).strip().lower()
    if granularity not in GRANULARITIES:
        granularity = DEFAULT_GRANULARITY
    if granularity != "auto":
        return granularity
    if (device_type or "").lower() in POINT_DEVICE_TYPES:
        return "device"
    if not any(_splittable(v)[0] for v in virtuals.values()):
        return "device"
    return "segment"


# ── the enumeration ────────────────────────────────────────────────────────

def enumerate_device(device_id: str, virtual_ids: Iterable[str],
                     virtuals: dict[str, dict], *,
                     granularity: str = DEFAULT_GRANULARITY,
                     block_pixels: int = DEFAULT_BLOCK_PIXELS,
                     device_type: str = "") -> list[Emitter]:
    """This device's emitters at the chosen granularity.

    `virtuals` is the live `GET /api/virtuals` map. A virtual missing from
    it (inactive, or not rendering) is not enumerated — the run reports
    "nothing to light" for it by name, exactly as it did before."""
    vids = [v for v in dict.fromkeys(virtual_ids) if v in virtuals]
    if not vids:
        return []
    resolved = resolve_granularity(granularity, device_type,
                                   {v: virtuals[v] for v in vids})
    if resolved == "device":
        return [Emitter(emitter_id=device_id, device_id=device_id,
                        label=device_id, virtual_ids=list(vids), ranges=[])]

    ranges: list[PixelRange] = []
    notes: list[str] = []
    whole: list[str] = []
    for vid in vids:
        virtual = virtuals[vid]
        ok, why = _splittable(virtual)
        if not ok:
            whole.append(vid)
            notes.append(f"{vid}: {why}")
            continue
        if resolved == "block":
            ranges.extend(_blocks(vid, effective_pixel_count(virtual),
                                  block_pixels))
        else:
            found = device_segment_ranges(vid, virtual, device_id)
            if not found:
                # A virtual that names this device but whose segment walk
                # produced nothing (a malformed segment list) is mapped
                # whole rather than skipped.
                whole.append(vid)
                notes.append(f"{vid}: no segment of this device found in its "
                             f"configuration")
                continue
            ranges.extend(found)

    out: list[Emitter] = []
    for index, rng in enumerate(ranges):
        out.append(Emitter(
            emitter_id=f"{device_id}:seg{index}[{rng.start}-{rng.end}]",
            device_id=device_id,
            label=f"{device_id} px {rng.start}–{rng.end}",
            virtual_ids=[rng.virtual_id], ranges=[rng]))
    if whole:
        # Whatever could not be split is still ONE emitter covering it, so
        # a mixed device is fully mapped rather than partly.
        out.append(Emitter(
            emitter_id=(device_id if not out else f"{device_id}:whole"),
            device_id=device_id, label=device_id,
            virtual_ids=list(whole), ranges=[],
            note="; ".join(notes)))
    if not out:
        out = [Emitter(emitter_id=device_id, device_id=device_id,
                       label=device_id, virtual_ids=list(vids), ranges=[])]
    return out


@dataclass
class Plan:
    """What a run at this granularity would light, before it lights it."""
    granularity: str
    block_pixels: int
    emitters: list[Emitter] = field(default_factory=list)
    per_device: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def seconds(self) -> float:
        """Roughly how long the room is dark. The four protocol waits are
        read from `room_mapping` itself rather than copied, plus a flat
        HOLD_OVERHEAD_S per emitter for opening and reverting that emitter's
        own hold — which is real (the chain restores the room between every
        emitter) and is what makes the shipped copy say "about four
        seconds per fixture" rather than 3.4."""
        from spectra.services import room_mapping
        per = (room_mapping.DARK_SETTLE_S + room_mapping.DARK_CAPTURE_S +
               room_mapping.LIT_SETTLE_S + room_mapping.LIT_CAPTURE_S +
               HOLD_OVERHEAD_S)
        return round(len(self.emitters) * per, 1)

    def as_dict(self) -> dict:
        return {
            "granularity": self.granularity,
            "block_pixels": self.block_pixels,
            "per_device": self.per_device,
            "count": len(self.emitters),
            "estimated_seconds": self.seconds,
            "truncated": self.truncated,
            "problems": self.problems,
            "emitters": [{"emitter_id": e.emitter_id, "device_id": e.device_id,
                          "label": e.label, "virtual_ids": e.virtual_ids,
                          "ranges": [r.model_dump() for r in e.ranges],
                          "whole_device": e.whole_device, "note": e.note}
                         for e in self.emitters],
        }


def plan_run(device_ids: Iterable[str], virtuals: dict[str, dict],
             virtuals_by_device: dict[str, list[str]],
             device_types: Optional[dict[str, str]] = None, *,
             granularity: str = DEFAULT_GRANULARITY,
             block_pixels: int = DEFAULT_BLOCK_PIXELS) -> Plan:
    """The whole run's emitter list, in the order it will be captured.

    Pure: it reads the live virtual map and the device->virtual mapping the
    caller already resolved, and writes nothing. The Rooms page calls it to
    SHOW him what pressing the button will do (how many emitters, how long
    the room is dark) before he presses it — a nineteen-emitter run is a
    different act from a two-emitter one and he should not discover that
    from a progress bar."""
    types = device_types or {}
    plan = Plan(granularity=(granularity or DEFAULT_GRANULARITY),
                block_pixels=int(block_pixels))
    for device_id in device_ids:
        vids = list(virtuals_by_device.get(device_id) or [])
        live = [v for v in vids if v in virtuals]
        if not live:
            plan.problems.append(
                f"{device_id}: no virtual of this device is rendering right "
                f"now — nothing to light, so nothing to photograph")
            continue
        resolved = resolve_granularity(plan.granularity,
                                       types.get(device_id, ""),
                                       {v: virtuals[v] for v in live})
        plan.per_device[device_id] = resolved
        emitters = enumerate_device(device_id, live, virtuals,
                                    granularity=resolved,
                                    block_pixels=plan.block_pixels,
                                    device_type=types.get(device_id, ""))
        for e in emitters:
            if e.note:
                plan.problems.append(f"{device_id}: {e.note}")
        plan.emitters.extend(emitters)
    if len(plan.emitters) > MAX_EMITTERS_PER_RUN:
        plan.truncated = True
        plan.problems.append(
            f"{len(plan.emitters)} emitters is past the {MAX_EMITTERS_PER_RUN} "
            f"a single run will attempt — raise the block size, or map fewer "
            f"devices at a time")
        plan.emitters = plan.emitters[:MAX_EMITTERS_PER_RUN]
    return plan
