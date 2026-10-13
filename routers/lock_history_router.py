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


# ── Whole-song check (services/whole_song_check.py) ──────────────────────────

@router.get("/whole-song")
async def whole_song(limit: int = 50, corrections_only: bool = False) -> dict:
    """Every end-of-play whole-song check, newest first — the corrections it
    made (song, old → new offset, windows won, median r) and the checks that
    left a song alone, with why. Also the live settings."""
    from config import settings
    from services import whole_song_check
    return {
        "entries": whole_song_check.recent(limit=max(1, min(limit, 300)),
                                           corrections_only=corrections_only),
        "settings": whole_song_check.current_settings(settings),
    }


@router.get("/whole-song/settings")
async def whole_song_settings() -> dict:
    from config import settings
    from services import whole_song_check
    return {"settings": whole_song_check.current_settings(settings),
            "spec": whole_song_check.SETTINGS}


@router.put("/whole-song/settings")
async def put_whole_song_settings(body: dict) -> dict:
    """Partial update: only the keys sent change. Validated against
    whole_song_check.SETTINGS, applied live, persisted to
    storage/settings.json. 422 names the first bad key."""
    from config import settings
    from routers import settings_router
    from services import whole_song_check
    try:
        patch = whole_song_check.validate_patch(body)
    except whole_song_check.SettingRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    previous = whole_song_check.current_settings(settings)
    stored = settings_router._load_settings_file()
    for k, v in patch.items():
        object.__setattr__(settings, k, v)
        stored[k] = v
    settings_router._save_settings_file(stored)
    return {"settings": whole_song_check.current_settings(settings),
            "previous": previous, "changed": sorted(patch)}
