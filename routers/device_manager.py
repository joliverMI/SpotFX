"""
SpotFX — Device Category API router.

Endpoints:
  GET    /api/device-categories                        — list all categories
  GET    /api/device-categories/{id}                   — get one category
  POST   /api/device-categories                        — create / update category
  DELETE /api/device-categories/{id}                   — delete category
  GET    /api/device-categories/import/ledfx-virtuals  — fetch virtuals from LedFX
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException

from models.device_category import DeviceCategory
from services.device_category_service import (
    list_categories, get_category, save_category, delete_category,
)

router = APIRouter(prefix="/api/device-categories", tags=["device-categories"])


@router.get("")
async def get_categories():
    return [c.model_dump() for c in list_categories()]


@router.get("/import/ledfx-virtuals")
async def import_ledfx_virtuals():
    """Fetch all virtuals from LedFX for the import picker."""
    from api.ledfx_client import get_all_virtuals
    raw = await get_all_virtuals()
    # LedFX wraps virtuals under a "virtuals" key
    virtual_dict = raw.get("virtuals", raw) if isinstance(raw, dict) else {}
    # Normalize to a simple list for the frontend
    virtuals = []
    for vid, info in virtual_dict.items():
        if not isinstance(info, dict):
            continue
        effect = info.get("effect", {})
        virtuals.append({
            "id": vid,
            "effect_type": effect.get("type", "") if isinstance(effect, dict) else "",
            "pixel_count": info.get("pixel_count", 0),
            "active": info.get("active", False),
        })
    return {"virtuals": virtuals}


@router.get("/{cat_id}")
async def get_category_by_id(cat_id: str):
    cat = get_category(cat_id)
    if cat is None:
        raise HTTPException(404, "Category not found")
    return cat.model_dump()


@router.post("")
async def upsert_category(cat: DeviceCategory):
    save_category(cat)
    return {"status": "saved", "id": cat.id}


@router.delete("/{cat_id}")
async def remove_category(cat_id: str):
    ok = delete_category(cat_id)
    if not ok:
        raise HTTPException(404, "Category not found")
    return {"status": "deleted"}
