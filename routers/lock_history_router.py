"""
SpotFX — Lock history API.

Serves the Timing page's lock-history panel: the last N distinct songs'
lock outcomes, full-text search over the stored history, and all plays of
one song. Data is recorded by services/lock_history.py from the xcorr
finalize path.
"""
from __future__ import annotations

from fastapi import APIRouter

from config import settings
from services import lock_history

router = APIRouter(prefix="/api/lock-history", tags=["lock-history"])


@router.get("/recent")
async def recent(limit: int = 10) -> dict:
    """Most recent lock per distinct song, newest first."""
    return {
        "entries": lock_history.recent_songs(limit=max(1, min(limit, 50))),
        "active_device": getattr(settings, "active_timing_device", "default"),
    }


@router.get("/search")
async def search(q: str = "", limit: int = 100) -> dict:
    """All stored entries matching `q` (title/artist/uri/device substring),
    newest first — repeated plays of a song each get their own row."""
    return {"entries": lock_history.search(q, limit=max(1, min(limit, 500)))}


@router.get("/song")
async def song(uri: str, limit: int = 50) -> dict:
    """Every recorded play of one song, newest first."""
    return {"entries": lock_history.entries_for_uri(uri, limit=max(1, min(limit, 500)))}
