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


def _entry(at: datetime, uri: str, offset_ms: int, prev: int | None = 0,
           locked: bool = True, quality: float = 0.8) -> dict:
    return {
        "at": at.isoformat(),
        "uri": uri,
        "offset_ms": int(offset_ms),
        "prev_offset_ms": prev,
        "quality": quality,
        "locked": locked,
        "grade": "B",
    }


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Never read or write the repo's real storage/lock_history.json."""
    monkeypatch.setattr(lock_history, "_STORE_PATH", tmp_path / "lock_history.json")
    monkeypatch.setattr(lock_history, "_entries", None)
    monkeypatch.setattr(lock_history, "_anchor_seed_oldest", None)


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


def test_garbage_plays_never_enter_the_baseline_or_level_pool():
    # An unlocked or near-zero-Q play is not evidence of a song's normal
    # state — report §5.1's "+27575ms @ Q .41" class. A run of such plays,
    # scattered through an otherwise healthy world, must move neither the
    # legacy residual nor the new level, though they still count as plays.
    world = _daily_world(10, lambda day, k: 1000 * k)
    for i in range(15):
        world.append(_entry(T0 + timedelta(days=6, hours=i), SONGS[0],
                             27000, locked=False, quality=0.2))
        world.append(_entry(T0 + timedelta(days=6, hours=i, minutes=1), SONGS[1],
                             -19000, locked=True, quality=0.1))
    _install(world)
    d = lock_history.pipeline_drift(max_sessions=20)
    cur = d["current"]
    assert cur is not None
    assert abs(cur["median_residual_ms"]) < 200
    assert abs(cur["level_ms"]) < 200
    assert d["alarm"] is False
    # the garbage plays are visible in the raw play count, not the pools
    garbage_session = next(s for s in d["sessions"]
                            if s["start_at"][:10] == (T0 + timedelta(days=6)).date().isoformat())
    assert garbage_session["plays"] > 6
    assert garbage_session["baselined"] <= 6
    assert garbage_session["level_baselined"] <= 6


def _step_world() -> list[dict]:
    """The report's own shape (§2/§4): a flat anchor era, a steady ramp,
    one discrete step, then a stable era holding the new level — never a
    scattered, sign-flipping sequence."""
    world: list[dict] = []
    for day in range(4):                                    # anchor era
        for k, uri in enumerate(SONGS):
            world.append(_entry(T0 + timedelta(days=day, minutes=4 * k),
                                 uri, 1000 * k))
    for i, day in enumerate(range(5, 10)):                   # ramp era
        for k, uri in enumerate(SONGS):
            world.append(_entry(T0 + timedelta(days=day, minutes=4 * k),
                                 uri, 1000 * k - 400 * (i + 1)))
    step_level = -400 * 5 + 5000                              # THE STEP
    for k, uri in enumerate(SONGS):
        world.append(_entry(T0 + timedelta(days=11, minutes=4 * k),
                             uri, 1000 * k + step_level))
    for day in range(12, 14):                                 # stable era
        for k, uri in enumerate(SONGS):
            world.append(_entry(T0 + timedelta(days=day, minutes=4 * k),
                                 uri, 1000 * k + step_level))
    return world


def test_level_reads_ramp_then_step_then_stable_not_scatter():
    # The regression this instrument was rebuilt for
    # (data/spectra-timing-drift-cause/report.md): fed the same shaped
    # history, the OLD lagged-baseline number turns a clean ramp-then-step
    # into what reads as scatter with a sign flip. The LEVEL must not.
    _install(_step_world())
    d = lock_history.pipeline_drift(max_sessions=20)
    ordered = list(reversed(d["sessions"]))       # oldest → newest
    shapes = [s["shape"] for s in ordered if s["shape"] != "insufficient"]
    assert shapes == ["start", "ramp", "ramp", "ramp", "step", "stable", "stable"]

    step_session = next(s for s in ordered if s["shape"] == "step")
    stable_sessions = [s for s in ordered if s["shape"] == "stable"]
    assert step_session["level_ms"] > 2500                   # the real jump
    assert all(abs(s["level_ms"] - stable_sessions[0]["level_ms"]) < 200
               for s in stable_sessions)                     # settled, not drifting

    # `current` (and the alarm) read the level, not the lagged residual —
    # the newest session is stable, so it must not misreport as still moving.
    assert d["current"] is not None
    assert d["current"]["shape"] == "stable"
    assert d["alarm"] is True   # the settled level itself is past the threshold


def _record(monkeypatch, plays: list[tuple[datetime, str, int]]) -> None:
    """Drive the real write path, one play at a time, on a controlled clock."""
    clock: dict[str, datetime] = {}
    monkeypatch.setattr(lock_history, "_now_iso", lambda: clock["now"].isoformat())
    for at, uri, off in plays:
        clock["now"] = at
        lock_history.record(uri=uri, locked=True, offset_ms=off, quality=0.8, n_windows=3)


def _levels_by_day(d: dict) -> dict[str, int | None]:
    return {s["start_at"][:10]: s["level_ms"] for s in d["sessions"]}


def test_the_capped_log_evicting_the_anchor_era_never_moves_an_anchor(monkeypatch):
    # The store is capped; every new play past the cap evicts the oldest.
    # Once the anchor era's own plays are gone from the log, each song's
    # anchor — and so every level already read against it — must not move.
    monkeypatch.setattr(lock_history, "_CAP", 48)
    era = [(T0 + timedelta(days=day, minutes=4 * k), uri, 1000 * k)
           for day in range(4) for k, uri in enumerate(SONGS)]
    settled = [(T0 + timedelta(days=day, minutes=4 * k), uri, 1000 * k - 2000)
               for day in range(6, 14) for k, uri in enumerate(SONGS)]

    _record(monkeypatch, era + settled[:24])                  # days 6–9, log exactly full
    before = lock_history.pipeline_drift(max_sessions=50)
    assert before["anchor_era"]["start_at"] == T0.isoformat()
    kept_days = {(T0 + timedelta(days=day)).date().isoformat() for day in range(6, 10)}
    assert {day: before_lvl for day, before_lvl in _levels_by_day(before).items()
            if day in kept_days} == {day: -2000 for day in kept_days}

    _record(monkeypatch, settled[24:])                         # days 10–13 evict the era
    oldest_kept = min(datetime.fromisoformat(e["at"]) for e in lock_history._entries)
    assert oldest_kept > T0 + timedelta(days=4)                # not one era play left
    after = lock_history.pipeline_drift(max_sessions=50)
    assert after["anchor_era"] == before["anchor_era"]
    after_levels = _levels_by_day(after)
    assert all(after_levels[day] == -2000 for day in kept_days)
    assert after["current"]["level_ms"] == -2000
    assert after["alarm"] is True


def test_an_unreadable_anchor_store_means_no_anchor_not_a_rederived_one(monkeypatch):
    # Re-deriving from whatever the capped log still holds would quietly
    # swap in a later, moving anchor; an honest "no anchor" is the answer.
    world = _daily_world(10, lambda day, k: 1000 * k - 400 * day)
    _install(world)
    path = lock_history._anchor_path()
    path.write_text("{ not json", encoding="utf-8")
    d = lock_history.pipeline_drift(max_sessions=20)
    assert d["anchor_era"] is None
    assert all(s["level_ms"] is None for s in d["sessions"])
    assert d["current"] is None and d["alarm"] is False
    assert all(s["median_residual_ms"] is not None
               for s in d["sessions"] if s["baselined"])        # legacy reading unaffected

    _record(monkeypatch, [(T0 + timedelta(days=11), SONGS[0], 0)])
    assert path.read_text(encoding="utf-8") == "{ not json"


def _settled_world_plays(days: range) -> list[tuple[datetime, str, int]]:
    era = [(T0 + timedelta(days=day, minutes=4 * k), uri, 1000 * k)
           for day in range(4) for k, uri in enumerate(SONGS)]
    return era + [(T0 + timedelta(days=day, minutes=4 * k), uri, 1000 * k - 2000)
                  for day in days for k, uri in enumerate(SONGS)]


def _failing_saves(monkeypatch, failures: int) -> None:
    real_save = lock_history._save_anchor_era
    calls = {"n": 0}

    def save(era):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise OSError("disk full")
        real_save(era)

    monkeypatch.setattr(lock_history, "_save_anchor_era", save)


def test_a_failed_anchor_save_is_no_anchor_once_the_log_evicts_past_it(monkeypatch):
    # Every save fails until the capped log has already dropped the anchor
    # era's first plays. Rebuilding the era from what the log holds then —
    # on read, or on the next save that works — would be a moved anchor.
    monkeypatch.setattr(lock_history, "_CAP", 48)
    plays = _settled_world_plays(range(6, 14))
    _failing_saves(monkeypatch, failures=60)
    _record(monkeypatch, plays[:60])                            # evicts 12 era plays
    during = lock_history.pipeline_drift(max_sessions=50)
    assert during["anchor_era"] is None
    assert all(s["level_ms"] is None for s in during["sessions"])

    _record(monkeypatch, plays[60:])                            # saves work again
    lock_history._entries = None                                # as after a restart
    after = lock_history.pipeline_drift(max_sessions=50)
    assert not lock_history._anchor_path().exists()
    assert after["anchor_era"] is None
    assert all(s["level_ms"] is None for s in after["sessions"])
    assert after["current"] is None and after["alarm"] is False
    assert any(s["median_residual_ms"] is not None for s in after["sessions"])


def test_a_failed_anchor_save_recovers_while_the_log_still_holds_the_era(monkeypatch):
    _failing_saves(monkeypatch, failures=5)
    _record(monkeypatch, _settled_world_plays(range(6, 10)))
    d = lock_history.pipeline_drift(max_sessions=50)
    assert lock_history._anchor_path().exists()
    assert d["anchor_era"]["start_at"] == T0.isoformat()
    assert d["current"]["level_ms"] == -2000


def test_selftest_ignores_an_anchors_store_beside_the_real_log(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "check_timing_drift.py"
    spec = importlib.util.spec_from_file_location("check_timing_drift", script)
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)

    _record(monkeypatch, [(T0 + timedelta(days=day), "spotify:track:unrelated", 0)
                          for day in range(6)])
    assert lock_history._anchor_path().exists()
    real_store = lock_history._STORE_PATH

    assert check.selftest() == 0
    assert lock_history._STORE_PATH == real_store
    assert lock_history.pipeline_drift()["anchor_era"]["songs"] == 1


def _anchored_world(levels_by_day: dict[int, int]) -> list[dict]:
    world = [_entry(T0 + timedelta(days=day, minutes=4 * k), uri, 1000 * k)
             for day in range(4) for k, uri in enumerate(SONGS)]
    for day, level in levels_by_day.items():
        world += [_entry(T0 + timedelta(days=day, minutes=4 * k), uri, 1000 * k + level)
                  for k, uri in enumerate(SONGS)]
    return world


def _shapes(d: dict) -> list[str]:
    return [s["shape"] for s in reversed(d["sessions"]) if s["shape"] != "insufficient"]


def test_sign_flipping_scatter_reads_as_reversals_not_a_ramp():
    _install(_anchored_world({6: -900, 7: 0, 8: -900, 9: 0}))
    assert _shapes(lock_history.pipeline_drift(max_sessions=20)) == [
        "start", "ramp", "reversal", "reversal"]


@pytest.mark.parametrize("gap_days, shape", [(1, "step"), (8, "step_or_ramp")])
def test_a_step_sized_move_is_only_a_step_when_no_ramp_could_have_made_it(gap_days, shape):
    # The incident's −400 ms/day ratchet, read only 8 days apart, moves
    # 3.2 s — a step's size, but not a step. The same move in one day is.
    _install(_anchored_world({6: -2400, 6 + gap_days: -2400 - 3200}))
    assert _shapes(lock_history.pipeline_drift(max_sessions=20)) == ["start", shape]
