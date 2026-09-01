"""THE MAPPING RUN — ONE CONTINUOUS DARK HOLD, one emitter at a time, on
the ONE held-room seam. Never a second hold system.

WHAT A RUN DOES. The room goes dark ONCE, at the start, and stays dark
until the run ends; then, per emitter:

  1. dark write               every live virtual to black (the room is
                              already dark — this re-asserts it, so a lit
                              neighbour can never survive into the next
                              reference by an ordering accident)
  2. settle DARK_SETTLE_S     the write has to actually land (WLED transport
                              plus whatever per-device timing delay is
                              applied) before the reference means anything,
                              and the PREVIOUS emitter's own fade is now the
                              only thing this has to outlast
  3. dark reference           DARK_CAPTURE_S of frames, averaged
  4. light ONE emitter        full white through the one write seam
  5. settle LIT_SETTLE_S      same reason as 2
  6. lit capture              LIT_CAPTURE_S of frames, averaged
  7. derive + store           footprint = lit - dark, clipped, downsampled
                              (spectra/services/light_field.py)

and the hold is released ONCE, when the run ends — however it ends.

WHY IT IS ONE HOLD NOW, AND WAS A CHAIN OF SHORT ONES BEFORE (2026-08-31,
fm/mapping-one-dark-hold). The chain was a real design answer to a real
constraint: `flare_preview_hold.MAX_HOLD_DURATION_S` caps ONE hold at three
minutes, so releasing between emitters kept a run of any length inside it
and made the room genuinely restored — not merely restorable — at every
link. Then the owner watched a twenty-two-emitter run and said it: "it seems
like it keeps releasing the lights to the music frequently... just stay dark
between tests." He was watching the mechanism work as designed, and it was
wrong twice over:

  * his show floods back through the fixtures between every capture, which
    is not what "mapping the room" should look like from the sofa; and,
    worse,
  * EVERY DARK REFERENCE AFTER THE FIRST WAS TAKEN MOMENTS AFTER A RESTORE.
    The show fading back out of the fixtures lands IN the dark frame, so the
    reference comes out too bright and subtracts the next emitter's own
    light away. The chain was contaminating the instrument it existed to
    protect — a plausible contributor to the depressed TV-ring weights in
    his real runs, on top of the firmware-brightness deficit.

THAT CONTAMINATION PATH IS NOW CLOSED BY CONSTRUCTION, not tuned away:
between two captures the room has been dark all along, so the only residual
a dark reference has to outlast is the PREVIOUS EMITTER's own fade — which
is exactly what DARK_SETTLE_S was always for and why it is unchanged.

RESTORABLE AT ANY INSTANT SURVIVES AS THE PROPERTY IT ALWAYS WAS. It was
never the chain that made it true — it is the hold: his Stop, a lapsed
heartbeat, the independent sweep, and restart recovery all still land the
snapshot within seconds. What changed is that STOPPING IS HIS ACT, never
something the run does to itself between emitters.

THE CEILING IS RUN-SCOPED (`run_ceiling_s` below). MAX_HOLD_DURATION_S is
untouched and still governs every preview; a mapping run declares its own on
the hold's first open, derived from the plan's own estimate with a stated
margin, floored and hard-capped. It is computed AT PLAN TIME and shown in
the plan response beside the emitter count — the check-before-the-cost
surface that already exists — and a run whose estimate is past the hard cap
REFUSES there, by name, with nothing written. It never quietly maps fewer
emitters, and it never adjusts his granularity or block size on his behalf:
those are his decisions, and the plan line's job is to price them, not to
correct them.

EVERYTHING HARD IS INHERITED, NOT REBUILT. flare_preview_hold.
open_program_hold owns the snapshot taken once per hold, the deadline that
lapses on its own, the independent sweep that reverts a hold nobody closed,
the ceiling, the persisted snapshot a service restart lands back, and the
1 ms tween-safe revert. This module supplies only what is new: which
virtuals are in scope, what each named step writes, and how long this
particular run is allowed to hold the room. A dropped phone, a closed tab
or a mid-run service restart therefore land in machinery that was already
proven the expensive way (see that module's own docstring).

WHY THE DARK STEP DARKENS EVERY LIVE VIRTUAL, not only the room's own
carriers: a footprint is what a CAMERA sees, so any other fixture still
playing the show lands in the frame and in the difference. The room's
`carrier_ids` decide which emitters get MAPPED; the dark step covers the
whole live room because that is what "with the room dark" means to a
camera. Everything it darkens is in the same snapshot and comes back with
it — the same scope av_sync_pattern.py's own default flash already takes.

GRANULARITY IS A PER-CAPTURE CHOICE, and step 4 is the only thing that
changes with it. A whole-device emitter is lit exactly as before —
`singleColor` full white on every one of its virtuals. A PIXEL-RANGE
emitter is lit with `fx/effects/pixelRange.py`, the measuring instrument
that renders white over a configured range and black elsewhere, on the same
one write seam and inside the same held room. Everything else about the
protocol — the dark reference, the settles, the frame counts, the
derivation — is identical, which is the point: photographing a smaller lamp
is not a second protocol.

SUB-DEVICE CAPTURE NEEDS SPECTRA TO OWN THE LIGHTS, and the run says so
rather than failing at the seam. `pixelRange` is a vendored fx effect that
lives in THIS process; when spot-effects owns the room, writes go out as
HTTP PUTs to the external LedFX service, which has never heard of it. So a
sub-device run is refused by name up front, with nothing written.

WHAT THIS MODULE NEVER DOES: decide anything about fixture positions. It
turns one emitter on, photographs the room, and hands the difference to
light_field.py. A pixel RANGE is an addressing fact from the configuration,
never a position — spectra/services/emitters.py is the binding statement.
If a future change here starts computing where a strip is, it has left the
plan (spectra/models/room_map.py's docstring).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from spectra.models.room_map import CaptureContext, PixelRange, RoomMap
from spectra.models.scene import (SceneColorAssignment, SceneDeviceConfig,
                                  SceneV2)
from spectra.services import emitters as emitters_mod
from spectra.services import (fixture_brightness, flare_preview_hold,
                              light_field, mapping_refusals)
from spectra.services.emitters import Emitter

logger = logging.getLogger(__name__)

#: The write primitive, shared with the AV instrument's flash pattern so
#: "full white through the one write seam" means the same thing in both
#: (av_sync_pattern.PATTERN_EFFECT_TYPE / PATTERN_COLOR).
MAP_EFFECT_TYPE = "singleColor"
#: The range lamp: fx/effects/pixelRange.py, white over a configured range
#: of one virtual's effect pixels and black elsewhere. Registry-exempt on
#: purpose (it is an instrument, not something to author with) — see that
#: module's docstring.
RANGE_EFFECT_TYPE = "pixelRange"
WHITE = "#ffffff"
BLACK = "#000000"
#: Full, not the flash pattern's 0.85: a footprint wants the fixture's real
#: reach, and any clipping it causes is REPORTED (capture.saturated_fraction)
#: rather than avoided by measuring a dimmer fixture than he owns.
LIT_BRIGHTNESS = 1.0
#: 1 ms is fx_executor's JUMP_MS convention — instant, but through the
#: tween-retarget branch, so a dangling glide from the show cannot resume
#: over the top of the write (flare_preview_hold.REVERT_TRANSITION_MS's own
#: reasoning, which applies identically here).
WRITE_TRANSITION_MS = 1

DARK_SETTLE_S = 0.7
DARK_CAPTURE_S = 0.5
LIT_SETTLE_S = 0.7
LIT_CAPTURE_S = 1.5
#: ALL FOUR PROTOCOL WAITS ARE PER-RUN ARGUMENTS WITH BOUNDS, not constants
#: a caller edits — the settles first (a slower run buys a cleaner
#: reference), and the two CAPTURE durations since 2026-08-31, for the
#: overnight speed sweep: a sweep that varies one knob at a time needs all
#: four as honest inputs, or "which of these actually costs the time" is not
#: answerable. The defaults above are unchanged, so an omitted override runs
#: exactly the protocol that shipped.
#:
#: AT A FIXED CAMERA RATE, LIT DWELL AND FRAMES-AVERAGED ARE ONE KNOB, NOT
#: TWO. The phone streams at roughly 5 fps and `mapping_session` averages
#: whatever ARRIVED in the window, so `lit_capture_s` buys frames at about
#: five a second and nothing else: 1.5 s is ~7 frames, 0.6 s is ~3, and
#: MIN_FRAMES (2) is the floor below which an emitter is reported unmapped
#: rather than averaged from one frame. So shortening the capture and
#: "averaging fewer frames" are the SAME change described two ways —
#: there is no second knob that keeps the dwell and drops the frames, and
#: anyone reading a sweep must not count them as independent variables.
MIN_SETTLE_S = 0.1
MAX_SETTLE_S = 10.0
#: The capture window's own bounds. The floor is deliberately above one
#: frame interval at ~5 fps: below it MIN_FRAMES can never be met and every
#: emitter would come back unmapped, which is a broken run, not a fast one.
MIN_CAPTURE_S = 0.25
MAX_CAPTURE_S = 10.0
#: THE WEIGHT-ZERO RETRY (his own design, 2026-08-31). An emitter measured
#: at ~zero gets ONE more capture later in the same run with a dark settle
#: this many times longer, before it is recorded unseen.
#:
#: THE DATA BEHIND IT: the zero blocks in his first real map are SCATTERED
#: (blocks 2, 3, 5, 8 and 11, with SEEN neighbours either side) — not the
#: contiguous far side of a wrap, which is what "outside the frame" would
#: look like. A scattered zero next to a seen neighbour is far better
#: explained by the PREVIOUS emitter's WLED fade still dying away into this
#: emitter's dark reference: the reference comes out too bright, the
#: difference clips to nothing, and the emitter reads as invisible. A longer
#: dark settle is exactly the discriminating measurement — it removes that
#: one explanation and nothing else. Whichever way the retry lands, the
#: answer is now measured rather than assumed.
RETRY_DARK_SETTLE_X = 3.0
#: The hold's heartbeat window for a run. The run re-arms it on every step
#: it opens, and a single emitter's dark->lit->capture is ~3.5 s, so this
#: only ever has to outlast one emitter. If the run dies mid-emitter — a
#: crashed task, a killed process's successor, a phone that vanished — the
#: sweep reverts within this + flare_preview_hold.SWEEP_INTERVAL_S with
#: nothing else needing to have run. It is deliberately NOT the run's
#: ceiling: the ceiling bounds a HEALTHY run, this bounds an abandoned one.
HOLD_HEARTBEAT_S = 20.0

# ── THE RUN-SCOPED HOLD CEILING ────────────────────────────────────────────
#
# flare_preview_hold.MAX_HOLD_DURATION_S (three minutes) is right for a
# preview — a person judging one flare — and wrong for a capture run, which
# is now ONE continuous hold and must not release his room half-way through
# a twenty-two-emitter sweep. So a run declares its own ceiling on the
# hold's first open. Three numbers, each doing a different job:
#
#: The margin over the plan's own estimate. A run is never exactly its
#: estimate: a WLED write can be slow, a frame can be late, and the
#: weight-zero retry pass (RETRY_DARK_SETTLE_X above) re-measures whatever
#: read as nothing, which the estimate does not include. 1.5x covers a
#: normal run with a handful of retries; a run in which nearly everything
#: retries can still reach the ceiling, and that is a NAMED, footprint-
#: keeping stop (mapping_refusals.HOLD_CEILING), never a silent one.
RUN_CEILING_MARGIN = 1.5
#: The floor. A two-emitter run estimates ~8 s, and holding it to 12 s would
#: make an ordinary hiccup fatal. Below this the ceiling is not the binding
#: constraint on anything, so it is simply the preview's own three minutes.
RUN_CEILING_FLOOR_S = 180.0
#: The hard cap on ONE continuous hold, whatever the estimate says. Fifteen
#: minutes is already a long time to stand still holding a phone, and a run
#: asking for more is a room to map in two passes, not a bigger number. A
#: plan past this REFUSES (`too_long_refusal`) rather than being truncated:
#: a run that quietly maps fewer emitters than it listed is worse than one
#: that will not start.
RUN_CEILING_HARD_CAP_S = 900.0


def run_ceiling_s(estimate_s: float) -> float:
    """How long ONE mapping run may hold the room, from its plan estimate.

    Computed at PLAN time (spectra/services/emitters.Plan) so it is shown
    beside the emitter count before he presses, and handed to the hold on
    its first open so the number he was shown is the number enforced."""
    try:
        est = float(estimate_s)
    except (TypeError, ValueError):
        est = 0.0
    if est != est or est < 0:                                      # NaN/junk
        est = 0.0
    return round(max(RUN_CEILING_FLOOR_S,
                     min(RUN_CEILING_HARD_CAP_S, est * RUN_CEILING_MARGIN)), 1)


def too_long_refusal(estimate_s: float) -> str:
    """The sentence for a plan past the hard cap, or "" when it fits.

    Checked at plan time AND at the top of a run, because a plan can be
    read on one device and a run started on another — and because a run
    that started must never be the first place he learns the cost."""
    try:
        est = float(estimate_s)
    except (TypeError, ValueError):
        return ""
    if est != est or est * RUN_CEILING_MARGIN <= RUN_CEILING_HARD_CAP_S:
        return ""
    return mapping_refusals.too_long_refusal(est, RUN_CEILING_HARD_CAP_S)
def clamp_seconds(value, default: float, lo: float, hi: float) -> float:
    """A caller's timing override, bounded. Anything unusable falls back to
    the shipped default rather than refusing a run over a stray number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:                                          # NaN
        return default
    return max(lo, min(hi, v))


def clamp_settle(value, default: float) -> float:
    """A caller's SETTLE override, bounded."""
    return clamp_seconds(value, default, MIN_SETTLE_S, MAX_SETTLE_S)


def clamp_capture(value, default: float) -> float:
    """A caller's CAPTURE-WINDOW override, bounded. See the note above
    MIN_CAPTURE_S: this is the frame count, expressed in seconds."""
    return clamp_seconds(value, default, MIN_CAPTURE_S, MAX_CAPTURE_S)


def run_estimate_s(emitter_count: int, dark_settle: float,
                   dark_capture: float, lit_settle: float,
                   lit_capture: float) -> float:
    """Roughly how long the room is dark for a run of this shape.

    ONE definition, called from both places that need it: the plan's own
    `seconds` (with the shipped defaults, which is what the page prices)
    and `run_mapping`, with the four values THIS run was actually given, so
    a sweep at half the dwell is bounded by a ceiling derived from the run
    it is about to do rather than the one it isn't."""
    per = (dark_settle + dark_capture + lit_settle + lit_capture
           + emitters_mod.STEP_OVERHEAD_S)
    return round(max(0, int(emitter_count)) * per
                 + emitters_mod.HOLD_OVERHEAD_S, 1)


#: Frames the average must actually have. Below this the emitter is reported
#: unmapped WITH ITS REASON — never a footprint built from one frame.
MIN_FRAMES = 2


def _entry(vid: str, color: str, brightness: float) -> SceneDeviceConfig:
    return SceneDeviceConfig(
        target_kind="virtual", target=vid, effect_type=MAP_EFFECT_TYPE,
        params={"color": color},
        # "fixed", never "set": a mapping write must not pick up the room's
        # active colour set, which is the whole point of writing white.
        color=SceneColorAssignment(mode="fixed"),
        brightness=brightness, background_brightness=0.0)


def dark_scene(virtual_ids: list[str]) -> SceneV2:
    """The synthetic scene the hold is built on: every in-scope virtual at
    black. Its compiled writes are what the hold snapshots against and what
    the "dark" step lands. Never stored, never named like a real scene."""
    return SceneV2(name="· room mapping (dark) ·",
                   devices=[_entry(v, BLACK, 0.0) for v in virtual_ids])


class MappingProgram(flare_preview_hold.PreviewProgram):
    """Two steps over the ONE hold: take the room dark, then light exactly
    one emitter — a whole virtual, or a range of one virtual's pixels.

    The "lit" step writes the dark set FIRST and the white set second in a
    single apply_scene payload, so a virtual can never be left lit from a
    previous emitter by an ordering accident — the payload is always the
    complete state of every in-scope virtual, not a delta.

    A RANGED emitter is the same step with a different lamp: the lit
    virtual is written `pixelRange` (white over its range, black outside)
    instead of `singleColor`. Every other virtual in scope is still written
    black, so exactly the intended pixels are lit and everything else in
    the room is off — which is what the dark reference is subtracted
    against."""

    steps = ("dark", "lit")

    def __init__(self, virtual_ids: list[str],
                 lit_virtual_ids: Optional[list[str]] = None,
                 ranges: Optional[list[PixelRange]] = None) -> None:
        self.virtual_ids = list(dict.fromkeys(virtual_ids))
        #: The scene the ONE hold is built on, and therefore what its
        #: snapshot covers: every in-scope virtual, for the whole run. It
        #: does not change as emitters go by — which is what lets one
        #: snapshot, taken once, give back everything the run ever touched.
        self.hold_scene = dark_scene(self.virtual_ids)
        self.lit_virtual_ids: list[str] = []
        #: virtual -> the one range lit on it. Absent = the whole virtual.
        self.ranges: dict[str, PixelRange] = {}
        self.select(lit_virtual_ids or [], ranges)

    def select(self, lit_virtual_ids: list[str],
               ranges: Optional[list[PixelRange]] = None) -> None:
        """Point the "lit" step at THIS emitter. One program serves the whole
        run — the room's scope is fixed, only which piece of it is lit
        changes — so selecting is the only thing that happens between two
        captures, and the hold is never disturbed."""
        in_scope = set(self.virtual_ids)
        self.lit_virtual_ids = [v for v in dict.fromkeys(lit_virtual_ids)
                                if v in in_scope]
        self.ranges = {r.virtual_id: r for r in (ranges or [])
                       if r.virtual_id in in_scope}

    def _lit_write(self, vid: str) -> dict:
        rng = self.ranges.get(vid)
        if rng is None:
            return {"virtual_id": vid, "effect_type": MAP_EFFECT_TYPE,
                    "config": {"color": WHITE, "brightness": LIT_BRIGHTNESS,
                               "background_brightness": 0.0}}
        return {"virtual_id": vid, "effect_type": RANGE_EFFECT_TYPE,
                "config": {"color": WHITE, "range_start": int(rng.start),
                           "range_end": int(rng.end),
                           "brightness": LIT_BRIGHTNESS,
                           "background_brightness": 0.0}}

    def _writes(self, lit: bool) -> list[dict]:
        lit_set = set(self.lit_virtual_ids) if lit else set()
        out = []
        for v in self.virtual_ids:
            if v in lit_set:
                out.append(self._lit_write(v))
            else:
                out.append({"virtual_id": v, "effect_type": MAP_EFFECT_TYPE,
                            "config": {"color": BLACK, "brightness": 0.0,
                                       "background_brightness": 0.0}})
        return out

    async def execute(self, step: str, ctx) -> dict:
        if step not in self.steps:
            raise ValueError(f"unknown mapping step: {step!r}")
        lit = step == "lit"
        await ctx.apply_scene(writes=self._writes(lit),
                              transition_ms=WRITE_TRANSITION_MS)
        return {"result": step, "virtuals": len(self.virtual_ids),
                "lit": list(self.lit_virtual_ids) if lit else [],
                "ranges": [r.model_dump() for r in self.ranges.values()]
                          if lit else []}


# ── the run ────────────────────────────────────────────────────────────────

@dataclass
class EmitterResult:
    emitter_id: str
    mapped: bool
    reason: str = ""
    #: This emitter RAN and the camera saw nothing of its light from this
    #: pose. Not mapped, and not a failure either — a stored fact, kept in
    #: the room as a footprint-less record so "never ran" and "ran, not in
    #: shot" stop looking identical. `reason` carries the sentence.
    unseen: bool = False
    #: This emitter was measured TWICE — once in plan order, once again with
    #: an extended dark settle after its first capture came out at ~zero.
    #: True on the retry's own result whichever way it landed, so "it was
    #: given a second chance" is visible rather than inferred.
    retried: bool = False
    weight: float = 0.0
    dark_frames: int = 0
    lit_frames: int = 0
    saturated_fraction: float = 0.0
    seconds: float = 0.0
    carrier_id: str = ""
    label: str = ""
    ranges: list[dict] = field(default_factory=list)


@dataclass
class MappingResult:
    room_id: str
    ok: bool
    reason: str = ""
    pose_id: str = ""
    emitters: list[EmitterResult] = field(default_factory=list)
    seconds: float = 0.0
    granularity: str = emitters_mod.DEFAULT_GRANULARITY
    block_pixels: int = emitters_mod.DEFAULT_BLOCK_PIXELS
    #: The settles this run actually used, after bounding — reported, so a
    #: map taken at a slower quality level says so rather than looking like
    #: every other one.
    dark_settle_s: float = DARK_SETTLE_S
    lit_settle_s: float = LIT_SETTLE_S
    #: The capture WINDOWS this run used — at a fixed camera rate these are
    #: how many frames each average was built from, expressed in seconds
    #: (see the note above MIN_CAPTURE_S). Reported for the same reason as
    #: the settles: a map taken at a different quality level says so.
    dark_capture_s: float = DARK_CAPTURE_S
    lit_capture_s: float = LIT_CAPTURE_S
    #: the granularity each carrier ACTUALLY got, after "auto" resolved
    per_carrier: dict = field(default_factory=dict)
    #: everything the enumeration declined to do, named rather than hidden
    problems: list[str] = field(default_factory=list)
    #: what this run DID that he may not have meant — today, a map that came
    #: out as one piece and therefore cannot show a wave travelling. Carried
    #: on the result as well as the plan, because a run started before the
    #: plan was read (or from a phone that never showed it) must still say so.
    warnings: list[str] = field(default_factory=list)
    #: how the run was carried out, when it was not the obvious way — today,
    #: that a carrier was mapped through its fixture's own strip.
    notes: list[str] = field(default_factory=list)
    #: How long this run was allowed to hold the room, in seconds — the
    #: SAME number the plan showed him before he pressed (run_ceiling_s of
    #: the plan's own estimate). Reported so a run that stopped at the
    #: ceiling can be read against the bound it was actually held to.
    hold_ceiling_s: float = 0.0
    #: WHICH named refusal ended this run, when one did ("ownership",
    #: "hold_ceiling", "aborted"). The page needs the sentence, not this —
    #: it exists so a caller can act on the KIND without matching prose.
    refusal: str = ""
    #: True when a refusal ended the run but footprints were kept — "some of
    #: it landed" is a different thing from both success and failure, and
    #: the page says which.
    partial: bool = False

    @property
    def mapped_count(self) -> int:
        return sum(1 for e in self.emitters if e.mapped)

    @property
    def unseen_count(self) -> int:
        """Emitters that RAN and whose light this pose could not see. Counted
        beside the mapped ones because "14 mapped, 8 unseen from this pose"
        is a complete account of a run and "14 mapped" is not."""
        return sum(1 for e in self.emitters if e.unseen)

    @property
    def retried_count(self) -> int:
        return sum(1 for e in self.emitters if e.retried)

    @property
    def recovered_count(self) -> int:
        """Emitters that measured ~zero first time and MAPPED on the retry —
        the count that says whether the extended dark settle is doing real
        work, which is the whole reason the retry is a measurement and not a
        guess."""
        return sum(1 for e in self.emitters if e.retried and e.mapped)

    @property
    def summary(self) -> str:
        parts = [f"{self.mapped_count} mapped"]
        if self.recovered_count:
            parts.append(f"{self.recovered_count} of them on a second, "
                         f"slower look")
        if self.unseen_count:
            parts.append(f"{self.unseen_count} unseen from this pose")
        failed = sum(1 for e in self.emitters if not e.mapped and not e.unseen)
        if failed:
            parts.append(f"{failed} could not be measured")
        return ", ".join(parts)

    def as_dict(self) -> dict:
        return {"room_id": self.room_id, "ok": self.ok, "reason": self.reason,
                "mapped_count": self.mapped_count,
                "unseen_count": self.unseen_count, "summary": self.summary,
                "retried_count": self.retried_count,
                "recovered_count": self.recovered_count,
                "dark_settle_s": self.dark_settle_s,
                "lit_settle_s": self.lit_settle_s,
                "dark_capture_s": self.dark_capture_s,
                "lit_capture_s": self.lit_capture_s,
                "hold_ceiling_s": self.hold_ceiling_s,
                "pose_id": self.pose_id, "seconds": round(self.seconds, 2),
                "granularity": self.granularity,
                "block_pixels": self.block_pixels,
                "per_carrier": self.per_carrier, "problems": self.problems,
                "warnings": self.warnings, "notes": self.notes,
                "refusal": self.refusal, "partial": self.partial,
                "emitters": [e.__dict__ for e in self.emitters]}


async def _no_carrier_devices() -> dict:
    return {}


async def _no_fixture_devices() -> list:
    return []


def spectra_owns_lights() -> bool:
    """Whether writes from this process reach the render pipeline IN this
    process. Sub-device capture needs it (`pixelRange` is a vendored effect
    the external LedFX service does not have) and so does a sub-device room
    effect (the gain mask is applied in this process's own frame assembly)."""
    from fx import light_ownership
    return light_ownership.load().owner == light_ownership.SPECTRA


@dataclass
class RunDeps:
    """Every seam one run touches. Production wires the real ones; the check
    script and the tests hand in fakes, so a run is provable end to end
    without a camera, a room, or a light."""
    session: Any                                     # MappingSession-shaped
    get_virtuals: Callable[[], Any]
    open_hold: Callable[..., Any] = flare_preview_hold.open_program_hold
    close_hold: Callable[[], Any] = flare_preview_hold.close_hold
    sleep: Callable[[float], Any] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic
    save_room: Optional[Callable[[RoomMap], Any]] = None
    #: carrier id -> the device entries its segments name. Two jobs, both
    #: at the CHAIN rather than at the carrier: the emits-light backstop,
    #: and "auto" granularity (a carrier that is all Hue bulbs is never
    #: split). Defaults to empty, which skips neither and resolves auto by
    #: what the virtual itself can do — never by guessing.
    carrier_devices: Callable[[], Any] = _no_carrier_devices
    #: Whether the in-process render path is the one being written. Only
    #: sub-device capture needs it; a whole-device run works either way.
    spectra_owns: Callable[[], bool] = spectra_owns_lights
    #: Bring a virtual up for the capture / put it back afterwards. Only a
    #: run that has to light a fixture's own idle strip uses these.
    activate: Callable[[str], Any] = None              # type: ignore[assignment]
    deactivate: Callable[[str], Any] = None            # type: ignore[assignment]
    #: The LIVE driver objects for this room's fixtures, which is the only
    #: thing that can be asked its firmware brightness (a config entry
    #: cannot — see spectra/services/fixture_brightness.py). Defaults to
    #: none, which makes the whole brightness guard a stated no-op rather
    #: than a crash on a rig that has no driver layer.
    fixture_devices: Callable[[], Any] = _no_fixture_devices


def production_deps(session) -> RunDeps:
    from spectra.services import fx_seam

    # ONE device listing per deps object: the chain is needed for every
    # carrier in the room, and device_console.list_devices() is a real read
    # of the live stack.
    cache: dict[str, list[dict]] = {}

    async def carrier_devices() -> dict[str, list[dict]]:
        if not cache:
            from spectra.services import carriers, device_console
            listing = await device_console.list_devices()
            cache.update(carriers.devices_by_carrier(
                listing.get("devices") or []))
        return cache

    async def activate(virtual_id: str) -> None:
        # An idle virtual may have no effect at all, and the effects PUT
        # refuses that — so give it the run's own black singleColor first
        # (the same lamp the dark step writes), THEN raise the flag.
        await fx_seam.set_virtual_effect(
            virtual_id, MAP_EFFECT_TYPE,
            {"color": BLACK, "brightness": 0.0, "background_brightness": 0.0})
        await fx_seam.set_virtual_active(virtual_id, True)

    async def deactivate(virtual_id: str) -> None:
        await fx_seam.set_virtual_active(virtual_id, False)

    async def fixture_devices() -> list:
        # The live driver objects, not the config: only a driver that has
        # resolved its destination carries the WLED helper this reads
        # through (fx/devices/wled.py builds `.wled` at activation).
        from spectra.services.live_host import live
        host = getattr(live, "host", None)
        if host is None:
            return []
        return list(host.devices.values())

    return RunDeps(session=session,
                   get_virtuals=fx_seam.get_virtuals,
                   carrier_devices=carrier_devices,
                   activate=activate, deactivate=deactivate,
                   fixture_devices=fixture_devices,
                   save_room=light_field.put_room)


async def live_virtual_ids(get_virtuals: Callable[[], Any]) -> list[str]:
    """Every virtual that is ACTIVE with an effect right now — the same
    scope av_sync_pattern's whole-room flash takes. An inactive virtual is
    left alone: writing one would activate something the room was not
    running, and the revert could not put that back."""
    live = await get_virtuals() or {}
    out = []
    for vid, v in live.items():
        eff = (v or {}).get("effect") or {}
        if (v or {}).get("active", True) and eff.get("type"):
            out.append(vid)
    return sorted(out)


async def resolve_plan(room: RoomMap, deps: RunDeps, scope: list[str],
                       granularity: str, block_pixels: int):
    """The run's emitter list, resolved against what is LIVE right now.

    A carrier that is not rendering is not enumerated and says so by name.
    The carrier->devices chain comes from the device listing (the one
    definition of that mapping) and is what the emits-light backstop checks.

    SUBSTITUTES ARE RESOLVED AGAINST *ALL* VIRTUALS, not the live ones. His
    `tv-mapper` is copy-mapped and cannot be lit in parts; the fixture's own
    560-pixel span virtual `tv-backlight` can, and is INACTIVE — so looking
    only at what is currently rendering would find nothing and refuse the
    one route that works. The run brings it up for the capture and puts it
    back (ACTIVATION, in run_mapping)."""
    live = await deps.get_virtuals() or {}
    in_scope = set(scope)
    virtuals = {c: live[c] for c in room.carrier_ids
                if c in live and c in in_scope}
    chain_failure = ""
    try:
        chains = await deps.carrier_devices()
    except Exception as exc:                           # noqa: BLE001
        logger.exception("room mapping: carrier chain lookup failed")
        chains = {}
        # SURFACED, not just logged: with no chain the emits-light backstop
        # cannot run, so this run is proceeding with one of its own checks
        # switched off. A human has to be told that, not the journal.
        chain_failure = (f"the device list could not be read ({exc}), so this "
                         f"run cannot check that each carrier's chain reaches "
                         f"a real light — it will map whatever is rendering")
    substitutes = {}
    for carrier_id, carrier in virtuals.items():
        found = emitters_mod.substitutes_for(carrier_id, carrier,
                                             chains.get(carrier_id) or [], live)
        if found:
            substitutes[carrier_id] = found
    plan = emitters_mod.plan_run(room.carrier_ids, virtuals,
                                 {c: chains.get(c, []) for c in room.carrier_ids
                                  if c in chains},
                                 substitutes=substitutes,
                                 granularity=granularity,
                                 block_pixels=block_pixels)
    if chain_failure:
        plan.problems.insert(0, chain_failure)
    # BEFORE THE COST: each fixture's own firmware brightness, read while
    # the room is still lit and nothing has been spent. A turned-down
    # fixture scales everything it emits, so a map taken like that measures
    # the dimmer — his first map's weights came out about ten times too
    # small for exactly this reason, and nothing told him.
    readings, devices = await fixture_readings(plan, chains, deps)
    plan.brightness = [r.as_dict() for r in readings]
    warning = fixture_brightness.warning_for(readings)
    if warning:
        plan.warnings.insert(0, warning)
    for r in readings:
        if r.state == "unreadable":
            plan.problems.append(r.reason)
    return plan


async def _chains(deps: RunDeps) -> dict:
    try:
        return await deps.carrier_devices() or {}
    except Exception:                                  # noqa: BLE001
        return {}


async def fixture_readings(plan, chains: dict, deps: RunDeps):
    """(readings, live driver objects) for the fixtures THIS plan will
    light — never the whole house, so a lamp in another room is neither
    read nor turned up.

    Resolved through the carrier->devices chain the plan already uses, so
    there is no second idea anywhere of which fixtures a run touches."""
    wanted = set()
    for e in plan.emitters:
        for d in chains.get(e.carrier_id, []) or []:
            if d.get("id"):
                wanted.add(str(d["id"]))
    if not wanted:
        return [], []
    try:
        devices = [d for d in (await deps.fixture_devices() or [])
                   if str(getattr(d, "id", "") or "") in wanted]
    except Exception as exc:                           # noqa: BLE001
        logger.info("room mapping: no driver layer to read brightness: %s", exc)
        return [], []
    return await fixture_brightness.read_all(devices), devices


async def activate_for_capture(plan, scope: list[str], deps: RunDeps
                               ) -> tuple[list[str], list[str]]:
    """Bring up any virtual this run must light that is not rendering, and
    say which ones were brought up so the run can put them back.

    ACTIVATION, and why the run owns it: a substitute strip
    (`resolve_plan`) is typically INACTIVE — that is why the carrier was
    standing in front of it in the first place. The run already holds the
    room and writes effects, so lighting one more virtual is the same act
    it is already performing; what it must not do is leave the room
    changed. The hold's snapshot covers the EFFECT on a virtual it can see,
    but it cannot restore an `active` flag it never observed as false — so
    the flag is this function's to remember and `deactivate_after_capture`
    below is what puts it back. Verified, not assumed:
    tests/test_capture_activation.py drives a real headless host and reads
    the flag after the run.

    Returns (scope with the activated ids added, ids to put back, and the
    ones that could NOT be brought up — named, because a fixture that never
    came up is about to be reported as "not rendering" and the reason it is
    not rendering would otherwise die in the journal)."""
    needed = {v for e in plan.emitters for v in e.virtual_ids}
    missing = sorted(needed - set(scope))
    if not missing:
        return list(scope), [], []
    activated: list[str] = []
    failed: list[str] = []
    for vid in missing:
        if deps.activate is None:
            failed.append(f"{vid}: this run has no way to bring a virtual up")
            continue
        try:
            await deps.activate(vid)
        except Exception as exc:                       # noqa: BLE001
            logger.exception("room mapping: could not activate %s for the "
                             "capture", vid)
            failed.append(f"{vid}: could not be brought up for the capture "
                          f"({type(exc).__name__}: {exc})")
            continue
        activated.append(vid)
    return sorted(set(scope) | set(activated)), activated, failed


async def deactivate_after_capture(activated: list[str],
                                   deps: RunDeps) -> list[str]:
    """Put back exactly what `activate_for_capture` brought up. Never
    raises: this runs in a `finally`, and a room already handed back must
    not turn a finished map into a 500. Returns what could not be put back
    — a fixture left rendering is a REAL change to his room, and the one
    thing that must never be only a log line."""
    left_on: list[str] = []
    for vid in activated:
        if deps.deactivate is None:
            left_on.append(vid)
            continue
        try:
            await deps.deactivate(vid)
        except Exception as exc:                       # noqa: BLE001
            logger.warning("room mapping: could not deactivate %s after the "
                           "capture — it is left rendering", vid,
                           exc_info=True)
            left_on.append(f"{vid} ({type(exc).__name__}: {exc})")
    return left_on


async def run_mapping(room: RoomMap, deps: RunDeps, *,
                      granularity: str = emitters_mod.DEFAULT_GRANULARITY,
                      block_pixels: int = emitters_mod.DEFAULT_BLOCK_PIXELS,
                      dark_settle_s: Optional[float] = None,
                      lit_settle_s: Optional[float] = None,
                      dark_capture_s: Optional[float] = None,
                      lit_capture_s: Optional[float] = None,
                      ) -> MappingResult:
    """Map every emitter in `room` at the chosen granularity, one short
    held-room hold each.

    REFUSES BEFORE TOUCHING A LIGHT when the camera is not locked — the
    whole instrument's honesty (spectra/services/mapping_session.py's
    docstring). The refusal names the phone and the capability; nothing is
    written, nothing is stored, and the room never goes dark for a run that
    could not have produced a comparable map anyway.

    REFUSES THE SAME WAY when a sub-device granularity is asked for while
    spot-effects owns the lights: the range lamp is a vendored effect in
    THIS process and the external LedFX service has never heard of it, so
    the write would fail at the seam half-way through a dark room."""
    started = deps.clock()
    sess = deps.session
    dark_settle = clamp_settle(dark_settle_s, DARK_SETTLE_S)
    lit_settle = clamp_settle(lit_settle_s, LIT_SETTLE_S)
    dark_capture = clamp_capture(dark_capture_s, DARK_CAPTURE_S)
    lit_capture = clamp_capture(lit_capture_s, LIT_CAPTURE_S)
    result = MappingResult(room_id=room.id, ok=False,
                           pose_id=getattr(sess, "pose_id", ""),
                           granularity=granularity, block_pixels=block_pixels,
                           dark_settle_s=dark_settle, lit_settle_s=lit_settle,
                           dark_capture_s=dark_capture,
                           lit_capture_s=lit_capture)
    refusal = sess.refusal()
    if refusal:
        result.reason = refusal
        return result
    if not room.carrier_ids:
        result.reason = "this room has no carriers assigned yet"
        return result
    sess.run_abort = None

    try:
        scope = await live_virtual_ids(deps.get_virtuals)
    except Exception as exc:                           # noqa: BLE001
        # An ownership state is EXPECTED here (his room is one press from
        # released) and gets its own sentence; anything else is a real bug
        # and still raises, because inventing a sentence for it would lie.
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        result.reason = named
        result.refusal = "ownership"
        return result
    if not scope:
        result.reason = ("no virtual is rendering anything right now — is "
                         "SPECTRA driving the room?")
        return result

    try:
        plan = await resolve_plan(room, deps, scope, granularity, block_pixels)
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        result.reason = named
        result.refusal = "ownership"
        return result
    result.per_carrier = dict(plan.per_carrier)
    result.problems = list(plan.problems)
    result.warnings = list(plan.warnings)
    result.notes = list(plan.notes)
    if not plan.emitters:
        result.reason = ("nothing to map: " + "; ".join(plan.problems)
                         if plan.problems else
                         "nothing to map — no carrier of this room is "
                         "rendering right now")
        return result
    # BEFORE THE COST, AND BEFORE THE ROOM GOES DARK: one continuous hold has
    # a hard cap, and a plan past it refuses BY NAME rather than being
    # quietly truncated to whatever fits. Nothing here touches his
    # granularity or block size — the plan prices his decision, it never
    # corrects it.
    # Priced with THIS run's own four waits, not the shipped defaults the
    # plan page quotes — a sweep at half the dwell must be bounded by the
    # run it is about to do.
    estimate_s = run_estimate_s(len(plan.emitters), dark_settle, dark_capture,
                                lit_settle, lit_capture)
    result.hold_ceiling_s = run_ceiling_s(estimate_s)
    too_long = too_long_refusal(estimate_s)
    if too_long:
        result.reason = too_long
        result.refusal = "too_long"
        return result
    if any(not e.whole_carrier for e in plan.emitters) and not deps.spectra_owns():
        result.reason = (
            "mapping below whole-device granularity needs SPECTRA to be "
            "driving the lights: the range lamp is an effect inside this "
            "process, and the external LedFX service does not have it. Take "
            "the room back, or map at 'Whole device' granularity.")
        return result

    # A carrier carries footprints from exactly ONE granularity: re-mapping
    # a TV per segment must not leave last week's whole-carrier footprint
    # beside the new ranges, where the room effect would drive both and dim
    # the fixture twice.
    for carrier_id in {e.carrier_id for e in plan.emitters}:
        room.drop_carrier_footprints(carrier_id)

    scope, activated, not_brought_up = await activate_for_capture(
        plan, scope, deps)
    for problem in not_brought_up:
        result.problems.append(problem)
    if activated:
        result.notes.append(
            f"Brought up {', '.join(activated)} for the capture and put "
            f"{'it' if len(activated) == 1 else 'them'} back afterwards.")
    try:
        # OWN THE FIXTURE'S OWN BRIGHTNESS for the capture and give his level
        # back — including if the chain below raises. The plan already read
        # it (and warned); this is the acting half. A fixture already at
        # full, or one that could not be read, is never touched.
        readings = [fixture_brightness.FixtureBrightness(**{
            "device_id": b["device_id"], "state": b["state"],
            "value": b["value"], "reason": b["reason"]})
            for b in (getattr(plan, "brightness", None) or [])]
        _, fixtures = await fixture_readings(plan, await _chains(deps), deps)
        async with fixture_brightness.owned(fixtures, readings) as owned:
            await _capture_all(room, plan, scope, deps, result,
                               dark_settle, lit_settle,
                               dark_capture, lit_capture)
        if owned.note:
            result.notes.append(owned.note)
        result.problems.extend(owned.problems)
    finally:
        # THE ONE RELEASE. The room was taken dark once and comes back once,
        # here, whatever ended the run — a finished sweep, his Stop, an
        # ownership loss, the ceiling, or a bug. Letting this raise would
        # turn a stated partial back into a 500, and the hold's own sweep
        # owns the room from here if it does fail.
        try:
            await deps.close_hold()
        except Exception:                              # noqa: BLE001
            logger.warning("room mapping: releasing the hold at the end of "
                           "the run failed; the hold sweep owns it from here",
                           exc_info=True)
        left_on = await deactivate_after_capture(activated, deps)
        if left_on:
            result.problems.append(
                f"left rendering after the capture (they were idle before "
                f"it): {', '.join(left_on)} — turn them off on the devices "
                f"page, or run the map again")

    result.seconds = deps.clock() - started
    mapped = [e for e in result.emitters if e.mapped]
    result.partial = bool(mapped) and bool(result.refusal or sess.run_abort)
    # A run that STOPPED is never "ok", however much it managed first — but
    # what it managed is kept, and `partial` is how the page says both.
    result.ok = bool(mapped) and not sess.run_abort and not result.refusal
    if sess.run_abort and not result.refusal:
        result.refusal = "aborted"
    if not result.reason and not mapped:
        result.reason = (
            "nothing in this room was visible from where the phone was "
            "standing — every emitter lit, and none of its light landed in "
            "the frame. Move to somewhere that can see them and map again."
            if result.unseen_count and result.unseen_count == len(result.emitters)
            else "no emitter produced a footprint — see each one's reason")
    return result


async def _capture_all(room: RoomMap, plan, scope: list[str], deps: RunDeps,
                       result: "MappingResult", dark_settle: float,
                       lit_settle: float, dark_capture: float,
                       lit_capture: float) -> None:
    """Every emitter in plan order, under ONE continuous dark hold, followed
    by ONE retry pass over whatever measured ~zero, with an extended dark
    settle. The hold is opened by the first emitter's own dark step and is
    released by `run_mapping`'s finally — never here, and never between two
    emitters.

    ONE PROGRAM FOR THE WHOLE RUN: the scope is the room, which does not
    change as emitters go by, so only which piece is lit is re-selected.
    That is what keeps the hold's snapshot a single read of the show, taken
    before anything was written.

    WHY THE RETRY IS A SECOND PASS AND NOT AN IMMEDIATE RE-TAKE: it is a
    DISCRIMINATING measurement, and it re-measures with real time and other
    emitters in between rather than on the spot. Its original leading
    hypothesis — the previous emitter's fade bleeding into this emitter's
    dark reference — is now largely closed by construction (the room no
    longer comes back between captures at all; see the module docstring), so
    the retry stands as cheap insurance against a genuinely contaminated
    reference rather than as an explanation of anything.

    ONE retry, never a loop: a second failure is an answer ("this pose
    cannot see it"), not a reason to keep the room dark longer."""
    program = MappingProgram(scope)
    stopped = await _capture_pass(room, program, plan.emitters, scope, deps,
                                  result, dark_settle, lit_settle,
                                  dark_capture, lit_capture)
    if stopped:
        return
    retry = [e for e in plan.emitters
             if any(r.emitter_id == e.emitter_id and r.unseen
                    for r in result.emitters)]
    if not retry:
        return
    logger.info("room mapping: %d emitter(s) measured ~zero; one retry with "
                "a %.1fx dark settle", len(retry), RETRY_DARK_SETTLE_X)
    # SAID, not silent: the run is now longer than the plan's estimate, and
    # a piece that ends up mapped was mapped on a second look. Both are
    # things he would otherwise have to infer from a clock.
    result.notes.append(
        f"{len(retry)} piece{'' if len(retry) == 1 else 's'} measured no "
        f"light first time, so {'it was' if len(retry) == 1 else 'they were'} "
        f"looked at once more with the room left dark "
        f"{RETRY_DARK_SETTLE_X:g}x as long — that adds about "
        f"{len(retry) * (dark_capture + lit_capture + lit_settle + dark_settle * RETRY_DARK_SETTLE_X):.0f}s "
        f"to this run.")
    await _capture_pass(room, program, retry, scope, deps, result,
                        dark_settle * RETRY_DARK_SETTLE_X, lit_settle,
                        dark_capture, lit_capture, retry_pass=True)


async def _capture_pass(room: RoomMap, program: "MappingProgram", emitters,
                        scope: list[str], deps: RunDeps,
                        result: "MappingResult",
                        dark_settle: float, lit_settle: float,
                        dark_capture: float, lit_capture: float, *,
                        retry_pass: bool = False) -> bool:
    """One sweep over `emitters`, inside the run's ONE hold. Returns True
    when the run STOPPED (abort, ownership loss, hold ceiling) — a stopped
    run never goes on to a retry pass, since every retry would be refused
    identically.

    On the retry pass an emitter's result REPLACES its first one rather than
    being appended: an emitter measured twice is still one emitter, and a
    duplicate row would double it in every count."""
    sess = deps.session
    for emitter in emitters:
        if sess.run_abort:
            result.reason = sess.run_abort
            return True
        t0 = deps.clock()
        in_scope = [v for v in emitter.virtual_ids if v in set(scope)]
        if not in_scope:
            _record(result, EmitterResult(
                emitter.emitter_id, False,
                "no virtual of this emitter is rendering right now — nothing "
                "to light, so nothing to photograph",
                retried=retry_pass,
                carrier_id=emitter.carrier_id, label=emitter.label))
            continue
        lost = ""
        try:
            outcome = await _map_one(room, program, emitter, in_scope, deps,
                                     dark_settle, lit_settle, dark_capture,
                                     lit_capture, result.hold_ceiling_s,
                                     retry_pass=retry_pass)
        except Exception as exc:                       # noqa: BLE001
            if mapping_refusals.ownership_refusal(exc) is not None:
                # He released the room (or a handover started) mid-run. That
                # ends the run with a STATED partial — every later emitter
                # would fail identically, and a stack of identical failures
                # reads as a broken instrument rather than a room that
                # changed hands.
                logger.info("room mapping: ownership lost mid-run at %s",
                            emitter.emitter_id)
                lost = mapping_refusals.MID_RUN_LOSS
                outcome = EmitterResult(emitter.emitter_id, False, lost,
                                        retried=retry_pass,
                                        carrier_id=emitter.carrier_id,
                                        label=emitter.label)
            else:
                logger.exception("room mapping: emitter %s failed",
                                 emitter.emitter_id)
                outcome = EmitterResult(
                    emitter.emitter_id, False,
                    mapping_refusals.capture_refusal(
                        emitter.label or emitter.emitter_id, exc),
                    retried=retry_pass,
                    carrier_id=emitter.carrier_id, label=emitter.label)
        # NOTHING IS RELEASED HERE. The room stays dark between two captures
        # — that is the whole point of this rework — and `run_mapping`'s own
        # finally is the ONE place the hold is closed, on every path out of
        # the run. See the module docstring for what the old per-emitter
        # release was doing to the dark references.
        outcome.seconds = round(deps.clock() - t0, 2)
        _record(result, outcome)
        if lost:
            result.reason = lost
            result.refusal = "ownership"
            return True
        if outcome.reason == mapping_refusals.HOLD_CEILING:
            # The ceiling is not this emitter's problem, it is the run's:
            # every remaining emitter would be refused identically, and a
            # column of the same sentence reads as a broken instrument.
            result.reason = outcome.reason
            result.refusal = "hold_ceiling"
            return True
    return False


def _record(result: "MappingResult", outcome: EmitterResult) -> None:
    """One row per emitter, however many times it was measured. The retry
    pass overwrites IN PLACE (keeping plan order), so every count on the
    result reads emitters, not attempts."""
    for i, existing in enumerate(result.emitters):
        if existing.emitter_id == outcome.emitter_id:
            result.emitters[i] = outcome
            return
    result.emitters.append(outcome)


async def _persist(room: RoomMap, deps: RunDeps) -> None:
    """Land the room after an emitter — a MAPPED one or an UNSEEN one. Both
    are results worth surviving a run that stops half-way."""
    if deps.save_room is None:
        return
    maybe = deps.save_room(room)
    if asyncio.iscoroutine(maybe):
        await maybe


async def _map_one(room: RoomMap, program: "MappingProgram",
                   emitter: Emitter, lit_vids: list[str], deps: RunDeps,
                   dark_settle: float, lit_settle: float,
                   dark_capture: float, lit_capture: float,
                   hold_ceiling_s: float, *,
                   retry_pass: bool = False) -> EmitterResult:
    """One emitter, inside the run's ONE hold.

    The FIRST call of a run is what opens that hold (and takes its single
    snapshot of the show); every call after it re-arms the same hold's
    deadline and re-asserts the same dark room. `hold_ceiling_s` is read
    only on that first open — it is the run-scoped ceiling the plan already
    showed him — and is ignored, by the hold, on every call after it.

    The DARK step still runs per emitter even though the room is already
    dark: it costs one write, and it is what guarantees the previous
    emitter's white is off before this one's reference is taken, rather
    than trusting an ordering."""
    sess = deps.session
    ranges = [r for r in emitter.ranges if r.virtual_id in set(lit_vids)]
    program.select(lit_vids, ranges)

    held = await deps.open_hold(program, 1.0, step="dark",
                                heartbeat_timeout_s=HOLD_HEARTBEAT_S,
                                max_duration_s=hold_ceiling_s)
    if not (held or {}).get("held"):
        return EmitterResult(
            emitter.emitter_id, False,
            mapping_refusals.hold_refusal(
                str((held or {}).get("reason") or "no writes")),
            retried=retry_pass,
            carrier_id=emitter.carrier_id, label=emitter.label)
    await deps.sleep(dark_settle)
    dark_grids, _dark_max = await sess.gather(dark_capture, min_frames=MIN_FRAMES)

    await deps.open_hold(program, 1.0, step="lit",
                         heartbeat_timeout_s=HOLD_HEARTBEAT_S,
                         max_duration_s=hold_ceiling_s)
    await deps.sleep(lit_settle)
    lit_grids, lit_max = await sess.gather(lit_capture, min_frames=MIN_FRAMES)

    if sess.run_abort:
        return EmitterResult(emitter.emitter_id, False, sess.run_abort,
                             retried=retry_pass,
                             dark_frames=len(dark_grids), lit_frames=len(lit_grids),
                             carrier_id=emitter.carrier_id, label=emitter.label)
    if len(dark_grids) < MIN_FRAMES or len(lit_grids) < MIN_FRAMES:
        return EmitterResult(
            emitter.emitter_id, False,
            f"not enough frames arrived ({len(dark_grids)} dark, "
            f"{len(lit_grids)} lit; each needs {MIN_FRAMES}) — is the camera "
            f"running and the phone still connected?",
            retried=retry_pass,
            dark_frames=len(dark_grids), lit_frames=len(lit_grids),
            carrier_id=emitter.carrier_id, label=emitter.label)

    capture = CaptureContext(
        pose_id=getattr(sess, "pose_id", ""),
        exposure_locked=sess.lock.exposure_locked,
        white_balance_locked=sess.lock.white_balance_locked,
        exposure_mode=sess.lock.exposure_mode,
        white_balance_mode=sess.lock.white_balance_mode)
    footprint = light_field.footprint_from_frames(
        emitter_id=emitter.emitter_id, virtual_ids=lit_vids,
        dark_frames=dark_grids, lit_frames=lit_grids,
        axis=room.axis, capture=capture, label=emitter.label or emitter.emitter_id)
    footprint.carrier_id = emitter.carrier_id
    footprint.ranges = ranges
    # The saturation figure belongs to the RAW frames, which the session
    # already reduced — recompute it from the maxima it handed back rather
    # than keeping frames alive just to measure clipping.
    hot = sum(1 for m in lit_max if m >= light_field.SATURATION_LEVEL)
    footprint.capture.saturated_fraction = round(
        hot / len(lit_max), 5) if lit_max else 0.0

    if footprint.weight < light_field.UNSEEN_WEIGHT:
        # RAN, AND THE CAMERA SAW NOTHING. Keep the record: a footprint-less
        # entry with the reason on it, so this emitter is visibly "unseen
        # from this pose" instead of silently absent from the store (his
        # first real map: 22 ran, 14 stored, 8 vanished). Not an error — a
        # second pose can see it — so nothing here is worded as one.
        note = mapping_refusals.unseen_note(
            emitter.label or emitter.emitter_id, getattr(sess, "pose_id", ""),
            retried=retry_pass)
        footprint.grid = []
        footprint.axis_profile = []
        footprint.unseen = True
        footprint.retried = retry_pass
        footprint.note = note
        room.put_footprint(footprint)
        await _persist(room, deps)
        return EmitterResult(
            emitter.emitter_id, False, note, unseen=True, retried=retry_pass,
            weight=round(footprint.weight, 4),
            dark_frames=len(dark_grids), lit_frames=len(lit_grids),
            saturated_fraction=footprint.capture.saturated_fraction,
            carrier_id=emitter.carrier_id, label=emitter.label,
            ranges=[r.model_dump() for r in ranges])

    footprint.retried = retry_pass
    # A retry that FOUND light replaces this emitter's unseen record — the
    # store never keeps both readings of one emitter.
    room.put_footprint(footprint)
    await _persist(room, deps)
    return EmitterResult(emitter.emitter_id, True, "", retried=retry_pass,
                         weight=round(footprint.weight, 4),
                         dark_frames=len(dark_grids), lit_frames=len(lit_grids),
                         saturated_fraction=footprint.capture.saturated_fraction,
                         carrier_id=emitter.carrier_id, label=emitter.label,
                         ranges=[r.model_dump() for r in ranges])
