"""Triggers ~1.45s late with the playhead correct (2026-10-06, his report:
"the playhead was on correctly but the triggers were not firing on time.
they were noticeably delayed").

Measured on his room: Bad Bunny — Caro played straight after Krewella —
Greenlights. Spot-effects' sweep locked Caro at -525ms, but SPECTRA's
bridge reported shape_offset_ms=-1977 for Caro — Greenlights' lock.
Caro's profile is a title/artist-fallback match whose own spotify_uri is
the pseudo-URI `ledfx:bad bunny:caro`, and the root trigger engine's run()
loop gated on `profile.spotify_uri == playing track`, so it skipped every
tick for Caro — including the ONLY write of state.timing — and the
previous song's lock stayed in the broadcast all play. SPECTRA's trigger
clock (bridge.effective_position_ms) then ran 1452ms behind what he heard.

Two halves, each proven here, plus their composition:
  - root: run() refreshes state.timing for a song whose profile carries a
    pseudo-URI, and stamps it with the track it belongs to;
  - SPECTRA: a timing block naming a different track is refused, never
    applied to the song playing now.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from config import settings
from models.song_profile import SongProfile
from models.state import SpotifyTrackInfo, state
from services.trigger_engine import TriggerEngine
from spectra.services.bridge import SpotEffectsBridge

CARO = "spotify:track:6it15CsDlkqB7N4lF0C1qM"
GREENLIGHTS = "spotify:track:0ZPfoFzZ4qmdyzYmG8whmn"
CARO_LOCK = -525          # spot-effects' own sweep lock for Caro that play
GREENLIGHTS_LOCK = -1977  # the previous song's lock, left in state.timing
CARO_DROP_MS = 87207      # a confirmed drop in Caro, song (heard) time


@pytest.fixture()
def caro_playing():
    """Caro loaded through main.py's title/artist fallback (pseudo-URI
    profile, real track uri as the engine identity — load_profile's
    outcome), with Greenlights' timing block still in shared state."""
    orig_state = {f.name: getattr(state, f.name) for f in dataclasses.fields(state)}
    orig_flag = settings.legacy_trigger_engine_enabled
    object.__setattr__(settings, "legacy_trigger_engine_enabled", False)

    profile = SongProfile(spotify_uri="ledfx:bad bunny:caro", title="Caro",
                          artist="Bad Bunny", duration_ms=231_000, triggers=[])
    engine = TriggerEngine()
    engine._profile = profile
    engine._last_uri = CARO
    engine._shape_offset_ms = CARO_LOCK
    engine._shape_offset_quality = 0.95

    state.current_track = SpotifyTrackInfo(
        spotify_uri=CARO, title="Caro", artist="Bad Bunny",
        duration_ms=231_000, progress_ms=60_000, is_playing=True,
        fetched_at=time.monotonic(),
    )
    state.on_target_device = True
    state.active_setlist_id = ""
    state.timing = {"uri": GREENLIGHTS, "shape_offset_ms": GREENLIGHTS_LOCK,
                    "shape_offset_quality": 0.9}
    try:
        yield engine
    finally:
        for k, v in orig_state.items():
            setattr(state, k, v)
        object.__setattr__(settings, "legacy_trigger_engine_enabled", orig_flag)


async def _run_a_few_ticks(engine):
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _bridge_with(timing, uri=CARO, progress_ms=60_000):
    bridge = SpotEffectsBridge(clock=lambda: 0.0)
    asyncio.run(bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": uri, "is_playing": True,
                  "progress_ms": progress_ms},
        "timing": timing,
    }))
    return bridge


def _heard_lateness_ms(bridge_factory, true_lock_ms: int) -> int:
    """Where the drop lands against what he HEARS: the trigger clock
    (effective position) crosses CARO_DROP_MS at some Spotify position;
    the music he hears at that moment is spotify + true lock. Positive =
    the light lands after the beat."""
    for spotify_ms in range(CARO_DROP_MS - 5000, CARO_DROP_MS + 5000):
        if bridge_factory(spotify_ms).effective_position_ms() >= CARO_DROP_MS:
            return (spotify_ms + true_lock_ms) - CARO_DROP_MS
    raise AssertionError("trigger clock never reached the drop")


# ── root half ────────────────────────────────────────────────────────────


def test_run_loop_refreshes_timing_for_a_pseudo_uri_profile(caro_playing):
    asyncio.run(_run_a_few_ticks(caro_playing))
    assert state.timing.get("shape_offset_ms") == CARO_LOCK, (
        "run() skipped a title/artist-fallback song — the previous song's "
        "lock is still what SPECTRA reads")
    assert state.timing.get("uri") == CARO


def test_timing_names_the_track_it_belongs_to_for_a_real_uri_profile(caro_playing):
    caro_playing._profile = SongProfile(spotify_uri=CARO, title="Caro",
                                        artist="Bad Bunny",
                                        duration_ms=231_000, triggers=[])
    asyncio.run(_run_a_few_ticks(caro_playing))
    assert state.timing.get("uri") == CARO
    assert state.timing.get("shape_offset_ms") == CARO_LOCK


# ── SPECTRA half ─────────────────────────────────────────────────────────


def test_bridge_refuses_a_timing_block_from_another_track():
    bridge = _bridge_with({"uri": GREENLIGHTS, "shape_offset_ms": GREENLIGHTS_LOCK})
    assert bridge.shape_offset_ms() is None
    assert bridge.effective_position_ms() == 60_000
    assert bridge.refused_timing_uri() == GREENLIGHTS
    assert bridge.status()["track"]["timing_refused_for_uri"] == GREENLIGHTS


def test_bridge_uses_a_timing_block_for_this_track():
    bridge = _bridge_with({"uri": CARO, "shape_offset_ms": CARO_LOCK})
    assert bridge.shape_offset_ms() == CARO_LOCK
    assert bridge.effective_position_ms() == 60_000 + CARO_LOCK
    assert bridge.refused_timing_uri() is None


def test_bridge_still_uses_an_unstamped_block_from_an_older_spot_effects():
    bridge = _bridge_with({"shape_offset_ms": CARO_LOCK})
    assert bridge.shape_offset_ms() == CARO_LOCK
    assert bridge.refused_timing_uri() is None


# ── the measured lateness, reproduced and fixed ─────────────────────────


def test_the_measured_lateness_reproduces_with_the_stale_unstamped_block():
    """The pre-fix world exactly: an unstamped Greenlights block during
    Caro (the bridge cannot tell, so it applies it) — the drop lands
    1452ms after the beat he hears, the delay he reported."""
    late = _heard_lateness_ms(
        lambda pos: _bridge_with({"shape_offset_ms": GREENLIGHTS_LOCK},
                                 progress_ms=pos),
        CARO_LOCK)
    assert late == GREENLIGHTS_LOCK * -1 + CARO_LOCK == 1452


def test_root_and_bridge_together_land_the_drop_on_the_beat(caro_playing):
    """Composition: the root loop writes the block the bridge reads (via
    the websocket 'state' payload, payload["timing"] = state.timing)."""
    asyncio.run(_run_a_few_ticks(caro_playing))
    timing = dict(state.timing)
    late = _heard_lateness_ms(
        lambda pos: _bridge_with(timing, progress_ms=pos), CARO_LOCK)
    assert late == 0
