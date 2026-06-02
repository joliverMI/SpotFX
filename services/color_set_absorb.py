"""
SpotFX — live LedFX state → starter Color Set importer.

Given a list of virtual ids the user picked, read each one's CURRENT effect
config from live LedFX and build a Color Set card with one entry per virtual,
capturing FG color (gradient/solid), BG color, and background mode. Gradients
encountered are auto-registered into the SpotFX gradient library so the editor
dropdown can show them.

Mirrors services/scene_absorb.py but reads `GET /api/virtuals` (live) instead
of a saved scene, and produces ColorSetEntry objects rather than MorphTargets.
"""
from __future__ import annotations

import logging
from typing import Optional

from api import ledfx_client
from models.color_set import ColorSetCard, ColorSetEntry
from models.music_event import MorphScope
from models.state import state
from services import morph_aspects
from services.effect_params import get_param_meta
from services.scene_absorb import _register_scene_gradients

logger = logging.getLogger(__name__)


def _color_for_cfg(etype: str, cfg: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (color_kind, color_value) from the effect's color param, or
    (None, None) when absent."""
    for p in morph_aspects.params_for_aspect(etype, "color"):
        val = cfg.get(p)
        if isinstance(val, str) and val:
            kind = "gradient" if "gradient(" in val else "solid"
            return kind, val
    return None, None


def _bg_color_for_cfg(etype: str, cfg: dict) -> Optional[str]:
    for p in morph_aspects.params_for_aspect(etype, "bg_color"):
        val = cfg.get(p)
        if isinstance(val, str) and val:
            return val
    return None


async def _read_virtual(vid: str) -> dict:
    """Current state for one virtual, working even while audio capture is in
    progress (when get_all_virtuals() returns nothing). Prefers the engine's
    polled cache, then falls back to a single get_virtual() — which itself
    returns the cache during capture."""
    rec = state.ledfx_virtual_cache.get(vid)
    if isinstance(rec, dict) and (rec.get("effect") or {}).get("type"):
        return rec
    live = await ledfx_client.get_virtual(vid) or {}
    # get_virtual returns {vid: record} when read live, or the bare record
    # (from cache) during capture.
    return live.get(vid, live) if isinstance(live, dict) else {}


async def import_color_set(virtual_ids: list[str]) -> Optional[ColorSetCard]:
    """Build a starter Color Set with one entry per selected virtual.

    Each entry is pre-filled with whatever FG/BG color the device is currently
    showing; devices with no current color (e.g. a radial effect) still get an
    empty scaffold entry so the user can assign colors to them. Returns None
    only if no virtuals were selected. One entry is created per selected id
    regardless of whether it currently has color data, so the user gets a
    full scaffold to edit."""
    entries: list[ColorSetEntry] = []
    seen_gradients: set[str] = set()

    for vid in virtual_ids:
        rec = await _read_virtual(vid)
        eff = (rec or {}).get("effect") or {}
        etype = eff.get("type")
        cfg = eff.get("config") or {}

        # Read current color data when the active effect exposes it; leave
        # unset otherwise. Either way we still emit an entry for this device.
        color_kind = color_value = bg_color = bg_mode = None
        if etype:
            color_kind, color_value = _color_for_cfg(etype, cfg)
            bg_color = _bg_color_for_cfg(etype, cfg)
            if get_param_meta(etype, "background_mode") is not None:
                cur = cfg.get("background_mode")
                bg_mode = cur if cur in ("additive", "overwrite") else None

        if color_kind == "gradient" and color_value:
            seen_gradients.add(color_value)

        entries.append(ColorSetEntry(
            scope=MorphScope(virtual_ids=[vid]),
            color_kind=color_kind,
            color_value=color_value,
            bg_color=bg_color,
            bg_mode=bg_mode,
        ))

    if not entries:
        return None

    _register_scene_gradients("Import", seen_gradients)

    return ColorSetCard(
        name="Imported Colors",
        kind="set",
        color="#FFD700",
        labels=["imported-colors"],
        entries=entries,
    )
