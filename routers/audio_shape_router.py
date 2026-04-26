"""
SpotFX — Audio Shape API router.

Endpoints:
  GET /api/audio-shape          — get meta + music marks for current / given URI
  GET /api/audio-shape/data     — return shape timeseries as JSON (for graph)
  DELETE /api/audio-shape       — delete shape, triggering re-learn next playback
"""
import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

import numpy as np

from config import AUDIO_SHAPES_DIR
from services.audio_analyzer import load_audio_shape_meta, MusicMarkDetector
from services.audio_shape_service import audio_shape_service
from models.audio_shape import AudioShapeMeta, MusicMark
from models.state import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio-shape", tags=["audio-shape"])


@router.get("/meta")
async def get_meta(uri: str = Query(...)):
    meta = load_audio_shape_meta(uri)
    if meta is None:
        return None
    return meta.model_dump()


@router.get("/data")
async def get_data(uri: str = Query(...), start_ms: int = 0, end_ms: int = 0):
    """Return timeseries data as JSON arrays (downsampled if needed)."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")

    npz_path = AUDIO_SHAPES_DIR / meta.npz_file
    if not npz_path.exists():
        raise HTTPException(404, "Audio shape file missing")

    data = np.load(npz_path)
    ts = data["timestamps_ms"].astype(int)
    rms_t = data["rms_total"]
    rms_l = data["rms_low"]
    rms_m = data["rms_mid"] if "rms_mid" in data else np.zeros_like(rms_l)
    rms_h = data["rms_high"]

    # Slice to requested window if provided
    if end_ms > start_ms:
        mask = (ts >= start_ms) & (ts <= end_ms)
        ts, rms_t, rms_l, rms_m, rms_h = ts[mask], rms_t[mask], rms_l[mask], rms_m[mask], rms_h[mask]

    # Downsample to max 10000 points for browser rendering
    max_pts = 10000
    if len(ts) > max_pts:
        step = len(ts) // max_pts
        ts, rms_t, rms_l, rms_m, rms_h = ts[::step], rms_t[::step], rms_l[::step], rms_m[::step], rms_h[::step]

    return {
        "timestamps_ms": ts.tolist(),
        "rms_total": rms_t.tolist(),
        "rms_low": rms_l.tolist(),
        "rms_mid": rms_m.tolist(),
        "rms_high": rms_h.tolist(),
    }


@router.get("/live")
async def get_live_data(uri: str = Query(...)):
    """Return in-progress capture data for the given URI, downsampled for the browser."""
    data = audio_shape_service.get_live_data(uri)
    if data is None:
        raise HTTPException(404, "No active capture for this URI")

    ts    = data["timestamps_ms"]
    rms_t = data["rms_total"]
    rms_l = data["rms_low"]
    rms_m = data["rms_mid"]
    rms_h = data["rms_high"]

    # Downsample to max 10000 points (same as /data)
    max_pts = 10000
    n = len(ts)
    if n > max_pts:
        step = n // max_pts
        ts    = ts[::step]
        rms_t = rms_t[::step]
        rms_l = rms_l[::step]
        rms_m = rms_m[::step]
        rms_h = rms_h[::step]

    return {
        "timestamps_ms": ts,
        "rms_total": rms_t,
        "rms_low": rms_l,
        "rms_mid": rms_m,
        "rms_high": rms_h,
        "capture_complete": False,
    }


@router.get("/calibration-status")
async def get_calibration_status(uri: str):
    """Return current auto-offset detection target for a URI (used to restore canvas state on page load)."""
    from services.auto_offset_service import auto_offset_service
    return auto_offset_service.get_status(uri)


@router.get("/auto-offset-stats")
async def auto_offset_stats(uri: str):
    """Return per-Set-List + default offset entries for the song's audio shape."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")
    return {
        "uri": uri,
        "default": {
            "timestamp_offset_ms": meta.timestamp_offset_ms,
            "offset_quality": meta.offset_quality,
            "verification": meta.offset_verification,
        },
        "setlist_offsets": meta.setlist_offsets or {},
        "captured_duration_ms": meta.duration_ms,
    }


@router.patch("/offset")
async def update_offset(uri: str, timestamp_offset_ms: int,
                        offset_verification: str = "user_verified"):
    """Save shape timestamp offset and verification status to the sidecar JSON."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")
    meta.timestamp_offset_ms = timestamp_offset_ms
    meta.offset_verification = offset_verification  # type: ignore[assignment]
    meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    # Hot-reload trigger engine so offset takes effect without a song change
    try:
        from main import engine
        engine.reload_shape_offset(uri)
    except Exception:
        pass
    return {"status": "updated", "timestamp_offset_ms": timestamp_offset_ms,
            "offset_verification": offset_verification}


@router.get("/perception-trim")
async def get_perception_trim(uri: str):
    """Read the current perception trim for the active scope (Set List slot
    if one is active, otherwise the song's default slot)."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        return {"uri": uri, "scope": "default", "perception_trim_ms": 0}
    sl_id = state.active_setlist_id
    if sl_id:
        entry = (meta.setlist_offsets or {}).get(sl_id) or {}
        return {"uri": uri, "scope": f"setlist:{sl_id}", "perception_trim_ms": int(entry.get("perception_trim_ms", 0))}
    return {"uri": uri, "scope": "default", "perception_trim_ms": int(getattr(meta, "perception_trim_ms", 0) or 0)}


@router.post("/perception-trim")
async def update_perception_trim(uri: str, delta_ms: int = 0, value_ms: int | None = None):
    """Adjust the per-(track, Set List) perception trim that layers on top
    of the xcorr-derived offset. `delta_ms` nudges by that amount (additive);
    pass `value_ms` to set an absolute value instead. Writes to the active
    Set List slot when one is active, otherwise to the default slot.
    """
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")
    sl_id = state.active_setlist_id
    if sl_id:
        if not isinstance(meta.setlist_offsets, dict):
            meta.setlist_offsets = {}
        entry = meta.setlist_offsets.get(sl_id) or {}
        cur = int(entry.get("perception_trim_ms", 0))
        new_trim = int(value_ms) if value_ms is not None else cur + int(delta_ms)
        entry["perception_trim_ms"] = new_trim
        meta.setlist_offsets[sl_id] = entry
        scope = f"setlist:{sl_id}"
    else:
        cur = int(getattr(meta, "perception_trim_ms", 0) or 0)
        new_trim = int(value_ms) if value_ms is not None else cur + int(delta_ms)
        meta.perception_trim_ms = new_trim
        scope = "default"
    meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    try:
        from main import engine
        engine.reload_shape_offset(uri)
    except Exception:
        pass
    try:
        from services.websocket_manager import ws_manager
        await ws_manager.broadcast({
            "type": "perception_trim_updated",
            "uri": uri,
            "scope": scope,
            "perception_trim_ms": new_trim,
        })
    except Exception:
        pass
    return {"uri": uri, "scope": scope, "perception_trim_ms": new_trim}


@router.patch("/marks")
async def update_marks(uri: str, marks: list[MusicMark]):
    """Save user-edited music marks back to the sidecar JSON."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")
    meta.music_marks = marks
    meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return {"status": "updated", "mark_count": len(marks)}


@router.post("/redetect")
async def redetect_marks(uri: str = Query(...)):
    """Re-run mark detection on an existing .npz without re-capturing the song."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found for this URI")
    npz_path = AUDIO_SHAPES_DIR / meta.npz_file
    if not npz_path.exists():
        raise HTTPException(404, "NPZ file missing — re-learn the song first")
    marks = MusicMarkDetector().detect(npz_path)
    meta.music_marks = marks
    meta_path = npz_path.with_suffix(".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return {"marks": len(marks), "music_marks": [m.model_dump() for m in marks]}


@router.post("/backfill-genres")
async def backfill_genres():
    """Fetch genres from Spotify for all audio shapes and song profiles that have empty genres."""
    from api.spotify_client import get_spotify, _fetch_artist_genres
    from config import PROFILES_DIR
    sp = get_spotify()
    updated = 0

    def _genres_for_uri(uri: str) -> list[str]:
        track_data = sp.track(uri)
        first = track_data["artists"][0] if track_data.get("artists") else {}
        aid = first.get("id", "")
        aname = first.get("name", "")
        return _fetch_artist_genres(sp, aid, aname) if aid else []

    # Audio shape sidecars
    for path in AUDIO_SHAPES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("genres"):
                continue
            uri = data.get("spotify_uri", "")
            if not uri:
                continue
            data["genres"] = _genres_for_uri(uri)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            updated += 1
        except Exception as exc:
            logger.warning("backfill-genres (shape) failed for %s: %s", path.name, exc)

    # Song profiles
    for path in PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("artist_genre"):
                continue
            uri = data.get("spotify_uri", "")
            if not uri:
                continue
            data["artist_genre"] = _genres_for_uri(uri)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            updated += 1
        except Exception as exc:
            logger.warning("backfill-genres (profile) failed for %s: %s", path.name, exc)

    return {"updated": updated}


@router.get("/librosa")
async def get_librosa(uri: str = Query(...)):
    """Return saved librosa analysis for a URI, or 404 if not yet analysed."""
    from services.librosa_service import get_analysis_by_uri
    analysis = get_analysis_by_uri(uri)
    if analysis is None:
        raise HTTPException(404, "No librosa analysis found for this URI")
    return analysis.model_dump()


@router.get("/librosa-status")
async def get_librosa_status(uri: str = Query(...)):
    """Return whether a WAV and/or librosa analysis exist for a URI."""
    from services.librosa_service import get_analysis_by_uri, wav_path
    from services.audio_analyzer import load_audio_shape_meta as _load
    meta = _load(uri)
    has_wav = meta is not None and wav_path(meta).exists()
    has_analysis = get_analysis_by_uri(uri) is not None
    return {"has_wav": has_wav, "has_analysis": has_analysis}


@router.patch("/librosa-offset")
async def update_librosa_offset(uri: str, librosa_offset_ms: int):
    """Persist the librosa time offset for a URI to its .librosa.json sidecar."""
    from services.librosa_service import get_analysis_by_uri, librosa_json_path
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")
    analysis = get_analysis_by_uri(uri)
    if analysis is None:
        raise HTTPException(404, "No librosa analysis found")
    analysis.librosa_offset_ms = librosa_offset_ms
    jpath = librosa_json_path(meta)
    jpath.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    return {"status": "updated", "librosa_offset_ms": librosa_offset_ms}


@router.post("/librosa-analyze")
async def trigger_librosa_analyze(body: dict):
    """
    Manually trigger librosa re-analysis for a URI.
    After analysis completes, runs the embedded trigger pipeline on songs
    that don't already have triggers (matching a training profile).
    Requires a WAV file to already exist.
    Returns { status: "queued" | "no_wav" | "no_meta" }.
    """
    import asyncio as _asyncio
    from services.librosa_service import wav_path, analyze_async
    from services.audio_analyzer import load_audio_shape_meta as _load
    uri = body.get("uri", "")
    meta = _load(uri)
    if meta is None:
        return {"status": "no_meta"}
    if not wav_path(meta).exists():
        return {"status": "no_wav"}

    async def _analyze_then_suggest():
        from services.audio_shape_service import _find_profile_for_genres, _auto_generate_embedded
        from services.websocket_manager import ws_manager
        result = await analyze_async(meta)
        if result is None:
            return
        training_profile = _find_profile_for_genres(meta.genres or [])
        if training_profile is None:
            return
        await _auto_generate_embedded(
            uri, meta.title or "", meta.artist or "", meta, training_profile, ws_manager
        )

    _asyncio.create_task(_analyze_then_suggest())
    return {"status": "queued"}


@router.delete("")
async def delete_shape(uri: str = Query(...)):
    """Remove all audio shape files (NPZ, sidecar JSON, WAV, librosa JSON) so the song can be re-learned.
    Also cancels any active in-progress capture for this URI so it is not re-saved after deletion."""
    from services.librosa_service import wav_path, librosa_json_path
    from services.audio_shape_service import audio_shape_service
    meta = load_audio_shape_meta(uri)
    if meta is None:
        raise HTTPException(404, "No audio shape found")
    # Cancel active capture first so it doesn't overwrite the deleted files
    await audio_shape_service.cancel_capture(uri)
    npz_path = AUDIO_SHAPES_DIR / meta.npz_file
    for path in (
        npz_path,
        npz_path.with_suffix(".json"),
        wav_path(meta),
        librosa_json_path(meta),
    ):
        path.unlink(missing_ok=True)
    return {"status": "deleted"}
