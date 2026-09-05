"""Pipeline-drift instrument (services/lock_history.pipeline_drift) — the
drift line + alarm on the Timing page's Lock history panel.

Born from the Aug 25 → Sep 2 2026 incident: the audio pipeline ratcheted
~350 ms/day to −3.2 s while every per-song save quietly re-learned it, so
nothing alarmed until locks were already failing at the ~3 s search cliff.
These worlds are synthetic but shaped like that incident; the read-only
demonstration against the real stored history is scripts/check_timing_drift.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services import lock_history


T0 = datetime(2026, 9, 1, 20, 0, 0, tzinfo=timezone.utc)
SONGS = [f"spotify:track:song{i}" for i in range(6)]


def _entry(at: datetime, uri: str, offset_ms: int, prev: int | None = 0) -> dict:
    return {
        "at": at.isoformat(),
        "uri": uri,
        "offset_ms": int(offset_ms),
        "prev_offset_ms": prev,
        "quality": 0.8,
        "grade": "B",
    }


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Never read or write the repo's real storage/lock_history.json."""
    monkeypatch.setattr(lock_history, "_STORE_PATH", tmp_path / "lock_history.json")
    monkeypatch.setattr(lock_history, "_entries", None)


def _install(entries: list[dict]) -> None:
    lock_history._entries = list(reversed(entries))   # store order: newest first


def _daily_world(days: int, offset_for) -> list[dict]:
    """One evening session per day; every song played every day."""
    out = []
    for day in range(days):
        for k, uri in enumerate(SONGS):
            at = T0 + timedelta(days=day, minutes=4 * k)
            out.append(_entry(at, uri, offset_for(day, k)))
    return out


def test_healthy_world_stays_quiet():
    # Stable per-song offsets with small jitter: no common component.
    _install(_daily_world(10, lambda day, k: 1000 * k + (50 if day % 2 else -50)))
    d = lock_history.pipeline_drift()
    assert d["current"] is not None
    assert abs(d["current"]["median_residual_ms"]) < 200
    assert d["alarm"] is False


def test_pipeline_ratchet_alarms():
    # The incident's shape: every song's offset walks −400 ms/day together.
    _install(_daily_world(10, lambda day, k: 1000 * k - 400 * day))
    d = lock_history.pipeline_drift()
    cur = d["current"]
    assert cur is not None and cur["baselined"] >= len(SONGS)
    assert cur["median_residual_ms"] <= -lock_history.DRIFT_ALARM_MS
    assert d["alarm"] is True


def test_first_plays_cannot_move_the_number():
    # A healthy world, then an album of 12 brand-new songs with wild offsets
    # lands in the newest session (the Sep 3 Beatles shape). They have no
    # baseline, so they must be invisible to the drift median and the alarm.
    world = _daily_world(10, lambda day, k: 1000 * k)
    last_session_start = T0 + timedelta(days=9)
    for j in range(12):
        world.append(_entry(last_session_start + timedelta(minutes=30 + j),
                            f"spotify:track:new{j}", 9000, prev=None))
    _install(world)
    d = lock_history.pipeline_drift()
    cur = d["current"]
    assert cur is not None
    assert cur["plays"] == len(SONGS) + 12
    assert cur["baselined"] == len(SONGS)          # the new songs never count
    assert abs(cur["median_residual_ms"]) < 200
    assert d["alarm"] is False


def test_underpopulated_session_never_drives_the_alarm():
    # Two wild repeat plays in the newest session (< min baselined) must not
    # alarm; `current` falls back to the last session with enough evidence.
    world = _daily_world(10, lambda day, k: 1000 * k)
    tiny = T0 + timedelta(days=10)
    world.append(_entry(tiny, SONGS[0], 1000 * 0 - 5000))
    world.append(_entry(tiny + timedelta(minutes=3), SONGS[1], 1000 * 1 - 5000))
    _install(world)
    d = lock_history.pipeline_drift()
    assert d["sessions"][0]["baselined"] == 2      # the tiny session is reported…
    cur = d["current"]
    assert cur is not None and cur["baselined"] >= 3   # …but never drives the alarm
    assert abs(cur["median_residual_ms"]) < 200
    assert d["alarm"] is False


def test_young_baselines_do_not_chase_the_drift():
    # The baseline must be ≥36h old: a song's play from the SAME session (or
    # yesterday's) may not serve as its own baseline, or a multi-day ratchet
    # measures as a small daily increment and never alarms. With only two
    # consecutive days of history nothing qualifies as a baseline at all.
    _install(_daily_world(2, lambda day, k: 1000 * k - 2000 * day))
    d = lock_history.pipeline_drift()
    assert d["current"] is None
    assert d["alarm"] is False
    assert all(s["baselined"] == 0 for s in d["sessions"])


def test_session_split_on_two_hour_gap():
    # Two clusters 3h apart on one evening are two sessions.
    world = []
    for k, uri in enumerate(SONGS[:3]):
        world.append(_entry(T0 + timedelta(minutes=4 * k), uri, 0))
    for k, uri in enumerate(SONGS[:3]):
        world.append(_entry(T0 + timedelta(hours=3, minutes=4 * k), uri, 0))
    _install(world)
    d = lock_history.pipeline_drift()
    assert len(d["sessions"]) == 2
    assert d["sessions"][0]["plays"] == 3          # newest first
