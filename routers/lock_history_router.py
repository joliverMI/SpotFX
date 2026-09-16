"""
SpotFX — Lock history API.

Serves the Timing page's lock-history panel: the last N distinct songs'
lock outcomes, full-text search over the stored history, and all plays of
one song. Data is recorded by services/lock_history.py from the xcorr
finalize path.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services import lock_history

router = APIRouter(prefix="/api/lock-history", tags=["lock-history"])


@router.get("/recent")
async def recent(limit: int = 10) -> dict:
    """Most recent lock per distinct song, newest first."""
    return {
        "entries": lock_history.recent_songs(limit=max(1, min(limit, 50))),
    }


@router.get("/search")
async def search(q: str = "", limit: int = 100) -> dict:
    """All stored entries matching `q` (title/artist/uri substring),
    newest first — repeated plays of a song each get their own row."""
    return {"entries": lock_history.search(q, limit=max(1, min(limit, 500)))}


@router.get("/song")
async def song(uri: str, limit: int = 50) -> dict:
    """Every recorded play of one song, newest first."""
    return {"entries": lock_history.entries_for_uri(uri, limit=max(1, min(limit, 500)))}


@router.get("/drift")
async def drift() -> dict:
    """Pipeline-drift instrument: per listening session, the LEVEL of each
    play's winning offset vs that song's own FIXED, quality-gated anchor —
    the common component a pipeline-level latency change leaves across a
    whole session, which per-song saves otherwise quietly absorb. Also
    carries the legacy sliding-baseline `median_residual_ms` for continuity
    (see services/lock_history.pipeline_drift's docstring for why it reads
    change, not level). Drives the Timing page's drift line, its alarm, and
    its per-session ramp/step/stable shape."""
    return lock_history.pipeline_drift()


@router.get("/drift/reanchor-preview")
async def reanchor_preview(start_at: str) -> dict:
    """What re-anchoring the drift instrument at `start_at` would adopt —
    the new era, the one it replaces, and how far the anchors would move.
    Writes nothing."""
    try:
        return lock_history.preview_reanchor(start_at)
    except lock_history.ReanchorRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class ReanchorBody(BaseModel):
    start_at: str
    by: str
    reason: str
    confirm: bool = False


@router.post("/drift/reanchor")
async def reanchor(body: ReanchorBody, request: Request) -> dict:
    """Adopt a new drift anchor era ON PURPOSE. Nothing automatic ever calls
    this; the era otherwise never moves. Requires `confirm: true` plus who
    (`by`) and why (`reason`), all kept in the anchors store's audit trail
    and logged. Preview first with GET /drift/reanchor-preview."""
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="re-anchoring replaces every song's drift anchor — send confirm: true "
                   "(preview with GET /api/lock-history/drift/reanchor-preview first)")
    client: Optional[str] = request.client.host if request.client else None
    try:
        return lock_history.reanchor(start_at=body.start_at, by=body.by,
                                     reason=body.reason, client=client)
    except lock_history.ReanchorRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc))
