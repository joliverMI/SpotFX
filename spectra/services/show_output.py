"""THE LIGHT SHOW's device half — what "make the crystal dark", "hold the
sconces steady", "dim the strips to 30% for ten seconds" and "flash the
porch" MEAN, on top of the per-device output layer in fx/device_output.py
(read that module's docstring first: it is where a frame is actually
changed, and why there).

This module owns:

  * TARGETS — one fixture (a device id), one category (resolved through the
    shared category registry to its virtuals, then to the devices those
    virtuals' segments touch), or Everything. Resolved at the moment an
    action fires, so a regrouped category follows.
  * HOLDS — a fixture held Steady, Frozen or Dark. "Show" is not a hold: it
    is the absence of one, faded back to.
  * LEVELS — temporary multipliers that stack (they multiply), each ending
    after N seconds, at the next scene change, or when released.
  * THE GATE — the show acts only while SPECTRA owns the lights, its stack
    is up and its engine is live, and stands down while a preview, a camera
    run or a night run holds the room. It never takes or releases the room.
  * PERSISTENCE — holds and levels survive a restart (a Level whose end has
    passed is dropped) and are re-pushed when the live stack comes up; a
    release drops every one of them.

PUT BACK IS STRUCTURAL, not a snapshot: the show keeps rendering underneath
every hold, so ending one fades back into the live, in-step picture, and
there is no stored "before" to go stale.

THE BASE LAYER (HOUSE LIGHTING, spectra/services/house.py). A house mode
sets a resting level per fixture (and can switch one off) BELOW every Light
Show hold and level. It is pushed here, not written to fx/device_output.py
separately, because the output layer holds ONE target per device: two
writers would clobber each other. So a device's level is base × every show
Level, and its state is the show's hold if it has one, else the base state,
else Show. Letting go of a show hold (Show, Release, End show) fades back
to the BASE, not to an undimmed picture — "End show returns to the current
mode" (plan §3.3). The base is in-memory: the house layer re-pushes it on
every tick it is active and clears it the moment it stands aside.

THE VOICE OVERLAY (HOUSE LIGHTING phase 2, spectra/services/house_voice.py).
Serenity's listening / processing / responding colours sit ABOVE everything
else on the fixtures they light: a steady colour at the voice's own level.
Like a hold, it is a state on the output layer and the picture keeps
rendering underneath, so clearing it fades back to whatever the fixture
should show NOW — its show hold if the Light Show put one on it meanwhile,
else the house mode's base — never to a snapshot taken before the voice
started (Home Assistant's scene.create/restore race, retired). The base
layer and a show hold landing mid-utterance respect it: a base change moves
nothing on a voice-held fixture, and a show hold takes the fixture over
outright (the show wins; the voice simply ends there).

THE STEADY SCALE (fx/device_output.set_scale_provider). A steady colour
REPLACES the picture, so on its own it would ignore the room dimmer and a
running room effect. This module hands the output layer a callable that
answers "what gain is the room applying to this device right now":
`brightness_multiplier` (cached, refreshed by the supervisor) times the
mean room-effect gain over the virtuals feeding the device. The other
states need no help: Level and Dark multiply a frame that already carries
both.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable, Optional

from fx import device_output, light_ownership
from spectra.models.light_show import DeviceHold, LevelHold, now_ms
from spectra.services import show_store

logger = logging.getLogger(__name__)

SUPERVISOR_TICK_S = 0.25
#: Fade used when a hold is let go without one being named (End show).
DEFAULT_RELEASE_FADE_MS = 1500
MAX_FADE_MS = 60_000

_brightness_mult = 1.0
_device_virtuals: dict[str, list[str]] = {}
#: house lighting's resting layer — device id -> level (1.0 never stored)
_base_levels: dict[str, float] = {}
#: house lighting's resting layer — device id -> state (only "dark" today)
_base_states: dict[str, str] = {}
#: the voice overlay — device id -> (rgb colour, level 0..MAX_LEVEL)
_overlay: dict[str, tuple] = {}
_was_live = False
_task: Optional[asyncio.Task] = None


# ── the gate ───────────────────────────────────────────────────────────────

def ownership_refusal() -> Optional[str]:
    """Why the show may not touch the lights at all right now, or None."""
    try:
        owner = light_ownership.load().owner
    except Exception:                                    # noqa: BLE001
        return "the light-ownership record could not be read"
    if owner == light_ownership.RELEASED:
        return ("the room is released — SPECTRA is not driving the lights. "
                "The Light Show never takes the room; take it back first.")
    if owner != light_ownership.SPECTRA:
        return (f"SPECTRA does not own the lights right now (owner: {owner}). "
                f"The Light Show never takes the room.")
    from spectra.services.live_host import live
    if not live.active:
        return "SPECTRA's live light stack is not up."
    try:
        from spectra.services import engine
        if getattr(engine.executor, "mode", "recording") == "recording":
            return ("SPECTRA's engine is on paper (not live) — a quiet take "
                    "or a stack that has not gone live yet.")
    except Exception:                                    # noqa: BLE001
        return "SPECTRA's engine state could not be read"
    return None


def standdown_reason() -> Optional[str]:
    """Why the show is standing down right now (a preview, a camera run or a
    night run has the room), or None. A room effect the SHOW (or the Room
    Effects page) is running holds the room through the same preview hold
    but is a layer riding on top, not a preview — it does not count."""
    try:
        from spectra.services import preview_pause
        if preview_pause.active():
            return "a preview is holding the room"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from spectra.services import room_preview
        if room_preview.active():
            return "a colour preview is holding the room"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from spectra.services import flare_preview_hold, room_effects
        if flare_preview_hold.active() and not room_effects._state.running:
            return "a preview is holding the room"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from spectra.services import capture_runs
        run = capture_runs.current_run()
        if run is not None:
            return "a camera run is measuring the room"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from spectra.services import night_run
        cur = night_run.current
        if cur is not None and cur.state not in night_run.ENDED_STATES:
            return "a night run is in progress"
    except Exception:                                    # noqa: BLE001
        pass
    return None


def refusal() -> Optional[str]:
    return ownership_refusal() or standdown_reason()


def _colour_preview_alone() -> bool:
    """Is a colour-set preview (room_preview.py) the ONLY thing holding the
    room? Anything unreadable answers False — the old, suspended behaviour."""
    try:
        from spectra.services import room_preview
        if not room_preview.active():
            return False
        from spectra.services import flare_preview_hold, room_effects
        if flare_preview_hold.active() and not room_effects._state.running:
            return False
        from spectra.services import av_sync_pattern
        if av_sync_pattern.driver.active:
            return False
        from spectra.services import capture_runs
        if capture_runs.current_run() is not None:
            return False
        from spectra.services import night_run
        cur = night_run.current
        if cur is not None and cur.state not in night_run.ENDED_STATES:
            return False
    except Exception:                                    # noqa: BLE001
        return False
    return True


def suspension_reason() -> Optional[str]:
    """Why the per-device output layer must pass every frame through
    untouched right now, or None. Narrower than refusal() by exactly one
    case: a COLOUR-SET PREVIEW holding the room on its own.

    Suspension exists for things that must see raw frames — a camera run, a
    night run, the A/V-sync flash pattern, a scene/flare preview — and for a
    room that is not ours or an engine on paper. A colour preview is none of
    those: it is "these colours on the room as it is", so the house mode's
    resting levels, its switched-off and lent fixtures, and any Light Show
    hold stay in force. Suspending them under it took his Standard mode's
    crystal from 12% to full for the length of every preview (the Admiral,
    2026-10-07: "when i preview a color set, it pushes to 100% brightness").
    The colour preview still stands everything else down — refusal() and
    house.gate() are unchanged, so Light Show fires stay refused and the
    house writes nothing over it. Built FROM refusal(), never beside it, so
    there is still one gate deciding what holds the room."""
    reason = refusal()
    if reason is None:
        return None
    if ownership_refusal() is None and _colour_preview_alone():
        return None
    return reason


# ── targets ────────────────────────────────────────────────────────────────

def _host():
    from spectra.services.live_host import live
    return live.host


def _scope(host):
    """The fixtures a scoped take reaches (FxHost.scope_device_ids), or
    None for a whole-room take. The show never addresses a fixture the take
    was not handed — it would not be streamed, and offering it is a promise
    the room cannot keep."""
    fn = getattr(host, "scope_device_ids", None) if host is not None else None
    return fn() if fn is not None else None


def _virtual_devices(host, vid: str) -> list[str]:
    v = host.virtuals.get(vid) if host is not None else None
    if v is None:
        return []
    scope = _scope(host)
    out = []
    for seg in getattr(v, "_segments", None) or []:
        did = str(seg[0])
        if did.startswith("gap-") or did in out:
            continue
        if scope is not None and did not in scope:
            continue
        if did in host.devices:
            out.append(did)
    return out


def _real_devices(host) -> list[str]:
    if host is None:
        return []
    scope = _scope(host)
    return [d for d in host.devices if not str(d).startswith("gap-")
            and (scope is None or str(d) in scope)]


def resolve_target(target: dict) -> tuple[list[str], list[str]]:
    """(device_ids, problems). An unresolvable target returns no devices and
    a problem sentence — never a guess."""
    host = _host()
    if host is None:
        return [], ["the live stack is not up, so no fixture can be resolved"]
    kind = (target or {}).get("kind", "everything")
    tid = (target or {}).get("id")
    if kind == "everything":
        return _real_devices(host), []
    if kind == "fixture":
        if tid in host.devices:
            scope = _scope(host)
            if scope is not None and tid not in scope:
                return [], [f"fixture {tid!r} is outside the current take"]
            return [tid], []
        return [], [f"no fixture called {tid!r} is in the live stack"]
    if kind == "category":
        from fx import device_model
        vids = device_model.get_virtuals_for_category(tid or "")
        if not vids:
            return [], [f"no category called {tid!r} (or it has no virtuals)"]
        devices: list[str] = []
        for vid in vids:
            for d in _virtual_devices(host, vid):
                if d not in devices:
                    devices.append(d)
        if not devices:
            return [], [f"category {tid!r} reaches no live fixture"]
        return devices, []
    return [], [f"unknown target kind {kind!r}"]


def device_label(device_id: str) -> str:
    host = _host()
    dev = host.devices.get(device_id) if host is not None else None
    name = getattr(dev, "name", None) if dev is not None else None
    return str(name or device_id)


def held_by_ambient(device_id: str) -> bool:
    host = _host()
    dev = host.devices.get(device_id) if host is not None else None
    return bool(getattr(dev, "frozen", False)) if dev is not None else False


def list_targets() -> dict:
    """Every fixture and category the show can address, for the editor."""
    host = _host()
    fixtures = []
    for did in _real_devices(host):
        dev = host.devices.get(did)
        fixtures.append({"id": did, "name": device_label(did),
                         "type": getattr(dev, "type", None) or type(dev).__name__,
                         "held_by_ambient": held_by_ambient(did)})
    cats = []
    try:
        from fx import device_model
        for c in device_model.list_categories():
            name = c.get("name") if isinstance(c, dict) else None
            if name:
                devs, _ = resolve_target({"kind": "category", "id": name}) \
                    if host is not None else ([], [])
                cats.append({"name": name, "fixtures": devs})
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: could not list categories")
    return {"live": host is not None, "fixtures": fixtures, "categories": cats}


# ── the steady scale ───────────────────────────────────────────────────────

def _refresh_scale_inputs() -> None:
    global _brightness_mult, _device_virtuals
    try:
        from spectra.services import room_controls
        _brightness_mult = float(room_controls.load_room_controls().brightness_multiplier)
    except Exception:                                    # noqa: BLE001
        _brightness_mult = 1.0
    host = _host()
    mapping: dict[str, list[str]] = {}
    if host is not None:
        # The real fx `Virtuals` registry is iterable (ids) with `.get()` —
        # it has no `.items()`. A dict-shaped fake hid that once and the
        # supervisor crashed every tick on the live host (2026-10-04 proof).
        for vid in list(host.virtuals):
            v = host.virtuals.get(vid)
            if v is None or not getattr(v, "active", False):
                continue
            for did in _virtual_devices(host, vid):
                mapping.setdefault(did, []).append(vid)
    _device_virtuals = mapping


def steady_scale(device_id: str) -> float:
    """Room dimmer × mean room-effect gain over the device's virtuals.
    Runs on render threads: dict reads only."""
    gain = 1.0
    vids = _device_virtuals.get(device_id)
    if vids:
        try:
            from spectra.services import room_effects
            gains = [room_effects.gain_for(v) for v in vids]
            gain = sum(gains) / len(gains)
        except Exception:                                # noqa: BLE001
            gain = 1.0
    return _brightness_mult * gain


# ── holds ──────────────────────────────────────────────────────────────────

def _fade_s(ms) -> float:
    return max(0, min(MAX_FADE_MS, int(ms or 0))) / 1000.0


def _push_hold(h: DeviceHold) -> None:
    color = tuple(h.color) if h.color else None
    device_output.set_state(h.device_id, h.state, color=color,
                            fade_s=_fade_s(h.fade_ms))


def set_state(device_ids: Iterable[str], state: str, *,
              color: Optional[tuple] = None, fade_ms: int = 0,
              source: str = "") -> list[dict]:
    """Put each device in `state`. SHOW lets go of a hold (fading back)."""
    st = show_store.state()
    out = []
    for did in device_ids:
        note = "held by Hue Hold — the show cannot change it until Hue Hold lets go" \
            if held_by_ambient(did) else None
        if state == device_output.STATE_SHOW:
            had = st.holds.pop(did, None)
            _push_rest(did, fade_ms)
            out.append({"device": did, "name": device_label(did), "state": state,
                        "was": had.state if had else "show", "note": note})
            continue
        hold = DeviceHold(device_id=did, state=state,
                          color=list(color) if color is not None else None,
                          fade_ms=int(fade_ms or 0), source=source)
        st.holds[did] = hold
        if _overlay.pop(did, None) is not None:
            # The show takes the fixture over: the voice ends here, and its
            # level gives way to the show's own.
            device_output.set_level(did, _combined_level(did, st.levels),
                                    fade_s=_fade_s(fade_ms))
        _push_hold(hold)
        out.append({"device": did, "name": device_label(did), "state": state,
                    "note": note})
    _mark_started()
    show_store.save_state()
    return out


def _combined_level(device_id: str, levels: list[LevelHold]) -> float:
    ov = _overlay.get(device_id)
    if ov is not None:
        return max(0.0, min(device_output.MAX_LEVEL, float(ov[1])))
    v = _base_levels.get(device_id, 1.0)
    for lv in levels:
        if device_id in lv.device_ids:
            v *= lv.level
    return max(0.0, min(device_output.MAX_LEVEL, v))


def add_level(device_ids: list[str], level: float, *, fade_in_ms: int = 0,
              fade_out_ms: int = 0, until: str = "time",
              duration_s: Optional[float] = None, source: str = "") -> LevelHold:
    st = show_store.state()
    ends = None
    if until == "time":
        if not duration_s or duration_s <= 0:
            until = "released"
        else:
            ends = now_ms() + int(float(duration_s) * 1000)
    lv = LevelHold(device_ids=list(device_ids), level=float(level),
                   fade_in_ms=int(fade_in_ms or 0), fade_out_ms=int(fade_out_ms or 0),
                   until=until, ends_at_ms=ends, source=source)
    st.levels.append(lv)
    for did in lv.device_ids:
        device_output.set_level(did, _combined_level(did, st.levels),
                                fade_s=_fade_s(lv.fade_in_ms))
    _mark_started()
    show_store.save_state()
    return lv


def end_level(level_id: str, *, fade_ms: Optional[int] = None) -> bool:
    st = show_store.state()
    lv = next((x for x in st.levels if x.id == level_id), None)
    if lv is None:
        return False
    st.levels = [x for x in st.levels if x.id != level_id]
    fade = lv.fade_out_ms if fade_ms is None else fade_ms
    for did in lv.device_ids:
        device_output.set_level(did, _combined_level(did, st.levels),
                                fade_s=_fade_s(fade))
    show_store.save_state()
    return True


# ── the base layer (house lighting) ────────────────────────────────────────

def base_state(device_id: str) -> str:
    """What a device shows when the Light Show holds nothing on it."""
    return _base_states.get(device_id, device_output.STATE_SHOW)


def _push_rest(did: str, fade_ms) -> None:
    """Put a device in what it should show with NO show hold on it: the
    voice overlay if one is up, else the house base."""
    ov = _overlay.get(did)
    if ov is not None:
        device_output.set_state(did, device_output.STATE_STEADY, color=ov[0],
                                fade_s=_fade_s(fade_ms))
    else:
        device_output.set_state(did, base_state(did), fade_s=_fade_s(fade_ms))


# ── the voice overlay (house lighting phase 2) ─────────────────────────────

def overlay_snapshot() -> dict:
    return {d: {"color": list(c), "level": lv} for d, (c, lv) in _overlay.items()}


def overlay_set(device_ids: Iterable[str], color: tuple, level: float, *,
                fade_s: float = 0.0) -> list[str]:
    """Put the voice colour on these fixtures (a steady colour at `level`).
    Returns the devices it landed on. The caller (house_voice) has already
    skipped fixtures the Light Show holds."""
    color = tuple(float(max(0, min(255, c))) for c in color)
    level = max(0.0, min(device_output.MAX_LEVEL, float(level)))
    out = []
    for did in device_ids:
        _overlay[did] = (color, level)
        device_output.set_state(did, device_output.STATE_STEADY, color=color,
                                fade_s=max(0.0, float(fade_s)))
        device_output.set_level(did, level, fade_s=max(0.0, float(fade_s)))
        out.append(did)
    return out


def overlay_clear(device_ids: Optional[Iterable[str]] = None, *,
                  fade_s: float = 0.0) -> list[str]:
    """Take the voice colour off (every voice-held fixture when `device_ids`
    is None) and fade back to what the fixture should show NOW: its show
    hold if the Light Show put one on it, else the house base."""
    st = show_store.state()
    ids = list(_overlay) if device_ids is None else [d for d in device_ids
                                                     if d in _overlay]
    fade_ms = int(max(0.0, float(fade_s)) * 1000)
    for did in ids:
        _overlay.pop(did, None)
        if did in st.holds:
            _push_hold(st.holds[did].model_copy(update={"fade_ms": fade_ms}))
        else:
            device_output.set_state(did, base_state(did), fade_s=_fade_s(fade_ms))
        device_output.set_level(did, _combined_level(did, st.levels),
                                fade_s=_fade_s(fade_ms))
    return ids


def busy_reason(device_id: str) -> Optional[str]:
    """Why a momentary overlay (the voice) must leave this fixture alone, or
    None: the Light Show holds it, dims it with a Level, or is flashing it."""
    st = show_store.state()
    if device_id in st.holds:
        return "the Light Show holds it"
    if any(device_id in lv.device_ids for lv in st.levels):
        return "a Light Show Level is on it"
    tg = device_output.target(device_id)
    if tg is not None and tg.flash is not None and not tg.flash.done(device_output.now()):
        return "the Light Show is flashing it"
    return None


def base_snapshot() -> dict:
    return {"levels": dict(_base_levels), "states": dict(_base_states)}


def set_base(levels: dict[str, float], states: dict[str, str], *,
             fade_s: float = 0.0) -> list[str]:
    """Replace house lighting's resting layer WHOLESALE and fade every
    device whose base changed to its new look. A device the Light Show
    holds keeps its hold — its base state applies when the hold lets go —
    but its level still moves, because a show Level multiplies the base.
    Returns the devices that changed. Never raises for an unknown device:
    the output layer is keyed by id and a stale one is simply never read."""
    global _base_levels, _base_states
    new_levels = {str(d): max(0.0, min(device_output.MAX_LEVEL, float(v)))
                  for d, v in (levels or {}).items() if float(v) != 1.0}
    new_states = {str(d): s for d, s in (states or {}).items()
                  if s in (device_output.STATE_DARK,)}
    old_levels, old_states = _base_levels, _base_states
    _base_levels, _base_states = new_levels, new_states
    fade = max(0.0, min(MAX_FADE_MS / 1000.0, float(fade_s or 0.0)))
    st = show_store.state()
    changed = []
    for did in sorted(set(old_levels) | set(old_states) | set(new_levels) | set(new_states)):
        moved = False
        if old_levels.get(did, 1.0) != new_levels.get(did, 1.0):
            device_output.set_level(did, _combined_level(did, st.levels), fade_s=fade)
            moved = True
        if old_states.get(did) != new_states.get(did):
            moved = True
            if did not in st.holds and did not in _overlay:
                device_output.set_state(did, base_state(did), fade_s=fade)
        if moved:
            changed.append(did)
    return changed


def flash(device_ids: Iterable[str], *, color=(255, 255, 255), amount=1.0,
          attack_ms=50, hold_ms=100, decay_ms=400) -> list[str]:
    ids = list(device_ids)
    for did in ids:
        device_output.flash(did, color=tuple(color), amount=amount,
                            attack_s=attack_ms / 1000.0, hold_s=hold_ms / 1000.0,
                            decay_s=decay_ms / 1000.0)
    return ids


def release_device(device_id: str, fade_ms: int = DEFAULT_RELEASE_FADE_MS) -> dict:
    """Let one fixture go: its hold and every level touching it."""
    st = show_store.state()
    had = st.holds.pop(device_id, None)
    touched = [lv for lv in st.levels if device_id in lv.device_ids]
    for lv in touched:
        lv.device_ids = [d for d in lv.device_ids if d != device_id]
    st.levels = [lv for lv in st.levels if lv.device_ids]
    _push_rest(device_id, fade_ms)
    device_output.set_level(device_id, _combined_level(device_id, st.levels),
                            fade_s=_fade_s(fade_ms))
    show_store.save_state()
    return {"device": device_id, "released": bool(had or touched)}


def release_all(fade_ms: int = DEFAULT_RELEASE_FADE_MS) -> list[str]:
    """End show's device half: every hold and level faded back to Show."""
    st = show_store.state()
    devices = set(st.holds) | {d for lv in st.levels for d in lv.device_ids}
    based = set(_base_levels) | set(_base_states)
    devices |= set(device_output.snapshot()) - based - set(_overlay)
    st.holds.clear()
    st.levels.clear()
    for did in devices:
        # Back to the house mode's resting look, not to an undimmed picture.
        _push_rest(did, fade_ms)
        device_output.set_level(did, _combined_level(did, []),
                                fade_s=_fade_s(fade_ms))
    show_store.save_state()
    # Pulse modulations and flare switches (show_mods.py) end with them.
    from spectra.services import show_mods
    show_mods.release_all(fade_ms)
    return sorted(devices)


def on_release() -> None:
    """The room is being released: drop everything, abruptly, before the
    release fade, so the room lets go of its TRUE state. The house layer's
    base goes too — it is re-pushed when the house is active again."""
    device_output.clear_all()
    device_output.clear_withheld()
    _base_levels.clear()
    _base_states.clear()
    _overlay.clear()
    try:
        from spectra.services import show_mods
        show_mods.on_release()
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: dropping Pulse/flare holds on release failed")
    try:
        from spectra.services import show_arms
        show_arms.on_release()
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: arm expiry on release failed")
    st = show_store.state()
    if st.holds or st.levels:
        st.holds.clear()
        st.levels.clear()
        show_store.save_state()


def on_scene_change() -> list[str]:
    """A real scene change: end every Level authored to last until one."""
    st = show_store.state()
    ending = [lv.id for lv in st.levels if lv.until == "scene_change"]
    for lid in ending:
        end_level(lid)
    from spectra.services import show_mods
    return ending + show_mods.on_scene_change()


def _mark_started() -> None:
    st = show_store.state()
    if st.started_ms is None:
        st.started_ms = now_ms()


def repush() -> dict:
    """Re-install every saved hold and live level into the output layer (the
    live stack just came up — a restart or a take-back). A Level whose end
    has passed is dropped, never resurrected."""
    st = show_store.state()
    t = now_ms()
    dropped = [lv.id for lv in st.levels
               if lv.until == "time" and lv.ends_at_ms is not None and lv.ends_at_ms <= t]
    expired = [lv for lv in st.levels if lv.id in dropped]
    st.levels = [lv for lv in st.levels if lv.id not in dropped]
    for did, state in _base_states.items():
        if did not in st.holds and did not in _overlay:
            device_output.set_state(did, state)
    for h in st.holds.values():
        _push_hold(h.model_copy(update={"fade_ms": 0}))
    for did, (color, _lv) in _overlay.items():
        if did not in st.holds:
            device_output.set_state(did, device_output.STATE_STEADY, color=color)
    devices = ({d for lv in st.levels for d in lv.device_ids} | set(_base_levels)
               | set(_overlay))
    # A dropped level's devices are reset too: within one process (a stack
    # that came back without a restart) the layer may still carry it.
    devices |= {d for lv in expired for d in lv.device_ids}
    for did in devices:
        device_output.set_level(did, _combined_level(did, st.levels))
    if dropped:
        show_store.save_state()
    from spectra.services import show_mods
    mods = show_mods.repush()
    return {"holds": sorted(st.holds), "levels": len(st.levels), "dropped": dropped,
            **mods}


# ── the supervisor ─────────────────────────────────────────────────────────

_refresh_failed = False


def _safe_refresh() -> None:
    """The steady-scale inputs are a nicety; a failure there must never stop
    a timed Level ending or a re-push landing (it did, live, 2026-10-04: one
    AttributeError every 250 ms and a 20% Level that never let go). Logged
    once per failure streak, not four times a second."""
    global _refresh_failed
    try:
        _refresh_scale_inputs()
        _refresh_failed = False
    except Exception:                                    # noqa: BLE001
        if not _refresh_failed:
            logger.exception("light show: steady-scale refresh failed")
        _refresh_failed = True


def tick() -> None:
    """One supervisor pass (also callable directly from tests)."""
    global _was_live
    from spectra.services.live_host import live
    is_live = live.active
    # Suspend FIRST, so a re-push never gets a frame out before the stand-
    # down applies (a night run's quiet take brings the stack up with the
    # engine on paper — a held Steady must not light a capture's dark step).
    # `suspension_reason()` covers an engine on paper and every stand-down
    # except a colour preview on its own (see its docstring).
    device_output.suspend(suspension_reason() is not None)
    from fx import pulse_modulation
    pulse_modulation.suspend(device_output.suspended())
    try:
        from spectra.services import show_arms
        show_arms.tick()
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: arm expiry pass failed")
    if is_live and not _was_live:
        _safe_refresh()
        try:
            repush()
        except Exception:                                # noqa: BLE001
            logger.exception("light show: re-push after the stack came up failed")
    elif not is_live and _was_live:
        device_output.clear_all()
    _was_live = is_live
    if not is_live:
        return
    _safe_refresh()
    st = show_store.state()
    t = now_ms()
    for lv in list(st.levels):
        if lv.until == "time" and lv.ends_at_ms is not None and lv.ends_at_ms <= t:
            end_level(lv.id)
    device_output.prune()
    try:
        from spectra.services import show_mods
        show_mods.tick()
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: Pulse/flare hold pass failed")


async def run_supervised() -> None:
    device_output.set_scale_provider(steady_scale)
    while True:
        try:
            tick()
        except Exception:                                # noqa: BLE001
            logger.exception("light show supervisor tick failed")
        await asyncio.sleep(SUPERVISOR_TICK_S)


def reset() -> None:
    """Tests: forget the module's own memory."""
    global _was_live, _brightness_mult, _device_virtuals
    _was_live = False
    _brightness_mult = 1.0
    _device_virtuals = {}
    _base_levels.clear()
    _base_states.clear()
    _overlay.clear()
    device_output.clear_all()
    device_output.clear_withheld()
    device_output.suspend(False)
    from spectra.services import show_mods
    show_mods.reset()


device_output.set_scale_provider(steady_scale)


def status() -> dict:
    st = show_store.state()
    t = now_ms()
    holds = [{"device": d, "name": device_label(d), "state": h.state,
              "color": h.color, "since_ms": h.since_ms, "source": h.source,
              "held_by_ambient": held_by_ambient(d)}
             for d, h in st.holds.items()]
    levels = [{"id": lv.id, "devices": lv.device_ids,
               "names": [device_label(d) for d in lv.device_ids],
               "level": lv.level, "until": lv.until,
               "remaining_s": (round((lv.ends_at_ms - t) / 1000.0, 1)
                               if lv.ends_at_ms is not None else None),
               "source": lv.source}
              for lv in st.levels]
    from spectra.services import show_mods
    return {"holds": holds, "levels": levels, **show_mods.status(),
            "suspended": device_output.suspended(),
            "standdown": standdown_reason(),
            "refusal": ownership_refusal(),
            "base": {"levels": dict(_base_levels), "states": dict(_base_states)},
            "voice": overlay_snapshot(),
            "withheld": device_output.withheld(),
            "output": device_output.snapshot()}
