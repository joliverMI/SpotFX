"""EMITTER ENUMERATION — how one capture run decides WHAT counts as an
emitter, at the granularity chosen for that run.

HIS OWN CORRECTION, verbatim, and the reason this module exists: "A single
device that spans the direction of the wave should be able to show the
effect. the tv mapper is wrapped around a tv. It should be able to run a
dimness wave vertically." The first slice fenced an emitter to a whole
DEVICE, so a wave over a strip wrapped round a television could only ever
dim the whole television at once. His original spec had said "individual
and grouped leds" all along.

WHAT AN EMITTER IS: a CARRIER — one genuinely-driven virtual, the thing he
runs effects on — or a contiguous PIXEL RANGE of it.
`spectra/services/carriers.py` is the binding statement for what counts as
a carrier and why the picker asks that question rather than the /devices
page's; this module only enumerates what a run will light.

  whole carrier   emitter_id == the carrier id, `ranges` empty.
  a pixel range   emitter_id == f"{carrier}:blk{n}[{start}-{end}]"
                  (or `seg`), `ranges` naming (virtual_id, start, end).

WHY THE CARRIER IS THE RIGHT KEY, and the thing worth noticing: the
machinery underneath was already carrier-native. The capture lamp
(fx/effects/pixelRange.py) writes into a VIRTUAL's effect buffer and the
render-time gain mask (fx/virtual_gain_mask.py) is indexed by that same
buffer, so nothing here had to be "delayered" — enumerating per carrier is
the enumeration agreeing with the layer beneath it. It also spans fixtures
for free: his tv-mapper reaches a backlight and both sconces as ONE
continuous run of pixels, which is what makes a wave along it possible at
all, and what a device-keyed enumeration could never express.

THE GUARDRAIL THAT DOES NOT MOVE. A range is an ADDRESSING FACT read out
of the virtual's own segment configuration — the same kind of fact
`virtual_ids` already was — and it is indices into that virtual's effect
pixel buffer. It is NEVER a position in the room. Nothing in this module,
or anything it feeds, stores or derives a coordinate, a metre, or a
fixture location; where a range's light LANDS is still measured with a
camera and nothing else. If a change here starts computing where a
segment physically is, it has left the design.

THE THREE GRANULARITIES, and the fourth word that picks between them:

  "whole"     one emitter per carrier ("device" is accepted as the
              pre-carrier wire word for it).
  "segment"   one emitter per CONFIGURED SEGMENT of the carrier — the
              addressing the config already carries. A TV wrap is usually
              four runs; a strip built as one segment is one emitter,
              which is why "block" exists too.
  "block"     one emitter per BLOCK of `block_pixels` consecutive effect
              pixels. The granularity that subdivides regardless of how
              the config happens to be segmented — the one that gives a
              wrapped TV a real vertical resolution.
  "auto"      per carrier: "whole" for a carrier whose whole chain is
              single lamps (Hue bulbs) or that cannot be lit in parts
              (below), "segment" for everything else. This is the shipped
              default and is exactly his "default segment for strips,
              device for Hue" — resolved PER CARRIER at enumeration time,
              never a global setting.

WHAT CANNOT BE SPLIT, and is reported rather than silently mapped whole:

  * a COPY-mapping virtual renders one segment's worth of pixels and
    copies it to every segment, so "light segment 2 alone" is not a thing
    that exists there — every segment would light. Such a carrier is
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

GRANULARITIES = ("auto", "whole", "segment", "block")
#: The pre-carrier wire word for "whole". Accepted, never emitted — a saved
#: room and an open page both carry it.
GRANULARITY_ALIASES = {"device": "whole"}
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

#: Device types that put no light into the room. A dummy is a real,
#: load-bearing entry in his config (the crystal's mapper chain, the radial
#: dummy) — it just does not emit.
NON_EMITTING_DEVICE_TYPES = frozenset({"dummy"})


def emits_light(device) -> bool:
    """Whether a camera could see this FIXTURE — the ONE place a new
    non-physical type joins the decision.

    Used as the CHAIN-LEVEL sub-check of the mapping picker's own question,
    which is about carriers rather than fixtures (spectra/services/
    carriers.py): a carrier is offered when it is genuinely driven AND its
    chain reaches at least one device this returns True for.

    NOT the same question as `device_usage`'s `in_use`. That list answers
    "does this back something driven" — the right question for the /devices
    page and the WRONG one for a picker that asks "what do I address that a
    camera can see". A dummy backs real virtuals and is genuinely in use,
    yet emits nothing; a carrier whose whole chain is dummies is
    unphotographable BY CONSTRUCTION, not merely untidy. One list, two
    different questions — so the /devices page keeps the other answer,
    unfiltered.

    Accepts a device entry dict or a bare type string."""
    if isinstance(device, str):
        device_type = device
    else:
        device_type = (device or {}).get("type") or ""
    return str(device_type).strip().lower() not in NON_EMITTING_DEVICE_TYPES


# `PixelRange` is the STORED model's own type (spectra/models/room_map.py),
# imported rather than redefined: a second definition of the same three
# fields is exactly the "defined twice" drift this codebase has been bitten
# by before, and it would need a conversion at every hand-off between the
# enumeration and the footprint it produces.


@dataclass(frozen=True)
class Emitter:
    """One thing a capture run lights on its own.

    `ranges` EMPTY means the whole carrier."""
    emitter_id: str
    carrier_id: str
    label: str
    virtual_ids: list[str] = field(default_factory=list)
    ranges: list[PixelRange] = field(default_factory=list)
    note: str = ""

    @property
    def whole_carrier(self) -> bool:
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


def carrier_segment_ranges(carrier_id: str, virtual: dict) -> list[PixelRange]:
    """The effect-pixel ranges this CARRIER's configured segments occupy in
    its own buffer — one range per segment, in configuration order.

    Mirrors the fork's `Virtual._segments_by_device` walk exactly: every
    segment advances `data_start` by its own width, gap devices included
    (their pixels are rendered and simply not displayed). Keying on the
    carrier rather than on one device is what lets a wave run along the
    whole of a strip that spans three fixtures — his tv-mapper — instead of
    only the part one fixture happens to back. Grouping is applied at the
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
        seg_start, seg_end = int(segment[1]), int(segment[2])
        width = seg_end - seg_start + 1
        if width <= 0:
            continue
        lo = data_start // group
        hi = (data_start + width - 1) // group
        hi = min(hi, total - 1) if total else hi
        if total and lo <= hi:
            out.append(PixelRange(virtual_id=carrier_id, start=lo, end=hi))
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


def usable_segments(virtual: dict) -> int:
    """How many CONFIGURED segments this carrier actually has, by the same
    walk `carrier_segment_ranges` uses — so "segments would give one piece"
    is answered by the enumeration itself and never by a second count that
    could disagree with it."""
    return len(carrier_segment_ranges("_", virtual))


def resolve_granularity(granularity: str, virtual: dict,
                        point: bool = False) -> str:
    """"auto" -> the granularity THIS carrier actually gets. Every other
    value is returned unchanged; an unknown one falls back to the default
    rather than raising, because it arrives off a wire.

    `point` says every fixture in this carrier's chain is a single lamp (a
    Hue bulb): "auto" never splits one.

    THE SINGLE-SEGMENT STRIP (found on his own first real run, 2026-08-31):
    "segments for a strip" collapses to ONE emitter whenever the strip is
    configured as a single segment — which his TV wrap is. That is the exact
    case the whole granularity feature exists to avoid: one emitter cannot
    show a wave travelling along anything. So "auto" resolves a splittable,
    multi-pixel carrier with fewer than two segments to BLOCK, which is the
    granularity that subdivides regardless of how the config happens to be
    segmented. An explicit choice is still never overridden."""
    granularity = (granularity or DEFAULT_GRANULARITY).strip().lower()
    granularity = GRANULARITY_ALIASES.get(granularity, granularity)
    if granularity not in GRANULARITIES:
        granularity = DEFAULT_GRANULARITY
    if granularity != "auto":
        return granularity
    if point:
        return "whole"
    if not _splittable(virtual)[0]:
        return "whole"
    if usable_segments(virtual) < 2:
        return "block"
    return "segment"


# ── the enumeration ────────────────────────────────────────────────────────

def enumerate_carrier(carrier_id: str, virtual: dict, *,
                      granularity: str = DEFAULT_GRANULARITY,
                      block_pixels: int = DEFAULT_BLOCK_PIXELS,
                      point: bool = False) -> list[Emitter]:
    """This CARRIER's emitters at the chosen granularity, in its OWN effect
    pixel space.

    That space is the native one for both ends of this feature already: the
    capture lamp (fx/effects/pixelRange.py) renders into a virtual's effect
    buffer, and the render-time gain mask (fx/virtual_gain_mask.py) is
    indexed by it. Enumerating per carrier therefore spans every fixture the
    carrier fans out to — his tv-mapper's backlight and both sconces are one
    continuous run of pixels, which is what makes a wave along it possible
    at all."""
    if not virtual:
        return []
    resolved = resolve_granularity(granularity, virtual, point)
    if resolved == "whole":
        return [Emitter(emitter_id=carrier_id, carrier_id=carrier_id,
                        label=carrier_id, virtual_ids=[carrier_id], ranges=[])]

    ok, why = _splittable(virtual)
    if not ok:
        return [Emitter(emitter_id=carrier_id, carrier_id=carrier_id,
                        label=carrier_id, virtual_ids=[carrier_id], ranges=[],
                        note=why)]
    if resolved == "block":
        kind = "blk"
        ranges = _blocks(carrier_id, effective_pixel_count(virtual),
                         block_pixels)
    else:
        kind = "seg"
        ranges = carrier_segment_ranges(carrier_id, virtual)
        if not ranges:
            # A carrier whose segment walk produced nothing (a malformed
            # segment list) is mapped whole rather than skipped.
            return [Emitter(emitter_id=carrier_id, carrier_id=carrier_id,
                            label=carrier_id, virtual_ids=[carrier_id],
                            ranges=[],
                            note="no usable segment found in this carrier's "
                                 "configuration")]
    return [Emitter(emitter_id=f"{carrier_id}:{kind}{i}[{r.start}-{r.end}]",
                    carrier_id=carrier_id,
                    label=f"{carrier_id} px {r.start}–{r.end}",
                    virtual_ids=[carrier_id], ranges=[r])
            for i, r in enumerate(ranges)]


@dataclass
class Plan:
    """What a run at this granularity would light, before it lights it."""
    granularity: str
    block_pixels: int
    emitters: list[Emitter] = field(default_factory=list)
    per_carrier: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    #: What this run WILL do that he may not have meant — distinct from a
    #: problem, which is something it declined to do. Today's one member is
    #: the single-piece map that cannot show a wave travelling.
    warnings: list[str] = field(default_factory=list)
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
            "per_carrier": self.per_carrier,
            "count": len(self.emitters),
            "estimated_seconds": self.seconds,
            "truncated": self.truncated,
            "problems": self.problems,
            "warnings": self.warnings,
            "emitters": [{"emitter_id": e.emitter_id, "carrier_id": e.carrier_id,
                          "label": e.label, "virtual_ids": e.virtual_ids,
                          "ranges": [r.model_dump() for r in e.ranges],
                          "whole_carrier": e.whole_carrier, "note": e.note}
                         for e in self.emitters],
        }


def plan_run(carrier_ids: Iterable[str], virtuals: dict[str, dict],
             carrier_devices: Optional[dict[str, list[dict]]] = None, *,
             granularity: str = DEFAULT_GRANULARITY,
             block_pixels: int = DEFAULT_BLOCK_PIXELS) -> Plan:
    """The whole run's emitter list, in the order it will be captured.

    Pure: it reads the live virtual map and the carrier->devices chain the
    caller already resolved, and writes nothing. The Rooms page calls it to
    SHOW him what pressing the button will do (how many emitters, how long
    the room is dark) before he presses it — a nineteen-emitter run is a
    different act from a two-emitter one and he should not discover that
    from a progress bar.

    THE BACKSTOP: a carrier whose chain reaches no light-emitting fixture is
    SKIPPED and NAMED. The picker already declines to offer one
    (spectra/services/carriers.py), so this only ever fires for a room saved
    before that filter, or for a chain that has since been re-wired — either
    way it is stated in the run's own problems, never silently dropped."""
    chains = carrier_devices or {}
    plan = Plan(granularity=(granularity or DEFAULT_GRANULARITY),
                block_pixels=int(block_pixels))
    for carrier_id in carrier_ids:
        chain = chains.get(carrier_id)
        if chain is not None and not any(emits_light(d) for d in chain):
            names = ", ".join(str(d.get("id")) for d in chain) or "nothing"
            plan.problems.append(
                f"{carrier_id}: nothing in this carrier's chain emits light "
                f"({names}), so there is nothing for a camera to see — "
                f"skipped")
            continue
        virtual = virtuals.get(carrier_id)
        if not virtual:
            plan.problems.append(
                f"{carrier_id}: this carrier is not rendering right now — "
                f"nothing to light, so nothing to photograph")
            continue
        point = bool(chain) and all(
            str(d.get("type") or "").lower() in POINT_DEVICE_TYPES
            for d in chain if emits_light(d))
        resolved = resolve_granularity(plan.granularity, virtual, point)
        plan.per_carrier[carrier_id] = resolved
        emitters = enumerate_carrier(carrier_id, virtual,
                                     granularity=resolved,
                                     block_pixels=plan.block_pixels,
                                     point=point)
        for e in emitters:
            if e.note:
                plan.problems.append(f"{carrier_id}: {e.note}")
        # ONE PIECE IS NOT A MAP OF A STRIP. Said at plan time, before the
        # room goes dark for a run whose result cannot drive a wave.
        if len(emitters) == 1 and effective_pixel_count(virtual) > 1:
            from spectra.services import mapping_refusals
            plan.warnings.append(mapping_refusals.one_piece_warning(
                carrier_id, effective_pixel_count(virtual), plan.block_pixels,
                splittable=_splittable(virtual)[0]))
        plan.emitters.extend(emitters)
    if len(plan.emitters) > MAX_EMITTERS_PER_RUN:
        plan.truncated = True
        plan.problems.append(
            f"{len(plan.emitters)} emitters is past the {MAX_EMITTERS_PER_RUN} "
            f"a single run will attempt — raise the block size, or map fewer "
            f"carriers at a time")
        plan.emitters = plan.emitters[:MAX_EMITTERS_PER_RUN]
    return plan
