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
    """Return the full effect_params config (categories + effects)."""
    return effect_params._CONFIG


@router.get("/labels")
async def get_labels(category: Optional[str] = None):
    """Return available labels (numeric/toggle only).
    If category is given, returns labels for that category's effects.
    Otherwise returns all labels across all effects.
    """
    if category:
        return effect_params.get_labels_for_category(category)
    return effect_params.get_all_labels()
