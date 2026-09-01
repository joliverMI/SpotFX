"""THE EXPOSURE COMPARISON — one emitter, one pose, two camera regimes, and
a number saying which put more measurable light in the frame.

WHY IT EXISTS, in one sentence: after 2026-09-01 the honest statement about
his room was "his ten emitters could not be resolved", and the question
nobody could answer was whether that was the camera's DEFAULT SETTINGS or
the room. This turns that into a two-minute measurement — same pose, same
emitter, back to back, converge-then-freeze against a named integration
time and gain — so the sentence becomes "could not, at default camera
settings" or confirms it honestly either way.

WHAT MAKES THE COMPARISON LEGITIMATE, since the two regimes are DELIBERATELY
on different byte scales and the model normally forbids exactly that. A
footprint is `lit - dark` taken WITHIN one regime, so each half is a
self-contained difference: the camera's own response cancels out of neither
half, but neither half needs it to. What is being compared is not two
footprints of one pose — that would be meaningless — it is HOW MUCH SIGNAL
EACH REGIME PRODUCED, which is exactly the quantity the question is about.
The result says so in its own words rather than leaving a reader to assume
the usual rule applies.

WHAT IT NEVER DOES:

  * write to the map. It runs against a THROWAWAY copy of the room with no
    `save_room`, so a comparison can be run as often as he likes without a
    single stored footprint moving. Two regimes in one store would be two
    incomparable measurements wearing one pose id, which is the one thing
    `mapping_session._adopt_pose` exists to prevent.
  * change the camera permanently. The manual regime is applied, measured,
    and the camera is put back to whatever it was doing before — in a
    `finally`, so an ownership loss or a refused hold restores it too.
  * decide anything. It reports both weights, the ratio, and which regime
    won, with the tolerance it called a tie. `better` is a computed word,
    not a judgment.

IT REUSES THE MAP'S OWN PROTOCOL, deliberately and completely: the same
plan, the same substitution, the same held room, the same
`room_mapping._map_one`. A second implementation of "measure one emitter"
would be a second thing to keep true, and the whole point of the answer is
that it is the SAME measurement the map takes, twice.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from spectra.models.room_map import RoomMap
from spectra.services import capture_settings, light_field, mapping_refusals
from spectra.services import emitters as emitters_mod
from spectra.services import room_mapping

logger = logging.getLogger(__name__)

#: Weights within this fraction of each other are a TIE. A footprint weight
#: is a sum over 2,304 cells of a noisy difference, and two runs of the SAME
#: regime will not repeat exactly; calling a 3% difference a win would be
#: reporting the instrument's own wobble as a finding.
TIE_FRACTION = 0.10


@dataclass
class RegimeResult:
    """One regime's own measurement, and what the camera actually was while
    it was taken — read back, never the request."""
    label: str
    ok: bool = False
    reason: str = ""
    weight: float = 0.0
    saturated_fraction: float = 0.0
    dark_frames: int = 0
    lit_frames: int = 0
    unseen: bool = False
    lock: dict = field(default_factory=dict)
    requested: dict = field(default_factory=dict)
    capture_s: float = 0.0
    observed_fps: float = 0.0

    def as_dict(self) -> dict:
        return {"label": self.label, "ok": self.ok, "reason": self.reason,
                "weight": round(self.weight, 4),
                "saturated_fraction": self.saturated_fraction,
                "dark_frames": self.dark_frames, "lit_frames": self.lit_frames,
                "unseen": self.unseen, "lock": self.lock,
                "requested": self.requested,
                "capture_s": round(self.capture_s, 3),
                "observed_fps": self.observed_fps}


@dataclass
class ComparisonResult:
    room_id: str
    ok: bool = False
    reason: str = ""
    refusal: str = ""
    pose_id: str = ""
    emitter_id: str = ""
    emitter_label: str = ""
    seconds: float = 0.0
    regimes: list = field(default_factory=list)
    #: "manual" / "default" / "tie" / "" — computed from the two weights and
    #: TIE_FRACTION, never chosen.
    better: str = ""
    ratio: Optional[float] = None
    #: The sentence a person reads, saying what was measured and what it
    #: does and does not license.
    summary: str = ""
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {"room_id": self.room_id, "ok": self.ok, "reason": self.reason,
                "refusal": self.refusal, "pose_id": self.pose_id,
                "emitter_id": self.emitter_id,
                "emitter_label": self.emitter_label,
                "seconds": round(self.seconds, 2),
                "regimes": [r.as_dict() for r in self.regimes],
                "better": self.better, "ratio": self.ratio,
                "tie_fraction": TIE_FRACTION,
                "summary": self.summary, "problems": self.problems,
                "notes": self.notes, "at": self.at}


def verdict(default_w: float, manual_w: float) -> tuple[str, Optional[float]]:
    """WHICH REGIME PUT MORE MEASURABLE LIGHT IN THE FRAME, and by how much.

    A pure function so the number and the word can never disagree, and so
    the tie band is one definition rather than a comparison written twice.
    `ratio` is manual / default — above 1 means the manual regime measured
    more. A default of zero has no ratio (dividing by it would invent an
    infinity); the word still lands, because "the default saw nothing and
    the manual saw something" is the most interesting answer this can
    give."""
    if manual_w <= 0 and default_w <= 0:
        return "tie", None
    ratio = (manual_w / default_w) if default_w > 0 else None
    if default_w <= 0:
        return "manual", None
    if abs(manual_w - default_w) <= TIE_FRACTION * max(manual_w, default_w):
        return "tie", ratio
    return ("manual" if manual_w > default_w else "default"), ratio


def _summary(result: ComparisonResult) -> str:
    """The sentence. It says what was measured, what won, and — the part
    that matters — what the comparison does NOT license."""
    got = {r.label: r for r in result.regimes}
    d, m = got.get("default"), got.get("manual")
    if not (d and m and d.ok and m.ok):
        which = [r.label for r in result.regimes if not r.ok]
        return (f"No comparison: {', '.join(which) or 'neither regime'} did "
                f"not produce a measurement, so there is nothing to compare. "
                f"See each regime's own reason.")
    ratio = (f"{result.ratio:.2f}x" if result.ratio is not None
             else "the default regime measured nothing at all, so there is "
                  "no ratio")
    word = {"manual": "the MANUAL regime measured more light",
            "default": "the DEFAULT regime measured more light",
            "tie": "the two regimes are within the tie band"}[result.better]
    return (f"{result.emitter_label or result.emitter_id}, one pose, two "
            f"regimes back to back: converge-then-freeze measured "
            f"{d.weight:.2f} and the manual settings measured {m.weight:.2f} "
            f"({ratio}) — {word}. Each weight is `lit - dark` WITHIN its own "
            f"regime, so both are honest measurements of how much signal "
            f"that regime produced; they are NOT two footprints of one pose "
            f"and must not be compared with any other footprint in this "
            f"room. Nothing was stored.")


async def compare_regimes(room: RoomMap, deps: room_mapping.RunDeps, *,
                          emitter_id: Optional[str] = None,
                          exposure_time: Optional[int] = None,
                          gain: Optional[int] = None,
                          granularity: str = "whole",
                          block_pixels: int = emitters_mod.DEFAULT_BLOCK_PIXELS,
                          dark_settle_s: Optional[float] = None,
                          lit_settle_s: Optional[float] = None,
                          dark_capture_s: Optional[float] = None,
                          lit_capture_s: Optional[float] = None,
                          ) -> ComparisonResult:
    """ONE emitter, measured twice: at whatever the camera converged to, and
    at the named integration time and gain.

    `emitter_id` picks which piece; omitted, it takes the first the plan
    resolves, which on a whole-carrier granularity is the room's first
    carrier. `granularity` defaults to WHOLE deliberately — this is a
    two-minute question about the camera, not a map, and lighting one whole
    fixture is both the brightest signal available and the cheapest thing to
    hold the room dark for.

    Refuses on exactly the gates a map refuses on, in the same words, and —
    since asking for neither lever would make this a comparison of a regime
    with itself — refuses a request that names neither."""
    started = deps.clock()
    sess = deps.session
    result = ComparisonResult(room_id=room.id, ok=False,
                              pose_id=getattr(sess, "pose_id", ""))

    if exposure_time is None and gain is None:
        result.reason = (
            "an exposure comparison needs a manual integration time, a gain, "
            "or both to compare the camera's own settings against — with "
            "neither, both halves would be the same regime and the answer "
            "would be the instrument's own noise.")
        result.refusal = "no_levers"
        return result
    refusal = sess.refusal()
    if refusal:
        result.reason, result.refusal = refusal, "camera_lock"
        return result
    if not room.carrier_ids:
        result.reason = "this room has no carriers assigned yet"
        return result

    try:
        scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
        plan = await room_mapping.resolve_plan(room, deps, scope, granularity,
                                               block_pixels)
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        result.reason, result.refusal = named, "ownership"
        return result
    result.problems.extend(plan.problems)
    if not plan.emitters:
        result.reason = ("nothing to measure — no carrier of this room is "
                         "rendering right now")
        return result
    emitter = next((e for e in plan.emitters if e.emitter_id == emitter_id),
                   None) if emitter_id else plan.emitters[0]
    if emitter is None:
        result.reason = (
            f"{emitter_id!r} is not one of the pieces this room resolves to "
            f"({', '.join(e.emitter_id for e in plan.emitters[:8])}"
            f"{'...' if len(plan.emitters) > 8 else ''})")
        result.refusal = "no_emitter"
        return result
    result.emitter_id = emitter.emitter_id
    result.emitter_label = emitter.label or emitter.emitter_id

    dark_settle = room_mapping.clamp_settle(dark_settle_s,
                                            room_mapping.DARK_SETTLE_S)
    lit_settle = room_mapping.clamp_settle(lit_settle_s,
                                           room_mapping.LIT_SETTLE_S)
    dark_capture = room_mapping.clamp_capture(dark_capture_s,
                                              room_mapping.DARK_CAPTURE_S)
    lit_capture = room_mapping.clamp_capture(lit_capture_s,
                                             room_mapping.LIT_CAPTURE_S)

    # NOTHING IS STORED. A throwaway room with the same carriers and axis,
    # and deps with no `save_room`, so `_map_one`'s own persist is a no-op
    # and his real map is untouched however often this is run.
    scratch = RoomMap(name=room.name, carrier_ids=list(room.carrier_ids),
                      axis=room.axis)
    quiet = replace(deps, save_room=None)

    scope, activated, not_up = await room_mapping.activate_for_capture(
        plan, scope, quiet)
    result.problems.extend(not_up)
    program = room_mapping.MappingProgram(scope)
    sess.run_abort = None
    before = sess.camera_request
    try:
        for label, req in (
                ("default", capture_settings.CameraRequest(
                    frame_size=capture_settings.MAP_PROFILE)),
                ("manual", capture_settings.CameraRequest(
                    frame_size=capture_settings.MAP_PROFILE,
                    exposure_time=exposure_time, gain=gain))):
            result.regimes.append(await _one_regime(
                label, req, scratch, program, emitter, scope, quiet, result,
                dark_settle, lit_settle, dark_capture, lit_capture))
    finally:
        # PUT THE CAMERA BACK, whatever happened — a comparison that leaves
        # a long integration time running would silently retune every run
        # after it.
        try:
            await sess.apply_camera(
                before if before.manual or before.frame_size
                else capture_settings.CameraRequest(
                    frame_size=capture_settings.MAP_PROFILE))
        except Exception:                              # noqa: BLE001
            logger.warning("exposure test: could not put the camera back",
                           exc_info=True)
        try:
            await quiet.close_hold()
        except Exception:                              # noqa: BLE001
            logger.warning("exposure test: releasing the hold failed; the "
                           "hold sweep owns it from here", exc_info=True)
        left_on = await room_mapping.deactivate_after_capture(activated, quiet)
        if left_on:
            result.problems.append(
                f"left rendering after the comparison: {', '.join(left_on)}")

    result.seconds = deps.clock() - started
    got = {r.label: r for r in result.regimes}
    if all(r.ok for r in result.regimes) and len(result.regimes) == 2:
        result.better, result.ratio = verdict(got["default"].weight,
                                              got["manual"].weight)
        if result.ratio is not None:
            result.ratio = round(result.ratio, 4)
        result.ok = True
    else:
        result.reason = next((r.reason for r in result.regimes if not r.ok),
                             result.reason or "no regime produced a reading")
    result.summary = _summary(result)
    return result


async def _one_regime(label: str, req: "capture_settings.CameraRequest",
                      scratch: RoomMap, program, emitter, scope: list,
                      deps: room_mapping.RunDeps, result: ComparisonResult,
                      dark_settle: float, lit_settle: float,
                      dark_capture: float, lit_capture: float) -> RegimeResult:
    """Ask the camera for this regime, gate on the READ-BACK, then take the
    map's own single-emitter measurement."""
    sess = deps.session
    out = RegimeResult(label=label, requested=req.as_wire())
    await sess.apply_camera(req)
    got = await sess.await_frame_size(req.frame_size,
                                      room_mapping.FRAME_SWITCH_WAIT_S)
    # THE COMPARISON DEPENDS ON THIS MORE THAN EITHER RUN DOES: its whole
    # answer is what the manual regime measured, so reading the previous
    # regime's read-back would compare a regime with itself and report the
    # noise as a finding.
    await sess.await_camera(room_mapping.FRAME_SWITCH_WAIT_S)
    out.lock = sess.camera_lock_view()
    out.observed_fps = sess.observed_fps()
    problem = sess.frame_refusal(req.frame_size) or sess.camera_refusal()
    if problem:
        out.reason = problem
        return out
    if got != tuple(req.frame_size):
        result.notes.append(
            f"the {label} regime read at {got[0]}x{got[1]} — this camera "
            f"could not reach {req.frame_size[0]}x{req.frame_size[1]}")
    dark_c, lit_c, too_long, note = room_mapping.capture_windows(
        dark_capture, lit_capture, req.exposure_time,
        sess.observed_fps() or 5.0)
    if too_long:
        out.reason = too_long
        return out
    if note:
        result.notes.append(f"{label}: {note}")
    out.capture_s = lit_c
    outcome = await room_mapping._map_one(                     # noqa: SLF001
        scratch, program, emitter, [v for v in emitter.virtual_ids
                                    if v in set(scope)],
        deps, dark_settle, lit_settle, dark_c, lit_c,
        room_mapping.RUN_CEILING_FLOOR_S)
    out.dark_frames, out.lit_frames = outcome.dark_frames, outcome.lit_frames
    out.saturated_fraction = outcome.saturated_fraction
    out.unseen = outcome.unseen
    out.weight = float(outcome.weight or 0.0)
    # AN UNSEEN EMITTER IS A REAL READING HERE, unlike in a map. "This
    # regime measured nothing" is precisely the finding the comparison is
    # for — it is the DEFAULT half of "could not, at default settings" —
    # so it counts as a measurement rather than a failed one.
    out.ok = outcome.mapped or outcome.unseen
    if not out.ok:
        out.reason = outcome.reason
    elif outcome.unseen:
        out.reason = (f"this regime measured no usable light at all "
                      f"(weight {out.weight:.3f}, under the "
                      f"{light_field.UNSEEN_WEIGHT} an emitter must clear) — "
                      f"a real reading, and the interesting half of the "
                      f"answer if the other regime saw something")
    return out
