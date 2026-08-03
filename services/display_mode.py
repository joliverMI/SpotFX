"""
SpotFX — Dark / Light display mode.

One room-wide mode ("dark" | "light" | none), decided by a seven-level
cascade where the FIRST level that isn't "default" wins:

  1. Global TopBar toggle          state.display_mode
  2. Trigger                       MusicTrigger.display_mode  (via ContextVar)
  3. Active scene group            MusicEvent.display_mode    (scene_group)
  4. Current scene                 MusicEvent.display_mode    (scene_update)
  5. Set Color action              SetColorAction.display_mode
  6. Color Group card              ColorSetCard.display_mode  (kind="group")
  7. Color Set card                ColorSetCard.display_mode  (kind="set")

What the resolved mode does (only on non-shielded devices):
  dark  — every background is forced black. SpotFX blanks bg values at the
          set_color seam AND flips a per-virtual `dark_lock` flag in LedFX,
          which hard-clamps background_color/#000000 + background_brightness/0
          inside Effect._apply_config — so writes from ANY path (tweens, morph
          steps, scenes, presets) can't light a background while dark.
  light — entries keep their authored bg; entries WITHOUT one get the default
          light background (settings.display_light_bg_color / _brightness).

Shielded devices (settings.display_shield_categories by category NAME +
settings.display_shield_virtuals by id; default: the "Singles" category)
always keep their authored backgrounds in both modes.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import settings
from models.state import state

logger = logging.getLogger(__name__)

Mode = str  # "default" | "dark" | "light"


def resolve(*modes: Optional[str]) -> Mode:
    """Walk the cascade top-down; the first "dark"/"light" wins.

    None / "" / "default" defer; unknown strings are skipped defensively.
    Returns "default" when every level defers (= leave backgrounds alone).
    """
    for m in modes:
        if m in ("dark", "light"):
            return m
    return "default"


def group_and_scene_modes() -> tuple[Mode, Mode]:
    """Levels 3 & 4 read from shared state: (active scene group's mode,
    current scene's mode). Cheap enough to call per fire — get_event parses
    from the profile_manager's raw-events cache."""
    from services.profile_manager import get_event

    group_mode = "default"
    gid = state.active_scene_group_id
    if gid:
        grp = get_event(gid)
        if grp is not None and grp.event_type == "scene_group":
            group_mode = grp.display_mode

    scene_mode = "default"
    sid = state.last_scene_update_id
    if sid:
        scn = get_event(sid)
        if scn is not None and scn.event_type == "scene_update":
            scene_mode = scn.display_mode

    return group_mode, scene_mode


def shielded_virtuals() -> set[str]:
    """Virtual ids exempt from both dark forcing and the light default bg."""
    from services import device_category_service

    out: set[str] = {str(v) for v in (settings.display_shield_virtuals or [])}
    for name in settings.display_shield_categories or []:
        cat = device_category_service.get_category_by_name(str(name))
        if cat is not None:
            out.update(cat.virtuals)
    return out


_HEX_RE = None


def visible_bg_fallback(color_value: Optional[str]) -> str:
    """A background color guaranteed to be visible, for rescuing shielded
    devices from authored black backgrounds: prefer the entry's own FG color
    (solid hex, or the first parseable stop of a gradient) so the glow stays
    palette-coherent; fall back to the configured light default."""
    global _HEX_RE
    import re
    if _HEX_RE is None:
        _HEX_RE = (re.compile(r"#[0-9a-fA-F]{6}\b"),
                   re.compile(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)"))
    cv = (color_value or "").strip()
    m = _HEX_RE[0].search(cv)
    if m and m.group(0).lower() != "#000000":
        return m.group(0)
    m = _HEX_RE[1].search(cv)
    if m:
        rgb = tuple(min(255, int(x)) for x in m.groups())
        if any(rgb):
            return "#%02x%02x%02x" % rgb
    return settings.display_light_bg_color


def is_black(color: Optional[str]) -> bool:
    return (color or "").strip().lower() in ("#000000", "#000", "black")


# ── LedFX dark-lock sync ─────────────────────────────────────────────────────
# Last dark_lock value confirmed pushed per virtual. Empty after a SpotFX
# restart → the first sync re-pushes everything (self-healing). LedFX persists
# the flag in its own config, so an LedFX restart keeps locks without us.
_pushed: dict[str, bool] = {}
_sync_gate: asyncio.Lock | None = None


def _gate() -> asyncio.Lock:
    global _sync_gate
    if _sync_gate is None:
        _sync_gate = asyncio.Lock()
    return _sync_gate


async def sync_dark_locks(resolved_mode: Mode) -> None:
    """Reconcile every owned virtual's LedFX dark_lock with the resolved mode.

    Locked = mode is dark AND the virtual isn't shielded. Only virtuals whose
    desired state differs from the last confirmed push are touched, so calling
    this on every fire is ~free in steady state."""
    from api import ledfx_client
    from services import effect_params

    state.display_mode_resolved = resolved_mode if resolved_mode in ("dark", "light") else "default"
    dark = resolved_mode == "dark"
    shields = shielded_virtuals()
    async with _gate():
        for vid in effect_params.get_all_virtual_ids():
            want = dark and vid not in shields
            if _pushed.get(vid) == want:
                continue
            if await ledfx_client.set_virtual_dark_lock(vid, want):
                _pushed[vid] = want
            else:
                logger.warning("dark_lock push failed for '%s' (want %s)", vid, want)


def sync_dark_locks_bg(resolved_mode: Mode) -> None:
    """Fire-and-forget wrapper for call sites inside the fire path."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(sync_dark_locks(resolved_mode))


def resync() -> None:
    """Forget confirmed pushes and reconcile from scratch — call after the
    shield settings change so newly (un)shielded virtuals get updated."""
    _pushed.clear()
    sync_dark_locks_bg(state.display_mode_resolved)
