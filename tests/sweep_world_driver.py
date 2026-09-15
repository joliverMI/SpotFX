"""
A scripted world for driving the REAL auto-offset sweep end to end.

`services/auto_offset_service.AutoOffsetService.on_track_change` →
`_detect_loop_xcorr` is run exactly as it ships — its own frame loop, its own
planned-queue dispatch, drift monitor, done-callback and post-loop finalize —
with only the edges of the world replaced:

  * the live capture (frames on a fixed 100 ms clock, ending at song end);
  * the math kernel (`_xcorr_window`, `_eval_at_shift`, `_difficulty_score`,
    `_mismatch_spike`, `_max_frame_gap_ms`) — answered from a `World`
    describing where the song truly aligns and how clearly each stretch of it
    can be measured, so which windows find what is decided up front;
  * the trigger engine (`main.engine`) — a stand-in that keeps the real
    engine's one gate that matters here, "a snap must strictly beat this
    play's best Q";
  * disk (`_save_offset`, the offset-history write, `lock_history.record`)
    and the websocket, both recorded.

The decision logic between those edges — `SweepEvaluator`, `MismatchMonitor`,
`KeepSearching` and every branch of the loop — is the production code, not a
model of it.

`load_baseline_module()` loads the sweep as it stood BEFORE keep-searching
(`BASELINE_REF`, pinned — a moving ref retires a byte-identity proof the day
this change merges) so the same world can be run through both and the two
recorded traces compared.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable, Optional

import numpy as np

REPO = Path(__file__).resolve().parent.parent
URI = "spotify:track:mayday"

# master at PR #266 (the lock badge), immediately before keep-searching.
BASELINE_REF = "4795fd3a69391e0577bdfc8a2bc8e597e4fd1910"

FRAME_MS = 100


def load_baseline_module() -> ModuleType:
    """`services/auto_offset_service.py` as of BASELINE_REF, as its own module.
    Raises (never skips) when git cannot produce it: a byte-identity proof
    that quietly skips reads exactly like one that passed."""
    src = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:services/auto_offset_service.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    name = "auto_offset_service_baseline_4795fd3"
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(REPO / "services" / "auto_offset_service.py")
    exec(compile(src, f"<{BASELINE_REF[:7]}:services/auto_offset_service.py>", "exec"),
         mod.__dict__)
    return mod


def current_module() -> ModuleType:
    import services.auto_offset_service as aos
    return aos


# ── The world ─────────────────────────────────────────────────────────────────

@dataclass
class World:
    """What the song looks like to the matcher.

    `truth(stored_ms)` is the offset the song truly aligns at around that
    stored position; `clarity(stored_ms)` is `(r, difficulty)` — how strongly
    a window starting there correlates at the truth, and how dynamic it is.
    A window finds NEW `(truth, r)` when `r` clears 0.5; OLD scores `r` only
    when tested at the truth, else `off_r`."""
    duration_ms: int
    windows: list[tuple[int, int]]
    loaded_offset_ms: int
    truth: Callable[[int], int]
    clarity: Callable[[int], tuple[float, float]]
    verification: str = "auto_verified"
    off_r: float = 0.05
    # (win_start, win_end, spike_ms) for a spike asked for at (t_now, engine_offset)
    spike: Optional[Callable[[int, int], Optional[tuple[int, int, int]]]] = None
    # Hold the capture open at this song time until cancelled (a track change).
    hang_at_ms: Optional[int] = None


def mayday_world(**over) -> World:
    """MAYDAY, 2026-09-08 21:15 (spotfx.service): four planned windows in the
    first ~30s, a far jump to +1325 distrusted for want of prior agreement,
    `final offset=+1325ms Q=0.39`, grade F. Here the stretch from 60s on is
    clean, so a search that is still running there can lock."""
    base = dict(
        duration_ms=247_339,
        windows=[(10_000, 15_000), (16_000, 21_000), (22_000, 27_000), (27_500, 32_500)],
        loaded_offset_ms=-2091,
        truth=lambda _ms: 1325,
        clarity=lambda ms: (0.95, 1.0) if ms >= 60_000 else (0.65, 0.6),
    )
    base.update(over)
    return World(**base)


def default_spike(t_now_ms: int, _engine_offset_ms: int) -> tuple[int, int, int]:
    """A distinctive spot a few seconds back in the recent audio."""
    spike_ms = t_now_ms - 4000
    return (spike_ms - 2500, spike_ms + 2500, spike_ms)


# ── Edges ─────────────────────────────────────────────────────────────────────

class _Npz(dict):
    @property
    def files(self):
        return list(self.keys())


class FakeEngine:
    """`main.engine`, reduced to the state the sweep reads and the gate that
    decides whether a snap lands: it must strictly beat this play's best Q."""

    def __init__(self, loaded_offset_ms: int) -> None:
        self._shape_offset_ms = int(loaded_offset_ms)
        self._play_best_quality = 0.0
        self.calls: list[tuple] = []

    def apply_save(self, uri, raw_offset_ms, quality, source="sweep",
                   bypass_drift_cap=False):
        applied = float(quality) > self._play_best_quality
        self.calls.append(("apply_save", uri, int(raw_offset_ms),
                           round(float(quality), 6), source, bool(bypass_drift_cap),
                           applied))
        if applied:
            self._shape_offset_ms = int(raw_offset_ms)
            self._play_best_quality = float(quality)
        return applied

    def demote_play_best(self, uri, ceiling, reason="monitor"):
        self.calls.append(("demote", uri, float(ceiling), reason))
        if self._play_best_quality > ceiling:
            self._play_best_quality = float(ceiling)


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def broadcast(self, payload: dict) -> None:
        self.sent.append(dict(payload))


class _Frame(SimpleNamespace):
    pass


def _capture_class(world: World, trace: "Trace", real_sleep):
    class FakeCapture:
        def __init__(self, _song_start):
            self._t = 0
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            trace.capture_stopped_at = self._t

        def __aiter__(self):
            return self

        async def __anext__(self):
            await real_sleep(0)
            if world.hang_at_ms is not None and self._t >= world.hang_at_ms:
                trace.hung = True
                await asyncio.Event().wait()       # until cancelled
            if self._t > world.duration_ms:
                raise StopAsyncIteration
            f = _Frame(timestamp_ms=self._t, rms_total=0.0, rms_low=0.0,
                       rms_mid=0.0, rms_high=0.0)
            trace.last_frame_ms = self._t
            self._t += FRAME_MS
            return f

    return FakeCapture


@dataclass
class Trace:
    """Every side effect the sweep produced, in order."""
    kernel: list[tuple] = field(default_factory=list)
    saves: list[tuple] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    lock_during: list[Optional[dict]] = field(default_factory=list)
    last_frame_ms: int = -1
    capture_stopped_at: int = -1
    hung: bool = False
    engine: Optional[FakeEngine] = None
    ws: Optional[FakeWs] = None
    final_lock_state: Optional[dict] = None
    after_poll_lock_state: Optional[dict] = None
    watching_after: Optional[str] = None
    task_after_poll: bool = False

    def comparable(self) -> dict:
        """The trace with wall-clock stamps removed — everything else must
        match byte for byte between two runs of the same world."""
        def strip(d):
            return None if d is None else {k: v for k, v in d.items() if k != "at_ms"}
        return {
            "kernel": self.kernel,
            "engine": self.engine.calls,
            "saves": self.saves,
            "history": self.history,
            "ws": [strip(m) for m in self.ws.sent],
            "logs": self.logs,
            "last_frame_ms": self.last_frame_ms,
            "capture_stopped_at": self.capture_stopped_at,
            "final_lock_state": strip(self.final_lock_state),
            "after_poll_lock_state": strip(self.after_poll_lock_state),
            "watching_after": self.watching_after,
            "task_after_poll": self.task_after_poll,
        }

    def windows_evaluated(self) -> list[tuple[int, int]]:
        return [(c[1], c[2]) for c in self.kernel if c[0] == "xcorr_window"]


class _ListHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(logging.INFO)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(record.getMessage())


SETTINGS = dict(
    xcorr_monitor_enabled=True,
    xcorr_fft_enabled=False,
    xcorr_accum_enabled=False,
    xcorr_search_ladder_enabled=False,
    xcorr_progressive_enabled=False,
    xcorr_csv_logging=False,
    anchor_enabled=False,
    xcorr_global_threshold=0.50,
    xcorr_lock_q=0.70,
    xcorr_lock_agree_windows=3,
    xcorr_save_confirm_tol_ms=300,
    xcorr_save_min_confirm=2.0,
    xcorr_save_min_quality=0.50,
    engine_snap_far_jump_ms=1000,
    engine_snap_far_jump_q=0.85,
    xcorr_monitor_interval_ms=2000,
    xcorr_monitor_confirm_checks=3,
    xcorr_monitor_min_r=0.20,
    xcorr_monitor_max_recoveries=2,
    xcorr_window_max_gap_ms=200,
    xcorr_keep_searching_enabled=True,
    xcorr_keep_searching_interval_ms=5000,
    xcorr_keep_searching_give_up_ms=45000,
)


def run_world(mod: ModuleType, world: World, monkeypatch, tmp_path: Path, *,
              settings_over: Optional[dict] = None,
              poll_after_ms: Optional[int] = None,
              stop_after: bool = False) -> Trace:
    """Run one play of `world` through `mod`'s real sweep. `poll_after_ms`
    re-runs `on_track_change` once the sweep has ended, as the next Spotify
    poll would, at that song position. `stop_after` stops the service as a
    track change does (for a world that hangs its capture)."""
    from config import settings
    from models.state import SpotifyTrackInfo, state as app_state
    from services import lock_state
    import services
    import services.lock_history as lock_history
    import services.websocket_manager as wm

    trace = Trace()
    lock_state.clear()

    fields = type(settings).model_fields
    for k, v in {**SETTINGS, **(settings_over or {})}.items():
        if k in fields:
            monkeypatch.setattr(settings, k, v)
        else:
            # Not a Settings field: SweepConfig/MonitorConfig read it through
            # getattr with a default, which must be the value this world means.
            from services.xcorr_sweep import MonitorConfig, SweepConfig
            got = {**vars(SweepConfig.from_settings(settings)),
                   **vars(MonitorConfig.from_settings(settings))}
            key = {"xcorr_save_confirm_tol_ms": "save_confirm_tol_ms",
                   "xcorr_save_min_confirm": "save_min_confirm",
                   "xcorr_save_min_quality": "save_min_quality",
                   "engine_snap_far_jump_q": "engine_snap_far_jump_q",
                   "engine_snap_far_jump_ms": "engine_snap_far_jump_ms"}.get(k)
            assert key is not None and got[key] == v, (k, v, got.get(key))

    real_sleep = asyncio.sleep

    async def fast_sleep(_delay=0, result=None):
        await real_sleep(0)
        return result

    async def inline_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)

    # Stored shape: every band is a ramp of its own timestamps, so a template
    # interpolated for a window begins with that window's start — which is
    # how the difficulty stub knows where it is being asked about.
    stored_ts = np.arange(0, world.duration_ms + FRAME_MS, FRAME_MS, dtype=float)
    npz = _Npz({"timestamps_ms": stored_ts})
    for b in ("rms_total", "rms_low", "rms_mid", "rms_high"):
        npz[b] = stored_ts.copy()
        npz[b + "_sq"] = stored_ts.copy()
    monkeypatch.setattr(np, "load", lambda _p, *a, **k: npz)

    meta = SimpleNamespace(
        capture_complete=True, npz_file="world.npz",
        xcorr_windows=[{"start_ms": s, "end_ms": e, "difficulty": 1.0}
                       for s, e in world.windows],
        offset_verification=world.verification,
        timestamp_offset_ms=world.loaded_offset_ms, offset_quality=0.5,
        offset_history=[], setlist_offsets={}, duration_ms=world.duration_ms,
        anchor_candidates=[], title="MAYDAY", artist="world",
        model_dump_json=lambda **_k: "{}",
    )

    engine = FakeEngine(world.loaded_offset_ms)
    trace.engine = engine
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(engine=engine))
    fake_librosa = SimpleNamespace(get_analysis=lambda _m: None)
    monkeypatch.setitem(sys.modules, "services.librosa_service", fake_librosa)
    monkeypatch.setattr(services, "librosa_service", fake_librosa, raising=False)
    fake_ass = SimpleNamespace(audio_shape_service=SimpleNamespace(_recording_uri=None))
    monkeypatch.setitem(sys.modules, "services.audio_shape_service", fake_ass)
    monkeypatch.setattr(services, "audio_shape_service", fake_ass, raising=False)

    ws = FakeWs()
    trace.ws = ws
    monkeypatch.setattr(wm, "ws_manager", ws)
    monkeypatch.setattr(lock_history, "record",
                        lambda **kw: trace.history.append(dict(kw)))

    def k_difficulty(template, _song):
        return float(world.clarity(int(template[0]))[1]) if len(template) else 0.0

    def k_eval(_ts, _bands, _frames, ws_, we_, shift_ms):
        trace.kernel.append(("eval_at_shift", int(ws_), int(we_), int(shift_ms)))
        r, _d = world.clarity(int(ws_))
        return r if -int(shift_ms) == world.truth(int(ws_)) else world.off_r

    def k_xcorr(_ts, _bands, _frames, ws_, we_, *, search_ms, old_r=None, tempo_bpm=None):
        trace.kernel.append(("xcorr_window", int(ws_), int(we_)))
        trace.lock_during.append(lock_state.for_uri(URI))
        r, _d = world.clarity(int(ws_))
        return (world.truth(int(ws_)), r) if r >= 0.5 else None

    def k_spike(_ts, _bands, _frames, *, engine_offset_ms, t_now_ms,
                lookback_ms, halfwin_ms):
        fn = world.spike or default_spike
        got = fn(int(t_now_ms), int(engine_offset_ms))
        trace.kernel.append(("mismatch_spike", int(t_now_ms), int(engine_offset_ms), got))
        if got is None:
            return None
        return (int(got[0]), int(got[1]), int(got[2]), 0.8)

    def record_save(uri, offset_ms, quality=0.0, source="sweep", bypass_drift_cap=False):
        trace.saves.append((uri, int(offset_ms), round(float(quality), 6), source,
                            bool(bypass_drift_cap)))

    patches = {
        "AudioCaptureStream": _capture_class(world, trace, real_sleep),
        "load_audio_shape_meta": lambda _uri: meta,
        "AUDIO_SHAPES_DIR": tmp_path,
        "_difficulty_score": k_difficulty,
        "_eval_at_shift": k_eval,
        "_xcorr_window": k_xcorr,
        "_mismatch_spike": k_spike,
        "_max_frame_gap_ms": lambda *_a, **_k: 0,
        "_save_offset": record_save,
        "_save_offset_from_anchor": lambda uri, o, q: record_save(uri, o, q, source="anchor"),
    }
    for name, value in patches.items():
        monkeypatch.setattr(mod, name, value)
    monkeypatch.setattr(mod.AutoOffsetService, "_get_or_compute_windows",
                        lambda self, uri, m: list(world.windows))

    monkeypatch.setattr(app_state, "on_target_device", True)
    monkeypatch.setattr(app_state, "active_setlist_id", None)
    monkeypatch.setattr(app_state, "active_setlist_xcorr_enabled", True)

    def track_at(progress_ms: int):
        import time
        return SpotifyTrackInfo(
            spotify_uri=URI, title="MAYDAY", artist="world",
            duration_ms=world.duration_ms, progress_ms=progress_ms,
            is_playing=True, fetched_at=time.monotonic(),
        )

    monkeypatch.setattr(app_state, "current_track", track_at(500))

    handler = _ListHandler(trace.logs)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    async def drive():
        svc = mod.AutoOffsetService()
        await svc.on_track_change(track_at(500))
        task = svc._task
        if stop_after:
            while not trace.hung:
                await real_sleep(0)
            for _ in range(5):
                await real_sleep(0)
            await svc._stop()
        await asyncio.gather(task, return_exceptions=True)
        for _ in range(5):
            await real_sleep(0)
        trace.final_lock_state = lock_state.for_uri(URI)
        trace.watching_after = svc._watching_uri
        if poll_after_ms is not None:
            # The previous poll landed a second earlier, as it does live —
            # without it on_track_change reads the jump from 500ms as a skip.
            svc._last_track_snapshot = (URI, poll_after_ms - 1000, world.duration_ms)
            await svc.on_track_change(track_at(poll_after_ms))
            trace.task_after_poll = svc._task is not None
            if svc._task is not None:
                svc._task.cancel()
                await asyncio.gather(svc._task, return_exceptions=True)
            for _ in range(5):
                await real_sleep(0)
            trace.after_poll_lock_state = lock_state.for_uri(URI)

    try:
        asyncio.run(drive())
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
        lock_state.clear()
    return trace
