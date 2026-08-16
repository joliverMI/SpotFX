"""SPECTRA — per-song, genre-anchored render-intensity scale (the ported
SpotFX v2 mechanism, PLUS the Admiral's 2026-08-15 headroom-reserve
correction to how it combines with a moment's measured intensity).

THE FLOOR (ported verbatim from services/intensity_scale_service.py): a
training profile's genre slider is a RELATIVE energy dial, mapped into
song-space via

    genre_to_song_scale(g) = clamp(0.6 * g + 0.1, 0.30, 1.25)

calibrated 2026-07-29 against the Admiral's own reference songs — these
are SCALING FACTORS (a multiplier on measured intensity), not target
intensities: Dopamine's factor ~= 1.20 (120%), Let It Be's ~= 0.50 (50%),
Soy Peor's ~= 1.00 (100%, i.e. NO adjustment — not "maximum"), against
sliders EDM 1.85 / Rock 0.7 / Trap 1.35 (storage/training_profiles.json,
read-only). Units matter here: a 100% factor is mid-range on the [30%,
125%] auto scale, nowhere near a ceiling — conflating "his calibration
factor is 100%" with "he hears this song as maximum intensity" is a
category error a 2026-08-15 report made and then retracted; don't repeat
it. A per-song BASS factor then nudges within the genre:

    auto = clamp(genre_base * (0.9 + 0.2 * r_bass), 0.30, 1.25)

where r_bass is the song's mean percentile rank across the analysed
library on three bass-forward signals (mean rms_low in dB, bass ratio,
bass-onset density) read from the SAME raw capture files the read-only
bridge already reads (storage/audio_shapes/*.npz + *.librosa.json —
analysis_reader.py's own contract: no spot-effects import, storage read
only). No AUTO value ever exceeds 125% (auto_scaling_factor(), always
clamped to [SCALE_MIN, SCALE_MAX]) — SpotFX let a human's manual per-song
slider go higher (up to 200%), and so does SPECTRA's own equivalent,
intensity_scale_marks.py (2026-08-15 ruling: "he marks the track;
automatic never does" — see song_scaling_factor()'s docstring).

Per-song bass features are cached in SPECTRA's OWN store
(config.INTENSITY_SCALE_CACHE_FILE, storage/spectra/intensity_scale_
features.json) — deliberately NOT SpotFX's storage/cache/intensity_scale_
features_v2.json, so this never contends with the live spot-effects
process writing its own cache (the storage-ownership pattern every other
SPECTRA store follows). Keyed by stem + source mtimes; the first library
sweep is one-time; every function here is synchronous.

THE HEADROOM-RESERVE CORRECTION (2026-08-15, the Admiral's binding spec,
corr=<report>): the previous plan was a straight multiplication of the
per-song factor into the moment's measured intensity — exactly what he
flagged as wrong ("currently it is just a straight multiplication of a
factor"). His replacement:

    final = measured_intensity * HEADROOM_RESERVE * song_scaling_factor

combine_measured_and_scale() below is THE SEAM: the one function this
formula lives in. See its docstring for why 0.6 is a deliberate gate, not
a fudge factor, and for the clamp order (load-bearing: clamping the wrong
term at the wrong time silently destroys the gate).
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from spectra import config
from spectra.services import analysis_reader

logger = logging.getLogger(__name__)

SCALE_MIN = 0.30
SCALE_MAX = 1.25   # hard cap for the auto (genre + bass) scale

_METRICS = ("bass_db", "bass_ratio", "bass_onset_ps")

_lock = threading.Lock()
_features: dict[str, dict] | None = None  # stem -> {mtime, bass_db, ...}


# ── the per-song scale (ported floor) ────────────────────────────────────

def genre_to_song_scale(genre_value: Optional[float]) -> float:
    """Map a raw genre-slider value to a song-space starting scale."""
    g = 1.0 if genre_value is None else float(genre_value)
    return max(SCALE_MIN, min(SCALE_MAX, 0.6 * g + 0.1))


def resolve_genre_scale(genres: list[str]) -> float:
    """Song-space starting scale for a genre list (matching training
    profile's slider through genre_to_song_scale; no match -> the default
    profile's, same as analysis_reader.genre_bucket's own fallback)."""
    profile = analysis_reader.training_profile_for_genres(genres or [])
    raw = profile.get("default_intensity_scale", 1.0) if profile else 1.0
    return genre_to_song_scale(raw if raw is not None else 1.0)


def _compute_stem_features(npz_path: Path) -> Optional[dict]:
    """Bass feature dict for one song, or None when a source file is
    unusable. Identical formula to SpotFX's intensity_scale_service."""
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
        logger.debug("intensity-scale features failed for %s", npz_path.name,
                    exc_info=True)
        return None


def _load_features() -> dict[str, dict]:
    """Load SPECTRA's own cache and sweep storage/audio_shapes (read-only
    source), recomputing stale/new stems (keyed on npz + librosa mtimes).
    Returns {stem: features}."""
    global _features
    with _lock:
        if _features is not None:
            return _features
        cache_file = config.INTENSITY_SCALE_CACHE_FILE
        cache: dict[str, dict] = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        out: dict[str, dict] = {}
        dirty = False
        for npz_path in Path(config.AUDIO_SHAPES_DIR).glob("*.npz"):
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
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(out), encoding="utf-8")
                tmp.replace(cache_file)
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
    """The song's mean bass percentile rank (0-1) over the analyzed
    library, or None when it has no capture/librosa data or the library
    is too small to rank against (<20 usable songs)."""
    stem = analysis_reader.stem_for_uri(spotify_uri)
    if stem is None:
        return None
    feats_by_stem = _load_features()
    song = feats_by_stem.get(stem)
    if not song or _METRICS[0] not in song:
        return None
    usable = [f for f in feats_by_stem.values() if _METRICS[0] in f]
    if len(usable) < 20:
        return None
    ranks = [_percentile_rank([f[m] for f in usable], song[m]) for m in _METRICS]
    return sum(ranks) / len(ranks)


def compute_auto_scale(spotify_uri: str, genres: Optional[list[str]] = None) -> Optional[float]:
    """Auto intensity scale: genre base x bass-rank factor (0.9-1.1),
    clamped to 30-125%. None when the song can't be ranked (caller falls
    back to the genre base alone via song_scaling_factor)."""
    r = bass_rank(spotify_uri)
    if r is None:
        return None
    base = resolve_genre_scale(genres or [])
    scale = base * (0.9 + 0.2 * r)
    return round(max(SCALE_MIN, min(SCALE_MAX, scale)), 3)


def auto_scaling_factor(spotify_uri: Optional[str], genres: Optional[list[str]] = None) -> float:
    """The AUTO-only resolution, IGNORING any manual mark: the bass-ranked
    auto scale when computable, else the genre base alone (SpotFX's same
    fallback order). Always capped to [SCALE_MIN, SCALE_MAX] (30-125%) —
    this is the half of the 0.75 ceiling (combine_measured_and_scale's
    docstring) that a manual mark exists to let him bypass. No song at
    all -> the genre base for an empty genre list (0.7, the SAME number
    SpotFX shows an unmatched song, not a separate neutral 1.0 — this
    stays faithful to the ported formula rather than inventing a new
    fallback)."""
    if not spotify_uri:
        return resolve_genre_scale(genres or [])
    auto = compute_auto_scale(spotify_uri, genres)
    if auto is not None:
        return auto
    return resolve_genre_scale(genres or [])


def song_scaling_factor(spotify_uri: Optional[str], genres: Optional[list[str]] = None) -> float:
    """Public resolver, and the ONE place a manual mark takes effect
    (2026-08-15 ruling — spectra/services/intensity_scale_marks.py): a
    mark on this song wins outright, clamped to its own [0, 2.0] range,
    NEVER re-clamped down into the AUTO [SCALE_MIN, SCALE_MAX] range —
    that's the whole point, it's the one way past the 0.75 ceiling.
    No mark -> falls through to auto_scaling_factor() unchanged."""
    if spotify_uri:
        from spectra.services import intensity_scale_marks
        mark = intensity_scale_marks.get_mark(spotify_uri)
        if mark is not None:
            return mark
    return auto_scaling_factor(spotify_uri, genres)


# ── the headroom-reserve seam (2026-08-15 correction) ────────────────────

HEADROOM_RESERVE = 0.6
"""Deliberate ceiling reserve, NOT a fudge factor and NOT a volume trim —
the Admiral's own words: "this allows me to gate certain high-intensities
by requiring a high scaling factor on a track so we do not get loud hype
scenes unless its a hype track." Worked example he gave: at a maximum
scaling factor of 200% the reachable ceiling is 0.6 * 2.0 = 120%, not
200% — the top of the intensity range is UNREACHABLE unless a track has
earned a high enough song_scaling_factor to buy back the reserve. Do not
"simplify" this constant away; that silently deletes the gate he asked
for."""


def combine_measured_and_scale(measured_intensity: float,
                                song_scaling_factor: float) -> float:
    """THE SEAM: combines a moment's measured (raw, unscaled) intensity
    with the current song's scaling factor into the final render
    intensity every fire/bind/band-select consumes.

        final = measured_intensity * HEADROOM_RESERVE * song_scaling_factor

    CLAMP ORDER IS LOAD-BEARING. The only clamp in this function is the
    final one, applied to the full three-term product, LAST. There is
    deliberately no intermediate clamp on HEADROOM_RESERVE * song_scaling_
    factor (or on song_scaling_factor alone) before it multiplies
    measured_intensity — clamping that product to <=1.0 early would cap
    every song's effective scale at the same ceiling regardless of how
    "hype" it is, which defeats the gate this function exists to
    implement. (song_scaling_factor's OWN clamp to [SCALE_MIN, SCALE_MAX]
    already happened earlier, inside song_scaling_factor()/compute_auto_
    scale() — that's a different, independent clamp on a different term,
    not this one.)

    THE 0.75 CEILING, AND THE ONE WAY PAST IT (2026-08-15 ruling): an
    AUTO-resolved song_scaling_factor (auto_scaling_factor(), no manual
    mark) is always <= SCALE_MAX = 1.25, so `final` at that song's single
    most intense moment (measured_intensity = 1.0) can never exceed
    HEADROOM_RESERVE * SCALE_MAX = 0.75 — deliberate, his ruling: "0.75
    STANDS as the automatic ceiling. Nothing automatic ever exceeds it."
    His own "120% ceiling" worked example (0.6 * 2.0) is reachable only
    through a manual per-track mark (spectra/services/intensity_scale_
    marks.py, song_scaling_factor()'s own docstring) — "he marks the
    track; automatic never does." Without that release valve the 0.6
    reserve would be a CAP with no way to open it, not a GATE.
    """
    final = measured_intensity * HEADROOM_RESERVE * song_scaling_factor
    return max(0.0, min(1.0, final))


def render_intensity(spotify_uri: Optional[str], genres: Optional[list[str]],
                     measured_intensity: float) -> float:
    """Convenience wrapper: song_scaling_factor() + combine_measured_and_
    scale() in one call, for callers that just want "this moment's final
    render intensity for this song" (trigger_engine, scene_sequencer)."""
    factor = song_scaling_factor(spotify_uri, genres)
    return combine_measured_and_scale(measured_intensity, factor)
