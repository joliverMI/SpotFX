"""PARAM ORPHAN WATCHDOG — the safety net under the response engine's
momentary releases (owner ask, 2026-08-21, verbatim: "some kind of
watchdog system to make sure that parameters are set correctly like
that"), asked for after he found an effect stuck running backwards with
no way back: a momentary `reverse` flare whose release never landed left
`reverse=True` on the live effect while every piece of engine bookkeeping
said the flare was over. The second time that same evening his room was
left in a state nobody was holding (the other was a preview hold left
open, refusing his scene changes). Prevention for the stuck-reverse defect
itself is a SEPARATE task (reverse-flare-glide-and-stuck); this module is
the net under it, not a replacement — a system that can only be left wrong
is a different thing from one that notices and recovers.

WHAT IT DOES
  Every SWEEP_INTERVAL_S it reads each engine-tracked virtual's LIVE effect
  config off the in-process render host and compares every param the
  engine holds a baseline for (drift_conductor.VirtualState.param_baseline
  — seeded from the scene fire's own resolved writes, moved only by a
  permanent kind's carry) against what the live effect is actually
  showing. A param sitting AWAY FROM ITS BASELINE WITH NOTHING HOLDING IT
  THERE, continuously, for at least ORPHAN_GRACE_S, is an orphan: the
  watchdog restores it to the baseline (the exact value a momentary
  release would have returned it to — ResponseEngine.release_target, the
  same _carried_value every flush_releases call reads), logs what it
  found at WARNING, records it to fire_history's "watchdog" bucket (the
  Review page's show log), and counts it on the liveness endpoint.

"NOTHING HOLDING IT" — precisely, the four legitimate holders, all
checked fresh each sweep, any one of them standing down the check:
  1. a pending momentary release for that (virtual, param) in
     ResponseEngine._pending_releases (pending_release_keys) — the spike
     is still inside its authored hold, or its release task hasn't run
     yet (an event-loop stall only delays the flush; the entry sits there
     the whole time, so a late release is never mistaken for a lost one);
  2. an active drift mechanism (creep/follow) owning that (virtual,
     param) in drift_conductor.mechanisms — its live value is ALWAYS
     gliding toward the next leg's target, legitimately away from any
     fixed number;
  3. a param tween currently in flight on the live effect (Effect._tweens
     has the key) — a release glide, a permanent move's ease-in, a scene
     fire's entry ramp, a gain's landing are all mid-flight writes the
     engine already issued;
  4. a running ROOM EFFECT owning that (virtual, "brightness") — the
     room-effects layer (spectra/services/room_effects.py) drives a
     travelling wave by moving brightness continuously and by design, so
     those exact keys are held while it runs. Note honestly what this does
     and does not add TODAY: a room effect holds the room through
     flare_preview_hold, and _production_gate() already stands the WHOLE
     sweep down while any hold is active, so in production this holder is
     currently belt-and-braces. It is here because it is the honest
     expression of ownership, because it is per-KEY where the gate is
     global, and because the moment a room effect is allowed to run without
     the hold (his own open question — "ride on top, like the dimmer") it
     becomes the only thing standing between a wave and a watchdog that
     would fight it. tests/test_room_effects.py proves it against a
     deliberately-open gate, which is the shape a narrowed gate would take.

THE DISCRIMINATOR THAT MAKES THIS SAFE — how a legitimate PERMANENT move is
told apart from an ORPHANED MOMENTARY spike, established before the
restore was written (it is structural, not a heuristic):
  A permanent kind (and a dice re-roll, a held gain, a colour jump's
  brightness) writes its landed value into the surge's `carry`, and
  _execute_band/fire_kind hand that carry to conductor.on_surge(), which
  MOVES VirtualState.param_baseline (and brightness_baseline) to the new
  value — a permanent move IS the baseline from then on, so live ==
  baseline and there is nothing to restore. A momentary kind NEVER
  touches carry/param_baseline (scene_response._compute_param_moves'
  momentary branch, _gain's momentary branch): it spikes the live value
  and queues a return, so live != baseline for exactly as long as the
  spike + release are in progress — holder 1 and then holder 3 above. The
  only way to have live != baseline with none of the three holders is a
  release that was lost, skipped, or rejected. The watchdog therefore
  cannot fight an authored permanent flare by construction: the moment a
  permanent kind lands, the baseline it compares against is the landed
  value. Proven, not asserted: tests/test_param_watchdog.py fires a real
  permanent move and a real in-flight momentary hold on the vendored
  pipeline and asserts both are left alone.

WHAT IS DELIBERATELY OUT OF SCOPE, BY NAME (each is a legitimate writer
the engine's own bookkeeping does not follow, so a watchdog over it would
fight a legitimate writer rather than catch a defect):
  - `background_brightness` / `background_color`: written by the
    conductor's own colour-set landings (apply_color_set, _color_jump
    write entry.background_brightness to the wire without moving
    param_baseline — a pre-existing bookkeeping gap, not this module's to
    close), by Dark mode's `dark_lock` clamp (fx/effects/__init__.py
    forces both black on every write), and by Light mode's forced
    background (spectra/services/dark_light.py). Three legitimate writers;
    excluded by name (EXCLUDED_PARAMS).
  - `gradient` and every other string-valued key: colour, not a param;
    the colour journey/rotate/jump own those with their own release queue.
  - a param NOT in param_baseline (never authored by the scene's fire
    write and never moved by a permanent kind): no baseline, no opinion —
    restoring to a registry/schema default instead would risk changing a
    look he never authored (the brightness carry-forward case is exactly
    one where the schema default is the WRONG answer).
  - a param whose live effect TYPE differs from the conductor's picture of
    that virtual (something outside the engine switched the effect — e.g.
    Dark→Hybrid's stale-snapshot repaint landing an older scene's type):
    the baseline is for a different effect; counted (`type_mismatch`),
    never acted on.
  - `brightness` is scaled at the write seam by the room's
    brightness_multiplier (fx_executor._room_scaled), so its expected live
    value is baseline × multiplier. A multiplier change does NOT rewrite
    live brightness until the next brightness write (pre-existing), so a
    live value explained by ANY multiplier seen since the last scene fire
    (a short history) counts as matched — the watchdog never acts on
    behalf of the dimmer.

WHEN IT STANDS DOWN ENTIRELY (the sweep is skipped, and every in-progress
suspicion is dropped, because the lights are legitimately being driven by
something other than the engine, or not by this process at all):
  - the engine is dark (executor.mode != "facade") or the live stack is
    down — there is no live config to read and nothing of ours to restore;
  - a colour-set Preview or a flare-preview hold is active
    (preview_pause.active() / flare_preview_hold.active()) — both write
    real lights through fx_seam outside the engine and revert on their
    own; the sweep resumes fresh once they let go.

THRESHOLD — ORPHAN_GRACE_S = 30 s, SWEEP_INTERVAL_S = 10 s, stated and
justified: a momentary spike is legitimately away from baseline for its
authored hold (PULSE_HOLD_S 0.25 s default; the longest authored hold_ms
in his real scenes, read live 2026-08-21, is 500 ms) plus its return
(PULSE_RELEASE_S 1.5 s), plus the measured live release overrun (up to
~1.9 s against 500 ms authored — AGENTS.md, still unexplained) — worst
observed legitimate window ≈ 3.5 s, and every millisecond of it is ALSO
covered by holder 1 or holder 3 above, so the grace is margin on top of a
structural check, not the check itself. 30 s is ~8× that worst case and
longer than a whole 20 s drift leg; an orphan must be seen mismatched on
at least two consecutive sweeps with the SAME expected value (a baseline
that moved between sweeps restarts the clock). A restore therefore lands
30–40 s after the last legitimate holder let go — late enough that normal
operation never trips it, early enough that a stuck reverse doesn't sit
through a whole song. A restore that does not take (the next sweep still
sees the mismatch, no tween in flight) is retried on the same grace at
most RESTORE_ATTEMPT_LIMIT times, then given up on — at CRITICAL, named —
until the baseline changes or the next scene fire, so a write something
keeps re-moving (or a schema keeps rejecting) can never become a silent
every-sweep fight.

LOUD, NOT SILENT: every restore logs the virtual, the param, the live
value it found, the baseline it restored to, how long it had been orphaned,
and how the write was landed; it is recorded to fire_history's "watchdog"
bucket (durable count + show-log timeline); status() carries the running
total, the currently-suspected set, the recent restores, and anything
given up on; liveness_summary() puts the count on GET /spectra/api/liveness
(informational — never affects `healthy`) so a RECURRING orphan is visible
rather than merely handled. The recovery is the lesser half: the log line
is what finds the cause.

Module-level state, no DI seam for the state itself (same shape as
flare_preview_hold/ambient_music_gate): tests/conftest.py's autouse fixture
calls reset(); the Deps dataclass is the injection seam for everything the
sweep reads or writes. Executable proof: tests/test_param_watchdog.py.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from spectra.services.scene_response import PULSE_RELEASE_S

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_S = 10.0
ORPHAN_GRACE_S = 30.0
# A restore looks like the release that never came: the same glide every
# momentary release uses (flush_releases). Bools/toggles jump, same as there.
RESTORE_GLIDE_MS = int(PULSE_RELEASE_S * 1000)
RESTORE_ATTEMPT_LIMIT = 3
VALUE_TOLERANCE = 1e-6
EXCLUDED_PARAMS = frozenset({"background_brightness", "background_color",
                             "gradient"})
MULTIPLIER_HISTORY = 8
RECENT_RESTORES = 50
FIRE_HISTORY_BUCKET = "watchdog"


@dataclass(frozen=True)
class LiveEffect:
    """One snapshot of a live effect: its type, a copy of its config, and
    the keys currently mid-tween."""
    effect_type: str
    config: dict
    tweening: frozenset


@dataclass
class Deps:
    """Everything one sweep reads or writes. production_deps() wires the
    real singletons; tests hand in the headless rig or plain fakes."""
    conductor: Any
    responses: Any
    executor: Callable[[], Any]
    live_effect: Callable[[str], Optional[LiveEffect]]
    room_controls: Callable[[], Any]
    gate: Callable[[], Optional[str]]
    clock: Callable[[], float] = time.monotonic
    #: HOLDER 4 — the room-effects layer (spectra/services/room_effects.py).
    #: A running Dim Wave moves `brightness` on its mapped virtuals
    #: continuously and by design, so those exact (virtual, param) keys are
    #: legitimately held while it runs. Per KEY, never a global stand-down:
    #: every other param on every other virtual stays watched throughout,
    #: which is the difference between registering a holder and switching
    #: the watchdog off. Returns an empty set when nothing is running, so
    #: the sweep is unchanged by this feature's existence.
    room_effect_holds: Callable[[], set] = lambda: set()


# ── module state ───────────────────────────────────────────────────────────

_tracking: dict[tuple[str, str], dict] = {}
_attempts: dict[tuple[str, str], int] = {}
_given_up: dict[tuple[str, str], dict] = {}
_restores: deque = deque(maxlen=RECENT_RESTORES)
_restores_total = 0
_last_sweep: Optional[dict] = None
_last_sweep_wall: Optional[float] = None
_epoch: Optional[int] = None
_multipliers: list[float] = []


def reset() -> None:
    global _restores_total, _last_sweep, _last_sweep_wall, _epoch
    _tracking.clear()
    _attempts.clear()
    _given_up.clear()
    _restores.clear()
    _restores_total = 0
    _last_sweep = None
    _last_sweep_wall = None
    _epoch = None
    _multipliers.clear()


# ── production wiring (lazy imports; the module is imported from app.py's
#    lifespan, and engine.py imports it lazily inside status()) ─────────────

LOCK_TIMEOUT_S = 0.5


def snapshot_effect(effect) -> Optional[LiveEffect]:
    """Read one live effect under its own lock (the same lock
    start_param_transitions takes from the event loop on every engine
    write): a copy of _config and the set of keys currently tweening.
    Lock-free reads would race _advance_tweens' in-place pops. Bounded
    wait (LOCK_TIMEOUT_S): a render thread wedged inside the lock must
    make this virtual unreadable for one sweep, never hang the event loop
    — None means "couldn't read it", counted, never acted on."""
    lock = getattr(effect, "lock", None)
    if lock is not None:
        if not lock.acquire(timeout=LOCK_TIMEOUT_S):
            return None
        try:
            config = dict(effect._config or {})
            tweening = frozenset(effect._tweens or ())
        finally:
            lock.release()
    else:
        config = dict(getattr(effect, "_config", None) or {})
        tweening = frozenset(getattr(effect, "_tweens", None) or ())
    return LiveEffect(effect_type=str(effect.type), config=config,
                      tweening=tweening)


def _production_live_effect(vid: str) -> Optional[LiveEffect]:
    from fx.effects import DummyEffect
    from spectra.services.live_host import live
    host = live.host
    if host is None:
        return None
    virtual = host.virtuals.get(vid)
    if virtual is None:
        return None
    effect = getattr(virtual, "active_effect", None)
    if effect is None or isinstance(effect, DummyEffect):
        return None
    return snapshot_effect(effect)


def _production_gate() -> Optional[str]:
    from spectra.services import engine, flare_preview_hold, preview_pause
    from spectra.services.live_host import live
    if engine.executor.mode != "facade":
        return "engine dark (recording executor)"
    if not live.active:
        return "live stack down"
    if preview_pause.active():
        return "preview active"
    if flare_preview_hold.active():
        return "flare preview hold active"
    return None


def _load_room_controls():
    from spectra.services.room_controls import load_room_controls
    return load_room_controls()


def production_deps() -> Deps:
    from spectra.services import engine
    from spectra.services import room_effects
    return Deps(conductor=engine.conductor, responses=engine.responses,
                executor=lambda: engine.executor,
                live_effect=_production_live_effect,
                room_controls=_load_room_controls,
                gate=_production_gate,
                room_effect_holds=room_effects.holds)


# ── the comparison ─────────────────────────────────────────────────────────

def _scaled_brightness(value: float, multiplier: float) -> float:
    # Mirrors room_controls.apply_brightness' per-key arithmetic exactly.
    if multiplier == 1.0:
        return value
    return max(0.0, min(1.0, value * multiplier))


def _same_value(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=VALUE_TOLERANCE,
                            abs_tol=VALUE_TOLERANCE)
    return a == b


def _explained(pname: str, live: Any, expected: Any,
               multipliers: list[float]) -> Optional[bool]:
    """True when the live value is what the baseline predicts; False when
    it's a genuine mismatch; None when the two can't be judged against
    each other (a bool against a number — a registry/effect disagreement
    the watchdog has no business resolving)."""
    if isinstance(expected, bool) or isinstance(live, bool):
        if not (isinstance(expected, bool) and isinstance(live, bool)):
            return None
        return live == expected
    if not isinstance(live, (int, float)) or not isinstance(expected, (int, float)):
        return None
    if pname == "brightness":
        return any(_same_value(live, _scaled_brightness(float(expected), m))
                   for m in (multipliers or [1.0]))
    return _same_value(live, expected)


# ── the sweep ──────────────────────────────────────────────────────────────

def _note_multiplier(multiplier: float) -> None:
    if multiplier in _multipliers:
        return
    _multipliers.append(multiplier)
    del _multipliers[:-MULTIPLIER_HISTORY]


async def sweep_once(deps: Optional[Deps] = None) -> dict:
    """One sweep. Returns the sweep record (also kept as status()'s
    last_sweep). Never raises on a single virtual's trouble — run_supervised
    catches and retries whole-sweep crashes; inside, a restore that raises
    is logged and the rest of the sweep continues."""
    global _last_sweep, _last_sweep_wall, _epoch
    deps = deps or production_deps()
    now = deps.clock()
    record: dict[str, Any] = {"at": now, "skipped": None, "checked": 0,
                              "ok": 0, "held": 0, "suspected": 0,
                              "restored": 0, "type_mismatch": 0,
                              "unreadable": 0, "given_up": 0, "restores": []}
    reason = deps.gate()
    if reason is not None:
        # A gated window (preview hold, dark engine) drives the lights
        # outside the engine's bookkeeping; whatever we were suspecting is
        # void, and the multiplier history with it.
        _tracking.clear()
        _multipliers.clear()
        record["skipped"] = reason
        _last_sweep, _last_sweep_wall = record, time.time()
        return record

    conductor, responses = deps.conductor, deps.responses
    epoch = id(conductor.virtuals)
    if epoch != _epoch:
        # A scene fire replaced every VirtualState — new baselines, written
        # at the current multiplier; every prior suspicion/attempt is moot.
        _epoch = epoch
        _tracking.clear()
        _attempts.clear()
        _given_up.clear()
        _multipliers.clear()

    controls = deps.room_controls()
    _note_multiplier(float(getattr(controls, "brightness_multiplier", 1.0)))
    pending = set(responses.pending_release_keys())
    owned = {(m.vid, m.param) for m in conductor.mechanisms}
    room_effect = set(deps.room_effect_holds() or ())
    seen: set[tuple[str, str]] = set()

    for vid, state in list(conductor.virtuals.items()):
        live = deps.live_effect(vid)
        if live is None:
            record["unreadable"] += 1
            continue
        if live.effect_type != state.effect_type:
            record["type_mismatch"] += 1
            continue
        for pname, _baseline in list(state.param_baseline.items()):
            if pname in EXCLUDED_PARAMS:
                continue
            key = (vid, pname)
            if key in pending or key in owned or key in room_effect \
                    or pname in live.tweening:
                record["checked"] += 1
                record["held"] += 1
                _tracking.pop(key, None)
                continue
            if pname not in live.config:
                continue
            live_val = live.config[pname]
            expected = responses.release_target(vid, pname)
            if expected is None:
                continue
            verdict = _explained(pname, live_val, expected, _multipliers)
            if verdict is None:
                continue
            record["checked"] += 1
            seen.add(key)
            if verdict:
                record["ok"] += 1
                _tracking.pop(key, None)
                _attempts.pop(key, None)
                _given_up.pop(key, None)
                continue
            given = _given_up.get(key)
            if given is not None and _same_value(given["expected"], expected):
                record["given_up"] += 1
                continue
            track = _tracking.get(key)
            if track is None or not _same_value(track["expected"], expected):
                _tracking[key] = {"first_seen": now,
                                  "first_seen_wall": time.time(),
                                  "live": live_val, "expected": expected,
                                  "effect_type": state.effect_type}
                record["suspected"] += 1
                continue
            age = now - track["first_seen"]
            if age < ORPHAN_GRACE_S:
                record["suspected"] += 1
                continue
            try:
                entry = await _restore(deps, vid, state.effect_type, pname,
                                       live_val, expected, age)
            except Exception:
                logger.exception("param watchdog: restore of %s.%s failed",
                                 vid, pname)
                continue
            record["restored"] += 1
            record["restores"].append(entry)

    for key in list(_tracking):
        if key not in seen:
            _tracking.pop(key, None)
    _last_sweep, _last_sweep_wall = record, time.time()
    return record


async def _restore(deps: Deps, vid: str, effect_type: str, pname: str,
                   live_val: Any, expected: Any, age_s: float) -> dict:
    global _restores_total
    key = (vid, pname)
    executor = deps.executor()
    if isinstance(expected, bool):
        await executor.jump(vid, effect_type, {pname: expected})
        method = "jump"
    else:
        await executor.glide(vid, effect_type, {pname: expected},
                             RESTORE_GLIDE_MS)
        method = f"glide {RESTORE_GLIDE_MS}ms"
    attempt = _attempts.get(key, 0) + 1
    _attempts[key] = attempt
    _tracking.pop(key, None)
    entry = {"at_wall_ms": int(time.time() * 1000), "virtual_id": vid,
             "effect_type": effect_type, "param": pname,
             "found": live_val, "restored_to": expected,
             "orphaned_for_s": round(age_s, 1), "method": method,
             "attempt": attempt}
    _restores.append(entry)
    _restores_total += 1
    logger.warning(
        "PARAM ORPHAN RESTORED — %s.%s (%s) was %r with nothing holding it "
        "for %.0fs (no pending release, no drift mechanism, no tween in "
        "flight): restored to baseline %r via %s [attempt %d/%d]. The "
        "restore is the lesser half — find what lost the release.",
        vid, pname, effect_type, live_val, age_s, expected, method,
        attempt, RESTORE_ATTEMPT_LIMIT)
    try:
        from spectra.services import fire_history
        fire_history.record_fire(FIRE_HISTORY_BUCKET, f"{vid}.{pname}", {
            "virtual_id": vid, "effect_type": effect_type, "param": pname,
            "found": live_val, "restored_to": expected,
            "orphaned_for_s": round(age_s, 1), "method": method,
            "attempt": attempt})
    except Exception:
        logger.exception("param watchdog: fire_history record failed")
    if attempt >= RESTORE_ATTEMPT_LIMIT:
        _given_up[key] = {"expected": expected, "attempts": attempt,
                          "at_wall_ms": entry["at_wall_ms"],
                          "virtual_id": vid, "param": pname}
        logger.critical(
            "PARAM ORPHAN NOT TAKING — %s.%s restored %d times to %r and "
            "still reads away from baseline with nothing holding it; "
            "giving up on it until the baseline changes or the next scene "
            "fire. Something keeps re-moving it, or the effect's schema is "
            "rejecting the write — find the cause.",
            vid, pname, attempt, expected)
    return entry


async def run_supervised(deps_factory: Callable[[], Deps] = production_deps,
                         interval_s: float = SWEEP_INTERVAL_S) -> None:
    """Own asyncio task (spectra/app.py lifespan, beside frame_watchdog/
    ownership_reconciler/ambient verifier/flare-preview sweep): a crashing
    sweep is logged and retried, never fatal to the process."""
    while True:
        try:
            await sweep_once(deps_factory())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("param watchdog sweep crashed (retrying): %r", exc)
        await asyncio.sleep(interval_s)


# ── observability ──────────────────────────────────────────────────────────

def _suspected_list() -> list[dict]:
    now_wall = time.time()
    return [{"virtual_id": vid, "param": pname,
             "live": track["live"], "expected": track["expected"],
             "seen_for_s": round(max(0.0, now_wall - track["first_seen_wall"]), 1)}
            for (vid, pname), track in _tracking.items()]


def status() -> dict:
    return {
        "sweep_interval_s": SWEEP_INTERVAL_S,
        "orphan_grace_s": ORPHAN_GRACE_S,
        "last_sweep_age_s": (round(time.time() - _last_sweep_wall, 1)
                             if _last_sweep_wall is not None else None),
        "last_sweep": _last_sweep,
        "suspected": _suspected_list(),
        "restores_total": _restores_total,
        "recent_restores": list(_restores)[-10:],
        "given_up": list(_given_up.values()),
    }


def liveness_summary() -> dict:
    """The compact, additive slice for GET /spectra/api/liveness —
    informational only, never part of `healthy`: a recurring orphan is
    something to SEE on the fleet's own check, not something to restart
    the process over."""
    last = _restores[-1] if _restores else None
    return {
        "restores_total": _restores_total,
        "suspected": len(_tracking),
        "given_up": len(_given_up),
        "last_sweep_skipped": (_last_sweep or {}).get("skipped"),
        "last_sweep_age_s": (round(time.time() - _last_sweep_wall, 1)
                             if _last_sweep_wall is not None else None),
        "last_restore": last,
    }
