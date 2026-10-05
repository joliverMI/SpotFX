"""HOUSE LIGHTING — the resting layer (phase 1 of /home/javi/fleet-spotfx/
data/standard-lighting-plan/report.md, §4; his ask 2026-10-04: "I'd like to
use spectra as my standard lighting engine, not just for music").

A HOUSE MODE (spectra/models/house_mode.py) is what the room looks like when
nothing more specific is happening. This module applies the one that is set.

═══ INERT UNLESS SPECTRA HOLDS THE ROOM AND A MODE IS SET ═══

Home Assistant still drives his lights until phase 2 (River's seam), so this
layer does NOTHING — no write of any kind, no cap, no Hue directive — unless
both are true: a mode is set (house_state.json) AND `show_output.
ownership_refusal()` is None (SPECTRA owns the lights, the live stack is up,
the engine is live). Setting a mode while the room is released only records
it; it applies the moment SPECTRA holds the room. It never takes or releases
the room and has no code that could.

A preview, a camera run or a night run holding the room puts the layer on
STANDBY (`show_output.standdown_reason()`): no writes at all, frame-rate caps
lifted, the per-device output layer already suspended by the Light Show's
supervisor. When the hold ends the mode is re-asserted (its scene kept if it
is still showing).

═══ PRECEDENCE — a higher layer wins; removing it shows the one below ═══

  Light Show holds/levels/flashes   show_output's own holds sit ABOVE the
                                    base layer this module pushes (base ×
                                    show Level; a show hold wins the state)
  Force Scene / Force Colour        his pins: the mode does not fire a
                                    scene while a scene is pinned, nor
                                    apply colours while colours are pinned
  the music show                    see MUSIC below
  the mode                          this module

The base layer is pushed into show_output (not fx/device_output directly):
the output layer keeps ONE target per device, so two writers would clobber
each other. End show therefore fades back to the mode, not to an undimmed
picture.

═══ WHAT A MODE DOES WHILE IT RESTS ═══

  * per-fixture LEVEL / OFF   show_output.set_base — faded over the glide
  * frame-rate CAPS           fx/device_rate.py (VENDOR #43) — only lowers
  * MOTION                    the effect's registry-tagged motion param
                              (config/effect_params.json "motion": true),
                              written as a glide AND carried into the
                              conductor's baseline (on_surge), so drift and
                              the param watchdog agree with it
  * SCENES                    drawn from the mode's pool by weight through
                              scene_sequencer.fire_scene_by_id (origin
                              "house", the mode's glide as transition_ms) —
                              on entry, then every flow.scene_every_min.
                              A scene already showing that is in the new
                              mode's pool is KEPT, so two modes sharing a
                              scene change by a pure glide.
  * COLOURS                   the colour journey walks ONLY the mode's sets
                              (groups expanded to members) at the mode's
                              pace (journey_override, read by the
                              conductor); on entry a set from the pool is
                              landed as a GLIDE unless one already shows
  * HUE                       hue_directive — per-area colour temperature /
                              colour / off held over the bridge by
                              ambient_music_gate, never streamed; a mode
                              with no Hue looks leaves Hue to the Hue Hold
                              room setting exactly as before

═══ MUSIC ═══

`mode.music` decides what music does on top of the mode:

  show    the music show takes the room: on the first confirmed playing
          read the layer HANDS IN (levels back to 100%, caps lifted, motion
          restored to what the scene authored, over HAND_IN_FADE_S) and the
          engine runs exactly as it always has. When music has stayed
          stopped for transitions.music_debounce_s the room HANDS OUT —
          the mode is re-entered over music_return_glide_s.
  calm    the mode keeps its scene, levels and colours; the music's scene
          and colour changes are deferred, its flares still play.
  ignore  nothing music-driven fires at all (scene changes, flares, update
          flares, analysed colour).

Deferral is checked live (`scene_deferral()`, `response_deferral()`) at the
choke points the music engine already funnels through — fire_scene_by_id,
engine's response/update gates, the analysed colour event, the trigger
engine's colour-set action. An UNKNOWN playback read (bridge down) never
hands in or out on its own.

═══ TRANSITIONS ═══

A mode entered because Home Assistant's clock moved glides over
transitions.clock_glide_s (90 s); one entered on a press over
button_glide_s (5 s). An effect-type switch still crossfades in at most the
virtual's own cap (fx/virtuals.py); everything else — levels, colour,
motion, Hue `dynamics.duration` — takes the whole glide.

═══ WHO SET IT ═══

`set_mode` takes a mode by id/name or Home Assistant's own lighting_mode
word (an alias, house_store.mode_for_ha). A pick by a PERSON (source other
than "ha") is MANUAL: it holds until Home Assistant's value next CHANGES,
so HA's 5-minute re-assert of the same value is a no-op rather than a
fight. Nothing here invents a clock — HA keeps it (decision B1).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from spectra.models.house_mode import HouseMode, now_ms
from spectra.services import house_store

logger = logging.getLogger(__name__)

TICK_S = 1.0
#: mode → music: the layer lets go quickly; the show's own first fire leads.
HAND_IN_FADE_S = 2.0
#: a mode's own scene fire is an explicit act (a clock change, a press) —
#: never deferred by the music's minimum dwell. Recorded on the fire record
#: as dwell_tolerance_used_s, never silent.
HOUSE_DWELL_TOLERANCE_S = 24 * 3600.0
#: motion re-applied after someone else fired a scene under the mode.
MOTION_REAPPLY_GLIDE_S = 3.0
#: glide used when the mode is re-asserted after a standby (a preview etc.)
RESUME_GLIDE_S = 3.0
MAX_RECENT = 12

PHASE_INACTIVE = "inactive"
PHASE_STANDBY = "standby"
PHASE_RESTING = "resting"
PHASE_MUSIC = "music"


# ── what other modules read ────────────────────────────────────────────────

@dataclass(frozen=True)
class JourneyOverride:
    """The colour journey's pool and pace while a mode rests."""
    set_ids: frozenset
    deg_per_min: float
    mode_name: str


@dataclass(frozen=True)
class HueDirective:
    """How ambient_music_gate holds Hue while a mode drives it. `looks` is
    hashable — the gate compares it to what last landed."""
    looks: tuple
    ramp_ms: int
    mode_name: str

    @property
    def holds_any(self) -> bool:
        return any(lk[1] in ("hold", "off") for lk in self.looks)


@dataclass
class Plan:
    """A mode's fixture hooks resolved against the live room."""
    levels: dict = field(default_factory=dict)     # device -> 0..2
    states: dict = field(default_factory=dict)     # device -> "dark"
    caps: dict = field(default_factory=dict)       # device -> fps
    motion: dict = field(default_factory=dict)     # virtual -> 0..1
    problems: list = field(default_factory=list)


# ── seams (tests replace them; production imports lazily) ──────────────────

def _default_playing() -> Optional[bool]:
    try:
        from spectra.services.engine import bridge
        return bridge.is_playing()
    except Exception:                                    # noqa: BLE001
        return None


async def _default_fire_scene(scene_id: str, **kw) -> dict:
    from spectra.services import scene_sequencer
    return await scene_sequencer.fire_scene_by_id(scene_id, **kw)


async def _default_apply_set(card, glide_ms: int) -> dict:
    from spectra.services import engine
    return await engine.conductor.apply_set_directly(card, glide_ms=glide_ms)


def _default_conductor():
    from spectra.services import engine
    return engine.conductor


async def _default_sync_hue() -> Any:
    from spectra.services import ambient_music_gate
    return await ambient_music_gate.reconcile_now(wait=False)


def _default_room_active_set_id() -> Optional[str]:
    from spectra.services import color_journey
    return color_journey.load_room().active_set_id


@dataclass
class Deps:
    playing: Callable[[], Optional[bool]] = _default_playing
    fire_scene: Callable[..., Awaitable[dict]] = _default_fire_scene
    apply_set: Callable[[Any, int], Awaitable[dict]] = _default_apply_set
    conductor: Callable[[], Any] = _default_conductor
    sync_hue: Callable[[], Awaitable[Any]] = _default_sync_hue
    active_set_id: Callable[[], Optional[str]] = _default_room_active_set_id
    clock: Callable[[], float] = time.monotonic


deps = Deps()
_rng = random.Random()


# ── runtime ────────────────────────────────────────────────────────────────

@dataclass
class _Runtime:
    phase: str = PHASE_INACTIVE
    reason: str = "not started"
    applied_mode_id: Optional[str] = None
    applied_updated_ms: Optional[int] = None
    applied_glide_s: float = 0.0
    entered_at: Optional[float] = None
    last_scene_at: Optional[float] = None
    quiet_since: Optional[float] = None
    playing: Optional[bool] = None
    hue_ramp_ms: int = 0
    #: the directive's looks last handed to the Hue Hold gate — None at
    #: start, so a process that never sets a mode never pokes the gate
    hue_key: Any = None
    caps_pushed: bool = False
    base_pushed: bool = False
    #: (vid, param) -> the value the scene authored, captured before motion
    motion_authored: dict = field(default_factory=dict)
    motion_applied: dict = field(default_factory=dict)
    #: identity of the conductor re-baseline motion was applied against
    motion_key: Any = None
    recent: list = field(default_factory=list)
    last_problems: list = field(default_factory=list)


_rt = _Runtime()
_lock: Optional[asyncio.Lock] = None
_task: Optional[asyncio.Task] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def reset() -> None:
    """Tests: forget the module's own memory (not the stores)."""
    global _rt, _lock, deps
    _rt = _Runtime()
    _lock = None
    deps = Deps()


# ── the gate ───────────────────────────────────────────────────────────────

def current_mode() -> Optional[HouseMode]:
    return house_store.get_mode(house_store.state().mode_id)


def gate() -> tuple[Optional[str], Optional[str]]:
    """(kind, reason): ("refused", why) when the layer must do nothing at
    all, ("standby", why) when a preview/camera/night run holds the room,
    (None, None) when it may act. A mode must also be set — checked by the
    callers, which need the mode anyway."""
    try:
        from spectra.services import show_output
        refusal = show_output.ownership_refusal()
        if refusal:
            return "refused", _house_words(refusal)
        standdown = show_output.standdown_reason()
        if standdown:
            return "standby", _house_words(standdown)
    except Exception as exc:                             # noqa: BLE001
        return "refused", f"the room's state could not be read ({exc})"
    return None, None


def _house_words(reason: str) -> str:
    """show_output's reasons are written for the Light Show ("The Light Show
    never takes the room…"); the house reads the same fact without that
    sentence and without a trailing full stop, so it sits inside one."""
    for tail in (" The Light Show never takes the room; take it back first.",
                 " The Light Show never takes the room."):
        reason = reason.replace(tail, "")
    return reason.strip().rstrip(".")


def _live_mode() -> Optional[HouseMode]:
    """The set mode, only while the layer may act (or is on standby — its
    look still stands during a preview). None otherwise."""
    mode = current_mode()
    if mode is None:
        return None
    kind, _reason = gate()
    if kind == "refused":
        return None
    return mode


def _resting_now(mode: HouseMode, playing: Optional[bool]) -> bool:
    """Is the mode's look the room's look right now (live read, so the
    hooks are right before the supervisor's next tick)."""
    if mode.music != "show":
        return True
    if playing is True:
        return False
    return _rt.phase != PHASE_MUSIC


# ── hooks other modules call (sync, cheap, never raise) ────────────────────

def scene_deferral() -> Optional[str]:
    """Why an AUTOMATIC scene (or colour) pick must wait, or None. A
    resting mode owns the scene; a calm/ignore mode keeps it through
    music."""
    try:
        mode = _live_mode()
        if mode is None:
            return None
        if mode.music in ("calm", "ignore"):
            return f"house mode {mode.name!r} keeps its look while music plays ({mode.music})"
        if _resting_now(mode, deps.playing()):
            return f"house mode {mode.name!r} is resting — it owns the scene"
        return None
    except Exception:                                    # noqa: BLE001
        logger.exception("house: scene_deferral failed — not deferring")
        return None


def response_deferral() -> Optional[str]:
    """Why a music response (flare, charge/lull/drop, update flare) must
    not fire, or None. Only an "ignore" mode silences them."""
    try:
        mode = _live_mode()
        if mode is None or mode.music != "ignore":
            return None
        return f"house mode {mode.name!r} ignores music"
    except Exception:                                    # noqa: BLE001
        logger.exception("house: response_deferral failed — not deferring")
        return None


def _expanded_set_ids(mode: HouseMode) -> frozenset:
    from spectra.services import color_sets
    out: set[str] = set()
    for pick in mode.color_sets:
        if pick.weight <= 0:
            continue
        card = color_sets.get_by_id(pick.card_id)
        if card is None or getattr(card, "disabled", False):
            continue
        if getattr(card, "kind", "set") == "group":
            out.update(m.color_set_id for m in getattr(card, "members", []) or [])
        else:
            out.add(card.id)
    return frozenset(out)


def journey_override() -> Optional[JourneyOverride]:
    """The colour journey's pool and pace while a mode rests, or None."""
    try:
        mode = _live_mode()
        if mode is None or not mode.color_sets:
            return None
        if not _resting_now(mode, deps.playing()):
            return None
        return JourneyOverride(set_ids=_expanded_set_ids(mode),
                               deg_per_min=float(mode.flow.journey_deg_per_min),
                               mode_name=mode.name)
    except Exception:                                    # noqa: BLE001
        logger.exception("house: journey_override failed — journey unchanged")
        return None


def _looks(mode: HouseMode) -> tuple:
    return tuple(sorted((lk.area, lk.look, lk.mirek, lk.color, float(lk.brightness))
                        for lk in mode.hue))


def hue_directive() -> Optional[HueDirective]:
    """How Hue is held right now, or None to leave it to the Hue Hold room
    setting (no mode, the room not ours, or a mode with no Hue looks)."""
    mode = _live_mode()
    if mode is None or not mode.hue:
        return None
    ramp = _rt.hue_ramp_ms or int(mode.transitions.clock_glide_s * 1000)
    if not _resting_now(mode, deps.playing()):
        if mode.music_hue == "room":
            return None
        if mode.music_hue == "join":
            # Every area follows the show's stream: a directive that holds
            # nothing (released through the gate's own two-phase ease).
            return HueDirective(looks=(("*", "show", None, None, 100.0),),
                                ramp_ms=int(HAND_IN_FADE_S * 1000),
                                mode_name=mode.name)
    return HueDirective(looks=_looks(mode), ramp_ms=ramp, mode_name=mode.name)


# ── setting the mode ───────────────────────────────────────────────────────

def _record(kind: str, detail: dict) -> None:
    entry = {"at_ms": now_ms(), "kind": kind, **detail}
    _rt.recent.append(entry)
    del _rt.recent[:-MAX_RECENT]
    try:
        from spectra.services import fire_history
        fire_history.record_fire("house", kind, detail)
    except Exception:                                    # noqa: BLE001
        logger.exception("house: fire-history write failed")


def _clamp_glide(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return max(0.0, min(600.0, float(v)))


async def set_mode(*, mode: Optional[str] = None, ha_mode: Optional[str] = None,
                   source: str = "spectra", glide_s: Optional[float] = None,
                   clear: bool = False) -> dict:
    """Select a mode by id/name (`mode`), by Home Assistant's own word
    (`ha_mode`), or clear it. Idempotent. Applies at once when the layer
    may act; otherwise it is recorded and applies when SPECTRA holds the
    room. Returns {"status", "lighting"} — status is one of applied /
    unchanged / held_manual / unmapped / unknown_mode / cleared."""
    st = house_store.state()
    source = (source or "spectra").strip() or "spectra"
    manual = source != "ha"
    glide_s = _clamp_glide(glide_s)
    status = "unchanged"
    target: Optional[HouseMode] = None

    if clear:
        if st.mode_id is not None or not st.manual:
            st.mode_id = None
            st.source = source
            st.since_ms = now_ms()
            st.manual = True
            st.glide_s = glide_s if glide_s is not None else 5.0
            status = "cleared"
            _record("cleared", {"source": source})
        house_store.save_state()
        await tick()
        return {"status": status, "lighting": status_dict()}

    if ha_mode is not None:
        value = ha_mode.strip()
        changed_ha = (st.ha_value or "").strip().lower() != value.lower()
        st.ha_value = value
        st.ha_value_ms = now_ms()
        target = house_store.mode_for_ha(value)
        if source == "ha" and changed_ha:
            st.manual = False   # HA moved on: a person's pick has had its time
        if source == "ha" and st.manual and not changed_ha:
            house_store.save_state()
            return {"status": "held_manual", "ha_value": value,
                    "lighting": status_dict()}
        if target is None:
            house_store.save_state()
            if changed_ha:
                _record("unmapped", {"ha_value": value, "source": source})
            return {"status": "unmapped", "ha_value": value,
                    "reason": f"no house mode answers to {value!r}",
                    "lighting": status_dict()}
    elif mode is not None:
        target = house_store.find_mode(mode)
        if target is None:
            return {"status": "unknown_mode", "mode": mode,
                    "reason": f"no house mode called {mode!r}",
                    "known": [m.name for m in house_store.list_modes()],
                    "lighting": status_dict()}
    else:
        return {"status": "unchanged", "reason": "nothing asked for",
                "lighting": status_dict()}

    if target.id == st.mode_id:
        if st.manual != manual:
            st.manual = manual
            st.source = source
        house_store.save_state()
        await tick()
        return {"status": "unchanged", "lighting": status_dict()}

    previous = st.mode_id
    st.mode_id = target.id
    st.source = source
    st.since_ms = now_ms()
    st.manual = manual
    st.glide_s = (glide_s if glide_s is not None else
                  target.transitions.button_glide_s if manual
                  else target.transitions.clock_glide_s)
    house_store.save_state()
    status = "applied"
    _record("mode", {"mode": target.name, "mode_id": target.id, "source": source,
                     "manual": manual, "glide_s": st.glide_s,
                     "previous_mode_id": previous})
    await tick()
    return {"status": status, "lighting": status_dict()}


# ── the supervisor ─────────────────────────────────────────────────────────

async def tick() -> None:
    """One pass (also called right after set_mode, so a change applies
    now). Errors are logged — one bad pass never stops the layer."""
    async with _get_lock():
        try:
            await _tick_locked()
        except Exception:                                # noqa: BLE001
            logger.exception("house: tick failed")


async def _tick_locked() -> None:
    st = house_store.state()
    mode = current_mode()
    kind, reason = gate()
    if mode is None:
        why = ("no mode set" if st.mode_id is None
               else f"the set mode ({st.mode_id}) no longer exists")
        # Cleared while the room is ours: fade the look off over the glide
        # the clear asked for, restoring motion. Otherwise nothing to write.
        await _go_inactive(why, fade_s=st.glide_s or HAND_IN_FADE_S,
                           write_motion=kind is None)
        return
    if kind == "refused":
        await _go_inactive(reason or "the room is not SPECTRA's",
                           fade_s=HAND_IN_FADE_S, write_motion=False)
        return
    if kind == "standby":
        _go_standby(reason or "something else holds the room")
        await _sync_hue()
        return

    now = deps.clock()
    playing = deps.playing()
    _rt.playing = playing
    if playing is True:
        _rt.quiet_since = None
    elif playing is False and _rt.quiet_since is None:
        _rt.quiet_since = now

    if mode.music == "show":
        if playing is True and _rt.phase != PHASE_MUSIC:
            await _hand_in(mode)
            await _sync_hue()
            return
        if _rt.phase == PHASE_MUSIC:
            quiet_for = (now - _rt.quiet_since) if _rt.quiet_since is not None else 0.0
            if playing is False and quiet_for >= mode.transitions.music_debounce_s:
                await _enter(mode, mode.transitions.music_return_glide_s,
                             why="music stopped", refire=True,
                             prefer_remembered=True)
            await _sync_hue()
            return

    if _rt.phase == PHASE_STANDBY and _rt.applied_mode_id == mode.id:
        await _enter(mode, RESUME_GLIDE_S, why="resumed after standby")
    elif _rt.phase != PHASE_RESTING or _rt.applied_mode_id != mode.id:
        # The first pass of this process re-enters the mode it was in: the
        # remembered scene and colour, so a restart keeps the picture.
        first = _rt.reason == "not started"
        why = "restart" if first else "mode change"
        glide = st.glide_s
        if first:
            glide = max(glide, mode.transitions.button_glide_s)
        await _enter(mode, glide, why=why, prefer_remembered=True)
    elif _rt.applied_updated_ms != mode.updated_ms:
        await _enter(mode, mode.transitions.button_glide_s, why="mode edited")
    else:
        await _maintain(mode, now)
    await _sync_hue()


async def run_supervised() -> None:
    while True:
        await tick()
        await asyncio.sleep(TICK_S)


# ── phases ─────────────────────────────────────────────────────────────────

async def _go_inactive(why: str, *, fade_s: float, write_motion: bool) -> None:
    if (_rt.phase != PHASE_INACTIVE or _rt.base_pushed or _rt.caps_pushed
            or _rt.motion_applied):
        await _let_go(fade_s=fade_s, write_motion=write_motion)
        if _rt.phase != PHASE_INACTIVE:
            _record("inactive", {"reason": why})
    _rt.phase = PHASE_INACTIVE
    _rt.reason = why
    _rt.applied_mode_id = None
    _rt.applied_updated_ms = None
    _rt.motion_authored = {}
    _rt.motion_applied = {}
    _rt.motion_key = None
    await _sync_hue()


def _go_standby(why: str) -> None:
    """No writes. Caps lifted (a capture wants fresh frames); the output
    layer is already suspended by the Light Show's supervisor."""
    if _rt.phase != PHASE_STANDBY:
        _record("standby", {"reason": why})
    if _rt.caps_pushed:
        from fx import device_rate
        device_rate.clear()
        _rt.caps_pushed = False
    if _rt.phase in (PHASE_RESTING, PHASE_STANDBY):
        _rt.phase = PHASE_STANDBY
    _rt.reason = why


async def _let_go(*, fade_s: float, write_motion: bool) -> None:
    """Take the mode's look off the room: base levels faded back, caps
    lifted, motion restored to what the scene authored (only while that
    scene is still the one showing — a newer fire already authored its
    own)."""
    from fx import device_rate
    from spectra.services import show_output
    if _rt.base_pushed or show_output.base_snapshot()["levels"] \
            or show_output.base_snapshot()["states"]:
        show_output.set_base({}, {}, fade_s=fade_s)
        _rt.base_pushed = False
    if _rt.caps_pushed:
        device_rate.clear()
        _rt.caps_pushed = False
    if write_motion:
        await _restore_motion(fade_s)
    else:
        _rt.motion_applied = {}


async def _hand_in(mode: HouseMode) -> None:
    await _let_go(fade_s=HAND_IN_FADE_S, write_motion=True)
    _rt.phase = PHASE_MUSIC
    _rt.reason = "music is playing — the show has the room"
    _rt.hue_ramp_ms = int(HAND_IN_FADE_S * 1000)
    _record("music_in", {"mode": mode.name})


async def _enter(mode: HouseMode, glide_s: float, *, why: str,
                 refire: bool = False, prefer_remembered: bool = False) -> None:
    glide_s = max(0.0, float(glide_s))
    plan = build_plan(mode)
    from fx import device_rate
    from spectra.services import show_output
    show_output.set_base(plan.levels, plan.states, fade_s=glide_s)
    _rt.base_pushed = bool(plan.levels or plan.states)
    device_rate.set_caps(plan.caps)
    _rt.caps_pushed = bool(plan.caps)
    _rt.hue_ramp_ms = int(glide_s * 1000)
    look = await _apply_scene_and_colour(mode, glide_s, refire=refire,
                                         prefer_remembered=prefer_remembered)
    # Motion AFTER the scene: a fire re-baselines the conductor, and the
    # virtuals it writes motion onto are the new scene's.
    await _apply_motion(mode, glide_s)
    now = deps.clock()
    _rt.last_scene_at = now
    _rt.phase = PHASE_RESTING
    _rt.reason = why
    _rt.applied_mode_id = mode.id
    _rt.applied_updated_ms = mode.updated_ms
    _rt.applied_glide_s = glide_s
    _rt.entered_at = now
    _rt.last_problems = plan.problems + look.get("problems", [])
    _record("enter", {"mode": mode.name, "why": why, "glide_s": glide_s,
                      **{k: v for k, v in look.items() if k != "problems"},
                      "levels": len(plan.levels), "caps": len(plan.caps),
                      "off": len(plan.states), "problems": _rt.last_problems})


async def _maintain(mode: HouseMode, now: float) -> None:
    """While resting: the flow clock, and motion re-applied if someone
    else fired a scene under the mode (a Light Show step, a pin)."""
    every = mode.flow.scene_every_min
    if (every > 0 and _rt.last_scene_at is not None
            and now - _rt.last_scene_at >= every * 60.0):
        look = await _flow_scene(mode)
        _rt.last_scene_at = now
        if look.get("scene_fired"):
            _record("flow", {"mode": mode.name, **{k: v for k, v in look.items()
                                                  if k != "problems"}})
            await _apply_motion(mode, mode.transitions.clock_glide_s)
            return
    if _rebaseline_key() != _rt.motion_key:
        await _apply_motion(mode, MOTION_REAPPLY_GLIDE_S)


async def _sync_hue() -> None:
    """Ask the Hue Hold gate to re-read the directive whenever it changed
    (it also re-reads on every bridge broadcast)."""
    try:
        d = hue_directive()
    except Exception:                                    # noqa: BLE001
        logger.exception("house: hue directive failed")
        d = None
    key = d.looks if d is not None else None
    if key == _rt.hue_key:
        return
    _rt.hue_key = key
    try:
        await deps.sync_hue()
    except Exception:                                    # noqa: BLE001
        logger.exception("house: Hue Hold sync failed")


# ── the plan ───────────────────────────────────────────────────────────────

def _virtuals_for(target: dict, live_vids: list[str]) -> list[str]:
    kind = target.get("kind", "everything")
    if kind == "everything":
        return list(live_vids)
    if kind == "category":
        from fx import device_model
        cat = set(device_model.get_virtuals_for_category(target.get("id") or ""))
        return [v for v in live_vids if v in cat]
    if kind == "fixture":
        from spectra.services import show_output
        host = show_output._host()
        if host is None:
            return []
        return [v for v in live_vids
                if target.get("id") in show_output._virtual_devices(host, v)]
    return []


def build_plan(mode: HouseMode) -> Plan:
    """Resolve the mode's fixture hooks against the live room. Hooks apply
    in order; a later hook wins a field an earlier one set. A target that
    resolves to nothing is a stated problem, never a guess. Take scope is
    respected by construction: show_output.resolve_target only ever returns
    fixtures the current take holds."""
    from spectra.services import show_output
    plan = Plan()
    for i, hook in enumerate(mode.fixtures, 1):
        target = hook.target.model_dump()
        wants_device = hook.level is not None or hook.off or hook.fps is not None
        if wants_device:
            devices, problems = show_output.resolve_target(target)
            if not devices:
                plan.problems.append(f"fixture setting {i}: "
                                     + ("; ".join(problems) or "reaches no fixture"))
            for did in devices:
                if hook.level is not None:
                    plan.levels[did] = hook.level / 100.0
                if hook.off:
                    plan.states[did] = "dark"
                if hook.fps is not None:
                    plan.caps[did] = int(hook.fps)
    plan.motion = motion_targets(mode)
    return plan


def motion_targets(mode: HouseMode) -> dict:
    """virtual -> resting speed (0..1) for the virtuals the conductor
    tracks NOW (the scene showing). Later hooks win."""
    try:
        live_vids = list(deps.conductor().virtuals)
    except Exception:                                    # noqa: BLE001
        live_vids = []
    out: dict = {}
    for hook in mode.fixtures:
        if hook.motion is None:
            continue
        for vid in _virtuals_for(hook.target.model_dump(), live_vids):
            out[vid] = float(hook.motion)
    return out


# ── scenes and colours ─────────────────────────────────────────────────────

def _eligible_scenes(mode: HouseMode) -> list[tuple[Any, float]]:
    from spectra.services import mode_availability, scene_store
    from spectra.services.room_controls import load_room_controls
    room_mode = load_room_controls().display_mode
    out = []
    for pick in mode.scenes:
        if pick.weight <= 0:
            continue
        scene = scene_store.get_by_id(pick.scene_id)
        if scene is None or getattr(scene, "disabled", False):
            continue
        if not mode_availability.available_in_room_mode(
                getattr(scene, "display_availability", "default"), room_mode):
            continue
        out.append((scene, pick.weight))
    return out


def _eligible_cards(mode: HouseMode) -> list[tuple[Any, float]]:
    from spectra.services import color_sets
    out = []
    for pick in mode.color_sets:
        if pick.weight <= 0:
            continue
        card = color_sets.get_by_id(pick.card_id)
        if card is None or getattr(card, "disabled", False):
            continue
        out.append((card, pick.weight))
    return out


def _draw(items: list[tuple[Any, float]], exclude_id: Optional[str] = None):
    pool = [(x, w) for x, w in items if getattr(x, "id", None) != exclude_id] \
        if len(items) > 1 else list(items)
    if not pool:
        return None
    return _rng.choices([x for x, _ in pool], weights=[w for _, w in pool], k=1)[0]


def _current_scene_id() -> Optional[str]:
    try:
        scene = deps.conductor().scene
        return scene.id if scene is not None else None
    except Exception:                                    # noqa: BLE001
        return None


async def _apply_scene_and_colour(mode: HouseMode, glide_s: float, *,
                                  refire: bool, prefer_remembered: bool) -> dict:
    """Land the mode's scene and colour set. Returns what it did."""
    from spectra.services import force_color
    from spectra.services.room_controls import load_room_controls
    controls = load_room_controls()
    st = house_store.state()
    out: dict = {"problems": []}
    scenes = _eligible_scenes(mode)
    cards = _eligible_cards(mode)
    if mode.scenes and not scenes:
        out["problems"].append("none of the mode's scenes can fire "
                               "(missing, disabled, or not available in this display mode)")
    if mode.color_sets and not cards:
        out["problems"].append("none of the mode's colour sets exist or are enabled")
    pinned_scene = bool(controls.force_scene_enabled and controls.force_scene_scene_id)
    pinned_colour = force_color.active(controls)
    current = _current_scene_id()
    scene_ids = {s.id for s, _ in scenes}

    card = None
    if cards:
        active_id = deps.active_set_id()
        pool_ids = _expanded_set_ids(mode)
        if active_id is not None and active_id in pool_ids and not refire:
            card = None             # the room already wears one of the mode's sets
        else:
            remembered = next((c for c, _ in cards if c.id == st.color_card_id), None) \
                if prefer_remembered else None
            card = remembered or _draw(cards)

    scene = None
    if scenes and not pinned_scene:
        if current in scene_ids and not refire:
            scene = None            # keep it — a pure glide between modes
        else:
            remembered = next((s for s, _ in scenes if s.id == st.scene_id), None) \
                if prefer_remembered else None
            scene = remembered or _draw(scenes, exclude_id=None)
    elif scenes and pinned_scene:
        out["problems"].append("Force Scene is pinned — the mode's scenes wait")
    if pinned_colour and cards:
        out["problems"].append("Force Colour is pinned — the mode's colours wait")
        card = None

    glide_ms = int(glide_s * 1000)
    if scene is not None:
        res = await deps.fire_scene(
            scene.id, color_set_id=(card.id if card is not None else None),
            intensity=mode.flow.intensity,
            dwell_tolerance_s=HOUSE_DWELL_TOLERANCE_S,
            transition_ms=glide_ms, origin="house")
        skipped = (res or {}).get("skipped")
        if skipped:
            out["problems"].append(f"scene {scene.name!r} did not fire ({skipped})")
        else:
            out["scene_fired"] = scene.name
            st.scene_id = scene.id
            if card is not None:
                out["colour_set"] = card.name
                st.color_card_id = card.id
            house_store.save_state()
            return out
    if card is not None:
        from spectra.services import color_set_groups
        try:
            resolved = color_set_groups.resolve_ref(card.id)
        except ValueError as exc:
            out["problems"].append(str(exc))
            return out
        await deps.apply_set(resolved, glide_ms)
        out["colour_set"] = card.name
        st.color_card_id = card.id
        house_store.save_state()
    if current is not None and current in scene_ids:
        out["scene_kept"] = current
    return out


async def _flow_scene(mode: HouseMode) -> dict:
    """The flow clock: a different scene from the pool (a one-scene pool
    never changes)."""
    from spectra.services.room_controls import load_room_controls
    controls = load_room_controls()
    if controls.force_scene_enabled and controls.force_scene_scene_id:
        return {}
    scenes = _eligible_scenes(mode)
    current = _current_scene_id()
    candidates = [(s, w) for s, w in scenes if s.id != current]
    if not candidates:
        return {}
    scene = _draw(candidates)
    res = await deps.fire_scene(
        scene.id, color_set_id=None, intensity=mode.flow.intensity,
        dwell_tolerance_s=HOUSE_DWELL_TOLERANCE_S,
        transition_ms=int(mode.transitions.clock_glide_s * 1000), origin="house")
    if (res or {}).get("skipped"):
        return {"problems": [f"scene {scene.name!r} did not fire ({res['skipped']})"]}
    st = house_store.state()
    st.scene_id = scene.id
    house_store.save_state()
    return {"scene_fired": scene.name}


# ── motion ─────────────────────────────────────────────────────────────────

def _rebaseline_key():
    """Identity of the conductor's current re-baseline: a new scene fire
    replaces its `virtuals` dict wholesale (DriftConductor.on_scene_fire)."""
    try:
        c = deps.conductor()
        return (id(c.virtuals), c.scene.id if c.scene is not None else None)
    except Exception:                                    # noqa: BLE001
        return None


async def _apply_motion(mode: HouseMode, glide_s: float) -> None:
    """Write each hooked virtual's motion param to its resting speed (a
    position in the param's registry range) as a glide, and carry it into
    the conductor's baseline so drift and the param watchdog agree."""
    from fx import device_model
    key = _rebaseline_key()
    if key != _rt.motion_key:
        _rt.motion_authored = {}
        _rt.motion_applied = {}
    c = deps.conductor()
    changes: dict = {}
    glide_ms = max(1, int(glide_s * 1000))
    for vid, motion in sorted(motion_targets(mode).items()):
        vstate = c.virtuals.get(vid)
        if vstate is None:
            continue
        param = device_model.motion_param_for(vstate.effect_type)
        if not param:
            continue
        meta = device_model.get_param_meta(vstate.effect_type, param) or {}
        lo, hi = meta.get("min"), meta.get("max")
        if lo is None or hi is None:
            continue
        target = float(lo) + float(motion) * (float(hi) - float(lo))
        authored = vstate.param_baseline.get(param, meta.get("default"))
        _rt.motion_authored.setdefault((vid, param), authored)
        if _rt.motion_applied.get((vid, param)) == target:
            continue
        await c.executor.glide(vid, vstate.effect_type, {param: target}, glide_ms)
        changes[(vid, param)] = target
        _rt.motion_applied[(vid, param)] = target
    if changes:
        c.on_surge(changes)
    _rt.motion_key = key


async def _restore_motion(fade_s: float) -> None:
    if not _rt.motion_applied:
        return
    if _rebaseline_key() != _rt.motion_key:
        # A newer scene fire already authored its own params.
        _rt.motion_applied = {}
        _rt.motion_authored = {}
        return
    c = deps.conductor()
    changes = {}
    glide_ms = max(1, int(fade_s * 1000))
    for (vid, param), _value in sorted(_rt.motion_applied.items()):
        vstate = c.virtuals.get(vid)
        authored = _rt.motion_authored.get((vid, param))
        if vstate is None or authored is None:
            continue
        await c.executor.glide(vid, vstate.effect_type, {param: authored}, glide_ms)
        changes[(vid, param)] = authored
    if changes:
        c.on_surge(changes)
    _rt.motion_applied = {}


# ── status ─────────────────────────────────────────────────────────────────

def status_dict() -> dict:
    """The `lighting` key on GET /api/engine/status and GET /api/house/mode
    — what Home Assistant reads back."""
    st = house_store.state()
    mode = current_mode()
    mapped = (house_store.mode_for_ha(st.ha_value) if st.ha_value else None)
    out: dict = {
        "mode": ({"id": mode.id, "name": mode.name} if mode is not None else None),
        "source": st.source or None,
        "since_ms": st.since_ms,
        "manual": st.manual,
        "ha_value": st.ha_value,
        "ha_value_ms": st.ha_value_ms,
        "ha_mapped_mode": mapped.name if mapped is not None else None,
        "active": _rt.phase in (PHASE_RESTING, PHASE_MUSIC),
        "phase": _rt.phase,
        "reason": _rt.reason,
        "problems": list(_rt.last_problems),
        "recent": list(reversed(_rt.recent[-5:])),
    }
    if st.manual and st.ha_value:
        out["manual_until"] = (f"Home Assistant's value changes from {st.ha_value!r}")
    if mode is not None:
        playing = _rt.playing
        returns_in = None
        if (_rt.phase == PHASE_MUSIC and playing is False
                and _rt.quiet_since is not None):
            returns_in = max(0.0, mode.transitions.music_debounce_s
                             - (deps.clock() - _rt.quiet_since))
        out["music"] = {"playing": playing, "policy": mode.music,
                        "hue": mode.music_hue,
                        "returns_in_s": round(returns_in, 1) if returns_in is not None else None}
        nxt = None
        if (_rt.phase == PHASE_RESTING and mode.flow.scene_every_min > 0
                and _rt.last_scene_at is not None):
            nxt = max(0.0, mode.flow.scene_every_min * 60.0
                      - (deps.clock() - _rt.last_scene_at))
        out["next_scene_in_s"] = round(nxt, 1) if nxt is not None else None
    try:
        c = deps.conductor()
        if c.scene is not None:
            out["scene"] = {"id": c.scene.id, "name": c.scene.name}
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from fx import device_rate
        from spectra.services import show_output
        base = show_output.base_snapshot()
        out["fixtures"] = {
            "levels": {show_output.device_label(d): round(v * 100, 1)
                       for d, v in base["levels"].items()},
            "off": [show_output.device_label(d) for d in base["states"]],
            "caps": {show_output.device_label(d): v
                     for d, v in device_rate.caps().items()},
        }
    except Exception:                                    # noqa: BLE001
        pass
    if _rt.motion_applied:
        out["motion"] = [{"virtual": v, "param": p, "value": round(val, 3)}
                         for (v, p), val in sorted(_rt.motion_applied.items())]
    try:
        d = hue_directive()
        out["hue"] = ({"looks": [{"area": a, "look": k, "mirek": m, "color": col,
                                  "brightness": b} for (a, k, m, col, b) in d.looks]}
                      if d is not None else None)
    except Exception:                                    # noqa: BLE001
        out["hue"] = None
    return out


def status() -> dict:
    return status_dict()
