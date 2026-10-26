"""
SpotFX — Song Profile API router.

Endpoints:
  GET    /api/profiles              — list all profiles
  GET    /api/profiles/by-uri?uri=  — load by Spotify URI
  POST   /api/profiles              — create / update profile
  GET    /api/profiles/triggers/provenance?uri=
                                    — his charge/lull/drop triggers: each
                                      one placed by hand or imported
  POST   /api/profiles/triggers/edit
                                    — the narrow phase-trigger edit (Home's
                                      Drops panel): remove / delete /
                                      disable / enable / move / restore;
                                      services/profile_trigger_edit.py
"""
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.song_profile import SongProfile
from models.state import state
from services import (profile_trigger_edit, profile_trigger_sync_queue,
                      spectra_trigger_sync_client)
from services.profile_manager import (
    list_profiles, load_profile_by_uri, profile_path_for_uri, save_profile,
    write_profile_raw,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# ── the narrow phase-trigger edit (services/profile_trigger_edit.py) ───────

def _raw_profile(uri: str) -> tuple[Any, dict, bool]:
    path = profile_path_for_uri(uri)
    if path is None:
        raise HTTPException(404, "Profile not found")
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:                             # noqa: BLE001
        raise HTTPException(422, f"this song's profile cannot be read: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(422, "this song's profile is not an object")
    return path, data, profile_trigger_edit.file_is_ascii(raw)


@router.get("/triggers/provenance")
async def get_trigger_provenance(uri: str):
    """His charge/lull/drop triggers in this song's profile, each one placed
    by hand or imported, and what Remove would do to it (delete / disable).
    Read-only."""
    _path, data, _ascii = _raw_profile(uri)
    return profile_trigger_edit.provenance(data)


class _Move(BaseModel):
    id: str = Field(..., min_length=1)
    timestamp_ms: int


class _Restore(BaseModel):
    id: str = Field(..., min_length=1)
    # `from`/`to` are reserved words in Python — aliased on the wire
    from_: Optional[dict] = Field(default=None, alias="from")
    to: Optional[dict] = None
    index: Optional[int] = None

    model_config = {"populate_by_name": True}


class TriggerEditBody(BaseModel):
    uri: str = Field(..., min_length=1)
    remove: list[str] = Field(default_factory=list)
    delete: list[str] = Field(default_factory=list)
    disable: list[str] = Field(default_factory=list)
    enable: list[str] = Field(default_factory=list)
    move: list[_Move] = Field(default_factory=list)
    restore: list[_Restore] = Field(default_factory=list)


@router.post("/triggers/edit")
async def post_trigger_edit(body: TriggerEditBody):
    """The one narrow write to his charge/lull/drop triggers other than a
    Timeline save (Home's Drops panel, Sonic). Patches the RAW profile in
    place (no model round-trip), writes it atomically, runs the whole-song
    sync so the fired copy follows (a deletion included — all of his phase
    triggers are in the sync ledger), tells every open Timeline the song
    changed (`profile_triggers_changed`), and answers every row it changed
    as it was and as it is: the undo record. The sync is the whole-song one
    a Timeline save runs, so it also lands any earlier profile edit of this
    song that had not reached the fired copy yet (the profile wins, the
    sync's own standing rule). Refuses an unknown id (404),
    a trigger that is not a charge/lull/drop (422) and a stale restore
    (409), writing nothing."""
    path, data, ascii_file = _raw_profile(body.uri)
    edit = profile_trigger_edit.Edit(
        remove=list(body.remove), delete=list(body.delete), disable=list(body.disable),
        enable=list(body.enable), move=[m.model_dump() for m in body.move],
        restore=[{"id": r.id, "from": r.from_, "to": r.to, "index": r.index}
                 for r in body.restore])
    try:
        changes = profile_trigger_edit.apply(data, edit)
    except profile_trigger_edit.TriggerNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except profile_trigger_edit.EditRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except profile_trigger_edit.RestoreConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if not changes:
        return {"status": "unchanged", "changed": [], "spectra_sync": None}
    write_profile_raw(path, data, ensure_ascii=ascii_file)
    profile = load_profile_by_uri(body.uri)
    sync: dict = {"status": "skipped", "reason": "profile could not be reloaded"}
    if profile is not None:
        sync = await spectra_trigger_sync_client.sync_profile(profile)
        if sync.get("status") == "ok":
            profile_trigger_sync_queue.clear(profile.spotify_uri)
    try:
        from services.websocket_manager import ws_manager
        await ws_manager.broadcast({"type": "profile_triggers_changed", "uri": body.uri,
                                    "ids": [c["id"] for c in changes]})
    except Exception:                                    # noqa: BLE001
        pass                     # telling the Timeline must never fail the edit
    return {"status": "saved", "changed": changes, "spectra_sync": sync}


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
    # THE ONE whole-song sync: an explicit save is his deliberate act, so his
    # deletions land here (and only here). Every AUTOMATIC writer is
    # upsert-only. Retiring the mark on success keeps the background drain
    # from repeating a song this response already reported on.
    sync = await spectra_trigger_sync_client.sync_profile(profile)
    if sync.get("status") == "ok":
        profile_trigger_sync_queue.clear(profile.spotify_uri)
    return {"status": "saved", "filename": profile.filename, "spectra_sync": sync}
