"""SPECTRA's global Default/Dark/Light room mode (day-one bar item,
SPECTRA_SPEC.md §9) — the room bar's three-way display-mode control
(room_controls.RoomControlState.display_mode).

THE DIRECT EQUIVALENT (D1 fidelity rule: exact where one exists). Legacy's
mechanism is services/display_mode.py + the LedFX-side `dark_lock` flag
(fx/virtuals.py CONFIG_SCHEMA, vendored verbatim — see fx/VENDOR.md): while a
virtual's `dark_lock` config is True, fx/effects/__init__.py's
Effect._apply_config hard-clamps background_color -> #000000 /
background_brightness -> 0 on EVERY write path that touches those keys, and
flipping the flag on immediately blacks whatever the virtual is showing
RIGHT NOW (fx/virtuals.py's update_config). This is the SAME vendored code
SPECTRA already writes through (spectra/services/fx_seam.py) — Dark mode
here is exactly that flag, toggled the same way legacy's own
services/display_mode.sync_dark_locks does, over fx_seam's ownership-routed
set_virtual_config (HTTP to the external LedFX pre-handover, in-process
facade once SPECTRA owns the lights — the same routing apply_writes uses,
so this module needs no ownership awareness of its own).

THREE-STATE REBUILD (2026-08-16, replacing the original bool): a scout
investigation (data/spectra-display-mode-three-state/report.md) found the
original two-state build was a mislabel, not a smaller-but-honest version —
`dark_mode_enabled=False` was called "Light" everywhere (code, API status
field, help text) but behaved as legacy's Default (nothing forced). Legacy's
actual Light — a configurable, always-on, immediately-repainted forced
background — was never built. This module now implements all three states
legacy has, keyed off `display_mode: "default" | "dark" | "light"`:

  "dark"    Exactly as before: dark_lock=True on every non-shielded
            virtual, hard-clamping background black at the LedFX layer.

  "light"   THE NEW HALF, and the priority one — his scenes all author dark
            colour sets, so without a forced Light state he has no
            before/after to test any of this against. Writes
            display_light_bg_color/_brightness (RoomControlState, legacy
            defaults #201830 @ 0.3) as background_color/background_
            brightness onto every non-shielded virtual's CURRENT live
            effect config, via fx_seam.get_virtuals() (read) + apply_writes
            (write, background fields merged into the read config — the
            running effect type and every foreground/other param are left
            untouched). UNCONDITIONAL — not gated on bridge.is_playing(),
            unlike the "default" repaint below. That gate exists because a
            *snapshot* replay is stale by the time it's forced back; a
            fresh "set background to X now" write is authoritative the
            instant it lands, the same reason Dark's own dark_lock push is
            never gated either. If Light were gated on playback he could
            never see it work while his music plays — which is the whole
            point of building it.

  "default" (his word "hybrid" — legacy's own Default: "leave backgrounds
            alone so the scene's own authored colour set shows through").
            dark_lock=False, and restores the pre-dark snapshot the SAME
            way the old bool's "off" did — see the snapshot section below.
            This is legacy's actual Default semantics, at legacy's actual
            name; nothing here changed behaviourally from what the original
            build's "off" state did, only the label and the API/help text
            calling it what it is.

  Snapshot-and-restore, not re-fire-the-last-Color-Set (default only).
  Legacy's own unlock is ALSO not self-restoring (services/display_mode.py:
  "Unlocking restores nothing by itself") — routers/control.py's POST
  /display-mode repaints by re-firing state.last_color_group_id/
  last_color_set_id at advance=0. SPECTRA has no equivalent "the room's
  last-fired Color Set, replayable without reshuffling" concept at the
  room-control layer (that idea belongs to the same retired per-node
  authoring world). What SPECTRA captures instead, right before locking
  dark, is the LIVE per-virtual effect (type + config) actually read back
  from fx_seam.get_virtuals() — closer to ground truth than "replay the
  last authored card" would be, since it's what was REALLY showing, not
  what was last intentionally fired. Persisted to DARK_LIGHT_SNAPSHOT_FILE
  (survives a SPECTRA restart while dark) and replayed via
  fx_seam.apply_writes() on the transition to "default" — itself the exact
  write path a normal scene fire already uses — BUT ONLY WHEN NOTHING LIVE
  IS ABOUT TO REPAINT IT ANYWAY: bridge.is_playing() (spectra/services/
  bridge.py) gates the repaint. The snapshot is a still frame from the
  moment dark was engaged — while music is actively playing, forcing that
  stale frame back is the same shape of mistake as Ambient holding the
  room static through a song: it imposes a frozen look on a room that
  should be tracking live music, right as the room's own automatic driver
  (scene_change_mode / trigger_engine / drift) is about to repaint it for
  real. dark_lock still clears either way (nothing stays forced black);
  only the STALE repaint is skipped, reported as
  `repaint_skipped: "music_playing"` in the reconcile result. With no
  music playing (or paused — the room-proof's own condition), there is no
  live driver about to repaint it, so the snapshot restore is the only way
  back and proceeds as before. bridge.is_playing() is Optional[bool]
  (shared with ambient_music_gate.py — None means no signal has arrived
  at all yet, e.g. a fresh bridge before the first broadcast); ONLY a
  confirmed True skips the repaint (`is bridge.is_playing() is True`,
  not a truthy check dressed up as one — None is falsy in Python too, so
  the effect is the same, but the intent is spelled out). Unlike
  ambient_music_gate's own fail-safe direction (an unknown read carries
  the existing hold forward, never acts), this repaint has no continuous
  state to carry forward — it fires once per transition to "default" — so
  an unresolved read defaults to PROCEEDING with the repaint, the choice
  that guarantees the room visually recovers from dark, rather than to
  caution. The pre-dark snapshot is cleared on every transition AWAY from
  "dark" (to "light" or "default" alike) — Light immediately overwrites
  the background with its own forced write, so the stale snapshot has
  nothing left to restore into once Light has run.

Shielded devices ARE ported verbatim, and apply to BOTH Dark and Light
(legacy's own semantics — a shielded device keeps its authored background
in either forced mode): dark_light_shield_categories (default ["Singles"],
legacy's own default) / dark_light_shield_virtuals on RoomControlState,
resolved the same way services/display_mode.shielded_virtuals() does
(category name -> member virtuals via the shared registry,
fx/device_model.get_virtuals_for_category — read-only, SPECTRA doesn't own
device_categories.json). A shielded virtual is walked on every reconcile
same as legacy's loop (not skipped outright) so it always lands dark_lock
False and is excluded from the Light write, regardless of the room's mode —
"keeps its own look regardless."

Orthogonal to Ambient, exactly like legacy (services/ambient_mode.py has
zero display_mode references, confirmed by grep) — and, since 2026-08-15,
composes with Ambient's own binary toggle and its separate music-pause
switch (ambient_enabled/ambient_on_music_pause, spectra/services/
ambient_music_gate.py).
Not a coincidence to preserve here: whenever a Hue device is ACTUALLY
frozen right now — "always" unconditionally, or "auto" while playback
reads confirmed-not-playing — that device's stream is driven by direct
bridge REST (spectra/services/ambient.py), bypassing LedFX/dark_lock
entirely, so toggling dark mode has no visible effect on it. The moment
that device ISN'T frozen ("off", or "auto" while confirmed playing), it's
LedFX-rendered like any other virtual and responds to dark_lock normally.
This module never reads Ambient's own state to decide any of this — the
orthogonality is a property of the write path (a frozen device never
reaches LedFX's effect config at all), not a rule either feature encodes
about the other, the same "compose for free by construction" shape
ambient_music_gate.py's own docstring found for the selection kernel. It
only ever shows on devices LedFX is actually rendering (WLED etc., or a
Hue device that isn't currently frozen).

Measurement note (mirrors AGENTS.md's "Reading real Hue bulb state — don't
trust a raw CLIP light GET during a live entertainment stream" entry):
this module's own mechanism is LedFX-side — dark_lock + effect config on
/api/virtuals, read via fx_seam.get_virtuals() — never the Hue CLIP light
resource, which is Ambient's own instrument for a different subsystem
(REST-held bulbs, not a streamed scene). Verifying dark/light mode at the
bridges means reading LedFX's per-virtual state back, not the light
resource.

Verification is "read real state back," not "trust the POST" (the standing
lesson of every other partial-write defect this project has fixed — see
§51's Ambient confirmed-vs-attempted note): after pushing every dark_lock
change (and, in "light", every forced background write), one
fx_seam.get_virtuals() read confirms the ACTUAL resulting dark_lock per
virtual and, for Light, the actual background_color/background_brightness
landed on each written virtual; anything that doesn't match comes back
named in `unconfirmed`, never folded into a bigger "done" count.
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


async def reconcile(mode: str, shield_categories: list[str], shield_virtuals: list[str],
                    light_bg_color: str = "#201830",
                    light_bg_brightness: float = 0.3) -> dict:
    """Drive the room's display_mode to `mode` ("default" | "dark" |
    "light"). Locked so rapid switches / a shield-list edit racing a mode
    flip can't interleave and fight over the same snapshot. Never raises —
    a mid-handover refusal or an unreachable LedFX still leaves the
    room-control save itself succeeding (state is the durable record even
    when nothing could be driven live), same posture as ambient.reconcile()."""
    async with _get_lock():
        try:
            return await _reconcile_impl(mode, shield_categories, shield_virtuals,
                                         light_bg_color, light_bg_brightness)
        except fx_seam.RoomReleased:
            logger.warning("dark/light: room released — state saved, no lights touched")
            return {"status": "released"}
        except fx_seam.HandoverInProgress:
            logger.warning("dark/light: handover in flight — state saved, no lights touched")
            return {"status": "handover-in-progress"}
        except Exception as exc:
            logger.exception("dark/light: reconcile failed")
            return {"status": "failed", "error": str(exc)}


async def _reconcile_impl(mode: str, shield_categories: list[str],
                          shield_virtuals: list[str], light_bg_color: str,
                          light_bg_brightness: float) -> dict:
    from fx import device_model
    virtual_ids = device_model.get_all_virtual_ids()
    if not virtual_ids:
        return {"status": "no-devices"}
    shielded = _shielded_set(shield_categories, shield_virtuals)

    snapshot: dict = {}
    if mode == "dark":
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
        want = (mode == "dark") and vid not in shielded
        try:
            await fx_seam.set_virtual_config(vid, {"dark_lock": want})
        except Exception:
            logger.exception("dark/light: dark_lock push failed for '%s' (want %s)",
                             vid, want)

    restored: list[str] = []
    lit: list[str] = []
    repaint_skipped: Optional[str] = None

    if mode == "light":
        # THE forced state (see module docstring) — write the configured
        # background onto every non-shielded virtual's CURRENT live effect,
        # unconditionally. Not gated on bridge.is_playing(): a fresh
        # "set background to X now" write is authoritative the instant it
        # lands, unlike the stale snapshot the "default" branch below has
        # to gate.
        try:
            live = await fx_seam.get_virtuals()
        except Exception:
            logger.exception("dark/light: could not read live virtuals for the light write")
            live = {}
        writes = []
        for vid in virtual_ids:
            if vid in shielded:
                continue
            effect = (live.get(vid) or {}).get("effect") or {}
            effect_type = effect.get("type")
            if not effect_type:
                continue
            cfg = dict(effect.get("config") or {})
            cfg["background_color"] = light_bg_color
            cfg["background_brightness"] = light_bg_brightness
            writes.append({"virtual_id": vid, "effect_type": effect_type, "config": cfg})
        if writes:
            try:
                await fx_seam.apply_writes(writes, transition_ms=0)
                lit = [w["virtual_id"] for w in writes]
            except Exception:
                logger.exception("dark/light: forcing the light background failed")
        _clear_snapshot()
    elif mode == "default":
        if snapshot:
            from spectra.services.engine import bridge
            if bridge.is_playing() is True:
                # Music is live right now — the snapshot is a still frame
                # from the moment dark was engaged, already stale. Forcing
                # it back is the same mistake as Ambient holding the room
                # static through a song: it imposes a frozen look on a room
                # that should be tracking live music. Leave it to the
                # room's own automatic driver (scene_change_mode /
                # trigger_engine / drift) to repaint it on its own next
                # fire — dark_lock is already cleared above, so nothing is
                # left forced black, just not yet repainted.
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
    unconfirmed: set[str] = set()
    for vid in virtual_ids:
        want = (mode == "dark") and vid not in shielded
        actual = bool((live_after.get(vid) or {}).get("config", {}).get("dark_lock", False))
        if actual == want:
            if want:
                locked.append(vid)
        else:
            unconfirmed.add(vid)

    for vid in lit:
        cfg = ((live_after.get(vid) or {}).get("effect") or {}).get("config") or {}
        color_ok = cfg.get("background_color") == light_bg_color
        try:
            bright_ok = abs(float(cfg.get("background_brightness")) - light_bg_brightness) < 1e-6
        except (TypeError, ValueError):
            bright_ok = False
        if not (color_ok and bright_ok):
            unconfirmed.add(vid)

    result: dict = {
        "status": mode,
        "locked": sorted(locked),
        "shielded": sorted(shielded & set(virtual_ids)),
    }
    if mode == "default":
        result["restored"] = sorted(restored)
        if repaint_skipped:
            result["repaint_skipped"] = repaint_skipped
    if mode == "light":
        result["lit"] = sorted(lit)
    if unconfirmed:
        result["unconfirmed"] = sorted(unconfirmed)
        logger.error("dark/light: %d virtual(s) not confirmed for mode=%s: %s",
                     len(unconfirmed), mode, sorted(unconfirmed))
    return result
