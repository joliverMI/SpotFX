"""Unit proof for spectra/services/intensity_scale.py: the ported SpotFX v2
per-song genre+bass scale (floor), plus the 2026-08-15 headroom-reserve
seam (combine_measured_and_scale) that replaced a straight multiplication.

conftest.py's autouse _isolated_intensity_scale fixture repoints
AUDIO_SHAPES_DIR / TRAINING_PROFILES_FILE / INTENSITY_SCALE_CACHE_FILE to an
empty tmp_path and resets both module-level caches before/after every test —
nothing here touches real repo storage.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from spectra import config
from spectra.services import intensity_scale as isc

SCALE_MIN, SCALE_MAX = isc.SCALE_MIN, isc.SCALE_MAX


# ── genre base ────────────────────────────────────────────────────────────

def test_genre_to_song_scale_formula_and_clamp():
    assert isc.genre_to_song_scale(1.0) == pytest.approx(0.7)
    assert isc.genre_to_song_scale(1.85) == pytest.approx(1.21)   # EDM slider
    assert isc.genre_to_song_scale(0.7) == pytest.approx(0.52)    # Rock slider
    assert isc.genre_to_song_scale(None) == pytest.approx(0.7)    # None -> 1.0
    # Clamp: nothing below SCALE_MIN or above SCALE_MAX, however extreme g is.
    assert isc.genre_to_song_scale(-100) == SCALE_MIN
    assert isc.genre_to_song_scale(100) == SCALE_MAX


def _write_training_profiles(profiles: dict) -> None:
    config.TRAINING_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.TRAINING_PROFILES_FILE.write_text(json.dumps(profiles), encoding="utf-8")


def test_resolve_genre_scale_matches_a_profile_case_insensitively():
    _write_training_profiles({
        "p1": {"name": "EDM", "genres": ["edm", "dubstep"],
              "default_intensity_scale": 1.85, "is_default": False},
        "p2": {"name": "Default", "genres": [], "default_intensity_scale": 1.0,
              "is_default": True},
    })
    assert isc.resolve_genre_scale(["Dubstep", "melodic bass"]) == pytest.approx(
        isc.genre_to_song_scale(1.85))


def test_resolve_genre_scale_falls_back_to_default_profile_on_no_match():
    _write_training_profiles({
        "p1": {"name": "EDM", "genres": ["edm"],
              "default_intensity_scale": 1.85, "is_default": False},
        "p2": {"name": "Default", "genres": [], "default_intensity_scale": 1.0,
              "is_default": True},
    })
    assert isc.resolve_genre_scale(["polka"]) == pytest.approx(isc.genre_to_song_scale(1.0))


def test_resolve_genre_scale_with_no_training_profiles_file_at_all():
    # conftest points TRAINING_PROFILES_FILE at a fresh tmp_path — nothing
    # written here, so the file genuinely doesn't exist.
    assert isc.resolve_genre_scale(["anything"]) == pytest.approx(isc.genre_to_song_scale(1.0))


# ── bass features + library percentile rank ──────────────────────────────

def _write_song(stem: str, uri: str, *, rms_low: float, rms_total: float = 0.5,
                n_bass_onsets: int, duration_ms: int = 60_000) -> None:
    shapes_dir = config.AUDIO_SHAPES_DIR
    shapes_dir.mkdir(parents=True, exist_ok=True)
    ts = np.linspace(0, duration_ms, 50)
    rms_total_arr = np.full(50, rms_total)
    rms_low_arr = np.full(50, rms_low)
    np.savez(shapes_dir / f"{stem}.npz", rms_total=rms_total_arr,
            rms_low=rms_low_arr, timestamps_ms=ts)
    (shapes_dir / f"{stem}.librosa.json").write_text(json.dumps({
        "bass_onsets": list(range(n_bass_onsets))}), encoding="utf-8")
    (shapes_dir / f"{stem}.json").write_text(json.dumps({"spotify_uri": uri}),
                                             encoding="utf-8")


def _build_library(n=20):
    """n songs, bass_db / bass_ratio / bass_onset_ps ALL strictly increasing
    with index (rms_total fixed, rms_low and onset count scale with i) — so
    every one of the three metrics ranks songs in the SAME order, making the
    combined bass_rank exactly (i + 0.5) / n for song i (no ties, no cross-
    metric disagreement to reason about by hand)."""
    for i in range(n):
        _write_song(f"song{i}", f"spotify:track:song{i}",
                   rms_low=0.01 + i * 0.001, n_bass_onsets=i + 1)


def test_bass_rank_none_below_the_20_song_floor():
    _build_library(n=19)
    assert isc.bass_rank("spotify:track:song0") is None, \
        "19 usable songs is below the 20-song minimum library size"


def test_bass_rank_none_for_an_unknown_uri():
    _build_library(n=20)
    assert isc.bass_rank("spotify:track:does-not-exist") is None


def test_bass_rank_orders_songs_by_bass_and_is_stable_under_a_second_call():
    _build_library(n=20)
    quiet = isc.bass_rank("spotify:track:song0")
    loud = isc.bass_rank("spotify:track:song19")
    assert quiet == pytest.approx(0.5 / 20)
    assert loud == pytest.approx(19.5 / 20)
    assert loud > quiet
    # Second call must read the cache, not recompute (and must agree).
    assert isc.bass_rank("spotify:track:song19") == pytest.approx(loud)


def test_compute_auto_scale_moves_within_the_genre_with_bass_rank():
    _build_library(n=20)
    quiet_scale = isc.compute_auto_scale("spotify:track:song0", genres=[])
    loud_scale = isc.compute_auto_scale("spotify:track:song19", genres=[])
    base = isc.genre_to_song_scale(1.0)   # no training_profiles.json -> 0.7
    assert quiet_scale == pytest.approx(round(base * (0.9 + 0.2 * (0.5 / 20)), 3))
    assert loud_scale == pytest.approx(round(base * (0.9 + 0.2 * (19.5 / 20)), 3))
    assert loud_scale > quiet_scale, \
        "a song ranked louder on bass should scale higher within its genre"


def test_compute_auto_scale_never_exceeds_scale_max_even_at_an_extreme_genre():
    _write_training_profiles({
        "hot": {"name": "Hot", "genres": ["hot"], "default_intensity_scale": 1.85,
               "is_default": True},
    })
    _build_library(n=20)
    scale = isc.compute_auto_scale("spotify:track:song19", genres=["hot"])
    assert scale <= SCALE_MAX
    assert scale == SCALE_MAX, \
        "genre 1.85 (EDM's own slider) already clamps at SCALE_MAX before " \
        "the bass factor even applies (0.6*1.85+0.1=1.21 * up to 1.1 > 1.25)"


def test_compute_auto_scale_returns_none_when_unrankable():
    _build_library(n=20)
    assert isc.compute_auto_scale("spotify:track:song0", genres=["anything"]) is not None
    assert isc.compute_auto_scale("spotify:track:unknown", genres=[]) is None


def test_song_scaling_factor_falls_back_to_genre_base_when_unrankable():
    _write_training_profiles({
        "rock": {"name": "Rock", "genres": ["rock"], "default_intensity_scale": 0.7,
                "is_default": True},
    })
    # No library built at all -> bass_rank is always None -> pure genre fallback.
    assert isc.song_scaling_factor("spotify:track:no-data", ["rock"]) == pytest.approx(
        isc.genre_to_song_scale(0.7))


def test_song_scaling_factor_with_no_uri_uses_genre_base_alone():
    _write_training_profiles({
        "rock": {"name": "Rock", "genres": ["rock"], "default_intensity_scale": 0.7,
                "is_default": True},
    })
    assert isc.song_scaling_factor(None, ["rock"]) == pytest.approx(
        isc.genre_to_song_scale(0.7))
    assert isc.song_scaling_factor("", ["rock"]) == pytest.approx(
        isc.genre_to_song_scale(0.7))


def test_invalidate_cache_forces_a_resweep():
    _build_library(n=20)
    isc.bass_rank("spotify:track:song0")   # populates the feature cache (20 stems)
    _write_song("song20", "spotify:track:song20", rms_low=0.05, n_bass_onsets=25)
    # analysis_reader's OWN uri->stem index self-heals on a miss, so it
    # finds the new file immediately — but intensity_scale's separate
    # feature cache doesn't re-sweep just because a lookup misses, so the
    # new song is invisible to it until invalidate_cache() runs.
    assert isc.bass_rank("spotify:track:song20") is None, \
        "the feature cache was already populated without song20 in it"
    isc.invalidate_cache()
    assert isc.bass_rank("spotify:track:song20") is not None, \
        "invalidate_cache() forces the next call to re-sweep and pick it up"


# ── the headroom-reserve seam ─────────────────────────────────────────────

def test_headroom_reserve_constant_is_point_six():
    assert isc.HEADROOM_RESERVE == 0.6


def test_combine_measured_and_scale_matches_the_admirals_worked_example():
    # "with a maximum scaling factor of 200%, the ceiling becomes 120% ...
    # rather than 200%" -- at raw intensity 1.0 (his ceiling example).
    assert isc.combine_measured_and_scale(1.0, 2.0) == pytest.approx(1.0), \
        "0.6 * 2.0 = 1.2 pre-clamp, clamped to the [0,1] intensity contract"


def test_combine_measured_and_scale_straight_math_below_the_clamp():
    assert isc.combine_measured_and_scale(0.5, 1.0) == pytest.approx(0.3)
    assert isc.combine_measured_and_scale(1.0, 1.0) == pytest.approx(0.6)


def test_combine_measured_and_scale_auto_only_ceiling_is_075():
    """Structural fact from the seam's own docstring: with no manual
    per-song override, song_scaling_factor never exceeds SCALE_MAX (1.25),
    so `final` can never exceed HEADROOM_RESERVE * SCALE_MAX = 0.75 for
    ANY auto-scaled song, even at its single most intense moment."""
    assert isc.combine_measured_and_scale(1.0, SCALE_MAX) == pytest.approx(0.75)


def test_combine_measured_and_scale_clamps_only_the_final_product():
    # A pathologically large scale (well beyond anything song_scaling_factor
    # itself would ever return) still just clamps the FINAL product to 1.0 —
    # proving there's no earlier clamp silently capping the scale term.
    assert isc.combine_measured_and_scale(1.0, 10.0) == pytest.approx(1.0)
    assert isc.combine_measured_and_scale(0.0, 10.0) == pytest.approx(0.0)


def test_combine_measured_and_scale_never_negative():
    assert isc.combine_measured_and_scale(0.0, 0.0) == 0.0
