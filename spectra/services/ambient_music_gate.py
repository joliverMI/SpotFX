"""Ambient's music-precedence gate — the Admiral's ruling, 2026-08-15: Ambient
is the room's RESTING state, not a state that outranks music. "I want the
whole house to restore when a music sync ends" (his own words) is the other
half of the same rule: while music is genuinely playing, MUSIC WINS and
Ambient stands aside; the moment it stops, Ambient resumes on its own.

The proven live defect this closes: RoomControlState.ambient_enabled=True
freezes every live Hue device (services/ambient.py) unconditionally — it
never checked whether a track was playing. 2026-08-15 room proof: Ambient
on + a real track playing + an active scene + triggers firing = all 19 Hue
bulbs sat frozen at ambient cream, following none of it. Ambient was not
merely competing with music; it silently swallowed the whole song.

RoomControlState.ambient_enabled still means exactly what it said before
("I want Ambient") — it is the STANDING PREFERENCE and this module never
flips it. What this module owns is the LIVE PHYSICAL hold, which now
tracks a second, independent signal — bridge.is_playing() — and only
actually holds the room when BOTH are true: the preference says yes, AND
nothing is playing. Every caller that can change either input funnels
through reconcile()/reconcile_now() rather than calling
services.ambient.reconcile() directly, so "music wins" can never be
bypassed by one path (a human PUT, a bridge broadcast, process
startup/resume) reaching the Hue write seam on its own:
  - spectra/services/engine.py's _on_track_uri — every bridge "state"
    broadcast (several times a minute), the primary trigger.
  - spectra/services/room_controls.py's reconcile_ambient_if_changed — a
    human PUT /api/room-controls save.
  - spectra/app.py's _standalone_lifespan — process startup/resume.
This module never talks to a Hue bridge itself — every actual write still
goes through services.ambient.reconcile(), the exact function a human
toggling the room-bar checkbox always drove — so Ambient's release/
ease-back fidelity (the thing the Admiral explicitly praised, "way
better") is untouched BY CONSTRUCTION, not merely re-tested.

Fail-safe direction, on purpose, and NOT symmetric with "confirmed
playing": an UNKNOWN playback read (is_playing() returns None — bridge.py
docstring: only when no signal has EVER arrived) never ACTIVELY changes
the live hold either way — _desired_hold() returns whatever is already
held. Collapsing "unknown" onto "confirmed playing" (both -> release) was
an earlier, tempting shortcut, and it's wrong: it would make a transient
bridge blip actively RELEASE an already-quiet, already-held room — a
flicker regression against the ease-back-must-survive-unharmed bar this
fix is judged against, for a case (bridge hiccup) that has nothing to do
with music actually starting. The only asymmetry left is at the OTHER
edge, first engagement: a room that has never yet been confirmed quiet
starts unheld (module-load default), so "unknown" there means "stay
unheld," not "start holding blind." That bounds the cost to a narrow
window at process start/resume, before the first bridge broadcast
arrives, where Ambient briefly does not hold a truly quiet room even
though the preference says on — one bridge message wide, and VISIBLE
(status() below) rather than silently wrong the other way. Turning
ambient_enabled off is the one thing that always wins regardless of any
playback reading, confirmed or not. A track loaded but genuinely not
playing (paused, or nothing loaded at all) reads as "not playing" —
bridge.is_playing() docstring — so a deliberate pause also lets Ambient
resume, matching "when music ends" read literally.

Visibility (the second half of the fix, the Admiral's own words: "a
control that reads as ON while doing nothing is the exact pattern this
project has spent the week killing"): status() reports which of four
MODES is currently true — "off" (ambient_enabled is False), "holding"
(enabled, and actually holding the room), "yielding" (enabled, but
standing aside for music or an unresolved playback read), or
"transitioning" (a hold/release is physically in flight right now) —
folded into GET /api/engine/status's own "ambient" key so the existing 3s
room-bar/top-bar poll (spectra/web/src/queries.ts useEngineStatus) shows
it live with no new endpoint. reconcile()/reconcile_now() themselves keep
returning services.ambient.reconcile()'s own {"status": ...} shape (or an
honest "on"/"off"/"yielding" synthesized when nothing needed to change) —
the SAME shape spectra/api/room_controls.py's PUT response and
RoomControlsBar.tsx's ambient_result badge already expect — status() is
the separate, always-current surface for the room-bar's live indicator.

Concurrency: _apply_lock serialises this module's own decisions (a burst
of bridge broadcasts must not fire a burst of redundant Hue reconciles);
services.ambient.reconcile()'s own lock still serialises the underlying
Hue I/O regardless of how many callers overlap. reconcile() only ever
AWAITS the full reconcile and returns its honest final result — it never
backgrounds anything itself. A caller on a hot path that must not block
for the several seconds a hold/release can take (engine.py's
_on_track_uri, called on every bridge broadcast) wraps the call in
asyncio.create_task instead of awaiting it inline; a caller where blocking
is expected and desired (a PUT response, startup) awaits it directly.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from spectra.services import ambient
from spectra.services.room_controls import load_room_controls

logger = logging.getLogger(__name__)

_held = False
_held_color: Optional[str] = None
_last_result: dict = {}
_apply_lock: Optional[asyncio.Lock] = None


def _get_apply_lock() -> asyncio.Lock:
    global _apply_lock
    if _apply_lock is None:
        _apply_lock = asyncio.Lock()
    return _apply_lock


def _desired_hold(ambient_enabled: bool, is_playing: Optional[bool],
                  currently_held: bool) -> bool:
    """The full precedence rule. Disabled always releases, regardless of
    playback. A CONFIRMED read (True/False) always wins even over an
    existing hold — that's the whole point: music starting releases an
    already-held room, music stopping re-engages one that wasn't held. An
    UNKNOWN read (None) never actively changes anything — it returns
    whatever is already held, so a bridge blip can neither release an
    already-quiet hold nor spuriously start one (see module docstring)."""
    if not ambient_enabled:
        return False
    if is_playing is None:
        return currently_held
    return is_playing is False


async def reconcile(is_playing: Optional[bool]) -> dict:
    """The core decision point — reconcile the live hold against the
    room's CURRENT ambient_enabled/_color preference and the given
    playback read. Always resolves synchronously to the honest final
    result (services.ambient.reconcile()'s own read-back retries can take
    several seconds) — see module docstring for who should await this
    inline vs. background it. Returns the same {"status": ...} shape
    services.ambient.reconcile() returns when it actually acts; when
    nothing needed to change it synthesizes an equally honest "on" /
    "off" / "yielding" rather than replaying a stale prior result."""
    controls = load_room_controls()
    desired = _desired_hold(controls.ambient_enabled, is_playing, _held)
    return await _apply(controls.ambient_enabled, desired, controls.ambient_color)


async def reconcile_now() -> dict:
    """Convenience wrapper for callers with no playback read of their
    own — a human PUT save (room_controls.reconcile_ambient_if_changed) or
    process startup/resume (app.py) — reads the live bridge singleton's
    current is_playing() itself. Deferred import: spectra.services.engine
    imports this module (for status(), folded into engine.status()), so a
    module-level import here would cycle."""
    from spectra.services.engine import bridge
    return await reconcile(bridge.is_playing())


async def _apply(enabled: bool, desired: bool, color: Optional[str]) -> dict:
    global _held, _held_color, _last_result
    async with _get_apply_lock():
        # Re-check after acquiring the lock: a caller queued behind an
        # in-flight reconcile may already have what it wants once its turn
        # comes, and must not re-fire an identical Hue write.
        if desired != _held or (desired and color != _held_color):
            _last_result = await ambient.reconcile(desired, color)
            if _last_result.get("status") != "failed":
                _held = desired
                _held_color = color if desired else None
            return _last_result
    if desired:
        return {"status": "on"}
    return {"status": "off"} if not enabled else {"status": "yielding"}


def status() -> dict:
    """The room-bar's honest, always-live read of what Ambient is
    ACTUALLY doing right now — not just what the checkbox says. Folded
    into GET /api/engine/status by services/engine.py."""
    controls = load_room_controls()
    lock = _apply_lock
    if not controls.ambient_enabled:
        mode = "off"
    elif lock is not None and lock.locked():
        mode = "transitioning"
    elif _held:
        mode = "holding"
    else:
        mode = "yielding"
    out = {"enabled": controls.ambient_enabled, "mode": mode, "held": _held}
    if _last_result:
        out["result"] = _last_result
    return out
