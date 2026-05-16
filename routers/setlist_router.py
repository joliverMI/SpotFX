"""
SpotFX — Set List CRUD router.

GET    /api/setlists                     — list all
POST   /api/setlists                     — create or update (id required for update)
DELETE /api/setlists/{id}                — delete
GET    /api/setlists/by-context?uri=...  — lookup by Spotify context URI
GET    /api/setlists/discoverable        — playlists SpotFX has seen recently but isn't tracking
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, HTTPException

from models.setlist import Setlist
from models.state import state
from services import setlist_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setlists", tags=["setlists"])


@router.get("")
async def list_setlists():
    return [s.model_dump() for s in setlist_store.list_all()]


@router.post("")
async def upsert_setlist(setlist: Setlist):
    setlist_store.save(setlist)
    return setlist.model_dump()


@router.delete("/{setlist_id}")
async def delete_setlist(setlist_id: str):
    if not setlist_store.delete(setlist_id):
        raise HTTPException(404, "Set List not found")
    return {"ok": True}


@router.get("/by-context")
async def by_context(uri: str):
    sl = setlist_store.get_by_context_uri(uri)
    return sl.model_dump() if sl else None


@router.get("/{setlist_id}/drift")
async def drift_for_setlist(setlist_id: str):
    """Songs whose stored offset for this Set List has been anti-correlated
    on recent plays (anti_corr_count >= 2). Surfaces in the Set List page so
    the user knows which entries to re-tune."""
    from config import AUDIO_SHAPES_DIR
    import json
    out = []
    for path in AUDIO_SHAPES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entry = (data.get("setlist_offsets") or {}).get(setlist_id)
        if not entry:
            continue
        n = int(entry.get("anti_corr_count") or 0)
        if n >= 2:
            out.append({
                "uri": data.get("spotify_uri"),
                "title": data.get("title"),
                "artist": data.get("artist"),
                "anti_corr_count": n,
                "last_anti_corr_at": entry.get("last_anti_corr_at"),
                "stored_offset_ms": entry.get("timestamp_offset_ms"),
            })
    out.sort(key=lambda r: r["anti_corr_count"], reverse=True)
    return out


@router.get("/discoverable")
async def discoverable():
    """Return context URIs SpotFX has observed but isn't tracking yet, so the
    UI can offer one-click "track this playlist as a Set List"."""
    seen = list((state.observed_context_uris or {}).items())
    tracked = {s.context_uri for s in setlist_store.list_all() if s.context_uri}
    return [
        {"context_uri": uri, "name": name}
        for uri, name in seen
        if uri and uri not in tracked
    ]
