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

BORROWING A TV STRIP LENT TO HYPERHDR (voice-tuning-plan, §7/§9.3 2.2). A TV
strip lent to Hyperion/HyperHDR (`house_fixtures.lend_reasons()` naming it,
not a scene/override lend) is ordinarily skipped like any other lent
fixture. If it is one of `settings.voice_fixtures`, the voice may borrow it
instead: this module un-withholds it directly (`fx.device_output`, a plain
dict write — still no network, no await) so the very next frame carries the
overlay, and kicks `house_fixtures` so its own tick agrees on the exclusion
and the eventual hand-back. `house_fixtures.desired()` is the one that
decides a borrowed TV strip gets no `TARGET_LENT` write while the borrow
holds — this module never calls Hyperion/HyperHDR or the WLED itself; the
existing lend code path sends the one `{"live": false}` once the borrow
ends (idle, the mode stopping, or the 20 s cap), exactly as it would for an
ordinary lend. The cap (`VOICE_BORROW_MAX_S`) is its own, separate from
`VOICE_MAX_S` — a stuck borrow lets the strip go back to Hyperion long
before a stuck overlay on the other fixtures would expire, and release of
one does not require the other. The borrowed strip paints at
`VOICE_BORROW_LEVEL`, not the state's own look level, while
`house.media_active()` is true (Q7, 2026-11-15: "TV strip at 60% in
video") — the condition under which a strip is ever lent for this reason
in the first place.
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
#: A TV strip borrowed from Hyperion/HyperHDR is handed back after this
#: long even with no "idle" — much sooner than VOICE_MAX_S, since a strip
#: stuck on the voice colour mid-movie is a far more visible mistake than
#: one of the ordinary voice fixtures staying lit a little late.
VOICE_BORROW_MAX_S = 20.0
#: The borrowed TV strip's level while media is active (Q7, 2026-11-15).
VOICE_BORROW_LEVEL = 60.0

clock: Callable[[], float] = time.monotonic

_state: Optional[str] = None
_since: Optional[float] = None
_since_ms: Optional[int] = None
_painted: list[str] = []
_skipped: list[dict] = []
_last: dict = {}
_borrow_device: Optional[str] = None
_borrow_since: Optional[float] = None
_borrow_since_ms: Optional[int] = None


def reset() -> None:
    global _state, _since, _since_ms, _painted, _skipped, _last, clock
    global _borrow_device, _borrow_since, _borrow_since_ms
    _state = None
    _since = None
    _since_ms = None
    _painted = []
    _skipped = []
    _last = {}
    _borrow_device = None
    _borrow_since = None
    _borrow_since_ms = None
    clock = time.monotonic


def borrowed_device() -> Optional[str]:
    """The TV strip currently borrowed from Hyperion/HyperHDR, or None —
    `house_fixtures.desired()` reads this to leave it unlent while it holds."""
    return _borrow_device


def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _borrowable(did: str, strips: set, reason: str) -> bool:
    """Only a TV strip lent for Hyperion/HyperHDR — never one lent to an
    explicit scene/override target, and never one already capped this
    borrow (checked by the caller before this is consulted again)."""
    return did in strips and "hyperion" in reason.lower()


def _unwithhold_for_borrow(did: str) -> None:
    """Let the borrowed strip stream THIS frame, not the next tick — a
    plain dict write (fx.device_output), still no network and no await.
    `house_fixtures.kick()` asks its own tick to agree on the exclusion
    (and, later, to hand the strip back) sooner than its normal cadence."""
    from fx import device_output
    from spectra.services import house_fixtures
    w = device_output.withheld()
    if did in w:
        w.pop(did, None)
        device_output.set_withheld(w)
    house_fixtures.kick()


def _start_borrow(did: str) -> None:
    global _borrow_device, _borrow_since, _borrow_since_ms
    if _borrow_device != did:
        _borrow_device, _borrow_since, _borrow_since_ms = did, clock(), now_ms()
    _unwithhold_for_borrow(did)


def _release_borrow() -> None:
    """End the borrow: re-withhold at once (stops our own stream this
    frame) and kick the supervisor, whose next tick finds the strip lent
    again and sends it the one `{"live": false}` — the existing lend code
    path, not a second one invented here."""
    global _borrow_device, _borrow_since, _borrow_since_ms
    from fx import device_output
    from spectra.services import house_fixtures
    did = _borrow_device
    _borrow_device, _borrow_since, _borrow_since_ms = None, None, None
    if did is not None:
        w = device_output.withheld()
        if did not in w:
            lent = house_fixtures.lend_reasons()
            w[did] = lent.get(did, "lent: Hyperion/HyperHDR drives the strip")
            device_output.set_withheld(w)
        house_fixtures.kick()


def _expire_borrow() -> Optional[dict]:
    """Let go of a borrowed TV strip that outlived VOICE_BORROW_MAX_S —
    scoped to the strip alone; the rest of the voice overlay stays up."""
    global _painted
    if _borrow_device is None or _borrow_since is None:
        return None
    if clock() - _borrow_since < VOICE_BORROW_MAX_S:
        return None
    from spectra.services import show_output
    did = _borrow_device
    cleared = show_output.overlay_clear([did], fade_s=VOICE_FADE_OUT_S)
    _painted = [d for d in _painted if d != did]
    _release_borrow()
    logger.warning("house voice: let go of the borrowed TV strip %s "
                   "(%.0fs cap)", did, VOICE_BORROW_MAX_S)
    return {"status": "borrow_expired", "device": did, "fixtures": cleared,
            "at_ms": now_ms()}


def _targets() -> tuple[list[str], list[dict], Optional[str]]:
    """(device ids to paint, [{fixture, reason}] skipped, the borrowed TV
    strip's id or None)."""
    from fx import device_output
    from spectra.services import house_fixtures, show_output
    settings = house_store.load_library().settings
    paint, skipped = [], []
    lent = house_fixtures.lend_reasons()
    strips = set(house_fixtures.tv_strip_ids())
    st = house_store.state()
    borrowing = None
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
            capped = (_borrow_device == did and _borrow_since is not None
                      and clock() - _borrow_since >= VOICE_BORROW_MAX_S)
            if not capped and _borrowable(did, strips, lent[did]):
                _start_borrow(did)
            elif capped:
                skipped.append({"fixture": did,
                                "reason": f"borrow capped at "
                                          f"{VOICE_BORROW_MAX_S:.0f}s"})
                continue
            else:
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
        if did == _borrow_device:
            borrowing = did
    if borrowing is None and _borrow_device is not None:
        _release_borrow()
    return paint, skipped, borrowing


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
        if _borrow_device is not None:
            _release_borrow()
        was = _state
        _state, _since, _since_ms, _painted, _skipped = None, None, None, [], []
        _last = {"status": "cleared" if cleared else "unchanged", "state": state,
                 "from": was, "fixtures": cleared, "at_ms": now_ms()}
        return dict(_last)
    reason = house.inactive_reason()
    if reason is not None:
        # Nothing of ours is up — but never leave an old overlay behind.
        show_output.overlay_clear(fade_s=VOICE_FADE_OUT_S)
        if _borrow_device is not None:
            _release_borrow()
        _state, _painted = None, []
        _last = {"status": "skipped", "state": state, "reason": reason,
                 "at_ms": now_ms()}
        return dict(_last)
    look = house_store.load_library().settings.voice_looks[state]
    paint, skipped, borrowed = _targets()
    # A fixture painted for the previous state that is busy now is let go.
    stale = [d for d in _painted if d not in paint]
    if stale:
        show_output.overlay_clear(stale, fade_s=VOICE_FADE_OUT_S)
    others = [d for d in paint if d != borrowed]
    landed = show_output.overlay_set(others, _hex_rgb(look.color),
                                     look.level / 100.0, fade_s=VOICE_FADE_IN_S)
    if borrowed is not None:
        # The borrowed TV strip caps at VOICE_BORROW_LEVEL while media is
        # active (Q7, 2026-11-15) — the only reason it is ever lent to
        # Hyperion/HyperHDR in the first place, so this is really always.
        borrow_level = VOICE_BORROW_LEVEL if house.media_active() else look.level
        landed = landed + show_output.overlay_set(
            [borrowed], _hex_rgb(look.color), borrow_level / 100.0,
            fade_s=VOICE_FADE_IN_S)
    if _state is None:
        _since = clock()
        _since_ms = now_ms()
    _state = state
    _painted = landed
    _skipped = skipped
    _last = {"status": "painted" if landed else "skipped", "state": state,
             "color": look.color, "level": look.level, "fixtures": landed,
             "skipped": skipped, "source": source, "at_ms": now_ms()}
    if borrowed is not None:
        _last["borrowed_tv_strip"] = borrowed
    if not landed:
        _last["reason"] = "every voice fixture is busy or unavailable"
    return dict(_last)


def expire() -> Optional[dict]:
    """Let go of an overlay that outlived VOICE_MAX_S, and of one whose
    mode stopped driving the room. Also lets go of a borrowed TV strip
    that outlived VOICE_BORROW_MAX_S on its own, well before VOICE_MAX_S —
    the rest of the voice overlay (if any) is unaffected by that cap.
    Called by the seam supervisor."""
    global _state, _since, _since_ms, _painted, _last
    borrow_expired = _expire_borrow()
    if _state is None:
        return borrow_expired
    from spectra.services import house, show_output
    why = None
    if _since is not None and clock() - _since >= VOICE_MAX_S:
        why = f"no idle after {VOICE_MAX_S:.0f}s"
    elif house.inactive_reason() is not None:
        why = house.inactive_reason()
    if why is None:
        return borrow_expired
    cleared = show_output.overlay_clear(fade_s=VOICE_FADE_OUT_S)
    if _borrow_device is not None:
        _release_borrow()
    logger.warning("house voice: let go of %r (%s) on %s", _state, why, cleared)
    _last = {"status": "expired", "state": _state, "reason": why,
             "fixtures": cleared, "at_ms": now_ms()}
    _state, _since, _since_ms, _painted = None, None, None, []
    return dict(_last)


def status() -> dict:
    borrow = None
    if _borrow_device is not None:
        borrow = {"device": _borrow_device, "since_ms": _borrow_since_ms,
                  "cap_s": VOICE_BORROW_MAX_S, "level": VOICE_BORROW_LEVEL}
    return {"state": _state or VOICE_IDLE, "since_ms": _since_ms,
            "fixtures": list(_painted), "skipped": list(_skipped),
            "last": dict(_last), "borrow": borrow}
