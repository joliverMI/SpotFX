"""
Offline replay of one xcorr play.

Reproduces the production loop's event order against synthesized frames:
pre-flight window injection → progressive anchor horizon crossings →
per-window difficulty/OLD/NEW (services.xcorr_core) → SweepEvaluator
decisions → FakeEngine snaps / FakeMetaStore saves → lock-and-stop →
finalize. Windows and anchor horizons are processed on a merged
chronological timeline, matching the live frame loop.

Differences vs live (deliberate, deterministic):
  * frames available at an event = all frames with ts ≤ event time (live
    workers may see a few extra frames due to compute latency);
  * song_start stabilization jitter doesn't exist (frames are exact);
  * perception trim = 0.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from config import settings, AUDIO_SHAPES_DIR
from models.audio_shape import AudioShapeMeta
from services import anchor_detector
from services import xcorr_core
from services.xcorr_sweep import (
    MismatchMonitor, MonitorConfig, SweepConfig, SweepEvaluator,
)
from bench.simulate import FakeEngine, FakeMetaStore, Frame, load_wav, make_frames

_XCORR_MARGIN_MS = 1_000        # mirrors auto_offset_service
_PRE_FLIGHT_INTRO_MS = 8_000


@dataclass
class Scenario:
    name: str
    true_offset_ms: int = 0
    cut_in_ms: int = 0
    gain: float = 1.0
    noise_snr_db: Optional[float] = None
    blend_ms: int = 0
    blend_donor: Optional[str] = None       # corpus stem for donor tail
    offset_change_at_ms: int = 0             # midshift: clock time of a position re-sync
    offset_change_delta_ms: int = 0          # midshift: expected offset steps by this
    gap_at_ms: int = 0                       # capture-stall: drop frames from here
    gap_len_ms: int = 0                      # capture-stall: for this duration
    seed: str = "cold"                       # cold | seeded_correct | seeded_wrong_2s | snapshot
    seed_snapshot: Optional[dict] = None     # FakeMetaStore.snapshot() of a prior play
    play_type: str = "first"
    force_search_ms: Optional[int] = None    # override mix-aware search range


@dataclass
class WindowTrace:
    win_start: int
    win_end: int
    difficulty: float
    old_r: float
    new_offset_ms: Optional[int]
    new_r: Optional[float]
    winner: str
    win_offset: int
    win_r: float
    win_quality: float
    is_global_best: bool
    envelope_clipped: bool
    cpu_ms: float


@dataclass
class PlayResult:
    stem: str
    scenario: str
    expected_offset_ms: int
    # Outcome
    final_stored_offset_ms: Optional[int]    # slot offset after play (None = never saved)
    final_stored_error_ms: Optional[int]
    engine_final_offset_ms: int
    engine_final_error_ms: int
    time_to_first_correct_lock_ms: Optional[int]   # song-time; |err|≤100 and never wrong later
    wrong_lock_events: int                   # disk saves with |error| > 300ms
    n_saves: int
    anchor_matched: bool
    progressive_matched: bool
    locked_via_stop: bool
    windows_evaluated: int
    windows_planned: int
    # CPU
    cpu_ms_total: float
    cpu_ms_p50: float
    cpu_ms_p95: float
    engine_correct_time_pct: float = 0.0     # % of song time engine offset within 300ms
    monitor_recoveries: int = 0
    traces: list[WindowTrace] = field(default_factory=list)
    store_snapshot: dict = field(default_factory=dict)   # seeds two-play scenarios

    @property
    def correct(self) -> bool:
        return (self.final_stored_error_ms is not None
                and abs(self.final_stored_error_ms) <= 300)


def load_song_assets(stem: str) -> dict:
    """Load NPZ bands + sidecar meta + librosa tempo + WAV pcm for a stem."""
    npz_path = AUDIO_SHAPES_DIR / f"{stem}.npz"
    json_path = AUDIO_SHAPES_DIR / f"{stem}.json"
    wav_path = AUDIO_SHAPES_DIR / f"{stem}.wav"
    librosa_path = AUDIO_SHAPES_DIR / f"{stem}.librosa.json"

    meta = AudioShapeMeta(**json.loads(json_path.read_text(encoding="utf-8")))
    data = np.load(npz_path)
    stored_ts = data["timestamps_ms"].astype(float)

    def _band(name: str) -> np.ndarray:
        sq_key = f"{name}_sq"
        if sq_key in data.files:
            return np.asarray(data[sq_key], dtype=float)
        return xcorr_core.signed_square(np.asarray(data[name], dtype=float))

    stored_bands = [_band("rms_total"), _band("rms_low"),
                    _band("rms_mid"), _band("rms_high")]

    tempo_bpm = None
    if librosa_path.exists():
        try:
            tempo = json.loads(librosa_path.read_text(encoding="utf-8")).get("tempo_bpm")
            tempo_bpm = float(tempo) if tempo else None
        except Exception:
            tempo_bpm = None

    return {
        "meta": meta,
        "stored_ts": stored_ts,
        "stored_bands": stored_bands,
        "tempo_bpm": tempo_bpm,
        "wav_path": wav_path,
    }


def search_ms_for(meta: AudioShapeMeta, scenario: Scenario) -> int:
    """Mirror _xcorr_search_ms: base + max(0, captured − polled) + buffer.
    A blended cut-in models Spotify reporting the mix-trimmed duration."""
    if scenario.force_search_ms is not None:
        return int(scenario.force_search_ms)
    polled = int(meta.duration_ms or 0) - int(scenario.cut_in_ms)
    cut_ms = max(0, int(meta.duration_ms or 0) - polled)
    return int(settings.xcorr_search_ms_base + cut_ms + settings.xcorr_cut_buffer_ms)


def replay_play(stem: str, scenario: Scenario, *,
                assets: Optional[dict] = None,
                frames: Optional[list[Frame]] = None,
                wav_bias_ms: Optional[int] = None,
                verbose: bool = False) -> PlayResult:
    """Replay one play of `stem` under `scenario`. Pass `assets`/`frames` to
    reuse expensive loads across scenarios of the same song.

    `wav_bias_ms` is the song's stored WAV↔NPZ misalignment (see
    bench.calibrate) — the expected offset for the play is
    `scenario.true_offset_ms + wav_bias_ms`. When None it's looked up (and
    cached) automatically."""
    uri = "bench:play"
    if assets is None:
        assets = load_song_assets(stem)
    if wav_bias_ms is None:
        from bench.calibrate import wav_bias
        wav_bias_ms = wav_bias(stem, assets)
        if wav_bias_ms is None:
            raise RuntimeError(f"{stem}: WAV↔NPZ bias calibration failed — "
                               "song unusable for replay")
    meta: AudioShapeMeta = assets["meta"]
    stored_ts = assets["stored_ts"]
    stored_bands = assets["stored_bands"]
    stored_rms = stored_bands[1]   # squared rms_low — difficulty scoring band
    tempo_bpm = assets["tempo_bpm"]

    if frames is None:
        donor_pcm = None
        if scenario.blend_donor and scenario.blend_ms > 0:
            donor_pcm = load_wav(AUDIO_SHAPES_DIR / f"{scenario.blend_donor}.wav")
        frames = make_frames(
            load_wav(assets["wav_path"]),
            true_offset_ms=scenario.true_offset_ms,
            cut_in_ms=scenario.cut_in_ms,
            gain=scenario.gain,
            noise_snr_db=scenario.noise_snr_db,
            blend_donor_pcm=donor_pcm,
            blend_ms=scenario.blend_ms,
            offset_change_at_ms=scenario.offset_change_at_ms,
            offset_change_delta_ms=scenario.offset_change_delta_ms,
            gap_at_ms=scenario.gap_at_ms,
            gap_len_ms=scenario.gap_len_ms,
        )
    last_frame_ts = frames[-1][0] if frames else 0

    # ── Windows: cached plan + pre-flight injection (mirrors on_track_change) ──
    all_windows = [(int(w["start_ms"]), int(w["end_ms"]))
                   for w in (meta.xcorr_windows or [])]
    windows = list(all_windows)   # current_pos = 0 → all reachable
    first_planned = windows[0][0] if windows else None
    if (not settings.xcorr_progressive_enabled   # progressive replaces pre-flight
            and first_planned is not None
            and first_planned >= _PRE_FLIGHT_INTRO_MS
            and (not all_windows or all_windows[0][0] != 0)):
        windows.insert(0, (0, _PRE_FLIGHT_INTRO_MS))

    envelope_lookup: dict[tuple[int, int], tuple[int, int]] = {}
    for w in (meta.xcorr_windows or []):
        try:
            envelope_lookup[(int(w["start_ms"]), int(w["end_ms"]))] = (
                int(w.get("safe_neg_ms", -10**9)),
                int(w.get("safe_pos_ms", 10**9)),
            )
        except (KeyError, TypeError, ValueError):
            continue
    diff_lookup = {(int(w["start_ms"]), int(w["end_ms"])): float(w.get("difficulty", 0))
                   for w in (meta.xcorr_windows or [])}

    # ── Seed state per scenario ────────────────────────────────────────────────
    # Expected offset = injected truth + the song's stored WAV↔NPZ bias.
    expected = int(scenario.true_offset_ms) + int(wav_bias_ms)
    seed_cut_in: Optional[int] = None
    if scenario.seed == "snapshot" and scenario.seed_snapshot:
        snap = scenario.seed_snapshot
        seed_history = list(snap.get("history") or [])
        seed_q = float(snap.get("quality") or 0.0)
        coarse_locked = bool(snap.get("coarse_locked"))
        seed_cut_in = snap.get("observed_cut_in_ms")
    elif scenario.seed == "seeded_correct":
        seed_history, seed_q, coarse_locked = [expected] * 3, 0.8, True
    elif scenario.seed == "seeded_wrong_2s":
        seed_history, seed_q, coarse_locked = [expected + 2000] * 3, 0.8, True
    elif scenario.seed == "seeded_wrong_beat":
        # Wrong by exactly one beat period — the beat-tile twin trap. The
        # residual stays low through periodic content and spikes only at
        # pattern boundaries (the monitor's hardest recovery case).
        beat = int(round(60000.0 / tempo_bpm)) if tempo_bpm else 600
        seed_history, seed_q, coarse_locked = [expected + beat] * 3, 0.8, True
    else:   # cold
        seed_history, seed_q, coarse_locked = [], 0.0, False

    engine = FakeEngine(uri, loaded_offset_ms=(seed_history[0] if seed_history else 0))
    store = FakeMetaStore(engine, seed_history=seed_history,
                          seed_quality=seed_q, coarse_locked=coarse_locked,
                          observed_cut_in_ms=seed_cut_in)
    seed_offset = store.median_offset() if store.history else 0
    if seed_offset is None:
        seed_offset = store.timestamp_offset_ms

    # Phase 4: search center from history (mirrors the live derivation;
    # Set-List cross-track bias is live-only).
    history_center: Optional[int] = None
    if store.history:
        history_center = int(seed_offset)
    elif store.observed_cut_in_ms is not None:
        history_center = int(store.observed_cut_in_ms)

    # Phase 3/4 flags (mirrors the live loop's gating)
    _accum_active = settings.xcorr_accum_enabled and settings.xcorr_fft_enabled
    search_ms = search_ms_for(meta, scenario)
    ladder = None
    if settings.xcorr_search_ladder_enabled and settings.xcorr_fft_enabled:
        from services.xcorr_sweep import SearchLadder
        ladder = SearchLadder(
            history_center_ms=history_center,
            wide_span_ms=search_ms,
            narrow_span_ms=int(settings.xcorr_search_narrow_ms),
            global_span_ms=int(settings.xcorr_search_global_ms),
            duration_ms=int(meta.duration_ms or 0),
            escalate_after=int(settings.xcorr_ladder_escalate_after),
        )
    accumulator = None
    if _accum_active:
        from services.xcorr_evidence import EvidenceAccumulator
        accum_span = (max(search_ms, int(settings.xcorr_search_global_ms))
                      if ladder else search_ms)
        accumulator = EvidenceAccumulator(max_offset_ms=accum_span + 5000)
        if history_center is not None:
            if store.history:
                w_hist = min(1.0, len(store.history) / 3.0) * max(0.0, store.offset_quality)
            else:
                w_hist = 0.5
            prior_mass = float(settings.xcorr_prior_bonus_mass) * w_hist
            if prior_mass > 0:
                accumulator.add_gaussian(history_center, prior_mass,
                                         sigma_ms=float(settings.xcorr_prior_sigma_ms),
                                         count_support=False)

    evaluator = SweepEvaluator(
        SweepConfig.from_settings(settings),
        uri=uri,
        verification="auto_verified",
        play_type=scenario.play_type,
        seed_offset_ms=int(seed_offset),
        envelope_lookup=envelope_lookup,
        accumulator=accumulator,
    )

    # ── Anchor setup (mirrors the cold-start gate) ────────────────────────────
    anchor_should_run = settings.anchor_enabled and not store.coarse_locked
    anchor_candidates: list[anchor_detector.AnchorCandidate] = []
    if anchor_should_run:
        anchor_candidates = [anchor_detector.AnchorCandidate.from_dict(d)
                             for d in (meta.anchor_candidates or [])]
    _anchor_radius = int(settings.anchor_search_radius_ms) + int(settings.anchor_template_radius_ms)
    anchor_horizons = [c.timestamp_ms + _anchor_radius for c in anchor_candidates]

    # ── Merged event timeline ─────────────────────────────────────────────────
    # Tick kinds: anchor horizons, progressive ticks, monitor ticks (Phase 5),
    # and window-readiness ticks (we + margin). Window dispatch mirrors the
    # live loop exactly: a queue + readiness check after every tick, so a
    # mismatch recovery can rebuild the queue mid-play like live does.
    _prio = {"anchor": 0, "prog": 1, "monitor": 2, "tick": 3}
    events: list[tuple[int, str, object]] = []
    for h in sorted(set(anchor_horizons)):
        events.append((h, "anchor", h))
    if settings.xcorr_progressive_enabled:
        t = int(settings.xcorr_progressive_start_ms)
        while t <= last_frame_ts:
            events.append((t, "prog", None))
            t += int(settings.xcorr_progressive_interval_ms)
    monitor_enabled = bool(settings.xcorr_monitor_enabled)
    mon_cfg = MonitorConfig.from_settings(settings)
    if monitor_enabled:
        t = mon_cfg.interval_ms
        while t <= last_frame_ts:
            events.append((t, "monitor", None))
            t += mon_cfg.interval_ms
    for (ws, we) in windows:
        events.append((we + _XCORR_MARGIN_MS, "tick", None))
    events.sort(key=lambda e: (e[0], _prio[e[1]]))

    all_planned = list(windows)
    window_queue = list(windows)
    monitor = MismatchMonitor(mon_cfg)
    monitor_mode = False
    pending_dynamic: Optional[tuple[int, int]] = None

    anchor_done = not anchor_candidates
    anchor_matched = False
    anchor_last_eligible = 0
    prog_active = bool(settings.xcorr_progressive_enabled)
    prog_matched = False
    locked_via_stop = False
    traces: list[WindowTrace] = []
    cpu_samples: list[float] = []

    def expected_at(t: int) -> int:
        """Expected offset as a step function (midshift scenarios)."""
        if (scenario.offset_change_at_ms and scenario.offset_change_delta_ms
                and t >= scenario.offset_change_at_ms):
            return expected + int(scenario.offset_change_delta_ms)
        return expected

    def run_window(win_start: int, win_end: int, frames_now: list) -> bool:
        """One window evaluation + side effects. Mirrors live _run_window.
        Returns True when lock-and-stop fired."""
        # Capture-gap rejection (Phase 6) — mirrors live _run_window.
        _gap = xcorr_core.max_frame_gap_ms(
            frames_now, win_start - search_ms, win_end + search_ms)
        if _gap > settings.xcorr_window_max_gap_ms:
            return False
        t0 = time.perf_counter()

        bins = np.arange(win_start, win_end, xcorr_core.XCORR_BIN_MS, dtype=float)
        window_template = np.interp(bins, stored_ts, stored_rms)
        difficulty = xcorr_core.difficulty_score(window_template, stored_rms)

        stored_offset_ms = engine._shape_offset_ms   # engine runtime offset (live parity)
        stored_quality_for_old = float(store.offset_quality)

        old_r = xcorr_core.eval_at_shift(
            stored_ts, stored_bands, frames_now, win_start, win_end,
            -stored_offset_ms,
        )
        old_r = float(old_r) if old_r is not None else 0.0

        win_landscape = None
        stage = ladder.current if ladder else None
        if ladder is not None:
            lo, hi = stage.shift_bounds
            new_result, win_landscape = xcorr_core.xcorr_window_fft_full(
                stored_ts, stored_bands, frames_now, win_start, win_end,
                search_lo_ms=lo, search_hi_ms=hi, old_r=old_r, tempo_bpm=tempo_bpm,
            )
        elif _accum_active:
            new_result, win_landscape = xcorr_core.xcorr_window_fft_full(
                stored_ts, stored_bands, frames_now, win_start, win_end,
                search_ms=search_ms, old_r=old_r, tempo_bpm=tempo_bpm,
            )
        else:
            _sweep_fn = (xcorr_core.xcorr_window_fft if settings.xcorr_fft_enabled
                         else xcorr_core.xcorr_window)
            new_result = _sweep_fn(
                stored_ts, stored_bands, frames_now, win_start, win_end,
                search_ms=search_ms, old_r=old_r, tempo_bpm=tempo_bpm,
            )
        cpu_ms = (time.perf_counter() - t0) * 1000.0
        cpu_samples.append(cpu_ms)

        outcome = evaluator.process_window(
            win_start, win_end,
            difficulty=difficulty,
            new_result=new_result,
            old_r=old_r,
            stored_offset_ms=stored_offset_ms,
            stored_quality=stored_quality_for_old,
            engine_current_offset_ms=engine._shape_offset_ms,
            engine_play_best_quality=engine._play_best_quality,
            landscape=win_landscape,
            envelope_exempt=(stage is not None and stage.name == "global"),
        )
        if ladder is not None:
            if ladder.note_window(outcome.new_result is not None) is None \
                    and outcome.baseline_anti_corr:
                ladder.escalate_to_global()

        if outcome.engine_snap is not None:
            s_off, s_q, s_bypass = outcome.engine_snap
            engine.apply_save(uri, s_off, s_q, source="sweep-window",
                              bypass_drift_cap=s_bypass)
        if outcome.disk_save is not None:
            d_off, d_q, d_source, d_bypass = outcome.disk_save
            store.save_offset(uri, d_off, d_q, source=d_source,
                              bypass_drift_cap=d_bypass)

        traces.append(WindowTrace(
            win_start=win_start, win_end=win_end,
            difficulty=round(difficulty, 3),
            old_r=round(outcome.old_r, 3),
            new_offset_ms=outcome.new_offset_ms if outcome.new_result else None,
            new_r=round(outcome.new_r, 3) if outcome.new_result else None,
            winner="new" if outcome.is_new else "old",
            win_offset=outcome.win_offset,
            win_r=round(outcome.win_r, 3),
            win_quality=outcome.win_quality,
            is_global_best=outcome.is_global_best,
            envelope_clipped=outcome.envelope_clipped,
            cpu_ms=round(cpu_ms, 2),
        ))
        if verbose:
            tr = traces[-1]
            print(f"  [{win_start:>6}-{win_end:>6}] diff={tr.difficulty:.2f} "
                  f"OLD r={tr.old_r:+.2f}@{stored_offset_ms:+d}  "
                  f"NEW {('%+d' % tr.new_offset_ms) if tr.new_offset_ms is not None else '--'}ms "
                  f"r={tr.new_r if tr.new_r is not None else 0:.2f}  "
                  f"winner={tr.winner}{' ★' if tr.is_global_best else ''} "
                  f"({tr.cpu_ms:.1f}ms)")

        return evaluator.lock_and_stop(engine._play_best_quality)

    ended = False
    for ev_time, kind, payload in events:
        if ended or ev_time > last_frame_ts:
            break
        engine.now_ms = ev_time
        frames_now = [f for f in frames if f[0] <= ev_time]
        if not frames_now:
            continue

        if kind == "anchor":
            if not anchor_done:
                eligible = [c for c, h in zip(anchor_candidates, anchor_horizons)
                            if ev_time >= h]
                eligible_count = len(eligible)
                if eligible_count > anchor_last_eligible:
                    match = anchor_detector.match_in_frames(eligible, frames_now)
                    if match is not None:
                        store.save_offset(uri, match.offset_ms, match.match_q, source="anchor")
                        evaluator.add_anchor_vote(
                            int(match.offset_ms),
                            float(match.match_r) * max(1, eligible_count),
                        )
                        anchor_matched = True
                        anchor_done = True
                    elif eligible_count >= len(anchor_candidates):
                        anchor_done = True
                    anchor_last_eligible = eligible_count

        elif kind == "prog":
            if prog_active:
                t0 = time.perf_counter()
                if ladder is not None:
                    p_center, p_span = ladder.current.center_offset_ms, ladder.current.span_ms
                else:
                    p_center, p_span = 0, search_ms
                match = xcorr_core.progressive_match(
                    frames_now, stored_ts, stored_bands,
                    t_now_ms=ev_time, search_ms=p_span, center_offset_ms=p_center,
                )
                cpu_samples.append((time.perf_counter() - t0) * 1000.0)
                if match is not None:
                    # Engine-only (mirrors live): no disk write from progressive.
                    engine.apply_save(uri, match.offset_ms, match.quality,
                                      source="progressive")
                    evaluator.add_progressive_vote(match.offset_ms, match.r)
                    prog_matched = True
                    prog_active = False
                    if verbose:
                        print(f"  [prog @{ev_time:>6}] match {match.offset_ms:+d}ms "
                              f"r={match.r:.2f} Q={match.quality:.2f} span={match.span_ms}ms")

        elif kind == "monitor":
            if monitor_mode:
                t0 = time.perf_counter()
                mon_off = engine._shape_offset_ms
                mw_end = min(ev_time + mon_off, int(stored_ts[-1]))
                mw_start = mw_end - mon_cfg.span_ms
                rolling_r = None
                if mw_start >= 0:
                    # Difficulty + gap gate (mirrors live): flat spans and
                    # capture stalls are neutral (rolling_r stays None).
                    mw_bins = np.arange(mw_start, mw_end, xcorr_core.XCORR_BIN_MS, dtype=float)
                    mw_tpl = np.interp(mw_bins, stored_ts, stored_rms)
                    mw_gap = xcorr_core.max_frame_gap_ms(
                        frames_now, mw_start - mon_off, mw_end - mon_off)
                    if (xcorr_core.difficulty_score(mw_tpl, stored_rms) >= float(
                            getattr(settings, "xcorr_starting_threshold", 0.15))
                            and mw_gap <= settings.xcorr_window_max_gap_ms):
                        rolling_r = xcorr_core.eval_at_shift(
                            stored_ts, stored_bands, frames_now,
                            mw_start, mw_end, -mon_off,
                        )
                cpu_samples.append((time.perf_counter() - t0) * 1000.0)
                action = monitor.note_check(rolling_r, engine._play_best_quality)
                if action == "confirmed":
                    spike = xcorr_core.mismatch_spike(
                        stored_ts, stored_bands, frames_now,
                        engine_offset_ms=mon_off, t_now_ms=ev_time,
                        lookback_ms=mon_cfg.spike_lookback_ms,
                        halfwin_ms=mon_cfg.spike_halfwin_ms,
                    )
                    if ladder is not None:
                        if monitor.recoveries >= 2:
                            ladder.escalate_to_global()
                        else:
                            ladder.escalate()
                    evaluator.note_mismatch_confirmed(mon_cfg.accum_decay)
                    engine.demote_play_best(uri, mon_cfg.demote_q)
                    if spike is not None:
                        pending_dynamic = (spike[0], spike[1])
                        if verbose:
                            print(f"  [monitor @{ev_time:>6}] CONFIRMED r={rolling_r} "
                                  f"→ dynamic window [{spike[0]}-{spike[1]}] spike={spike[2]}")
                    window_queue = [(s, e) for s, e in all_planned if s > ev_time]
                    monitor_mode = False

        # ── Dispatch (every tick, mirrors the live per-frame checks) ──────────
        if pending_dynamic is not None:
            dws, dwe = pending_dynamic
            pending_dynamic = None
            locked = run_window(dws, dwe, frames_now)
            monitor.recovery_done()
            if locked:
                locked_via_stop = True
                if not monitor_enabled:
                    ended = True
                else:
                    monitor_mode = True
                    window_queue = []
            continue

        while (not monitor_mode and window_queue
               and ev_time >= window_queue[0][1] + _XCORR_MARGIN_MS):
            ws, we = window_queue.pop(0)
            prog_active = False   # first planned window reached — progressive done
            locked = run_window(ws, we, frames_now)
            if locked:
                locked_via_stop = True
                if not monitor_enabled:
                    ended = True
                else:
                    monitor_mode = True
                    window_queue = []
                break
        if ended:
            break
        if not window_queue and not monitor_mode:
            if not monitor_enabled:
                break
            monitor_mode = True

    # ── Finalize ──────────────────────────────────────────────────────────────
    if evaluator.n_measurements > 0:
        final = evaluator.finalize()
        if final.disk_save is not None:
            f_off, f_q, f_source, f_bypass = final.disk_save
            engine.now_ms = last_frame_ts
            store.save_offset(uri, f_off, f_q, source=f_source,
                              bypass_drift_cap=f_bypass)

    # ── Metrics ───────────────────────────────────────────────────────────────
    # "Stored" = what the NEXT play would load from the slot. Errors compare
    # against the END-of-play expected offset (step function for midshift).
    expected_final = expected_at(last_frame_ts)
    if store.save_log or store.history:
        final_stored = store.timestamp_offset_ms
    else:
        final_stored = None
    final_stored_err = (final_stored - expected_final) if final_stored is not None else None
    engine_err = engine._shape_offset_ms - expected_final

    # First correct engine lock that is never later displaced by a wrong one.
    t_lock: Optional[int] = None
    for i, ev in enumerate(engine.snap_log):
        if abs(ev.offset_ms - expected_at(ev.song_time_ms)) <= 100:
            if all(abs(later.offset_ms - expected_at(later.song_time_ms)) <= 100
                   for later in engine.snap_log[i + 1:]):
                t_lock = ev.song_time_ms
                break
    wrong_locks = sum(1 for ev in store.save_log
                      if abs(ev.offset_ms - expected_at(ev.song_time_ms)) > 300)

    # Engine-correct time fraction: integrate the engine-offset step function
    # against the expected step function over [0, last_frame_ts].
    correct_ms = 0
    points = [(0, engine._loaded_offset_ms)] + [
        (ev.song_time_ms, ev.offset_ms) for ev in engine.snap_log]
    boundaries = sorted({t for t, _ in points}
                        | ({int(scenario.offset_change_at_ms)}
                           if scenario.offset_change_at_ms else set())
                        | {0, last_frame_ts})
    for a, b in zip(boundaries, boundaries[1:]):
        if b <= a:
            continue
        off = next(o for t, o in reversed(points) if t <= a)
        if abs(off - expected_at(a)) <= 300:
            correct_ms += b - a
    engine_correct_pct = round(100.0 * correct_ms / max(1, last_frame_ts), 1)

    cpu_arr = np.array(cpu_samples) if cpu_samples else np.array([0.0])
    return PlayResult(
        stem=stem, scenario=scenario.name, expected_offset_ms=expected,
        final_stored_offset_ms=final_stored,
        final_stored_error_ms=final_stored_err,
        engine_final_offset_ms=engine._shape_offset_ms,
        engine_final_error_ms=engine_err,
        time_to_first_correct_lock_ms=t_lock,
        wrong_lock_events=wrong_locks,
        n_saves=len(store.save_log),
        anchor_matched=anchor_matched,
        progressive_matched=prog_matched,
        locked_via_stop=locked_via_stop,
        windows_evaluated=len(traces),
        windows_planned=len(windows),
        cpu_ms_total=round(float(cpu_arr.sum()), 1),
        cpu_ms_p50=round(float(np.percentile(cpu_arr, 50)), 1),
        cpu_ms_p95=round(float(np.percentile(cpu_arr, 95)), 1),
        engine_correct_time_pct=engine_correct_pct,
        monitor_recoveries=monitor.recoveries,
        traces=traces,
        store_snapshot=store.snapshot(),
    )
