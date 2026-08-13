"""
SpotFX — song catalogs for the trigger-training pipeline.

list_songs_with_shapes()  — every song with a complete audio-shape capture
list_training_songs()     — shape-complete songs whose profile has triggers
                            (the pool the Triggerless page picks training
                            songs from)
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger(__name__)

from config import AUDIO_SHAPES_DIR


def list_songs_with_shapes() -> list[dict]:
    """All songs with a complete audio shape capture."""
    result = []
    for path in AUDIO_SHAPES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("capture_complete"):
                continue
            result.append({
                "uri":         data["spotify_uri"],
                "title":       data["title"],
                "artist":      data["artist"],
                "duration_ms": data["duration_ms"],
                "mark_count":  len(data.get("music_marks", [])),
                "genres":      data.get("genres", []),
                "npz_file":    data.get("npz_file", ""),
            })
        except Exception:
            pass
    return result


def list_training_songs() -> list[dict]:
    """Songs with a complete audio shape AND at least one trigger in their profile."""
    from config import PROFILES_DIR as _PROFILES_DIR

    all_shapes = {s["uri"]: s for s in list_songs_with_shapes()}
    result = []
    for path in _PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            uri = data.get("spotify_uri", "")
            triggers = data.get("triggers", [])
            if not triggers or uri not in all_shapes:
                continue
            row = dict(all_shapes[uri])
            row["trigger_count"] = len(triggers)
            result.append(row)
        except Exception:
            pass
    return result
