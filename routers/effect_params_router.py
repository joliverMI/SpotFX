"""
SpotFX — Effect parameter config API.
Serves the effect_params registry to the frontend.
"""
from typing import Optional
from fastapi import APIRouter
from services import effect_params

router = APIRouter(prefix="/api/effect-params", tags=["effect-params"])


@router.get("/config")
async def get_config():
    """Return the effect_params config with `categories` swapped for the LIVE
    device categories (storage/device_categories.json) — the static section in
    config/effect_params.json is only the one-time seed and goes stale as soon
    as categories are edited on the Devices page. Scope pickers and the Color
    Set import dialog all populate from this endpoint."""
    from services.device_category_service import list_categories
    cfg = dict(effect_params._CONFIG)
    cfg["categories"] = {
        c.name: {"id": c.id, "parent_id": c.parent_id, "role": c.role,
                 "virtuals": c.virtuals, "effects": c.effects}
        for c in sorted(list_categories(), key=lambda c: c.sort_order)
    }
    return cfg


@router.get("/labels")
async def get_labels(category: Optional[str] = None):
    """Return available labels (numeric/toggle only).
    If category is given, returns labels for that category's effects.
    Otherwise returns all labels across all effects.
    """
    if category:
        return effect_params.get_labels_for_category(category)
    return effect_params.get_all_labels()
