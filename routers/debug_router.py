"""
SpotFX — Debug API router.

Endpoints used exclusively by the Advanced-Mode-only /debug.html page.
Kept separate from audio_shape_router so removing the page (or hiding it
in non-advanced installs) is a one-import change in main.py.
"""
from fastapi import APIRouter, Query

from services.auto_offset_service import auto_offset_service

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/xcorr-frames")
async def xcorr_frames(uri: str = Query(...)):
    """Return the most recent xcorr-captured frames for `uri`. Empty arrays
    when xcorr is not currently watching this URI (the matcher has gone idle
    after lock-and-stop, or no xcorr task is running). The Debug page polls
    this every ~1.5s to render the live shape overlay."""
    return auto_offset_service.get_live_frames(uri)
