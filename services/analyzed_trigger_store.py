"""
SpotFX — Cache for analyzed triggers.

`_generate_analyzed_triggers` runs the embedded pipeline (librosa shape +
`suggest_triggers`) and is the dominant cost on a URI change (~0.5–2s).
Results are deterministic given (song audio shape, training profile), so
we persist them to disk under storage/analyzed_triggers/ and reuse them
on subsequent plays.

Invalidation: a sha256 of the training profile's JSON is stored with the
cache entry. If the profile changes (genre match flips, or any field is
edited), the hash differs and we regenerate.

One file per track_id — we only care about the latest valid set.
"""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from config import BASE_DIR
from services.training_profile_manager import TrainingProfile

logger = logging.getLogger(__name__)

ANALYZED_TRIGGERS_DIR = BASE_DIR / "storage" / "analyzed_triggers"


class CachedTrigger(BaseModel):
    id: str
    timestamp_ms: int
    event_id: str
    labels: list[str] = []
    intensity: Optional[float] = None  # generator intensity; None → runtime falls back to section energy


class CachedAnalyzedTriggers(BaseModel):
    track_id: str
    training_profile_id: str
    training_profile_hash: str
    generated_at: str
    triggers: list[CachedTrigger]


def hash_profile(profile: TrainingProfile) -> str:
    """Stable content hash over the profile's model_dump_json()."""
    return hashlib.sha256(profile.model_dump_json().encode("utf-8")).hexdigest()


def _path_for(track_id: str) -> Path:
    return ANALYZED_TRIGGERS_DIR / f"{track_id}.json"


def load(track_id: str) -> Optional[CachedAnalyzedTriggers]:
    p = _path_for(track_id)
    if not p.exists():
        return None
    try:
        return CachedAnalyzedTriggers.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read analyzed-trigger cache %s: %s", p, exc)
        return None


def is_valid(cached: CachedAnalyzedTriggers, profile: TrainingProfile) -> bool:
    return (
        cached.training_profile_id == profile.id
        and cached.training_profile_hash == hash_profile(profile)
    )


def save(track_id: str, profile: TrainingProfile, triggers: list) -> None:
    """Write the cache entry. `triggers` may be MusicTrigger instances or dicts."""
    ANALYZED_TRIGGERS_DIR.mkdir(parents=True, exist_ok=True)
    payload = CachedAnalyzedTriggers(
        track_id=track_id,
        training_profile_id=profile.id,
        training_profile_hash=hash_profile(profile),
        generated_at=datetime.now(timezone.utc).isoformat(),
        triggers=[_to_cached_trigger(t) for t in triggers],
    )
    _path_for(track_id).write_text(
        payload.model_dump_json(indent=2), encoding="utf-8"
    )


def generate_for_uri(spotify_uri: str, *, save_cache: bool = True) -> Optional[list[CachedTrigger]]:
    """Run the full analyzed-trigger pipeline and (optionally) persist the result.

    Returns CachedTrigger list on success, or None when librosa data or a
    matching training profile isn't available. Safe to call from background
    threads — all work is local I/O + CPU; no shared mutable state beyond
    the cache file written atomically at the end.
    """
    # Local imports so this module stays importable from capture-time code
    # without pulling in the trigger engine / websocket stack.
    from services.librosa_service import get_analysis_by_uri
    from services.embedded_trigger_service import suggest_triggers
    from services.audio_shape_service import _find_profile_for_genres
    from services.profile_manager import load_profile_by_uri

    la = get_analysis_by_uri(spotify_uri)
    if not la or not la.beats:
        return None

    sp = load_profile_by_uri(spotify_uri)
    genres = list(sp.artist_genre) if sp and sp.artist_genre else []
    tp_data = _find_profile_for_genres(genres)
    if not tp_data:
        logger.info(
            "Analyzed triggers (cache): no matching training profile for genres %s uri=%s",
            genres, spotify_uri,
        )
        return None

    tp = TrainingProfile(**tp_data)

    available: set[str] = set()
    for attr in (
        "song_start_event_id", "beat_start_event_id", "song_end_event_id",
        "drop_event_id", "lull_event_id", "charge_event_id",
        "quiet_event_id", "scene_fill_event_id", "flare_event_id",
        "flare_low_event_id", "flare_mid_event_id", "flare_high_event_id",
        "flare_scene_event_id",
    ):
        eid = getattr(tp, attr, "")
        if eid:
            available.add(eid)
    if not available:
        return None

    raw = suggest_triggers(
        target_uri=spotify_uri,
        all_training_uris=[],
        available_event_ids=available,
        training_profile=tp,
        _cached_analysis=la,
    )
    if not raw:
        return None

    triggers = [
        CachedTrigger(
            id=f"analyzed_{r['event_id']}_{r['timestamp_ms']}",
            timestamp_ms=r["timestamp_ms"],
            event_id=r["event_id"],
            labels=list(r.get("labels") or []),
            intensity=r.get("intensity"),
        )
        for r in raw
    ]

    if save_cache:
        track_id = spotify_uri.split(":")[-1]
        save(track_id, tp, triggers)
        logger.info(
            "Analyzed triggers: generated %d and cached for %s (profile: %s)",
            len(triggers), spotify_uri, tp.name,
        )
    return triggers


def _to_cached_trigger(t) -> CachedTrigger:
    if isinstance(t, CachedTrigger):
        return t
    if hasattr(t, "model_dump"):
        d = t.model_dump()
    elif isinstance(t, dict):
        d = t
    else:
        d = {"id": t.id, "timestamp_ms": t.timestamp_ms, "event_id": t.event_id,
             "labels": list(t.labels or []), "intensity": getattr(t, "intensity", None)}
    return CachedTrigger(
        id=d.get("id", ""),
        timestamp_ms=int(d.get("timestamp_ms", 0)),
        event_id=d.get("event_id", ""),
        labels=list(d.get("labels") or []),
        intensity=d.get("intensity"),
    )
