"""
SpotFX — Suggestion Store.

Persists AI suggestion sets to storage/ai_suggestions/{track_id}.json.
One file per song, keyed by Spotify track ID.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from config import BASE_DIR
from models.ai_suggestion_set import AISuggestionSet

logger = logging.getLogger(__name__)

AI_SUGGESTIONS_DIR = BASE_DIR / "storage" / "ai_suggestions"


def _track_id(spotify_uri: str) -> str:
    """Extract track ID from 'spotify:track:{id}'."""
    return spotify_uri.split(":")[-1]


def _path(track_id: str) -> Path:
    return AI_SUGGESTIONS_DIR / f"{track_id}.json"


def _ensure_dir() -> None:
    AI_SUGGESTIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_suggestion_set(s: AISuggestionSet) -> None:
    _ensure_dir()
    path = _path(_track_id(s.spotify_uri))
    path.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    logger.debug("Saved suggestion set: %s", path.name)


def load_suggestion_set(track_id: str) -> AISuggestionSet | None:
    path = _path(track_id)
    if not path.exists():
        return None
    try:
        return AISuggestionSet.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load suggestion set %s: %s", path.name, exc)
        return None


def list_suggestion_sets() -> list[dict]:
    """Return metadata for all saved sets (no suggestions array), newest-first."""
    _ensure_dir()
    results = []
    for path in AI_SUGGESTIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append({
                "track_id":             path.stem,
                "spotify_uri":          data.get("spotify_uri", ""),
                "title":                data.get("title", ""),
                "artist":               data.get("artist", ""),
                "duration_ms":          data.get("duration_ms", 0),
                "generated_at":         data.get("generated_at", ""),
                "training_profile_id":  data.get("training_profile_id", ""),
                "training_profile_name": data.get("training_profile_name", ""),
                "suggestion_count":     len(data.get("suggestions", [])),
                "reviewed":             data.get("reviewed", False),
                "applied":              data.get("applied", False),
                "cost_usd":             data.get("cost_usd", 0.0),
                "input_tokens":         data.get("input_tokens", 0),
                "output_tokens":        data.get("output_tokens", 0),
                "model":                data.get("model", ""),
            })
        except Exception as exc:
            logger.warning("Skipping unreadable suggestion file %s: %s", path.name, exc)
    results.sort(key=lambda r: r["generated_at"], reverse=True)
    return results


def delete_suggestion_set(track_id: str) -> bool:
    path = _path(track_id)
    if not path.exists():
        return False
    path.unlink()
    logger.debug("Deleted suggestion set: %s", path.name)
    return True
