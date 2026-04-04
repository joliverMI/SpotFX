"""
SpotFX — Song Profile API router.

Endpoints:
  GET    /api/profiles              — list all profiles
  GET    /api/profiles/current      — profile for currently playing track
  GET    /api/profiles/by-uri?uri=  — load by Spotify URI
  GET    /api/profiles/{filename}   — load one profile
  POST   /api/profiles              — create / update profile
  DELETE /api/profiles              — delete by spotify URI
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.song_profile import SongProfile
from models.state import state
from services.profile_manager import (
    list_profiles, load_profile_by_uri, load_profile_by_filename,
    save_profile, delete_profile, get_event_map,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
async def get_profiles():
    return list_profiles()


@router.get("/current")
async def get_current_profile():
    """Return the profile for the currently playing track, with events joined."""
    track = state.current_track
    if track is None:
        raise HTTPException(404, "Nothing playing")
    profile = load_profile_by_uri(track.spotify_uri)
    if profile is None:
        raise HTTPException(404, "No profile for current track")
    events = get_event_map()
    data = profile.model_dump()
    for t in data.get("triggers", []):
        ev = events.get(t.get("event_id", ""))
        t["event_name"] = ev["name"] if ev else "?"
        t["event_color"] = ev["color"] if ev else "#888"
    return data


@router.get("/by-uri")
async def get_profile_by_uri(uri: str):
    profile = load_profile_by_uri(uri)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    return profile.model_dump()


@router.get("/{filename}")
async def get_profile(filename: str):
    profile = load_profile_by_filename(filename)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    return profile.model_dump()


@router.post("")
async def upsert_profile(profile: SongProfile):
    save_profile(profile)
    return {"status": "saved", "filename": profile.filename}


@router.delete("")
async def remove_profile(uri: str):
    ok = delete_profile(uri)
    if not ok:
        raise HTTPException(404, "Profile not found")
    return {"status": "deleted"}
