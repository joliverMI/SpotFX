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
