"""SPECTRA's global Dark/Light room mode (day-one bar item, SPECTRA_SPEC.md
§9) — the room bar's "Dark mode" checkbox
(room_controls.RoomControlState.dark_mode_enabled).

THE DIRECT EQUIVALENT (D1 fidelity rule: exact where one exists). Legacy's
mechanism is services/display_mode.py + the LedFX-side `dark_lock` flag
(fx/virtuals.py CONFIG_SCHEMA, vendored verbatim — see fx/VENDOR.md): while a
virtual's `dark_lock` config is True, fx/effects/__init__.py's
Effect._apply_config hard-clamps background_color -> #000000 /
background_brightness -> 0 on EVERY write path that touches those keys, and
flipping the flag on immediately blacks whatever the virtual is showing
RIGHT NOW (fx/virtuals.py's update_config). This is the SAME vendored code
SPECTRA already writes through (spectra/services/fx_seam.py) — dark mode
here is exactly that flag, toggled the same way legacy's own
services/display_mode.sync_dark_locks does, over fx_seam's ownership-routed
set_virtual_config (HTTP to the external LedFX pre-handover, in-process
facade once SPECTRA owns the lights — the same routing apply_writes uses,
so this module needs no ownership awareness of its own).

WHERE THIS MODULE DELIBERATELY DIFFERS FROM LEGACY, AND WHY (D1's free
half — differs in kind, not a corner cut):

  Two states, not three. Legacy's TopBar cycles default -> dark -> light,
  because "default" meant "defer to a LOWER cascade level" (trigger ->
  scene group -> scene -> Set Color action -> Color Group card -> Color Set
  card — services/display_mode.py's seven-level resolve()). Every one of
  those lower levels is the retired Light Mode Chooser / per-node dark-light
  authoring (SPECTRA_SPEC.md §36, §42 — RETIRED, explicitly NOT this
  feature). With nothing left to defer TO, "default" and "light" resolve
  identically in SPECTRA (dark_lock False, nothing forced) — so
  dark_mode_enabled is a plain bool, matching the two states standing order
  11's own proof names ("switch to dark... switch to light").

  Snapshot-and-restore, not re-fire-the-last-Color-Set. Legacy's own
  unlock is ALSO not self-restoring (services/display_mode.py: "Unlocking
  restores nothing by itself") — routers/control.py's POST /display-mode
  repaints by re-firing state.last_color_group_id/last_color_set_id at
  advance=0. SPECTRA has no equivalent "the room's last-fired Color Set,
  replayable without reshuffling" concept at the room-control layer (that
  idea belongs to the same retired per-node authoring world). What SPECTRA
  captures instead, right before locking, is the LIVE per-virtual effect
  (type + config) actually read back from fx_seam.get_virtuals() — closer
  to ground truth than "replay the last authored card" would be, since it's
  what was REALLY showing, not what was last intentionally fired. Persisted
  to DARK_LIGHT_SNAPSHOT_FILE (survives a SPECTRA restart while dark) and
  replayed via fx_seam.apply_writes() on the transition back to light —
  itself the exact write path a normal scene fire already uses — BUT ONLY
  WHEN NOTHING LIVE IS ABOUT TO REPAINT IT ANYWAY: bridge.is_playing()
  (spectra/services/bridge.py) gates the repaint. The snapshot is a still
  frame from the moment dark was engaged — while music is actively
  playing, forcing that stale frame back is the same shape of mistake as
  Ambient holding the room static through a song: it imposes a frozen look
  on a room that should be tracking live music, right as the room's own
  automatic driver (scene_change_mode / trigger_engine / drift) is about to
  repaint it for real. dark_lock still clears either way (nothing stays
  forced black); only the STALE repaint is skipped, reported as
  `repaint_skipped: "music_playing"` in the reconcile result. With no
  music playing (or paused — the room-proof's own condition), there is no
  live driver about to repaint it, so the snapshot restore is the only way
  back and proceeds as before.

  No settings.display_light_bg_color backfill. Legacy's "light" mode
  additionally backfills settings.display_light_bg_color/_brightness onto
  entries that never authored their own background (services/
  trigger_engine.py's _execute_set_color, ~line 4541) — a data-authoring
  default, not a mechanism this module owns; SPECTRA's "light" is simply
  "not dark, whatever was there before comes back," which is what the
  snapshot restores.

Shielded devices ARE ported verbatim: dark_light_shield_categories (default
["Singles"], legacy's own default) / dark_light_shield_virtuals on
RoomControlState, resolved the same way services/display_mode.shielded_
virtuals() does (category name -> member virtuals via the shared registry,
fx/device_model.get_virtuals_for_category — read-only, SPECTRA doesn't own
device_categories.json). A shielded virtual is walked on every reconcile
same as legacy's loop (not skipped outright) so it always lands dark_lock
False regardless of the room's mode — "keeps its own look regardless."

Orthogonal to Ambient, exactly like legacy (services/ambient_mode.py has
zero display_mode references, confirmed by grep). Not a coincidence to
preserve here: while Ambient holds a Hue device, that device's stream is
FROZEN and driven by direct bridge REST (spectra/services/ambient.py),
bypassing LedFX/dark_lock entirely — so toggling dark mode has no visible
effect on a Hue device currently held by Ambient. That is correct layering,
not a defect: two independent controls, neither aware of the other, same as
legacy. It only ever shows on devices LedFX is actually rendering (WLED
etc., or a Hue device with Ambient off).

Verification is "read real state back," not "trust the POST" (the standing
lesson of every other partial-write defect this project has fixed — see
§51's Ambient confirmed-vs-attempted note): after pushing every dark_lock
change, one fx_seam.get_virtuals() read confirms the ACTUAL resulting
dark_lock per virtual; anything that doesn't match comes back named in
`unconfirmed`, never folded into a bigger "done" count.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Optional

from spectra import config
from spectra.services import fx_seam

logger = logging.getLogger(__name__)

_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _load_snapshot() -> dict:
    path = config.DARK_LIGHT_SNAPSHOT_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("dark/light: unreadable snapshot %s — treating as empty", path)
        return {}


def _save_snapshot(snapshot: dict) -> None:
    path = config.DARK_LIGHT_SNAPSHOT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _clear_snapshot() -> None:
    try:
        config.DARK_LIGHT_SNAPSHOT_FILE.unlink()
    except FileNotFoundError:
        pass


def _shielded_set(shield_categories: list[str], shield_virtuals: list[str]) -> set[str]:
    from fx import device_model
    out = {str(v) for v in shield_virtuals}
    for name in shield_categories:
        out.update(device_model.get_virtuals_for_category(str(name)))
    return out


async def reconcile(enabled: bool, shield_categories: list[str],
                    shield_virtuals: list[str]) -> dict:
    """Drive the room's dark_mode_enabled toggle to `enabled`. Locked so
    rapid toggles / a shield-list edit racing a mode flip can't interleave
    and fight over the same snapshot. Never raises — a mid-handover refusal
    or an unreachable LedFX still leaves the room-control save itself
    succeeding (state is the durable record even when nothing could be
    driven live), same posture as ambient.reconcile()."""
    async with _get_lock():
        try:
            return await _reconcile_impl(enabled, shield_categories, shield_virtuals)
        except fx_seam.RoomReleased:
            logger.warning("dark/light: room released — state saved, no lights touched")
            return {"status": "released"}
        except fx_seam.HandoverInProgress:
            logger.warning("dark/light: handover in flight — state saved, no lights touched")
            return {"status": "handover-in-progress"}
        except Exception as exc:
            logger.exception("dark/light: reconcile failed")
            return {"status": "failed", "error": str(exc)}


async def _reconcile_impl(enabled: bool, shield_categories: list[str],
                          shield_virtuals: list[str]) -> dict:
    from fx import device_model
    virtual_ids = device_model.get_all_virtual_ids()
    if not virtual_ids:
        return {"status": "no-devices"}
    shielded = _shielded_set(shield_categories, shield_virtuals)

    snapshot: dict = {}
    if enabled:
        snapshot = _load_snapshot()
        if not snapshot:
            live = await fx_seam.get_virtuals()
            snapshot = {
                vid: {"type": live[vid]["effect"]["type"],
                      "config": live[vid]["effect"]["config"]}
                for vid in virtual_ids
                if vid not in shielded and (live.get(vid) or {}).get("effect", {}).get("type")
            }
            if snapshot:
                _save_snapshot(snapshot)
    else:
        snapshot = _load_snapshot()

    for vid in virtual_ids:
        want = enabled and vid not in shielded
        try:
            await fx_seam.set_virtual_config(vid, {"dark_lock": want})
        except Exception:
            logger.exception("dark/light: dark_lock push failed for '%s' (want %s)",
                             vid, want)

    restored: list[str] = []
    repaint_skipped: Optional[str] = None
    if not enabled and snapshot:
        from spectra.services.engine import bridge
        if bridge.is_playing():
            # Music is live right now — the snapshot is a still frame from
            # the moment dark was engaged, already stale. Forcing it back is
            # the same mistake as Ambient holding the room static through a
            # song: it imposes a frozen look on a room that should be
            # tracking live music. Leave it to the room's own automatic
            # driver (scene_change_mode / trigger_engine / drift) to repaint
            # it on its own next fire — dark_lock is already cleared below,
            # so nothing is left forced black, just not yet repainted.
            repaint_skipped = "music_playing"
            logger.info("dark/light: music is playing — skipping the stale "
                       "pre-dark repaint, the room's own live show repaints "
                       "it on its next natural fire")
        else:
            writes = [{"virtual_id": vid, "effect_type": snap["type"], "config": snap["config"]}
                     for vid, snap in snapshot.items()
                     if vid in virtual_ids and vid not in shielded]
            if writes:
                try:
                    await fx_seam.apply_writes(writes, transition_ms=0)
                    restored = [w["virtual_id"] for w in writes]
                except Exception:
                    logger.exception("dark/light: repaint after unlock failed")
        _clear_snapshot()

    # Verify at the bridge — read the ACTUAL resulting state back rather
    # than trusting the POSTs above landed.
    try:
        live_after = await fx_seam.get_virtuals()
    except Exception:
        logger.exception("dark/light: could not read back virtuals to confirm")
        live_after = {}
    locked: list[str] = []
    unconfirmed: list[str] = []
    for vid in virtual_ids:
        want = enabled and vid not in shielded
        actual = bool((live_after.get(vid) or {}).get("config", {}).get("dark_lock", False))
        if actual == want:
            if want:
                locked.append(vid)
        else:
            unconfirmed.append(vid)

    result: dict = {
        "status": "dark" if enabled else "light",
        "locked": sorted(locked),
        "shielded": sorted(shielded & set(virtual_ids)),
    }
    if not enabled:
        result["restored"] = sorted(restored)
        if repaint_skipped:
            result["repaint_skipped"] = repaint_skipped
    if unconfirmed:
        result["unconfirmed"] = sorted(unconfirmed)
        logger.error("dark/light: %d virtual(s) not confirmed at dark_lock=%s: %s",
                     len(unconfirmed), enabled, unconfirmed)
    return result
