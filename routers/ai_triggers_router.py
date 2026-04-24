"""
SpotFX — AI trigger generation router.

GET  /api/ai-triggers/training-songs          — songs eligible as training data
GET  /api/ai-triggers/candidate-songs         — songs eligible as targets (have audio shape)
POST /api/ai-triggers/generate                — call Claude for trigger suggestions
POST /api/ai-triggers/apply                   — write approved suggestions to a profile
GET  /api/ai-triggers/training-profiles       — list saved training profiles
POST /api/ai-triggers/training-profiles       — create / update a training profile
DELETE /api/ai-triggers/training-profiles/{id} — delete a training profile
POST /api/ai-triggers/analyze-learning        — Claude meta-analysis of approval feedback
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ai_trigger_service import (
    generate_suggestions,
    estimate_generation_cost,
    list_training_songs,
    list_songs_with_librosa,
    analyze_learning,
    SuggestedTrigger,
)
from services.profile_manager import load_profile_by_uri, save_profile
from services.training_profile_manager import (
    list_training_profiles,
    save_training_profile,
    delete_training_profile,
    TrainingProfile,
)
from services.suggestion_store import (
    save_suggestion_set,
    load_suggestion_set,
)
from models.song_profile import MusicTrigger
from models.ai_suggestion_set import AISuggestionSet, SavedSuggestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-triggers", tags=["ai-triggers"])


# ── Request / response models ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    training_uris: list[str]
    target_uri: str
    description: str = ""


class ApplySuggestion(BaseModel):
    timestamp_ms: int
    event_id: str


class ApplyRequest(BaseModel):
    target_uri: str
    suggestions: list[ApplySuggestion]
    ai_training_profile_id: str = ""


class FeedbackSong(BaseModel):
    song: str
    song_comment: str = ""
    approved: list[dict] = []
    rejected: list[dict] = []
    manually_added: list[dict] = []


class AnalyzeLearningRequest(BaseModel):
    current_description: str = ""
    feedback: list[FeedbackSong]


# ── Song / profile endpoints ───────────────────────────────────────────────────

@router.get("/training-songs")
async def training_songs():
    """Songs that have both a complete audio shape and at least one trigger."""
    return list_training_songs()


@router.get("/candidate-songs")
async def candidate_songs():
    """All songs with a complete audio shape and librosa analysis (suitable as generation targets)."""
    return list_songs_with_librosa()


class GenerateRequestWithProfile(GenerateRequest):
    training_profile_id: str = ""
    training_profile_name: str = ""
    model: str = "claude-sonnet-4-6"


class EstimateCostRequest(BaseModel):
    training_uris: list[str]
    target_uris: list[str]
    description: str = ""


@router.post("/estimate-cost")
async def estimate_cost(req: EstimateCostRequest):
    """Estimate Claude token cost for generating suggestions without calling the API."""
    try:
        return estimate_generation_cost(
            training_uris=req.training_uris,
            target_uris=req.target_uris,
            description=req.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate")
async def generate(req: GenerateRequestWithProfile):
    """Call Claude to suggest triggers for the target song based on training songs."""
    try:
        suggestions, usage = generate_suggestions(
            training_uris=req.training_uris,
            target_uri=req.target_uri,
            description=req.description,
            model=req.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Claude API error: {exc}")

    from services.audio_analyzer import load_audio_shape_meta
    from datetime import datetime, timezone
    meta = load_audio_shape_meta(req.target_uri)
    title  = meta.title  if meta else ""
    artist = meta.artist if meta else ""

    # Auto-save to disk
    saved_suggestions = [
        SavedSuggestion(
            timestamp_ms=s.timestamp_ms,
            event_id=s.event_id,
            event_name=s.event_name,
            confidence=s.confidence,
            reasoning=s.reasoning,
            original_timestamp_ms=s.timestamp_ms,
            original_event_id=s.event_id,
        )
        for s in suggestions
    ]
    suggestion_set = AISuggestionSet(
        spotify_uri=req.target_uri,
        title=title,
        artist=artist,
        duration_ms=meta.duration_ms if meta else 0,
        generated_at=datetime.now(timezone.utc).isoformat(),
        training_profile_id=req.training_profile_id,
        training_profile_name=req.training_profile_name,
        suggestions=saved_suggestions,
        cost_usd=usage["cost_usd"],
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        model=usage.get("model", req.model),
    )
    save_suggestion_set(suggestion_set)

    return {
        "target_title":  title,
        "target_artist": artist,
        "suggestions":   [s.model_dump() for s in suggestions],
        "cost_usd":      usage["cost_usd"],
        "input_tokens":  usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
    }


@router.post("/apply")
async def apply(req: ApplyRequest):
    """Append approved suggestions as MusicTrigger objects to the target song profile."""
    from datetime import date
    profile = load_profile_by_uri(req.target_uri)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found for this URI")

    profile.triggers = [
        MusicTrigger(timestamp_ms=s.timestamp_ms, event_id=s.event_id)
        for s in req.suggestions
    ]

    profile.ai_generated = True
    profile.ai_generated_date = date.today().isoformat()
    if req.ai_training_profile_id:
        profile.ai_training_profile_id = req.ai_training_profile_id

    # Read model from saved suggestion set and log it on the profile
    track_id = req.target_uri.split(":")[-1]
    saved = load_suggestion_set(track_id)
    if saved and saved.model:
        profile.ai_model = saved.model

    save_profile(profile)

    # Mark the saved suggestion set as applied (best-effort)
    if saved:
        saved.applied = True
        save_suggestion_set(saved)

    return {"applied": len(req.suggestions), "profile_uri": req.target_uri}


# ── Training profiles ─────────────────────────────────────────────────────────

@router.get("/training-profiles")
async def get_training_profiles():
    return list_training_profiles()


@router.post("/training-profiles")
async def upsert_training_profile(profile: TrainingProfile):
    save_training_profile(profile)
    return {"status": "saved", "id": profile.id}


@router.delete("/training-profiles/{profile_id}")
async def remove_training_profile(profile_id: str):
    ok = delete_training_profile(profile_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Training profile not found")
    return {"status": "deleted"}


# ── Retroactive generation ────────────────────────────────────────────────────

@router.post("/generate-now")
async def generate_now(uri: str):
    """Manually trigger AI suggestion generation for a URI that already has a shape."""
    import asyncio
    from services.audio_shape_service import _auto_generate_for_uri
    asyncio.create_task(_auto_generate_for_uri(uri))
    return {"started": True}


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
    profile_obj.triggers = [
        MusicTrigger(timestamp_ms=s["timestamp_ms"], event_id=s["event_id"])
        for s in raw
    ]
    profile_obj.embedded_generated = True
    save_profile(profile_obj)

    return {"applied": len(raw), "title": title, "artist": artist}


# ── Analyze learning ──────────────────────────────────────────────────────────

@router.post("/analyze-learning")
async def analyze_learning_endpoint(req: AnalyzeLearningRequest):
    """Ask Claude to refine the description based on approval/rejection feedback."""
    try:
        refined = analyze_learning(
            current_description=req.current_description,
            feedback=[f.model_dump() for f in req.feedback],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Claude API error: {exc}")
    return {"refined_description": refined}


# ── Analyzed trigger generation (for builder import) ──────────────────────────

@router.get("/analyze-triggers")
async def analyze_triggers(uri: str, category: str = "all"):
    """
    Generate analyzed triggers for a song using the embedded pipeline.

    category: "all", "scenes", or "flares"
    Returns list of {timestamp_ms, event_id, confidence, role}.
    """
    from services.librosa_service import get_analysis_by_uri
    from services.embedded_trigger_service import suggest_triggers
    from services.audio_shape_service import _find_profile_for_genres
    from services.training_profile_manager import TrainingProfile
    from services.profile_manager import load_profile_by_uri

    la = get_analysis_by_uri(uri)
    if not la or not la.beats:
        raise HTTPException(400, "No librosa analysis available for this song")

    profile = load_profile_by_uri(uri)
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
                id=f"analyzed_{t['event_id']}_{t['timestamp_ms']}",
                timestamp_ms=t["timestamp_ms"],
                event_id=t["event_id"],
                labels=list(t.get("labels") or []),
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
            "timestamp_ms": t["timestamp_ms"],
            "event_id": t["event_id"],
            "confidence": t.get("confidence", 0.5),
            "role": role,
        })

    return {
        "triggers": results,
        "training_profile": tp.name,
        "total": len(results),
        "category": category,
    }


# ── Training profile tuning ──────────────────────────────────────────────────

import time as _time

# Global progress state keyed by profile_id
_tune_progress: dict[str, dict] = {}
_tune_cancel: dict[str, bool] = {}


@router.get("/tune/active")
async def tune_active():
    """Return progress for any currently running tune, or {running: false}."""
    for pid, prog in _tune_progress.items():
        if prog.get("running"):
            return prog
    return {"running": False}


@router.get("/training-profiles/{profile_id}/tune/progress")
async def tune_progress(profile_id: str):
    """Poll current tuning progress for a profile."""
    return _tune_progress.get(profile_id, {"running": False})


@router.post("/training-profiles/{profile_id}/tune/cancel")
async def tune_cancel(profile_id: str):
    """Request cancellation of a running tune."""
    if profile_id in _tune_progress and _tune_progress[profile_id].get("running"):
        _tune_cancel[profile_id] = True
        return {"status": "cancel_requested"}
    return {"status": "not_running"}


@router.post("/training-profiles/{profile_id}/tune")
async def tune_profile(profile_id: str):
    """Run the automated tuning loop for a training profile.
    Returns the best parameters found and applies them to the profile."""
    import asyncio
    from services.training_profile_manager import TrainingProfile, TRAINING_PROFILES_FILE
    import json

    raw = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8")) if TRAINING_PROFILES_FILE.exists() else {}
    if profile_id not in raw:
        raise HTTPException(404, f"Training profile {profile_id} not found")

    if _tune_progress.get(profile_id, {}).get("running"):
        raise HTTPException(409, "Tuning already in progress for this profile")

    tp = TrainingProfile(**raw[profile_id])

    # Run tuning in executor to avoid blocking
    def _run_tune():
        import sys
        sys.path.insert(0, str(TRAINING_PROFILES_FILE.parent.parent))
        from scripts.tune_triggers import _grid_combos, \
            _apply_overrides, preload_songs, score_fast, SCENE_GRID, FLARE_GRID
        from scripts.score_triggers import (
            build_role_map, DEFAULT_SCORE_WEIGHTS, match_triggers,
            SongScore, SCENE_CATEGORIES, FLARE_CATEGORIES,
        )

        _tune_cancel[profile_id] = False
        _tune_progress[profile_id] = {
            "running": True, "phase": "loading", "pct": 0,
            "profile_name": tp.name, "profile_id": profile_id,
        }

        def _check_cancel():
            if _tune_cancel.get(profile_id):
                return True
            return False

        t_start = _time.monotonic()

        role_map = build_role_map(tp)
        weights = DEFAULT_SCORE_WEIGHTS
        all_uris = list(set(tp.training_uris + tp.embedded_only_uris))
        songs = preload_songs(all_uris)
        if not songs:
            return {"error": "No usable training songs", "improved": False}

        song_list = [{"title": s["title"], "artist": s["artist"], "uri": s["uri"]} for s in songs]

        beat_ms = (60_000 / songs[0]["analysis"].tempo_bpm) if songs[0]["analysis"].tempo_bpm else 500
        tolerance_ms = int(2 * beat_ms)

        baseline_f1 = score_fast(tp, songs, role_map, tolerance_ms, weights)

        scene_combos = _grid_combos(SCENE_GRID)
        flare_combos = _grid_combos(FLARE_GRID)
        total_combos = len(scene_combos) + len(flare_combos)

        # Scene tuning
        _tune_progress[profile_id].update(phase="scene", pct=0)
        best_scene = {}
        best_f1 = baseline_f1
        for i, overrides in enumerate(scene_combos):
            if _check_cancel():
                return {"improved": False, "cancelled": True}
            trial = _apply_overrides(tp, overrides)
            f1 = score_fast(trial, songs, role_map, tolerance_ms, weights)
            if f1 > best_f1:
                best_f1 = f1
                best_scene = overrides.copy()
            if (i + 1) % 50 == 0:
                _time.sleep(0)  # release GIL so event loop can serve requests
            if (i + 1) % 100 == 0 or i == len(scene_combos) - 1:
                _tune_progress[profile_id].update(
                    pct=round((i + 1) / total_combos * 100, 1),
                    phase="scene",
                    elapsed_s=round(_time.monotonic() - t_start, 1),
                )

        # Flare tuning (locked to best scene)
        tp_scene = _apply_overrides(tp, best_scene) if best_scene else tp
        scene_f1 = score_fast(tp_scene, songs, role_map, tolerance_ms, weights)
        best_flare = {}
        best_f1_flare = scene_f1
        for i, overrides in enumerate(flare_combos):
            if _check_cancel():
                return {"improved": False, "cancelled": True}
            all_ov = {**best_scene, **overrides}
            trial = _apply_overrides(tp, all_ov)
            f1 = score_fast(trial, songs, role_map, tolerance_ms, weights)
            if f1 > best_f1_flare:
                best_f1_flare = f1
                best_flare = overrides.copy()
            if (i + 1) % 50 == 0:
                _time.sleep(0)  # release GIL
            if (i + 1) % 100 == 0 or i == len(flare_combos) - 1:
                _tune_progress[profile_id].update(
                    pct=round((len(scene_combos) + i + 1) / total_combos * 100, 1),
                    phase="flare",
                    elapsed_s=round(_time.monotonic() - t_start, 1),
                )

        all_best = {**best_scene, **best_flare}
        final_f1 = best_f1_flare if best_flare else best_f1
        duration_s = round(_time.monotonic() - t_start, 1)

        # Score breakdown: run final params on each song for detailed results
        final_tp = _apply_overrides(tp, all_best) if all_best else tp
        score_breakdown = {}
        total_scene_triggers = 0
        total_flare_triggers = 0
        from services.embedded_trigger_service import suggest_triggers
        for song in songs:
            available = set(role_map.keys())
            generated = suggest_triggers(
                target_uri=song["uri"],
                all_training_uris=[],
                available_event_ids=available,
                training_profile=final_tp,
                _cached_analysis=song["analysis"],
            )
            categories = match_triggers(song["human"], generated, role_map, tolerance_ms)
            ss = SongScore(categories=categories)
            for cat, cs in categories.items():
                if cat in SCENE_CATEGORIES:
                    total_scene_triggers += cs.gen_count
                elif cat in FLARE_CATEGORIES:
                    total_flare_triggers += cs.gen_count
                agg = score_breakdown.setdefault(cat, {
                    "tp": 0.0, "fp": 0, "fn": 0.0,
                    "human_count": 0, "gen_count": 0, "match_count": 0,
                })
                agg["tp"] += cs.tp
                agg["fp"] += cs.fp
                agg["fn"] += cs.fn
                agg["human_count"] += cs.human_count
                agg["gen_count"] += cs.gen_count
                agg["match_count"] += cs.match_count

        # Compute per-category F1
        for cat, agg in score_breakdown.items():
            p = agg["tp"] / (agg["tp"] + agg["fp"]) if (agg["tp"] + agg["fp"]) > 0 else 0.0
            r = agg["tp"] / (agg["tp"] + agg["fn"]) if (agg["tp"] + agg["fn"]) > 0 else 0.0
            agg["precision"] = round(p, 3)
            agg["recall"] = round(r, 3)
            agg["f1"] = round(2 * p * r / (p + r) if (p + r) > 0 else 0.0, 3)
            agg["weight"] = weights.get(cat, 1.0)

        return {
            "baseline_f1": round(baseline_f1, 3),
            "tuned_f1": round(final_f1, 3),
            "improvement_pct": round((final_f1 - baseline_f1) / max(baseline_f1, 0.001) * 100, 1),
            "best_params": all_best,
            "songs_used": len(songs),
            "song_list": song_list,
            "improved": final_f1 > baseline_f1,
            "duration_s": duration_s,
            "score_breakdown": score_breakdown,
            "scene_triggers": total_scene_triggers,
            "flare_triggers": total_flare_triggers,
            "total_triggers": total_scene_triggers + total_flare_triggers,
            "timestamp": _time.time(),
        }

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _run_tune)
    finally:
        _tune_progress[profile_id] = {"running": False}
        _tune_cancel.pop(profile_id, None)

    if result.get("cancelled"):
        return {"improved": False, "cancelled": True}

    if result.get("error"):
        raise HTTPException(400, result["error"])

    # Auto-apply if improved
    if result["improved"] and result["best_params"]:
        raw_data = json.loads(TRAINING_PROFILES_FILE.read_text(encoding="utf-8"))
        raw_data[profile_id].update(result["best_params"])
        TRAINING_PROFILES_FILE.write_text(json.dumps(raw_data, indent=2), encoding="utf-8")

    return result
