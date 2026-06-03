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
import re
from typing import Optional

from api import ledfx_client
from models.color_set import ColorSetCard, ColorSetEntry
from models.music_event import MorphScope
from models.state import state
from services import morph_aspects
from services.scene_absorb import _register_scene_gradients, _load_gradients

logger = logging.getLogger(__name__)


def _normalize_gradient(css: str) -> Optional[tuple]:
    """Canonical, comparable form of a CSS gradient so visually-identical
    gradients match across formats (LedFX emits hex stops + 'NN.00%'; the
    SpotFX library saves rgb() stops + integer '%'). Returns (direction,
    ((r,g,b,pos), …)) or None if `css` isn't a gradient we can parse."""
    if not css or "gradient(" not in css:
        return None
    dm = re.search(r"linear-gradient\(\s*(\d+)deg", css)
    direction = int(dm.group(1)) if dm else 90
    stops: list[tuple] = []
    for m in re.finditer(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*([\d.]+)?%?", css):
        pos = round(float(m.group(4))) if m.group(4) else None
        stops.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), pos))
    for m in re.finditer(r"#([0-9a-fA-F]{6})\s*([\d.]+)?%?", css):
        h = m.group(1)
        pos = round(float(m.group(2))) if m.group(2) else None
        stops.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), pos))
    if not stops:
        return None
    return (direction, tuple(stops))


def _color_for_cfg(etype: str, cfg: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (color_kind, color_value) from the effect's color param, or
    (None, None) when absent. Falls back to LedFX's canonical `gradient` key
    so effects SpotFX doesn't model (e.g. crawler) still import their color."""
    candidates = list(morph_aspects.params_for_aspect(etype, "color")) + ["gradient"]
    for p in candidates:
        val = cfg.get(p)
        if isinstance(val, str) and val:
            kind = "gradient" if "gradient(" in val else "solid"
            return kind, val
    return None, None


def _bg_color_for_cfg(etype: str, cfg: dict) -> Optional[str]:
    """BG color from the effect's bg param, falling back to LedFX's canonical
    `background_color` key for unmodeled effects."""
    candidates = list(morph_aspects.params_for_aspect(etype, "bg_color")) + ["background_color"]
    for p in candidates:
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
            # background_mode is a LedFX base param present on most effects.
            cur = cfg.get("background_mode")
            bg_mode = cur if cur in ("additive", "overwrite") else None

        entries.append(ColorSetEntry(
            scope=MorphScope(virtual_ids=[vid]),
            color_kind=color_kind,
            color_value=color_value,
            bg_color=bg_color,
            bg_mode=bg_mode,
        ))

    if not entries:
        return None

    # Reuse a matching library gradient when one exists (normalized compare),
    # otherwise register the imported gradient as new — once per distinct
    # gradient so multiple devices sharing a gradient all reference one entry.
    existing_by_canon: dict[tuple, str] = {}
    for g in _load_gradients():
        canon = _normalize_gradient(g.get("value", ""))
        if canon and canon not in existing_by_canon:
            existing_by_canon[canon] = g["value"]

    new_by_canon: dict[tuple, str] = {}
    to_register: set[str] = set()
    for entry in entries:
        if entry.color_kind != "gradient" or not entry.color_value:
            continue
        canon = _normalize_gradient(entry.color_value)
        if canon and canon in existing_by_canon:
            entry.color_value = existing_by_canon[canon]      # reference existing
        elif canon and canon in new_by_canon:
            entry.color_value = new_by_canon[canon]           # share a freshly-seen one
        else:
            if canon:
                new_by_canon[canon] = entry.color_value
            to_register.add(entry.color_value)

    _register_scene_gradients("Import", to_register)

    return ColorSetCard(
        name="Imported Colors",
        kind="set",
        color="#FFD700",
        labels=["imported-colors"],
        entries=entries,
    )
