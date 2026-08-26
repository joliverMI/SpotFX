"""
SpotFX — Song Profile API router.

Endpoints:
  GET    /api/profiles              — list all profiles
  GET    /api/profiles/by-uri?uri=  — load by Spotify URI
  POST   /api/profiles              — create / update profile
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.song_profile import SongProfile
from models.state import state
from services import spectra_trigger_sync_client
from services.profile_manager import (
    list_profiles, load_profile_by_uri, save_profile,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
async def get_profiles():
    return list_profiles()


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
    engine's in-memory profile so it's live without waiting for a poll.

    DELIBERATELY NOT trigger-synced: this writes ONE profile-level scalar and
    never touches `triggers`, so the fired copy (storage/spectra/triggers.json)
    holds nothing this edit could make stale. See upsert_profile below for the
    hook every trigger-writing path does run."""
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


@router.post("")
async def upsert_profile(profile: SongProfile):
    """THE save path for the Profile Builder timeline — his "Timeline of
    Spectra" (/spectra/timeline) and the legacy /app builder both land here.

    Since 2026-08-24 the save ALSO lands this song's authored triggers in the
    copy SPECTRA actually fires from (storage/spectra/triggers.json), which is
    what makes an edit reach his show instead of only the editor's own file —
    see services/spectra_trigger_sync_client.py and spectra/services/
    profile_trigger_sync.py. Best-effort: the profile is already on disk, so a
    SPECTRA that is down reports `spectra_sync.status != "ok"` here rather
    than failing his save, and the deploy-time catch-up repairs it."""
    save_profile(profile)
    sync = await spectra_trigger_sync_client.sync_profile(profile)
    return {"status": "saved", "filename": profile.filename, "spectra_sync": sync}
