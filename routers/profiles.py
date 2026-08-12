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


class IntensityScalePatch(BaseModel):
    intensity_scale: float | None = None   # 0-2 (0-200%); ignored when clear=True
    clear: bool = False                    # True → unset (fall back to genre/auto)


@router.get("/intensity-scale")
async def get_intensity_scale(uri: str):
    """Resolved intensity scale for a song: stored value + source, the genre
    fallback, and the effective multiplier the engine will use."""
    profile = load_profile_by_uri(uri)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    from services.intensity_scale_service import resolve_genre_scale
    genres = list(profile.artist_genre or [])
    if not genres and state.current_track and state.current_track.spotify_uri == uri:
        genres = list(state.current_track.genres or [])
    # Song-space value (the genre slider is a relative dial — see
    # intensity_scale_service.genre_to_song_scale).
    genre_default = round(resolve_genre_scale(genres), 3)
    effective = (profile.intensity_scale
                 if profile.intensity_scale is not None else genre_default)
    return {
        "intensity_scale": profile.intensity_scale,
        "source": profile.intensity_scale_source,
        "genre_default": genre_default,
        "effective": max(0.0, min(2.0, effective)),
    }


@router.patch("/by-uri")
async def patch_profile_by_uri(uri: str, body: IntensityScalePatch):
    """Set (source="user") or clear the song's intensity scaler. Pokes the
    engine's in-memory profile so it's live without waiting for a poll."""
    profile = load_profile_by_uri(uri)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    if body.clear:
        profile.intensity_scale = None
        profile.intensity_scale_source = None
    elif body.intensity_scale is not None:
        profile.intensity_scale = max(0.0, min(2.0, float(body.intensity_scale)))
        profile.intensity_scale_source = "user"
    else:
        raise HTTPException(422, "intensity_scale or clear required")
    save_profile(profile)
    from main import engine
    if engine._profile and engine._profile.spotify_uri == uri:
        engine._profile.intensity_scale = profile.intensity_scale
        engine._profile.intensity_scale_source = profile.intensity_scale_source
        engine._genre_scale_uri = None  # re-resolve the genre fallback next fire
    return {"status": "saved", "intensity_scale": profile.intensity_scale,
            "source": profile.intensity_scale_source}


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
