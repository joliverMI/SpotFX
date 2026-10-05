"""HOUSE LIGHTING phase 2 — SERENITY'S VOICE COLOURS, rendered by Spectra
(River's R8; the four Home Assistant automations serenity_listening /
_processing / _responding / _complete_return_state, read 2026-10-05).

Home Assistant used to snapshot the crystal and both kitchen sconces
(`scene.create`), paint them solid blue / green / purple, and put the
snapshot back on idle — racing whatever Spectra was streaming to the same
fixtures. Now it POSTs the assistant's state and Spectra paints it:

  listening / processing / responding   a steady colour at the voice's own
                                        level on each voice fixture (the
                                        library's `voice_looks`, defaulting
                                        to HA's exact colours at 100%)
  idle                                  fades back to what each fixture
                                        should show NOW — its Light Show hold
                                        if one landed meanwhile, else the
                                        mode's resting look

THE EXACT LOOK COMES BACK BECAUSE NOTHING WAS TAKEN AWAY. The overlay is a
state on the per-device output layer (show_output's voice overlay); the
picture keeps rendering underneath, so "restore" is letting go, never a
replayed snapshot that may have gone stale while the assistant spoke.

SKIPPED IF BUSY, AND THE VOICE PIPELINE NEVER WAITS. `set_voice` is a plain
function — no network, no lock, no await — so the route answers in
microseconds whatever the room is doing. It paints nothing (and says why)
when no mode drives the room, the room is on standby for a preview / camera
run / night run, or a fixture is held by the Light Show, lent, switched off
or outside the take. Home Assistant should still call it with a short
timeout and never block on it.

A STUCK VOICE EXPIRES. A "listening" with no "idle" after it (HA restarted
mid-utterance) is let go after VOICE_MAX_S, by the seam supervisor.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from spectra.models.house_mode import VOICE_IDLE, VOICE_STATES, now_ms
from spectra.services import house_store

logger = logging.getLogger(__name__)

#: A steady colour fades in this fast — the assistant is listening now.
VOICE_FADE_IN_S = 0.15
#: Home Assistant's own restore used `transition: 1`.
VOICE_FADE_OUT_S = 1.0
#: An overlay nobody sent "idle" for is let go after this long.
VOICE_MAX_S = 120.0

clock: Callable[[], float] = time.monotonic

_state: Optional[str] = None
_since: Optional[float] = None
_since_ms: Optional[int] = None
_painted: list[str] = []
_skipped: list[dict] = []
_last: dict = {}


def reset() -> None:
    global _state, _since, _since_ms, _painted, _skipped, _last, clock
    _state = None
    _since = None
    _since_ms = None
    _painted = []
    _skipped = []
    _last = {}
    clock = time.monotonic


def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _targets() -> tuple[list[str], list[dict]]:
    """(device ids to paint, [{fixture, reason}] skipped)."""
    from fx import device_output
    from spectra.services import house_fixtures, show_output
    settings = house_store.load_library().settings
    paint, skipped = [], []
    lent = house_fixtures.lend_reasons()
    st = house_store.state()
    for name in settings.voice_fixtures:
        devices, problems = show_output.resolve_target({"kind": "fixture",
                                                        "id": name})
        if not devices:
            dev, why = house_fixtures.resolve_fixture(name)
            if dev is not None:
                devices, problems = show_output.resolve_target(
                    {"kind": "fixture", "id": dev["id"]})
            if not devices:
                skipped.append({"fixture": name,
                                "reason": "; ".join(problems) or why or "not found"})
                continue
        did = devices[0]
        if did in lent:
            skipped.append({"fixture": did, "reason": lent[did]})
            continue
        ov = st.fixtures.get(did)
        if ov is not None and ov.power == "off":
            skipped.append({"fixture": did, "reason": "switched off"})
            continue
        if device_output.is_withheld(did):
            skipped.append({"fixture": did, "reason": "gets no stream right now"})
            continue
        busy = show_output.busy_reason(did)
        if busy:
            skipped.append({"fixture": did, "reason": f"busy — {busy}"})
            continue
        paint.append(did)
    return paint, skipped


def set_voice(state: str, *, source: str = "ha") -> dict:
    """Paint (or let go of) the voice colour. Synchronous on purpose — see
    the module docstring. Returns {"status": painted / cleared / skipped /
    unchanged / invalid, ...}."""
    global _state, _since, _since_ms, _painted, _skipped, _last
    from spectra.services import house, show_output
    state = (state or "").strip().lower()
    if state not in VOICE_STATES and state != VOICE_IDLE:
        return {"status": "invalid",
                "reason": f"state must be one of {list(VOICE_STATES) + [VOICE_IDLE]}"}
    if state == VOICE_IDLE:
        cleared = show_output.overlay_clear(fade_s=VOICE_FADE_OUT_S)
        was = _state
        _state, _since, _since_ms, _painted, _skipped = None, None, None, [], []
        _last = {"status": "cleared" if cleared else "unchanged", "state": state,
                 "from": was, "fixtures": cleared, "at_ms": now_ms()}
        return dict(_last)
    reason = house.inactive_reason()
    if reason is not None:
        # Nothing of ours is up — but never leave an old overlay behind.
        show_output.overlay_clear(fade_s=VOICE_FADE_OUT_S)
        _state, _painted = None, []
        _last = {"status": "skipped", "state": state, "reason": reason,
                 "at_ms": now_ms()}
        return dict(_last)
    look = house_store.load_library().settings.voice_looks[state]
    paint, skipped = _targets()
    # A fixture painted for the previous state that is busy now is let go.
    stale = [d for d in _painted if d not in paint]
    if stale:
        show_output.overlay_clear(stale, fade_s=VOICE_FADE_OUT_S)
    landed = show_output.overlay_set(paint, _hex_rgb(look.color),
                                     look.level / 100.0, fade_s=VOICE_FADE_IN_S)
    if _state is None:
        _since = clock()
        _since_ms = now_ms()
    _state = state
    _painted = landed
    _skipped = skipped
    _last = {"status": "painted" if landed else "skipped", "state": state,
             "color": look.color, "level": look.level, "fixtures": landed,
             "skipped": skipped, "source": source, "at_ms": now_ms()}
    if not landed:
        _last["reason"] = "every voice fixture is busy or unavailable"
    return dict(_last)


def expire() -> Optional[dict]:
    """Let go of an overlay that outlived VOICE_MAX_S, and of one whose
    mode stopped driving the room. Called by the seam supervisor."""
    global _state, _since, _since_ms, _painted, _last
    if _state is None:
        return None
    from spectra.services import house, show_output
    why = None
    if _since is not None and clock() - _since >= VOICE_MAX_S:
        why = f"no idle after {VOICE_MAX_S:.0f}s"
    elif house.inactive_reason() is not None:
        why = house.inactive_reason()
    if why is None:
        return None
    cleared = show_output.overlay_clear(fade_s=VOICE_FADE_OUT_S)
    logger.warning("house voice: let go of %r (%s) on %s", _state, why, cleared)
    _last = {"status": "expired", "state": _state, "reason": why,
             "fixtures": cleared, "at_ms": now_ms()}
    _state, _since, _since_ms, _painted = None, None, None, []
    return dict(_last)


def status() -> dict:
    return {"state": _state or VOICE_IDLE, "since_ms": _since_ms,
            "fixtures": list(_painted), "skipped": list(_skipped),
            "last": dict(_last)}
