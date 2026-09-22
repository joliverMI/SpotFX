"""SPECTRA registry + read-only bridge reads.

  GET /api/registry     — device categories + effect param registry (the
      shared fx/device_model truth), shaped like spot-effects'
      /effect-params/config so editor logic ports cleanly
  GET /api/color-sets   — read-only Colour Set projection (id/name/kind/
      opt-out) for the Colour Sets tab; the global opt-out TOGGLE goes
      through the spot-effects API from the frontend (its own supported
      surface) — SPECTRA's backend never writes spot-effects storage
"""
from __future__ import annotations

from fastapi import APIRouter

from fx import device_model
from spectra.services import color_sets

router = APIRouter(prefix="/api", tags=["spectra-registry"])


@router.get("/registry")
async def get_registry():
    cats = {
        c["name"]: {
            "id": c["id"],
            "parent_id": c.get("parent_id"),
            "virtuals": c.get("virtuals", []),
            # curated names first, then every registered effect whose own
            # device dimension matches this category's — the curated list
            # alone is a hand-maintained shortlist that drifts behind the
            # registry (device_model.category_effect_options's docstring).
            "effects": device_model.category_effect_options(c["name"]),
        }
        for c in device_model.list_categories()
    }
    effects = {
        etype: {"params": device_model.effect_params(etype)}
        for etype in device_model.effect_types()
    }
    return {"categories": cats, "effects": effects}


@router.get("/color-sets")
async def get_color_sets():
    return [c.model_dump() for c in color_sets.list_all()]
