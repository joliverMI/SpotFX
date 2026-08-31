"""THE ROOM-EFFECTS LAYER — one bounded writer turning a field over the
room's measured light map into a per-emitter brightness gain, applied
MULTIPLICATIVELY at the one write seam.

IT COMPOSES, IT NEVER REPLACES. A room effect is the same shape as the
room's brightness dimmer: a factor the show's own output passes through.
The wave does not fire a scene, does not pick a colour, does not pause the
sequencer — his fish keeps swimming and a Dim Wave over it is one toggle,
not a scene rebuild (the plan's own suggestion card). Two halves, and both
are needed:

  * spectra/services/fx_seam.apply_writes calls `compose()` on every write
    it sends, so the SHOW's own writes already carry the wave's current gain
    and a scene fire mid-wave cannot stomp a fixture back to full;
  * the TICK loop below re-writes `brightness` for each driven virtual at
    TICK_HZ, because a field that travels has to keep moving between the
    show's own (sparse, irregular) writes.

The base each gain multiplies is the show's OWN authored brightness, learned
from the writes passing through compose() and seeded from the live effect
configs at start. Nothing here invents a brightness.

BOUNDED, and by the machinery that was already proven: a run holds the room
through flare_preview_hold.open_program_hold, so the snapshot, the deadline,
the independent sweep, the 3-minute absolute ceiling, the persisted snapshot
a restart lands back, and the 1 ms tween-safe revert are all inherited. The
hold is opened WITHOUT arming preview_pause: the show keeps playing
underneath, which is the plan's own answer to its open question ("ride on
top, like the dimmer" — his call to change, and changing it is one call to
preview_pause.start, not a redesign).

THE CONSEQUENCE OF THAT, STATED RATHER THAN HIDDEN: a running room effect
cannot currently outlive the hold's 3-minute ceiling. For a slice whose
entire safety story is the held-room seam that is the right trade — a
forgotten wave is a 3-minute nuisance, not a lost show — but it does mean
"leave the wave on all evening" is not yet a thing this build does. Lifting
it needs its own lifetime story, not a bigger number.

THE WATCHDOG KNOWS. spectra/services/param_watchdog.py restores a param
that has drifted from its baseline with nothing holding it; a running wave
moves `brightness` continuously and by design. The layer therefore
registers as a genuine HOLDER for exactly the (virtual, "brightness") keys
it is driving — the same shape as a pending release or a drift mechanism,
checked per key, never a global stand-down of the watchdog while an effect
runs.

WRITE COST IS MEASURED, NOT ASSUMED (the plan's own named risk: "a wave
ticking every emitter at 20 Hz is more write traffic than any current room
mode; the slice measures real cost on two devices before phase 2 scales
it"). Every tick's seam call is timed and `status()` reports p50/p95/max
and the achieved rate, so the number in the report comes from the
instrument rather than from arithmetic.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from spectra import config
from spectra.models.room_map import RoomMap
from spectra.services import flare_preview_hold, light_field
from spectra.services.light_field_fields import KINDS, DimWave

logger = logging.getLogger(__name__)

#: Modest, in the plan's own 10-20 Hz band. 15 Hz is one write per virtual
#: per 67 ms — slow enough to be nothing next to a render loop, fast enough
#: that a wave crossing the room in 4 s moves in steps well under what the
#: eye resolves as a step.
TICK_HZ = 15.0
#: How often the driven virtuals' effect TYPES are re-read from the seam.
#: compose() keeps them current for every write that passes through it; this
#: is the belt-and-braces for anything that ever writes another way.
TYPE_REFRESH_S = 10.0
WRITE_TRANSITION_MS = 1        # fx_executor's JUMP_MS convention
COST_SAMPLES = 200
#: The hold window a running effect re-arms. The page heartbeats well inside
#: it; the absolute ceiling still bounds the whole session.
HOLD_HEARTBEAT_S = 15.0


class RoomEffectSpec(BaseModel):
    """One authored effect. Only `dim_wave` is built — the other three kinds
    exist as pure fields (light_field_fields.py) and are deliberately not
    selectable here."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    room_id: str
    name: str = "Dim Wave"
    kind: str = "dim_wave"
    #: axis units: 1.0 = one full cycle across the whole floor->ceiling axis
    wavelength: float = Field(default=1.0, ge=0.05, le=8.0)
    #: cycles per second the pattern travels; positive = toward the ceiling
    speed: float = Field(default=0.25, ge=-4.0, le=4.0)
    #: how far the trough dips; 0.0 is an exact no-op
    depth: float = Field(default=0.6, ge=0.0, le=1.0)
    #: which of the room's mapped emitters this effect drives; empty = all
    device_ids: list[str] = Field(default_factory=list)

    def field(self):
        if self.kind != "dim_wave":
            raise ValueError(
                f"kind {self.kind!r} is declared in the interface but not "
                f"built in this slice — see light_field_fields.KINDS")
        return DimWave(wavelength=self.wavelength, speed=self.speed,
                       depth=self.depth)


# ── the store (authored specs only; running state is never persisted) ──────

def _path(path: Optional[os.PathLike] = None):
    return config.ROOM_EFFECTS_FILE if path is None else path


def load_effects(path: Optional[os.PathLike] = None) -> list[RoomEffectSpec]:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            return [RoomEffectSpec(**e) for e in (json.load(fh).get("effects") or [])]
    except Exception:
        logger.exception("room_effects: unreadable store %s", p)
        return []


def save_effects(effects: list[RoomEffectSpec], path: Optional[os.PathLike] = None) -> None:
    p = _path(path)
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="room_effects", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"effects": [e.model_dump() for e in effects]}, fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def put_effect(spec: RoomEffectSpec, path: Optional[os.PathLike] = None) -> RoomEffectSpec:
    items = [e for e in load_effects(path) if e.id != spec.id] + [spec]
    save_effects(items, path)
    return spec


def delete_effect(effect_id: str, path: Optional[os.PathLike] = None) -> bool:
    items = load_effects(path)
    kept = [e for e in items if e.id != effect_id]
    if len(kept) == len(items):
        return False
    save_effects(kept, path)
    return True


# ── running state ──────────────────────────────────────────────────────────

@dataclass
class _Driven:
    """One emitter as the runner drives it: its measured samples and the
    virtuals its light comes out of."""
    emitter_id: str
    samples: Any
    virtual_ids: list[str]


@dataclass
class _State:
    running: bool = False
    spec: Optional[RoomEffectSpec] = None
    room_id: str = ""
    driven: list[_Driven] = field(default_factory=list)
    gains: dict[str, float] = field(default_factory=dict)        # virtual -> gain
    base: dict[str, float] = field(default_factory=dict)         # virtual -> show brightness
    effect_type: dict[str, str] = field(default_factory=dict)    # virtual -> live type
    started_at: float = 0.0
    ticks: int = 0
    writes: int = 0
    cost_s: deque = field(default_factory=lambda: deque(maxlen=COST_SAMPLES))
    last_error: str = ""
    task: Optional[asyncio.Task] = None


_state = _State()


def reset() -> None:
    """Drop every trace of a run — module-global state, so the tests' own
    fixture calls this (the fire_history/param_watchdog precedent: no DI
    seam on the module itself, only on what a run touches)."""
    global _state
    if _state.task is not None:
        _state.task.cancel()
    _state = _State()


# ── the composition seam ───────────────────────────────────────────────────

def _live() -> bool:
    """Gains apply only while a run is genuinely live AND the held room is
    still held. The second half matters: flare_preview_hold's revert writes
    the pre-effect config back through the same seam, and scaling THAT by a
    gain would hand the room back dimmed. `active()` is a pure deadline read
    that has already gone False by the time the sweep reverts, and stop()
    clears `running` before an explicit close — so both revert paths land
    unscaled, by construction rather than by ordering luck."""
    if not _state.running:
        return False
    return flare_preview_hold.active()


def gain_for(virtual_id: str) -> float:
    """The gain currently applied to this virtual — 1.0 when no effect is
    running or this virtual is not driven."""
    return _state.gains.get(virtual_id, 1.0) if _live() else 1.0


def compose(virtual_id: str, effect_type: str, cfg: dict) -> dict:
    """Apply the running gain to one write's config, and learn from it.

    Called by fx_seam.apply_writes for every write it sends. Identity — the
    SAME dict object back — whenever nothing is running, so the seam's
    normal path is untouched by this feature's existence.

    Two things are learned here rather than polled: the show's own authored
    `brightness` (the base every gain multiplies) and the virtual's live
    effect type (what the tick loop must name so a brightness write merges
    into the running effect instead of switching it)."""
    if not _live():
        return cfg
    if effect_type:
        _state.effect_type[virtual_id] = effect_type
    gain = _state.gains.get(virtual_id)
    if gain is None:
        return cfg
    value = cfg.get("brightness")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return cfg
    _state.base[virtual_id] = float(value)
    return {**cfg, "brightness": max(0.0, min(1.0, float(value) * gain))}


def holds() -> set[tuple[str, str]]:
    """The (virtual, param) keys a running effect legitimately owns — read
    by param_watchdog.sweep_once so a travelling wave is never "repaired"
    back to its baseline. Empty when nothing is running, so the watchdog's
    behaviour is unchanged by this feature's existence."""
    if not _live():
        return set()
    return {(vid, "brightness") for vid in _state.gains}


# ── the runner ─────────────────────────────────────────────────────────────

@dataclass
class RunnerDeps:
    """The seams a run touches. Production wires fx_seam and the real hold;
    the headless proof hands in the same functions pointed at fx.headless,
    and the unit tests hand in fakes."""
    apply_writes: Callable[..., Any]
    get_virtuals: Callable[[], Any]
    open_hold: Optional[Callable[..., Any]] = None
    close_hold: Optional[Callable[[], Any]] = None
    touch_hold: Optional[Callable[[float], Any]] = None
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Any] = asyncio.sleep


def production_deps() -> RunnerDeps:
    from spectra.services import fx_seam
    return RunnerDeps(apply_writes=fx_seam.apply_writes,
                      get_virtuals=fx_seam.get_virtuals,
                      open_hold=flare_preview_hold.open_program_hold,
                      close_hold=flare_preview_hold.close_hold,
                      touch_hold=flare_preview_hold.touch)


class RoomEffectProgram(flare_preview_hold.PreviewProgram):
    """The hold's program: it exists to make the driven virtuals part of the
    hold's SNAPSHOT, and it writes nothing of its own.

    Deliberately no apply_scene call: a room effect rides on top of whatever
    the show is doing, so landing a synthetic scene would be the one thing
    this layer promises never to do. Everything it needs from the hold —
    snapshot, deadline, sweep, ceiling, restart recovery, revert — comes
    from being a program at all."""

    steps = ("arm",)

    def __init__(self, virtual_ids: list[str]) -> None:
        from spectra.services.room_mapping import dark_scene
        # The scene's WRITES are only ever read for their virtual ids (the
        # snapshot basis); they are never applied, which is why a plain
        # per-virtual scene is the right shape and its colours are irrelevant.
        self.hold_scene = dark_scene(list(dict.fromkeys(virtual_ids)))

    async def execute(self, step: str, ctx) -> dict:
        return {"result": "armed", "virtuals": len(self.hold_scene.devices)}


def resolve_driven(room: RoomMap, spec: RoomEffectSpec) -> list[_Driven]:
    """The emitters this effect drives: those the room has actually MAPPED,
    narrowed by the spec's device selection. An unmapped device is silently
    absent from the result — the API reports it by name so "why is that
    sconce not moving" is answered by the page, not by a mystery."""
    wanted = set(spec.device_ids) if spec.device_ids else None
    out: list[_Driven] = []
    for fp in room.footprints:
        if not fp.mapped:
            continue
        if wanted is not None and fp.emitter_id not in wanted:
            continue
        out.append(_Driven(emitter_id=fp.emitter_id,
                           samples=light_field.samples_for(fp, room.axis),
                           virtual_ids=list(fp.virtual_ids)))
    return out


def compute_gains(driven: list[_Driven], field_fn, t: float) -> dict[str, float]:
    """emitter gains -> per-virtual gains. An emitter's gain applies to every
    virtual its light came out of, because that is what was measured: the
    footprint was captured with all of them lit together."""
    per_emitter = light_field.per_emitter_scalar(
        field_fn, t, samples=[d.samples for d in driven])
    gains: dict[str, float] = {}
    for d in driven:
        g = per_emitter.get(d.emitter_id)
        if g is None:
            continue
        for vid in d.virtual_ids:
            gains[vid] = max(0.0, min(1.0, float(g)))
    return gains


async def start(room: RoomMap, spec: RoomEffectSpec,
                deps: Optional[RunnerDeps] = None) -> dict:
    """Hold the room and start the wave. Returns a stated outcome — never a
    silent no-op — including which of the spec's devices are not mapped."""
    deps = deps or production_deps()
    await stop(deps)
    driven = resolve_driven(room, spec)
    unmapped = [d for d in (spec.device_ids or room.device_ids)
                if d not in {x.emitter_id for x in driven}]
    if not driven:
        return {"running": False,
                "reason": ("none of the selected devices has a measured "
                           "footprint yet — map the room first"),
                "unmapped": unmapped}
    virtual_ids = sorted({v for d in driven for v in d.virtual_ids})

    live = await deps.get_virtuals() or {}
    base: dict[str, float] = {}
    types: dict[str, str] = {}
    for vid in virtual_ids:
        eff = ((live.get(vid) or {}).get("effect") or {})
        if eff.get("type"):
            types[vid] = eff["type"]
            b = (eff.get("config") or {}).get("brightness")
            base[vid] = float(b) if isinstance(b, (int, float)) and not isinstance(b, bool) else 1.0
    known = [v for v in virtual_ids if v in types]
    if not known:
        return {"running": False,
                "reason": ("none of the mapped virtuals is rendering an "
                           "effect right now — is SPECTRA driving the room?"),
                "unmapped": unmapped}

    if deps.open_hold is not None:
        held = await deps.open_hold(RoomEffectProgram(known), 1.0, step="arm",
                                    heartbeat_timeout_s=HOLD_HEARTBEAT_S)
        if not (held or {}).get("held"):
            return {"running": False,
                    "reason": f"the room could not be held: "
                              f"{(held or {}).get('reason') or 'no writes'}",
                    "unmapped": unmapped}

    _state.running = True
    _state.spec = spec
    _state.room_id = room.id
    _state.driven = [_Driven(d.emitter_id, d.samples,
                             [v for v in d.virtual_ids if v in types])
                     for d in driven]
    _state.base = base
    _state.effect_type = types
    _state.gains = {v: 1.0 for v in known}
    _state.started_at = deps.clock()
    _state.ticks = 0
    _state.writes = 0
    _state.cost_s.clear()
    _state.last_error = ""
    _state.task = asyncio.create_task(_run(deps), name="spectra-room-effect")
    return {"running": True, "effect": spec.model_dump(),
            "emitters": [d.emitter_id for d in _state.driven],
            "virtuals": known, "unmapped": unmapped,
            "tick_hz": TICK_HZ}


async def stop(deps: Optional[RunnerDeps] = None) -> dict:
    """Stop the wave and hand the room back.

    ORDER IS LOAD-BEARING: `running` goes False FIRST, so the hold's revert
    write passes through compose() unscaled and the room comes back at the
    brightness it had, not at the brightness the wave happened to be on."""
    deps = deps or production_deps()
    was = _state.running
    _state.running = False
    task, _state.task = _state.task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:                              # noqa: BLE001
            logger.exception("room_effects: runner raised on cancel")
    _state.gains = {}
    if deps.close_hold is not None:
        await deps.close_hold()
    return {"stopped": bool(was)}


async def _run(deps: RunnerDeps) -> None:
    """The tick loop. Paced against the DEADLINE, not by sleeping a whole
    period after the work: an in-process seam write costs real milliseconds
    (see write_cost()), and sleeping a full period on top of it drifts the
    achieved rate below the target — which would make a wave's speed knob
    mean something slightly different from what it says."""
    period = 1.0 / TICK_HZ
    t0 = deps.clock()
    due = t0
    last_types = t0
    spec = _state.spec
    field_fn = spec.field()
    while _state.running:
        try:
            if deps.open_hold is not None and not flare_preview_hold.active():
                # The hold lapsed (an abandoned page, the ceiling) and its
                # sweep has already handed the room back — a wave must not
                # keep writing over a room it no longer holds.
                _state.running = False
                _state.last_error = "the held room lapsed — the wave stopped with it"
                break
            now = deps.clock()
            if deps.touch_hold is not None:
                await deps.touch_hold(HOLD_HEARTBEAT_S)
            if now - last_types >= TYPE_REFRESH_S:
                last_types = now
                await _refresh_types(deps)
            _state.gains = compute_gains(_state.driven, field_fn, now - t0)
            await _write_tick(deps)
            _state.ticks += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # noqa: BLE001
            _state.last_error = str(exc)
            logger.exception("room_effects: tick failed")
        due += period
        # Never sleep zero in a hot loop and never try to CATCH UP by
        # firing several ticks back to back: a wave that fell behind should
        # simply be where it is now (its phase is a function of wall time),
        # so a missed tick is skipped, not replayed.
        remaining = due - deps.clock()
        if remaining <= 0:
            due = deps.clock() + period
            remaining = period
        await deps.sleep(remaining)


async def _refresh_types(deps: RunnerDeps) -> None:
    live = await deps.get_virtuals() or {}
    for vid in list(_state.effect_type):
        eff = ((live.get(vid) or {}).get("effect") or {})
        if eff.get("type"):
            _state.effect_type[vid] = eff["type"]


async def _write_tick(deps: RunnerDeps) -> None:
    """One tick's writes: a partial config carrying only `brightness`, on
    the virtual's CURRENT effect type, so the vendored engine merges it into
    the running effect rather than rebuilding one.

    `room_effect` marks the payload so compose() leaves it alone — this
    write already carries the gain, and scaling it a second time would
    square the wave."""
    writes = []
    for vid, gain in _state.gains.items():
        etype = _state.effect_type.get(vid)
        if not etype:
            continue
        base = _state.base.get(vid, 1.0)
        writes.append({"virtual_id": vid, "effect_type": etype,
                       "config": {"brightness": max(0.0, min(1.0, base * gain))},
                       "room_effect": True})
    if not writes:
        return
    started = deps.clock()
    await deps.apply_writes(writes, transition_ms=WRITE_TRANSITION_MS)
    _state.cost_s.append(deps.clock() - started)
    _state.writes += len(writes)


# ── status / cost ──────────────────────────────────────────────────────────

def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def write_cost() -> dict:
    """The measured cost of driving this wave — the plan's named risk,
    answered with the instrument rather than with arithmetic. `per_tick_ms`
    is the wall time of ONE seam call carrying every driven virtual, which
    is what actually competes with the render loop."""
    costs = [c * 1000.0 for c in _state.cost_s]
    elapsed = max(1e-9, (time.monotonic() - _state.started_at)) if _state.started_at else 0.0
    return {
        "samples": len(costs),
        "virtuals_per_tick": len(_state.gains),
        "per_tick_ms": {"p50": round(_pct(costs, 0.5), 3),
                        "p95": round(_pct(costs, 0.95), 3),
                        "max": round(max(costs), 3) if costs else 0.0},
        "ticks": _state.ticks,
        "writes": _state.writes,
        "target_tick_hz": TICK_HZ,
        "achieved_tick_hz": round(_state.ticks / elapsed, 2) if elapsed else 0.0,
        "writes_per_s": round(_state.writes / elapsed, 1) if elapsed else 0.0,
    }


def status() -> dict:
    return {
        "running": _state.running,
        "live": _live(),
        "room_id": _state.room_id,
        "effect": _state.spec.model_dump() if _state.spec else None,
        "emitters": [d.emitter_id for d in _state.driven],
        "gains": {k: round(v, 4) for k, v in _state.gains.items()},
        "base": {k: round(v, 4) for k, v in _state.base.items()},
        "held_params": sorted(f"{v}:{p}" for v, p in holds()),
        "cost": write_cost(),
        "last_error": _state.last_error,
        "kinds": KINDS,
    }
