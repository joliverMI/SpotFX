"""AV-sync FLASH PATTERN driver — the LIGHT REFERENCE for a precise
measurement: drives every live virtual through a short, RANDOM-timed
on/off white pattern over SPECTRA's one write seam (fx_seam), recording
the server monotonic time of every edge, then lands the room back
EXACTLY where it was.

Why a pattern at all: the passive reference (the show's own executor
writes, av_sync_session.ShowReference) is free but weak — a 20 s drift
glide has no edge, a colour change may not move luminance, and the
engine can't know which writes the camera can see. A dozen seconds of
crisp random edges is what turns "a number" into "a number with a tight,
stated error bar". Random holds (150-450 ms, av_sync_correlate.
random_edge_schedule) are load-bearing: a periodic flash correlates
equally well at every multiple of its period and is REFUSED as ambiguous
by the correlator — by design, not by accident.

THE ROOM-SAFETY CONTRACT (mirrors room_preview.py / flare_preview_hold.py):
  * snapshot = EXACTLY what fx_seam.get_virtuals() read the instant the
    pattern started (type + config per virtual), replayed verbatim via
    fx_seam.apply_writes(transition_ms=REVERT_TRANSITION_MS) on revert —
    the same 1 ms "retarget any dangling tween" convention
    flare_preview_hold established; never transition_ms=0.
  * preview_pause armed for the pattern's duration (+ margin), so the
    show's own automatic scene/response/set changes can't land mid-
    pattern and corrupt the reference; cleared on revert.
  * bounded BY CONSTRUCTION: MAX_DURATION_S caps one run; nothing a
    client sends can extend a running pattern — a new run is a new,
    explicit start after the previous one reverted.
  * the snapshot is persisted (AV_SYNC_PATTERN_FILE) the instant a run
    starts and cleared on revert; recover_stale_pattern() (spectra/app.py
    lifespan, after resume_own_room) lands a leftover snapshot back at
    startup — a restart mid-pattern must not strand the room white.
  * exactly one run at a time (a room has one Admiral); start() while a
    run is live reverts the old one first, like room_preview.

What a flash IS: the first write switches each virtual to the vendored
`singleColor` effect at PATTERN_COLOR (one type switch), then every edge
writes only `brightness` 0.0/PATTERN_BRIGHTNESS on that same type — a
config merge, no further type switches, landing on the next render frame
(transition_ms=1, fx_executor's own JUMP_MS convention). The edge time
recorded is the midpoint of [before the write call, after it returned];
the half-width is kept per edge (`write_half_width_s`) and folded into
the confidence statement as the write-landing uncertainty.

Which virtuals: every virtual fx_seam.get_virtuals() reports ACTIVE with
an effect — the phone only measures what its camera can see, so flashing
the whole room and letting him AIM is the feature (point at the crystal,
point at the sconces). A later per-category selector is a one-line
filter here if he asks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from spectra import config
from spectra.services.av_sync_correlate import random_edge_schedule

logger = logging.getLogger(__name__)

DEFAULT_DURATION_S = 12.0
MAX_DURATION_S = 30.0
PAUSE_MARGIN_S = 5.0
REVERT_TRANSITION_MS = 1
EDGE_TRANSITION_MS = 1
PATTERN_EFFECT_TYPE = "singleColor"
PATTERN_COLOR = "#ffffff"
PATTERN_BRIGHTNESS = 0.85


@dataclass
class PatternRun:
    seed: int
    started_at: float                     # server monotonic, first write
    duration_s: float
    virtual_ids: list[str]
    edges: list[tuple[float, int]] = field(default_factory=list)   # (t_server, state)
    write_half_width_s: list[float] = field(default_factory=list)
    finished_at: Optional[float] = None
    aborted: bool = False

    @property
    def done(self) -> bool:
        return self.finished_at is not None

    def as_dict(self) -> dict:
        return {
            "seed": self.seed, "started_at": self.started_at,
            "duration_s": self.duration_s, "virtual_ids": list(self.virtual_ids),
            "edge_count": len(self.edges), "done": self.done, "aborted": self.aborted,
            "max_write_half_width_ms": (round(max(self.write_half_width_s) * 1000, 1)
                                        if self.write_half_width_s else None),
        }


class PatternDriver:
    """One driver per process (module-level `driver` below); tests build
    their own with fake seams."""

    def __init__(self, *, get_virtuals: Callable | None = None,
                 apply_writes: Callable | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], "asyncio.Future"] | None = None) -> None:
        self._get_virtuals = get_virtuals
        self._apply_writes = apply_writes
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, dict] | None = None
        self._run: Optional[PatternRun] = None
        self._task: Optional[asyncio.Task] = None
        self._on_edge: Optional[Callable[[float, int], None]] = None
        self._on_done: Optional[Callable[[PatternRun], None]] = None

    # ── seams ─────────────────────────────────────────────────────────────
    async def _virtuals(self) -> dict:
        if self._get_virtuals is not None:
            return await self._get_virtuals()
        from spectra.services import fx_seam
        return await fx_seam.get_virtuals()

    async def _write(self, writes: list[dict], transition_ms: int) -> None:
        if self._apply_writes is not None:
            await self._apply_writes(writes, transition_ms=transition_ms)
            return
        from spectra.services import fx_seam
        await fx_seam.apply_writes(writes, transition_ms=transition_ms)

    # ── status ────────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return self._snapshot is not None

    @property
    def run(self) -> Optional[PatternRun]:
        return self._run

    def status(self) -> dict:
        return {"active": self.active,
                "run": self._run.as_dict() if self._run else None}

    # ── start / stop ──────────────────────────────────────────────────────
    async def start(self, *, duration_s: float = DEFAULT_DURATION_S, seed: int | None = None,
                    on_edge: Callable[[float, int], None] | None = None,
                    on_done: Callable[[PatternRun], None] | None = None) -> PatternRun:
        duration_s = float(min(max(1.0, duration_s), MAX_DURATION_S))
        seed = int(seed if seed is not None else (time.time_ns() % (2 ** 31)))
        # a live run is cancelled OUTSIDE the lock: its own finally block
        # reverts under the lock, so awaiting it while holding the lock
        # would deadlock (found by tests/test_av_sync_session.py, not in
        # his room)
        await self._cancel_run()
        async with self._lock:
            if self._snapshot is not None:
                await self._revert_locked("restart")
            live = await self._virtuals()
            snapshot: dict[str, dict] = {}
            for vid, v in (live or {}).items():
                eff = (v or {}).get("effect") or {}
                if not (v or {}).get("active", True) or not eff.get("type"):
                    continue
                snapshot[vid] = {"type": eff["type"], "config": dict(eff.get("config") or {})}
            if not snapshot:
                raise RuntimeError("no active virtual with an effect to flash — "
                                   "is SPECTRA driving the room?")
            self._snapshot = snapshot
            _save_snapshot(snapshot)
            from spectra.services import preview_pause
            preview_pause.start(duration_s + PAUSE_MARGIN_S)
            self._on_edge = on_edge
            self._on_done = on_done
            self._run = PatternRun(seed=seed, started_at=self._clock(), duration_s=duration_s,
                                   virtual_ids=sorted(snapshot))
            self._task = asyncio.create_task(self._drive(self._run),
                                             name="spectra-av-sync-pattern")
            return self._run

    async def stop(self) -> None:
        """Abort a running pattern (its finally block reverts) or, with no
        task alive, revert any held snapshot directly. Idempotent."""
        if await self._cancel_run():
            return
        async with self._lock:
            await self._revert_locked("stop")

    async def _cancel_run(self) -> bool:
        task, self._task = self._task, None
        if task is None or task.done() or task is asyncio.current_task():
            return False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        return True

    async def _drive(self, run: PatternRun) -> None:
        vids = run.virtual_ids
        schedule = random_edge_schedule(run.seed, run.duration_s)
        try:
            # one type switch up front (state ON), then brightness-only edges
            await self._write([{"virtual_id": vid, "effect_type": PATTERN_EFFECT_TYPE,
                                "config": {"color": PATTERN_COLOR,
                                           "brightness": 0.0}} for vid in vids],
                              transition_ms=0)
            t_start = self._clock()
            run.started_at = t_start
            for t_off, state in schedule:
                due = t_start + t_off
                delay = due - self._clock()
                if delay > 0:
                    await self._sleep(delay)
                before = self._clock()
                await self._write([{"virtual_id": vid, "effect_type": PATTERN_EFFECT_TYPE,
                                    "config": {"color": PATTERN_COLOR,
                                               "brightness": PATTERN_BRIGHTNESS if state else 0.0}}
                                   for vid in vids], transition_ms=EDGE_TRANSITION_MS)
                after = self._clock()
                mid = 0.5 * (before + after)
                run.edges.append((mid, int(state)))
                run.write_half_width_s.append(0.5 * (after - before))
                if self._on_edge is not None:
                    try:
                        self._on_edge(mid, int(state))
                    except Exception:
                        logger.exception("av_sync pattern: on_edge callback failed")
            # close the final hold so the last edge has a defined end
            tail = self._clock() - run.edges[-1][0] if run.edges else 0.0
            if tail < 0.3:
                await self._sleep(0.3 - tail)
        except asyncio.CancelledError:
            run.aborted = True
            raise
        except Exception:
            run.aborted = True
            logger.exception("av_sync pattern: drive failed — reverting")
        finally:
            run.finished_at = self._clock()
            async with self._lock:
                if self._run is run:
                    await self._revert_locked("done", from_task=True)
            if self._on_done is not None:
                try:
                    self._on_done(run)
                except Exception:
                    logger.exception("av_sync pattern: on_done callback failed")

    async def _revert_locked(self, reason: str, *, from_task: bool = False) -> None:
        """Caller holds _lock and has already cancelled any drive task
        (or IS the drive task's finally block, from_task=True). Writes the
        snapshot back, clears the pause + the persisted file. Idempotent."""
        snap = self._snapshot
        self._snapshot = None
        if from_task:
            self._task = None
        from spectra.services import preview_pause
        preview_pause.clear()
        _clear_snapshot_file()
        if not snap:
            return
        writes = [{"virtual_id": vid, "effect_type": s["type"], "config": s["config"]}
                  for vid, s in snap.items()]
        try:
            await self._write(writes, transition_ms=REVERT_TRANSITION_MS)
        except Exception:
            logger.exception("av_sync pattern: revert (%s) failed for %s", reason, sorted(snap))
        logger.info("av_sync pattern: reverted %d virtual(s) (%s)", len(snap), reason)


# ── snapshot persistence (restart safety) ─────────────────────────────────

def _save_snapshot(snapshot: dict) -> None:
    path = config.AV_SYNC_PATTERN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"snapshot": snapshot, "started_at": time.time()}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_snapshot() -> dict | None:
    path = config.AV_SYNC_PATTERN_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("snapshot")
    except Exception:
        logger.exception("av_sync pattern: unreadable snapshot %s — treating as empty", path)
        return None


def _clear_snapshot_file() -> None:
    try:
        config.AV_SYNC_PATTERN_FILE.unlink()
    except FileNotFoundError:
        pass


driver = PatternDriver()


async def recover_stale_pattern(apply_writes: Callable | None = None) -> bool:
    """Startup: a snapshot still on disk means a pattern was running when
    the process died — nothing else can legitimately own one, so it is
    unconditionally stale. Land it back, clear the file. Mirrors
    flare_preview_hold.recover_stale_hold (not age-gated, same reason)."""
    snap = _load_snapshot()
    if not snap:
        return False
    writes = [{"virtual_id": vid, "effect_type": s["type"], "config": s["config"]}
              for vid, s in snap.items()]
    try:
        if apply_writes is not None:
            await apply_writes(writes, transition_ms=REVERT_TRANSITION_MS)
        else:
            from spectra.services import fx_seam
            await fx_seam.apply_writes(writes, transition_ms=REVERT_TRANSITION_MS)
        logger.warning("av_sync pattern: recovered a stale pre-pattern snapshot at startup "
                       "(%d virtual(s)) — landed back", len(snap))
    except Exception:
        logger.exception("av_sync pattern: stale snapshot recovery write failed for %s",
                         sorted(snap))
    _clear_snapshot_file()
    return True
