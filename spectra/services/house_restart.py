"""HOUSE LIGHTING phase 2 — A SPECTRA RESTART KEEPS THE LAST PICTURE.

Before this, a deploy blinked the house. Three separate blinks, each with its
own cause and its own fix here:

  1. THE WLEDs LET GO. Stopping the stack sent every WLED {"live": false}, so
     for the 5-40 s a restart takes they showed their underlying preset.
     Now a planned stop while a mode drives the room (`hold_on_shutdown`)
     tears down with `live.deactivate(hold_last_frame=True)` — no release,
     and each fixture keeps its last frame for its own realtime timeout
     (crystal / TV / porch 50 s; the sconces' 2.5 s is a WLED setting —
     scripts/set_wled_realtime_timeout.py raises it).
  2. THE FIRST FRAMES WERE AT FULL BRIGHTNESS. The resting layer's levels,
     its "off" fixtures, its frame-rate caps and the withheld (lent / off)
     fixtures are in-memory, re-pushed by the house supervisor only after
     the stack is up — so the first second of the new process streamed the
     crystal at 100% over a 3% mode. `maybe_persist` keeps a snapshot of
     exactly what is pushed (house_restart.json, written only when it
     changes) and `prepare_for_resume` re-installs it into the output layer
     BEFORE `handover.resume_own_room()` brings the stack up, so the first
     frame already carries it. The house supervisor's first pass then
     replaces it wholesale with the live answer.
  3. THE HUE BULBS STREAMED THE SHOW. Fresh HueDevice objects come up
     unfrozen and start an entertainment session before the Hue Hold gate
     re-freezes them. The areas held at the last snapshot are named to
     fx/hue_freeze.py and come up frozen — no session, the held look stays.
     `after_resume` must not undo that while the hold is still landing
     (2026-10-07: it read only what had LANDED, unfroze both areas, and the
     dining area's stream start overtook the hold's freeze) — so an area
     the gate intends to hold is kept frozen and watched.
     (Phase 4: an ordinary TAKE does the same — handover.SpectraSide.
     activate names house.take_frozen_areas(), and `after_take` is this
     module's `after_resume` once the gate's post-commit transition ends.)

ONLY WHEN IT WILL APPLY. `prepare_for_resume` does nothing unless a mode is
set, the ownership record says SPECTRA (resume will bring the stack up) and
a snapshot exists. With no mode set every path here is a no-op — the
shipped state. A crash (no planned stop) still benefits from 2 and 3 when
the snapshot was current; 1 needs the planned stop.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from spectra.models.house_mode import now_ms

logger = logging.getLogger(__name__)

#: A snapshot older than this is not re-installed (a stale picture landed on
#: the first frame is worse than none: the supervisor fixes it either way).
MAX_AGE_MS = 24 * 3600 * 1000

_last_written: Optional[dict] = None


def reset() -> None:
    global _last_written
    _last_written = None


def _path():
    from spectra import config as scfg
    return scfg.HOUSE_RESTART_FILE


def _hue_frozen_now() -> list[str]:
    try:
        from spectra.services.live_host import live
        host = live.host
        if host is None:
            return []
        return sorted(str(d) for d in host.devices
                      if bool(getattr(host.devices.get(d), "frozen", False)))
    except Exception:                                    # noqa: BLE001
        return []


def snapshot() -> dict:
    """What the house layer has on the fixtures right now."""
    from fx import device_output, device_rate
    from spectra.services import house_store, show_output
    from spectra.services import house
    base = show_output.base_snapshot()
    return {"mode_id": house_store.state().mode_id,
            "levels": base["levels"], "states": base["states"],
            "caps": device_rate.caps(),
            "withheld": device_output.withheld(),
            "mode_off": house.switched_off_by_mode(),
            "hue_frozen": _hue_frozen_now()}


def _write(data: dict) -> None:
    path = str(_path())
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".house_restart", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load() -> Optional[dict]:
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else None
    except FileNotFoundError:
        return None
    except Exception:                                    # noqa: BLE001
        logger.exception("house restart: unreadable snapshot")
        return None


def maybe_persist(force: bool = False) -> bool:
    """Write the snapshot when it changed (or `force`). Only while SPECTRA's
    stack is up — a torn-down stack has nothing on the fixtures to keep.
    Returns True when it wrote."""
    global _last_written
    from spectra.services.live_host import live
    if live.host is None and not force:
        return False
    snap = snapshot()
    if not force and snap == _last_written:
        return False
    if (not force and snap["mode_id"] is None
            and (_last_written is None or _last_written.get("mode_id") is None)):
        # No mode, and nothing of a mode's to overwrite: inert, no file.
        return False
    _write({**snap, "at_ms": now_ms()})
    _last_written = snap
    return True


def hold_on_shutdown() -> bool:
    """Should a planned stop keep the last picture? Only while a mode drives
    the room — the house is then the room's resting light, and a restart
    must not blink it. Every other stop releases exactly as before."""
    try:
        from spectra.services import house
        return house.layer_active()
    except Exception:                                    # noqa: BLE001
        return False


def prepare_for_resume() -> dict:
    """Re-install the last snapshot into the output layer, the rate caps and
    the Hue start-frozen list, BEFORE the stack comes up. Never raises.
    Returns what it did (for the startup log)."""
    try:
        from fx import device_output, device_rate, hue_freeze, light_ownership
        from spectra.services import house_store, show_output
        st = house_store.state()
        if st.mode_id is None:
            return {"installed": False, "why": "no house mode is set"}
        if light_ownership.load().owner != light_ownership.SPECTRA:
            return {"installed": False, "why": "SPECTRA does not own the room"}
        snap = load()
        if not snap:
            return {"installed": False, "why": "no snapshot"}
        if snap.get("mode_id") != st.mode_id:
            return {"installed": False, "why": "the snapshot is of another mode"}
        if now_ms() - int(snap.get("at_ms") or 0) > MAX_AGE_MS:
            return {"installed": False, "why": "the snapshot is stale"}
        levels = {str(k): float(v) for k, v in (snap.get("levels") or {}).items()}
        states = {str(k): str(v) for k, v in (snap.get("states") or {}).items()}
        show_output.set_base(levels, states, fade_s=0.0)
        device_rate.set_caps(snap.get("caps") or {})
        device_output.set_withheld(snap.get("withheld") or {})
        hue_freeze.set_pending(snap.get("hue_frozen") or [])
        from spectra.services import house
        house.preinstall_off(snap.get("mode_off") or [])
        out = {"installed": True, "levels": len(levels), "off": len(states),
               "caps": len(snap.get("caps") or {}),
               "withheld": sorted((snap.get("withheld") or {}).keys()),
               "hue_frozen": snap.get("hue_frozen") or []}
        logger.warning("house restart: re-installed the last picture before "
                       "the stack comes up: %s", out)
        return out
    except Exception:                                    # noqa: BLE001
        logger.exception("house restart: could not re-install the snapshot")
        return {"installed": False, "why": "error"}


def _looks_hold(looks, device_id: str) -> bool:
    areas = {lk[0] for lk in looks if lk[1] in ("hold", "off")}
    return "*" in areas or device_id in areas


def _gate_holds(device_id: str) -> bool:
    """Does the Hue Hold gate hold this Hue device right now (what LANDED)?"""
    from spectra.services import ambient_music_gate as gate
    looks = gate._held_looks
    if looks is not None:
        return _looks_hold(looks, device_id)
    if gate._held:
        return device_id in gate._held_resolved_groups
    return False


def _target_holds(target: tuple, device_id: str) -> bool:
    """Does a gate target (desired, colour, group ids[, looks]) hold this
    device? Empty group ids = every Hue area (the gate's own default)."""
    desired, _color, group_ids, looks = (*target, None)[:4] if len(target) == 3 else target
    if looks is not None:
        return _looks_hold(looks, device_id)
    if not desired:
        return False
    return not group_ids or device_id in group_ids


def _gate_intends_hold(device_id: str) -> bool:
    """Is the Hue Hold gate HOLDING THIS AREA, or on its way to? 2026-10-07:
    the startup reconcile can return before its hold lands (a transition a
    bridge broadcast already started, or a stack still assembling), and
    reading only what LANDED then unfroze both areas a moment before the
    hold re-froze them — the dining area's stream start overtook the
    freeze and it followed the show under "held". So: an ON transition in
    flight, a house mode (live or pending) holding the area, or the room
    toggle that will hold it all count as holding. Never raises (an
    unreadable answer keeps the area frozen — the hold's side)."""
    try:
        from spectra.services import ambient_music_gate as gate
        if _gate_holds(device_id):
            return True
        tr = gate._transition
        if tr is not None and tr.in_flight:
            return _target_holds(tr.target, device_id)
        directive = gate._house_directive() or gate._house_pending()
        if directive is not None:
            return _looks_hold(directive.looks, device_id)
        from spectra.services.room_controls import load_room_controls
        controls = load_room_controls()
        try:
            from spectra.services.engine import bridge
            playing = bridge.is_playing()
        except Exception:                                # noqa: BLE001
            playing = None
        desired = gate._desired_hold(controls.ambient_enabled,
                                     controls.ambient_on_music_pause,
                                     playing, gate._held)
        return _target_holds(
            (desired, None, frozenset(controls.ambient_hue_group_ids), None),
            device_id)
    except Exception:                                    # noqa: BLE001
        logger.exception("house restart: could not read the Hue Hold's intent "
                         "for %s — leaving it frozen", device_id)
        return True


#: After a restart, an area kept frozen because the Hue Hold was still on
#: its way is re-checked until the hold lands (or the intent goes away).
INTENT_WATCH_S = 90.0
INTENT_POLL_S = 0.5
_intent_watch: Optional["object"] = None


async def _watch_intended(device_ids: list[str], *, sleep=None,
                          wait_s: float = INTENT_WATCH_S) -> list[str]:
    """Follow-up for areas after_resume kept frozen on the hold's INTENT
    alone: once the hold has landed on an area it is the gate's again;
    if the intent goes away without landing (the hold never came), the
    area is unfrozen so it streams. If the intent is STILL there when
    wait_s runs out, the area is left frozen — that is what the hold
    wants, and the gate's own later transitions own it from there — and
    it is named in a log so a stuck reconcile is not silently invisible.
    Returns the areas it unfroze. Never raises."""
    import asyncio
    sleep = sleep or asyncio.sleep
    unfrozen: list[str] = []
    pending = set(device_ids)
    waited = 0.0
    try:
        from spectra.services import ambient_music_gate as gate
        from spectra.services.live_host import live
        while pending and waited < wait_s:
            await sleep(INTENT_POLL_S)
            waited += INTENT_POLL_S
            if gate.transition_in_flight():
                continue
            host = live.host
            for did in sorted(pending):
                dev = host.devices.get(did) if host is not None else None
                if dev is None or not getattr(dev, "frozen", False):
                    pending.discard(did)
                    continue
                if _gate_holds(did):
                    pending.discard(did)
                    continue
                if _gate_intends_hold(did):
                    continue
                await dev.set_frozen(False)
                unfrozen.append(did)
                pending.discard(did)
        if unfrozen:
            logger.warning("house restart: %s was kept frozen for a Hue Hold "
                           "that never landed — streaming again", unfrozen)
        if pending:
            logger.warning("house restart: %s still frozen after %ss — the "
                           "Hue Hold still intends to hold them but has not "
                           "landed; left frozen for the gate to resolve",
                           sorted(pending), wait_s)
    except Exception:                                    # noqa: BLE001
        logger.exception("house restart: intent watch failed")
    return unfrozen


async def after_resume() -> list[str]:
    """The stack is up. Any name not consumed by an activation is dropped
    (one-shot), and a Hue area that came up frozen but the gate neither
    holds nor INTENDS to hold now (the room moved on while SPECTRA was down
    — music playing with Hue joining the show) is unfrozen, so it streams
    again instead of sitting static. An area the hold is still on its way
    to is kept frozen (_gate_intends_hold) and watched until it lands.
    Returns the areas it unfroze. Never raises."""
    global _intent_watch
    unfrozen: list[str] = []
    kept: list[str] = []
    try:
        from fx import hue_freeze
        from spectra.services.live_host import live
        consumed = hue_freeze.take_consumed()
        hue_freeze.clear()
        host = live.host
        for did in sorted(consumed):
            dev = host.devices.get(did) if host is not None else None
            if dev is None or not getattr(dev, "frozen", False):
                continue
            if _gate_holds(did):
                continue
            if _gate_intends_hold(did):
                kept.append(did)
                continue
            await dev.set_frozen(False)
            unfrozen.append(did)
        if unfrozen:
            logger.warning("house restart: %s came up frozen but nothing "
                           "holds it now — streaming again", unfrozen)
        if kept:
            import asyncio
            logger.warning("house restart: %s came up frozen and the Hue Hold "
                           "is still landing on it — kept frozen", kept)
            _intent_watch = asyncio.create_task(
                _watch_intended(kept), name="house-restart-intent-watch")
    except Exception:                                    # noqa: BLE001
        logger.exception("house restart: after-resume Hue check failed")
    return unfrozen


#: How long after a take the Hue check waits for the gate's own post-commit
#: transition (a whole-room hold paces its writes 300 ms apart and confirms
#: each) before it reads what landed.
AFTER_TAKE_WAIT_S = 90.0
AFTER_TAKE_POLL_S = 0.5


async def after_take(*, sleep=None, wait_s: float = AFTER_TAKE_WAIT_S) -> list[str]:
    """after_resume, for an ordinary take: handover.SpectraSide.activate
    named the Hue areas the house mode was about to hold
    (house.take_frozen_areas) so they came up frozen. Once the Hue Hold
    gate's post-commit transition has finished, any of them it does NOT
    hold (the room moved on — music started with Hue joining the show, the
    mode was cleared) is unfrozen so it streams. Never raises."""
    import asyncio
    sleep = sleep or asyncio.sleep
    try:
        from spectra.services import ambient_music_gate as gate
        waited = 0.0
        await sleep(AFTER_TAKE_POLL_S)
        while gate.transition_in_flight() and waited < wait_s:
            await sleep(AFTER_TAKE_POLL_S)
            waited += AFTER_TAKE_POLL_S
    except Exception:                                    # noqa: BLE001
        logger.exception("house: after-take wait failed")
    return await after_resume()
