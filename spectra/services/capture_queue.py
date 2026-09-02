"""THE CAPTURE QUEUE — a declared list of capture runs, executed end to end
while nobody is awake.

WHY THIS EXISTS (the captain's own bottleneck): a mapping or commissioning
run needed a person at every step — open the page on a device with a camera,
grant it, wait for the exposure lock, aim, keep the tab alive, press Start,
watch it finish, press the next one. He ran one overnight queue that way and
it worked only because he personally set the session up before bed. When the
session is the bottleneck, every capture experiment queues behind his
availability.

WHAT THIS MODULE REMOVES, and what it deliberately does NOT. It removes the
PRESSING: given a live capture session (from a phone's page or, more to the
point, from `spectra/capture_client/` on a machine with a webcam), it walks
a declared list of runs, keeps whatever each one measured, and writes a
machine-readable outcome per item. It does not remove, weaken or pre-empt a
single gate: every item goes through `capture_runs`, which is the same
function the button goes through, so the exposure refusal, the ownership
refusal, the hold ceiling and the one-run-at-a-time lock are inherited
rather than reimplemented. There is no "unattended mode" anywhere in this
codebase that a run behaves differently under.

THREE PROPERTIES THAT MATTER MORE AT 3 AM THAN THEY DO AT A KEYBOARD:

  KEEP WHAT LANDED. A run that stops part-way is `partial`, its footprints
  are already persisted by `room_mapping` as it goes, and the queue records
  that fact and carries on. An unattended queue that discarded a partial —
  or that stopped the whole night because item 3 lost the room for eight
  seconds — would be worse than the human it replaced.

  SAY WHY, IN A SENTENCE. Nobody is watching, so the log IS the run. Every
  refusal carries `mapping_refusals`' own wording, never a status word on
  its own, and the record is written after EVERY item rather than at the
  end — a queue killed mid-way still explains itself.

  NEVER PRETEND THE POSE DID NOT MOVE. Footprints are comparable only
  within one pose (one camera, one place, one locked exposure). The client
  keeps its pose across a dropped WebSocket and cannot keep it across a
  camera reopen; when the pose changes mid-queue this module NAMES it on
  the item that changed and on the queue as a whole
  (`mapping_refusals.pose_changed_note`), because a map that is silently
  two measurements is the exact failure the exposure gate exists to
  prevent, arriving by another door.

WAITING FOR THE SESSION IS PART OF THE JOB. A queue may legitimately be
started before the camera is up (a cron line, a systemd unit, an ssh
one-liner), so each item waits up to `session_wait_s` for a session that is
present AND locked. When that wait runs out the queue STOPS — the remaining
items are recorded `not_run` with the session's own sentence rather than
each burning the same wait — and everything already measured is kept.

ONE QUEUE AT A TIME, process-wide, for the same reason there is one run at a
time: two would fight over one held room and one camera.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from spectra import config as scfg
from spectra.services import capture_runs, capture_source, mapping_refusals

logger = logging.getLogger(__name__)

#: Queues kept in the store. A queue record is bounded by construction (one
#: `RunOutcome.summary()` per item, never a decode array), so this is a
#: history depth rather than a size guard.
MAX_STORED_QUEUES = 20
#: How long an item waits for a present, LOCKED session before the queue
#: gives up. Generous on purpose: the common shape is "start the queue, then
#: start the client", and the client has a camera to open and an exposure to
#: let settle before it can honestly report a lock.
DEFAULT_SESSION_WAIT_S = 180.0
SESSION_POLL_S = 0.5
#: Bounds on a declared queue. A list this long is a mistake, not a plan.
MAX_ITEMS = 50

STATUS_NOT_RUN = "not_run"
STATUS_STOPPED = "stopped"


def _path(path=None):
    return path or scfg.CAPTURE_QUEUE_FILE


@dataclass
class QueueItem:
    """One declared run. `kind` is `capture_runs.KIND_MAP` or
    `KIND_COMMISSION`; everything else is that run's own arguments, which
    are the SAME arguments the route takes — a queue file is a list of
    button presses, not a second dialect."""
    kind: str
    room_id: str
    label: str = ""
    # map
    granularity: Optional[str] = None
    #: SCOPE this map to part of the room — the carriers, or the individual
    #: emitters, to re-measure. Both None (the default, and every queue
    #: declared before amendments existed) means the whole room. A
    #: calibration amendment is the caller that uses them; see
    #: `spectra/services/amendment.py` for when the RESULT may be mixed with
    #: what the map already holds, and `room_mapping.scope_plan` for what is
    #: enforced at run time.
    carrier_ids: Optional[list[str]] = None
    emitter_ids: Optional[list[str]] = None
    block_pixels: Optional[int] = None
    dark_settle_s: Optional[float] = None
    lit_settle_s: Optional[float] = None
    dark_capture_s: Optional[float] = None
    lit_capture_s: Optional[float] = None
    # THE CAMERA'S FOUR PINNED LEVERS, on BOTH kinds — a queue file is a
    # list of button presses and both routes take these, so leaving them out
    # here would make an unattended run the one place his camera cannot be
    # told what to do. `exposure_time` is in 100-microsecond units (V4L2's
    # own unit and the browser's, so nothing converts); `gain` and `focus`
    # are the device's own scales; `white_balance` is a temperature in
    # Kelvin. The last two are NATIVE-CLIENT ONLY, which is not a
    # restriction here — an unattended queue is always driven by the native
    # client. All four default to None, which is converge-then-freeze —
    # every queue declared before these existed runs exactly as it did.
    # `spectra/services/capture_settings.py` is the binding statement.
    exposure_time: Optional[int] = None
    gain: Optional[int] = None
    white_balance: Optional[int] = None
    focus: Optional[int] = None
    # commissioning
    mapper_id: Optional[str] = None
    repeat: int = 1
    targets: Optional[list[str]] = None
    #: The switch form of `targets: ["fixtures"]`, accepted here for the
    #: same reason the route accepts it: a queue file is a list of button
    #: presses, so it takes the button's own arguments.
    per_fixture: bool = False
    #: How many EXTRA attempts this item gets if it is cut short by
    #: something that might not recur — a dropped connection, a lost room.
    #: Default 0: a retry re-measures the same emitters, which costs the
    #: room another dark minute, so it is a declared decision and never
    #: automatic. A REFUSAL is never retried (an unlocked camera or a
    #: released room will refuse identically the second time).
    retries: int = 0
    session_wait_s: float = DEFAULT_SESSION_WAIT_S

    @property
    def name(self) -> str:
        return self.label or f"{self.kind} {self.room_id}"


@dataclass
class ItemOutcome:
    index: int
    name: str
    kind: str
    room_id: str
    status: str
    detail: str = ""
    refusal: str = ""
    attempts: int = 0
    pose_id: str = ""
    session_id: str = ""
    pose_changed: bool = False
    started_at: float = 0.0
    seconds: float = 0.0
    run: dict = field(default_factory=dict)
    #: EVERY ATTEMPT, in order, not only the one that stuck. A retried item
    #: whose first attempt was `partial` measured something real and kept
    #: it; a record that showed only the second attempt's `ok` would erase
    #: the fact that the room was interrupted, which is exactly the fact
    #: somebody reading this at breakfast needs.
    attempt_log: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"index": self.index, "name": self.name, "kind": self.kind,
                "room_id": self.room_id, "status": self.status,
                "detail": self.detail, "refusal": self.refusal,
                "attempts": self.attempts, "pose_id": self.pose_id,
                "session_id": self.session_id,
                "pose_changed": self.pose_changed,
                "started_at": self.started_at,
                "seconds": round(self.seconds, 2), "run": self.run,
                "attempt_log": self.attempt_log}


@dataclass
class QueueRun:
    id: str
    label: str
    started_at: float
    items: list[QueueItem]
    outcomes: list[ItemOutcome] = field(default_factory=list)
    finished_at: float = 0.0
    running_index: int = -1
    stopped: bool = False
    #: The queue's own account of itself, one line, for the surface a human
    #: reads first.
    notes: list[str] = field(default_factory=list)
    first_pose: str = ""

    @property
    def done(self) -> bool:
        return self.finished_at > 0.0

    @property
    def counts(self) -> dict:
        out: dict[str, int] = {}
        for o in self.outcomes:
            out[o.status] = out.get(o.status, 0) + 1
        return out

    @property
    def summary(self) -> str:
        c = self.counts
        parts = [f"{c.get(k, 0)} {word}" for k, word in (
            (capture_runs.STATUS_OK, "completed"),
            (capture_runs.STATUS_PARTIAL, "partial"),
            (capture_runs.STATUS_REFUSED, "refused"),
            (STATUS_NOT_RUN, "not run"),
            (STATUS_STOPPED, "stopped")) if c.get(k)]
        return f"{len(self.items)} declared: " + (", ".join(parts) or "none run yet")

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "running_index": self.running_index, "stopped": self.stopped,
                "declared": len(self.items), "counts": self.counts,
                "summary": self.summary, "notes": self.notes,
                "first_pose": self.first_pose,
                "items": [o.as_dict() for o in self.outcomes]}


# ── the one live queue ─────────────────────────────────────────────────────

current: Optional[QueueRun] = None
_task: Optional[asyncio.Task] = None
_stop = False


def running() -> bool:
    return current is not None and not current.done


def stop() -> bool:
    """Ask the queue to stop after the run in flight. Never cancels a run
    mid-capture: a cancelled run would leave the room dark until the hold's
    own sweep noticed, and the run it interrupted would lose measurements it
    had already taken but not yet written."""
    global _stop
    if not running():
        return False
    _stop = True
    if current is not None:
        current.stopped = True
    return True


def parse_items(raw: Any) -> list[QueueItem]:
    """A declared list -> QueueItems, refusing anything it cannot honour
    rather than silently dropping it. A queue file with a typo in it must
    fail at declaration, not at 3 am on the item nobody reads."""
    if isinstance(raw, dict):
        raw = raw.get("items")
    if not isinstance(raw, list) or not raw:
        raise ValueError("a capture queue is a non-empty list of items")
    if len(raw) > MAX_ITEMS:
        raise ValueError(f"a capture queue is capped at {MAX_ITEMS} items; "
                         f"this one declares {len(raw)}")
    fields = set(QueueItem.__dataclass_fields__)
    items: list[QueueItem] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"item {i} is not an object")
        unknown = sorted(set(entry) - fields)
        if unknown:
            raise ValueError(f"item {i} has unknown field(s): "
                             f"{', '.join(unknown)}")
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in (capture_runs.KIND_MAP, capture_runs.KIND_COMMISSION):
            raise ValueError(f"item {i}: kind must be "
                             f"'{capture_runs.KIND_MAP}' or "
                             f"'{capture_runs.KIND_COMMISSION}', not {kind!r}")
        if not str(entry.get("room_id") or "").strip():
            raise ValueError(f"item {i}: room_id is required")
        if kind != capture_runs.KIND_MAP:
            # SCOPING IS A MAP'S OWN ARGUMENT. A commissioning pass names
            # what it reads with `targets`, and silently ignoring a
            # carrier/emitter list here would let an amendment believe it
            # narrowed a pass it did not.
            for scoped in ("carrier_ids", "emitter_ids"):
                if entry.get(scoped):
                    raise ValueError(
                        f"item {i}: {scoped} scopes a '{capture_runs.KIND_MAP}' "
                        f"item; a '{kind}' item names what it reads with "
                        f"'targets'")
        items.append(QueueItem(**{**entry, "kind": kind}))
    return items


async def wait_for_session(wait_s: float, *,
                           sleep: Callable[[float], Any] = asyncio.sleep,
                           clock: Callable[[], float] = time.monotonic,
                           action: str = "queue"
                           ) -> tuple[Optional[dict], str]:
    """Wait for a session that is present, LOCKED and CALIBRATION-GRADE, up
    to `wait_s`. Returns (session_view, refusal_sentence).

    IT WAITS FOR LOCKED, NOT MERELY PRESENT, on purpose: a client that has
    just reconnected has an exposure to settle and re-read, and a run
    started in that window would refuse for a reason that was about to stop
    being true. This is a wait, never a softening — the thing waited for is
    the gate's own answer, unchanged.

    IT ALSO WAITS THROUGH A BROWSER SESSION, since the browser's demotion,
    and that is the same argument rather than a new one: everything either
    caller runs is calibration-grade, so a page left open on a phone is a
    session that cannot do the job — and one session is live at a time, so
    the native client CONNECTING is exactly the thing worth waiting for. At
    the deadline the browser's own refusal sentence is what comes back, so
    the queue log says which camera was there rather than "no session",
    which would have sent a reader to look for a machine that was plugged in
    all along.

    PUBLIC because there is a second legitimate waiter now: a CALIBRATION
    run (spectra/services/calibration_runs.py) has to have a camera before
    its pose fingerprint can drive a single anchor, and that wait must be
    the same wait a queue item makes rather than a second one that drifts —
    the whole discipline `capture_runs` exists for, one level up.

    `action` is only ever the WORD a refusal names this caller by (see
    `mapping_refusals._ACTION_WORDS`) — it changes nothing about what is
    waited for, because both callers wait for exactly the same thing."""
    deadline = clock() + max(0.0, wait_s)
    ever = False
    while True:
        view = capture_runs.session_view()
        ever = ever or view["present"]
        if view["present"] and view["locked"] and view["calibration_grade"]:
            return view, ""
        if clock() >= deadline:
            if view["present"] and not view["calibration_grade"]:
                # A BROWSER, all along. The SAME wording function the run
                # gate refuses with — asked for this caller's own flavour,
                # because whoever reads a queue log at breakfast was never
                # standing at a button and "press this again" is an
                # instruction they cannot follow.
                return None, mapping_refusals.browser_not_calibration_grade(
                    capture_source.describe_hello(view.get("client") or {}),
                    action=action)
            if view["present"] and not view["locked"]:
                # A camera that is THERE and will not lock is the exposure
                # gate's own refusal, verbatim — not a session problem.
                return None, view["refusal"] or mapping_refusals.NO_SESSION
            return None, mapping_refusals.session_lost(
                wait_s, ever_connected=ever)
        await sleep(SESSION_POLL_S)


async def _wait_for_session(item: QueueItem, sleep, clock
                            ) -> tuple[Optional[dict], str]:
    return await wait_for_session(item.session_wait_s, sleep=sleep,
                                  clock=clock)


def _attempt_row(n: int, outcome: capture_runs.RunOutcome) -> dict:
    """One attempt, small enough to keep every one of them."""
    row = {"attempt": n, "status": outcome.status,
           "refusal": outcome.refusal, "detail": outcome.detail}
    got = outcome.result
    if outcome.kind == capture_runs.KIND_MAP:
        row["mapped_count"] = got.get("mapped_count")
        row["run_summary"] = got.get("summary")
    else:
        row["verdict"] = got.get("verdict")
    return row


async def _execute(item: QueueItem) -> capture_runs.RunOutcome:
    if item.kind == capture_runs.KIND_MAP:
        return await capture_runs.run_map(
            item.room_id, granularity=item.granularity,
            block_pixels=item.block_pixels,
            carrier_ids=item.carrier_ids, emitter_ids=item.emitter_ids,
            dark_settle_s=item.dark_settle_s, lit_settle_s=item.lit_settle_s,
            dark_capture_s=item.dark_capture_s,
            lit_capture_s=item.lit_capture_s,
            exposure_time=item.exposure_time, gain=item.gain,
            white_balance=item.white_balance, focus=item.focus,
            # An overnight sweep must not redecorate his page's granularity
            # control with whichever item happened to run last.
            remember=False)
    from spectra.services import commissioning
    targets = (list(item.targets) if item.targets
               else ([commissioning.TARGET_FIXTURES] if item.per_fixture
                     else None))
    return await capture_runs.run_commission(
        item.room_id, mapper_id=item.mapper_id, repeat=item.repeat,
        targets=targets, exposure_time=item.exposure_time, gain=item.gain,
        white_balance=item.white_balance, focus=item.focus)


def new_run(items: list[QueueItem], label: str = "") -> QueueRun:
    """Create the record and install it as the live one, synchronously.

    `start()` calls this BEFORE creating its task so the id it hands back is
    the id the store will carry — a caller that got an id for a queue the
    runner had not installed yet would be reading a different record than
    the one it started."""
    global current, _stop
    _stop = False
    current = QueueRun(id=uuid.uuid4().hex[:12], label=label,
                       started_at=time.time(), items=list(items))
    return current


async def run_queue(items: list[QueueItem], *, label: str = "",
                    sleep: Callable[[float], Any] = asyncio.sleep,
                    clock: Callable[[], float] = time.monotonic,
                    save: Optional[Callable[[QueueRun], Any]] = None,
                    run: Optional[QueueRun] = None,
                    guard: Optional[Callable[[QueueItem], Optional[str]]] = None
                    ) -> QueueRun:
    """Walk the declared list. Never raises for an expected condition — an
    unattended caller gets a record, and the record says what happened.

    `guard` is an optional per-item veto, asked BEFORE each item is started
    and returning a sentence to refuse it (or None to allow it). Default
    None, so every existing caller behaves exactly as before this parameter
    existed. It is a REFUSAL SEAM, never a softening: nothing a guard
    returns can let an item past a gate `capture_runs` would apply, and a
    guard that refuses stops the queue the same way a lost session does —
    the refused item and every item after it are recorded `not_run` with
    the guard's own sentence, and everything already measured is kept.

    Its one caller today is the night run, whose guard is the hard
    planned-end bound: his morning routine (spectra/services/night_run.py).
    A run that could not finish before his morning must not be started —
    "never schedule capture work past it" — and a bound checked only once,
    at the top of a queue, would still let item six start at 05:28."""
    if run is None:
        run = new_run(items, label)
    persist = save if save is not None else save_queue

    for index, item in enumerate(items):
        refusal = guard(item) if guard is not None else None
        if refusal:
            remaining = len(items) - index
            for j, later in enumerate(items[index:], start=index):
                run.outcomes.append(ItemOutcome(
                    index=j, name=later.name, kind=later.kind,
                    room_id=later.room_id, status=STATUS_NOT_RUN,
                    detail=refusal, refusal="guard"))
            if refusal not in run.notes:
                run.notes.append(refusal)
            logger.warning("capture queue: item %d refused before it started "
                           "(%d not run) — %s", index, remaining, refusal)
            persist(run)
            break

        if _stop:
            remaining = len(items) - index
            for j, later in enumerate(items[index:], start=index):
                run.outcomes.append(ItemOutcome(
                    index=j, name=later.name, kind=later.kind,
                    room_id=later.room_id, status=STATUS_STOPPED,
                    detail=mapping_refusals.queue_stopped(remaining),
                    refusal="stopped"))
            persist(run)
            break

        run.running_index = index
        started = clock()
        view, refusal = await _wait_for_session(item, sleep, clock)
        if view is None:
            run.outcomes.append(ItemOutcome(
                index=index, name=item.name, kind=item.kind,
                room_id=item.room_id, status=STATUS_NOT_RUN, detail=refusal,
                refusal="session", started_at=time.time(),
                seconds=clock() - started))
            # The session is the shared precondition for every remaining
            # item, so burning each one's own wait on the same missing
            # camera would turn one lost client into an hour of nothing.
            for j, later in enumerate(items[index + 1:], start=index + 1):
                run.outcomes.append(ItemOutcome(
                    index=j, name=later.name, kind=later.kind,
                    room_id=later.room_id, status=STATUS_NOT_RUN,
                    detail=refusal, refusal="session"))
            run.notes.append(refusal)
            persist(run)
            break

        if not run.first_pose:
            run.first_pose = view["pose_id"]
        pose_changed = bool(run.first_pose and view["pose_id"] != run.first_pose)

        outcome = await _execute(item)
        attempts = 1
        attempt_log = [_attempt_row(1, outcome)]
        while (outcome.status == capture_runs.STATUS_PARTIAL
               and attempts <= item.retries and not _stop):
            # A PARTIAL is the only retryable outcome: it means the run was
            # cut short by something that might not recur. A refusal is not
            # retried — an unlocked camera or a released room refuses
            # identically the second time and would just spend the night.
            view2, why = await _wait_for_session(item, sleep, clock)
            if view2 is None:
                # The retry never got a camera. Say so on the item rather
                # than leaving the partial looking like a choice nobody
                # revisited.
                attempt_log.append({"attempt": attempts + 1,
                                    "status": STATUS_NOT_RUN,
                                    "refusal": "session", "detail": why})
                break
            attempts += 1
            outcome = await _execute(item)
            attempt_log.append(_attempt_row(attempts, outcome))

        record = ItemOutcome(
            index=index, name=item.name, kind=item.kind, room_id=item.room_id,
            status=outcome.status, detail=outcome.detail,
            refusal=outcome.refusal, attempts=attempts,
            pose_id=outcome.pose_id or view["pose_id"],
            session_id=outcome.session_id or view["session_id"],
            pose_changed=pose_changed, started_at=time.time(),
            seconds=clock() - started, run=outcome.summary(),
            attempt_log=attempt_log)
        if pose_changed:
            note = mapping_refusals.pose_changed_note(run.first_pose,
                                                      view["pose_id"])
            record.detail = (record.detail + " " if record.detail else "") + note
            if note not in run.notes:
                run.notes.append(note)
        run.outcomes.append(record)
        persist(run)

    run.running_index = -1
    run.finished_at = time.time()
    persist(run)
    return run


async def start(items: list[QueueItem], *, label: str = "") -> QueueRun:
    """Start a queue as a background task and return its (empty) record. The
    caller gets an id immediately: an unattended caller is usually an ssh
    line that must not sit on a socket for forty minutes."""
    global _task
    if running():
        raise RuntimeError("a capture queue is already running")
    run = new_run(items, label)

    async def _go():
        try:
            await run_queue(items, label=label, run=run)
        except Exception:                              # noqa: BLE001
            logger.exception("capture queue: the run task failed")

    _task = asyncio.create_task(_go(), name="spectra-capture-queue")
    return run


# ── the store ──────────────────────────────────────────────────────────────

def load_queues(path=None) -> list[dict]:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            return list(json.load(fh).get("queues") or [])
    except Exception:                                  # noqa: BLE001
        logger.exception("capture queue: unreadable store %s", p)
        return []


def save_queue(run: QueueRun, path=None) -> dict:
    """Write after EVERY item, replacing this queue's own record in place.

    Written as it goes rather than at the end because nobody is watching: a
    queue killed by a reboot, a kill signal or a power cut has still
    explained everything it did up to that point, which is the difference
    between a night's data and a mystery."""
    p = _path(path)
    body = run.as_dict()
    kept = [q for q in load_queues(p) if q.get("id") != run.id]
    kept = (kept + [body])[-MAX_STORED_QUEUES:]
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="capture-queue", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"queues": kept}, fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return body


def status() -> dict:
    """What the page and an unattended caller both read."""
    return {"running": running(),
            "current": current.as_dict() if current is not None else None,
            "session": capture_runs.session_view(),
            "recent": list(reversed(load_queues()))[:5]}
