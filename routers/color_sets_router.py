"""
SpotFX — Color Set API router.

  GET    /api/color-sets          — list all cards (Color Sets + Groups)
  GET    /api/color-sets/{id}     — get one card
  POST   /api/color-sets          — create / update a card
  DELETE /api/color-sets/{id}     — delete a card
  POST   /api/color-sets/import   — build a starter Color Set from live LedFX
                                    state of the given virtuals
  POST   /api/color-sets/{id}/fire — preview-fire a Set/Group immediately
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.color_set import ColorSetCard
from services import color_set_store, color_set_absorb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/color-sets", tags=["color_sets"])


class ImportRequest(BaseModel):
    virtual_ids: list[str] = []


@router.get("")
async def list_cards():
    return [c.model_dump() for c in color_set_store.list_all()]


@router.get("/{card_id}")
async def get_card(card_id: str):
    card = color_set_store.get_by_id(card_id)
    if card is None:
        raise HTTPException(404, "Color Set not found")
    return card.model_dump()


@router.post("")
async def upsert_card(card: ColorSetCard):
    color_set_store.save(card)
    return {"status": "saved", "id": card.id}


@router.delete("/{card_id}")
async def delete_card(card_id: str):
    if not color_set_store.delete(card_id):
        raise HTTPException(404, "Color Set not found")
    return {"status": "deleted"}


@router.post("/import")
async def import_card(body: ImportRequest):
    if not body.virtual_ids:
        raise HTTPException(400, "No virtuals selected")
    card = await color_set_absorb.import_color_set(body.virtual_ids)
    if card is None:
        raise HTTPException(404, "No importable color data on the selected devices")
    color_set_store.save(card)
    return {"id": card.id, "card": card.model_dump()}


@router.post("/{card_id}/fire")
async def fire_card(card_id: str):
    from main import engine
    ok = await engine.fire_color_set_now(card_id)
    if not ok:
        raise HTTPException(404, "Color Set not found or empty")
    return {"status": "fired"}
