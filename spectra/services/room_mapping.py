"""THE MAPPING RUN — lights off, one emitter at a time, on the ONE held-room
seam. Never a second hold system.

WHAT A RUN DOES, per emitter, and why each number is what the plan says:

  1. take the room dark        every live virtual to black, under the hold's
                               own snapshot
  2. settle DARK_SETTLE_S      the write has to actually land (WLED transport
                               plus whatever per-device timing delay is
                               applied) before the reference means anything
  3. dark reference            DARK_CAPTURE_S of frames, averaged
  4. light ONE emitter         full white through the one write seam
  5. settle LIT_SETTLE_S       same reason as 2
  6. lit capture               LIT_CAPTURE_S of frames, averaged
  7. derive + store            footprint = lit - dark, clipped, downsampled
                               (spectra/services/light_field.py)
  8. RELEASE THE HOLD          the room comes back before the next emitter

Step 8 is the design decision his plan states explicitly: the hold carries a
3-minute absolute ceiling that no client can push out, so a long mapping run
is A CHAIN OF SHORT PER-EMITTER HOLDS rather than one long one. Between two
emitters the room is genuinely restored — not "restorable in principle" —
which is the property he asked for, and it means a run of any length is
bounded by one emitter's worth of held room (~4 s), never by its total.

EVERYTHING HARD IS INHERITED, NOT REBUILT. flare_preview_hold.
open_program_hold owns the snapshot taken once per hold, the deadline that
lapses on its own, the independent sweep that reverts a hold nobody closed,
the absolute ceiling, the persisted snapshot a service restart lands back,
and the 1 ms tween-safe revert. This module supplies only what is new: which
virtuals are in scope, and what each named step writes. A dropped phone, a
closed tab or a mid-run service restart therefore land in machinery that was
already proven the expensive way (see that module's own docstring).

WHY THE DARK STEP DARKENS EVERY LIVE VIRTUAL, not only the room's own
devices: a footprint is what a CAMERA sees, so any other fixture still
playing the show lands in the frame and in the difference. The room's
`device_ids` decide which emitters get MAPPED; the dark step covers the
whole live room because that is what "with the room dark" means to a
camera. Everything it darkens is in the same snapshot and comes back with
it — the same scope av_sync_pattern.py's own default flash already takes.

WHAT THIS MODULE NEVER DOES: decide anything about fixture positions. It
turns one emitter on, photographs the room, and hands the difference to
light_field.py. If a future change here starts computing where a strip is,
it has left the plan (spectra/models/room_map.py's docstring).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from spectra.models.room_map import CaptureContext, EmitterFootprint, RoomMap
from spectra.models.scene import (SceneColorAssignment, SceneDeviceConfig,
                                  SceneV2)
from spectra.services import flare_preview_hold, light_field

logger = logging.getLogger(__name__)

#: The write primitive, shared with the AV instrument's flash pattern so
#: "full white through the one write seam" means the same thing in both
#: (av_sync_pattern.PATTERN_EFFECT_TYPE / PATTERN_COLOR).
MAP_EFFECT_TYPE = "singleColor"
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
#: The hold's heartbeat window for a run. A run drives its own holds
#: synchronously and closes each one itself, so this only has to outlast a
#: single emitter's ~3.5 s; if the run dies mid-emitter the sweep reverts
#: within this + flare_preview_hold.SWEEP_INTERVAL_S with nothing else
#: needing to have run.
HOLD_HEARTBEAT_S = 20.0
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
    one emitter's virtuals.

    The "lit" step writes the dark set FIRST and the white set second in a
    single apply_scene payload, so a virtual can never be left lit from a
    previous emitter by an ordering accident — the payload is always the
    complete state of every in-scope virtual, not a delta."""

    steps = ("dark", "lit")

    def __init__(self, virtual_ids: list[str], lit_virtual_ids: list[str]) -> None:
        self.virtual_ids = list(dict.fromkeys(virtual_ids))
        self.lit_virtual_ids = [v for v in dict.fromkeys(lit_virtual_ids)
                                if v in set(self.virtual_ids)]
        self.hold_scene = dark_scene(self.virtual_ids)

    def _writes(self, lit: bool) -> list[dict]:
        lit_set = set(self.lit_virtual_ids) if lit else set()
        return [{"virtual_id": v, "effect_type": MAP_EFFECT_TYPE,
                 "config": {"color": WHITE if v in lit_set else BLACK,
                            "brightness": LIT_BRIGHTNESS if v in lit_set else 0.0,
                            "background_brightness": 0.0}}
                for v in self.virtual_ids]

    async def execute(self, step: str, ctx) -> dict:
        if step not in self.steps:
            raise ValueError(f"unknown mapping step: {step!r}")
        lit = step == "lit"
        await ctx.apply_scene(writes=self._writes(lit),
                              transition_ms=WRITE_TRANSITION_MS)
        return {"result": step, "virtuals": len(self.virtual_ids),
                "lit": list(self.lit_virtual_ids) if lit else []}


# ── the run ────────────────────────────────────────────────────────────────

@dataclass
class EmitterResult:
    emitter_id: str
    mapped: bool
    reason: str = ""
    weight: float = 0.0
    dark_frames: int = 0
    lit_frames: int = 0
    saturated_fraction: float = 0.0
    seconds: float = 0.0


@dataclass
class MappingResult:
    room_id: str
    ok: bool
    reason: str = ""
    pose_id: str = ""
    emitters: list[EmitterResult] = field(default_factory=list)
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {"room_id": self.room_id, "ok": self.ok, "reason": self.reason,
                "pose_id": self.pose_id, "seconds": round(self.seconds, 2),
                "emitters": [e.__dict__ for e in self.emitters]}


@dataclass
class RunDeps:
    """Every seam one run touches. Production wires the real ones; the check
    script and the tests hand in fakes, so a run is provable end to end
    without a camera, a room, or a light."""
    session: Any                                     # MappingSession-shaped
    get_virtuals: Callable[[], Any]
    virtuals_for_device: Callable[[str], Any]
    open_hold: Callable[..., Any] = flare_preview_hold.open_program_hold
    close_hold: Callable[[], Any] = flare_preview_hold.close_hold
    sleep: Callable[[float], Any] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic
    save_room: Optional[Callable[[RoomMap], Any]] = None


def production_deps(session) -> RunDeps:
    from spectra.services import av_sync_pattern, fx_seam
    return RunDeps(session=session,
                   get_virtuals=fx_seam.get_virtuals,
                   virtuals_for_device=av_sync_pattern.virtuals_for_device,
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


async def run_mapping(room: RoomMap, deps: RunDeps) -> MappingResult:
    """Map every device in `room`, one short held-room hold each.

    REFUSES BEFORE TOUCHING A LIGHT when the camera is not locked — the
    whole instrument's honesty (spectra/services/mapping_session.py's
    docstring). The refusal names the phone and the capability; nothing is
    written, nothing is stored, and the room never goes dark for a run that
    could not have produced a comparable map anyway."""
    started = deps.clock()
    sess = deps.session
    result = MappingResult(room_id=room.id, ok=False, pose_id=getattr(sess, "pose_id", ""))
    refusal = sess.refusal()
    if refusal:
        result.reason = refusal
        return result
    if not room.device_ids:
        result.reason = "this room has no devices assigned yet"
        return result
    sess.run_abort = None

    scope = await live_virtual_ids(deps.get_virtuals)
    if not scope:
        result.reason = ("no virtual is rendering anything right now — is "
                         "SPECTRA driving the room?")
        return result

    for device_id in room.device_ids:
        if sess.run_abort:
            result.reason = sess.run_abort
            break
        t0 = deps.clock()
        try:
            lit_vids = list(await deps.virtuals_for_device(device_id) or [])
        except Exception as exc:                       # noqa: BLE001
            logger.exception("room mapping: device lookup failed for %s", device_id)
            result.emitters.append(EmitterResult(device_id, False,
                                                 f"device lookup failed: {exc}"))
            continue
        in_scope = [v for v in lit_vids if v in set(scope)]
        if not in_scope:
            result.emitters.append(EmitterResult(
                device_id, False,
                "no virtual of this device is rendering right now — nothing "
                "to light, so nothing to photograph"))
            continue
        try:
            outcome = await _map_one(room, device_id, scope, in_scope, deps)
        except Exception as exc:                       # noqa: BLE001
            logger.exception("room mapping: emitter %s failed", device_id)
            outcome = EmitterResult(device_id, False, f"capture failed: {exc}")
        finally:
            # The chain: every emitter's hold is released before the next
            # one opens, whatever happened inside it.
            await deps.close_hold()
        outcome.seconds = round(deps.clock() - t0, 2)
        result.emitters.append(outcome)

    result.seconds = deps.clock() - started
    mapped = [e for e in result.emitters if e.mapped]
    result.ok = bool(mapped) and not sess.run_abort
    if not result.reason and not mapped:
        result.reason = "no emitter produced a footprint — see each one's reason"
    return result


async def _map_one(room: RoomMap, device_id: str, scope: list[str],
                   lit_vids: list[str], deps: RunDeps) -> EmitterResult:
    sess = deps.session
    program = MappingProgram(scope, lit_vids)

    held = await deps.open_hold(program, 1.0, step="dark",
                                heartbeat_timeout_s=HOLD_HEARTBEAT_S)
    if not (held or {}).get("held"):
        return EmitterResult(device_id, False,
                             f"the room could not be held: "
                             f"{(held or {}).get('reason') or 'no writes'}")
    await deps.sleep(DARK_SETTLE_S)
    dark_grids, _dark_max = await sess.gather(DARK_CAPTURE_S, min_frames=MIN_FRAMES)

    await deps.open_hold(program, 1.0, step="lit",
                         heartbeat_timeout_s=HOLD_HEARTBEAT_S)
    await deps.sleep(LIT_SETTLE_S)
    lit_grids, lit_max = await sess.gather(LIT_CAPTURE_S, min_frames=MIN_FRAMES)

    if sess.run_abort:
        return EmitterResult(device_id, False, sess.run_abort,
                             dark_frames=len(dark_grids), lit_frames=len(lit_grids))
    if len(dark_grids) < MIN_FRAMES or len(lit_grids) < MIN_FRAMES:
        return EmitterResult(
            device_id, False,
            f"not enough frames arrived ({len(dark_grids)} dark, "
            f"{len(lit_grids)} lit; each needs {MIN_FRAMES}) — is the camera "
            f"running and the phone still connected?",
            dark_frames=len(dark_grids), lit_frames=len(lit_grids))

    capture = CaptureContext(
        pose_id=getattr(sess, "pose_id", ""),
        exposure_locked=sess.lock.exposure_locked,
        white_balance_locked=sess.lock.white_balance_locked,
        exposure_mode=sess.lock.exposure_mode,
        white_balance_mode=sess.lock.white_balance_mode)
    footprint = light_field.footprint_from_frames(
        emitter_id=device_id, virtual_ids=lit_vids,
        dark_frames=dark_grids, lit_frames=lit_grids,
        axis=room.axis, capture=capture, label=device_id)
    # The saturation figure belongs to the RAW frames, which the session
    # already reduced — recompute it from the maxima it handed back rather
    # than keeping frames alive just to measure clipping.
    hot = sum(1 for m in lit_max if m >= light_field.SATURATION_LEVEL)
    footprint.capture.saturated_fraction = round(
        hot / len(lit_max), 5) if lit_max else 0.0

    if footprint.weight <= 0.0:
        return EmitterResult(
            device_id, False,
            "this emitter added no measurable light to the frame — is it in "
            "shot, and is it actually the device you think it is?",
            dark_frames=len(dark_grids), lit_frames=len(lit_grids))

    room.put_footprint(footprint)
    if deps.save_room is not None:
        maybe = deps.save_room(room)
        if asyncio.iscoroutine(maybe):
            await maybe
    return EmitterResult(device_id, True, "", weight=round(footprint.weight, 4),
                         dark_frames=len(dark_grids), lit_frames=len(lit_grids),
                         saturated_fraction=footprint.capture.saturated_fraction)
