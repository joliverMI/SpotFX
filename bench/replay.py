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
from services.xcorr_sweep import SweepConfig, SweepEvaluator
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
    seed: str = "cold"                       # cold | seeded_correct | seeded_wrong_2s
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
    traces: list[WindowTrace] = field(default_factory=list)

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
    if scenario.seed == "seeded_correct":
        seed_history, seed_q, coarse_locked = [expected] * 3, 0.8, True
    elif scenario.seed == "seeded_wrong_2s":
        seed_history, seed_q, coarse_locked = [expected + 2000] * 3, 0.8, True
    else:   # cold
        seed_history, seed_q, coarse_locked = [], 0.0, False

    engine = FakeEngine(uri, loaded_offset_ms=(seed_history[0] if seed_history else 0))
    store = FakeMetaStore(engine, seed_history=seed_history,
                          seed_quality=seed_q, coarse_locked=coarse_locked)
    seed_offset = store.median_offset() if store.history else 0
    if seed_offset is None:
        seed_offset = store.timestamp_offset_ms

    # Phase 3 flags (mirrors the live loop's gating)
    _accum_active = settings.xcorr_accum_enabled and settings.xcorr_fft_enabled
    search_ms = search_ms_for(meta, scenario)
    accumulator = None
    if _accum_active:
        from services.xcorr_evidence import EvidenceAccumulator
        accumulator = EvidenceAccumulator(max_offset_ms=search_ms + 5000)

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
    # Anchor crossings fire when frame time reaches a horizon; progressive
    # ticks every interval from start_ms; windows fire at win_end + margin.
    # Process strictly in time order, like the frame loop (anchor →
    # progressive → window within a tick).
    _prio = {"anchor": 0, "prog": 1, "window": 2}
    events: list[tuple[int, str, object]] = []
    for h in sorted(set(anchor_horizons)):
        events.append((h, "anchor", h))
    if settings.xcorr_progressive_enabled:
        t = int(settings.xcorr_progressive_start_ms)
        while t <= last_frame_ts:
            events.append((t, "prog", None))
            t += int(settings.xcorr_progressive_interval_ms)
    for (ws, we) in windows:
        events.append((we + _XCORR_MARGIN_MS, "window", (ws, we)))
    events.sort(key=lambda e: (e[0], _prio[e[1]]))

    anchor_done = not anchor_candidates
    anchor_matched = False
    anchor_last_eligible = 0
    prog_active = bool(settings.xcorr_progressive_enabled)
    prog_matched = False
    locked_via_stop = False
    traces: list[WindowTrace] = []
    cpu_samples: list[float] = []

    for ev_time, kind, payload in events:
        if ev_time > last_frame_ts:
            break   # capture would have ended before this event
        engine.now_ms = ev_time
        frames_now = [f for f in frames if f[0] <= ev_time]
        if not frames_now:
            continue

        if kind == "anchor":
            if anchor_done:
                continue
            eligible = [c for c, h in zip(anchor_candidates, anchor_horizons)
                        if ev_time >= h]
            eligible_count = len(eligible)
            if eligible_count <= anchor_last_eligible:
                continue
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
            continue

        if kind == "prog":
            if not prog_active:
                continue
            t0 = time.perf_counter()
            match = xcorr_core.progressive_match(
                frames_now, stored_ts, stored_bands,
                t_now_ms=ev_time, search_ms=search_ms,
            )
            cpu_samples.append((time.perf_counter() - t0) * 1000.0)
            if match is not None:
                store.save_offset(uri, match.offset_ms, match.quality,
                                  source="progressive")
                evaluator.add_progressive_vote(match.offset_ms, match.r)
                prog_matched = True
                prog_active = False
                if verbose:
                    print(f"  [prog @{ev_time:>6}] match {match.offset_ms:+d}ms "
                          f"r={match.r:.2f} Q={match.quality:.2f} span={match.span_ms}ms")
            continue

        # ── Window event ──────────────────────────────────────────────────────
        win_start, win_end = payload
        prog_active = False   # first planned window reached — progressive done
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
        if _accum_active:
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
        )

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
            t = traces[-1]
            print(f"  [{win_start:>6}-{win_end:>6}] diff={t.difficulty:.2f} "
                  f"OLD r={t.old_r:+.2f}@{stored_offset_ms:+d}  "
                  f"NEW {('%+d' % t.new_offset_ms) if t.new_offset_ms is not None else '--'}ms "
                  f"r={t.new_r if t.new_r is not None else 0:.2f}  "
                  f"winner={t.winner}{' ★' if t.is_global_best else ''} "
                  f"({t.cpu_ms:.1f}ms)")

        if evaluator.lock_and_stop(engine._play_best_quality):
            locked_via_stop = True
            break

    # ── Finalize ──────────────────────────────────────────────────────────────
    if evaluator.n_measurements > 0:
        final = evaluator.finalize()
        if final.disk_save is not None:
            f_off, f_q, f_source, f_bypass = final.disk_save
            engine.now_ms = last_frame_ts
            store.save_offset(uri, f_off, f_q, source=f_source,
                              bypass_drift_cap=f_bypass)

    # ── Metrics ───────────────────────────────────────────────────────────────
    final_stored = store.save_log[-1].offset_ms if store.save_log else None
    final_stored_err = (final_stored - expected) if final_stored is not None else None
    engine_err = engine._shape_offset_ms - expected

    # First correct engine lock that is never later displaced by a wrong one.
    t_lock: Optional[int] = None
    for i, ev in enumerate(engine.snap_log):
        if abs(ev.offset_ms - expected) <= 100:
            if all(abs(later.offset_ms - expected) <= 100
                   for later in engine.snap_log[i + 1:]):
                t_lock = ev.song_time_ms
                break
    wrong_locks = sum(1 for ev in store.save_log
                      if abs(ev.offset_ms - expected) > 300)

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
        traces=traces,
    )
