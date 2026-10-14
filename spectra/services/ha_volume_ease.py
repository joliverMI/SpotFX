"""THE EASED HOME ASSISTANT VOLUME STEP — the Light Show's two volume
actions (`show_actions.py`'s "ha" group) walk `input_number.snap_volume`
to where it should be over a chosen time instead of jumping (the Admiral,
2026-10-11: "add setting to ease the volume over time. default is
1 second. figure out if the easing is best handled by home assistant or
spectra"; followed up 2026-10-13 — "how smoothed is the volume increase
... what would it take to smooth it further", answered "see if 3 is
available, then 2, then do 1 if neither of those is reasonable", where
3 = a native HA fade, 2 = fine-grained writes, 1 = lower HA's own step).

WHY SPECTRA AND NOT A RAMPING HA SCRIPT — measured, not argued (read-only,
2026-10-11, River's own script mirror `Homelab/HA_Packages/scripts/
music_volume.yaml` plus a GET of the live entities):
  * Neither script has a transition — `media_player.volume_set`/
    `input_number.set_value` both move Snapcast's own integer percent
    instantly, so OPTION 3 (a native fade) IS NOT AVAILABLE (River's
    own answer, 2026-10-13); nothing in this module waits on that again.
  * `script.music_volume_set` is `mode: single`: a ramping version of it
    would DROP a newer call that lands mid-ramp ("already running") — the
    exact opposite of last-writer-wins — and the relative script is a
    SEPARATE `mode: queued` script, so an HA-side ramp could not be
    cancelled by the other one without cross-script `script.turn_off`
    plumbing on River's side.
  * Only SPECTRA knows the step is part of a show, which ramp a newer step
    replaces, and what a relative step is relative to (below).
  * The one thing HA would do better — survive a SPECTRA restart
    mid-ramp — is cheap to give up: the ramp only ever writes real levels
    between where it started and where it was going, so a restart leaves
    the volume at one of them (stated below), never somewhere odd.

OPTION 2 (FINE-GRAINED WRITES) IS WHAT RUNS — confirmed available with no
HA change (River, 2026-10-13): the step of 4 on `input_number.snap_volume`
only shapes the DASHBOARD SLIDER; Home Assistant does not enforce it on a
write — the entity's own history already holds non-multiples of 4 (9, 10,
14, 18, 23, ...). SPECTRA writes a WHOLE PERCENT at a time (never a
fraction — fractional values are pointless on an integer volume), landing
exactly on the target, rather than quantising to the entity's step
attribute the way this module originally did. OPTION 1 (lowering HA's own
step to 1) is therefore moot and was never applied.

ONE RAMP AT A TIME. Both scripts move the same entity, so there is one
slot. A new volume step — eased or instant, absolute or relative, from a
set, an arm or Sonic — STOPS the ramp in flight before it writes anything
(between two writes, never mid-request — `_stop_current`), so the last
step fired always wins.
  * ABSOLUTE REPLACES: it reads where the volume is NOW (the old ramp's
    last level) and eases from there to its own target.
  * RELATIVE IS RELATIVE TO WHERE THE VOLUME WAS HEADING: the stopped
    ramp's unfinished part is carried into the new step (`carried`), so
    two quick "+8" steps land at +16, not wherever the first happened to
    be when the second arrived. A relative ramp is a series of smaller
    calls to the SAME relative script (never the absolute one), so it
    needs no read and keeps Home Assistant's own clamp.

THE FIRST WRITE IS INLINE, the rest run in the background. The step's
outcome is that first real call's answer (so "not configured", a 401 or an
unreachable HA still fail the step exactly as before) and a set is never
held back for the length of an ease. A later write that fails ends the
ramp loudly: an ERROR log line, a show-log entry (`show/ha_volume_ease`)
and `status()["last"]`, which rides on the Light Show's own status.

RATE: never more than one write per `MIN_WRITE_INTERVAL_S` (0.2 s, ~5 a
second) — River's own ceiling (2026-10-13): each change to snap_volume
fans out to five Snapcast clients, and the automation driving it is
`mode: restart`, so a burst only drops the intermediate points rather than
queuing or erroring. A span needing more whole-percent writes than the
ease span allows at that rate takes bigger (still whole-number) steps
instead of writing faster — never the reverse. HA's REST API has no rate
limiter of its own to respect.

RESTART MID-RAMP: nothing is persisted. The task dies with the process and
the volume stays at the last level written — a real snap_volume level
between the ramp's start and its target. Nothing resumes the ramp.

EASE 0 == THE OLD STEP, CALL FOR CALL: one write, no read, nothing in
flight (a relative step still carries a stopped ramp's remainder, which is
zero when nothing was in flight).

NO HOUSE GATE, like every HA action: nothing here consults house.py.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

SNAP_VOLUME_ENTITY = "input_number.snap_volume"
ABSOLUTE_DOMAIN = "script"
ABSOLUTE_SERVICE = "music_volume_set"
VOLUME_MIN = 0.0
VOLUME_MAX = 100.0
DEFAULT_EASE_S = 1.0
MAX_EASE_S = 60.0
#: Never more than five writes a second (see RATE above).
MIN_WRITE_INTERVAL_S = 0.2
#: How long a new step waits for the stopped ramp's in-flight request to
#: finish before cancelling it outright — a healthy HA answers in ~2 ms.
STOP_WAIT_S = 0.5


@dataclass
class EaseResult:
    """What one volume step did: the first (inline) call's answer, the
    sentence a person reads, and the ramp's shape for the step's data."""

    ha: object                          # ha_client.HAResult
    detail: str
    data: dict = field(default_factory=dict)


@dataclass
class _Ramp:
    mode: str                           # "absolute" | "relative"
    ease_s: float
    #: absolute: the target level; relative: the total delta.
    goal: float
    #: absolute: the last level written; relative: the delta applied so far.
    done: float
    planned: int
    writes: int = 0
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None

    def remaining(self) -> float:
        """The part this ramp has not written yet, as a volume delta."""
        return self.goal - self.done

    def as_dict(self) -> dict:
        return {"mode": self.mode, "ease_s": self.ease_s, "goal": self.goal,
                "done": self.done, "writes": self.writes,
                "planned": self.planned}


_current: Optional[_Ramp] = None
_last: Optional[dict] = None
_lock_for: Optional[tuple] = None


def _lock() -> asyncio.Lock:
    """One lock per running loop — an asyncio.Lock binds to the first loop
    that uses it, and the tests run many."""
    global _lock_for
    loop = asyncio.get_running_loop()
    if _lock_for is None or _lock_for[0] is not loop:
        _lock_for = (loop, asyncio.Lock())
    return _lock_for[1]


# ── the plan (pure) ─────────────────────────────────────────────────────────

def _writes_for(span: float, ease_s: float) -> int:
    """How many writes a span of this many whole percent needs over
    `ease_s`, capped at `MIN_WRITE_INTERVAL_S` apart — never more writes
    than the ease span can hold at that rate, coarsening evenly (bigger
    steps, not faster ones) when the span needs more than that."""
    if ease_s <= 0 or abs(span) < 1:
        return 1
    by_level = math.ceil(abs(span))
    by_rate = max(1, int(ease_s / MIN_WRITE_INTERVAL_S + 1e-9))
    return max(1, min(by_level, by_rate))


def _whole(x: float) -> float:
    """Snap to the nearest whole percent — snap_volume is an integer, and
    a fractional write is pointless on it."""
    return round(x)


def plan_absolute(start: float, target: float, ease_s: float) -> list[tuple[float, float]]:
    """(seconds after the step, level to write) — evenly held WHOLE-PERCENT
    levels, the last exactly `target`, the first at 0. A level equal to
    the one before it is not written again."""
    n = _writes_for(target - start, ease_s)
    out: list[tuple[float, float]] = []
    prev = start
    for k in range(1, n + 1):
        v = target if k == n else min(VOLUME_MAX, max(VOLUME_MIN,
                                                      _whole(start + (target - start) * k / n)))
        if k < n and v == prev:
            continue
        out.append((ease_s * (k - 1) / n, v))
        prev = v
    return out


def plan_relative(delta: float, ease_s: float) -> list[tuple[float, float]]:
    """(seconds after the step, increment to send) — WHOLE-PERCENT
    increments summing exactly to `delta`, the first at 0."""
    n = _writes_for(delta, ease_s)
    out: list[tuple[float, float]] = []
    prev = 0.0
    for k in range(1, n + 1):
        cum = delta if k == n else _whole(delta * k / n)
        inc = cum - prev
        if k < n and inc == 0:
            continue
        out.append((ease_s * (k - 1) / n, inc))
        prev = cum
    return out


# ── the slot ───────────────────────────────────────────────────────────────

async def _stop_current() -> float:
    """Stop the ramp in flight (between writes) and return what it had not
    written yet. 0 when nothing was in flight."""
    global _current
    ramp = _current
    _current = None
    if ramp is None:
        return 0.0
    ramp.stop.set()
    task = ramp.task
    if task is not None and task.get_loop() is not asyncio.get_running_loop():
        task = None             # a ramp from a loop that is gone (tests)
    if task is not None and not task.done():
        done, _ = await asyncio.wait({task}, timeout=STOP_WAIT_S)
        if not done:
            task.cancel()
    _finish(ramp, "replaced", f"replaced by a newer volume step after "
                              f"{ramp.writes} of {ramp.planned} writes")
    return ramp.remaining()


def _finish(ramp: _Ramp, state: str, detail: str) -> None:
    global _last
    _last = {**ramp.as_dict(), "state": state, "detail": detail}
    if state == "failed":
        logger.error("ha volume ease: %s", detail)
    try:
        from spectra.services import fire_history
        fire_history.record_fire("show", "ha_volume_ease",
                                 {"state": state, "detail": detail,
                                  **ramp.as_dict()})
    except Exception:                                    # noqa: BLE001
        logger.exception("ha volume ease: show-log write failed")


async def _drive(ramp: _Ramp, rest: list[tuple[float, float]], t0: float,
                 write: Callable[[float], Awaitable[object]]) -> None:
    global _current
    loop = asyncio.get_running_loop()
    for at, value in rest:
        delay = t0 + at - loop.time()
        if delay > 0:
            try:
                await asyncio.wait_for(ramp.stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        if ramp.stop.is_set():
            return
        result = await write(value)
        if not getattr(result, "ok", False):
            if _current is ramp:
                _current = None
            _finish(ramp, "failed",
                    f"volume ease stopped after {ramp.writes} of "
                    f"{ramp.planned} writes: "
                    f"{getattr(result, 'detail', '') or 'Home Assistant call failed'}")
            return
        ramp.writes += 1
        ramp.done = value if ramp.mode == "absolute" else ramp.done + value
    if _current is ramp:
        _current = None
        _finish(ramp, "done", f"volume ease finished ({ramp.writes} writes "
                              f"over {ramp.ease_s:g} s)")


async def _run(ramp: _Ramp, plan: list[tuple[float, float]],
               write: Callable[[float], Awaitable[object]]):
    """Write the first entry inline; if there is more, park the ramp in
    the slot and drive the rest in the background. Returns the first
    call's HAResult."""
    global _current
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    first = await write(plan[0][1])
    if not getattr(first, "ok", False):
        return first
    ramp.writes = 1
    ramp.done = plan[0][1] if ramp.mode == "absolute" else ramp.done + plan[0][1]
    if len(plan) > 1:
        _current = ramp
        ramp.task = asyncio.create_task(_drive(ramp, plan[1:], t0, write),
                                        name="ha-volume-ease")
    return first


def _num(x: float) -> str:
    return f"{x:g}"


async def set_absolute(volume: float, ease_s: float = DEFAULT_EASE_S) -> EaseResult:
    from spectra.services import ha_client

    async def write(v: float):
        return await ha_client.call_service(ABSOLUTE_DOMAIN, ABSOLUTE_SERVICE,
                                            {"volume": v})

    async with _lock():
        await _stop_current()
        note = ""
        start: Optional[float] = None
        if ease_s > 0 and ha_client.configured():
            st = await ha_client.get_state(SNAP_VOLUME_ENTITY)
            try:
                start = float(st.state) if st.ok else None
            except (TypeError, ValueError):
                start = None
            if start is None:
                note = (" instantly (could not read the current volume to "
                        f"ease from: {st.detail or st.state!r})")
        plan = ([(0.0, volume)] if start is None
                else plan_absolute(start, volume, ease_s))
        ramp = _Ramp("absolute", ease_s, goal=volume,
                     done=start if start is not None else volume,
                     planned=len(plan))
        first = await _run(ramp, plan, write)
        data = {"ease_s": ease_s, "writes": len(plan),
                "from": start, "to": volume}
        if len(plan) > 1:
            detail = (f"HA volume easing {_num(start)} → {_num(volume)} "
                      f"over {_num(ease_s)} s")
        else:
            detail = f"HA volume set to {_num(volume)}{note}"
        return EaseResult(first, detail, data)


async def step_relative(domain: str, service: str, delta: float,
                        ease_s: float = DEFAULT_EASE_S) -> EaseResult:
    from spectra.services import ha_client

    async def write(inc: float):
        return await ha_client.call_service(domain, service, {"delta": inc})

    async with _lock():
        carried = await _stop_current()
        total = delta + carried
        plan = plan_relative(total, ease_s)
        ramp = _Ramp("relative", ease_s, goal=total, done=0.0,
                     planned=len(plan))
        first = await _run(ramp, plan, write)
        sign = "+" if delta >= 0 else ""
        detail = f"HA volume step {sign}{_num(delta)}"
        if carried:
            csign = "+" if carried >= 0 else ""
            detail += (f" (plus {csign}{_num(carried)} still owed by the "
                       f"step it replaced)")
        if len(plan) > 1:
            detail += f" over {_num(ease_s)} s"
        return EaseResult(first, detail,
                          {"ease_s": ease_s, "writes": len(plan),
                           "carried": carried})


async def stop() -> None:
    """Stop any ramp in flight where it is (nothing is written)."""
    async with _lock():
        await _stop_current()


async def wait_idle() -> None:
    """Wait for the ramp in flight (if any) to finish — for tests and for
    any caller that genuinely needs the volume to have arrived."""
    ramp = _current
    if ramp is not None and ramp.task is not None:
        await asyncio.gather(ramp.task, return_exceptions=True)


def status() -> dict:
    return {"in_flight": _current.as_dict() if _current is not None else None,
            "last": dict(_last) if _last is not None else None}


def reset() -> None:
    """Forget everything (tests). Does not touch a running task."""
    global _current, _last, _lock_for
    _current = None
    _last = None
    _lock_for = None
