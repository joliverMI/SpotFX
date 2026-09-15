"""
Keep searching after a low-confidence sweep — `services/xcorr_sweep.py`
`KeepSearching`, wired into `services/auto_offset_service.py`'s one exit where
a play drains its planned windows without a hard lock.

The Admiral, verbatim: "if it has low confidence, it should keep spike
detection on to try to get better." MAYDAY, spotfx.service, 2026-09-08 21:15:
four windows inside the first ~30s, `final offset=+1325ms Q=0.39`,
`Engine: skip snap — far jump +1325ms (Δ=3416ms) without prior agreement`,
`lock_history: no hard lock grade=F`, `no reachable windows (pos=32611ms,
dur=247339ms)` — then silence for the remaining three and a half minutes.

Every sweep here is the REAL `on_track_change` → `_detect_loop_xcorr`, driven
over a scripted world by `tests/sweep_world_driver.py`; only the capture, the
math kernel, the trigger engine and disk are replaced.

  ONE   — the founding defect: reproduced on the pinned pre-change sweep, then
          fixed — the search keeps going and the better lock is adopted.
  TWO   — an early clean lock, the post-lock drift monitor (recovery and all),
          and the switched-off path are BYTE-IDENTICAL to the pre-change
          sweep: every engine call, save, websocket message, log line, kernel
          call, history record and badge record compared, not asserted.
  THREE — it terminates: nothing to find, no time left, a user-verified
          offset, and the song changing mid-search each end it, and each
          reads as failed only once it has genuinely stopped.
  FOUR  — the badge half: Searching throughout the continued search, Failed
          only on give-up, and the next poll never overwrites it.
  FIVE  — the same seconds of audio are never measured twice.
  SIX   — the pure state machine, its borrowed constants, and a structural
          proof that no offset arithmetic was added anywhere.
"""
from __future__ import annotations

import ast
import collections

import pytest

import sweep_world_driver as d
from services import lock_state
from services.xcorr_sweep import (
    KEEP_SEARCHING_NO_TIME_LEFT, KEEP_SEARCHING_NOTHING_TO_FIND,
    KEEP_SEARCHING_USER_VERIFIED, KeepSearching, KeepSearchingConfig,
)

URI = d.URI


@pytest.fixture(scope="module")
def baseline():
    return d.load_baseline_module()


@pytest.fixture
def new():
    return d.current_module()


def _drain_ms(world: d.World) -> int:
    """When the last planned window is dispatched (its end + the margin)."""
    return world.windows[-1][1] + 1000


def _continued(trace: d.Trace, world: d.World) -> list[tuple[int, int]]:
    planned = set(world.windows) | {(0, 8000)}
    return [w for w in trace.windows_evaluated() if w not in planned]


# ── ONE — the founding defect ────────────────────────────────────────────────

def test_the_pinned_baseline_reproduces_mayday(baseline, monkeypatch, tmp_path):
    """RED CONTROL. The harness must fail on the defect it was written for:
    the pre-change sweep stops at the end of its plan, never locks, and the
    very next poll overwrites the honest failure with "not checked"."""
    world = d.mayday_world()
    t = d.run_world(baseline, world, monkeypatch, tmp_path, poll_after_ms=200_000)

    assert any("skip snap — far jump +1325ms (Δ=3416ms, Q=0.39) without prior agreement"
               in line for line in t.logs), "the MAYDAY log line itself"
    assert t.last_frame_ms < _drain_ms(world) + 1000, "the baseline stops at its plan's end"
    assert _continued(t, world) == []
    assert t.history[-1]["locked"] is False and t.history[-1]["quality"] == 0.39
    assert t.final_lock_state["phase"] == lock_state.PHASE_UNLOCKED
    assert t.after_poll_lock_state["phase"] == lock_state.PHASE_SKIPPED
    assert t.after_poll_lock_state["reason"] == "no_windows"


def test_mayday_keeps_searching_and_adopts_the_better_lock(new, monkeypatch, tmp_path):
    world = d.mayday_world()
    t = d.run_world(new, world, monkeypatch, tmp_path, poll_after_ms=200_000)

    extra = _continued(t, world)
    assert extra, "the search went on past the plan"
    assert all(ws >= world.windows[-1][1] - 1000 for ws, _we in extra)
    lock = t.history[-1]
    assert lock["locked"] is True, "a hard lock was found in the continued search"
    assert lock["time_to_lock_ms"] > 60_000, "found where the song turned clean, past the plan"
    assert lock["offset_ms"] == 1325 and lock["quality"] == 0.95
    assert t.engine._shape_offset_ms == 1325 and t.engine._play_best_quality == 0.95, (
        "the engine adopted the better lock through its own strictly-better-Q gate"
    )
    assert len(t.history) == 1, "one play, one history record"

    # Past the lock the play is in the ordinary post-lock drift monitor.
    lock_at = lock["time_to_lock_ms"]
    assert any(m["type"] == "xcorr_monitor" and m["t_ms"] > lock_at for m in t.ws.sent)
    assert t.last_frame_ms >= world.duration_ms - d.FRAME_MS
    assert t.watching_after == URI and not t.task_after_poll


# ── TWO — byte-identical wherever the play locks, or the switch is off ───────

def _early_lock_loaded_right() -> d.World:
    return d.World(duration_ms=150_000,
                   windows=[(10_000, 15_000), (16_000, 21_000), (22_000, 27_000),
                            (28_000, 33_000), (60_000, 65_000)],
                   loaded_offset_ms=-400, truth=lambda _ms: -400,
                   clarity=lambda _ms: (0.9, 1.0))


def _early_lock_needs_correction() -> d.World:
    return d.World(duration_ms=150_000,
                   windows=[(10_000, 15_000), (16_000, 21_000), (22_000, 27_000),
                            (28_000, 33_000), (60_000, 65_000)],
                   loaded_offset_ms=+300, truth=lambda _ms: -650,
                   clarity=lambda ms: (0.92, 1.0) if ms >= 10_000 else (0.4, 0.5))


def _lock_then_drift() -> d.World:
    """Locks early; at 50s the song re-syncs 1500ms later, the drift monitor
    confirms the mismatch, fires a recovery window and re-arms the remaining
    planned window, which then drains — with no fresh hard lock."""
    return d.World(duration_ms=150_000,
                   windows=[(10_000, 15_000), (16_000, 21_000), (22_000, 27_000),
                            (80_000, 85_000)],
                   loaded_offset_ms=-400,
                   truth=lambda ms: -400 if ms < 50_000 else +1100,
                   clarity=lambda _ms: (0.9, 1.0))


def _compare(baseline, new, world, monkeypatch, tmp_path, **kw):
    a = d.run_world(baseline, world, monkeypatch, tmp_path, **kw)
    b = d.run_world(new, world, monkeypatch, tmp_path, **kw)
    ca, cb = a.comparable(), b.comparable()
    for key in ca:
        assert ca[key] == cb[key], f"{key} diverged from the pre-change sweep"
    return a


def test_an_early_clean_lock_is_byte_identical(baseline, new, monkeypatch, tmp_path):
    t = _compare(baseline, new, _early_lock_loaded_right(), monkeypatch, tmp_path,
                 poll_after_ms=120_000)
    assert t.history[0]["locked"] and t.history[0]["time_to_lock_ms"] < 35_000
    assert sum(m["type"] == "xcorr_monitor" for m in t.ws.sent) > 30, "monitor ran to song end"
    assert "continued" not in t.final_lock_state, "an early lock's badge record keeps its shape"


def test_an_early_lock_that_corrects_the_engine_is_byte_identical(baseline, new, monkeypatch, tmp_path):
    t = _compare(baseline, new, _early_lock_needs_correction(), monkeypatch, tmp_path,
                 poll_after_ms=120_000)
    assert t.history[0]["locked"] and t.engine._shape_offset_ms == -650


def test_the_post_lock_drift_monitor_is_byte_identical(baseline, new, monkeypatch, tmp_path):
    """Recovery, the dynamic spike window, the re-armed queue AND the drain
    that follows it: a play that ever hard-locked keeps its old exit."""
    t = _compare(baseline, new, _lock_then_drift(), monkeypatch, tmp_path,
                 poll_after_ms=140_000)
    assert t.history[0]["locked"] is True
    assert any(c[0] == "demote" for c in t.engine.calls), "a mismatch was confirmed"
    assert any(c == ("xcorr_window", 80_000, 85_000) for c in t.kernel), (
        "the re-armed planned window ran and drained"
    )


def test_switched_off_is_the_old_stop_at_the_end_of_the_plan(baseline, new, monkeypatch, tmp_path):
    t = _compare(baseline, new, d.mayday_world(), monkeypatch, tmp_path,
                 settings_over={"xcorr_keep_searching_enabled": False},
                 poll_after_ms=200_000)
    assert t.history[0]["locked"] is False


# ── THREE — it terminates ─────────────────────────────────────────────────────

def _unlockable(**over) -> d.World:
    base = dict(duration_ms=240_000,
                windows=[(10_000, 15_000), (16_000, 21_000), (22_000, 27_000),
                         (28_000, 33_000)],
                loaded_offset_ms=0, truth=lambda _ms: 700,
                clarity=lambda _ms: (0.1, 0.9))
    base.update(over)
    return d.World(**base)


def test_an_unlockable_song_gives_up_instead_of_spinning(new, monkeypatch, tmp_path):
    world = _unlockable()
    t = d.run_world(new, world, monkeypatch, tmp_path, poll_after_ms=100_000)

    give_up_ms = d.SETTINGS["xcorr_keep_searching_give_up_ms"]
    interval = d.SETTINGS["xcorr_keep_searching_interval_ms"]
    drain = _drain_ms(world)
    assert drain + give_up_ms <= t.last_frame_ms <= drain + give_up_ms + d.FRAME_MS, (
        "it stops once the budget of song without a usable measurement is spent"
    )
    assert t.last_frame_ms < world.duration_ms - 150_000, "long before the song ends"
    assert 0 < len(_continued(t, world)) <= give_up_ms // interval, "bounded work"
    assert any("keep-searching gave up (nothing_to_find)" in line for line in t.logs)
    assert t.history[-1]["locked"] is False and len(t.history) == 1

    assert t.final_lock_state["phase"] == lock_state.PHASE_UNLOCKED
    assert t.final_lock_state["reason"] == KEEP_SEARCHING_NOTHING_TO_FIND


def test_usable_but_unconvincing_measurements_search_until_no_time_is_left(new, monkeypatch, tmp_path):
    """Every window measures (so there IS something to find) but none is ever
    confident enough to lock: it keeps trying across the rest of the song and
    stops where no window is ever planned — the last 30s."""
    world = _unlockable(duration_ms=150_000, loaded_offset_ms=700,
                        clarity=lambda _ms: (0.6, 1.0))
    t = d.run_world(new, world, monkeypatch, tmp_path)

    end_of_search = world.duration_ms - 30_000
    assert end_of_search <= t.last_frame_ms <= end_of_search + d.FRAME_MS
    extra = _continued(t, world)
    assert len(extra) >= 15, "it kept measuring across the rest of the song"
    assert len(extra) <= (end_of_search - _drain_ms(world)) // 5000
    assert t.final_lock_state["phase"] == lock_state.PHASE_UNLOCKED
    assert t.final_lock_state["reason"] == KEEP_SEARCHING_NO_TIME_LEFT
    assert t.history[-1]["locked"] is False


def test_a_user_verified_offset_has_no_better_lock_to_reach(new, monkeypatch, tmp_path):
    world = _unlockable(verification="user_verified", clarity=lambda _ms: (0.6, 1.0))
    t = d.run_world(new, world, monkeypatch, tmp_path)
    assert _continued(t, world) == [], "the sweep can never move a pinned offset"
    assert t.last_frame_ms <= _drain_ms(world)
    assert t.final_lock_state["reason"] == KEEP_SEARCHING_USER_VERIFIED
    assert "continued" not in t.final_lock_state, "it never claimed to keep searching"


def test_the_song_changing_mid_search_ends_it_as_failed(new, monkeypatch, tmp_path):
    world = _unlockable(clarity=lambda _ms: (0.6, 1.0), loaded_offset_ms=700,
                        hang_at_ms=70_000)
    t = d.run_world(new, world, monkeypatch, tmp_path, stop_after=True)
    assert _continued(t, world), "it was mid-search"
    assert t.final_lock_state is not None
    assert t.final_lock_state["phase"] == lock_state.PHASE_UNLOCKED
    assert t.final_lock_state["reason"] is None, "the song ended; the search did not give up"
    assert len(t.history) == 1 and t.history[0]["locked"] is False


# ── FOUR — the badge: Searching while trying, Failed only on give-up ─────────

def test_the_badge_reads_searching_through_the_continued_search(new, monkeypatch, tmp_path):
    world = _unlockable()
    t = d.run_world(new, world, monkeypatch, tmp_path)
    planned = set(world.windows) | {(0, 8000)}
    samples = [(w, rec) for w, rec in zip(t.windows_evaluated(), t.lock_during)
               if w not in planned]
    assert samples
    for w, rec in samples:
        assert rec["phase"] == lock_state.PHASE_SEARCHING, f"window {w} was not Searching"
        assert rec["continued"] is True, f"window {w} did not say it had gone past the plan"
    pushed = [m for m in t.ws.sent if m["type"] == "lock_state"]
    phases = [m["phase"] for m in pushed]
    assert phases.count(lock_state.PHASE_UNLOCKED) == 1 and phases[-1] == lock_state.PHASE_UNLOCKED, (
        "Failed is pushed exactly once, at the very end"
    )
    assert pushed[-1]["continued_windows"] == len(samples)


def test_a_give_up_is_not_overwritten_by_the_next_poll(new, monkeypatch, tmp_path):
    """The pre-change sweep let the next poll relaunch, find "no reachable
    windows" and replace "Lock failed" with "Not checked" (ONE's red control).
    A search that genuinely gave up holds the watch until the song changes."""
    world = _unlockable()
    t = d.run_world(new, world, monkeypatch, tmp_path, poll_after_ms=100_000)
    assert t.watching_after == URI
    assert not t.task_after_poll, "no relaunch"
    assert t.after_poll_lock_state["phase"] == lock_state.PHASE_UNLOCKED
    assert t.after_poll_lock_state["reason"] == KEEP_SEARCHING_NOTHING_TO_FIND
    assert not any("no reachable windows" in line for line in t.logs)


# ── FIVE — the same audio is never measured twice ────────────────────────────

def test_a_spike_on_already_measured_audio_is_not_measured_again(new, monkeypatch, tmp_path):
    """Two measurements of the same seconds cast the same vote twice and could
    manufacture agreement out of one. A spike that keeps landing in one spot
    is measured once, and the search still ends."""
    world = _unlockable(spike=lambda _t, _o: (40_000, 45_000, 42_500))
    t = d.run_world(new, world, monkeypatch, tmp_path)
    assert t.windows_evaluated().count((40_000, 45_000)) == 1
    spikes = [c for c in t.kernel if c[0] == "mismatch_spike"]
    assert len(spikes) > 1, "it kept asking, and kept refusing the same audio"
    assert t.final_lock_state["reason"] == KEEP_SEARCHING_NOTHING_TO_FIND


# ── SIX — the state machine, its borrowed constants, no offset arithmetic ────

def _ks(**over) -> KeepSearching:
    cfg = KeepSearchingConfig(**{k: v for k, v in over.items()
                                 if k in KeepSearchingConfig.__dataclass_fields__})
    return KeepSearching(cfg, verification=over.get("verification", "auto_verified"),
                         started_ms=over.get("started_ms", 30_000),
                         duration_ms=over.get("duration_ms", 240_000),
                         evaluated=over.get("evaluated", [(22_000, 27_000), (28_000, 33_000)]))


def test_give_up_rules_and_their_precedence():
    ks = _ks()
    assert ks.give_up_reason(30_000) is None
    assert ks.give_up_reason(74_999) is None
    assert ks.give_up_reason(75_000) == KEEP_SEARCHING_NOTHING_TO_FIND
    ks.note_window(70_000, (60_000, 65_000), evidence=True)
    assert ks.give_up_reason(114_999) is None, "a usable measurement restarts the budget"
    ks.note_window(80_000, (70_000, 75_000), evidence=False)
    assert ks.give_up_reason(115_000) == KEEP_SEARCHING_NOTHING_TO_FIND
    assert ks.give_up_reason(210_000) == KEEP_SEARCHING_NO_TIME_LEFT
    assert _ks(verification="user_verified").give_up_reason(30_000) == KEEP_SEARCHING_USER_VERIFIED
    assert _ks(duration_ms=0).give_up_reason(30_000) == KEEP_SEARCHING_NO_TIME_LEFT


def test_placement_cadence_readiness_and_overlap():
    ks = _ks()
    assert not ks.wants_window(34_999) and ks.wants_window(35_000)
    assert ks.offer(35_000, None) is False, "a flat span places nothing"
    assert not ks.wants_window(39_999) and ks.wants_window(40_000)
    assert ks.offer(40_000, (31_500, 36_500)) is False, "1500ms over a measured window"
    assert ks.offer(45_000, (32_000, 37_000)) is True, "1000ms of overlap is the planner's own cap"
    assert not ks.wants_window(60_000), "one window pending at a time"
    assert ks.take_ready(37_999, 1000) is None
    assert ks.take_ready(38_000, 1000) == (32_000, 37_000)
    ks.note_window(38_000, (32_000, 37_000), evidence=False)
    assert not ks.admits(32_000, 37_000)
    assert ks.windows_run == 1 and ks.attempts == 3


def test_borrowed_constants_still_agree_with_the_planners():
    import services.auto_offset_service as aos
    from services import uscore_planner
    from config import settings
    cfg = KeepSearchingConfig.from_settings(settings, end_buffer_ms=aos._XCORR_END_BUFFER_MS)
    assert cfg.end_buffer_ms == aos._XCORR_END_BUFFER_MS == uscore_planner._END_BUFFER_MS
    assert KeepSearchingConfig().max_overlap_ms == uscore_planner._MAX_OVERLAP_MS
    assert settings.xcorr_keep_searching_enabled is True, "the Admiral authorised it: on"


def _offset_arithmetic(src: str) -> collections.Counter:
    """Every arithmetic, comparison or augmented assignment that touches an
    identifier naming an offset, unparsed."""
    found: collections.Counter = collections.Counter()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Compare, ast.AugAssign)):
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        if any("offset" in n.lower() or n in ("shift", "shift_ms") for n in names):
            found[ast.unparse(node)] += 1
    return found


def test_no_offset_arithmetic_was_added(baseline):
    """This change decides WHEN and HOW LONG the search runs. Read against the
    pinned pre-change sweep, not one expression that does arithmetic on an
    offset — or compares one — was added to the sweep; and the new state
    machine names no offset at all."""
    import subprocess
    old = subprocess.run(["git", "show", f"{d.BASELINE_REF}:services/auto_offset_service.py"],
                         cwd=d.REPO, capture_output=True, text=True, check=True).stdout
    now = (d.REPO / "services" / "auto_offset_service.py").read_text()
    added = _offset_arithmetic(now) - _offset_arithmetic(old)
    assert not added, f"offset arithmetic added: {sorted(added)}"

    sweep = (d.REPO / "services" / "xcorr_sweep.py").read_text()
    cls = next(n for n in ast.walk(ast.parse(sweep))
               if isinstance(n, ast.ClassDef) and n.name == "KeepSearching")
    idents = {n.id for n in ast.walk(cls) if isinstance(n, ast.Name)}
    idents |= {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute)}
    idents |= {a.arg for n in ast.walk(cls) if isinstance(n, ast.arguments)
               for a in n.args + n.kwonlyargs}
    assert not [i for i in idents if "offset" in i.lower() or "shift" in i.lower()]
