"""
SpotFX — Absorb Music's schedule (data/absorb-music-plan/report.md §9,
phase 3). His fourth ask, verbatim: "I can schedule it to run for periods of
times every evening."

NOTHING OPENS UNLESS HE CONFIGURED IT. AbsorbConfig ships `enabled: false`
and `windows: []`; a window opens on its own only when he has switched the
schedule on AND named at least one window. Either missing and `tick()`
returns before it reads anything else. His press (Start) is a separate door
and works either way.

HOUSE TIME. A window is `{days, start, end}` in America/New_York, evaluated
with `zoneinfo` — never the process's locale and never a fixed number of
seconds added to a timestamp (spectra/services/night_run.py's HOUSE_TZ rule,
for the same reason: his evening, his bedtime and his morning are wall-clock
events, and a DST change must land where his evening does). `days` name the
day a window STARTS, so Mon 21:30-00:30 runs Monday night into Tuesday.

THE PERSISTED ENTRY (tune_scheduler.py's shape). His windows are the entries
— `HH:MM` starts in AbsorbConfig, his store. This module's own store
(storage/absorb_schedule.json, AbsorbSchedule) remembers which OCCURRENCES it
has already acted on, keyed by the occurrence's start, and what happened. The
marker is written BEFORE the window is opened, so a restart — or a crash in
the middle of opening — can never open the same occurrence twice. The tick
runs inside services/absorb.py's supervisor, which main.py's lifespan arms,
AFTER the runner's own tick: a silence a dead process left behind is always
restored before the schedule may open anything.

ONE OPEN PER OCCURRENCE. Once an occurrence has opened (or been refused, or
he pressed Stop on it), the schedule never opens it again: a Stop at 22:00
must not be undone at 22:00:10. Two exceptions, both of which leave the house
untouched until they open:
  - his music is playing when the window starts. That is his Q4 ("resume")
    at the window's first second, so the window WAITS — the runner's own
    quiet clock (`resume_after_quiet_min` of confirmed quiet), never a
    refusal that loses the evening. Waiting is recorded.
  - SpotFX restarted while a window was still WAITING (it never touched the
    house). The schedule tries that occurrence again. A window that had
    OPENED and was cut by a restart is not reopened — a crash loop must not
    flap the house volume — and the record says so.
Every other refusal is final for that occurrence, recorded with its reason
(on the run, `state: "refused"`, and here), and the next occurrence tries
again: "did last night run, and if not, why not?" must be a read.

LATE IS FINE, TOO LATE IS NOT. If SpotFX was down at the start, the
occurrence opens when the schedule next ticks, as long as at least
`min_remaining_min` of it is left (the same bound a resume uses: silencing
the house for one song is not worth it). Less than that is recorded as
`too_late`.

THE END FOLLOWS HIS WINDOWS. While a scheduled window is open, its end is the
latest end of the configured occurrences that overlap it or touch its end —
so an overlapping or back-to-back window carries it on as one silence, and
an edit to tonight's end time moves tonight's close. With none (he deleted
it) the end stays as it was. A window that comes due while the last one is
still CLOSING waits for that close, then opens.
The close itself — the overrun grace and the ordered close — is the runner's
(services/absorb.py, `_window_end`).
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from models.absorb import DAYS, AbsorbConfig, AbsorbSchedule, AbsorbWindow, ScheduleOutcome
from services import absorb_store

logger = logging.getLogger(__name__)

HOUSE_TZ = "America/New_York"
SCHEDULE_TICK_S = 10.0           # how often the schedule looks (the runner ticks every 2 s)
FIRED_KEEP_DAYS = 8              # markers older than this can never match an occurrence again
DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

SENTENCES: dict[str, str] = {
    "too_late": "Too little of the window was left to open it ({left} min).",
    "restore_pending": ("The last window's house volume still wasn't back by the time this one "
                        "had too little left to run."),
    "joined": "An overlapping window was already open; it now runs until {end}.",
    "already_running": "Absorb was already running from your press.",
    "interrupted_opened": ("SpotFX restarted while this window was open. The schedule doesn't "
                           "reopen it — press Start to carry on."),
    "interrupted_waiting": ("SpotFX restarted while this window was waiting for your music to "
                            "stop. It never touched the house, so the schedule tries it again."),
}


def _tz() -> ZoneInfo:
    return ZoneInfo(HOUSE_TZ)


def _hm(text: str) -> tuple[int, int]:
    h, m = str(text).split(":", 1)
    return int(h), int(m)


def house_hhmm(ms: Optional[int]) -> str:
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000, _tz()).strftime("%H:%M")


@dataclass(frozen=True)
class Occurrence:
    """One evening of one window, resolved to epoch ms in house time."""
    start_ms: int
    end_ms: int
    label: str                    # "Mon 21:30–00:30"
    window_index: int

    def as_dict(self) -> dict:
        return asdict(self)


def _occurrence(w: AbsorbWindow, index: int, day: date, tz: ZoneInfo) -> Optional[Occurrence]:
    if DAYS[day.weekday()] not in w.days:
        return None
    sh, sm = _hm(w.start)
    eh, em = _hm(w.end)
    if (sh, sm) == (eh, em):
        return None                       # refused by the edit path; never opens
    start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
    end_day = day if (eh, em) > (sh, sm) else day + timedelta(days=1)
    end = datetime(end_day.year, end_day.month, end_day.day, eh, em, tzinfo=tz)
    s_ms, e_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    if e_ms <= s_ms:                      # a DST gap swallowed it
        return None
    return Occurrence(s_ms, e_ms, f"{DAY_LABELS[day.weekday()]} {w.start}–{w.end}", index)


def occurrences(windows: list[AbsorbWindow], now_ms: int, back_days: int = 2,
                ahead_days: int = 8) -> list[Occurrence]:
    """Every occurrence of every window whose start day is within
    [today - back_days, today + ahead_days], house time, by start."""
    tz = _tz()
    today = datetime.fromtimestamp(now_ms / 1000, tz).date()
    out: list[Occurrence] = []
    for offset in range(-back_days, ahead_days + 1):
        day = today + timedelta(days=offset)
        for i, w in enumerate(windows):
            o = _occurrence(w, i, day, tz)
            if o is not None:
                out.append(o)
    out.sort(key=lambda o: (o.start_ms, o.window_index))
    return out


def open_occurrences(windows: list[AbsorbWindow], now_ms: int) -> list[Occurrence]:
    """The occurrences `now_ms` falls inside: start <= now < end."""
    return [o for o in occurrences(windows, now_ms, ahead_days=0)
            if o.start_ms <= now_ms < o.end_ms]


def next_occurrence(windows: list[AbsorbWindow], now_ms: int) -> Optional[Occurrence]:
    """The next occurrence to START after `now_ms`."""
    for o in occurrences(windows, now_ms, back_days=0):
        if o.start_ms > now_ms:
            return o
    return None


def window_label(w: AbsorbWindow) -> str:
    days = [DAY_LABELS[DAYS.index(d)] for d in DAYS if d in w.days]
    every = "every day" if len(days) == 7 else ", ".join(days)
    return f"{every} {w.start}–{w.end}"


def problems(windows: list[AbsorbWindow]) -> list[str]:
    """What the edit path refuses about a set of windows, by name: a window
    that could never open is a typo, never a schedule."""
    out = []
    for i, w in enumerate(windows):
        if not w.days:
            out.append(f"window {i + 1} ({w.start}–{w.end}) has no days")
        if w.start == w.end:
            out.append(f"window {i + 1} starts and ends at {w.start}")
    return out


def sentence(code: str, **fmt: Any) -> str:
    base = SENTENCES.get(code, code)
    try:
        return base.format(**fmt)
    except (KeyError, IndexError):
        return base


# ── the scheduler ────────────────────────────────────────────────────────────

class Scheduler:
    """One per process (`scheduler`); `tick(runner)` from the supervisor."""

    def __init__(self) -> None:
        self._schedule: Optional[AbsorbSchedule] = None
        self._next_check = 0.0

    def _load(self) -> AbsorbSchedule:
        if self._schedule is None:
            self._schedule = absorb_store.load_schedule()
        return self._schedule

    def _save(self) -> None:
        try:
            absorb_store.save_schedule(self._load())
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("Absorb: could not save the schedule: %s", exc)

    def _record(self, occ: Occurrence, now_ms: int, outcome: str, reason: str = "",
                detail: str = "", run_id: str = "") -> ScheduleOutcome:
        entry = ScheduleOutcome(
            occurrence_start_ms=occ.start_ms, occurrence_end_ms=occ.end_ms, label=occ.label,
            at_ms=now_ms, outcome=outcome, reason=reason, detail=detail, run_id=run_id)
        sched = self._load()
        sched.outcomes.insert(0, entry)
        logger.info("Absorb schedule: %s — %s%s", occ.label, outcome,
                    f" ({detail})" if detail else "")
        return entry

    def _fire(self, occ: Occurrence, now_ms: int) -> None:
        sched = self._load()
        horizon = now_ms - FIRED_KEEP_DAYS * 86_400_000
        sched.fired = [s for s in sched.fired if s >= horizon and s != occ.start_ms]
        sched.fired.append(occ.start_ms)

    def fired(self, start_ms: int) -> bool:
        return start_ms in self._load().fired

    async def tick(self, runner: Any) -> Optional[ScheduleOutcome]:
        """Open the occurrence that is due, if any; keep an open scheduled
        window's end following his windows. At most one open per tick."""
        d = runner.deps
        mono = d.monotonic()
        if mono < self._next_check:
            return None
        self._next_check = mono + SCHEDULE_TICK_S
        cfg = absorb_store.load_config()
        if not cfg.enabled or not cfg.windows:
            return None
        now = d.now_ms()
        await self._follow(runner, cfg, now)
        due = open_occurrences(cfg.windows, now)
        for occ in due:
            if not self.fired(occ.start_ms):
                return await self._act(runner, cfg, occ, now)
        return None

    async def _follow(self, runner: Any, cfg: AbsorbConfig, now: int) -> None:
        """An open scheduled window ends at the latest end of the configured
        occurrences that overlap it or TOUCH its end (start <= its end) and
        are not over: an overlapping or back-to-back window carries it on —
        one continuous silence, never a restore and a re-silence a second
        apart — and an edit to tonight's own end moves it. With none (he
        deleted it) the end stays. This runs every schedule tick, so it
        always gets a look in the SCHEDULE_TICK_S before the end."""
        run = runner.run
        if run is None or not runner.open_window or run.started_by != "schedule":
            return
        end = (run.window or {}).get("end")
        if end is None or runner.closing is not None:
            return
        own = (run.window or {}).get("scheduled_start")
        # its own occurrence counts even once its (edited) end has passed:
        # moving tonight's end to 22:30 at 22:40 closes it now
        touching = [o for o in occurrences(cfg.windows, now, ahead_days=1)
                    if o.start_ms <= end and (o.end_ms > now or o.start_ms == own)]
        if not touching:
            return
        new_end = max(o.end_ms for o in touching)
        if new_end != end:
            await runner.move_window_end(new_end, "the schedule changed")

    async def _act(self, runner: Any, cfg: AbsorbConfig, occ: Occurrence,
                   now: int) -> Optional[ScheduleOutcome]:
        run = runner.run
        if runner.open_window and runner.closing is not None:
            # the last window is still closing (finishing a song, waiting on
            # a capture): open this one once that close is done, not into it
            return None
        if runner.open_window:
            self._fire(occ, now)
            if run.started_by == "schedule" and (run.window or {}).get("end") is not None:
                end = max(occ.end_ms, run.window["end"])
                if end != run.window["end"]:
                    await runner.move_window_end(end, f"{occ.label} overlaps it")
                entry = self._record(occ, now, "joined", "joined",
                                     sentence("joined", end=house_hhmm(end)), run.id)
            else:
                entry = self._record(occ, now, "already_running", "already_running",
                                     sentence("already_running"), run.id)
            self._save()
            return entry
        left_ms = occ.end_ms - now
        min_ms = cfg.min_remaining_min * 60_000
        if runner.deps.guard.holding():
            # The last window's silence isn't restored yet (the supervisor is
            # retrying it). Opening would be refused "restore_pending" and the
            # evening lost — wait for the restore instead, while there is time.
            if left_ms >= min_ms:
                return None
            self._fire(occ, now)
            entry = self._record(occ, now, "too_late", "restore_pending",
                                 sentence("restore_pending"))
            self._save()
            return entry
        if left_ms < min_ms:
            self._fire(occ, now)
            entry = self._record(occ, now, "too_late", "too_late",
                                 sentence("too_late", left=max(0, left_ms // 60_000)))
            self._save()
            return entry
        # The marker lands BEFORE the open: a crash mid-open can't reopen it.
        self._fire(occ, now)
        self._save()
        late_min = (now - occ.start_ms) // 60_000
        window = {"start": now, "end": occ.end_ms, "scheduled_start": occ.start_ms,
                  "label": occ.label}
        try:
            result = await runner.start(started_by="schedule", window=window,
                                        wait_if_listening=True)
        except Exception as exc:                                  # noqa: BLE001
            logger.exception("Absorb schedule: opening %s failed", occ.label)
            result = {"status": "refused", "reason": "error", "detail": str(exc)[:160],
                      "run": {}}
        status = str(result.get("status") or "")
        outcome = {"running": "opened", "waiting": "waiting", "refused": "refused",
                   "ended": "ended", "already_running": "already_running"}.get(status, status)
        detail = str(result.get("detail") or "")
        if outcome == "opened" and late_min >= 1:
            detail = f"opened {late_min} min after {house_hhmm(occ.start_ms)}"
        entry = self._record(occ, now, outcome, str(result.get("reason") or ""), detail,
                             str((result.get("run") or {}).get("run_id") or ""))
        self._save()
        return entry

    # ── startup ─────────────────────────────────────────────────────────────

    def arm(self, recovered_run_id: Optional[str] = None,
            now_ms: Optional[int] = None) -> None:
        """main.py's lifespan, right after `absorb.recover_orphaned_run()`.
        Prunes old markers, says what a restart did to a scheduled window,
        and logs what the schedule will do next. Opens nothing."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        sched = self._load()
        horizon = now - FIRED_KEEP_DAYS * 86_400_000
        sched.fired = [s for s in sched.fired if s >= horizon]
        if recovered_run_id:
            self._note_restart(recovered_run_id, now)
        self._save()
        cfg = absorb_store.load_config()
        nxt = next_occurrence(cfg.windows, now) if cfg.windows else None
        if not cfg.enabled or not cfg.windows:
            logger.info("Absorb schedule armed — off (%s, %d window(s))",
                        "switched on" if cfg.enabled else "switched off", len(cfg.windows))
        else:
            logger.info("Absorb schedule armed — %d window(s); next %s",
                        len(cfg.windows), nxt.label if nxt else "none in the next week")

    def _note_restart(self, run_id: str, now: int) -> None:
        try:
            run = absorb_store.latest_run()
        except Exception:                                         # noqa: BLE001
            return
        if run is None or run.id != run_id or run.started_by != "schedule":
            return
        start = (run.window or {}).get("scheduled_start")
        end = (run.window or {}).get("end")
        if not start:
            return
        occ = Occurrence(int(start), int(end or start), str(run.window.get("label") or ""), -1)
        sched = self._load()
        if run.opened_ms:
            if start not in sched.fired:
                sched.fired.append(int(start))
            self._record(occ, now, "interrupted", "process_restarted",
                         sentence("interrupted_opened"), run.id)
        else:
            sched.fired = [s for s in sched.fired if s != start]
            self._record(occ, now, "interrupted", "process_restarted",
                         sentence("interrupted_waiting"), run.id)


scheduler = Scheduler()


def arm(recovered_run_id: Optional[str] = None) -> None:
    scheduler.arm(recovered_run_id)


def status(now_ms: Optional[int] = None, limit: int = 20) -> dict:
    """What the schedule is and what it last did — GET /api/absorb/schedule.
    Reads only."""
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    cfg = absorb_store.load_config()
    on = bool(cfg.enabled and cfg.windows)
    nxt = next_occurrence(cfg.windows, now) if cfg.windows else None
    sched = absorb_store.load_schedule()
    # how each run the schedule opened finally went, joined by id — so
    # "waiting" at 21:30 reads together with what became of that evening
    runs: dict[str, dict] = {}
    latest = absorb_store.latest_run()
    if latest is not None:
        runs[latest.id] = absorb_store.compact(latest)
    for r in absorb_store.earlier_runs():
        runs.setdefault(str(r.get("id")), r)
    keep = ("state", "end_reason", "end_detail", "opened_ms", "counts", "head_rate")
    shown = []
    for o in sched.outcomes[:max(0, limit)]:
        entry = o.model_dump(mode="json")
        r = runs.get(o.run_id) if o.run_id else None
        entry["run"] = {k: r.get(k) for k in keep} if r else None
        shown.append(entry)
    return {
        "enabled": cfg.enabled,
        "active": on,
        "house_tz": HOUSE_TZ,
        "windows": [{"index": i, "days": w.days, "start": w.start, "end": w.end,
                     "label": window_label(w)} for i, w in enumerate(cfg.windows)],
        "open_now": [dict(o.as_dict(), fired=o.start_ms in sched.fired)
                     for o in open_occurrences(cfg.windows, now)],
        "next": (dict(nxt.as_dict(), in_s=max(0, (nxt.start_ms - now) // 1000))
                 if nxt else None),
        "overrun_grace_min": cfg.overrun_grace_min,
        "outcomes": shown,
    }
