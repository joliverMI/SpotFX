"""
SpotFX — auto-computed per-song intensity scale (v2, genre-anchored).

The genre slider on a Triggerless training profile is a RELATIVE energy dial;
it maps to a song-space starting scale via

    genre_to_song_scale(g) = clamp(0.6 * g + 0.1, 0.30, 1.25)

calibrated 2026-07-29 against Javi's reference songs (Dopamine ≈ 120%,
Let It Be ≈ 50%, Soy Peor ≈ 100% with sliders EDM 1.85 / Rock 0.7 /
Trap 1.35). A per-song BASS factor then nudges within the genre:

    auto = clamp(genre_base * (0.9 + 0.2 * r_bass), 0.30, 1.25)

where r_bass is the song's mean percentile rank over the analyzed library on
three bass-forward signals from the raw loopback capture + librosa v3:
mean rms_low in dB, bass ratio (mean rms_low / mean rms_total), and bass-onset
density. v1 used mean-RMS/tempo/onset-density — all three proved wrong on the
reference songs (librosa octave-doubles ballad tempos, onset density is
ANTI-correlated with perceived energy, and loudness-war masters compress mean
RMS into a ~1 dB band).

No auto/genre value ever exceeds 125% — only the user's manual slider can.

Per-song features are cached in storage/cache/intensity_scale_features_v2.json
keyed by stem + source mtimes; the first library sweep is one-time. All
functions are synchronous; the engine calls them via run_in_executor.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from config import AUDIO_SHAPES_DIR

logger = logging.getLogger(__name__)

CACHE_FILE = Path("storage/cache/intensity_scale_features_v2.json")

SCALE_MIN = 0.30
SCALE_MAX = 1.25   # hard cap for anything not set by hand

_METRICS = ("bass_db", "bass_ratio", "bass_onset_ps")

_lock = threading.Lock()
_features: dict[str, dict] | None = None  # stem -> {mtime, bass_db, ...}


def genre_to_song_scale(genre_value: float | None) -> float:
    """Map a raw genre-slider value to a song-space starting scale."""
    g = 1.0 if genre_value is None else float(genre_value)
    return max(SCALE_MIN, min(SCALE_MAX, 0.6 * g + 0.1))


def resolve_genre_scale(genres: list[str]) -> float:
    """Song-space starting scale for a genre list (matching training profile's
    slider through genre_to_song_scale; no match → the default profile's)."""
    try:
        from services.audio_shape_service import _find_profile_for_genres
        tp = _find_profile_for_genres(genres or [])
        raw = tp.get("default_intensity_scale", 1.0) if tp else 1.0
        return genre_to_song_scale(raw if raw is not None else 1.0)
    except Exception:
        logger.debug("genre scale lookup failed", exc_info=True)
        return genre_to_song_scale(1.0)


def _compute_stem_features(npz_path: Path) -> Optional[dict]:
    """Bass feature dict for one song, or None when a source file is unusable."""
    lib_path = npz_path.parent / (npz_path.stem + ".librosa.json")
    try:
        with np.load(npz_path) as z:
            rms_total = np.asarray(z["rms_total"], dtype=np.float64)
            rms_low = np.asarray(z["rms_low"], dtype=np.float64)
            ts = np.asarray(z["timestamps_ms"], dtype=np.float64)
        if rms_total.size == 0 or ts.size < 2:
            return None
        duration_s = float(ts[-1] - ts[0]) / 1000.0
        if duration_s <= 0:
            return None
        raw = json.loads(lib_path.read_text(encoding="utf-8"))
        mean_total = float(np.mean(rms_total))
        mean_low = float(np.mean(rms_low))
        return {
            "bass_db": 20.0 * math.log10(max(mean_low, 1e-9)),
            "bass_ratio": mean_low / max(mean_total, 1e-9),
            "bass_onset_ps": len(raw.get("bass_onsets") or []) / duration_s,
        }
    except FileNotFoundError:
        return None
    except Exception:
        logger.debug("intensity-scale features failed for %s", npz_path.name, exc_info=True)
        return None


def _load_features() -> dict[str, dict]:
    """Load the cache and sweep the audio-shapes dir, recomputing stale/new
    stems (keyed on npz + librosa mtimes). Returns {stem: features}."""
    global _features
    with _lock:
        if _features is not None:
            return _features
        cache: dict[str, dict] = {}
        if CACHE_FILE.exists():
            try:
                cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        out: dict[str, dict] = {}
        dirty = False
        for npz_path in Path(AUDIO_SHAPES_DIR).glob("*.npz"):
            stem = npz_path.stem
            lib_path = npz_path.parent / (stem + ".librosa.json")
            try:
                mtime = npz_path.stat().st_mtime + (
                    lib_path.stat().st_mtime if lib_path.exists() else 0.0)
            except OSError:
                continue
            cached = cache.get(stem)
            if cached is not None and cached.get("mtime") == mtime:
                out[stem] = cached
                continue
            feats = _compute_stem_features(npz_path)
            dirty = True
            if feats is not None:
                feats["mtime"] = mtime
                out[stem] = feats
            else:
                out[stem] = {"mtime": mtime}  # negative-cache unusable stems
        if dirty or set(out) != set(cache):
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = CACHE_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(out), encoding="utf-8")
                tmp.replace(CACHE_FILE)
            except Exception:
                logger.warning("intensity-scale cache write failed", exc_info=True)
        _features = out
        return out


def invalidate_cache() -> None:
    """Force the next call to re-sweep (e.g. after a new capture)."""
    global _features
    with _lock:
        _features = None


def _percentile_rank(values: list[float], v: float) -> float:
    """Fraction of library values strictly below v, ties counted half."""
    if not values:
        return 0.5
    below = sum(1 for x in values if x < v)
    ties = sum(1 for x in values if x == v)
    return (below + 0.5 * ties) / len(values)


def bass_rank(spotify_uri: str) -> Optional[float]:
    """The song's mean bass percentile rank (0-1) over the analyzed library,
    or None when it has no capture/librosa data or the library is too small."""
    from services.audio_analyzer import load_audio_shape_meta

    meta = load_audio_shape_meta(spotify_uri)
    if meta is None or not getattr(meta, "npz_file", None):
        return None
    feats_by_stem = _load_features()
    song = feats_by_stem.get(Path(meta.npz_file).stem)
    if not song or _METRICS[0] not in song:
        return None
    usable = [f for f in feats_by_stem.values() if _METRICS[0] in f]
    if len(usable) < 20:
        return None
    ranks = [_percentile_rank([f[m] for f in usable], song[m]) for m in _METRICS]
    return sum(ranks) / len(ranks)


def compute_auto_scale(spotify_uri: str, genres: list[str] | None = None) -> Optional[float]:
    """Auto intensity scale: genre base × bass-rank factor (0.9–1.1), clamped
    to 30–125%. None when the song can't be ranked (caller may fall back to
    the genre base alone). `genres` defaults to the capture meta's genre list."""
    r = bass_rank(spotify_uri)
    if r is None:
        return None
    if genres is None:
        from services.audio_analyzer import load_audio_shape_meta
        meta = load_audio_shape_meta(spotify_uri)
        genres = list(getattr(meta, "genres", None) or []) if meta else []
    base = resolve_genre_scale(genres)
    scale = base * (0.9 + 0.2 * r)
    return round(max(SCALE_MIN, min(SCALE_MAX, scale)), 3)
