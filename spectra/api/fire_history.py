"""SPECTRA fire-history read surface — the counter, not analytics
(deliberately scoped out: no UI beyond this endpoint).

  GET /api/fire-history  — the four buckets (scenes/responses/color_sets/
                           triggers), each key -> {count, first_fire_ms,
                           last_fire_ms}. See services/fire_history.py for
                           what populates each bucket.
"""
from __future__ import annotations

from fastapi import APIRouter

from spectra.services import fire_history

router = APIRouter(prefix="/api", tags=["spectra-fire-history"])


@router.get("/fire-history")
async def get_fire_history():
    return fire_history.load_all()
