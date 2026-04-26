"""
SpotFX — Set List runtime overrides.

When a tracked Set List becomes the active context, apply its behavioural
overrides (auto_activate, auto_use_analyzed, genre_blending). When the
context leaves a Set List, restore the prior values from
`state.pre_setlist_state`. The override layer is intentionally light — it
mutates the same flags the engine already reads, so no other call site
needs to learn about Set Lists.
"""
from __future__ import annotations
import logging

from config import settings
from models.state import state
from services import setlist_store

logger = logging.getLogger(__name__)


def apply_for_context(context_uri: str) -> None:
    sl = setlist_store.get_by_context_uri(context_uri) if context_uri else None
    target_id = sl.id if sl else ""

    # No change in active Set List? Nothing to do.
    if state.active_setlist_id == target_id:
        return

    # Leaving a Set List → restore prior toggles.
    if state.active_setlist_id and state.pre_setlist_state:
        _restore()

    # Entering a new Set List → snapshot + override.
    if sl is not None:
        _snapshot()
        _apply(sl)
        state.active_setlist_id = sl.id
        logger.info(
            "Set List active: %s (auto_activate=%s, auto_use_analyzed=%s, genre_blending=%s)",
            sl.name, sl.auto_activate, sl.auto_use_analyzed, sl.genre_blending,
        )
    else:
        state.active_setlist_id = ""


def active_setlist():
    """Return the currently-active Setlist (or None)."""
    return setlist_store.get_by_id(state.active_setlist_id) if state.active_setlist_id else None


# ── internal ────────────────────────────────────────────────────────────────

def _snapshot() -> None:
    state.pre_setlist_state = {
        "paused": state.paused,
        "use_analyzed_triggerless": state.use_analyzed_triggerless,
        "genre_blending_enabled": settings.genre_blending_enabled,
    }


def _restore() -> None:
    snap = state.pre_setlist_state or {}
    if "paused" in snap:
        state.paused = bool(snap["paused"])
    if "use_analyzed_triggerless" in snap:
        state.use_analyzed_triggerless = bool(snap["use_analyzed_triggerless"])
    if "genre_blending_enabled" in snap:
        # `settings` is a Pydantic BaseSettings, override via object.__setattr__
        # mirroring the toggle endpoint in main.py.
        object.__setattr__(settings, "genre_blending_enabled", bool(snap["genre_blending_enabled"]))
    state.pre_setlist_state = {}


def _apply(sl) -> None:
    if sl.auto_activate and state.paused:
        state.paused = False
    if sl.auto_use_analyzed:
        state.use_analyzed_triggerless = True
    if sl.genre_blending == "on":
        object.__setattr__(settings, "genre_blending_enabled", True)
    elif sl.genre_blending == "off":
        object.__setattr__(settings, "genre_blending_enabled", False)
    # "global" → don't touch
