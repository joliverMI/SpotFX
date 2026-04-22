"""
SpotFX — Song Profile manager.

CRUD operations for SongProfile JSON files stored in storage/profiles/.
Also manages MusicEvent definitions stored in storage/events.json.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from models.song_profile import SongProfile
from models.music_event import MusicEvent
from models.triggerless_profile import TriggerlessProfile
from config import PROFILES_DIR

logger = logging.getLogger(__name__)

EVENTS_FILE = PROFILES_DIR.parent / "events.json"


# ── Song Profiles ─────────────────────────────────────────────────────────────

def _profile_path(profile: SongProfile) -> Path:
    return PROFILES_DIR / f"{profile.filename}.json"


def save_profile(profile: SongProfile) -> Path:
    """Serialize a SongProfile to its canonical JSON file."""
    path = _profile_path(profile)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    logger.debug("Saved profile: %s", path.name)
    return path


def load_profile_by_uri(spotify_uri: str) -> Optional[SongProfile]:
    """Find and load a profile by Spotify URI (primary key)."""
    for path in PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("spotify_uri") == spotify_uri:
                return SongProfile(**data)
        except Exception as exc:
            logger.warning("Could not parse profile %s: %s", path.name, exc)
    return None


def _title_artist_key(artist: str, title: str) -> str:
    return f"{artist.lower().strip()}::{title.lower().strip()}"


def load_profile_by_title_artist(title: str, artist: str) -> Optional[SongProfile]:
    """Fallback lookup by normalized title + artist (cross-mode: spotify: ↔ ledfx: URIs)."""
    target = _title_artist_key(artist, title)
    for path in PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            key = _title_artist_key(data.get("artist", ""), data.get("title", ""))
            if key == target:
                return SongProfile(**data)
        except Exception as exc:
            logger.warning("Could not parse profile %s: %s", path.name, exc)
    return None


def load_profile_by_filename(filename: str) -> Optional[SongProfile]:
    """Load a profile by its filename (without .json extension)."""
    path = PROFILES_DIR / f"{filename}.json"
    if not path.exists():
        return None
    try:
        return SongProfile(**json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        logger.warning("Could not parse profile %s: %s", path.name, exc)
        return None


def list_profiles() -> list[dict]:
    """Return lightweight metadata for all stored profiles (for search UI)."""
    results = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append({
                "filename": path.stem,
                "title": data.get("title", ""),
                "artist": data.get("artist", ""),
                "spotify_uri": data.get("spotify_uri", ""),
                "verified": data.get("verified", False),
                "labels": data.get("labels", []),
                "trigger_count": len(data.get("triggers", [])),
                "has_audio_shape": data.get("audio_shape_file") is not None,
            })
        except Exception:
            pass
    return results


def delete_profile(spotify_uri: str) -> bool:
    """Delete a profile JSON file by URI. Returns True if found and deleted."""
    profile = load_profile_by_uri(spotify_uri)
    if profile is None:
        return False
    path = _profile_path(profile)
    path.unlink(missing_ok=True)
    return True


# ── Music Events ──────────────────────────────────────────────────────────────

def _load_events_raw() -> dict:
    if EVENTS_FILE.exists():
        try:
            return json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_events_raw(data: dict) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_events() -> list[MusicEvent]:
    return [MusicEvent(**v) for v in _load_events_raw().values()]


def get_event(event_id: str) -> Optional[MusicEvent]:
    raw = _load_events_raw()
    if event_id in raw:
        return MusicEvent(**raw[event_id])
    return None


def save_event(event: MusicEvent) -> None:
    raw = _load_events_raw()
    raw[event.id] = json.loads(event.model_dump_json())
    _save_events_raw(raw)


def get_event_map() -> dict[str, dict]:
    """Return {event_id: {name, color, energy_level, ai_exposed}} for quick UI joins."""
    raw = _load_events_raw()
    return {eid: {
        "name":         v.get("name", ""),
        "color":        v.get("color", "#888"),
        "energy_level": v.get("energy_level"),
        "ai_exposed":   v.get("ai_exposed", False),
    } for eid, v in raw.items()}


def delete_event(event_id: str) -> bool:
    raw = _load_events_raw()
    if event_id not in raw:
        return False
    del raw[event_id]
    _save_events_raw(raw)
    return True


# ── Triggerless Profiles ─────────────────────────────────────────────────────

TRIGGERLESS_FILE = PROFILES_DIR.parent / "triggerless_profiles.json"


def _load_triggerless_raw() -> dict:
    if TRIGGERLESS_FILE.exists():
        try:
            return json.loads(TRIGGERLESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_triggerless_raw(data: dict) -> None:
    TRIGGERLESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRIGGERLESS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_triggerless_profiles() -> list[TriggerlessProfile]:
    return [TriggerlessProfile(**v) for v in _load_triggerless_raw().values()]


def get_triggerless_profile(profile_id: str) -> Optional[TriggerlessProfile]:
    raw = _load_triggerless_raw()
    if profile_id in raw:
        return TriggerlessProfile(**raw[profile_id])
    return None


def save_triggerless_profile(profile: TriggerlessProfile) -> None:
    raw = _load_triggerless_raw()
    # Enforce single default
    if profile.is_default:
        for k, v in raw.items():
            if k != profile.id:
                v["is_default"] = False
    raw[profile.id] = json.loads(profile.model_dump_json())
    _save_triggerless_raw(raw)


def delete_triggerless_profile(profile_id: str) -> bool:
    raw = _load_triggerless_raw()
    if profile_id not in raw:
        return False
    del raw[profile_id]
    _save_triggerless_raw(raw)
    return True


def find_triggerless_for_genres(artist_genres: list[str]) -> Optional[TriggerlessProfile]:
    """Find a triggerless profile matching any of the artist's genres.
    Falls back to the default profile if no genre match."""
    profiles = list_triggerless_profiles()
    if not profiles:
        return None
    artist_set = {g.lower().strip() for g in artist_genres}
    for p in profiles:
        profile_genres = {g.lower().strip() for g in p.genres}
        if artist_set & profile_genres:
            return p
    # Fallback to default
    for p in profiles:
        if p.is_default:
            return p
    return None
