"""
The sync-lock badge's backend half — `services/lock_state.py` and the four
places `services/auto_offset_service.py` reports into it.

Born 2026-09-08 from the Admiral's report: the badge in
`web/src/components/TopBar.tsx` was driven only by the `xcorr_monitor`
websocket — the POST-LOCK drift monitor — so with no monitor message and any
stored offset it printed the literal string "Lock idle". A song still
searching, a song that finished at grade F, and a song genuinely idle after a
good lock all read identically. His words: when a song has not locked the
badge "should be failed or still trying".

The badge's own decision table lives in `scripts/check_lock_badge_states.mjs`,
which transpiles the real frontend module and drives it. This file proves the
half the frontend cannot: that the phases arrive from the sweep at the right
moments, that the terminal signal means "the engine stopped searching" and not
"the windows ran out", and — section FIVE — that none of this can reach into a
single timing or lock decision.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import time

import pytest

from services import lock_state


REPO = pathlib.Path(__file__).resolve().parent.parent
URI = "spotify:track:mayday"
OTHER = "spotify:track:other"


@pytest.fixture(autouse=True)
def _isolated_lock_state():
    lock_state.clear()
    yield
    lock_state.clear()


class _FakeWs:
    """Stands in for services.websocket_manager.ws_manager."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def broadcast(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
def ws(monkeypatch):
    import services.websocket_manager as wm
    fake = _FakeWs()
    monkeypatch.setattr(wm, "ws_manager", fake)
    return fake


async def _drain() -> None:
    """_publish fires the broadcast as a task; let it run."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# ── ONE — the founding defect ────────────────────────────────────────────────

def test_the_mayday_play_is_unlocked_not_idle():
    """spotfx.service, 2026-09-08 21:15: the sweep ran once (4 windows,
    play_type=skip), produced `final offset=+1325ms Q=0.39`, then
    `lock_history: no hard lock grade=F`. The drift monitor never engaged."""
    lock_state.note_searching(URI, windows_total=4, play_type="skip")
    for _ in range(4):
        lock_state.note_window_done(URI)
    lock_state.note_outcome(URI, locked=False, offset_ms=1325, quality=0.39)
    lock_state.note_search_ended(URI)

    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_UNLOCKED
    assert rec["phase"] != lock_state.PHASE_LOCKED, "a grade-F play is not idle"
    assert rec["offset_ms"] == 1325 and rec["quality"] == 0.39
    assert rec["windows_done"] == 4 and rec["windows_total"] == 4


def test_a_good_lock_is_the_only_thing_that_can_read_idle():
    lock_state.note_searching(URI, windows_total=3)
    lock_state.note_outcome(URI, locked=True, offset_ms=-420, quality=0.81)
    assert lock_state.for_uri(URI)["phase"] == lock_state.PHASE_LOCKED
    # The engine stopping afterwards must never downgrade a real lock.
    lock_state.note_search_ended(URI)
    assert lock_state.for_uri(URI)["phase"] == lock_state.PHASE_LOCKED


def test_a_lock_is_reported_when_it_happens_not_at_the_end_of_the_play():
    """After a hard lock the sweep stays alive monitoring for drift, and the
    `xcorr_monitor` messages speak for the badge. If those go quiet — a
    capture stall — the phase is the fallback, and it must already say
    `locked` rather than leaving a locked song reading "Searching…"."""
    lock_state.note_searching(URI, windows_total=4)
    lock_state.note_window_done(URI)
    lock_state.note_outcome(URI, locked=True, offset_ms=-400, quality=0.77)
    assert lock_state.for_uri(URI)["phase"] == lock_state.PHASE_LOCKED

    # The play then ends and the terminal note refines the numbers.
    lock_state.note_outcome(URI, locked=True, offset_ms=-420, quality=0.81)
    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_LOCKED
    assert rec["offset_ms"] == -420 and rec["quality"] == 0.81
    assert rec["windows_done"] == 1, "progress is carried across, not reset"


# ── TWO — the terminal signal means "stopped searching" ──────────────────────

def test_a_weak_result_does_not_end_the_search():
    """FORWARD COMPATIBILITY. A low-confidence result is not the engine
    giving up: the numbers are recorded and the phase stays `searching`, so a
    later keep-searching engine leaves the badge on "still trying" with
    nothing to change here. Never re-key this off window exhaustion."""
    lock_state.note_searching(URI, windows_total=4)
    for _ in range(4):
        lock_state.note_window_done(URI)
    lock_state.note_outcome(URI, locked=False, offset_ms=1325, quality=0.39)

    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_SEARCHING, (
        "running out of planned windows is not, by itself, a failed lock"
    )
    assert rec["offset_ms"] == 1325, "the best-so-far is already carried"


def test_only_the_end_of_the_search_resolves_it():
    lock_state.note_searching(URI, windows_total=2)
    lock_state.note_outcome(URI, locked=False, reason="no_measurements")
    assert lock_state.for_uri(URI)["phase"] == lock_state.PHASE_SEARCHING
    lock_state.note_search_ended(URI)
    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_UNLOCKED
    assert rec["reason"] == "no_measurements", (
        "the specific reason outranks the end-of-search caller's generic one"
    )


def test_a_search_cannot_outlive_the_task_that_was_searching():
    """The sweep task's done-callback is the backstop: a sweep killed by an
    unexpected exception (or cancelled) still resolves the badge instead of
    leaving it saying "Searching…" forever."""

    async def run(die):
        lock_state.note_searching(URI, windows_total=4)

        async def sweep():
            if die == "raise":
                raise RuntimeError("boom inside the sweep")
            await asyncio.sleep(3600)

        task = asyncio.create_task(sweep())
        task.add_done_callback(lambda _t, _u=URI: lock_state.note_search_ended(_u))
        if die == "cancel":
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await _drain()
        return lock_state.for_uri(URI)

    for die in ("raise", "cancel"):
        lock_state.clear()
        rec = asyncio.run(run(die))
        assert rec["phase"] == lock_state.PHASE_UNLOCKED, (
            f"a sweep that ended by {die} left the badge mid-search"
        )


# ── TWO(b) — the REAL sweep entry, not a model of it ─────────────────────────

def _track(uri: str = URI, progress_ms: int = 2000):
    from models.state import SpotifyTrackInfo
    return SpotifyTrackInfo(
        spotify_uri=uri, title="t", artist="a", duration_ms=240_000,
        progress_ms=progress_ms, is_playing=True, fetched_at=time.monotonic(),
    )


def _meta():
    from types import SimpleNamespace
    return SimpleNamespace(capture_complete=True, xcorr_windows=[],
                           offset_verification="auto_verified")


def test_the_real_sweep_entry_reports_searching_and_cannot_get_stuck(monkeypatch):
    """Drives services/auto_offset_service.on_track_change itself — the real
    note_searching, the real create_task, the real done-callback — with only
    the sweep body replaced. A backstop this test MODELLED would be a backstop
    no proof exercises."""
    import services.auto_offset_service as aos
    from models.state import state as app_state

    monkeypatch.setattr(app_state, "on_target_device", True)
    monkeypatch.setattr(app_state, "active_setlist_id", None)
    monkeypatch.setattr(aos, "load_audio_shape_meta", lambda _uri: _meta())
    monkeypatch.setattr(aos.AutoOffsetService, "_get_or_compute_windows",
                        lambda self, uri, meta: [(30_000, 40_000), (60_000, 70_000)])

    seen: dict = {}

    async def exploding_sweep(self, uri, windows, verification, play_type):
        # Snapshot what the badge says while the sweep is genuinely running,
        # then die the way an unexpected error would.
        seen["during"] = lock_state.for_uri(uri)
        raise RuntimeError("boom inside the sweep")

    monkeypatch.setattr(aos.AutoOffsetService, "_detect_loop_xcorr", exploding_sweep)

    async def run():
        svc = aos.AutoOffsetService()
        await svc.on_track_change(_track())
        await asyncio.gather(svc._task, return_exceptions=True)
        await _drain()
        return lock_state.for_uri(URI)

    after = asyncio.run(run())
    assert seen["during"]["phase"] == lock_state.PHASE_SEARCHING
    assert seen["during"]["windows_total"] == 2
    assert seen["during"]["play_type"] == "first"
    assert after["phase"] == lock_state.PHASE_UNLOCKED, (
        "a sweep that died left the badge saying Searching… forever"
    )


def test_the_real_skip_paths_say_why(monkeypatch):
    import services.auto_offset_service as aos
    from models.state import state as app_state

    monkeypatch.setattr(app_state, "on_target_device", True)

    # No usable audio shape — the real early return.
    monkeypatch.setattr(aos, "load_audio_shape_meta", lambda _uri: None)
    asyncio.run(aos.AutoOffsetService().on_track_change(_track()))
    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_SKIPPED and rec["reason"] == "no_shape"

    # Set List opt-out — the user's tuned offset is deliberately left alone.
    lock_state.clear()
    monkeypatch.setattr(aos, "load_audio_shape_meta", lambda _uri: _meta())
    monkeypatch.setattr(app_state, "active_setlist_id", "sl-1")
    monkeypatch.setattr(app_state, "active_setlist_xcorr_enabled", False)
    asyncio.run(aos.AutoOffsetService().on_track_change(_track()))
    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_SKIPPED and rec["reason"] == "setlist_disabled"

    # Already past every planned window.
    lock_state.clear()
    monkeypatch.setattr(app_state, "active_setlist_xcorr_enabled", True)
    monkeypatch.setattr(aos.AutoOffsetService, "_get_or_compute_windows",
                        lambda self, uri, meta: [(10_000, 20_000)])
    asyncio.run(aos.AutoOffsetService().on_track_change(_track(progress_ms=120_000)))
    rec = lock_state.for_uri(URI)
    assert rec["phase"] == lock_state.PHASE_SKIPPED and rec["reason"] == "no_windows"


# ── THREE — one record, uri-keyed, pushed once ───────────────────────────────

def test_the_previous_song_never_speaks_for_this_one():
    lock_state.note_searching(OTHER, windows_total=2)
    assert lock_state.for_uri(URI) is None
    assert lock_state.for_uri(OTHER)["phase"] == lock_state.PHASE_SEARCHING
    assert lock_state.for_uri(None) is None
    # Notes for a song that is no longer the record are ignored outright.
    lock_state.note_window_done(URI)
    lock_state.note_outcome(URI, locked=True)
    lock_state.note_search_ended(URI)
    assert lock_state.for_uri(OTHER)["phase"] == lock_state.PHASE_SEARCHING


def test_every_transition_pushes_and_an_unchanged_one_does_not(ws):
    """on_track_change re-runs on every Spotify poll, so an unchanged skip
    reason would otherwise re-broadcast once a second."""

    async def run():
        lock_state.note_skipped(URI, "setlist_disabled")
        await _drain()
        first = len(ws.sent)
        for _ in range(5):
            lock_state.note_skipped(URI, "setlist_disabled")
        await _drain()
        repeated = len(ws.sent)
        lock_state.note_skipped(URI, "no_windows")
        await _drain()
        return first, repeated, len(ws.sent)

    first, repeated, changed = asyncio.run(run())
    assert first == 1, "the first skip pushes"
    assert repeated == 1, "five identical polls push nothing more"
    assert changed == 2, "a changed reason pushes again"
    assert ws.sent[0]["type"] == "lock_state" and ws.sent[0]["uri"] == URI
    assert ws.sent[0]["phase"] == lock_state.PHASE_SKIPPED


def test_the_whole_lifecycle_is_pushed_in_order(ws):
    async def run():
        lock_state.note_searching(URI, windows_total=2, play_type="natural")
        lock_state.note_window_done(URI)
        lock_state.note_outcome(URI, locked=False, offset_ms=1325, quality=0.39)
        lock_state.note_search_ended(URI)
        await _drain()
        return [m["phase"] for m in ws.sent]

    assert asyncio.run(run()) == [
        lock_state.PHASE_SEARCHING,   # started
        lock_state.PHASE_SEARCHING,   # window progress
        lock_state.PHASE_SEARCHING,   # weak result, still looking
        lock_state.PHASE_UNLOCKED,    # engine stopped searching
    ]


def test_a_push_failure_never_loses_the_record(monkeypatch):
    """No running loop (offline scripts) or a broken websocket: the record
    still stands, and the next state broadcast carries it."""
    lock_state.note_searching(URI, windows_total=1)   # no loop running here
    assert lock_state.for_uri(URI)["phase"] == lock_state.PHASE_SEARCHING


# ── FOUR — the poll backstop, so a client that connects mid-song is not blind ─

def test_the_state_broadcast_carries_the_record_filtered_to_the_playing_song():
    import time as _time
    from models.state import AppState, SpotifyTrackInfo
    from services import websocket_manager as wm

    track = SpotifyTrackInfo(
        spotify_uri=URI, title="t", artist="a", duration_ms=200_000,
        progress_ms=1000, is_playing=True, fetched_at=_time.monotonic(),
    )
    state = AppState()
    state.current_track = track

    sent: list[dict] = []

    class _Capture(wm.WebSocketManager):
        async def broadcast(self, payload):     # noqa: D401
            sent.append(payload)

    mgr = _Capture()

    lock_state.note_searching(URI, windows_total=4)
    lock_state.note_window_done(URI)
    asyncio.run(mgr.broadcast_state(state))
    assert sent[-1]["lock_state"]["phase"] == lock_state.PHASE_SEARCHING
    assert sent[-1]["lock_state"]["windows_done"] == 1

    # A record for a different song is filtered out rather than mis-rendered.
    lock_state.clear()
    lock_state.note_outcome(OTHER, locked=True)      # ignored: no record yet
    lock_state.note_searching(OTHER, windows_total=1)
    asyncio.run(mgr.broadcast_state(state))
    assert sent[-1]["lock_state"] is None


# ── FIVE — it cannot reach a single timing or lock decision ──────────────────

def _lock_state_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "lock_state"
    ]


def test_no_lock_state_call_can_influence_the_sweep():
    """Every `lock_state.*` call in the sweep is a bare statement whose value
    is discarded — never a condition, an assignment, an argument or a return
    — so nothing this feature reports can feed back into an offset, a
    threshold or a lock decision. Read AGENTS.md "Timing and offset-direction
    conventions" before relaxing this."""
    src = (REPO / "services" / "auto_offset_service.py").read_text()
    tree = ast.parse(src)
    calls = _lock_state_calls(tree)
    assert len(calls) >= 8, f"expected the reporting call sites, found {len(calls)}"

    # A call's value is discarded iff it is the whole of an expression
    # statement, or the whole body of the done-callback lambda.
    discarded = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)}
    discarded |= {id(n.body) for n in ast.walk(tree) if isinstance(n, ast.Lambda)}
    for call in calls:
        assert id(call) in discarded, (
            f"lock_state call at line {call.lineno} feeds a value into the sweep"
        )


def test_lock_state_returns_nothing_and_holds_no_engine_import():
    src = (REPO / "services" / "lock_state.py").read_text()
    tree = ast.parse(src)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if not fn.name.startswith("note_"):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Return):
                assert node.value is None, f"{fn.name} returns a value the sweep could read"

    # Its docstring names the sweep it observes; what must not exist is a
    # DEPENDENCY on it, so read the imports and the identifiers, not the prose.
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {a.name for a in node.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for banned in ("auto_offset_service", "xcorr_core", "xcorr_sweep",
                   "trigger_engine", "anchor_detector", "lock_history"):
        assert not any(banned in m.split(".") for m in imported), (
            f"lock_state must not import {banned} — it reports, it never decides"
        )
        assert banned not in used, f"lock_state must not reference {banned}"


def test_the_timing_kernels_are_untouched_by_this_feature():
    """Every lock and offset decision lives in these modules, and this
    feature does not appear in any of them."""
    for mod in ("services/xcorr_core.py", "services/xcorr_sweep.py",
                "services/lock_history.py", "services/trigger_engine.py"):
        src = (REPO / mod).read_text()
        assert "lock_state" not in src, f"{mod} should know nothing about the badge"
