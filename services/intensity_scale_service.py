"""
SpotFX — auto-computed per-song intensity scale (0-2 = 0-200%).

Ranks a song against the analyzed library on a composite of three
cross-song-comparable signals and maps the rank to a starting
SongProfile.intensity_scale (stored with source="auto"; a user's Now Playing
slider always wins over it):

  - mean RMS in dB from the captured audio-shape NPZ. This is the raw loopback
    capture, so it IS comparable across songs — everything in the librosa JSON
    (beat rms, section energy_rms) is per-song normalized and useless here.
  - tempo_bpm from the librosa analysis
  - onset density: full-spectrum onsets per second of capture

Each metric is percentile-ranked over the library; the mean rank r in [0,1]
maps to scale = 0.6 + 0.8*r — the library median lands at 100%, the spread is
60-140% — then clamps to 0-2. Songs missing the NPZ or librosa file yield None
(caller falls through to the genre scaler, then 100%).

Per-song features are cached in storage/cache/intensity_scale_features.json
keyed by file stem + source mtimes, so the first library sweep (~700 NPZ
loads, seconds) is one-time and later calls are incremental. All functions are
synchronous; the engine calls them via run_in_executor.
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

CACHE_FILE = Path("storage/cache/intensity_scale_features.json")

_lock = threading.Lock()
_features: dict[str, dict] | None = None  # stem -> {mtime, rms_db, tempo_bpm, onset_density}


def _compute_stem_features(npz_path: Path) -> Optional[dict]:
    """Feature dict for one song, or None when either source file is unusable."""
    lib_path = npz_path.parent / (npz_path.stem + ".librosa.json")
    try:
        with np.load(npz_path) as z:
            rms = np.asarray(z["rms_total"], dtype=np.float64)
            ts = np.asarray(z["timestamps_ms"], dtype=np.float64)
        if rms.size == 0 or ts.size < 2:
            return None
        duration_s = float(ts[-1] - ts[0]) / 1000.0
        if duration_s <= 0:
            return None
        mean_rms = float(np.mean(rms))
        rms_db = 20.0 * math.log10(max(mean_rms, 1e-9))
        raw = json.loads(lib_path.read_text(encoding="utf-8"))
        tempo = float(raw.get("tempo_bpm") or 0.0)
        onsets = raw.get("onsets") or []
        if tempo <= 0:
            return None
        return {
            "rms_db": rms_db,
            "tempo_bpm": tempo,
            "onset_density": len(onsets) / duration_s,
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


def compute_auto_scale(spotify_uri: str) -> Optional[float]:
    """Auto intensity scale for a song, or None when it can't be ranked
    (missing capture/librosa data, or a too-small library)."""
    from services.audio_analyzer import load_audio_shape_meta

    meta = load_audio_shape_meta(spotify_uri)
    if meta is None:
        return None
    feats_by_stem = _load_features()
    stem = Path(meta.npz_file).stem if getattr(meta, "npz_file", None) else None
    song = feats_by_stem.get(stem or "")
    if not song or "rms_db" not in song:
        return None
    usable = [f for f in feats_by_stem.values() if "rms_db" in f]
    if len(usable) < 20:  # not enough library to rank against
        return None
    ranks = [
        _percentile_rank([f["rms_db"] for f in usable], song["rms_db"]),
        _percentile_rank([f["tempo_bpm"] for f in usable], song["tempo_bpm"]),
        _percentile_rank([f["onset_density"] for f in usable], song["onset_density"]),
    ]
    r = sum(ranks) / len(ranks)
    scale = 0.6 + 0.8 * r
    return round(max(0.0, min(2.0, scale)), 3)
