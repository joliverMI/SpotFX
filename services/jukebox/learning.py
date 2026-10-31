"""
THE LEARNING QUEUE — absorb-then-queue (data/jukebox-plan/report.md §9
phase 4, PR 4.2): a song the lights haven't learned is learned FIRST on the
hidden player (the capture lane, capture_lane/), and plays once it is.

THE RULE (the study's Q1 default, data/jukebox-study/report.md §3.2/§6):
  * A request HOLDS ITS PLACE from the moment it is made. While it is being
    learned it isn't `ready` (night.py's commit gate), so a slot that reaches
    it passes to the next ready song — it slides back, never out.
  * The host can let any of them through un-analysed at once
    (`play_unanalysed`), and the program lets the first one through on its
    own only when nothing else would play (`why: "dry"`).
  * WITHOUT A HIDDEN PLAYER — the lane not running or not answering, account
    B not signed in, the lane reporting the hidden player missing — or with
    the show's `learn_first` off, nothing waits: a song plays un-analysed and
    is learned as it plays, the plan's own fallback. A lane that reports the
    hidden player unusable is left alone for DOWN_BACKOFF_S.
  * A song that fails MAX_ATTEMPTS times is PARKED: the plan's §1 rule 5
    ("you get it back if ... it can't be learned") — a paid song is
    refunded at once (`refund_due`, written by services/jukebox/guests.py's
    settling, sticky whatever happens next) — and, per the study's "parked
    → master: play un-analysed | remove", it waits for the host. `relearn`
    gives it fresh tries.

ONE SONG AT A TIME, IN LINE ORDER: the lane learns one song, the first
waiting one in the line (the one that would play soonest). A lane job nobody
is waiting for any more — removed, sent to Spotify, let through un-analysed —
is cancelled, so the house never learns a song twice at once.

ETAs (the study's formula): the song being learned finishes at its start +
its length + the lane's measured overhead (setup, tail, save, librosa); each
waiting song ahead adds (length + overhead) ÷ the lane's recent success
rate. Every number is read off the lane's own outcomes, with stated priors
until it has some (DEFAULT_OVERHEAD_S, DEFAULT_SUCCESS).

It runs only while a night runs, never touches Spotify itself, and holds the
night's lock only to edit the line — every lane call and file read happens
outside it.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from models.jukebox import LearnState, LineEntry

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_S = 3.0
IDLE_POLL_S = 10.0
DOWN_BACKOFF_S = 300.0
DEFAULT_OVERHEAD_S = 85.0      # setup + tail + save + librosa: the study's ~75 s finalize, plus a start
DEFAULT_SUCCESS = 0.75         # the study's measured first-try rate, until the lane has its own
MIN_SUCCESS = 0.3
RECENT_OUTCOMES = 12

# Outcomes that say the hidden player can't be used at all (no song fault):
# the song goes back to waiting, untried, and the lane is left alone a while.
LANE_DOWN = frozenset({"not_signed_in", "wrong_account", "cannot_check_account",
                       "device_missing", "device_ambiguous", "device_restricted", "no_audio"})
# Outcomes that aren't the song's fault and don't use up a try.
NOT_A_TRY = frozenset({"cancelled", "already_learned"})

WORDS = {
    "lane_off": "The hidden player isn't running, so new songs play un-analysed.",
    "not_signed_in": "The capture account isn't signed in, so new songs play un-analysed.",
    "learning_off": "Learning first is off, so new songs play un-analysed.",
}


def gate(entry: LineEntry, *, learn_first: bool, available: bool) -> bool:
    """Is this waiting song READY to be sent to Spotify? (night.py commits
    only ready songs.)"""
    if entry.known:
        return True
    st = entry.learn.state if entry.learn else "waiting"
    if st in ("learned", "unanalysed"):
        return True
    if st == "parked":
        return False                    # the host decides (or the music runs dry)
    return not (learn_first and available)


@dataclass
class LearnerDeps:
    lane: Any
    runner: Callable[[], Any]
    known: Callable[[str], bool]
    signed_in: Callable[[], bool]
    show: Callable[[], Any]
    after_learned: Callable[[str], Awaitable[None]]
    clock: Callable[[], float] = time.monotonic
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread


def production_deps() -> LearnerDeps:
    from api import spotify_capture
    from services.jukebox import library, night, store
    from services.jukebox.lane_client import LaneClient

    async def after_learned(uri: str) -> None:
        # What a normal capture does on success (audio_shape_service): off the
        # recapture playlist, the flag cleared, AI triggers if he has them on.
        from models.state import state as app_state
        from services import audio_shape_service as shapes
        await shapes._after_successful_capture(uri)
        if app_state.auto_generate_enabled:
            asyncio.create_task(shapes._auto_generate_for_uri(uri))

    return LearnerDeps(lane=LaneClient(), runner=lambda: night.runner, known=library.known,
                       signed_in=lambda: bool(spotify_capture.status()["signed_in"]),
                       show=store.load_show, after_learned=after_learned)


def _lane_job(lane: dict) -> dict:
    return (lane or {}).get("job") or {}


def lane_numbers(outcomes: list[dict]) -> tuple[float, float]:
    """(overhead_s, success) from the lane's own recent outcomes: overhead is
    a song's whole job time beyond its length, success the share of songs
    that learned (the lane's own downs and our cancels don't count)."""
    tries = [o for o in outcomes[-RECENT_OUTCOMES:]
             if o.get("reason") not in LANE_DOWN | NOT_A_TRY]
    oks = [o for o in tries if o.get("status") == "ok"]
    over = [(o["ended_at_ms"] - o["started_at_ms"]) / 1000.0 - o.get("covered_ms", 0) / 1000.0
            for o in oks if o.get("ended_at_ms") is not None and o.get("started_at_ms") is not None]
    overhead = statistics.median(over) if over else DEFAULT_OVERHEAD_S
    success = len(oks) / len(tries) if tries else DEFAULT_SUCCESS
    return max(0.0, overhead), max(MIN_SUCCESS, success)


def etas(order: list[LineEntry], lane: dict, now_ms: int) -> dict[str, int]:
    """Seconds until each song in the learning order is learned."""
    overhead, success = lane_numbers((lane or {}).get("outcomes") or [])
    job = _lane_job(lane)
    out: dict[str, int] = {}
    t = 0.0
    for e in order:
        if e.learn and e.learn.state == "learning" and job.get("job_id") == e.learn.job_id:
            started = (lane or {}).get("job_started_at_ms") or e.learn.started_ms or now_ms
            t = max(t, (started - now_ms) / 1000.0 + e.duration_ms / 1000.0 + overhead)
        else:
            t += (e.duration_ms / 1000.0 + overhead) / success
        out[e.id] = max(0, round(t))
    return out


class Learner:
    def __init__(self, deps: Optional[LearnerDeps] = None) -> None:
        self._deps = deps
        self.available = False
        self.reason = WORDS["lane_off"]
        self.lane: dict = {}
        self.down_until = 0.0
        self.down_reason = ""
        self._view: dict[str, dict] = {}
        self._kick: Optional[asyncio.Event] = None
        self.log: list[str] = []

    @property
    def deps(self) -> LearnerDeps:
        if self._deps is None:
            self._deps = production_deps()
        return self._deps

    def _note(self, text: str) -> None:
        self.log.append(text)
        del self.log[:-40]
        logger.info("Jukebox learning: %s", text)

    # ── what the night asks ─────────────────────────────────────────────────

    def ready_at_add(self, entry: LineEntry) -> bool:
        """A song just added: ready now, or waiting to be learned? From the
        last poll (no I/O); the next pass settles it."""
        try:
            learn_first = bool(self.deps.show().learn_first)
        except Exception:                                         # noqa: BLE001
            learn_first = True
        ready = gate(entry, learn_first=learn_first, available=self.available)
        if not ready and entry.learn is None:
            entry.learn = LearnState()
        self.kick()
        return ready

    def view(self) -> dict[str, dict]:
        """Per waiting song: where it stands and when it will be learned —
        what the guest page shows on a guest's own songs."""
        return dict(self._view)

    def kick(self) -> None:
        try:
            if self._kick is None:
                self._kick = asyncio.Event()
            self._kick.set()
        except Exception:                                         # noqa: BLE001
            pass

    # ── the host's two buttons ──────────────────────────────────────────────

    async def play_unanalysed(self, entry_id: str) -> dict:
        def edit(r) -> dict:
            e = r._entry(entry_id)
            if e is None or e.state != "queued":
                return {"status": "refused", "reason": "not_waiting"}
            if e.ready and (e.known or (e.learn and e.learn.state in ("learned", "unanalysed"))):
                return {"status": "unchanged", "entry": e.model_dump(mode="json")}
            e.learn = (e.learn or LearnState()).model_copy(update={"state": "unanalysed", "why": "host"})
            e.ready = True
            r._log(f"the host let {e.title or e.uri} play un-analysed")
            return {"status": "unanalysed", "entry": e.model_dump(mode="json")}
        out = await self.deps.runner().edit_line(edit)
        self.kick()
        return out or {"status": "refused", "reason": "not_running"}

    async def relearn(self, entry_id: str) -> dict:
        def edit(r) -> dict:
            e = r._entry(entry_id)
            if e is None or e.state != "queued":
                return {"status": "refused", "reason": "not_waiting"}
            if e.known:
                return {"status": "refused", "reason": "already_learned"}
            old = e.learn or LearnState()
            e.learn = LearnState(refund_due=old.refund_due)
            e.ready = False
            r._log(f"the host asked for {e.title or e.uri} to be learned again")
            return {"status": "waiting", "entry": e.model_dump(mode="json")}
        out = await self.deps.runner().edit_line(edit)
        self.kick()
        return out or {"status": "refused", "reason": "not_running"}

    # ── one pass ────────────────────────────────────────────────────────────

    async def tick(self) -> None:
        d = self.deps
        runner = d.runner()
        if not runner.running:
            self._view = {}
            return
        show = d.show()
        from services.jukebox.lane_client import LaneBusy, LaneUnavailable
        lane: Optional[dict] = None
        why = ""
        try:
            lane = await d.lane.status()
        except LaneUnavailable as exc:
            why = str(exc)
        now = d.clock()
        signed = bool(d.signed_in())
        if lane is None:
            self.available, self.reason = False, WORDS["lane_off"]
        elif not signed:
            self.available, self.reason = False, WORDS["not_signed_in"]
        elif now < self.down_until:
            self.available, self.reason = False, self.down_reason
        else:
            self.available, self.reason = True, ""
        if why:
            logger.debug("Jukebox learning: %s", why)
        self.lane = lane or {}
        learn_first = bool(show.learn_first)
        if not learn_first:
            self.reason = WORDS["learning_off"]

        uris = {e.uri for e in runner.night.line
                if e.state == "queued" and not e.known
                or (e.learn and e.learn.state == "learning")}
        known_now: dict[str, bool] = {}
        for uri in uris:
            try:
                known_now[uri] = bool(await d.to_thread(d.known, uri))
            except Exception:                                     # noqa: BLE001
                known_now[uri] = False
        outcomes = {o.get("job_id"): o for o in self.lane.get("outcomes") or []}
        lane_job = _lane_job(self.lane)
        lane_idle = lane is not None and self.lane.get("state") == "idle"
        learned: list[str] = []
        cancel: list[str] = []
        downed: list[str] = []

        def edit(r) -> Optional[dict]:
            line = r.night.line
            for e in line:
                if known_now.get(e.uri) and not e.known:
                    e.known = True
            # 1. what the lane did with the songs it was learning
            wanted: set[str] = set()
            for e in line:
                L = e.learn
                if L is None or L.state != "learning":
                    continue
                o = outcomes.get(L.job_id)
                if o is not None:
                    self._finish(r, e, o, known_now.get(e.uri, False), learned, downed)
                elif lane_job.get("job_id") == L.job_id:
                    if e.state == "queued":
                        wanted.add(L.job_id)
                    else:
                        cancel.append(L.job_id)       # sent, removed, playing: not needed
                        L.state = "waiting"
                elif lane is not None:
                    L.state = "waiting"               # the lane forgot it (a restart)
            if lane_job.get("job_id") and lane_job["job_id"] not in wanted \
                    and lane_job["job_id"] not in cancel:
                cancel.append(lane_job["job_id"])     # nobody is waiting for it any more
            # 2. who is ready
            for e in line:
                if e.state != "queued":
                    continue
                if e.known and e.learn and e.learn.state not in ("learned", "unanalysed"):
                    e.learn.state = "learned"
                if not e.known and e.learn is None:
                    e.learn = LearnState()
                e.ready = gate(e, learn_first=learn_first, available=self.available)
            # 3. nothing else would play: let the first one through
            if not r._project(1):
                for e in line:
                    if e.state == "queued" and not e.ready and not e.held:
                        e.learn = (e.learn or LearnState()).model_copy(
                            update={"state": "unanalysed", "why": "dry"})
                        e.ready = True
                        r._log(f"nothing else would play, so {e.title or e.uri} plays un-analysed")
                        break
            # 4. the next song to learn
            job = None
            busy = any(e.learn and e.learn.state == "learning" and e.state == "queued"
                       for e in line)
            if learn_first and self.available and lane_idle and not busy and not cancel:
                for e in line:
                    if (e.state == "queued" and not e.known and e.learn is not None
                            and e.learn.state == "waiting"):
                        e.learn.state = "learning"
                        e.learn.job_id = uuid.uuid4().hex[:12]
                        e.learn.started_ms = d.now_ms()
                        job = {"job_id": e.learn.job_id, "uri": e.uri, "title": e.title,
                               "artist": e.artist, "duration_ms": e.duration_ms}
                        r._log(f"learning {e.title or e.uri} on the hidden player")
                        break
            return job

        job = await runner.edit_line(edit)
        for jid in cancel:
            try:
                await d.lane.cancel(jid)
            except LaneUnavailable:
                pass
        if job:
            try:
                await d.lane.learn(job)
            except (LaneBusy, LaneUnavailable) as exc:
                self._note(f"the hidden player didn't take {job['title'] or job['uri']} ({exc})")

                def back(r) -> None:
                    for e in r.night.line:
                        if e.learn and e.learn.job_id == job["job_id"] and e.learn.state == "learning":
                            e.learn.state = "waiting"
                await runner.edit_line(back)
        for uri in learned:
            try:
                await d.after_learned(uri)
            except Exception as exc:                              # noqa: BLE001
                logger.warning("Jukebox learning: follow-up after learning %s failed: %s", uri, exc)
        self._refresh_view(runner)

    def _finish(self, r, e: LineEntry, o: dict, known: bool,
                learned: list[str], downed: list[str]) -> None:
        L = e.learn
        reason = o.get("reason") or ""
        name = e.title or e.uri
        if o.get("status") == "ok" or known:
            L.state = "learned"
            e.known = True
            learned.append(e.uri)
            r._log(f"{name} is learned")
            return
        if reason in LANE_DOWN:
            L.state = "waiting"
            downed.append(reason)
            self._down(reason)               # before this pass dispatches anything
            r._log(f"the hidden player can't learn right now ({reason}); {name} waits")
            return
        if reason in NOT_A_TRY:
            L.state = "waiting"
            return
        L.attempts += 1
        L.reason, L.detail = reason, str(o.get("detail") or "")[:200]
        if L.attempts >= MAX_ATTEMPTS:
            L.state = "parked"
            L.refund_due = bool(e.paid_seq)
            r._log(f"{name} couldn't be learned ({reason}) after {L.attempts} tries; "
                   "it waits for the host")
        else:
            L.state = "waiting"
            r._log(f"learning {name} failed ({reason}); it will be tried again")

    def _down(self, reason: str) -> None:
        """The lane said the hidden player can't be used: leave it alone for
        DOWN_BACKOFF_S, and say why."""
        self.down_until = self.deps.clock() + DOWN_BACKOFF_S
        sentences = self.lane.get("sentences") or {}
        self.down_reason = (f"{sentences.get(reason, reason)} New songs play un-analysed "
                            "for a few minutes.")
        self.available, self.reason = False, self.down_reason

    def learning_order(self, runner) -> list[LineEntry]:
        line = [e for e in runner.night.line if e.state == "queued" and e.learn
                and not e.known and e.learn.state in ("learning", "waiting")]
        line.sort(key=lambda e: e.learn.state != "learning")
        return line

    def _refresh_view(self, runner) -> None:
        order = self.learning_order(runner)
        times = etas(order, self.lane, self.deps.now_ms()) if self.available else {}
        view: dict[str, dict] = {}
        for e in runner.night.line:
            if e.state != "queued" or e.learn is None or e.known:
                continue
            view[e.id] = {"state": e.learn.state, "eta_s": times.get(e.id),
                          "attempts": e.learn.attempts, "ready": e.ready}
        self._view = view

    # ── what the master view reads ──────────────────────────────────────────

    def status(self) -> dict:
        d = self.deps
        runner = d.runner()
        try:
            learn_first = bool(d.show().learn_first)
        except Exception:                                         # noqa: BLE001
            learn_first = True
        lane = self.lane or {}
        out = {"available": self.available, "reason": self.reason, "learn_first": learn_first,
               "max_attempts": MAX_ATTEMPTS,
               "lane": {"state": lane.get("state", "off"), "job": lane.get("job"),
                        "progress_ms": lane.get("progress_ms")},
               "queue": [], "parked": [], "log": self.log[-20:]}
        overhead, success = lane_numbers(lane.get("outcomes") or [])
        out["numbers"] = {"overhead_s": round(overhead), "success": round(success, 2)}
        if not getattr(runner, "running", False):
            return out
        times = etas(self.learning_order(runner), lane, d.now_ms()) if self.available else {}
        for e in self.learning_order(runner):
            out["queue"].append(_row(e, times.get(e.id)))
        for e in runner.night.line:
            if e.state == "queued" and e.learn and e.learn.state == "parked" and not e.known:
                out["parked"].append(_row(e, None))
        return out

    async def run_supervised(self) -> None:
        """Its own task: a pass every POLL_S while a night runs, sooner when
        kicked (a song added, a host button); IDLE_POLL_S otherwise."""
        if self._kick is None:
            self._kick = asyncio.Event()
        while True:
            try:
                running = bool(getattr(self.deps.runner(), "running", False))
                try:
                    await asyncio.wait_for(self._kick.wait(), timeout=POLL_S if running else IDLE_POLL_S)
                except asyncio.TimeoutError:
                    pass
                self._kick.clear()
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:                                     # noqa: BLE001
                logger.exception("Jukebox learning: a pass failed")
                await asyncio.sleep(POLL_S)


def _row(e: LineEntry, eta_s: Optional[int]) -> dict:
    L = e.learn or LearnState()
    return {"entry_id": e.id, "uri": e.uri, "title": e.title, "artist": e.artist,
            "duration_ms": e.duration_ms, "added_by": e.added_by, "state": L.state,
            "attempts": L.attempts, "reason": L.reason, "detail": L.detail,
            "eta_s": eta_s, "ready": e.ready, "held": e.held}


learner = Learner()
