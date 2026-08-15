"""Ambient's mode precedence gate — three settings, in the Admiral's own
language (2026-08-15 ruling, refined the same day after his first "music
wins always" framing turned out to be wrong):

  "off"    Ambient never holds. The whole room performs, Hue included.
  "always" Hue is held lit at ambient_color UNCONDITIONALLY — music playing
           or not. His own words: "Ambient mode should run even while the
           music is playing so that my Hue Lights are lit and bright but
           the other lights are still running the show." This is NOT the
           precedence bug re-introduced — it's a mode he explicitly wants,
           proven live 2026-08-14/15 to leave every non-Hue device
           untouched (services/ambient.py's device filter is Hue-only,
           architecturally; also grep-confirmed zero references to ambient
           state anywhere in selection_kernel.py/scene_sequencer.py/
           trigger_engine.py — Hue holding can never double-penalise or
           starve the show elsewhere, because nothing in scene selection
           or rendering even knows Ambient exists).
  "auto"   The 2026-08-15 music-precedence fix: holds only when playback is
           CONFIRMED not-playing, releases the instant it's confirmed
           playing, carries an unresolved read forward rather than
           guessing either way. Proven live the same day: hold engaging on
           a genuine pause (17/17 lights confirmed at the exact target
           colour), and release GLIDING back — a two-phase ease across
           colour and brightness, ~16s wall-clock, never a snap — when he
           resumed. THAT MEASURED SHAPE IS NOW THE REGRESSION BASELINE:
           any future change to this module must re-prove the glide
           survives, not assume it does.

The earlier, narrower framing this module shipped under first ("music
always wins") is superseded by the three-setting model above, not deleted
— "auto" is exactly that original fix, kept as one of the three choices
rather than the only one.

RoomControlState.ambient_mode is the STANDING PREFERENCE and this module
never flips it. What this module owns is the LIVE PHYSICAL hold, which
tracks a second, independent signal — bridge.is_playing() — used only by
"auto"; "off" and "always" never consult it at all. Every caller that can
change either input funnels through reconcile()/reconcile_now() rather
than calling services.ambient.reconcile() directly, so mode precedence can
never be bypassed by one path (a human PUT, a bridge broadcast, process
startup/resume) reaching the Hue write seam on its own:
  - spectra/services/engine.py's _on_track_uri — every bridge "state"
    broadcast (several times a minute), the primary trigger for "auto".
  - spectra/services/room_controls.py's reconcile_ambient_if_changed — a
    human PUT /api/room-controls save (covers "always" too — flipping the
    setting to "always" holds immediately regardless of what's playing).
  - spectra/app.py's _standalone_lifespan — process startup/resume.
This module never talks to a Hue bridge itself — every actual write still
goes through services.ambient.reconcile(), the exact function a human
toggling the room-bar control always drove — so Ambient's release/
ease-back fidelity (the thing the Admiral explicitly praised, "way
better") is untouched BY CONSTRUCTION, not merely re-tested.

Fail-safe direction for "auto", on purpose, and NOT symmetric with
"confirmed playing": an UNKNOWN playback read (is_playing() returns None —
bridge.py docstring: only when no signal has EVER arrived) never ACTIVELY
changes the live hold either way — _desired_hold() returns whatever is
already held. Collapsing "unknown" onto "confirmed playing" (both ->
release) was an earlier, tempting shortcut, and it's wrong: it would make
a transient bridge blip actively RELEASE an already-quiet, already-held
room — a flicker regression against the ease-back-must-survive-unharmed
bar this fix is judged against, for a case (bridge hiccup) that has
nothing to do with music actually starting. The only asymmetry left is at
the OTHER edge, first engagement: a room that has never yet been confirmed
quiet starts unheld (module-load default), so "unknown" there means "stay
unheld," not "start holding blind." That bounds the cost to a narrow
window at process start/resume, before the first bridge broadcast
arrives, where "auto" briefly does not hold a truly quiet room even
though the setting says so — one bridge message wide, and VISIBLE
(status() below) rather than silently wrong the other way. Switching the
setting to "off" is the one thing that always wins regardless of any
playback reading, confirmed or not. A track loaded but genuinely not
playing (paused, or nothing loaded at all) reads as "not playing" —
bridge.is_playing() docstring — so a deliberate pause also lets "auto"
resume, matching "when music ends" read literally.

Visibility (the fix's other half, the Admiral's own words: "a control that
reads as ON while doing nothing is the exact pattern this project has
spent the week killing"): status() reports which of four MODES is
currently true — "off" (setting is "off"), "holding" (actually holding
the room right now — true throughout "always", and only when confirmed
quiet under "auto"), "yielding" (setting isn't "off", but standing aside
for music or an unresolved playback read — only reachable under "auto"),
or "transitioning" (a hold/release is physically in flight) — folded into
GET /api/engine/status's own "ambient" key so the existing 3s room-bar/
top-bar poll (spectra/web/src/queries.ts useEngineStatus) shows it live
with no new endpoint. reconcile()/reconcile_now() themselves keep
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
from spectra.services.room_controls import AmbientMode, load_room_controls

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


def _desired_hold(ambient_mode: AmbientMode, is_playing: Optional[bool],
                  currently_held: bool) -> bool:
    """The full precedence rule, one branch per setting.

    "off" always releases, regardless of playback. "always" always holds,
    regardless of playback — his own requested mode, not a bypass of
    anything. "auto" is the music-precedence rule: a CONFIRMED read
    (True/False) always wins even over an existing hold — that's the whole
    point: music starting releases an already-held room, music stopping
    re-engages one that wasn't held. An UNKNOWN read (None) never actively
    changes anything under "auto" — it returns whatever is already held,
    so a bridge blip can neither release an already-quiet hold nor
    spuriously start one (see module docstring)."""
    if ambient_mode == "off":
        return False
    if ambient_mode == "always":
        return True
    # "auto"
    if is_playing is None:
        return currently_held
    return is_playing is False


async def reconcile(is_playing: Optional[bool]) -> dict:
    """The core decision point — reconcile the live hold against the
    room's CURRENT ambient_mode/_color preference and the given playback
    read (playback only matters for "auto"). Always resolves synchronously
    to the honest final result (services.ambient.reconcile()'s own
    read-back retries can take several seconds) — see module docstring for
    who should await this inline vs. background it. Returns the same
    {"status": ...} shape services.ambient.reconcile() returns when it
    actually acts; when nothing needed to change it synthesizes an equally
    honest "on" / "off" / "yielding" rather than replaying a stale prior
    result."""
    controls = load_room_controls()
    desired = _desired_hold(controls.ambient_mode, is_playing, _held)
    return await _apply(controls.ambient_mode, desired, controls.ambient_color)


async def reconcile_now() -> dict:
    """Convenience wrapper for callers with no playback read of their
    own — a human PUT save (room_controls.reconcile_ambient_if_changed) or
    process startup/resume (app.py) — reads the live bridge singleton's
    current is_playing() itself. Deferred import: spectra.services.engine
    imports this module (for status(), folded into engine.status()), so a
    module-level import here would cycle."""
    from spectra.services.engine import bridge
    return await reconcile(bridge.is_playing())


async def _apply(ambient_mode: AmbientMode, desired: bool, color: Optional[str]) -> dict:
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
    return {"status": "off"} if ambient_mode == "off" else {"status": "yielding"}


def status() -> dict:
    """The room-bar's honest, always-live read of what Ambient is
    ACTUALLY doing right now — not just what the setting says. Folded
    into GET /api/engine/status by services/engine.py."""
    controls = load_room_controls()
    setting = controls.ambient_mode
    lock = _apply_lock
    if setting == "off":
        mode = "off"
    elif lock is not None and lock.locked():
        mode = "transitioning"
    elif _held:
        mode = "holding"
    else:
        mode = "yielding"
    out = {"setting": setting, "mode": mode, "held": _held}
    if _last_result:
        out["result"] = _last_result
    return out
