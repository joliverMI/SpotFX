"""
SpotFX — trigger generation router (embedded pipeline + training profiles).

GET  /api/ai-triggers/training-songs           — songs eligible as training data
GET  /api/ai-triggers/training-profiles        — list saved training profiles
POST /api/ai-triggers/training-profiles        — create / update a training profile
DELETE /api/ai-triggers/training-profiles/{id} — delete a training profile
POST /api/ai-triggers/generate-embedded        — run the embedded KNN engine
GET  /api/ai-triggers/analyze-triggers         — analyzed triggers for builder import
Plus training-profile tuning, scheduling, and history endpoints.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ai_trigger_service import list_training_songs
from services import (profile_trigger_sync_queue, spectra_trigger_sync_client,
                      trigger_identity)
from services.profile_manager import load_profile_by_uri, save_profile
from services.training_profile_manager import (
    list_training_profiles,
    save_training_profile,
    delete_training_profile,
    TrainingProfile,
)
from models.state import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-triggers", tags=["ai-triggers"])


# ── Song / profile endpoints ───────────────────────────────────────────────────

@router.get("/training-songs")
async def training_songs():
    """Songs that have both a complete audio shape and at least one trigger."""
    return list_training_songs()


# ── Training profiles ─────────────────────────────────────────────────────────

@router.get("/training-profiles")
async def get_training_profiles():
    return list_training_profiles()


@router.get("/training-profiles/current-match")
async def current_profile_match():
    """Which profile the engine is using — or would use — for the CURRENT
    song's triggerless/analyzed playback. Resolution runs through the
    engine's own `_resolve_triggerless_profile` (Dinner Party → genre
    overlap → default), so the answer can never drift from what actually
    fires. `active` distinguishes "firing synthetic triggers right now"
    from "would apply if this song had no triggers"."""
    from main import engine
    from models.state import state

    track = state.current_track
    if track is None:
        return {"track": None, "profile_id": None, "reason": "no_track",
                "active": False}

    tp = engine._resolve_triggerless_profile()
    genres = list(track.genres or [])
    if not genres and engine._profile:
        genres = list(engine._profile.artist_genre or [])

    reason = "none"
    if tp is not None:
        if state.dinner_party_mode and tp.name.lower().strip() == "dinner party":
            reason = "dinner_party"
        elif {g.lower() for g in genres} & {g.lower() for g in tp.genres}:
            reason = "genre"
        elif tp.is_default:
            reason = "default"
    return {
        "track": {
            "uri": track.spotify_uri,
            "title": track.title,
            "artist": track.artist,
            "genres": genres,
        },
        "profile_id": tp.id if tp else None,
        "profile_name": tp.name if tp else None,
        "reason": reason,
        # synthetic triggerless triggers are live for this song
        "active": engine._triggerless_triggers is not None,
    }


@router.post("/training-profiles")
async def upsert_training_profile(profile: TrainingProfile):
    save_training_profile(profile)
    from main import engine
    engine._genre_scale_uri = None  # genre intensity-scale fallback may have changed
    return {"status": "saved", "id": profile.id}


@router.delete("/training-profiles/{profile_id}")
async def remove_training_profile(profile_id: str):
    ok = delete_training_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Training profile not found")
    return {"status": "deleted"}


# ── Embedded generation ───────────────────────────────────────────────────────

class EmbeddedGenerateRequest(BaseModel):
    target_uri: str
    training_uris: list[str]
    training_profile_id: str = ""   # optional — for per-profile tuning settings


@router.post("/generate-embedded")
async def generate_embedded(req: EmbeddedGenerateRequest):
    """Run the embedded KNN engine for a target song and auto-apply triggers to its profile."""
    from services.embedded_trigger_service import suggest_triggers
    from services.audio_analyzer import load_audio_shape_meta
    from services.profile_manager import get_event_map
    from models.song_profile import SongProfile

    if not req.training_uris:
        raise HTTPException(status_code=400, detail="No training URIs provided")

    meta = load_audio_shape_meta(req.target_uri)
    title  = meta.title  if meta else ""
    artist = meta.artist if meta else ""

    event_map = get_event_map()
    available_event_ids = set(event_map.keys())

    # Resolve training profile for per-profile tuning settings
    tp_obj: TrainingProfile | None = None
    if req.training_profile_id:
        raw_profiles = {p["id"]: p for p in list_training_profiles()}
        if req.training_profile_id in raw_profiles:
            tp_obj = TrainingProfile.model_validate(raw_profiles[req.training_profile_id])

    try:
        raw = suggest_triggers(req.target_uri, req.training_uris, available_event_ids,
                               training_profile=tp_obj)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedded generation error: {exc}")

    if not raw:
        return {"applied": 0, "title": title, "artist": artist}

    existing = load_profile_by_uri(req.target_uri)
    profile_obj = existing or SongProfile(
        spotify_uri=req.target_uri,
        title=title,
        artist=artist,
        duration_ms=meta.duration_ms if meta else 0,
    )
    # STABLE IDS + a policy-driven merge, never a wholesale replace: the same
    # analyzed mark computed twice is the SAME trigger twice, so a re-import
    # updates in place instead of churning the song's whole corpus under
    # fresh uuids. Which side wins on a mark he has since hand-edited is
    # settings.trigger_import_policy — see services/trigger_identity.py.
    imported = trigger_identity.build_imported_triggers(raw)
    profile_obj.triggers, merge_counts = trigger_identity.merge_imported_triggers(
        profile_obj.triggers, imported)
    profile_obj.embedded_generated = True
    save_profile(profile_obj)

    # The import must reach the copy SPECTRA fires from — found 2026-08-25,
    # this path wrote the editor copy only, so an imported song's triggers
    # never fired. UPSERT-ONLY: an import runs unattended, so it may add and
    # update but never delete (his deliberate deletions land through an
    # explicit Timeline save). Best-effort and REPORTED: the profile is
    # already on disk, so a SPECTRA that is down is named here, not hidden.
    sync = await spectra_trigger_sync_client.sync_profile_upsert_only(profile_obj)
    if sync.get("status") == "ok":
        profile_trigger_sync_queue.clear(profile_obj.spotify_uri)

    return {"applied": len(raw), "title": title, "artist": artist,
            "import_policy": trigger_identity.import_policy(),
            "merge": merge_counts, "spectra_sync": sync}


# ── Analyzed trigger generation (for builder import) ──────────────────────────

@router.get("/analyze-triggers")
async def analyze_triggers(uri: str, category: str = "all"):
    """
    Generate analyzed triggers for a song using the embedded pipeline.

    category: "all", "scenes", or "flares"
    Returns list of {timestamp_ms, event_id, confidence, role}.
    """
    from services.librosa_service import get_analysis_by_uri, get_analysis_by_title_artist
    from services.embedded_trigger_service import suggest_triggers
    from services.audio_shape_service import _find_profile_for_genres
    from services.training_profile_manager import TrainingProfile
    from services.profile_manager import load_profile_by_uri

    profile = load_profile_by_uri(uri)
    la = get_analysis_by_uri(uri)
    if (not la or not la.beats) and profile:
        # The capture may be keyed to a different release URI of the same
        # song — rescue through the profile's title/artist like the profile
        # layer does.
        la = get_analysis_by_title_artist(profile.artist, profile.title)
    if not la or not la.beats:
        raise HTTPException(400, "No librosa analysis available for this song")

    genres = profile.artist_genre if profile and profile.artist_genre else []
    if not genres and state.current_track and state.current_track.spotify_uri == uri:
        genres = state.current_track.genres or []

    tp_data = _find_profile_for_genres(genres)
    if not tp_data:
        raise HTTPException(400, "No matching training profile found for this song's genres")

    tp = TrainingProfile(**tp_data)

    # Build available event IDs + role map
    role_attrs = {
        "song_start_event_id": "scene", "beat_start_event_id": "scene",
        "song_end_event_id": "scene", "drop_event_id": "scene",
        "lull_event_id": "scene", "charge_event_id": "scene",
        "quiet_event_id": "scene", "scene_fill_event_id": "scene",
        "flare_event_id": "flare", "flare_low_event_id": "flare",
        "flare_mid_event_id": "flare", "flare_high_event_id": "flare",
        "flare_scene_event_id": "flare",
    }
    available: set[str] = set()
    eid_to_role: dict[str, str] = {}
    for attr, role in role_attrs.items():
        eid = getattr(tp, attr, "")
        if eid:
            available.add(eid)
            eid_to_role[eid] = role

    raw = suggest_triggers(
        target_uri=uri, all_training_uris=[], available_event_ids=available,
        training_profile=tp, _cached_analysis=la,
    )

    # Persist the full (unfiltered) result to the analyzed-trigger cache so
    # subsequent playbacks of this song are cache hits using the same triggers
    # the user just imported. The trigger_engine consumes the full list and
    # lets the label-aware action selector decide what to fire.
    try:
        from services import analyzed_trigger_store
        cached = [
            analyzed_trigger_store.CachedTrigger(
                id=trigger_identity.stable_trigger_id(t["event_id"], t["timestamp_ms"]),
                timestamp_ms=t["timestamp_ms"],
                event_id=t["event_id"],
                labels=list(t.get("labels") or []),
                intensity=t.get("intensity"),
            )
            for t in raw
        ]
        track_id = uri.split(":")[-1]
        analyzed_trigger_store.save(track_id, tp, cached)
    except Exception as exc:
        logger.warning("Analyzed-trigger cache save failed for %s: %s", uri, exc)

    # Filter by category
    results = []
    for t in raw:
        role = eid_to_role.get(t["event_id"], "unknown")
        if category == "scenes" and role != "scene":
            continue
        if category == "flares" and role != "flare":
            continue
        results.append({
            # THE STABLE ID, handed to the timeline so the mark it places is
            # the SAME trigger on every re-import instead of a fresh uuid each
            # time. Identical to the id this endpoint's own analyzed-trigger
            # cache keys the row with, above — one identity, not two.
            "id": trigger_identity.stable_trigger_id(t["event_id"], t["timestamp_ms"]),
            "timestamp_ms": t["timestamp_ms"],
            "event_id": t["event_id"],
            "confidence": t.get("confidence", 0.5),
            "intensity": t.get("intensity"),
            "role": role,
        })

    return {
        "triggers": results,
        "training_profile": tp.name,
        "total": len(results),
        "category": category,
        # The timeline applies the SAME policy this process would — one
        # setting, not a second client-side opinion about his hand edits.
        "import_policy": trigger_identity.import_policy(),
    }


# ── Training profile tuning ──────────────────────────────────────────────────
# Execution, progress state, scheduling, and history live in
# services/tune_scheduler.py — shared by immediate runs, scheduled runs,
# and queued ("right after") runs.

from services import tune_scheduler


@router.get("/tune/active")
async def tune_active():
    """Return progress for any currently running tune, or {running: false}."""
    return tune_scheduler.any_running() or {"running": False}


@router.get("/training-profiles/{profile_id}/tune/progress")
async def tune_progress(profile_id: str):
    """Poll current tuning progress for a profile."""
    return tune_scheduler.tune_progress.get(profile_id, {"running": False})


@router.post("/training-profiles/{profile_id}/tune/cancel")
async def tune_cancel(profile_id: str):
    """Request cancellation of a running tune."""
    if tune_scheduler.tune_progress.get(profile_id, {}).get("running"):
        tune_scheduler.tune_cancel[profile_id] = True
        return {"status": "cancel_requested"}
    return {"status": "not_running"}


@router.post("/training-profiles/{profile_id}/tune")
async def tune_profile(profile_id: str):
    """Run the tuning loop for a training profile immediately.
    Improved parameters are auto-applied inside the runner; every run is
    recorded in tune history regardless of outcome."""
    import asyncio
    import json
    from services.training_profile_manager import TRAINING_PROFILES_FILE

    raw = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8")) if TRAINING_PROFILES_FILE.exists() else {}
    if profile_id not in raw:
        raise HTTPException(404, f"Training profile {profile_id} not found")

    if tune_scheduler.tune_progress.get(profile_id, {}).get("running"):
        raise HTTPException(409, "Tuning already in progress for this profile")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, tune_scheduler.run_tune_blocking, profile_id, "immediate")

    if result.get("cancelled"):
        return {"improved": False, "cancelled": True}
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


# ── Tune scheduling + history ─────────────────────────────────────────────────

@router.get("/tune/schedule")
async def tune_schedule_list():
    """Pending schedule queue (in run order) + any currently running tune."""
    entries = tune_scheduler.load_schedule()
    for e in entries:
        e["due_at"] = tune_scheduler.entry_due_at(e)
    return {"entries": entries, "running": tune_scheduler.any_running()}


@router.post("/tune/schedule")
async def tune_schedule_add(body: dict):
    """Queue a tuning run. body: {profile_id, at: "HH:MM" | "after"}.
    "HH:MM" = next occurrence of that time (today if still ahead, else
    tomorrow). "after" = chained right after whatever precedes it in the
    queue (or the currently running tune)."""
    import json
    from services.training_profile_manager import TRAINING_PROFILES_FILE

    profile_id = str(body.get("profile_id") or "")
    at = str(body.get("at") or "")
    raw = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8")) if TRAINING_PROFILES_FILE.exists() else {}
    if profile_id not in raw:
        raise HTTPException(404, f"Training profile {profile_id} not found")
    if at != "after":
        parts = at.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts) \
                or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            raise HTTPException(400, f"Invalid time {at!r} — use HH:MM or \"after\"")

    entry = tune_scheduler.add_schedule_entry(
        profile_id, raw[profile_id].get("name", "?"), at)
    entry["due_at"] = tune_scheduler.entry_due_at(entry)
    return entry


@router.delete("/tune/schedule/{entry_id}")
async def tune_schedule_remove(entry_id: str):
    if not tune_scheduler.remove_schedule_entry(entry_id):
        raise HTTPException(404, "Schedule entry not found")
    return {"status": "removed"}


@router.get("/tune/history")
async def tune_history(limit: int = 20):
    """Recent tuning runs, newest first — including failures with their
    error message (full tracebacks land in storage/tune_runs.log)."""
    return {"runs": tune_scheduler.load_history()[:max(1, min(limit, 50))]}
