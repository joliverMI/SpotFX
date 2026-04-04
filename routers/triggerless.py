"""
SpotFX — Triggerless Play profile API router.

Endpoints:
  GET    /api/triggerless          -- list all triggerless profiles
  GET    /api/triggerless/{id}     -- get one profile
  POST   /api/triggerless          -- create / update profile
  DELETE /api/triggerless/{id}     -- delete profile
"""
from fastapi import APIRouter, HTTPException
from models.triggerless_profile import TriggerlessProfile
from services.profile_manager import (
    list_triggerless_profiles, get_triggerless_profile,
    save_triggerless_profile, delete_triggerless_profile,
)

router = APIRouter(prefix="/api/triggerless", tags=["triggerless"])


@router.get("")
async def get_all():
    return [p.model_dump() for p in list_triggerless_profiles()]


@router.get("/{profile_id}")
async def get_one(profile_id: str):
    p = get_triggerless_profile(profile_id)
    if p is None:
        raise HTTPException(404, "Triggerless profile not found")
    return p.model_dump()


@router.post("")
async def upsert(profile: TriggerlessProfile):
    save_triggerless_profile(profile)
    return {"status": "saved", "id": profile.id}


@router.delete("/{profile_id}")
async def remove(profile_id: str):
    ok = delete_triggerless_profile(profile_id)
    if not ok:
        raise HTTPException(404, "Triggerless profile not found")
    return {"status": "deleted"}
