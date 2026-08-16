"""Read-only analysis storage reader — the bridge's storage half.

SPECTRA's own reader for spot-effects' analysis artifacts (bridge contract:
one-directional, read-only, no spot-effects imports):

  storage/audio_shapes/<stem>.json          — capture sidecars carrying
      spotify_uri (the URI → stem index, same skip-librosa rule as the
      spot-effects reader: *.librosa.json shares the uri field and must not
      shadow the sidecar)
  storage/audio_shapes/<stem>.librosa.json  — librosa analysis; sections
      carry start_ms/end_ms/energy_rms (normalized 0–1 per song)
  storage/training_profiles.json            — genre buckets

Section times are read RAW — the standing librosa_offset_ms rule: the
stored offset is noise, and runtime values must agree with the live
bindings, which read raw. section_energy_at() is the ported
signal_resolver._section_energy: containing section, else nearest, clamped
0–1. Missing files degrade to None — the callers' stated fallbacks apply
(intensity 0.5 neutral, no genre bucket).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from spectra import config

logger = logging.getLogger(__name__)

# uri → audio-shape file stem. Built lazily, rebuilt on miss so freshly
# captured songs appear without a restart (the spot-effects index pattern).
_shape_index: dict[str, str] = {}
_index_built = False


def _build_index() -> None:
    global _index_built
    _shape_index.clear()
    shapes_dir = config.AUDIO_SHAPES_DIR
    if shapes_dir.exists():
        for path in shapes_dir.glob("*.json"):
            if path.name.endswith(".librosa.json"):
                continue
            try:
                uri = json.loads(path.read_text(encoding="utf-8")).get(
                    "spotify_uri") or ""
            except Exception:
                continue
            if uri:
                _shape_index[uri] = path.stem
    _index_built = True


def stem_for_uri(uri: str) -> Optional[str]:
    """uri -> audio-shape file stem, rebuilding the index once on a miss so
    a freshly captured song appears without a restart."""
    global _index_built
    if not _index_built:
        _build_index()
    stem = _shape_index.get(uri)
    if stem is None:
        _build_index()
        stem = _shape_index.get(uri)
    return stem


def sections_for_uri(uri: str) -> Optional[list]:
    stem = stem_for_uri(uri)
    if stem is None:
        return None
    path = config.AUDIO_SHAPES_DIR / f"{stem}.librosa.json"
    try:
        sections = json.loads(path.read_text(encoding="utf-8")).get("sections")
        return sections or None
    except Exception:
        return None


def section_energy_at(uri: str, now_ms: int) -> Optional[float]:
    """Librosa section energy at a playback position (RAW ms), 0–1."""
    sections = sections_for_uri(uri)
    if not sections:
        return None
    best = None
    for sec in sections:
        if int(sec.get("start_ms", 0)) <= now_ms < int(sec.get("end_ms", 0)):
            best = sec
            break
    if best is None:
        best = min(sections, key=lambda s: min(
            abs(int(s.get("start_ms", 0)) - now_ms),
            abs(int(s.get("end_ms", 0)) - now_ms)))
    try:
        return max(0.0, min(1.0, float(best.get("energy_rms"))))
    except (TypeError, ValueError):
        return None


def training_profile_for_genres(genres: list[str]) -> Optional[dict]:
    """Best-matching training-profile dict for a song's genres (the ported
    _find_profile_for_genres matching: case-insensitive substring either
    way, else the default profile), or None. genre_bucket() and
    intensity_scale.py's genre base both resolve through this one matcher
    so they never disagree about which profile a song belongs to."""
    path = config.TRAINING_PROFILES_FILE
    if not path.exists():
        return None
    try:
        profiles = list(json.loads(path.read_text(encoding="utf-8")).values())
    except Exception:
        return None
    lowered = [g.lower() for g in genres]
    for profile in profiles:
        for pg in profile.get("genres", []):
            pg_lower = pg.lower()
            if any(pg_lower in sg or sg in pg_lower for sg in lowered):
                return profile
    for profile in profiles:
        if profile.get("is_default"):
            return profile
    return None


def genre_bucket(genres: list[str]) -> Optional[str]:
    """Best-matching training-profile NAME for a song's genres, or None."""
    profile = training_profile_for_genres(genres)
    return profile.get("name") if profile else None
