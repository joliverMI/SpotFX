"""services/trigger_engine.py's run() loop, gated by
settings.legacy_trigger_engine_enabled (retired 2026-08-20 — his ask:
"retire the old engine, but make sure i can bring it back").

Two things must both be true, proven here rather than assumed:
  - OFF (the retired default): the loop fires nothing out of legacy
    storage/profiles/ data, but still refreshes state.timing every tick —
    spectra/services/bridge.py reads shape_offset_ms off it for its own
    xcorr-corrected fire timing, and this loop is the ONLY writer of
    state.timing in the whole codebase (grep-confirmed).
  - ON: firing is restored exactly as before — the reversibility promise
    actually works, not just exists on paper.

Also proves the retirement brief's hard-stop question: does run() ever
WRITE _shape_offset_ms / _play_best_quality — the fields
auto_offset_service reads and writes via engine.apply_save/load_profile/
reload_shape_offset/demote_play_best, all called from OUTSIDE this loop?
If it did, retiring the loop would silently degrade his latency
calibration. It doesn't, either way the flag is set — proven here, not
just read off the source.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from config import settings
from models.song_profile import MusicTrigger, SongProfile
from models.state import SpotifyTrackInfo, state
from services.trigger_engine import TriggerEngine


def _make_profile_and_track():
    profile = SongProfile(
        spotify_uri="spotify:track:retirement-test",
        title="Retirement Test", artist="Test Artist",
        duration_ms=200_000,
        triggers=[MusicTrigger(id="t1", timestamp_ms=1000, event_id="no-such-event", enabled=True)],
    )
    # progress_ms sits just past the trigger (200ms) — enough to be firable,
    # well under STALE_FIRE_MS (2000ms) so stale-fire suppression doesn't
    # silently swallow it before the fallback-fire path ever sees it.
    track = SpotifyTrackInfo(
        spotify_uri=profile.spotify_uri, title=profile.title, artist=profile.artist,
        duration_ms=profile.duration_ms, progress_ms=1200, is_playing=True,
        fetched_at=time.monotonic(),
    )
    return profile, track


@pytest.fixture()
def engine_env():
    """A TriggerEngine pinned to one song with a due trigger; state and the
    settings flag are restored after, since both are process-wide globals."""
    orig_state = {f.name: getattr(state, f.name) for f in dataclasses.fields(state)}
    orig_flag = settings.legacy_trigger_engine_enabled

    profile, track = _make_profile_and_track()
    engine = TriggerEngine()
    engine._profile = profile
    engine._last_uri = profile.spotify_uri
    engine._shape_offset_ms = 250
    engine._shape_offset_quality = 0.8
    engine._play_best_quality = 0.9

    state.current_track = track
    state.on_target_device = True
    state.paused = False
    state.dinner_party_mode = False
    state.active_setlist_id = ""
    state.timing = {}

    fired: list[str] = []

    async def _fake_fire_trigger(trigger, *, fired_at_ms, effective_offset_ms):
        fired.append(trigger.id)

    engine._fire_trigger = _fake_fire_trigger

    try:
        yield engine, fired
    finally:
        for k, v in orig_state.items():
            setattr(state, k, v)
        object.__setattr__(settings, "legacy_trigger_engine_enabled", orig_flag)


async def _run_a_few_ticks(engine):
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.2)  # TICK_MS=50ms — several ticks
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_retired_default_fires_nothing_but_keeps_timing_alive(engine_env):
    engine, fired = engine_env
    object.__setattr__(settings, "legacy_trigger_engine_enabled", False)

    async def go():
        assert state.timing == {}
        await _run_a_few_ticks(engine)

    asyncio.run(go())

    assert fired == [], "legacy engine fired a trigger while retired"
    # The sync feed SPECTRA's bridge depends on must still be alive.
    assert state.timing.get("shape_offset_ms") == 250
    assert state.timing.get("shape_offset_quality") == 0.8
    # auto_offset_service's own fields, untouched by the loop either way.
    assert engine._shape_offset_ms == 250
    assert engine._play_best_quality == 0.9


def test_flag_restores_legacy_firing(engine_env):
    engine, fired = engine_env
    object.__setattr__(settings, "legacy_trigger_engine_enabled", True)

    asyncio.run(_run_a_few_ticks(engine))

    assert fired == ["t1"], "flipping the flag back on did not restore firing"
    assert state.timing.get("shape_offset_ms") == 250
    # Still untouched by the loop when the flag is on, same as when it's off.
    assert engine._shape_offset_ms == 250
    assert engine._play_best_quality == 0.9
