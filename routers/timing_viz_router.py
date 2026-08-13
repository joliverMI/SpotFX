"""
SpotFX — Timing visualization data dump.

Aggregates everything that goes into computing the trigger fire time for a
song: the captured shape's stored offset history, the active Set List slot,
anchor candidates, current live timing values from the engine, and recent
xcorr sweep windows from the diagnostic CSV.

The /timing-viz frontend reads this to draw the pipeline diagram and a
table of measurements so we can spot where assumptions break.
"""
from __future__ import annotations
import csv
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from config import settings
from models.state import state
from services.audio_analyzer import load_audio_shape_meta
from services import setlist_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timing-viz", tags=["timing-viz"])

_CSV_PATH = Path(__file__).resolve().parent.parent / "storage" / "xcorr_diagnostic.csv"
_RECENT_SWEEPS_PER_URI = 5


@router.get("/dump")
async def dump(uri: str = "") -> dict:
    """All timing-relevant data for `uri` (or the currently-playing track when
    `uri` is empty). Frontend reads this to render the pipeline visualisation
    and recent-sweep tables.
    """
    if not uri and state.current_track:
        uri = state.current_track.spotify_uri
    out: dict = {"uri": uri}
    if not uri:
        return out
    meta = load_audio_shape_meta(uri)

    if meta is not None:
        out["audio_shape"] = {
            "title": meta.title,
            "artist": meta.artist,
            "captured_duration_ms": meta.duration_ms,
            "sample_interval_ms": meta.sample_interval_ms,
            "default_offset_ms": meta.timestamp_offset_ms,
            "default_quality": meta.offset_quality,
            "default_perception_trim_ms": int(getattr(meta, "perception_trim_ms", 0) or 0),
            "offset_verification": meta.offset_verification,
            "anchor_candidates": meta.anchor_candidates or [],
            "offset_history": list(meta.offset_history or [])[:10],
            "setlist_offsets": meta.setlist_offsets or {},
        }
    else:
        out["audio_shape"] = None

    # Active setlist context.
    sl_id = state.active_setlist_id
    if sl_id:
        sl = setlist_store.get_by_id(sl_id)
        out["active_setlist"] = {
            "id": sl_id,
            "name": sl.name if sl else None,
            "xcorr_enabled": getattr(sl, "xcorr_enabled", True) if sl else True,
            "xcorr_cut_buffer_ms": getattr(sl, "xcorr_cut_buffer_ms", None) if sl else None,
            "recent_offset_deltas": list(getattr(sl, "recent_offset_deltas", []) or []) if sl else [],
        }
        # Pull the active slot from setlist_offsets if present.
        if meta is not None and meta.setlist_offsets:
            out["active_setlist"]["slot"] = meta.setlist_offsets.get(sl_id)
    else:
        out["active_setlist"] = None

    # Live timing snapshot (broadcast by the engine each tick).
    timing = state.timing or {}
    out["live_timing"] = {
        "buffer_ms": timing.get("buffer_ms"),
        "ledfx_rtt_ms": timing.get("ledfx_rtt_ms"),
        "ledfx_trigger_buffer_ms": settings.ledfx_trigger_buffer_ms,
        "audio_latency_ms": settings.audio_latency_ms,
        "shape_offset_ms": timing.get("shape_offset_ms"),
        "shape_offset_quality": timing.get("shape_offset_quality"),
        "shape_offset_source": timing.get("shape_offset_source"),
        "effective_offset_ms": timing.get("effective_offset_ms"),
        "active_setlist_id": timing.get("active_setlist_id"),
    }

    # Spotify-side timing for the current track.
    cur_track = state.current_track
    if cur_track and cur_track.spotify_uri == uri:
        out["spotify_track"] = {
            "polled_duration_ms": cur_track.duration_ms,
            "interpolated_progress_ms": cur_track.interpolated_progress_ms(),
            "is_playing": cur_track.is_playing,
            "fetched_at": cur_track.fetched_at,
            "progress_ms": cur_track.progress_ms,
        }
    else:
        out["spotify_track"] = None

    # Recent sweep results from the diagnostic CSV.
    out["recent_sweeps"] = _recent_sweeps_for_uri(uri, _RECENT_SWEEPS_PER_URI)

    # Settings that affect xcorr behaviour.
    out["xcorr_settings"] = {
        "global_threshold": settings.xcorr_global_threshold,
        "wide_min_r": settings.xcorr_wide_min_r,
        "wide_top1_margin": settings.xcorr_wide_top1_margin,
        "high_confidence_r": settings.xcorr_high_confidence_r,
        "save_min_quality": float(getattr(settings, "xcorr_save_min_quality", 0.50)),
        "save_min_confirm": float(getattr(settings, "xcorr_save_min_confirm", 2)),
        "save_confirm_tol_ms": int(getattr(settings, "xcorr_save_confirm_tol_ms", 300)),
        "search_ms_base": settings.xcorr_search_ms_base,
        "cut_buffer_ms": settings.xcorr_cut_buffer_ms,
    }
    out["anchor_settings"] = {
        "scan_window_ms": settings.anchor_scan_window_ms,
        "template_radius_ms": settings.anchor_template_radius_ms,
        "min_uniqueness": settings.anchor_min_uniqueness,
        "min_rise_ratio": settings.anchor_min_rise_ratio,
        "max_candidates": settings.anchor_max_candidates,
        "search_radius_ms": settings.anchor_search_radius_ms,
        "min_match_q": settings.anchor_min_match_q,
    }
    return out


def _recent_sweeps_for_uri(uri: str, limit: int) -> list[dict]:
    """Read the last `limit` xcorr sweep rows for `uri` from the diagnostic CSV.
    Returns most-recent first.
    """
    if not _CSV_PATH.exists():
        return []
    try:
        with _CSV_PATH.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            matching: list[dict] = [row for row in reader if row.get("uri") == uri]
    except Exception as exc:
        logger.warning("timing-viz: CSV read failed: %s", exc)
        return []
    matching.reverse()  # most-recent first
    sweeps: list[dict] = []
    for row in matching[:limit]:
        windows: list[dict] = []
        for n in range(1, 16):  # _CSV_MAX_WINDOWS
            p = f"w{n}_"
            start = row.get(p + "start_ms", "")
            if start in ("", None):
                break
            try:
                windows.append({
                    "slot": n,
                    "start_ms": _to_int(row.get(p + "start_ms")),
                    "difficulty": _to_float(row.get(p + "difficulty")),
                    "winner": row.get(p + "winner") or "",
                    "offset_ms": _to_int(row.get(p + "offset_ms")),
                    "quality": _to_float(row.get(p + "quality")),
                    "r_avg": _to_float(row.get(p + "r_avg")),
                    "r_total": _to_float(row.get(p + "r_total")),
                    "r_low": _to_float(row.get(p + "r_low")),
                    "r_high": _to_float(row.get(p + "r_high")),
                    "old_r_avg": _to_float(row.get(p + "old_r_avg")),
                })
            except Exception:
                break
        sweeps.append({
            "timestamp": row.get("timestamp", ""),
            "play_type": row.get("play_type", ""),
            "duration_ms": _to_int(row.get("duration_ms")),
            "final_offset_ms": _to_int(row.get("final_offset_ms")),
            "final_quality": _to_float(row.get("final_quality")),
            "prev_offset_ms": _to_int(row.get("prev_offset_ms")),
            "n_windows": _to_int(row.get("n_windows")),
            "windows": windows,
        })
    return sweeps


def _to_int(v) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "", "None") else None
    except Exception:
        return None


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "", "None") else None
    except Exception:
        return None
