"""
SpotFX — AI Suggestion Set router.

GET    /api/ai-suggestions              — list all saved sets (metadata only)
GET    /api/ai-suggestions/{track_id}   — get full suggestion set
PUT    /api/ai-suggestions/{track_id}   — create or replace suggestion set
DELETE /api/ai-suggestions/{track_id}   — delete suggestion set
"""
from fastapi import APIRouter, HTTPException

from models.ai_suggestion_set import AISuggestionSet
from services.suggestion_store import (
    list_suggestion_sets,
    load_suggestion_set,
    save_suggestion_set,
    delete_suggestion_set,
)

router = APIRouter(prefix="/api/ai-suggestions", tags=["ai-suggestions"])


@router.get("")
async def list_sets():
    return list_suggestion_sets()


@router.get("/{track_id}")
async def get_set(track_id: str):
    s = load_suggestion_set(track_id)
    if not s:
        raise HTTPException(status_code=404, detail="Suggestion set not found")
    return s


@router.put("/{track_id}")
async def put_set(track_id: str, body: AISuggestionSet):
    save_suggestion_set(body)
    return {"status": "saved", "track_id": track_id}


@router.delete("/{track_id}")
async def delete_set(track_id: str):
    ok = delete_suggestion_set(track_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Suggestion set not found")
    return {"status": "deleted"}
