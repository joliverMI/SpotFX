"""
SpotFX — Auto-offset detection service.

Cross-correlates smart windows of the stored audio shape against live audio using
multi-band Pearson correlation (rms_total, rms_low, rms_high) to measure timing
drift and keep triggers in sync regardless of Spotify poll delay or session gaps.

Sign convention (matches trigger_engine._effective_offset_ms):
  effective_now = now_ms + (ledfx_buffer + rtt + timestamp_offset_ms)
  fires when trigger.timestamp_ms <= effective_now
  → positive offset fires EARLIER, negative fires LATER

  live is LATE by X ms  →  best_shift = +X  →  offset_ms = -X  →  fires later  ✓

Quality scoring:
  At each window we evaluate TWO candidates:
    NEW  — free-search xcorr finds the best-fitting shift for this window
    OLD  — xcorr evaluated at the currently-stored offset (how well does it still fit?)
  Each candidate gets a quality score:  Q = Pearson_r × difficulty
  The winner (higher Q) is tracked globally; whenever global best improves the
  offset (and its quality score) is saved.

  Difficulty = coefficient of variation of the stored window RMS, normalised by
  the song-global CV.  A flat/silent window → 0, a highly dynamic window → 1.
  This prevents a coincidental high-r match on a boring, low-signal passage from
  displacing a reliable measurement from a dynamic, transient-rich window.
"""
from __future__ import annotations
import asyncio
import csv                                      # DIAGNOSTIC CSV
import hashlib
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path                         # DIAGNOSTIC CSV
from typing import Optional

import numpy as np

from config import settings, AUDIO_SHAPES_DIR
from models.state import SpotifyTrackInfo, state as app_state
from api.audio_capture import AudioCaptureStream
from services.audio_analyzer import load_audio_shape_meta
# Math kernel extracted to services/xcorr_core.py so the offline bench harness
# can drive the exact production math. Aliased to the historical private names
# so the rest of this module reads unchanged.
from services.xcorr_core import (
    XCORR_BIN_MS as _XCORR_BIN_MS,
    XcorrDetail as _XcorrDetail,
    agc_normalize as _agc_normalize,
    signed_square as _signed_square,
    difficulty_score as _difficulty_score,
    eval_at_shift as _eval_at_shift,
    xcorr_window as _xcorr_window,
    xcorr_window_detail as _xcorr_window_detail,
    xcorr_window_fft as _xcorr_window_fft,
    xcorr_window_fft_full as _xcorr_window_fft_full,
    progressive_match as _progressive_match,
    mismatch_spike as _mismatch_spike,
)
from services.xcorr_sweep import (
    MismatchMonitor, MonitorConfig, SearchLadder, SweepConfig, SweepEvaluator,
)
from services.xcorr_evidence import EvidenceAccumulator

logger = logging.getLogger(__name__)

# ── Cross-correlation alignment ────────────────────────────────────────────────
_XCORR_FIRST_START_MS = 8_000    # first window starts at 8s — earlier sections
                                  # frequently misalign with stored shapes due to
                                  # mix variance / capture-time intro differences,
                                  # so both calibrators avoid the first 8s now.
_XCORR_END_BUFFER_MS  = 30_000   # stop 30s before song end
_XCORR_MARGIN_MS      = 1_000    # wait this far past window_end before computing
_XCORR_CANDIDATE_STEP = 500     # step size for candidate window positions (ms)
_OFFSET_HISTORY_CAP   = 5       # rolling window of saved offsets per (track, Set List)
_SETLIST_DELTA_CAP    = 10      # rolling deltas per Set List for cross-track bias hint
_PRE_FLIGHT_INTRO_MS  = 8_000   # how much of the intro we sample for the pre-flight scan
_PRE_FLIGHT_MIN_R     = 0.55    # acceptance threshold for pre-flight displacement


def _median_offset(history: list[dict]) -> int | None:
    """Median of `offset_ms` over a saved-offset history list. Returns None
    if the history is empty. Used to start each play from a stable baseline
    instead of the (potentially noisy) most recent save.
    """
    vals = sorted(int(h.get("offset_ms", 0)) for h in (history or []) if h)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) // 2


def _bump_anti_corr_count(uri: str, setlist_id: str, is_drifting: bool) -> None:
    """Track consecutive plays where the stored offset for (uri, setlist_id)
    was anti-correlated. Resets when the play looks normal. Persisted on
    AudioShapeMeta.setlist_offsets so the Set List page can surface drifting
    songs without keeping a separate index.
    """
    meta = load_audio_shape_meta(uri)
    if meta is None:
        return
    if not isinstance(meta.setlist_offsets, dict):
        meta.setlist_offsets = {}
    entry = meta.setlist_offsets.get(setlist_id) or {}
    if is_drifting:
        entry["anti_corr_count"] = int(entry.get("anti_corr_count", 0)) + 1
        entry["last_anti_corr_at"] = datetime.now(timezone.utc).isoformat()
        # Round 7: when the loaded baseline has been anti-correlated for
        # ≥3 consecutive plays, demote the slot back to coarse-unlocked so
        # the next play uses anchor as a cold-start safety net.
        if entry["anti_corr_count"] >= 3 and entry.get("coarse_locked", False):
            entry["coarse_locked"] = False
            logger.info(
                "Anti-corr streak ≥3 for %s slot %s — demoted coarse_locked → False (anchor will run next play)",
                uri, setlist_id,
            )
    else:
        if int(entry.get("anti_corr_count", 0)) > 0:
            entry["anti_corr_count"] = 0
    meta.setlist_offsets[setlist_id] = entry
    meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def _record_setlist_delta(setlist_id: str, delta_ms: int) -> None:
    """Append a (latest_lock − prior_median) sample to the Set List's
    recent_offset_deltas FIFO. Used as a starting bias for tracks the Set
    List hasn't seen before."""
    from services import setlist_store
    sl = setlist_store.get_by_id(setlist_id)
    if sl is None:
        return
    deltas = list(sl.recent_offset_deltas or [])
    deltas.insert(0, int(delta_ms))
    sl.recent_offset_deltas = deltas[:_SETLIST_DELTA_CAP]
    setlist_store.save(sl)


def _xcorr_search_ms(captured_duration_ms: int) -> int:
    """Per-side xcorr search range, in ms. Mix-aware:
        base + max(0, captured - polled) + buffer (per-Set-List or global).
    """
    polled = app_state.current_track.duration_ms if app_state.current_track else 0
    cut_ms = max(0, int(captured_duration_ms or 0) - int(polled or 0))
    buffer_ms = settings.xcorr_cut_buffer_ms
    try:
        from services import setlist_store
        sl = setlist_store.get_by_context_uri(
            app_state.current_track.context_uri if app_state.current_track else ""
        )
        if sl and sl.xcorr_cut_buffer_ms is not None:
            buffer_ms = int(sl.xcorr_cut_buffer_ms)
    except Exception:
        pass
    return int(settings.xcorr_search_ms_base + cut_ms + buffer_ms)


# DIAGNOSTIC CSV ──────────────────────────────────────────────────────────────
# v2: per-band detail now covers all 4 bands (the v1 writer had a band-index
# bug that put the MID band in the *_high columns and omitted high entirely).
# New schema → new file so the old header doesn't mis-align appended rows.
_CSV_PATH = Path(__file__).resolve().parent.parent / "storage" / "xcorr_diagnostic_v2.csv"
_CSV_MAX_WINDOWS = 15
_CSV_SONG_COLS = [
    "song", "timestamp", "uri", "duration_ms",
    "final_offset_ms", "final_quality", "n_windows", "prev_offset_ms",
    "play_type",  # DIAGNOSTIC CSV — natural/skip/first
]

def _csv_window_cols(n: int) -> list[str]:
    """Return column names for window slot n (1-based)."""
    p = f"w{n}_"
    return [
        p + "start_ms", p + "difficulty", p + "winner",
        p + "offset_ms", p + "quality", p + "r_avg",
        p + "r_total", p + "r_low", p + "r_mid", p + "r_high",
        p + "peak_total", p + "peak_low", p + "peak_mid", p + "peak_high",
        p + "old_r_avg",
    ]

_CSV_ALL_COLS = _CSV_SONG_COLS + [
    col for n in range(1, _CSV_MAX_WINDOWS + 1) for col in _csv_window_cols(n)
]
# END DIAGNOSTIC CSV ──────────────────────────────────────────────────────────


class AutoOffsetService:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._watching_uri: Optional[str] = None
        # Skip detection: previous track's state when it ended/was interrupted
        self._prev_track_end: Optional[tuple[str, int, int]] = None  # (uri, progress_ms, duration_ms)
        self._last_track_snapshot: Optional[tuple[str, int, int]] = None  # snapshot from previous poll
        # Snapshot of recent xcorr capture frames (URI + timestamps + bands).
        # Updated once per window iteration in _detect_loop_xcorr so the
        # /api/debug/xcorr-frames endpoint can return what the matcher is
        # currently working with without locking the live frames list.
        self._frames_snapshot_uri: Optional[str] = None
        self._frames_snapshot: list[tuple[int, float, float, float, float]] = []

    def get_status(self, uri: str) -> dict:
        """Return whether xcorr calibration is currently active for a URI."""
        return {"active": self._watching_uri == uri}

    def get_live_frames(self, uri: str) -> dict:
        """Return the most recent xcorr-captured frames for a URI in shape-data
        format, or empty arrays if no xcorr is running for this URI. Used by
        the Debug page to render a live overlay against the saved shape."""
        if self._frames_snapshot_uri != uri or not self._frames_snapshot:
            return {
                "timestamps_ms": [],
                "rms_total":     [],
                "rms_low":       [],
                "rms_mid":       [],
                "rms_high":      [],
            }
        snap = self._frames_snapshot
        return {
            "timestamps_ms": [int(f[0]) for f in snap],
            "rms_total":     [float(f[1]) for f in snap],
            "rms_low":       [float(f[2]) for f in snap],
            "rms_mid":       [float(f[3]) for f in snap],
            "rms_high":      [float(f[4]) for f in snap],
        }

    def _classify_play_type(self) -> str:
        """Classify how the current song started: 'natural', 'skip', or 'first'."""
        if self._prev_track_end is None:
            return "first"
        _prev_uri, prev_progress, prev_duration = self._prev_track_end
        # Natural: previous song played to within 5s of its end
        if prev_progress >= prev_duration - 5000:
            return "natural"
        return "skip"

    async def on_track_change(self, track: Optional[SpotifyTrackInfo]) -> None:
        """Called from audio_shape_service.on_track_change on every Spotify poll."""
        new_uri = track.spotify_uri if track else None

        # Detect track change using the snapshot URI (independent of _watching_uri,
        # which may already be None if xcorr finished early)
        prev_snapshot_uri = self._last_track_snapshot[0] if self._last_track_snapshot else None
        if prev_snapshot_uri and prev_snapshot_uri != new_uri:
            # Different song
            self._prev_track_end = self._last_track_snapshot
        elif (self._last_track_snapshot and track and track.is_playing
              and prev_snapshot_uri == new_uri):
            # Same URI — check for progress reset (repeat/restart)
            _prev_progress = self._last_track_snapshot[1]
            _cur_progress = track.interpolated_progress_ms()
            if _prev_progress > _cur_progress + 5000:
                # Progress jumped backwards by >5s → song restarted
                self._prev_track_end = self._last_track_snapshot
                await self._stop()  # cancel stale xcorr, allow fresh restart
            elif _cur_progress > _prev_progress + 15000:
                # Progress jumped forward by >15s → user skipped ahead
                await self._stop()

        # Cancel any existing detection if song changed or stopped
        if self._watching_uri and self._watching_uri != new_uri:
            await self._stop()

        # Snapshot current track for skip detection on the NEXT track change.
        # Must run on every poll so _last_track_snapshot is fresh when a change happens.
        if track and track.is_playing:
            self._last_track_snapshot = (track.spotify_uri, track.interpolated_progress_ms(), track.duration_ms)
        else:
            self._last_track_snapshot = None

        if not track or not track.is_playing or not app_state.on_target_device:
            return

        # If ANY capture is in progress, stop a running xcorr — the recorder
        # competes with xcorr for event-loop time and PulseAudio frames. Don't
        # restrict to URI match: a capture for song A still starves the xcorr
        # loop matching song B that's currently playing.
        try:
            from services.audio_shape_service import audio_shape_service as _ass
            if self._watching_uri and _ass._recording_uri:
                logger.info(
                    "Auto-offset xcorr: stopping (was watching %s) — capture in progress for %s",
                    self._watching_uri, _ass._recording_uri,
                )
                await self._stop()
        except Exception:
            pass

        # Already watching this song
        if self._watching_uri == new_uri:
            return

        # Run for any song with a complete shape (including auto_verified).
        # user_verified: still run for logging; _detect_loop_xcorr won't save.
        meta = load_audio_shape_meta(new_uri)
        if meta is None or not meta.capture_complete:
            return

        # Skip xcorr while ANY capture is in progress. xcorr opens its own
        # AudioCaptureStream and runs numpy work per window — competing with
        # the active capture for event-loop time and PulseAudio frames. The
        # observed failure mode: queue-full frame drops in the recorder ->
        # capture-gap > 200ms -> shape discarded (`Audio shape discarded —
        # gap of 2869ms detected (limit 200ms)`). Re-enabling xcorr after
        # capture finishes is automatic — `_recording_uri` clears when the
        # recorder stops, and the next track-change poll sets things up.
        try:
            from services.audio_shape_service import audio_shape_service
            if audio_shape_service._recording_uri:
                logger.info(
                    "Auto-offset xcorr: deferred for %s — capture in progress (recording=%s)",
                    new_uri, audio_shape_service._recording_uri,
                )
                return
        except Exception:
            # Defensive: if the import fails for any reason, fall through to
            # normal xcorr behavior rather than silently breaking the sweep.
            pass

        # Per-Set-List opt-out: when the active Set List has xcorr_enabled=False
        # (typically a non-mixed playlist), skip the per-play sweep entirely so
        # the user's previously-tuned stored offset is used as-is.
        if app_state.active_setlist_id and not app_state.active_setlist_xcorr_enabled:
            logger.info(
                "Auto-offset xcorr: skipped for %s — Set List has xcorr disabled",
                new_uri,
            )
            self._watching_uri = new_uri  # prevent re-checking every poll
            return

        current_pos_ms = track.interpolated_progress_ms()

        # Get smart windows (cached or freshly computed)
        all_windows = self._get_or_compute_windows(new_uri, meta)
        # Build difficulty lookup from cached window data
        diff_lookup = {(w["start_ms"], w["end_ms"]): w.get("difficulty", 0)
                       for w in (meta.xcorr_windows or [])}
        # Filter to only windows we can still reach
        windows = [(s, e) for s, e in all_windows if current_pos_ms < s]

        # Pre-flight scan: when the first reachable window starts well after
        # _PRE_FLIGHT_INTRO_MS and we're still near the song start, inject
        # a short [0, _PRE_FLIGHT_INTRO_MS] window at the front so the lock
        # has a chance to land before the planned schedule does. Saves the
        # song from playing 10–30s under a stale baseline.
        first_planned = windows[0][0] if windows else None
        if (not settings.xcorr_progressive_enabled   # progressive replaces pre-flight
                and current_pos_ms < 1500
                and first_planned is not None
                and first_planned >= _PRE_FLIGHT_INTRO_MS
                and (not all_windows or all_windows[0][0] != 0)):
            windows.insert(0, (0, _PRE_FLIGHT_INTRO_MS))
            logger.info(
                "Auto-offset xcorr: pre-flight window [0–%d]ms prepended for %s",
                _PRE_FLIGHT_INTRO_MS, new_uri,
            )

        if not windows:
            logger.info(
                "Auto-offset xcorr: no reachable windows for %s — %s (pos=%dms, dur=%dms)",
                track.artist, track.title, int(current_pos_ms), track.duration_ms,
            )
            self._watching_uri = new_uri  # prevent re-checking every poll
            return

        play_type = self._classify_play_type()
        logger.info(
            "Auto-offset xcorr: starting for %s — %s; %d windows (%d planned), play_type=%s",
            track.artist, track.title, len(windows), len(all_windows), play_type,
        )
        try:
            from services.websocket_manager import ws_manager
            asyncio.create_task(ws_manager.broadcast({
                "type": "xcorr_start",
                "uri": new_uri,
                "windows": [[s, e, round(diff_lookup.get((s, e), 0), 3)] for s, e in windows],
                "verification": meta.offset_verification,
                "stored_quality": meta.offset_quality,
                "play_type": play_type,
            }))
        except Exception:
            pass
        self._watching_uri = new_uri
        self._task = asyncio.create_task(
            self._detect_loop_xcorr(new_uri, windows, meta.offset_verification, play_type),
            name="auto-offset-xcorr",
        )

    async def _stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._watching_uri = None

    def _get_or_compute_windows(
        self,
        uri: str,
        meta,
    ) -> list[tuple[int, int]]:
        """Return xcorr windows, using cache if valid or computing fresh.

        Round 7+: prefers the U-Score planner (services.uscore_planner) when
        librosa data is available. Falls back to the legacy difficulty/uniqueness
        planner when no beats are present (rare — songs without librosa shouldn't
        normally reach the sweep, but the fallback keeps things working).
        """
        npz_path = AUDIO_SHAPES_DIR / meta.npz_file

        # Current planner version. Any other stored hash (older U-Score versions
        # or the legacy hex-style hash from the difficulty/uniqueness planner)
        # triggers a fresh re-plan so songs picked up before round 10 still
        # benefit from the new bands without an explicit backfill run.
        _current_uscore_hash = "uscore-v8"

        # Cache hit: stored windows match the current params version.
        if (meta.xcorr_windows and meta.xcorr_params_hash
                and meta.xcorr_params_hash == _current_uscore_hash):
            windows = [(w["start_ms"], w["end_ms"]) for w in meta.xcorr_windows]
            logger.info(
                "Auto-offset xcorr: using %d cached windows for %s (hash=%s)",
                len(windows), uri, meta.xcorr_params_hash,
            )
            return windows
        if meta.xcorr_windows and meta.xcorr_params_hash:
            logger.info(
                "Auto-offset xcorr: cache invalidated for %s — stored hash=%s, current=%s; re-planning",
                uri, meta.xcorr_params_hash, _current_uscore_hash,
            )

        # Fresh compute path. Load all 4 bands + librosa beats; route to the
        # U-Score planner when beats exist, fall back to the legacy planner.
        try:
            data = np.load(npz_path)
            stored_ts = data["timestamps_ms"].astype(float)
        except Exception as exc:
            logger.warning("Auto-offset xcorr: failed to load npz for window planning: %s", exc)
            return []

        planned: list[dict] = []
        params_hash = ""
        beats_ms: list[int] = []
        try:
            from services import librosa_service
            analysis = librosa_service.get_analysis(meta)
            if analysis and analysis.beats:
                beats_ms = [int(b.ms) for b in analysis.beats]
        except Exception:
            beats_ms = []

        if beats_ms:
            try:
                from services import uscore_planner
                bands_dict = {
                    "rms_total": data["rms_total"],
                    "rms_low":   data["rms_low"],
                    "rms_mid":   data["rms_mid"],
                    "rms_high":  data["rms_high"],
                }
                planned = uscore_planner.plan_uscore_windows(
                    stored_ts, bands_dict, meta.duration_ms, beats_ms,
                )
                params_hash = "uscore-v8"
            except Exception as exc:
                logger.warning("Auto-offset xcorr: U-Score planner failed for %s: %s", uri, exc)
                planned = []

        if not planned:
            # Fallback: legacy planner using rms_low only (no librosa needed).
            try:
                npz_mtime = os.path.getmtime(npz_path)
            except OSError:
                npz_mtime = 0
            stored_rms = data["rms_low"]
            planned = _plan_xcorr_windows(stored_ts, stored_rms, meta.duration_ms)
            params_hash = _compute_params_hash(npz_mtime)

        windows = [(w["start_ms"], w["end_ms"]) for w in planned]

        # Save to sidecar
        meta.xcorr_windows = planned
        meta.xcorr_params_hash = params_hash
        meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
        try:
            meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
            logger.info(
                "Auto-offset xcorr: planned %d windows via %s (saved to sidecar) for %s",
                len(planned), params_hash or "legacy", uri,
            )
        except Exception as exc:
            logger.warning("Auto-offset xcorr: failed to save window cache: %s", exc)

        return windows

    async def _detect_loop_xcorr(
        self,
        uri: str,
        windows: list[tuple[int, int]],
        verification: str,
        play_type: str = "first",
    ) -> None:
        """
        Capture audio continuously and compute cross-correlation at each checkpoint.

        At each window we evaluate two candidates:
          NEW  — free-search xcorr (finds optimal shift for this window)
          OLD  — xcorr at the currently-stored offset (how well does it still fit?)

        Quality score Q = Pearson_r × difficulty (0–1).
        Whenever the global best Q improves we apply (and save) the winning offset.
        Does NOT overwrite user_verified offsets — logs the result instead.
        """
        import time
        track = app_state.current_track
        if not track:
            return

        # ── Song-start stabilization ──────────────────────────────────────
        # Collect 3 song_start estimates ~500ms apart and use the median.
        # This reduces jitter from stale Spotify polls, especially after skips.
        estimates = []
        for _ in range(3):
            await asyncio.sleep(0.5)
            t = app_state.current_track
            if not t or t.spotify_uri != uri or not t.is_playing:
                return  # song changed or stopped during stabilization
            estimates.append(t.fetched_at - t.progress_ms / 1000.0)

        song_start = sorted(estimates)[1]  # median of 3
        spread_ms = (max(estimates) - min(estimates)) * 1000
        logger.info(
            "Auto-offset xcorr: song_start stabilized (spread=%.0fms, %d samples, play_type=%s) for %s",
            spread_ms, len(estimates), play_type, uri,
        )

        capture = AudioCaptureStream(song_start)
        # NOTE: capture.start() is deferred to just before the frame loop so
        # an exception anywhere in the setup below can't leak an open
        # PulseAudio stream (observed: a setup NameError left the stream
        # running → core dump at the next track change).

        # Load stored shape once
        meta = load_audio_shape_meta(uri)
        if not meta:
            capture.stop()
            return
        try:
            data = np.load(AUDIO_SHAPES_DIR / meta.npz_file)
            stored_ts  = data["timestamps_ms"].astype(float)
            # Prefer the pre-squared bands cached at capture time. Legacy
            # shapes (saved before the cache landed) are recomputed live;
            # the math is identical (`x · |x|`).
            def _band(name: str) -> np.ndarray:
                sq_key = f"{name}_sq"
                if sq_key in data.files:
                    return np.asarray(data[sq_key], dtype=float)
                return _signed_square(np.asarray(data[name], dtype=float))
            stored_bands = [
                _band("rms_total"),
                _band("rms_low"),
                _band("rms_mid"),
                _band("rms_high"),
            ]
            stored_rms = stored_bands[1]  # kept for difficulty scoring (squared rms_low)
        except Exception as exc:
            logger.warning("Auto-offset xcorr: failed to load npz for %s: %s", uri, exc)
            capture.stop()
            return

        # Round 9.5: envelope lookup. For each cached window, the planner
        # stored (safe_neg_ms, safe_pos_ms) — the safe-shift range relative
        # to the window's expected match position. At runtime we clip the
        # NEW measurement to engine_current ± envelope so a window can't
        # report a measurement that lies in twin territory. Missing entries
        # (legacy shapes that pre-date round 9.5) get a wide-open envelope
        # so the clip is a no-op for them.
        envelope_lookup: dict[tuple[int, int], tuple[int, int]] = {}
        for w in (meta.xcorr_windows or []):
            try:
                key = (int(w["start_ms"]), int(w["end_ms"]))
                envelope_lookup[key] = (
                    int(w.get("safe_neg_ms", -10**9)),
                    int(w.get("safe_pos_ms",  10**9)),
                )
            except (KeyError, TypeError, ValueError):
                continue

        # Librosa tempo (if analysed) — feeds the per-window beat-twin
        # rejection in _xcorr_window. Same source as the anchor detector.
        tempo_bpm: Optional[float] = None
        try:
            from services import librosa_service
            _analysis = librosa_service.get_analysis(meta)
            if _analysis is not None:
                tempo_bpm = float(_analysis.tempo_bpm) if _analysis.tempo_bpm else None
        except Exception:
            tempo_bpm = None

        # Mix-aware diagnostics: log the search range and which slot we're using.
        polled_dur = app_state.current_track.duration_ms if app_state.current_track else 0
        cut_ms = max(0, int(meta.duration_ms or 0) - int(polled_dur or 0))
        search_ms = _xcorr_search_ms(int(meta.duration_ms or 0))
        sl_id = app_state.active_setlist_id
        offset_source = f"setlist:{sl_id}" if sl_id else "default"
        sl_name = ""
        if sl_id:
            try:
                from services import setlist_store
                sl_obj = setlist_store.get_by_id(sl_id)
                sl_name = sl_obj.name if sl_obj else ""
            except Exception:
                pass
        logger.info(
            "xcorr search range = ±%dms (cut=%dms, buffer=%dms, source=%s, setlist=%s)",
            search_ms, cut_ms, settings.xcorr_cut_buffer_ms, offset_source, sl_name or "-",
        )

        # Each frame: (timestamp_ms, rms_total, rms_low, rms_high) — 3 bands for multi-band xcorr
        frames: list[tuple[int, float, float, float, float]] = []
        _csv_window_rows: list[dict] = []   # DIAGNOSTIC CSV
        # Seed offset: the stored offset for this slot, so the post-loop save
        # defaults to "no change" if nothing convincingly displaces it. (The
        # evaluator's best_quality starts at -1.0 — not seeded, otherwise
        # legitimate corrections at lower Q than the historical lock could
        # never displace.)
        _seed_meta = load_audio_shape_meta(uri)
        _slot_history_len = 0
        _slot_quality = 0.0
        _slot_cut_in: Optional[int] = None
        if _seed_meta is not None and app_state.active_setlist_id:
            _seed_entry = (_seed_meta.setlist_offsets or {}).get(app_state.active_setlist_id) or {}
            _seed_med = _median_offset(_seed_entry.get("history") or [])
            seed_offset = _seed_med if _seed_med is not None else int(_seed_entry.get("timestamp_offset_ms", 0))
            _slot_history_len = len(_seed_entry.get("history") or [])
            _slot_quality = float(_seed_entry.get("offset_quality", 0.0))
            if _seed_entry.get("observed_cut_in_ms") is not None:
                _slot_cut_in = int(_seed_entry["observed_cut_in_ms"])
        else:
            seed_offset = int(_seed_meta.timestamp_offset_ms or 0) if _seed_meta else 0
            _slot_history_len = len(_seed_meta.offset_history or []) if _seed_meta else 0
            _slot_quality = float(_seed_meta.offset_quality or 0.0) if _seed_meta else 0.0

        # Phase 4: search center from history. Priority: slot history median →
        # observed cut-in point → Set-List cross-track bias (first play of a
        # track in a blended Set List) → None (cold → start at the wide stage).
        history_center: Optional[int] = None
        _prior_weight_scale = 1.0
        if _slot_history_len > 0:
            history_center = int(seed_offset)
        elif _slot_cut_in is not None:
            history_center = _slot_cut_in
        elif (app_state.active_setlist_id
              and getattr(settings, "xcorr_setlist_bias_enabled", True)):
            try:
                from services import setlist_store
                _sl = setlist_store.get_by_id(app_state.active_setlist_id)
                _deltas = sorted(int(d) for d in (_sl.recent_offset_deltas or [])) if _sl else []
                if _deltas:
                    history_center = _deltas[len(_deltas) // 2]
                    _prior_weight_scale = 0.5   # cross-track hint, half trust
                    logger.info(
                        "Auto-offset xcorr: Set-List bias center %+dms from %d cross-track deltas for %s",
                        history_center, len(_deltas), uri,
                    )
            except Exception:
                pass
        window_queue = list(windows)
        # All per-window gate decisions (winner pick, confirmation clusters,
        # anti-corr streak, engine-snap stickiness, save gates, lock-and-stop)
        # live in the SweepEvaluator state machine — shared verbatim with the
        # offline bench harness. This loop performs the side effects.
        # Phase 3: evidence accumulation needs the FFT path's landscapes.
        _accum_active = settings.xcorr_accum_enabled and settings.xcorr_fft_enabled
        # Phase 4: search escalation ladder (narrow → wide → global).
        _ladder = None
        if settings.xcorr_search_ladder_enabled and settings.xcorr_fft_enabled:
            _ladder = SearchLadder(
                history_center_ms=history_center,
                wide_span_ms=search_ms,
                narrow_span_ms=int(settings.xcorr_search_narrow_ms),
                global_span_ms=int(settings.xcorr_search_global_ms),
                duration_ms=int(meta.duration_ms or 0),
                escalate_after=int(settings.xcorr_ladder_escalate_after),
            )
            logger.info(
                "Auto-offset xcorr: search ladder %s (start=%s center=%+dms ±%dms) for %s",
                "/".join(s.name for s in _ladder.stages),
                _ladder.current.name, _ladder.current.center_offset_ms,
                _ladder.current.span_ms, uri,
            )
        _accum_span = (max(search_ms, int(settings.xcorr_search_global_ms))
                       if _ladder else search_ms)
        accumulator = (
            EvidenceAccumulator(max_offset_ms=_accum_span + 5000)
            if _accum_active else None
        )
        # Phase 4: soft history prior — bounded mass at the historical offset
        # so it can tip twin ties but never out-vote fresh evidence.
        if accumulator is not None and history_center is not None:
            if _slot_history_len > 0:
                _w_hist = min(1.0, _slot_history_len / 3.0) * max(0.0, _slot_quality)
            else:
                _w_hist = 0.5   # cut-in / Set-List bias center: modest fixed trust
            _prior_mass = (float(settings.xcorr_prior_bonus_mass)
                           * _w_hist * _prior_weight_scale)
            if _prior_mass > 0:
                accumulator.add_gaussian(
                    history_center, _prior_mass,
                    sigma_ms=float(settings.xcorr_prior_sigma_ms),
                    count_support=False,
                )
        evaluator = SweepEvaluator(
            SweepConfig.from_settings(settings),
            uri=uri,
            verification=verification,
            play_type=play_type,
            seed_offset_ms=seed_offset,
            envelope_lookup=envelope_lookup,
            accumulator=accumulator,
        )
        # Set by the lock-and-stop early exit. When True, the post-loop
        # cleanup leaves `_watching_uri` set so on_track_change's "already
        # watching this URI" guard prevents a fresh xcorr task from spawning
        # for the rest of this play. Cleared on the next URI change.
        _locked_via_stop = False

        # Early-feature anchor match: consumes the first N seconds of frames
        # and snap-aligns before the per-window sweep starts evaluating.
        # Progressive: each candidate has its own horizon (timestamp + search
        # radius + template radius). As frame time crosses a new horizon, try
        # matching against ALL eligible candidates so far (in uniqueness order
        # so the best ones are tried first). The earliest unique candidate
        # that locks fires the snap — saves wall-clock when an early candidate
        # is the right one, and only waits for the latest candidate when
        # earlier ones don't confidently match.
        # Round 7: per-slot cold-start anchor gate. Anchor only runs when both
        # the global flag is enabled AND the active Set List slot is *not*
        # coarse-locked — i.e., we don't yet have a confirmed save for this
        # slot, OR the loaded baseline has gone anti-correlated for ≥3 plays
        # (anti_corr_count ≥ 3 demotes coarse_locked back to False).
        # When coarse-locked, the smart-window sweep handles calibration by
        # itself; the rise-detector's redundant work is skipped.
        from services import anchor_detector
        slot_coarse_locked = False
        try:
            sl_id = app_state.active_setlist_id
            if sl_id and meta.setlist_offsets:
                _slot = meta.setlist_offsets.get(sl_id) or {}
                slot_coarse_locked = bool(_slot.get("coarse_locked", False))
        except Exception:
            slot_coarse_locked = False

        anchor_should_run = settings.anchor_enabled and not slot_coarse_locked
        if anchor_should_run:
            anchor_candidates: list[anchor_detector.AnchorCandidate] = [
                anchor_detector.AnchorCandidate.from_dict(d)
                for d in (meta.anchor_candidates or [])
            ]
            if not anchor_candidates:
                logger.info(
                    "Anchor: cold-start path active for %s but no candidates stored — sweep-only this play",
                    uri,
                )
            else:
                logger.info(
                    "Anchor: cold-start path active for %s (slot.coarse_locked=False, %d candidates available)",
                    uri, len(anchor_candidates),
                )
        else:
            anchor_candidates = []
        anchor_done = False
        _anchor_radius = int(settings.anchor_search_radius_ms) + int(settings.anchor_template_radius_ms)
        anchor_horizons: list[int] = [c.timestamp_ms + _anchor_radius for c in anchor_candidates]
        anchor_last_eligible = 0
        _last_snap_ms = 0
        # Phase 3: progressive early matching — slide the whole captured take
        # across the stored shape every interval until first lock or the
        # first planned window completes. Replaces the pre-flight window.
        _prog_active = bool(settings.xcorr_progressive_enabled)
        _prog_next_ms = int(settings.xcorr_progressive_start_ms)

        # Phase 5: the per-window evaluation, callable for both planned and
        # dynamically scheduled (mismatch-spike) windows. Returns True when
        # lock-and-stop fired. Body moved verbatim from the loop (closure
        # over frames/stored_*/evaluator/_ladder/...).
        async def _run_window(win_start: int, win_end: int) -> bool:
            # ── Compute difficulty for this window ────────────────────────
            bins = np.arange(win_start, win_end, _XCORR_BIN_MS, dtype=float)
            window_template = np.interp(bins, stored_ts, stored_rms)
            difficulty = _difficulty_score(window_template, stored_rms)

            # ── OLD candidate: evaluate the engine's CURRENT live offset ──
            # Test r at whatever the trigger engine is actually using to fire
            # triggers right now. The disk-stored median is also computed so
            # downstream gating + diagnostic quality fields stay populated, but
            # the OLD test point itself is the engine's runtime offset.
            #
            # Why: when the engine loaded a stale median at song start (file
            # updated since by another play), testing OLD at the disk median
            # hides the engine staleness — every window says "OLD looks fine"
            # while triggers fire at the wrong offset. Testing at the engine's
            # actual offset surfaces the gap (low OLD r → NEW wins → apply_save
            # corrects the engine).
            cur_meta = load_audio_shape_meta(uri)
            stored_offset_ms_disk = cur_meta.timestamp_offset_ms if cur_meta else 0
            stored_quality_for_old = cur_meta.offset_quality if cur_meta else 0.0
            if cur_meta and app_state.active_setlist_id:
                sl_entry = (cur_meta.setlist_offsets or {}).get(app_state.active_setlist_id)
                if sl_entry:
                    med = _median_offset(sl_entry.get("history") or [])
                    stored_offset_ms_disk = med if med is not None else int(sl_entry.get("timestamp_offset_ms", 0))
                    stored_quality_for_old = float(sl_entry.get("offset_quality", 0.0))
            try:
                from main import engine as _engine_for_old
                engine_offset_ms = int(_engine_for_old._shape_offset_ms)
            except Exception:
                engine_offset_ms = None
            stored_offset_ms = engine_offset_ms if engine_offset_ms is not None else stored_offset_ms_disk
            # Run the OLD evaluation on a worker thread — same reason as
            # _xcorr_window: numpy releases the GIL during interp/dot, so
            # the asyncio loop stays responsive while xcorr math runs.
            old_r = await asyncio.to_thread(
                _eval_at_shift,
                stored_ts, stored_bands, frames, win_start, win_end,
                -stored_offset_ms,                # shift_ms
            )
            # Coerce pre-NEW to preserve original ordering: the margin-
            # skip check inside _xcorr_window sees 0.0 (not None) when the
            # OLD eval found all bands flat.
            old_r = float(old_r) if old_r is not None else 0.0

            # ── NEW candidate: free-search xcorr (multi-band) ────────────
            # Run on a worker thread so the numpy sweep doesn't block the
            # asyncio event loop (which serves LedFX HTTP writes, WebSocket
            # broadcasts, and the trigger engine tick). FFT path (Phase 2):
            # exact r at every 25ms shift + landscape gates; legacy
            # coarse+fine kept as fallback while the flag is off.
            _win_landscape = None
            _stage = _ladder.current if _ladder else None
            if _ladder is not None:
                _lo, _hi = _stage.shift_bounds
                new_result, _win_landscape = await asyncio.to_thread(
                    _xcorr_window_fft_full,
                    stored_ts, stored_bands, frames, win_start, win_end,
                    search_lo_ms=_lo, search_hi_ms=_hi,
                    old_r=old_r,
                    tempo_bpm=tempo_bpm,
                )
            elif _accum_active:
                new_result, _win_landscape = await asyncio.to_thread(
                    _xcorr_window_fft_full,
                    stored_ts, stored_bands, frames, win_start, win_end,
                    search_ms=_xcorr_search_ms(int(meta.duration_ms or 0)),
                    old_r=old_r,
                    tempo_bpm=tempo_bpm,
                )
            else:
                _sweep_fn = _xcorr_window_fft if settings.xcorr_fft_enabled else _xcorr_window
                new_result = await asyncio.to_thread(
                    _sweep_fn,
                    stored_ts, stored_bands, frames, win_start, win_end,
                    search_ms=_xcorr_search_ms(int(meta.duration_ms or 0)),
                    old_r=old_r,
                    tempo_bpm=tempo_bpm,
                )

            # Engine play-best read once per window — feeds the envelope
            # clip's cold-start skip and the snap stickiness gate.
            try:
                from main import engine as _engine_for_gates
                engine_play_best = float(_engine_for_gates._play_best_quality)
            except Exception:
                engine_play_best = 0.0

            # All gate decisions (winner pick, envelope clip, confirmation
            # votes, snap stickiness, save gates) happen in the evaluator;
            # this loop performs the side effects below.
            outcome = evaluator.process_window(
                win_start, win_end,
                difficulty=difficulty,
                new_result=new_result,
                old_r=old_r,
                stored_offset_ms=stored_offset_ms,
                stored_quality=stored_quality_for_old,
                engine_current_offset_ms=(engine_offset_ms if engine_offset_ms is not None else 0),
                engine_play_best_quality=engine_play_best,
                landscape=_win_landscape,
                envelope_exempt=(_stage is not None and _stage.name == "global"),
            )

            # Phase 4: ladder escalation — when the current stage keeps
            # finding nothing, widen; an anti-correlated baseline goes
            # straight to global (the loaded center is provably wrong).
            if _ladder is not None:
                _new_stage = _ladder.note_window(outcome.new_result is not None)
                if _new_stage is None and outcome.baseline_anti_corr:
                    _new_stage = _ladder.escalate_to_global()
                if _new_stage is not None:
                    logger.info(
                        "Auto-offset xcorr: search ladder → %s (center=%+dms ±%dms) for %s",
                        _new_stage.name, _new_stage.center_offset_ms,
                        _new_stage.span_ms, uri,
                    )

            logger.info(
                "Auto-offset xcorr: [%d–%d]ms  NEW %+dms r=%.2f Q=%.2f  "
                "OLD %+dms r=%.2f Q=%.2f  diff=%.2f  thr=%.3f  winner=%s%s  for %s",
                win_start, win_end,
                outcome.new_offset_ms if outcome.new_result else 0,
                outcome.new_r, outcome.new_quality,
                stored_offset_ms, outcome.old_r, outcome.old_quality,
                difficulty, outcome.displacement_threshold,
                "NEW" if outcome.is_new else "OLD",
                " ← global best" if outcome.is_global_best else "",
                uri,
            )

            try:
                from services.websocket_manager import ws_manager
                asyncio.create_task(ws_manager.broadcast({
                    "type":               "xcorr_window",
                    "uri":                uri,
                    "win_start":          win_start,
                    "win_end":            win_end,
                    "failed":             outcome.new_result is None and outcome.old_r == 0.0,
                    # NEW candidate
                    "new_offset_ms":      outcome.new_offset_ms if outcome.new_result else None,
                    "new_r":              round(outcome.new_r, 3) if outcome.new_result else None,
                    "new_quality":        outcome.new_quality if outcome.new_result else None,
                    # OLD candidate
                    "old_offset_ms":      stored_offset_ms,
                    "old_r":              round(outcome.old_r, 3),
                    "old_quality":        outcome.old_quality,
                    # Window info
                    "difficulty":         round(difficulty, 3),
                    "winner":             "new" if outcome.is_new else "old",
                    "applied":            outcome.is_global_best and verification != "user_verified",
                    # Legacy compatibility
                    "offset_ms":          outcome.win_offset,
                    "pearson_r":          round(outcome.win_r, 3),
                }))
            except Exception:
                pass

            # Engine snap (uncluttered): every high-r window also tries to
            # snap the live engine via apply_save. apply_save only takes
            # effect when its Q strictly beats the play-best, so a noisy
            # single window can't override a confident anchor or earlier
            # higher-Q window. This is what makes the Now Playing display
            # update mid-play even before a cluster has formed for disk.
            if outcome.engine_snap is not None:
                _snap_offset, _snap_q, _snap_bypass = outcome.engine_snap
                try:
                    from main import engine
                    engine.apply_save(uri, _snap_offset, _snap_q,
                                      source="sweep-window",
                                      bypass_drift_cap=_snap_bypass)
                except Exception as exc:
                    logger.debug("Engine apply_save (window) failed: %s", exc)

            # Per-window DISK save (cluster-confirmed, or the single-window
            # high-r escape hatch — decided in the evaluator).
            if outcome.disk_save is not None:
                _sv_offset, _sv_q, _sv_source, _sv_bypass = outcome.disk_save
                _save_offset(uri, _sv_offset, _sv_q,
                             source=_sv_source, bypass_drift_cap=_sv_bypass)

            # DIAGNOSTIC CSV ──────────────────────────────────────────
            if settings.xcorr_csv_logging:
                _detail = await asyncio.to_thread(
                    _xcorr_window_detail,
                    stored_ts, stored_bands, frames,
                    win_start, win_end,
                    -outcome.win_offset,                  # winning_shift
                    search_ms=_xcorr_search_ms(int(meta.duration_ms or 0)),
                )
                _csv_window_rows.append({
                    "start_ms":   win_start,
                    "difficulty": round(difficulty, 4),
                    "winner":     "new" if outcome.is_new else "old",
                    "offset_ms":  outcome.win_offset,
                    "quality":    outcome.win_quality,
                    "r_avg":      round(outcome.win_r, 4),
                    "r_total":    _detail.r_total,
                    "r_low":      _detail.r_low,
                    "r_mid":      _detail.r_mid,
                    "r_high":     _detail.r_high,
                    "peak_total": _detail.peak_total_ms,
                    "peak_low":   _detail.peak_low_ms,
                    "peak_mid":   _detail.peak_mid_ms,
                    "peak_high":  _detail.peak_high_ms,
                    "old_r_avg":  round(outcome.old_r, 4),
                })
            # END DIAGNOSTIC CSV ──────────────────────────────────────

            # Lock-and-stop: once the engine has snapped at high Q AND
            # multiple windows agree on the offset, the marginal value of
            # the trailing windows is nil. Reads the engine play-best AFTER
            # this window's apply_save, matching the pre-refactor ordering.
            try:
                from main import engine as _engine_for_lock
                if evaluator.lock_and_stop(float(_engine_for_lock._play_best_quality)):
                    return True
            except Exception:
                pass
            return False

        # Phase 5: continuous mismatch monitor state.
        all_planned = list(windows)
        _monitor_active = bool(settings.xcorr_monitor_enabled)
        _mon_cfg = MonitorConfig.from_settings(settings)
        monitor = MismatchMonitor(_mon_cfg)
        monitor_mode = False
        _mon_next_ms = 0
        pending_dynamic: Optional[tuple[int, int]] = None

        capture.start()
        try:
            async for frame in capture:
                if not app_state.current_track:
                    break
                frames.append((frame.timestamp_ms, frame.rms_total, frame.rms_low, frame.rms_mid, frame.rms_high))

                # Live-frame snapshot for the Debug page, refreshed on a ~1 s
                # throttle so the page's live tail advances smoothly instead of
                # jumping once per xcorr window. Trimmed to the most recent
                # ~30 s so the snapshot stays small. The reference swap is
                # safe — readers iterate the old list by value.
                if frame.timestamp_ms - _last_snap_ms >= 1000:
                    _last_snap_ms = frame.timestamp_ms
                    self._frames_snapshot_uri = uri
                    _snap_cutoff = max(0, frame.timestamp_ms - 30000)
                    self._frames_snapshot = [f for f in frames if f[0] >= _snap_cutoff]

                # Anchor snap (progressive). Each candidate has its own
                # horizon; as frame time crosses a new one, retry matching
                # against the full set of eligible candidates so far. We try
                # in uniqueness order (already the order of anchor_candidates)
                # so the strongest candidate that becomes available has first
                # shot. Stops on first match or when all candidates have been
                # tried.
                if anchor_candidates and not anchor_done:
                    eligible_count = sum(1 for h in anchor_horizons if frame.timestamp_ms >= h)
                    if eligible_count > anchor_last_eligible:
                        eligible = [
                            c for c, h in zip(anchor_candidates, anchor_horizons)
                            if frame.timestamp_ms >= h
                        ]
                        match = anchor_detector.match_in_frames(eligible, frames)
                        if match is not None:
                            logger.info(
                                "Anchor: snap matched candidate at song-time=%dms band=%s — "
                                "offset=%+dms r=%.2f Q=%.2f (tried %d/%d candidates) for %s",
                                match.candidate.timestamp_ms, match.candidate.band,
                                match.offset_ms, match.match_r, match.match_q,
                                eligible_count, len(anchor_candidates), uri,
                            )
                            _save_offset_from_anchor(uri, match.offset_ms, match.match_q)
                            # The anchor's offset becomes a vote in the sweep's
                            # cluster gate. Weight = match_r × eligible_count
                            # (i.e. the cross-validation strength). A 5/5 anchor
                            # at r=0.95 contributes ~4.75; a 2/5 anchor at r=0.86
                            # contributes ~1.72. With the anchor's vote, even
                            # one sweep window agreeing within ±300ms can push
                            # the cluster gate over its threshold and save.
                            anchor_vote_weight = float(match.match_r) * max(1, eligible_count)
                            evaluator.add_anchor_vote(int(match.offset_ms), anchor_vote_weight)
                            # Broadcast match details so the shape canvas can
                            # render the live-match marker + beat-twin lines.
                            try:
                                cand_idx = next(
                                    (i for i, c in enumerate(anchor_candidates)
                                     if c.timestamp_ms == match.candidate.timestamp_ms
                                     and c.band == match.candidate.band),
                                    -1,
                                )
                                from services.websocket_manager import ws_manager
                                asyncio.create_task(ws_manager.broadcast({
                                    "type":           "shape_match_updated",
                                    "uri":            uri,
                                    "offset_ms":      int(match.offset_ms),
                                    "r":              float(match.match_r),
                                    "q":              float(match.match_q),
                                    "candidate_idx":  int(cand_idx),
                                    "band":           match.candidate.band,
                                    "source":         "anchor",
                                }))
                            except Exception:
                                pass
                            anchor_done = True
                        elif eligible_count >= len(anchor_candidates):
                            logger.info(
                                "Anchor: no candidate matched in %d frames — falling back to per-window sweep for %s",
                                len(frames), uri,
                            )
                            anchor_done = True
                        anchor_last_eligible = eligible_count

                # Progressive early match (Phase 3). Strict gates inside
                # progressive_match (CV / r / dominance / comb) — a quiet
                # intro just returns None and we retry next tick.
                if _prog_active and frame.timestamp_ms >= _prog_next_ms:
                    _prog_next_ms = frame.timestamp_ms + int(settings.xcorr_progressive_interval_ms)
                    if _ladder is not None:
                        _p_center = _ladder.current.center_offset_ms
                        _p_span = _ladder.current.span_ms
                    else:
                        _p_center = 0
                        _p_span = _xcorr_search_ms(int(meta.duration_ms or 0))
                    _prog = await asyncio.to_thread(
                        _progressive_match,
                        frames, stored_ts, stored_bands,
                        t_now_ms=frame.timestamp_ms,
                        search_ms=_p_span,
                        center_offset_ms=_p_center,
                    )
                    if _prog is not None:
                        logger.info(
                            "Auto-offset xcorr: progressive match %+dms r=%.2f Q=%.2f (span=%.1fs) for %s",
                            _prog.offset_ms, _prog.r, _prog.quality,
                            _prog.span_ms / 1000.0, uri,
                        )
                        # Engine-only: progressive corrects the live engine
                        # early but never writes to disk — persistent saves
                        # remain the windows'/accumulator's job, so a wrong
                        # early match can't poison the slot history.
                        try:
                            from main import engine as _engine_for_prog
                            _engine_for_prog.apply_save(
                                uri, int(_prog.offset_ms), float(_prog.quality),
                                source="progressive",
                            )
                        except Exception as exc:
                            logger.debug("Engine apply_save (progressive) failed: %s", exc)
                        evaluator.add_progressive_vote(_prog.offset_ms, _prog.r)
                        try:
                            from services.websocket_manager import ws_manager
                            asyncio.create_task(ws_manager.broadcast({
                                "type":      "xcorr_progressive",
                                "uri":       uri,
                                "offset_ms": _prog.offset_ms,
                                "r":         _prog.r,
                                "q":         _prog.quality,
                                "span_ms":   _prog.span_ms,
                            }))
                        except Exception:
                            pass
                        _prog_active = False   # first lock — hand over to the sweep

                # ── Monitor tick (monitor-only mode, Phase 5) ────────────────
                if monitor_mode and _monitor_active and frame.timestamp_ms >= _mon_next_ms:
                    _mon_next_ms = frame.timestamp_ms + _mon_cfg.interval_ms
                    try:
                        from main import engine as _eng_mon
                        _mon_off = int(_eng_mon._shape_offset_ms)
                        _mon_pb = float(_eng_mon._play_best_quality)
                    except Exception:
                        _mon_off, _mon_pb = 0, 0.0
                    _mw_end = min(frame.timestamp_ms + _mon_off, int(stored_ts[-1]))
                    _mw_start = _mw_end - _mon_cfg.span_ms
                    rolling_r = None
                    if _mw_start >= 0:
                        # Difficulty gate: a flat/repetitive stored span can't
                        # testify about alignment — treat like silence
                        # (neutral), not like mismatch. Mirrors the sweep's
                        # window-difficulty wisdom; cuts false recoveries on
                        # quiet bridges/outros of correctly-locked plays.
                        _mw_bins = np.arange(_mw_start, _mw_end, _XCORR_BIN_MS, dtype=float)
                        _mw_tpl = np.interp(_mw_bins, stored_ts, stored_rms)
                        if _difficulty_score(_mw_tpl, stored_rms) >= float(
                                getattr(settings, "xcorr_starting_threshold", 0.15)):
                            rolling_r = await asyncio.to_thread(
                                _eval_at_shift, stored_ts, stored_bands, frames,
                                _mw_start, _mw_end, -_mon_off,
                            )
                    action = monitor.note_check(rolling_r, _mon_pb)
                    try:
                        from services.websocket_manager import ws_manager
                        asyncio.create_task(ws_manager.broadcast({
                            "type":       "xcorr_monitor",
                            "uri":        uri,
                            "t_ms":       frame.timestamp_ms,
                            "rolling_r":  round(rolling_r, 3) if rolling_r is not None else None,
                            "state":      monitor.state,
                            "recoveries": monitor.recoveries,
                        }))
                    except Exception:
                        pass
                    if action == "confirmed":
                        spike = await asyncio.to_thread(
                            _mismatch_spike,
                            stored_ts, stored_bands, frames,
                            engine_offset_ms=_mon_off,
                            t_now_ms=frame.timestamp_ms,
                            lookback_ms=_mon_cfg.spike_lookback_ms,
                            halfwin_ms=_mon_cfg.spike_halfwin_ms,
                        )
                        # First recovery: one ladder stage; second: global —
                        # the current center is suspect, but global is where
                        # twins live, so widen gradually.
                        if _ladder is not None:
                            _st = (_ladder.escalate_to_global()
                                   if monitor.recoveries >= 2 else _ladder.escalate())
                            if _st is not None:
                                logger.info(
                                    "Auto-offset monitor: ladder → %s (center=%+dms ±%dms) for %s",
                                    _st.name, _st.center_offset_ms, _st.span_ms, uri,
                                )
                        evaluator.note_mismatch_confirmed(_mon_cfg.accum_decay)
                        try:
                            from main import engine as _eng_dem
                            _eng_dem.demote_play_best(uri, _mon_cfg.demote_q)
                        except Exception:
                            pass
                        if spike is not None:
                            _dws, _dwe, _spike_ms, _strength = spike
                            pending_dynamic = (_dws, _dwe)
                            logger.info(
                                "Auto-offset monitor: CONFIRMED mismatch (r=%.2f) — dynamic window "
                                "[%d–%d]ms at residual spike %dms (strength=%.2f), sweep re-armed for %s",
                                rolling_r if rolling_r is not None else -1.0,
                                _dws, _dwe, _spike_ms, _strength, uri,
                            )
                        else:
                            logger.info(
                                "Auto-offset monitor: CONFIRMED mismatch (r=%.2f) — no usable spike, "
                                "sweep re-armed for %s",
                                rolling_r if rolling_r is not None else -1.0, uri,
                            )
                        window_queue = [(s, e) for s, e in all_planned
                                        if s > frame.timestamp_ms]
                        monitor_mode = False

                # ── Dynamic (mismatch-spike) window: bypasses the margin check —
                # its live data exists by construction (stored-domain window).
                if pending_dynamic is not None:
                    _dws, _dwe = pending_dynamic
                    pending_dynamic = None
                    locked = await _run_window(_dws, _dwe)
                    monitor.recovery_done()
                    if locked:
                        _locked_via_stop = True
                        if not _monitor_active:
                            break
                        monitor_mode = True
                        window_queue = []
                        _mon_next_ms = frame.timestamp_ms + _mon_cfg.interval_ms
                    continue

                if not window_queue:
                    if not _monitor_active:
                        break          # flags-off: byte-identical exit
                    if not monitor_mode:
                        monitor_mode = True
                        _mon_next_ms = frame.timestamp_ms + _mon_cfg.interval_ms
                    continue
                win_start, win_end = window_queue[0]
                if frame.timestamp_ms < win_end + _XCORR_MARGIN_MS:
                    continue

                window_queue.pop(0)
                _prog_active = False   # first planned window reached — progressive done

                locked = await _run_window(win_start, win_end)
                if locked:
                    _locked_via_stop = True
                    if not _monitor_active:
                        break          # flags-off: byte-identical exit
                    monitor_mode = True
                    window_queue = []
                    _mon_next_ms = frame.timestamp_ms + _mon_cfg.interval_ms
                    continue

                if not window_queue:
                    if not _monitor_active:
                        break          # flags-off: byte-identical exit
                    monitor_mode = True
                    _mon_next_ms = frame.timestamp_ms + _mon_cfg.interval_ms
                # Lock-and-stop: once the engine has snapped at high Q AND
                # multiple windows agree on the offset, the marginal value of
                # the trailing windows is nil — halt the rest of this play's
                # xcorr loop so worker-thread CPU isn't burned on diminishing
                # returns. Reads the engine play-best AFTER this window's
                # apply_save, matching the pre-refactor ordering.
                try:
                    from main import engine as _engine_for_lock
                    if evaluator.lock_and_stop(float(_engine_for_lock._play_best_quality)):
                        _locked_via_stop = True
                        break
                except Exception:
                    pass

                if not window_queue:
                    break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Auto-offset xcorr: detection error for %s: %s", uri, exc)
        finally:
            capture.stop()

        if evaluator.n_measurements == 0:
            logger.info("Auto-offset xcorr: no measurements obtained for %s", uri)
            self._watching_uri = None
            self._task = None
            return

        logger.info(
            "Auto-offset xcorr: final offset=%+dms Q=%.2f diff=%.2f "
            "from %d window(s) for %s",
            evaluator.best_offset, evaluator.best_quality,
            evaluator.best_difficulty, evaluator.n_measurements, uri,
        )

        # Post-loop decisions (anti-corr majority detector, cluster override,
        # final save gates) live in the evaluator; side effects below.
        final = evaluator.finalize()

        # ── OLD-anti-correlated detector ───────────────────────────────────
        # When a majority of windows (with non-trivial OLD samples) showed the
        # stored offset as anti-correlated, the stored baseline doesn't fit
        # this play. Bump anti_corr_count on the Set List slot so the UI can
        # surface drifting songs. Reset on any "well-correlated" play.
        try:
            if app_state.active_setlist_id and final.is_drifting is not None:
                _bump_anti_corr_count(uri, app_state.active_setlist_id, final.is_drifting)
        except Exception as exc:
            logger.debug("anti_corr_count update failed: %s", exc)

        # ── Record offset history ──────────────────────────────────────────
        prev_offset_ms = None
        try:
            hist_meta = load_audio_shape_meta(uri)
            if hist_meta:
                if hist_meta.offset_history:
                    prev_offset_ms = hist_meta.offset_history[0].get("offset_ms")
                hist_meta.offset_history.insert(0, {
                    "iso_timestamp": datetime.now(timezone.utc).isoformat(),
                    "offset_ms": final.best_offset,
                    "quality": round(final.best_quality, 3),
                    "window_count": final.n_measurements,
                })
                hist_meta.offset_history = hist_meta.offset_history[:20]  # cap at 20
                meta_path = AUDIO_SHAPES_DIR / hist_meta.npz_file.replace(".npz", ".json")
                meta_path.write_text(hist_meta.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Auto-offset xcorr: failed to save offset history: %s", exc)

        try:
            from services.websocket_manager import ws_manager
            asyncio.create_task(ws_manager.broadcast({
                "type":           "xcorr_final",
                "uri":            uri,
                "offset_ms":      final.best_offset,
                "quality_score":  final.best_quality,
                "difficulty":     round(final.best_difficulty, 3),
                "n_measurements": final.n_measurements,
                "saved":          verification != "user_verified",
                "prev_offset_ms": prev_offset_ms,
                "play_type":      play_type,
            }))
        except Exception:
            pass

        # DIAGNOSTIC CSV ──────────────────────────────────────────────────
        if settings.xcorr_csv_logging and final.n_measurements > 0:
            _write_csv_row(
                track=app_state.current_track, uri=uri,
                final_offset=final.best_offset, final_quality=final.best_quality,
                n_windows=final.n_measurements, prev_offset=prev_offset_ms,
                window_rows=_csv_window_rows,
                play_type=play_type,
            )
        # END DIAGNOSTIC CSV ──────────────────────────────────────────────

        if final.disk_save is not None:
            _fin_offset, _fin_q, _fin_source, _fin_bypass = final.disk_save
            _save_offset(uri, _fin_offset, _fin_q,
                         source=_fin_source, bypass_drift_cap=_fin_bypass)

        # Lock-and-stop: keep `_watching_uri` set so on_track_change's
        # "already watching this URI" guard suppresses a fresh xcorr task
        # spawn until the song actually changes. Without this, the task ends
        # → guard sees no watch → next poll starts a new xcorr → lock-and-stop
        # fires again on the next ~3 windows → endless loop.
        if not _locked_via_stop:
            self._watching_uri = None
        self._task = None

    async def _detect_loop_spike_legacy(self, uri: str, candidates: list[dict]) -> None:
        """
        DISABLED — original spike-detection alignment (v1). Kept for reference.

        TO REINTEGRATE:
          1. In on_track_change(), replace the xcorr task block with:
                 current_pos_ms = track.interpolated_progress_ms()
                 candidates = _find_target_spike(new_uri, current_pos_ms)
                 if not candidates:
                     logger.info("Auto-offset: no spike found for %s", new_uri)
                     return
                 self._watching_uri = new_uri
                 self._task = asyncio.create_task(
                     self._detect_loop_spike_legacy(new_uri, candidates),
                     name="auto-offset-detect",
                 )
          2. Restore the auto_offset_targeting WS broadcast and _candidates tracking
             from git history if needed by the builder UI.
          3. Remove _detect_loop_xcorr, _xcorr_window, _combine_measurements, and
             the _XCORR_* constants.

        TO REMOVE PERMANENTLY:
          Delete this method and _find_target_spike() once xcorr has been validated
          as reliable across ≥20 different songs in production.
        """
        track = app_state.current_track
        if not track:
            return
        import time
        song_start = time.monotonic() - track.interpolated_progress_ms() / 1000.0
        capture = AudioCaptureStream(song_start)
        capture.start()

        window = settings.auto_offset_search_window_ms
        pre_gate = settings.auto_offset_pre_gate_ms
        sr_ms = settings.audio_chunk_size / settings.audio_sample_rate * 1000  # ~11.6ms
        lookback_frames = max(1, int(settings.auto_offset_lookback_ms / sr_ms))
        threshold = settings.auto_offset_spike_threshold

        remaining = sorted(candidates, key=lambda c: c["ms"])
        buffer: deque[float] = deque(maxlen=lookback_frames)
        cand_idx = 0
        in_outer_window = False
        best_confidence = 0.0
        any_detected = False

        try:
            async for frame in capture:
                if cand_idx >= len(remaining):
                    break

                candidate = remaining[cand_idx]
                target_ms = candidate["ms"]
                target_conf = candidate["confidence"]

                if not app_state.current_track:
                    break

                frame_ts = frame.timestamp_ms
                buffer.append(frame.rms_low)

                if frame_ts > target_ms + window:
                    logger.info(
                        "Auto-offset: missed candidate %d at %dms (frame@%dms) for %s",
                        candidate["rank"], target_ms, frame_ts, uri,
                    )
                    cand_idx += 1
                    in_outer_window = False
                    continue

                if not in_outer_window:
                    if frame_ts >= target_ms - window:
                        in_outer_window = True
                    else:
                        continue

                if frame_ts < target_ms - pre_gate:
                    continue

                if len(buffer) < lookback_frames // 4:
                    continue
                baseline_mean = sum(buffer) / len(buffer)
                if baseline_mean < 1e-5:
                    continue

                live_onset_ratio = frame.rms_low / baseline_mean
                expected_onset_ratio = candidate.get("expected_onset_ratio", 0.0)
                min_ratio = settings.auto_offset_onset_ratio_min

                if live_onset_ratio < threshold:
                    continue

                if min_ratio > 0 and expected_onset_ratio > 0 \
                        and live_onset_ratio < expected_onset_ratio * min_ratio:
                    continue

                offset_ms = target_ms - frame_ts
                if not any_detected or target_conf > best_confidence:
                    _save_offset(uri, offset_ms)
                    best_confidence = target_conf
                    any_detected = True
                    logger.info(
                        "Auto-offset updated: %+dms (conf=%.1f, cand %d, "
                        "onset_ratio=%.2f/%.2f, target=%dms frame=%dms) for %s",
                        offset_ms, target_conf, candidate["rank"],
                        live_onset_ratio, expected_onset_ratio,
                        target_ms, frame_ts, uri,
                    )
                else:
                    cand_idx += 1
                    in_outer_window = False

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Auto-offset detection error: %s", exc)
        finally:
            capture.stop()

        if not any_detected:
            logger.debug("Auto-offset detection ended without result for %s", uri)
        self._watching_uri = None
        self._task = None


# ── Module-level helpers ───────────────────────────────────────────────────────


def _compute_params_hash(npz_mtime: float) -> str:
    """Hash of xcorr config params + npz modification time for cache invalidation."""
    s = settings
    raw = (
        f"{s.xcorr_window_size_ms}:{s.xcorr_max_test_gap_ms}:"
        f"{s.xcorr_starting_threshold}:{s.xcorr_global_threshold}:"
        f"{s.xcorr_max_windows}:{s.xcorr_min_early_windows}:"
        # mix-aware search affects self-similarity radius → must invalidate
        f"{s.xcorr_search_ms_base}:{s.xcorr_cut_buffer_ms}:"
        # bump on planner algorithm changes (e.g. self-similarity)
        f"selfsim_v1:"
        f"{npz_mtime}"
    )
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _plan_xcorr_windows(
    stored_ts: np.ndarray,
    stored_rms: np.ndarray,
    duration_ms: int,
) -> list[dict]:
    """
    Pre-compute the best xcorr windows for a song based on structural uniqueness.

    Returns list of {start_ms, end_ms, difficulty} dicts sorted by start_ms.

    Algorithm:
      1. Slide window across stored RMS, score each position by difficulty
      2. Greedy selection with zone constraints:
         - Pass 1: Early mandate (N windows in first 20s, even if low quality)
         - Pass 2: Early zone fill (5 windows in first third or 60s)
         - Pass 3: Global fill (up to max_windows total)
         - Pass 4: Gap fill (no gap > max_test_gap between window end and next start)
    """
    win_size = settings.xcorr_window_size_ms
    max_end = duration_ms - _XCORR_END_BUFFER_MS
    min_start = _XCORR_FIRST_START_MS
    threshold = settings.xcorr_starting_threshold
    max_windows = settings.xcorr_max_windows
    min_early = settings.xcorr_min_early_windows
    max_gap = settings.xcorr_max_test_gap_ms

    if max_end - win_size < min_start:
        logger.info("Auto-offset xcorr: song too short for smart windows (dur=%dms)", duration_ms)
        return []

    # ── Step 1: Generate all candidate positions and score them ──────────
    # Self-similarity radius uses the worst-case mix-aware search: a song's
    # active Set List buffer can override the global, so use base + global
    # buffer + headroom so we don't under-search for periodic candidates.
    sim_search_ms = (
        settings.xcorr_search_ms_base
        + settings.xcorr_cut_buffer_ms
        + 5000  # headroom; per-Set-List buffers can exceed the global default
    )
    full_bins = np.arange(0, duration_ms, _XCORR_BIN_MS, dtype=float)
    full_template = np.interp(full_bins, stored_ts, stored_rms)

    candidates: list[dict] = []
    pos = min_start
    while pos + win_size <= max_end:
        bins = np.arange(pos, pos + win_size, _XCORR_BIN_MS, dtype=float)
        window_rms = np.interp(bins, stored_ts, stored_rms)
        raw_diff = _difficulty_score(window_rms, stored_rms)
        sim_count = _self_similarity_count(
            window_template=window_rms,
            full_template=full_template,
            win_start_ms=pos,
            search_radius_ms=sim_search_ms,
        )
        uniqueness = _uniqueness_factor(sim_count)
        final_diff = raw_diff * uniqueness
        candidates.append({
            "start_ms": pos,
            "end_ms": pos + win_size,
            "difficulty": round(final_diff, 4),
            "raw_difficulty": round(raw_diff, 4),
            "self_similarity": sim_count,
            "uniqueness": round(uniqueness, 3),
        })
        pos += _XCORR_CANDIDATE_STEP

    if not candidates:
        return []

    # ── Step 2: Helper to check overlap with selected windows ────────────
    selected: list[dict] = []

    def overlaps(cand: dict) -> bool:
        for s in selected:
            if cand["start_ms"] < s["end_ms"] and cand["end_ms"] > s["start_ms"]:
                return True
        return False

    def pick_best(pool: list[dict], count: int, force: bool = False) -> None:
        """Pick up to `count` windows from pool. If force=True, ignore threshold."""
        sorted_pool = sorted(pool, key=lambda c: c["difficulty"], reverse=True)
        added = 0
        for c in sorted_pool:
            if added >= count:
                break
            if not force and c["difficulty"] < threshold:
                continue
            if overlaps(c):
                continue
            selected.append(c)
            added += 1
        # If force and we haven't hit count, also try below-threshold
        if force and added < count:
            for c in sorted_pool:
                if added >= count:
                    break
                if overlaps(c):
                    continue
                if c not in selected:
                    selected.append(c)
                    added += 1

    # ── Pass 1: Early mandate — at least min_early windows in first 20s ──
    early_20s = [c for c in candidates if c["start_ms"] + win_size <= 20_000]
    pick_best(early_20s, min_early, force=True)

    # ── Pass 2: Early zone fill — 5 windows in first third or 60s ────────
    early_zone_end = max(duration_ms // 3, 60_000)
    early_zone = [c for c in candidates if c["start_ms"] < early_zone_end]
    early_target = 5
    early_remaining = early_target - len([s for s in selected if s["start_ms"] < early_zone_end])
    if early_remaining > 0:
        pick_best(early_zone, early_remaining)

    # ── Pass 3: Global fill — up to max_windows total ────────────────────
    global_remaining = max_windows - len(selected)
    if global_remaining > 0:
        pick_best(candidates, global_remaining)

    # ── Pass 4: Gap fill ─────────────────────────────────────────────────
    # Sort selected, then find gaps exceeding max_test_gap
    selected.sort(key=lambda w: w["start_ms"])
    gap_iterations = 0
    max_gap_iterations = 20  # safety limit
    while gap_iterations < max_gap_iterations:
        gap_iterations += 1
        found_gap = False
        for i in range(len(selected) - 1):
            gap = selected[i + 1]["start_ms"] - selected[i]["end_ms"]
            if gap > max_gap:
                # Find best candidate that fits in this gap
                gap_start = selected[i]["end_ms"]
                gap_end = selected[i + 1]["start_ms"]
                gap_pool = [
                    c for c in candidates
                    if c["start_ms"] >= gap_start
                    and c["end_ms"] <= gap_end
                    and c["difficulty"] >= threshold
                    and not overlaps(c)
                ]
                if gap_pool:
                    best = max(gap_pool, key=lambda c: c["difficulty"])
                    selected.append(best)
                    selected.sort(key=lambda w: w["start_ms"])
                    found_gap = True
                    break  # restart gap scan with new selection
                # No candidate fits — accept this gap
        if not found_gap:
            break

    logger.info(
        "Auto-offset xcorr: planned %d windows (sim/diff: %s)",
        len(selected),
        ", ".join(
            f"{w.get('self_similarity', 1)}|{w['difficulty']:.2f}" for w in selected
        ),
    )
    return selected


def _self_similarity_count(
    window_template: np.ndarray,
    full_template: np.ndarray,
    win_start_ms: int,
    search_radius_ms: int,
    sim_threshold: float = 0.65,
    min_peak_separation_ms: int = 800,
) -> int:
    """
    Count how many times this window's pattern occurs within ±search_radius_ms
    around its own start position in the full song template.

    A truly unique window returns 1 (only matches itself). A window whose
    pattern repeats N times returns N. The trivial self-match at the
    candidate's own position is always excluded from the count.

    Both arrays are expected to be sampled at _XCORR_BIN_MS resolution.
    """
    n = len(window_template)
    full_n = len(full_template)
    if n < 2 or full_n < n:
        return 1

    # Bin index for the window's own start in full_template
    self_bin = int(round(win_start_ms / _XCORR_BIN_MS))
    radius_bins = max(1, int(search_radius_ms / _XCORR_BIN_MS))

    # Pre-normalise the template (z-score)
    t_mean = float(window_template.mean())
    t_std  = float(window_template.std())
    if t_std < 1e-6:
        return 1
    template_norm = (window_template - t_mean) / t_std

    # Walk all candidate start bins in [self_bin - radius_bins, self_bin + radius_bins]
    lo = max(0, self_bin - radius_bins)
    hi = min(full_n - n, self_bin + radius_bins)
    r_curve: list[tuple[int, float]] = []  # (bin_offset_from_self, r)
    for b in range(lo, hi + 1):
        seg = full_template[b:b + n]
        s_std = float(seg.std())
        if s_std < 1e-6:
            r_curve.append((b - self_bin, 0.0))
            continue
        seg_norm = (seg - seg.mean()) / s_std
        r = float(np.dot(template_norm, seg_norm)) / n
        r_curve.append((b - self_bin, r))

    # Count peaks above sim_threshold, enforcing min_peak_separation
    sep_bins = max(1, int(min_peak_separation_ms / _XCORR_BIN_MS))
    peaks: list[int] = []  # bin offsets of accepted peaks
    # Sort by r descending; greedily accept if not within sep_bins of an existing peak.
    for shift_bins, r in sorted(r_curve, key=lambda x: x[1], reverse=True):
        if r < sim_threshold:
            break
        if all(abs(shift_bins - p) >= sep_bins for p in peaks):
            peaks.append(shift_bins)

    # Exclude the self-match peak (at shift_bins == 0). Accept a small tolerance
    # in case rounding misaligns by one bin.
    excluded = sum(1 for p in peaks if abs(p) <= 1)
    return max(1, len(peaks) - excluded + 1)  # +1 always counts self


def _uniqueness_factor(self_sim_count: int) -> float:
    """Map self-similarity peak count to a difficulty multiplier in [0..1].

    count == 1 → 1.0   (perfectly unique — keep full difficulty)
    count == 2 → 0.5   (twin pattern — half-credit)
    count == 3 → 0.25
    count >= 4 → 0.0   (effectively disqualified)
    """
    if self_sim_count <= 1:
        return 1.0
    return max(0.0, 1.0 / (2 ** (self_sim_count - 1)))


def _find_target_spike(uri: str, current_pos_ms: float) -> list[dict]:
    """
    DISABLED — used by _detect_loop_spike_legacy. See that method's docstring for
    reintegration and permanent-removal instructions.

    Scan stored shape for isolated bass onset candidates at least 5 000 ms ahead.

    Scoring per frame i:
      onset_ratio     = rms_l[i] / mean(rms_l[i - lookback : i])
      isolation_ratio = rms_l[i] / max(rms_l[i - iso_frames : i - close_frames])
      confidence      = onset_ratio * isolation_ratio

    Both onset_ratio > threshold and isolation_ratio > isolation_ratio_threshold
    are required. Returns up to 3 candidates sorted chronologically (earliest first),
    each as {"ms": int, "confidence": float, "rank": int}.

    If the strict pass finds nothing, a single relaxed retry is performed with
    thresholds multiplied by auto_offset_relax_threshold / auto_offset_relax_isolation.
    Returns [] only if both passes find nothing.
    """
    meta = load_audio_shape_meta(uri)
    if meta is None:
        return []
    npz_path = AUDIO_SHAPES_DIR / meta.npz_file
    if not npz_path.exists():
        return []

    try:
        data = np.load(npz_path)
        ts    = data["timestamps_ms"].astype(int)
        rms_l = data["rms_low"]
    except Exception as exc:
        logger.warning("Auto-offset: failed to load npz for %s: %s", uri, exc)
        return []

    if len(ts) < 2:
        return []

    sr_ms        = max(1.0, float(np.mean(np.diff(ts))))
    lookback_frames = max(1, int(settings.auto_offset_lookback_ms / sr_ms))
    iso_frames      = max(1, int(settings.auto_offset_isolation_ms / sr_ms))
    close_frames    = max(1, int(200 / sr_ms))
    min_ms          = current_pos_ms + 5000

    passes = [
        ("strict",  settings.auto_offset_spike_threshold, settings.auto_offset_isolation_ratio,
                    iso_frames),
        ("relaxed", settings.auto_offset_spike_threshold  * settings.auto_offset_relax_threshold,
                    settings.auto_offset_isolation_ratio  * settings.auto_offset_relax_isolation,
                    max(1, int(settings.auto_offset_isolation_ms
                               * settings.auto_offset_relax_isolation_ms / sr_ms))),
    ]

    for pass_name, threshold, iso_threshold, pass_iso_frames in passes:
        need_frames = lookback_frames + pass_iso_frames
        all_candidates: list[tuple[float, int, float]] = []

        for i in range(need_frames, len(ts)):
            if ts[i] < min_ms:
                continue

            baseline = float(np.mean(rms_l[i - lookback_frames : i]))
            if baseline < 1e-5:
                continue
            onset_ratio = rms_l[i] / baseline
            if onset_ratio < threshold:
                continue

            iso_start = i - pass_iso_frames
            iso_end   = max(iso_start + 1, i - close_frames)
            if iso_end <= iso_start:
                continue
            iso_max = float(np.max(rms_l[iso_start : iso_end]))
            isolation_ratio = rms_l[i] / (iso_max + 1e-9)
            if isolation_ratio < iso_threshold:
                continue

            peak_end = min(i + close_frames + 1, len(ts))
            peak_idx = i + int(np.argmax(rms_l[i : peak_end]))
            all_candidates.append((onset_ratio * isolation_ratio, peak_idx, onset_ratio))

        if not all_candidates:
            if pass_name == "strict":
                logger.debug(
                    "Auto-offset: strict pass found nothing for %s — trying relaxed",
                    uri,
                )
            continue

        all_candidates.sort(key=lambda x: x[1])
        deduped: list[tuple[float, int, float]] = []
        for conf, idx, onset_r in all_candidates:
            spike_ms = int(ts[idx])
            if any(abs(spike_ms - int(ts[d_idx])) < 500 for _, d_idx, _ in deduped):
                continue
            deduped.append((conf, idx, onset_r))
            if len(deduped) == 3:
                break

        return [
            {
                "ms": int(ts[idx]),
                "confidence": round(float(conf), 2),
                "rank": rank + 1,
                "expected_onset_ratio": round(float(onset_r), 3),
            }
            for rank, (conf, idx, onset_r) in enumerate(deduped)
        ]

    return []


# DIAGNOSTIC CSV ──────────────────────────────────────────────────────────────
def _write_csv_row(
    track, uri: str,
    final_offset: int, final_quality: float,
    n_windows: int, prev_offset,
    window_rows: list[dict],
    play_type: str = "first",
) -> None:
    """Append one row to storage/xcorr_diagnostic.csv. Header written on first row."""
    try:
        write_header = not _CSV_PATH.exists() or _CSV_PATH.stat().st_size == 0
        song_name = f"{track.artist} - {track.title}" if track else uri
        play_ts = datetime.now(timezone.utc).isoformat()

        row: dict[str, object] = {
            "song":            song_name,
            "timestamp":       play_ts,
            "uri":             uri,
            "duration_ms":     track.duration_ms if track else "",
            "final_offset_ms": final_offset,
            "final_quality":   round(final_quality, 4),
            "n_windows":       n_windows,
            "prev_offset_ms":  prev_offset if prev_offset is not None else "",
            "play_type":       play_type,
        }

        for slot_idx, w in enumerate(window_rows[:_CSV_MAX_WINDOWS], start=1):
            p = f"w{slot_idx}_"
            row[p + "start_ms"]   = w["start_ms"]
            row[p + "difficulty"] = w["difficulty"]
            row[p + "winner"]     = w["winner"]
            row[p + "offset_ms"]  = w["offset_ms"]
            row[p + "quality"]    = w["quality"]
            row[p + "r_avg"]      = w["r_avg"]
            row[p + "r_total"]    = w["r_total"]
            row[p + "r_low"]      = w["r_low"]
            row[p + "r_mid"]      = w["r_mid"]
            row[p + "r_high"]     = w["r_high"]
            row[p + "peak_total"] = w["peak_total"]
            row[p + "peak_low"]   = w["peak_low"]
            row[p + "peak_mid"]   = w["peak_mid"]
            row[p + "peak_high"]  = w["peak_high"]
            row[p + "old_r_avg"]  = w["old_r_avg"]

        # Pad trailing window slots with empty strings
        for slot_idx in range(len(window_rows) + 1, _CSV_MAX_WINDOWS + 1):
            for col in _csv_window_cols(slot_idx):
                row[col] = ""

        _CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _CSV_PATH.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_ALL_COLS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        logger.debug("DIAGNOSTIC CSV: appended row for %s → %s", song_name, _CSV_PATH)
    except Exception as exc:
        logger.warning("DIAGNOSTIC CSV: failed to write row: %s", exc)
# END DIAGNOSTIC CSV ──────────────────────────────────────────────────────────


def _save_offset_from_anchor(uri: str, offset_ms: int, quality: float) -> None:
    """Anchor-derived save. The anchor's uniqueness is vetted offline, so a
    single confident match is enough to commit — no cluster gate needed.
    History entry is tagged `source: "anchor"` so it can be distinguished
    from cluster-confirmed sweep saves in diagnostics.
    """
    _save_offset(uri, offset_ms, quality, source="anchor")


def _save_offset(uri: str, offset_ms: int, quality: float = 0.0,
                 source: str = "sweep",
                 bypass_drift_cap: bool = False) -> None:
    """Persist offset + quality score, mark as auto_verified, hot-reload trigger engine.

    When the active context is a tracked Set List, write into
    `meta.setlist_offsets[setlist_id]` instead of the legacy fields, so
    non-mix plays of the same song aren't polluted by mix-warped offsets.
    The Spotify API doesn't reliably surface mix-trim, so the active Set
    List itself is the trigger — the user has explicitly told us this
    playlist is mix-affected by tracking it.

    `source` is recorded on the history entry: "sweep" for cluster-confirmed
    per-window xcorr saves, "anchor" for early-feature snap saves.
    """
    from datetime import datetime, timezone
    meta = load_audio_shape_meta(uri)
    if meta is None:
        return

    polled = app_state.current_track.duration_ms if app_state.current_track else 0
    cut_ms = max(0, int(meta.duration_ms or 0) - int(polled or 0))
    sl_id = app_state.active_setlist_id

    now_iso = datetime.now(timezone.utc).isoformat()
    if sl_id:
        if not isinstance(meta.setlist_offsets, dict):
            meta.setlist_offsets = {}
        prev = meta.setlist_offsets.get(sl_id) or {}
        history = list(prev.get("history") or [])
        history.insert(0, {
            "offset_ms": int(offset_ms),
            "quality": round(quality, 3),
            "generated_at": now_iso,
            "source": source,
        })
        history = history[:_OFFSET_HISTORY_CAP]
        entry_update = {
            **prev,                                          # preserve perception_trim_ms, anti_corr_count, etc
            "timestamp_offset_ms": int(offset_ms),
            "offset_quality": round(quality, 3),
            "generated_at": now_iso,
            "observed_cut_ms": int(cut_ms),
            "history": history,
        }
        # Phase 4: a large positive lock is a directly-observed blend cut-in
        # point — persist it so the next play's narrow search centers there.
        # Supersedes the crude captured−polled `observed_cut_ms` estimate.
        _cut_in_min = int(getattr(settings, "xcorr_cut_in_record_min_ms", 3000))
        if int(offset_ms) >= _cut_in_min:
            entry_update["observed_cut_in_ms"] = int(offset_ms)
        meta.setlist_offsets[sl_id] = {
            **entry_update,
            # Successful save means the stored offset is good for this play —
            # reset the anti-correlated streak counter.
            "anti_corr_count": 0,
            # Round 7: a save fired for this slot, so the slot is now
            # "coarse-locked" — anchor-as-cold-start is no longer needed
            # unless future plays anti-correlate enough to demote this back
            # to False (see _bump_anti_corr_count).
            "coarse_locked": True,
        }
        # Track per-Set-List bias delta against the prior median (Option 5).
        try:
            prior_median = _median_offset(prev.get("history") or [])
            if prior_median is not None:
                _record_setlist_delta(sl_id, int(offset_ms) - int(prior_median))
        except Exception as exc:
            logger.debug("setlist delta record failed: %s", exc)
    else:
        meta.timestamp_offset_ms = offset_ms
        meta.offset_quality = round(quality, 3)
        meta.offset_verification = "auto_verified"

    meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    # Apply to the live engine — only takes effect if this save's quality
    # beats the best seen this play. Persists either way (we just wrote to
    # disk above), so the next play's median can include this save.
    #
    # Anchor quality boost: the anchor save's `quality` field is match_r ×
    # uniqueness, typically 0.30–0.50. The per-window sweep emits Q values
    # of 0.50–0.80 (Pearson_r × difficulty), so without a boost an early
    # sweep window can win the engine.apply_save quality-wins gate within
    # seconds of the anchor snap and replace it. Anchors carry stronger
    # provenance — uniqueness vetted offline, ≥2 candidates cross-validated
    # at runtime — so they should hold their position unless the sweep finds
    # something genuinely better. Multiplying by 1.6 puts a strong anchor
    # (Q≈0.45) on par with a strong sweep window (Q≈0.72).
    apply_quality = float(quality) * (1.6 if source == "anchor" else 1.0)
    try:
        from main import engine
        engine.apply_save(uri, int(offset_ms), apply_quality, source,
                          bypass_drift_cap=bypass_drift_cap)
    except Exception as exc:
        logger.warning("Auto-offset: could not apply offset to trigger engine: %s", exc)

    # Broadcast to update all open pages (builder, ai_triggers sliders)
    try:
        from services.websocket_manager import ws_manager
        asyncio.create_task(ws_manager.broadcast({
            "type":       "shape_offset_updated",
            "uri":        uri,
            "offset_ms":  offset_ms,
            "quality":    round(quality, 3),
            "verification": "auto_verified",
        }))
    except Exception:
        pass


# Singleton
auto_offset_service = AutoOffsetService()
