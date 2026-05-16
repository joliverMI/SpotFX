"""
SpotFX — Morph API router.

Read-only endpoints for the Morph Step / Morph Set UI:
  GET /api/morph/aspects — Aspect catalog (ids, labels, per-effect param mapping, defaults)
"""
from fastapi import APIRouter

from services import morph_aspects

router = APIRouter(prefix="/api/morph", tags=["morph"])


@router.get("/aspects")
async def list_aspects():
    """Return the full Aspect catalog the builder UI needs to render Morph Step editors."""
    return morph_aspects.aspect_catalog()
