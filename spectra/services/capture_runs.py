"""ONE SEAM FOR EXECUTING ONE CAPTURE RUN — the map protocol, the
commissioning pass, the exposure comparison or the pose fingerprint —
whoever asked for it.

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
callers of equal standing: the routes (a human pressing a button),
`spectra/services/capture_queue.py` (a declared list running while nobody
is awake), and `spectra/services/calibration_runs.py` (a named calibration
re-running itself). None can acquire a capability the others lack, and a new
gate added here is added to all of them at once.

FOUR KINDS RUN THROUGH IT, and the fourth is the newest: the POSE
FINGERPRINT (`run_pose_fingerprint`) drives a handful of known fixtures and
reads back where their light lands, so a calibration can tell a moved camera
from a changed room. It drives lights and reads the same camera session's
frames, so it is a capture run in every sense the other three are — which is
exactly why it lives here rather than growing its own path to a light.

WHAT IT DOES NOT DO. It does not decide anything about the camera's
honesty: `run_mapping`/`run_commission` each ask the session for its own
refusal before touching a light, and this module never inspects, softens or
pre-empts that. The exposure gate has exactly one implementation
(`mapping_session.lock_refusal`) and this is not a second one.

WHAT IT DOES ADD, and only because there is one of it: the LEVER SELF-TEST
preflight (`spectra/services/lever_selftest.py`). Before a calibration-grade
run on a NATIVE session, the camera is made to prove that its exposure
control reaches its sensor — driven, measured, and refused BY NAME if the
light does not follow the command. It lives here for the same reason the
lock does: one seam, so the button and the overnight queue inherit it
together and neither can acquire what the other lacks.

AND, SINCE THE BROWSER'S DEMOTION, the gate that decides WHICH CLIENT may
take a calibration-grade measurement at all. A browser session is refused
BY NAME here (`_gate`) and is never self-tested, because there is nothing
to test: a browser cannot pin the camera in the first place. It is the same
one-seam argument one level up — the button, the queue and a calibration
re-running itself all pass through this function, so none of them can be
the one that forgot. `spectra/services/capture_source.py` is the binding
statement; the page keeps aiming, which needs no held camera at all.

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
from spectra.services import capture_health
from spectra.services import emitters as emitters_mod
from spectra.services import (capture_settings, capture_source, commissioning,
                              exposure_test, lever_selftest, light_field,
                              mapping_refusals, mapping_session, room_mapping)

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
#: THE POSE FINGERPRINT (spectra/services/pose_fingerprint.py) — a handful
#: of known fixtures driven and their light's landing place read back, so a
#: calibration can tell a moved camera from a changed room. It drives lights
#: and consumes the same camera session's frames, so it takes the SAME lock
#: as the other three for the same two reasons.
KIND_FINGERPRINT = "fingerprint"

#: WHICH KINDS ARE CALIBRATION-GRADE, i.e. run the lever self-test first
#: on a NATIVE session. All three are: each of them produces a number
#: somebody later compares against another number, and a camera that is not
#: obeying its own exposure control makes every one of those comparisons a
#: statement about the camera's mood.
#:
#: THE EXPOSURE COMPARISON IS GATED TOO, and it is worth saying why that is
#: not a lost diagnostic: it exists to answer "is it the room or the camera
#: settings", and a refusing self-test IS that answer — measured, named, and
#: arriving in fifteen seconds instead of two minutes. It is not a
#: capability being taken away; it is the same finding, sooner.
#:
#: THE POSE FINGERPRINT IS ONE TOO, and it is the clearest case of the
#: sentence above: its whole purpose is to compare a number taken now with
#: the same number taken weeks ago, so a camera not obeying its own exposure
#: control would make that comparison a statement about the camera's mood
#: with a calibration's comparability claim resting on it.
CALIBRATION_GRADE = (KIND_MAP, KIND_COMMISSION, KIND_EXPOSURE,
                     KIND_FINGERPRINT)

#: THE REFUSALS THAT HAPPEN BEFORE ANY LIGHT IS DRIVEN — nothing was
#: measured, nothing was written, and the whole answer is the sentence. Every
#: route on this path answers them the same way (409 with the wording), so
#: the set is named ONCE here rather than retyped at each route: a gate added
#: below that a route forgot to list would otherwise reach him as a 200 with
#: an empty result, which is the shape of a silent failure.
PREFLIGHT_REFUSALS = ("no_session", "browser_session", "busy")

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
    #: module's (`no_session`, `browser_session`, `busy`, `not_found`)
    refusal: str = ""
    target: str = ""
    room_id: str = ""
    session_id: str = ""
    pose_id: str = ""
    seconds: float = 0.0
    #: THE LEVER SELF-TEST'S VERDICT for the session this run went through
    #: (`spectra/services/lever_selftest.py`), or {} on a browser session,
    #: which this step deliberately leaves untouched. Carried on EVERY
    #: outcome, not only a refused one: "this run's camera was proven to
    #: obey its own exposure control" is part of what the run measured.
    lever: dict = field(default_factory=dict)
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
                "seconds": round(self.seconds, 2),
                # BOUNDED: the verdict word and its sentence, never the
                # three readings — the full verdict lives on the session
                # and on the run's own result.
                "lever": {"verdict": (self.lever or {}).get("verdict"),
                          "proven": (self.lever or {}).get("proven"),
                          "reason": (self.lever or {}).get("reason")}
                         if self.lever else {}}
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
                # WHICH EMITTERS THIS RUN ACTUALLY PRODUCED, by id — the
                # provenance link a calibration's lineage records, and
                # useful to any reader of a queue log asking "which pieces
                # did item 3 land?". Bounded by construction: a run is
                # capped at `emitters.MAX_EMITTERS_PER_RUN` short ids, so
                # this is a handful of strings and never a grid.
                "emitter_ids": [e.get("emitter_id")
                                for e in (r.get("emitters") or [])
                                if e.get("mapped")],
                # WHAT EACH ONE MEASURED, one small row per emitter — never
                # a grid. The room map keeps only the LATEST footprint, so a
                # calibration's lineage has to carry the number itself or a
                # diff between two of its own entries has nothing to read
                # (`spectra/models/calibration.EmitterMeasurement`). Bounded
                # by the run's own `emitters.MAX_EMITTERS_PER_RUN`.
                "measurements": [
                    {"emitter_id": e.get("emitter_id"),
                     "carrier_id": e.get("carrier_id") or "",
                     "label": e.get("label") or "",
                     "weight": round(float(e.get("weight") or 0.0), 4),
                     "mapped": bool(e.get("mapped")),
                     "unseen": bool(e.get("unseen"))}
                    for e in (r.get("emitters") or [])],
                "scoped": bool(r.get("scoped")),
                "mixed_carriers": list(r.get("mixed_carriers") or []),
                # The contamination witness's own three counts for this run
                # (clean / contaminated / unclaimed), verbatim.
                "witness": dict(r.get("witness") or {}),
                "granularity": r.get("granularity"),
                "block_pixels": r.get("block_pixels"),
                "run_summary": r.get("summary"),
                "problems": list(r.get("problems") or []),
                "warnings": list(r.get("warnings") or []),
                "notes": list(r.get("notes") or [])})
        elif self.kind == KIND_FINGERPRINT:
            refs = list(r.get("references") or [])
            base.update({
                "anchors": len(refs),
                "anchors_seen": sum(1 for x in refs if x.get("seen")),
                "problems": list(r.get("problems") or []),
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
    """The three things that refuse before any run: nothing holding a camera
    on the room, a camera nothing can hold to a known state, and another run
    already holding it.

    THE MIDDLE ONE IS THE BROWSER'S DEMOTION and it lands HERE, at the one
    seam, for the reason this module exists: the button, the unattended
    queue and a calibration re-running itself are callers of equal standing,
    and a gate written at any one of them would be a gate the other two do
    not have. `capture_source.py` is the binding statement for what is
    demoted; `mapping_refusals` owns the sentence.

    IT IS SCOPED TO CALIBRATION-GRADE KINDS, which today is all four — but
    the check reads `CALIBRATION_GRADE` rather than assuming, so a future
    kind that genuinely does not produce a comparable number is not silently
    swept into a refusal it never earned.

    NOTHING ABOUT THE SESSION TRANSPORT MOVES. A browser still connects,
    still streams frames, still reports its lock, and is still the whole of
    how a camera gets aimed — see this module's own `session_view`, which
    reports the demotion as a fact about calibration rather than as a broken
    session."""
    sess = live_session()
    if sess is None:
        return RunOutcome(kind=kind, status=STATUS_REFUSED,
                          detail=mapping_refusals.NO_SESSION,
                          refusal="no_session", target=target, room_id=room_id)
    if kind in CALIBRATION_GRADE:
        refusal = capture_source.calibration_refusal(sess, action=kind)
        if refusal:
            return RunOutcome(kind=kind, status=STATUS_REFUSED, detail=refusal,
                              refusal="browser_session", target=target,
                              room_id=room_id,
                              session_id=getattr(sess, "id", ""))
    if _run_lock.locked():
        return RunOutcome(kind=kind, status=STATUS_BUSY, detail=busy_detail(),
                          refusal="busy", target=target, room_id=room_id)
    return None


async def _preflight(kind: str, room: RoomMap, sess,
                     requested_exposure: Optional[int] = None
                     ) -> "lever_selftest.Verdict | None":
    """THE LEVER SELF-TEST, run before a calibration-grade run on a NATIVE
    session — and nothing at all on a browser one.

    IT RUNS HERE, inside the run lock, because it drives a light: it takes
    the same held room and the same camera session every capture takes, and
    two of those at once would fight over both. It acquires nothing new,
    which is the whole of "the emitter drive happens only inside an
    owned-room session like every other capture".

    IT IS FREE AFTER THE FIRST ONE. `lever_selftest.ensure` caches the
    verdict on the SESSION under a fingerprint carrying the pose, so a queue
    of twelve items pays for it once and a reconnect (a new session object)
    pays again — which is exactly "at establishment, and after any
    reconnect", made structural rather than remembered.

    A BROWSER SESSION NEVER REACHES HERE for a calibration-grade kind —
    `_gate` has already refused it by name (the browser's demotion), so this
    is not a second opinion about the browser and must not become one. What
    remains of the old "a browser is simply untouched" rule is still true
    of every NON-calibration-grade use of a session, and of aiming.

    THE ROOM COMES BACK BETWEEN THE TWO, and that is deliberate: the
    self-test closes its own hold in a `finally` and the run opens its own
    afterwards, so the show is visible for a moment in between. A hold that
    survived an exception path to save one flash of light would be the
    wrong trade — `flare_preview_hold`'s whole safety story is that nothing
    holds his room without a live deadline behind it."""
    if kind not in CALIBRATION_GRADE or sess is None:
        return None
    if not lever_selftest.is_native(sess):
        return None
    try:
        return await lever_selftest.ensure(
            room, room_mapping.production_deps(sess),
            requested_exposure=requested_exposure)
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        # An ownership state is not a finding about the camera. The run
        # itself is about to refuse on the same sentence, better.
        logger.info("lever self-test: not run (%s)", named)
        return None


def _lever_refusal(kind: str, verdict, room_id: str,
                   target: str) -> Optional[RunOutcome]:
    """A measured self-test that says this camera is not obeying its own
    exposure control stops the run BY NAME, before the room goes dark for
    it. `unprovable`/`unproven` never reach here — see
    `lever_selftest`'s docstring on why a check we could not make is not a
    fault."""
    if verdict is None or not verdict.refuses:
        return None
    return RunOutcome(kind=kind, status=STATUS_REFUSED, detail=verdict.reason,
                      refusal="lever", target=target, room_id=room_id,
                      lever=verdict.as_dict())


def _status_for(ok: bool, partial: bool) -> str:
    if ok:
        return STATUS_OK
    return STATUS_PARTIAL if partial else STATUS_REFUSED


async def run_map(room_id: str, *, granularity: Optional[str] = None,
                  block_pixels: Optional[int] = None,
                  carrier_ids: Optional[list[str]] = None,
                  emitter_ids: Optional[list[str]] = None,
                  dark_settle_s: Optional[float] = None,
                  lit_settle_s: Optional[float] = None,
                  dark_capture_s: Optional[float] = None,
                  lit_capture_s: Optional[float] = None,
                  exposure_time: Optional[int] = None,
                  gain: Optional[int] = None,
                  white_balance: Optional[int] = None,
                  focus: Optional[int] = None,
                  remember: bool = True) -> RunOutcome:
    """THE mapping run. Every caller — the button, the queue — comes here.

    `remember` writes this run's granularity back onto the room so the
    page's control comes back where he left it. A queue item leaves it
    alone by default: an overnight sweep that varied the granularity per
    item must not silently redecorate his page's control with whichever
    item happened to run last.

    `carrier_ids`/`emitter_ids` SCOPE the run to part of the room — a
    calibration amendment re-measuring one fixture, or a few ranges of one.
    Both default None, which is the whole room, so every caller that existed
    before amendments did behaves exactly as it did. `run_mapping.scope_plan`
    owns the narrowing and the one-granularity-per-carrier invariant."""
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
    lever = None
    async with _run_lock:
        _running = room_id
        try:
            lever = await _preflight(KIND_MAP, room, sess, exposure_time)
            refused = _lever_refusal(KIND_MAP, lever, room_id,
                                     room.name or room_id)
            if refused is not None:
                return refused
            result = await room_mapping.run_mapping(
                room, room_mapping.production_deps(sess),
                granularity=g, block_pixels=block,
                carrier_ids=list(carrier_ids) if carrier_ids else None,
                emitter_ids=list(emitter_ids) if emitter_ids else None,
                dark_settle_s=dark_settle_s, lit_settle_s=lit_settle_s,
                dark_capture_s=dark_capture_s, lit_capture_s=lit_capture_s,
                camera=capture_settings.request(
                    exposure_time=exposure_time, gain=gain,
                    white_balance=white_balance, focus=focus))
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
                      lever=lever.as_dict() if lever else {},
                      result=body)


async def run_commission(room_id: str, *, mapper_id: Optional[str] = None,
                         repeat: int = 1,
                         targets: Optional[list[str]] = None,
                         exposure_time: Optional[int] = None,
                         gain: Optional[int] = None,
                         white_balance: Optional[int] = None,
                         focus: Optional[int] = None) -> RunOutcome:
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
    lever = None
    async with _run_lock:
        _running = f"{room_id}/commission"
        try:
            lever = await _preflight(KIND_COMMISSION, room, sess,
                                     exposure_time)
            refused = _lever_refusal(KIND_COMMISSION, lever, room_id,
                                     target_id)
            if refused is not None:
                return refused
            result = await commissioning.run_commission(
                target_id, room_mapping.production_deps(sess),
                repeat=repeat, targets=list(targets) if targets else None,
                camera=capture_settings.request(
                    exposure_time=exposure_time, gain=gain,
                    white_balance=white_balance, focus=focus))
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
                      lever=lever.as_dict() if lever else {},
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
    lever = None
    async with _run_lock:
        _running = f"{room_id}/exposure"
        try:
            lever = await _preflight(KIND_EXPOSURE, room, sess, exposure_time)
            refused = _lever_refusal(KIND_EXPOSURE, lever, room_id,
                                     room.name or room_id)
            if refused is not None:
                return refused
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
                      lever=lever.as_dict() if lever else {},
                      result=result.as_dict())


async def run_pose_fingerprint(room_id: str, *,
                               emitter_ids: Optional[list[str]] = None,
                               exposure_time: Optional[int] = None,
                               gain: Optional[int] = None,
                               white_balance: Optional[int] = None,
                               focus: Optional[int] = None):
    """THE POSE FINGERPRINT PASS, through the same seam as the other three.

    It drives lights and reads the same camera session's frames, so it takes
    the same lock, passes the same session gate, runs the same lever
    self-test preflight and gets its ownership refusals worded by the same
    module. That is the entire reason this function lives here rather than
    in `pose_fingerprint` or in the calibration runner: a fingerprint that
    reached a light through its own path would be a second definition of
    "a capture run", and the gates would drift.

    It stores NOTHING (`pose_fingerprint.measure` runs against a throwaway
    room). What the caller does with the readings — establish a pose,
    check one, discard both — is the calibration's business, not this
    seam's.

    `RunOutcome.result` carries the measurement; `RunOutcome.status` is
    `ok` when readings were taken (even if some anchors were dark, which is
    a reading), `refused` otherwise."""
    from spectra.services import pose_fingerprint

    room = light_field.get_room(room_id)
    if room is None:
        return RunOutcome(kind=KIND_FINGERPRINT, status=STATUS_NOT_FOUND,
                          detail="no such room", refusal="not_found",
                          target=room_id, room_id=room_id)
    gate = _gate(KIND_FINGERPRINT, room.name or room_id, room_id)
    if gate is not None:
        return gate
    sess = live_session()

    global _running
    lever = None
    async with _run_lock:
        _running = f"{room_id}/fingerprint"
        try:
            lever = await _preflight(KIND_FINGERPRINT, room, sess,
                                     exposure_time)
            refused = _lever_refusal(KIND_FINGERPRINT, lever, room_id,
                                     room.name or room_id)
            if refused is not None:
                return refused
            # ASK THE CAMERA, THEN READ IT BACK, BEFORE THE ROOM GOES DARK —
            # `run_mapping`'s own shape verbatim, because a fingerprint's
            # readings are compared with readings taken weeks apart and are
            # therefore the LAST thing that may be measured under whatever
            # the camera happened to choose.
            request = capture_settings.request(
                frame_size=capture_settings.MAP_PROFILE,
                exposure_time=exposure_time, gain=gain,
                white_balance=white_balance, focus=focus)
            await sess.apply_camera(request)
            got = await sess.await_frame_size(request.frame_size,
                                              room_mapping.FRAME_SWITCH_WAIT_S)
            await sess.await_camera(room_mapping.FRAME_SWITCH_WAIT_S)
            camera = {"requested": request.as_wire(),
                      "frame_size": {"width": got[0], "height": got[1]},
                      "lock": sess.camera_lock_view(),
                      "observed_fps": sess.observed_fps()}
            problem = (sess.frame_refusal(request.frame_size)
                       or sess.camera_refusal())
            if problem:
                return RunOutcome(kind=KIND_FINGERPRINT,
                                  status=STATUS_REFUSED, detail=problem,
                                  refusal="camera", target=room.name or room_id,
                                  room_id=room_id,
                                  session_id=getattr(sess, "id", ""),
                                  lever=lever.as_dict() if lever else {},
                                  result={"camera": camera})
            measured = await pose_fingerprint.measure(
                room, room_mapping.production_deps(sess),
                emitter_ids=emitter_ids)
        except Exception as exc:                       # noqa: BLE001
            named = mapping_refusals.ownership_refusal(exc)
            if named is None:
                raise
            return RunOutcome(kind=KIND_FINGERPRINT, status=STATUS_REFUSED,
                              detail=named, refusal="ownership", escaped=True,
                              target=room.name or room_id, room_id=room_id)
        finally:
            _running = None

    body = {"references": [r.model_dump() for r in measured.references],
            "problems": list(measured.problems),
            "notes": list(measured.notes),
            "pose_id": measured.pose_id,
            "seconds": round(measured.seconds, 2),
            "camera": camera,
            "identity": pose_fingerprint.camera_identity(sess)}
    return RunOutcome(
        kind=KIND_FINGERPRINT,
        status=STATUS_REFUSED if measured.refusal else STATUS_OK,
        detail=measured.refusal, refusal="pose" if measured.refusal else "",
        target=room.name or room_id, room_id=room_id,
        session_id=getattr(sess, "id", ""), pose_id=measured.pose_id,
        seconds=measured.seconds,
        lever=lever.as_dict() if lever else {}, result=body)


def session_view() -> dict:
    """What a caller needs to know about the camera without reaching into
    the session object: is one there, is it locked, WHOSE IS IT AND WHAT MAY
    IT DO, and which pose. Every sentence in it is `mapping_refusals`' or
    `mapping_session.lock_refusal`'s own — this composes none.

    THE THREE ANSWERS ARE DELIBERATELY SEPARATE, because since the browser's
    demotion they can disagree and a surface that collapsed them would lie:

      `refusal`              — why the CAMERA cannot be trusted yet (the
                               exposure lock). Unchanged.
      `calibration_refusal`  — why this CLIENT may not source a measurement,
                               even with a perfectly locked camera. This is
                               the browser's demotion, and it is not a fault
                               in the session: the session is fine, and it is
                               still doing the job it is good at.
      `measured_by`          — WHOSE CAMERA a run would use when one CAN.
                               A page offering a Start button with two
                               devices in the room owes this answer.

    `aiming` is the positive statement the page needs most: a browser session
    is fully, first-class usable for pointing a camera, and nothing here
    should let that read as "unusable"."""
    sess = live_session()
    if sess is None:
        return {"present": False, "locked": False, "session_id": "",
                "pose_id": "", "refusal": mapping_refusals.NO_SESSION,
                "client": {}, "native": False, "lever": {},
                "source": capture_source.KIND_NONE,
                "calibration_grade": False, "calibration_refusal": "",
                "measured_by": capture_source.measured_by(None),
                "aiming": False,
                # ABSENCE IS A READ. `refusal` above is why the RUN cannot
                # go; this says which machine is missing, what it was
                # running and when it was last here. It refuses nothing —
                # see capture_health.py's own statement of that boundary.
                "host": capture_health.health(None)}
    verdict = getattr(sess, "lever_verdict", None)
    grade = capture_source.calibration_grade(sess)
    return {"host": capture_health.health(sess),
            "present": True, "locked": sess.lock.locked,
            "session_id": sess.id, "pose_id": sess.pose_id,
            "refusal": sess.refusal(), "client": dict(sess.hello or {}),
            # WHETHER THIS SESSION'S LEVERS ARE KNOWN TO BE REAL. `native`
            # says whether the question is even asked of it — a browser
            # session is never self-tested (it is refused before that, and
            # there is nothing to test), so no verdict here never reads as
            # a failed one.
            "native": grade,
            "source": capture_source.kind(sess),
            "calibration_grade": grade,
            # EMPTY WHEN IT MAY MEASURE. A sentence sitting in this field is
            # exactly the sentence a pressed run would refuse with, from the
            # same function, so the page cannot promise something the gate
            # will not honour.
            "calibration_refusal": capture_source.calibration_refusal(sess) or "",
            # ONE FUNCTION FOR ALL THREE STATES — it resolves the native
            # sentence through `mapping_refusals` itself, so this composes
            # nothing and there is no second copy to drift.
            "measured_by": capture_source.measured_by(sess),
            # A browser session is a VIEWFINDER, and that is a real capability
            # rather than a consolation: aiming is what it is for.
            "aiming": True,
            "lever": verdict.as_dict() if hasattr(verdict, "as_dict") else {}}
