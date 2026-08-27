"""Room-colour Preview (owner ask, 2026-08-17) — replaces the Colour
Set/Group editor's old "Apply to room" with a temporary, ALWAYS-REVERTIBLE
preview, and pauses SPECTRA's own automatic scene/response/set changes
while it's live so they can't fight the preview:

  TAP            pause TAP_HOLD_S (5s), apply, auto-revert.
  HOLD (500ms)   pause HOLD_HOLD_S (60s), apply, and STAYS until released —
                 a second press, the 60s timer, or the page navigating away
                 (spectra/web/src/colorsets/ColorSetsPage.tsx's unmount /
                 beforeunload handler POSTs /api/room-preview/release; the
                 server-side timer below is the backstop if that never
                 arrives — a killed tab, a dropped network).

Exactly one session at a time (a room has one Admiral). Starting a new one
while another is active reverts the old one first, the same way an
explicit release would — never two snapshots stacked.

THE REVERT CONTRACT (acceptance criterion 1): what gets restored is
EXACTLY what fx_seam.get_virtuals() read back the instant the preview
started — never assumed or reconstructed — mirroring dark_light.py's own
pre-dark snapshot/restore, the closest existing precedent for "read live,
hold a still frame, replay it verbatim." The snapshot and the first apply
share ONE get_virtuals() read (no window between "read what's live" and
"write over it" for something else to land in).

Live drag updates (acceptance criterion 3) call update(), which re-applies
colours WITHOUT touching the snapshot or the pause/revert timer — dragging
never restarts the clock, drops the pause, or stacks a second snapshot.
Write-rate control is the caller's: ColorGradientPicker's own onChange is
already debounced 200ms (react-gcolor-picker), and the frontend keeps at
most one in-flight /update request, dropping (not queueing) a drag tick
that arrives before the previous one's response — see ColorSetsPage.tsx.

Applying and reverting both write via fx_seam directly (apply_writes /
get_virtuals), NOT through drift_conductor/the engine's executor: a
preview must never touch the room's persisted active_set_id/wheel
position or fire_history (it isn't a real "fire", it's a look-and-decide),
and going through the same seam dark_light.py already uses keeps revert
byte-exact against what was truly live.
"""
from __future__ import annotations

import asyncio
import logging

from spectra.services.color_sets import ColorSetCard

logger = logging.getLogger(__name__)

TAP_HOLD_S = 5.0
HOLD_HOLD_S = 60.0

_lock = asyncio.Lock()
_snapshot: dict[str, dict] | None = None
_hold: bool = False
_revert_task: "asyncio.Task | None" = None


def active() -> bool:
    return _snapshot is not None


def status() -> dict:
    from spectra.services import preview_pause
    return {"active": active(), "hold": _hold if active() else None,
           "remaining_s": round(preview_pause.remaining_s(), 1) if active() else 0.0,
           "virtuals": sorted(_snapshot) if _snapshot else []}


async def _resolve(card: ColorSetCard):
    # A "group" card picks a member; a "set" card now also wears its own
    # enclosing groups' overrides (2026-08-19 broadening) — both handled by
    # resolve_for_fire itself, so Preview shows exactly what a real fire
    # would render for either kind.
    from spectra.services import color_set_groups
    return color_set_groups.resolve_for_fire(card)


async def _writes_for(card: ColorSetCard, live: dict) -> tuple[list[dict], dict[str, dict]]:
    """(writes, pre-write snapshot) for every virtual `card`'s entries
    touch and that `live` (an already-fetched fx_seam.get_virtuals() read)
    knows an effect type for. Pure given `live` — never reads/writes
    anything itself, so a caller can snapshot and apply from ONE read."""
    from spectra.services import scene_compiler
    resolved = await _resolve(card)
    if resolved is None:
        return [], {}
    by_vid = scene_compiler._set_entry_by_virtual(resolved)
    writes: list[dict] = []
    snapshot: dict[str, dict] = {}
    for vid, entry in by_vid.items():
        effect = (live.get(vid) or {}).get("effect") or {}
        effect_type = effect.get("type")
        if not effect_type:
            continue
        cfg = dict(effect.get("config") or {})
        snapshot[vid] = {"type": effect_type, "config": cfg}
        new_cfg = scene_compiler._apply_set_colors(cfg, effect_type, entry)
        writes.append({"virtual_id": vid, "effect_type": effect_type, "config": new_cfg})
    return writes, snapshot


async def _revert_locked() -> None:
    """Caller must hold _lock. Writes the held snapshot back and clears all
    session state — safe to call with an empty/already-cleared snapshot."""
    global _snapshot, _hold, _revert_task
    from spectra.services import fx_seam, preview_pause
    snap = _snapshot
    _snapshot = None
    _hold = False
    if _revert_task is not None and _revert_task is not asyncio.current_task():
        _revert_task.cancel()
    _revert_task = None
    preview_pause.clear()
    if not snap:
        return
    writes = [{"virtual_id": vid, "effect_type": s["type"], "config": s["config"]}
             for vid, s in snap.items()]
    try:
        await fx_seam.apply_writes(writes, transition_ms=0)
    except Exception:
        logger.exception("room_preview: revert failed for %s", sorted(snap))


async def _auto_revert(duration_s: float) -> None:
    try:
        await asyncio.sleep(duration_s)
    except asyncio.CancelledError:
        return
    async with _lock:
        # A concurrent release()/start() may have already cleared this
        # exact timer's session out from under it — _revert_locked is
        # idempotent (no-ops on an empty snapshot) so this is always safe.
        await _revert_locked()


async def start(card: ColorSetCard, *, hold: bool) -> dict:
    """Snapshot the live room, apply `card`'s colours, and arm the pause +
    auto-revert for TAP_HOLD_S or HOLD_HOLD_S. Returns
    {applied, virtuals, hold, expires_in_s} — applied=False (nothing to
    revert, nothing paused) when the card touches no live virtual with a
    known effect (e.g. every virtual is down, or the card has no entries).

    A DISABLED card (owner ask 2026-08-25) previews normally — an explicit
    press in the moment always wins, the same bypass a manual scene Fire
    already has — but the contradiction is NAMED, not silent:
    `overrode_disabled: True` rides on the response, the Force-Scene
    precedent (room_controls.reconcile_force_scene_if_changed).

    FORCE COLOUR (owner ask 2026-08-27, spectra/services/force_color.py) is
    the same shape one field over: a preview is the most explicit,
    most momentary act there is, so it still previews while the room's
    colour is pinned — preview_pause already outranks every other deferral
    including this one — but `overrode_force_color: <pinned id>` rides on
    the response so the contradiction is visible, and the pin (untouched)
    governs again the moment the preview reverts."""
    from spectra.services import force_color, fx_seam, preview_pause
    async with _lock:
        await _revert_locked()   # a prior session (if any) reverts first
        live = await fx_seam.get_virtuals()
        writes, snapshot = await _writes_for(card, live)
        overrode_disabled = bool(getattr(card, "disabled", False))
        overrode_force_color = force_color.pinned_id()
        if not writes:
            return {"applied": False, "virtuals": [], "hold": hold,
                    "expires_in_s": 0,
                    "overrode_disabled": overrode_disabled,
                    "overrode_force_color": overrode_force_color}
        await fx_seam.apply_writes(writes, transition_ms=0)
        global _snapshot, _hold, _revert_task
        _snapshot = snapshot
        _hold = hold
        duration = HOLD_HOLD_S if hold else TAP_HOLD_S
        preview_pause.start(duration)
        _revert_task = asyncio.create_task(_auto_revert(duration))
        return {"applied": True, "virtuals": sorted(snapshot), "hold": hold,
               "expires_in_s": duration,
               "overrode_disabled": overrode_disabled,
               "overrode_force_color": overrode_force_color}


async def update(card: ColorSetCard) -> dict:
    """Re-apply `card`'s colours live WITHOUT touching the snapshot or the
    pause timer — the live-drag path. A no-op (applied=False) once the
    session has already ended (timer fired / released) so a straggling
    drag tick from just before that can't resurrect a dead session or
    silently write to an unpaused room."""
    from spectra.services import fx_seam
    async with _lock:
        # Locked against _revert_locked (release/timer/a fresh start): a
        # drag tick landing on the far side of a revert must never write
        # colours back onto a room that just reverted out from under it.
        if not active():
            return {"applied": False, "virtuals": []}
        live = await fx_seam.get_virtuals()
        writes, _ = await _writes_for(card, live)
        if not writes:
            return {"applied": False, "virtuals": []}
        await fx_seam.apply_writes(writes, transition_ms=0)
        return {"applied": True, "virtuals": sorted(w["virtual_id"] for w in writes)}


async def release() -> dict:
    """Explicit release — a second press, or the page navigating away.
    Idempotent: releasing with nothing active is a harmless no-op."""
    was_active = active()
    async with _lock:
        await _revert_locked()
    return {"reverted": was_active}
