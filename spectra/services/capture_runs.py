"""ONE SEAM FOR EXECUTING ONE CAPTURE RUN — the map protocol or the
commissioning pass — whoever asked for it.

WHY THIS MODULE EXISTS. Until the unattended queue there was exactly one
caller of `room_mapping.run_mapping` and one of `commissioning.
run_commission`: the two routes in `spectra/api/rooms.py`, which also owned
the process-wide "one run at a time" lock, the no-session refusal, the
granularity resolution and the remember-his-choice write. A queue runner
that reimplemented any of that would be a SECOND definition of what a
capture run is, and the two would drift — the codebase's own repeated
lesson (`scene_sequencer.fire_scene_by_id` is the one scene-fire choke
point precisely so a new caller inherits every gate for free).

So the lock, the session gate and the run itself live HERE, and there are
two callers of equal standing: the routes (a human pressing a button) and
`spectra/services/capture_queue.py` (a declared list running while nobody
is awake). Neither can acquire a capability the other lacks, and a new gate
added here is added to both at once.

WHAT IT DOES NOT DO. It does not decide anything about the camera's
honesty: `run_mapping`/`run_commission` each ask the session for its own
refusal before touching a light, and this module never inspects, softens or
pre-empts that. The exposure gate has exactly one implementation
(`mapping_session.lock_refusal`) and this is not a second one.

THE OUTCOME IS MACHINE-READABLE AND SAYS BOTH THINGS. `status` is the word
a program branches on; `detail` is the sentence a person reads, and it is
always one of `mapping_refusals`' own. A run that stopped part-way is
`partial`, never folded into either `ok` or `refused`: "some of it landed"
is a third thing, it is what an unattended queue produces most often, and a
caller that cannot tell it apart will either throw away real measurements
or claim a map it does not have.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from spectra.models.room_map import RoomMap
from spectra.services import emitters as emitters_mod
from spectra.services import (capture_settings, commissioning, exposure_test,
                              light_field, mapping_refusals, mapping_session,
                              room_mapping)

logger = logging.getLogger(__name__)

#: One capture run at a time, process-wide. A map run and a commissioning
#: pass share it because they share both scarce things: the held room and
#: the one camera session's frames.
_run_lock = asyncio.Lock()
_running: Optional[str] = None

KIND_MAP = "map"
KIND_COMMISSION = "commission"
#: THE EXPOSURE COMPARISON. It holds the room and consumes the same camera
#: session's frames, so it takes the SAME lock as the other two — two of
#: these at once would fight over both scarce things exactly as a map and a
#: commissioning pass would.
KIND_EXPOSURE = "exposure"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_REFUSED = "refused"
STATUS_BUSY = "busy"
STATUS_NOT_FOUND = "not_found"


@dataclass
class RunOutcome:
    """What one run did, in both registers at once."""
    kind: str
    status: str
    detail: str = ""
    #: the machine word for WHICH refusal, when there was one — the run's own
    #: (`ownership`, `too_long`, `aborted`, `camera_lock`, ...) or this
    #: module's (`no_session`, `busy`, `not_found`)
    refusal: str = ""
    target: str = ""
    room_id: str = ""
    session_id: str = ""
    pose_id: str = ""
    seconds: float = 0.0
    #: True when the refusal ESCAPED the run as an exception rather than
    #: being stated by it. The distinction is not cosmetic: a run that
    #: STATES an ownership refusal has produced a real record (it may even
    #: have kept footprints), so the route answers 200 with that record; one
    #: that raised produced nothing, so the route answers 409 with the
    #: sentence. Conflating them either loses a partial map or claims a
    #: result that does not exist.
    escaped: bool = False
    #: The run's own full record, exactly as the route returns it. Callers
    #: that want a small record take `summary()` instead.
    result: dict = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        """True when a light was actually driven — i.e. this is a
        measurement, however it ended, rather than a refusal before the room
        went dark."""
        return self.status in (STATUS_OK, STATUS_PARTIAL)

    def summary(self) -> dict:
        """A BOUNDED record of this run, for a queue log that may hold
        dozens. The full result lives in its own store (`room_maps.json`
        for a map, `commissioning.json` for a pass) and is findable from
        here — copying a commissioning run's decode arrays into a second
        store would make the queue log unbounded in the one place nobody
        thinks to look."""
        r = self.result
        base = {"kind": self.kind, "status": self.status,
                "refusal": self.refusal, "detail": self.detail,
                "target": self.target, "room_id": self.room_id,
                "pose_id": self.pose_id, "session_id": self.session_id,
                "seconds": round(self.seconds, 2)}
        if self.kind == KIND_EXPOSURE:
            base.update({"better": r.get("better"), "ratio": r.get("ratio"),
                         "emitter_id": r.get("emitter_id"),
                         "run_summary": r.get("summary"),
                         "problems": list(r.get("problems") or []),
                         "notes": list(r.get("notes") or [])})
        elif self.kind == KIND_MAP:
            base.update({
                "mapped_count": r.get("mapped_count"),
                "unseen_count": r.get("unseen_count"),
                "granularity": r.get("granularity"),
                "block_pixels": r.get("block_pixels"),
                "run_summary": r.get("summary"),
                "problems": list(r.get("problems") or []),
                "warnings": list(r.get("warnings") or []),
                "notes": list(r.get("notes") or [])})
        else:
            base.update({
                "verdict": r.get("verdict"),
                "mapper_id": r.get("mapper_id"),
                "target_specs": list(r.get("target_specs") or []),
                "at": r.get("at"),
                "problems": list(r.get("problems") or []),
                "notes": list(r.get("notes") or [])})
        return base


def running() -> Optional[str]:
    """What is holding the run lock right now, or None."""
    return _running if _run_lock.locked() else None


def busy_detail() -> str:
    return f"a run is already in progress ({_running})"


def live_session():
    """The one capture session, or None. A session is what a phone's page
    and the unattended client BOTH establish — this never asks which."""
    sess = mapping_session.current
    return None if (sess is None or sess.closed) else sess


def run_granularity(room: RoomMap, granularity: Optional[str],
                    block_pixels: Optional[int]) -> tuple[str, int]:
    """This run's granularity and block size, bounded. An omitted value
    falls back to the room's own remembered choice, which is a seed for the
    page's control and never something a run reads on its own."""
    g = (granularity or room.granularity or emitters_mod.DEFAULT_GRANULARITY)
    g = g.strip().lower()
    g = emitters_mod.GRANULARITY_ALIASES.get(g, g)
    if g not in emitters_mod.GRANULARITIES:
        g = emitters_mod.DEFAULT_GRANULARITY
    try:
        block = int(block_pixels if block_pixels is not None
                    else (room.block_pixels or emitters_mod.DEFAULT_BLOCK_PIXELS))
    except (TypeError, ValueError):
        block = emitters_mod.DEFAULT_BLOCK_PIXELS
    block = max(emitters_mod.MIN_BLOCK_PIXELS,
                min(emitters_mod.MAX_BLOCK_PIXELS, block))
    return g, block


def _gate(kind: str, target: str, room_id: str) -> Optional[RunOutcome]:
    """The two things that refuse before any run: nothing holding a camera
    on the room, and another run already holding it."""
    if live_session() is None:
        return RunOutcome(kind=kind, status=STATUS_REFUSED,
                          detail=mapping_refusals.NO_SESSION,
                          refusal="no_session", target=target, room_id=room_id)
    if _run_lock.locked():
        return RunOutcome(kind=kind, status=STATUS_BUSY, detail=busy_detail(),
                          refusal="busy", target=target, room_id=room_id)
    return None


def _status_for(ok: bool, partial: bool) -> str:
    if ok:
        return STATUS_OK
    return STATUS_PARTIAL if partial else STATUS_REFUSED


async def run_map(room_id: str, *, granularity: Optional[str] = None,
                  block_pixels: Optional[int] = None,
                  dark_settle_s: Optional[float] = None,
                  lit_settle_s: Optional[float] = None,
                  dark_capture_s: Optional[float] = None,
                  lit_capture_s: Optional[float] = None,
                  exposure_time: Optional[int] = None,
                  gain: Optional[int] = None,
                  remember: bool = True) -> RunOutcome:
    """THE mapping run. Every caller — the button, the queue — comes here.

    `remember` writes this run's granularity back onto the room so the
    page's control comes back where he left it. A queue item leaves it
    alone by default: an overnight sweep that varied the granularity per
    item must not silently redecorate his page's control with whichever
    item happened to run last."""
    room = light_field.get_room(room_id)
    if room is None:
        return RunOutcome(kind=KIND_MAP, status=STATUS_NOT_FOUND,
                          detail="no such room", refusal="not_found",
                          target=room_id, room_id=room_id)
    gate = _gate(KIND_MAP, room.name or room_id, room_id)
    if gate is not None:
        return gate
    sess = live_session()
    g, block = run_granularity(room, granularity, block_pixels)

    global _running
    async with _run_lock:
        _running = room_id
        try:
            result = await room_mapping.run_mapping(
                room, room_mapping.production_deps(sess),
                granularity=g, block_pixels=block,
                dark_settle_s=dark_settle_s, lit_settle_s=lit_settle_s,
                dark_capture_s=dark_capture_s, lit_capture_s=lit_capture_s,
                camera=capture_settings.request(exposure_time=exposure_time,
                                                gain=gain))
        except Exception as exc:                       # noqa: BLE001
            # An ownership state is EXPECTED on this path and gets its own
            # sentence; anything else is a real bug and still raises, because
            # inventing a sentence for it would lie. `run_mapping` already
            # names the ones it can see — this catches any reaching us from a
            # seam it does not wrap, so the SENTENCE is what a caller gets
            # either way.
            named = mapping_refusals.ownership_refusal(exc)
            if named is None:
                raise
            return RunOutcome(kind=KIND_MAP, status=STATUS_REFUSED,
                              detail=named, refusal="ownership", escaped=True,
                              target=room.name or room_id, room_id=room_id)
        finally:
            _running = None

    if remember:
        stored = light_field.get_room(room_id) or room
        if (stored.granularity, stored.block_pixels) != (g, block):
            stored.granularity, stored.block_pixels = g, block
            light_field.put_room(stored)

    body = result.as_dict()
    return RunOutcome(kind=KIND_MAP,
                      status=_status_for(result.ok, result.partial),
                      detail=result.reason, refusal=result.refusal,
                      target=room.name or room_id, room_id=room_id,
                      session_id=getattr(sess, "id", ""),
                      pose_id=result.pose_id, seconds=result.seconds,
                      result=body)


async def run_commission(room_id: str, *, mapper_id: Optional[str] = None,
                         repeat: int = 1,
                         targets: Optional[list[str]] = None,
                         exposure_time: Optional[int] = None,
                         gain: Optional[int] = None) -> RunOutcome:
    """THE commissioning pass. Same lock, same session gate, same shape.

    The result is STORED either way (`commissioning.save_result`) — a
    refused run is a fact about the evening too, and an unattended queue is
    read afterwards or not at all."""
    room = light_field.get_room(room_id)
    if room is None:
        return RunOutcome(kind=KIND_COMMISSION, status=STATUS_NOT_FOUND,
                          detail="no such room", refusal="not_found",
                          target=room_id, room_id=room_id)
    target_id = mapper_id or (room.carrier_ids[0]
                              if len(room.carrier_ids) == 1 else "")
    if not target_id:
        return RunOutcome(
            kind=KIND_COMMISSION, status=STATUS_REFUSED, refusal="no_mapper",
            room_id=room_id, target=room.name or room_id,
            detail=(f"name the composition to commission — this room has "
                    f"{len(room.carrier_ids)} carriers "
                    f"({', '.join(room.carrier_ids) or 'none'})"))
    gate = _gate(KIND_COMMISSION, target_id, room_id)
    if gate is not None:
        return gate
    sess = live_session()

    global _running
    async with _run_lock:
        _running = f"{room_id}/commission"
        try:
            result = await commissioning.run_commission(
                target_id, room_mapping.production_deps(sess),
                repeat=repeat, targets=list(targets) if targets else None,
                camera=capture_settings.request(exposure_time=exposure_time,
                                                gain=gain))
        except Exception as exc:                       # noqa: BLE001
            named = mapping_refusals.ownership_refusal(exc)
            if named is None:
                raise
            return RunOutcome(kind=KIND_COMMISSION, status=STATUS_REFUSED,
                              detail=named, refusal="ownership", escaped=True,
                              target=target_id, room_id=room_id)
        finally:
            _running = None

    stored = commissioning.save_result(result)
    return RunOutcome(kind=KIND_COMMISSION,
                      status=STATUS_OK if result.ok else STATUS_REFUSED,
                      detail=result.reason, refusal=result.refusal,
                      target=target_id, room_id=room_id,
                      session_id=getattr(sess, "id", ""),
                      pose_id=result.pose_id, seconds=result.seconds,
                      result=stored)


async def run_exposure_test(room_id: str, *,
                            emitter_id: Optional[str] = None,
                            exposure_time: Optional[int] = None,
                            gain: Optional[int] = None,
                            granularity: str = "whole",
                            block_pixels: Optional[int] = None,
                            dark_settle_s: Optional[float] = None,
                            lit_settle_s: Optional[float] = None,
                            dark_capture_s: Optional[float] = None,
                            lit_capture_s: Optional[float] = None
                            ) -> RunOutcome:
    """THE EXPOSURE COMPARISON, through the same seam as the other two.

    It holds the room and consumes the same camera session's frames, so it
    takes the same lock, passes the same session gate, and gets its
    ownership refusals worded by the same module. Nothing about it is a
    second definition of "a capture run" — that was the whole reason this
    module exists.

    It stores NOTHING (`exposure_test` runs against a throwaway room), so
    unlike the other two there is no record to save here: the answer is the
    response."""
    room = light_field.get_room(room_id)
    if room is None:
        return RunOutcome(kind=KIND_EXPOSURE, status=STATUS_NOT_FOUND,
                          detail="no such room", refusal="not_found",
                          target=room_id, room_id=room_id)
    gate = _gate(KIND_EXPOSURE, room.name or room_id, room_id)
    if gate is not None:
        return gate
    sess = live_session()
    _, block = run_granularity(room, None, block_pixels)

    global _running
    async with _run_lock:
        _running = f"{room_id}/exposure"
        try:
            result = await exposure_test.compare_regimes(
                room, room_mapping.production_deps(sess),
                emitter_id=emitter_id, exposure_time=exposure_time,
                gain=gain, granularity=granularity, block_pixels=block,
                dark_settle_s=dark_settle_s, lit_settle_s=lit_settle_s,
                dark_capture_s=dark_capture_s, lit_capture_s=lit_capture_s)
        except Exception as exc:                       # noqa: BLE001
            named = mapping_refusals.ownership_refusal(exc)
            if named is None:
                raise
            return RunOutcome(kind=KIND_EXPOSURE, status=STATUS_REFUSED,
                              detail=named, refusal="ownership", escaped=True,
                              target=room.name or room_id, room_id=room_id)
        finally:
            _running = None

    return RunOutcome(kind=KIND_EXPOSURE,
                      status=STATUS_OK if result.ok else STATUS_REFUSED,
                      detail=result.reason, refusal=result.refusal,
                      target=room.name or room_id, room_id=room_id,
                      session_id=getattr(sess, "id", ""),
                      pose_id=result.pose_id, seconds=result.seconds,
                      result=result.as_dict())


def session_view() -> dict:
    """What a caller needs to know about the camera without reaching into
    the session object: is one there, is it locked, whose is it, and which
    pose. `refusal` is `mapping_session.lock_refusal`'s own sentence — this
    never composes a second one."""
    sess = live_session()
    if sess is None:
        return {"present": False, "locked": False, "session_id": "",
                "pose_id": "", "refusal": mapping_refusals.NO_SESSION,
                "client": {}}
    return {"present": True, "locked": sess.lock.locked,
            "session_id": sess.id, "pose_id": sess.pose_id,
            "refusal": sess.refusal(), "client": dict(sess.hello or {})}
