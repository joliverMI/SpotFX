"""services/trigger_engine.py's TriggerEngine.load_profile/apply_save —
the engine's identity must track the track actually playing, not the
loaded profile's own spotify_uri.

Root cause (data/false-lock-continued-search/report.md, section 3/"Ship
1"): main.py's title/artist fallback can load an OLDER profile whose own
spotify_uri is a stale `ledfx:artist:title` pseudo-URI (authored before
the song had a real spotify: match) while the real track plays under
`spotify:track:...`. Before this fix, load_profile stamped
`self._last_uri` from `profile.spotify_uri`, so apply_save's
`uri != self._last_uri` gate silently dropped every sweep snap for that
song all play — play-best stayed 0.00 and a hard lock was unreachable,
even when the sweep had a confident measurement in hand (tonight: RLNDT
at Q .982, Otra Noche en Miami at Q .91).
"""
from __future__ import annotations

import dataclasses

import pytest

from models.song_profile import SongProfile
from models.state import state
from services.trigger_engine import TriggerEngine

PSEUDO_URI = "ledfx:bad bunny:rlndt"
TRACK_URI = "spotify:track:rlndt-real-uri"


@pytest.fixture()
def clean_state():
    orig = {f.name: getattr(state, f.name) for f in dataclasses.fields(state)}
    state.current_track = None
    try:
        yield
    finally:
        for k, v in orig.items():
            setattr(state, k, v)


def _pseudo_profile() -> SongProfile:
    return SongProfile(
        spotify_uri=PSEUDO_URI,
        title="RLNDT", artist="Bad Bunny",
        duration_ms=200_000,
        triggers=[],
    )


def test_load_profile_records_the_track_uri_not_the_profiles_own(clean_state):
    engine = TriggerEngine()
    profile = _pseudo_profile()

    engine.load_profile(profile, track_uri=TRACK_URI)

    assert engine._last_uri == TRACK_URI
    assert engine._profile is profile


def test_apply_save_lands_a_sweep_snap_for_a_ledfx_profile_matched_song(clean_state):
    """The exact regression the report asks for: load a profile whose
    spotify_uri is a ledfx:x:y pseudo-URI for a track actually playing
    under spotify:track:z, drive apply_save with THAT track's uri, and
    assert the snap lands and _play_best_quality moves. Before the fix,
    apply_save's uri != self._last_uri check compared against
    profile.spotify_uri (the pseudo-URI) and always returned False here."""
    engine = TriggerEngine()
    profile = _pseudo_profile()
    engine.load_profile(profile, track_uri=TRACK_URI)

    assert engine._play_best_quality == 0.0

    applied = engine.apply_save(TRACK_URI, -475, 0.98, source="sweep")

    assert applied is True
    assert engine._play_best_quality == pytest.approx(0.98)
    assert engine._shape_offset_ms == -475


def test_apply_save_still_rejects_a_genuinely_different_song(clean_state):
    """A snap for a song that is NOT the one currently loaded must still
    be dropped — the fix narrows the identity to the real track, it does
    not disable the gate."""
    engine = TriggerEngine()
    profile = _pseudo_profile()
    engine.load_profile(profile, track_uri=TRACK_URI)

    applied = engine.apply_save("spotify:track:some-other-song", -900, 0.91, source="sweep")

    assert applied is False
    assert engine._play_best_quality == 0.0


def test_apply_save_skip_is_logged_not_silent(clean_state, caplog):
    engine = TriggerEngine()
    profile = _pseudo_profile()
    engine.load_profile(profile, track_uri=TRACK_URI)

    with caplog.at_level("INFO", logger="services.trigger_engine"):
        applied = engine.apply_save("spotify:track:some-other-song", -900, 0.91, source="sweep")

    assert applied is False
    assert any("skip snap" in r.message for r in caplog.records)


def test_load_profile_with_no_track_uri_falls_back_to_profiles_own(clean_state):
    """guest_source.py and offline callers with no separate track identity
    keep working exactly as before — profile.spotify_uri already equals
    the track for them."""
    engine = TriggerEngine()
    profile = SongProfile(
        spotify_uri="spotify:track:guest-synth", title="x", artist="y",
        duration_ms=100_000, triggers=[],
    )

    engine.load_profile(profile)

    assert engine._last_uri == "spotify:track:guest-synth"
