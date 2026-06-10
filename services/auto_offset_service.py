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
from dataclasses import dataclass as _dataclass  # DIAGNOSTIC CSV
from datetime import datetime, timezone
from pathlib import Path                         # DIAGNOSTIC CSV
from typing import Optional

import numpy as np

from config import settings, AUDIO_SHAPES_DIR
from models.state import SpotifyTrackInfo, state as app_state
from api.audio_capture import AudioCaptureStream
from services.audio_analyzer import load_audio_shape_meta

logger = logging.getLogger(__name__)

# ── Cross-correlation alignment ────────────────────────────────────────────────
_XCORR_FIRST_START_MS = 8_000    # first window starts at 8s — earlier sections
                                  # frequently misalign with stored shapes due to
                                  # mix variance / capture-time intro differences,
                                  # so both calibrators avoid the first 8s now.
_XCORR_END_BUFFER_MS  = 30_000   # stop 30s before song end
_XCORR_MARGIN_MS      = 1_000    # wait this far past window_end before computing
_XCORR_BIN_MS         = 25       # resample resolution (ms)
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


def _agc_normalize(arr: np.ndarray) -> np.ndarray:
    """Per-band AGC: divide by 95th percentile of |arr| so two windows captured
    at different volumes remain comparable. Symmetric on both sides of the
    correlation, so it never biases the winner; only stabilizes when SNR is
    asymmetric. Volume invariance is already mostly handled by the per-window
    z-score below — this is belt-and-suspenders for compressed dynamics.

    Uses `np.partition` for O(N) selection instead of `np.percentile`'s
    O(N log N) sort. Result is bit-identical to `np.percentile(..., 95)` for
    the integer index — no interpolation between adjacent percentiles, which
    is fine here since the AGC scale is then divided into a per-window
    z-score that absorbs any tiny offset.
    """
    if arr.size == 0:
        return arr
    n = arr.size
    k = min(n - 1, max(0, int(n * 0.95)))
    abs_arr = np.abs(arr)
    scale = float(np.partition(abs_arr, k)[k]) + 1e-6
    return arr / scale


def _signed_square(arr: np.ndarray) -> np.ndarray:
    # x → x·|x|: amplitude-weighted, sign-preserving. Loud excursions dominate
    # downstream Pearson r; quiet noise-floor wiggles contribute proportionally
    # less. Z-norm downstream still works (mean/std of squared values are valid).
    return arr * np.abs(arr)

# DIAGNOSTIC CSV ──────────────────────────────────────────────────────────────
_CSV_PATH = Path(__file__).resolve().parent.parent / "storage" / "xcorr_diagnostic.csv"
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
        p + "r_total", p + "r_low", p + "r_high",
        p + "peak_total", p + "peak_low", p + "peak_high",
        p + "old_r_avg",
    ]

_CSV_ALL_COLS = _CSV_SONG_COLS + [
    col for n in range(1, _CSV_MAX_WINDOWS + 1) for col in _csv_window_cols(n)
]


@_dataclass
class _XcorrDetail:
    """Per-band r at the winning shift and per-band independent peak shifts."""
    r_total: float
    r_low: float
    r_high: float
    peak_total_ms: int
    peak_low_ms: int
    peak_high_ms: int
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
        if (current_pos_ms < 1500
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
        capture.start()

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
        best_quality = -1.0
        # Seed best_offset with the stored offset for this slot so the post-loop
        # save defaults to "no change" if nothing convincingly displaces it.
        # (best_quality stays at -1.0 — we don't seed it, otherwise legitimate
        # corrections at lower Q than the historical lock could never displace.)
        _seed_meta = load_audio_shape_meta(uri)
        if _seed_meta is not None and app_state.active_setlist_id:
            _seed_entry = (_seed_meta.setlist_offsets or {}).get(app_state.active_setlist_id) or {}
            _seed_med = _median_offset(_seed_entry.get("history") or [])
            best_offset = _seed_med if _seed_med is not None else int(_seed_entry.get("timestamp_offset_ms", 0))
        else:
            best_offset = int(_seed_meta.timestamp_offset_ms or 0) if _seed_meta else 0
        best_difficulty = 0.0
        n_measurements = 0
        window_queue = list(windows)
        # (shift_ms, weight) pairs from windows where r >= xcorr_global_threshold.
        # Weight is the window's `difficulty` (intrinsic uniqueness); periodic
        # /repetitive windows weigh less than unique-feature windows. Both NEW
        # and OLD candidates are tracked when above threshold — even when a
        # candidate loses the per-window displacement gate, it still counts
        # toward cluster detection. Used by the post-loop save gate.
        confirmation_shifts: list[tuple[int, float]] = []
        # Per-window OLD r values — drives the "OLD is broken" detector that
        # bumps the Set List slot's anti_corr_count when the stored offset is
        # consistently anti-correlated this play.
        old_r_samples: list[float] = []
        # Anti-correlated baseline detector. After 3+ windows with OLD r<0 (the
        # stored offset is provably wrong for this play), relax downstream gates:
        # the cluster save threshold drops to xcorr_save_min_confirm_anti, and
        # apply_save bypasses the engine drift cap (the loaded baseline isn't
        # protecting anything).
        baseline_anti_corr = False
        _anti_neg_streak = 0
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

        try:
            async for frame in capture:
                if not app_state.current_track:
                    break
                frames.append((frame.timestamp_ms, frame.rms_total, frame.rms_low, frame.rms_mid, frame.rms_high))

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
                            confirmation_shifts.append(
                                (int(match.offset_ms), anchor_vote_weight)
                            )
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

                if not window_queue:
                    break
                win_start, win_end = window_queue[0]
                if frame.timestamp_ms < win_end + _XCORR_MARGIN_MS:
                    continue

                window_queue.pop(0)

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
                if old_r is not None:
                    old_quality = round(old_r * difficulty, 3)
                else:
                    old_r, old_quality = 0.0, 0.0
                old_r_samples.append(float(old_r))
                # Track consecutive negative-OLD-r windows. When this hits 3+,
                # the loaded baseline is provably wrong for this play and the
                # downstream gates relax to allow a corrective save.
                if old_r is not None and old_r < -0.05:
                    _anti_neg_streak += 1
                    if _anti_neg_streak >= 3 and not baseline_anti_corr:
                        baseline_anti_corr = True
                        logger.info(
                            "Auto-offset xcorr: baseline flagged anti-correlated for %s "
                            "(%d consecutive windows with OLD r<0) — relaxing save gates",
                            uri, _anti_neg_streak,
                        )
                else:
                    _anti_neg_streak = 0

                # ── NEW candidate: free-search xcorr (multi-band) ────────────
                # Run on a worker thread so the per-shift numpy sweep doesn't
                # block the asyncio event loop (which serves LedFX HTTP writes,
                # WebSocket broadcasts, and the trigger engine tick).
                new_result = await asyncio.to_thread(
                    _xcorr_window,
                    stored_ts, stored_bands, frames, win_start, win_end,
                    captured_duration_ms=int(meta.duration_ms or 0),
                    old_r=old_r,
                    tempo_bpm=tempo_bpm,
                )
                if new_result is not None:
                    new_offset_ms, new_r = new_result
                    new_quality = round(new_r * difficulty, 3)
                else:
                    new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

                # Round 9.5: envelope clip. Each window has a precomputed safe-
                # shift range — outside it, the matcher's peak likely landed on
                # a twin rather than the truth. Reject the NEW measurement when
                # it falls outside `engine_current ± envelope`. Skip the clip
                # during cold-start (engine has not snapped yet this play) so
                # a far-from-loaded truth can still be discovered.
                if new_result is not None:
                    try:
                        from main import engine as _engine_for_clip
                        _engine_current = _engine_for_clip._shape_offset_ms
                        _play_best = _engine_for_clip._play_best_quality
                    except Exception:
                        _engine_current = 0
                        _play_best = 0.0
                    if _play_best > 0.0:
                        env = envelope_lookup.get((win_start, win_end))
                        if env is not None:
                            _safe_neg, _safe_pos = env
                            _rel = new_offset_ms - _engine_current
                            if _rel < _safe_neg or _rel > _safe_pos:
                                logger.info(
                                    "xcorr reject: window [%d–%d]ms envelope clip — NEW %+dms "
                                    "(%+dms from engine %+dms) outside [%+d, %+d] for %s",
                                    win_start, win_end, new_offset_ms, _rel, _engine_current,
                                    _safe_neg, _safe_pos, uri,
                                )
                                new_result = None
                                new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

                # ── Pick winner for this window ───────────────────────────────
                # NEW must beat OLD's r by displacement_threshold to displace.
                # Threshold is stored_quality / 10 with a 1.5× bump for skip
                # plays (where song_start is slightly noisier), capped at 0.10
                # so a high stored Q (e.g. 0.85) can't make legitimate
                # corrections impossible. Earlier code used 3× for skip
                # uncapped → with stored_q=0.74 that meant 0.222, repeatedly
                # blocking NEW r>OLD r by 0.18-0.21 from displacing.
                stored_quality = stored_quality_for_old
                base_threshold = stored_quality / 10.0
                displacement_threshold = base_threshold * (1.5 if play_type == "skip" else 1.0)
                displacement_threshold = min(displacement_threshold, 0.10)
                # Round 8 — OLD-aware displacement floor. When OLD is positively
                # correlating (r ≥ xcorr_old_correlating_floor), the loaded
                # baseline is structurally agreeing with this window. A NEW
                # measurement at a DIFFERENT offset only deserves to displace
                # if it beats OLD by a wide margin — section-twins in periodic
                # music can score r=0.85-0.95 against the wrong alignment, and
                # without this floor they easily clear the small (≤0.10)
                # default threshold and override correct locks.
                old_floor = float(getattr(settings, "xcorr_old_correlating_floor", 0.50))
                if old_r >= old_floor:
                    old_margin = float(getattr(settings, "xcorr_old_correlating_margin", 0.20))
                    displacement_threshold = max(displacement_threshold, old_margin)
                if new_result is not None and new_r > old_r + displacement_threshold:
                    win_offset, win_quality, win_r, is_new = new_offset_ms, new_quality, new_r, True
                else:
                    win_offset, win_quality, win_r, is_new = stored_offset_ms, old_quality, old_r, False

                is_global_best = win_quality > best_quality
                if is_global_best:
                    best_quality   = win_quality
                    best_offset    = win_offset
                    best_difficulty = difficulty

                # Multi-window confirmation: record BOTH the per-window winner
                # AND any losing candidate that cleared the global threshold.
                # Tracking losing-NEW shifts is critical when the displacement
                # gate is conservative — without it, a NEW shift that appears
                # in two windows but loses the gate both times never registers
                # as a cluster, even though it's clearly a real signal.
                # Each entry is weighted by `difficulty` so periodic-tile peaks
                # (low diff) can't outvote a unique-feature peak (diff≈1.0).
                seen: set[int] = set()
                _prev_shifts_len = len(confirmation_shifts)  # round 9: snapshot for engine-snap stickiness gate
                if win_r >= settings.xcorr_global_threshold:
                    confirmation_shifts.append((win_offset, float(difficulty)))
                    seen.add(win_offset)
                if (new_result is not None
                        and new_r >= settings.xcorr_global_threshold
                        and new_offset_ms not in seen):
                    confirmation_shifts.append((new_offset_ms, float(difficulty)))
                    seen.add(new_offset_ms)
                if (old_r >= settings.xcorr_global_threshold
                        and stored_offset_ms not in seen):
                    confirmation_shifts.append((stored_offset_ms, float(difficulty)))

                n_measurements += 1

                # Live-frame snapshot for the Debug page. Trim to the most
                # recent ~30 s of frames so the snapshot stays small and the
                # diff visualization focuses on the section xcorr just
                # evaluated. List slicing is shallow-copy-safe — readers
                # iterate by value.
                self._frames_snapshot_uri = uri
                _snap_cutoff = max(0, win_end - 30000)
                self._frames_snapshot = [
                    f for f in frames if f[0] >= _snap_cutoff
                ]

                logger.info(
                    "Auto-offset xcorr: [%d–%d]ms  NEW %+dms r=%.2f Q=%.2f  "
                    "OLD %+dms r=%.2f Q=%.2f  diff=%.2f  thr=%.3f  winner=%s%s  for %s",
                    win_start, win_end,
                    new_offset_ms if new_result else 0, new_r, new_quality,
                    stored_offset_ms, old_r, old_quality,
                    difficulty, displacement_threshold,
                    "NEW" if is_new else "OLD",
                    " ← global best" if is_global_best else "",
                    uri,
                )

                try:
                    from services.websocket_manager import ws_manager
                    asyncio.create_task(ws_manager.broadcast({
                        "type":               "xcorr_window",
                        "uri":                uri,
                        "win_start":          win_start,
                        "win_end":            win_end,
                        "failed":             new_result is None and old_r == 0.0,
                        # NEW candidate
                        "new_offset_ms":      new_offset_ms if new_result else None,
                        "new_r":              round(new_r, 3) if new_result else None,
                        "new_quality":        new_quality if new_result else None,
                        # OLD candidate
                        "old_offset_ms":      stored_offset_ms,
                        "old_r":              round(old_r, 3),
                        "old_quality":        old_quality,
                        # Window info
                        "difficulty":         round(difficulty, 3),
                        "winner":             "new" if is_new else "old",
                        "applied":            is_global_best and verification != "user_verified",
                        # Legacy compatibility
                        "offset_ms":          win_offset,
                        "pearson_r":          round(win_r, 3),
                    }))
                except Exception:
                    pass

                # Engine snap (uncluttered): every high-r window also tries to
                # snap the live engine via apply_save. apply_save only takes
                # effect when its Q strictly beats the play-best, so a noisy
                # single window can't override a confident anchor or earlier
                # higher-Q window. This is what makes the Now Playing display
                # update mid-play even before a cluster has formed for disk.
                if (verification != "user_verified" and win_r >= settings.xcorr_global_threshold):
                    try:
                        from main import engine
                        # Round 9: stickiness gate. A single low-confidence window
                        # shouldn't yank the engine far from its current offset
                        # unless a prior window in this play already agreed with
                        # the new offset, the measurement is high-Q on its own,
                        # or this is a cold-start with anti-corr baseline (loaded
                        # median provably wrong). Compares NEW vs engine's *current*
                        # offset, not the loaded baseline.
                        engine_current = engine._shape_offset_ms
                        far_jump_ms = int(getattr(settings, "engine_snap_far_jump_ms", 1000))
                        displacement = abs(int(win_offset) - engine_current)
                        skip_snap = False
                        if displacement > far_jump_ms:
                            tol = int(getattr(settings, "xcorr_save_confirm_tol_ms", 300))
                            agreeing = sum(
                                1 for s, _w in confirmation_shifts[:_prev_shifts_len]
                                if abs(s - win_offset) <= tol
                            )
                            high_q_floor = float(getattr(settings, "engine_snap_far_jump_q", 0.85))
                            cold_start = engine._play_best_quality == 0.0
                            allow = (
                                agreeing >= 1
                                or win_quality >= high_q_floor
                                or (cold_start and baseline_anti_corr)
                            )
                            if not allow:
                                logger.info(
                                    "Engine: skip snap — far jump %+dms (Δ=%dms, Q=%.2f) without prior agreement for %s",
                                    int(win_offset), displacement, float(win_quality), uri,
                                )
                                skip_snap = True
                        if not skip_snap:
                            engine.apply_save(uri, int(win_offset), float(win_quality),
                                              source="sweep-window",
                                              bypass_drift_cap=baseline_anti_corr)
                    except Exception as exc:
                        logger.debug("Engine apply_save (window) failed: %s", exc)

                # Per-window DISK save: only fire when the winning shift has
                # been corroborated by another window within ±tol. Single-
                # window coincidences (typically: a weak/coarse early window
                # catching a fluke peak that scores higher than the historical
                # lock's *fresh* re-evaluation in the same weak window) no
                # longer overwrite a good stored baseline. The post-loop save
                # logic remains the final authority for cluster vs single-best.
                _save_confirm_tol = int(getattr(settings, "xcorr_save_confirm_tol_ms", 300))
                # Anti-correlated baseline halves-ish the confirmation requirement
                # (default 2.0 → 1.5) so a single sweep window plus the anchor's
                # weight (item 4) or just two weak windows can fire the save.
                if baseline_anti_corr:
                    _save_min_confirm = float(getattr(settings, "xcorr_save_min_confirm_anti", 1.5))
                else:
                    _save_min_confirm = float(getattr(settings, "xcorr_save_min_confirm", 2))
                _agree_now = sum(
                    w for s, w in confirmation_shifts
                    if abs(s - best_offset) <= _save_confirm_tol
                )
                # Single-window high-r escape hatch. With the squared-signal
                # correlator + beat-twin gate, an r ≥ xcorr_single_window_save_r
                # measurement is hard for false matches to reach. Allow it to
                # save without the cluster confirmation when its quality is also
                # strong enough — this rescues songs where the lone good window
                # was the right answer but no second window confirmed it.
                #
                # Round 8: tier the threshold by distance from the sweep's
                # current best offset (i.e. the engine's converged lock for
                # this play). Local refinements stay easy; far jumps require
                # much stronger evidence. Cluster confirmation can still
                # displace anything regardless of distance.
                _single_save_r = float(getattr(settings, "xcorr_single_window_save_r", 0.78))
                _single_save_q = float(getattr(settings, "xcorr_single_window_save_q", 0.70))
                _single_save_far_r = float(getattr(settings, "xcorr_single_window_save_far_r", 0.90))
                _single_save_far_q = float(getattr(settings, "xcorr_single_window_save_far_q", 0.85))
                _far_jump_ms = int(getattr(settings, "xcorr_far_jump_ms", 1000))
                # Distance from the sweep's current converged offset. When
                # best_quality is still 0 (no prior cluster this play),
                # treat as "near" so the first window can save normally.
                if best_quality > 0.5:
                    is_far_jump = abs(win_offset - best_offset) > _far_jump_ms
                else:
                    is_far_jump = False
                if is_far_jump:
                    eff_r = _single_save_far_r
                    eff_q = _single_save_far_q
                else:
                    eff_r = _single_save_r
                    eff_q = _single_save_q
                if (is_global_best
                        and verification != "user_verified"
                        and _agree_now >= _save_min_confirm):
                    _save_offset(uri, best_offset, best_quality,
                                 bypass_drift_cap=baseline_anti_corr)
                elif (is_global_best and verification != "user_verified"
                        and win_r >= eff_r and win_quality >= eff_q):
                    tag = "far-jump" if is_far_jump else "near"
                    logger.info(
                        "Auto-offset xcorr: SAVING single-window high-r [%s] — %+dms r=%.2f Q=%.2f (cluster %.2f<%.1f, but r≥%.2f & Q≥%.2f)",
                        tag, win_offset, win_r, win_quality, _agree_now, _save_min_confirm,
                        eff_r, eff_q,
                    )
                    _save_offset(uri, win_offset, win_quality, source="sweep-single",
                                 bypass_drift_cap=baseline_anti_corr)
                elif is_global_best and verification != "user_verified":
                    logger.info(
                        "Auto-offset xcorr: per-window save deferred — %+dms only weighted=%.2f/%.1f within ±%dms (r=%.2f<%.2f or Q=%.2f<%.2f for single-win)",
                        best_offset, _agree_now, _save_min_confirm, _save_confirm_tol,
                        win_r, _single_save_r, win_quality, _single_save_q,
                    )

                # DIAGNOSTIC CSV ──────────────────────────────────────────
                if settings.xcorr_csv_logging:
                    _detail = await asyncio.to_thread(
                        _xcorr_window_detail,
                        stored_ts, stored_bands, frames,
                        win_start, win_end,
                        -win_offset,                          # winning_shift
                        int(meta.duration_ms or 0),           # captured_duration_ms
                    )
                    _csv_window_rows.append({
                        "start_ms":   win_start,
                        "difficulty": round(difficulty, 4),
                        "winner":     "new" if is_new else "old",
                        "offset_ms":  win_offset,
                        "quality":    win_quality,
                        "r_avg":      round(win_r, 4),
                        "r_total":    _detail.r_total,
                        "r_low":      _detail.r_low,
                        "r_high":     _detail.r_high,
                        "peak_total": _detail.peak_total_ms,
                        "peak_low":   _detail.peak_low_ms,
                        "peak_high":  _detail.peak_high_ms,
                        "old_r_avg":  round(old_r, 4),
                    })
                # END DIAGNOSTIC CSV ──────────────────────────────────────

                # Lock-and-stop: once the engine has snapped at high Q AND
                # multiple windows agree on the offset, the marginal value of
                # the trailing windows is nil — halt the rest of this play's
                # xcorr loop so worker-thread CPU isn't burned on diminishing
                # returns. Disk-save logic continues working off whatever
                # offset the engine has locked.
                _lock_q = float(getattr(settings, "xcorr_lock_q", 0.75))
                _lock_agree = int(getattr(settings, "xcorr_lock_agree_windows", 3))
                try:
                    from main import engine as _engine_for_lock
                    if (_engine_for_lock._play_best_quality >= _lock_q
                            and _agree_now >= _lock_agree):
                        logger.info(
                            "Auto-offset xcorr: lock-and-stop at Q=%.2f after %.1f agreeing weight (≥%d) for %s",
                            _engine_for_lock._play_best_quality, _agree_now, _lock_agree, uri,
                        )
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

        if n_measurements == 0:
            logger.info("Auto-offset xcorr: no measurements obtained for %s", uri)
            self._watching_uri = None
            self._task = None
            return

        logger.info(
            "Auto-offset xcorr: final offset=%+dms Q=%.2f diff=%.2f "
            "from %d window(s) for %s",
            best_offset, best_quality, best_difficulty, n_measurements, uri,
        )

        # ── OLD-anti-correlated detector ───────────────────────────────────
        # When a majority of windows (with non-trivial OLD samples) showed the
        # stored offset as anti-correlated, the stored baseline doesn't fit
        # this play. Bump anti_corr_count on the Set List slot so the UI can
        # surface drifting songs. Reset on any "well-correlated" play.
        try:
            if app_state.active_setlist_id and old_r_samples:
                meaningful = [r for r in old_r_samples if abs(r) > 0.05]
                neg_count  = sum(1 for r in meaningful if r < -0.10)
                if meaningful:
                    is_drifting = neg_count >= max(2, len(meaningful) // 2)
                    _bump_anti_corr_count(uri, app_state.active_setlist_id, is_drifting)
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
                    "offset_ms": best_offset,
                    "quality": round(best_quality, 3),
                    "window_count": n_measurements,
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
                "offset_ms":      best_offset,
                "quality_score":  best_quality,
                "difficulty":     round(best_difficulty, 3),
                "n_measurements": n_measurements,
                "saved":          verification != "user_verified",
                "prev_offset_ms": prev_offset_ms,
                "play_type":      play_type,
            }))
        except Exception:
            pass

        # DIAGNOSTIC CSV ──────────────────────────────────────────────────
        if settings.xcorr_csv_logging and n_measurements > 0:
            _write_csv_row(
                track=app_state.current_track, uri=uri,
                final_offset=best_offset, final_quality=best_quality,
                n_windows=n_measurements, prev_offset=prev_offset_ms,
                window_rows=_csv_window_rows,
                play_type=play_type,
            )
        # END DIAGNOSTIC CSV ──────────────────────────────────────────────

        if verification == "user_verified":
            logger.info(
                "Auto-offset xcorr: user_verified — NOT saving "
                "(measured=%+dms Q=%.2f, stored offset unchanged)",
                best_offset, best_quality,
            )
        else:
            # Save guard: don't pollute the stored offset with weak or
            # one-window-only measurements. A real lock should clear the
            # global threshold AND be confirmed by at least one other window
            # with a winning shift within ±300ms.
            #
            # The single-best-Q heuristic (best_offset) can pick a window
            # whose Q happens to be highest while another shift had more
            # *agreement* across windows. So we cluster confirmation_shifts
            # within ±tol and prefer the most-agreed cluster when it beats
            # best_offset's agreement count.
            min_save_q  = float(getattr(settings, "xcorr_save_min_quality", 0.50))
            confirm_tol = int(getattr(settings, "xcorr_save_confirm_tol_ms", 300))
            # `min_confirm` is now a SUM of window difficulties (a "weight")
            # rather than an integer window count. With diff=1.0 windows each
            # contributing 1.0, the default 2.0 still means "at least two
            # unique-feature windows agree." Periodic-tile windows (diff~0.6)
            # need 4+ agreements to clear the same bar, which suppresses
            # spurious clusters from looped musical content.
            # Anti-correlated baselines get a relaxed cluster threshold so the
            # song can recover from a wrong stored median.
            if baseline_anti_corr:
                min_confirm = float(getattr(settings, "xcorr_save_min_confirm_anti", 1.5))
            else:
                min_confirm = float(getattr(settings, "xcorr_save_min_confirm", 2))

            def _agree_weight(target: int) -> float:
                return sum(w for s, w in confirmation_shifts if abs(s - target) <= confirm_tol)

            # Tally clusters: each unique shift becomes a cluster centre,
            # collect its members, score by sum of difficulty weights.
            cluster_weights: dict[int, float] = {}
            for s, _w in confirmation_shifts:
                cluster_weights[s] = _agree_weight(s)
            best_cluster_centre = max(cluster_weights, key=cluster_weights.get) if cluster_weights else best_offset
            best_cluster_weight = cluster_weights.get(best_cluster_centre, 0.0)
            best_offset_agree   = _agree_weight(best_offset)

            # Prefer cluster centre when its weighted agreement strictly beats
            # the single-best-Q offset's. Periodic-tile false clusters (low
            # diff each) can no longer outvote a unique-feature single window.
            if best_cluster_weight > best_offset_agree and best_cluster_weight >= min_confirm:
                cluster_members = [s for s, _w in confirmation_shifts if abs(s - best_cluster_centre) <= confirm_tol]
                save_offset = int(round(sum(cluster_members) / len(cluster_members)))
                save_quality = best_quality
                logger.info(
                    "Auto-offset xcorr: cluster override — saving %+dms (cluster weight=%.2f) "
                    "instead of single-best %+dms (weight=%.2f)",
                    save_offset, best_cluster_weight, best_offset, best_offset_agree,
                )
            else:
                save_offset = best_offset
                save_quality = best_quality

            agree = _agree_weight(save_offset)

            if save_quality < min_save_q:
                logger.info(
                    "Auto-offset xcorr: NOT saving — best Q=%.2f < min %.2f "
                    "(measured=%+dms, stored offset unchanged)",
                    save_quality, min_save_q, save_offset,
                )
            elif agree < min_confirm:
                logger.info(
                    "Auto-offset xcorr: NOT saving — weighted %.2f confirmed "
                    "%+dms within ±%dms (need %.1f) "
                    "(measured Q=%.2f, stored offset unchanged)",
                    agree, save_offset, confirm_tol, min_confirm, save_quality,
                )
            else:
                _save_offset(uri, save_offset, save_quality,
                             bypass_drift_cap=baseline_anti_corr)

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


def _difficulty_score(window_rms: np.ndarray, song_rms: np.ndarray) -> float:
    """
    How much dynamic content is in this window, normalised 0–1.
    Uses coefficient of variation (std/mean) of the window vs. the song-global CV.
    A flat/silent section → 0 (unreliable for alignment).
    A window as dynamic as the whole song → 1.
    A window more dynamic than average → capped at 1.
    """
    if len(window_rms) < 2:
        return 0.0
    w_mean = float(window_rms.mean())
    if w_mean < 1e-9:
        return 0.0
    cv_window = float(window_rms.std()) / w_mean

    g_mean = float(song_rms.mean())
    if g_mean < 1e-9:
        return 0.0
    cv_global = float(song_rms.std()) / g_mean
    if cv_global < 1e-9:
        return 0.0

    return float(min(1.0, cv_window / cv_global))


def _eval_at_shift(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    shift_ms: int,
) -> Optional[float]:
    """
    Evaluate multi-band Pearson r at a SPECIFIC shift (no search).
    shift_ms > 0 means the live signal is tested shifted right by shift_ms.
    Returns simple-mean correlation across all 4 bands, or None if all flat.

    stored_bands: [rms_total, rms_low, rms_mid, rms_high] arrays from npz.
    frames: [(ts, rms_total, rms_low, rms_mid, rms_high), ...] from live capture.

    Round 5 reverted from variance-weighted combine to a simple mean: each
    band gets equal vote. Forces all 4 bands (including melody-carrying mid)
    to agree, which makes beat-tile twins much harder to fool the matcher
    than when one high-variance band (typically rms_high during repetitive
    hi-hat patterns) dominated the score.
    """
    bins = np.arange(win_start, win_end, _XCORR_BIN_MS, dtype=float)
    live_ts = np.array([f[0] for f in frames], dtype=float)
    live_bins = bins + shift_ms

    r_values: list[float] = []
    for band_idx in range(len(stored_bands)):
        template = _agc_normalize(np.interp(bins, stored_ts, stored_bands[band_idx]))
        if template.std() < 1e-6:
            continue
        template_norm = (template - template.mean()) / template.std()

        live_rms = _signed_square(
            np.array([f[1 + band_idx] for f in frames], dtype=float)
        )
        signal = _agc_normalize(np.interp(live_bins, live_ts, live_rms, left=0.0, right=0.0))
        if signal.std() < 1e-6:
            continue
        signal_norm = (signal - signal.mean()) / signal.std()
        r_values.append(float(np.dot(template_norm, signal_norm)) / len(bins))

    if not r_values:
        return None
    return sum(r_values) / len(r_values)


def _xcorr_window(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    captured_duration_ms: int = 0,
    old_r: Optional[float] = None,
    tempo_bpm: Optional[float] = None,
) -> Optional[tuple[int, float]]:
    """
    Multi-band cross-correlation of stored shape window against live audio.
    Returns (offset_ms, avg_pearson_r) or None if below threshold.

    Coarse-then-fine sweep:
      1. Coarse: step xcorr_coarse_step_ms across the full ±search range,
         keep top-K candidates by averaged r.
      2. Fine: refine each candidate with ±150 ms at _XCORR_BIN_MS resolution.
         Keep the global best.

    The search range itself is mix-aware (derived from captured vs polled
    duration plus a buffer). When the range is wide, an adaptive threshold
    rejects ambiguous matches.

    Sign convention: offset_ms = -best_shift
      shift > 0  →  live is LATE by |shift| ms  →  offset < 0  →  fires later  ✓
    """
    bins = np.arange(win_start, win_end, _XCORR_BIN_MS, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    # band_info: (band_idx, template_norm). Round 5 reverted from variance-
    # weighted to simple-mean band combine, so per-band variance is no longer
    # tracked — each of the 4 bands gets equal vote in score_at.
    band_info: list[tuple[int, np.ndarray]] = []
    for band_idx, stored_rms in enumerate(stored_bands):
        template = _agc_normalize(np.interp(bins, stored_ts, stored_rms))
        if template.std() < 1e-6:
            continue
        band_info.append((band_idx, (template - template.mean()) / template.std()))
    if not band_info:
        return None

    live_arrays: dict[int, np.ndarray] = {}
    for band_idx, _ in band_info:
        live_arrays[band_idx] = _agc_normalize(
            _signed_square(np.array([f[1 + band_idx] for f in frames], dtype=float))
        )

    search_ms   = _xcorr_search_ms(captured_duration_ms)
    coarse_step = max(_XCORR_BIN_MS, settings.xcorr_coarse_step_ms)

    # Pre-resample live signals onto a fine grid covering the full search range.
    # Coarse + fine shifts are integer multiples of _XCORR_BIN_MS, so per-shift
    # signal extraction reduces to integer slicing — no per-shift np.interp.
    # That eliminates 720+ interp calls per window (was the dominant cost).
    grid_start = win_start - search_ms
    grid_end   = win_end   + search_ms + _XCORR_BIN_MS
    grid_ts    = np.arange(grid_start, grid_end, _XCORR_BIN_MS, dtype=float)
    n_grid     = len(grid_ts)
    live_grid: dict[int, np.ndarray] = {}
    for band_idx, _ in band_info:
        live_grid[band_idx] = np.interp(
            grid_ts, live_ts, live_arrays[band_idx], left=0.0, right=0.0
        )
    # Anchor: bins[0] sits at this index in the grid; shift adds shift/_XCORR_BIN_MS bins.
    base_idx_at_zero = int(round((win_start - grid_start) / _XCORR_BIN_MS))

    def score_at(shift: int) -> Optional[float]:
        offset = base_idx_at_zero + int(shift // _XCORR_BIN_MS)
        # Out-of-range shifts shouldn't happen (grid sized for ±search_ms) but
        # guard defensively to avoid a numpy slice that silently underfills.
        if offset < 0 or offset + n_bins > n_grid:
            return None
        r_sum = 0.0
        n_valid = 0
        for band_idx, template_norm in band_info:
            signal = live_grid[band_idx][offset : offset + n_bins]
            if signal.std() < 1e-6:
                continue
            signal_norm = (signal - signal.mean()) / signal.std()
            r_sum += float(np.dot(template_norm, signal_norm)) / n_bins
            n_valid += 1
        return (r_sum / n_valid) if n_valid else None

    # ── Coarse pass ──────────────────────────────────────────────────────────
    coarse_results: list[tuple[float, int]] = []
    for shift in range(-search_ms, search_ms + 1, coarse_step):
        r = score_at(shift)
        if r is not None:
            coarse_results.append((r, shift))
    if not coarse_results:
        return None
    coarse_results.sort(reverse=True)  # by r desc
    top_k = max(1, settings.xcorr_top_k_refine)
    candidates = coarse_results[:top_k]

    # ── Fine pass (refine each top-K) ────────────────────────────────────────
    fine_radius = 150
    best_r, best_shift = -float("inf"), 0
    second_r = -float("inf")
    for _, c_shift in candidates:
        for shift in range(c_shift - fine_radius, c_shift + fine_radius + 1, _XCORR_BIN_MS):
            r = score_at(shift)
            if r is None:
                continue
            if r > best_r:
                second_r = best_r
                best_r, best_shift = r, shift
            elif r > second_r:
                second_r = r

    if best_r == -float("inf"):
        return None

    # Adaptive thresholds for wide searches.
    threshold = settings.xcorr_global_threshold
    require_margin = 0.0
    if search_ms > settings.xcorr_wide_threshold_ms:
        threshold = max(threshold, settings.xcorr_wide_min_r)
        require_margin = settings.xcorr_wide_top1_margin

    if best_r < threshold:
        logger.info(
            "xcorr reject: window [%d–%d]ms best r=%.2f below threshold %.2f (search=±%dms)",
            win_start, win_end, best_r, threshold, search_ms,
        )
        return None
    # Margin check is skipped in two cases:
    #   1. top1 is itself high-confidence (xcorr_high_confidence_r) — strong
    #      enough on its own, twin peaks just reflect periodic music.
    #   2. OLD baseline is provably wrong (anti-correlated, r<0) — any peak
    #      that cleared `threshold` is better than what we have. The
    #      multi-window save gate will refuse to persist this until another
    #      window agrees, so letting the measurement through is safe.
    if (require_margin > 0 and second_r > -float("inf")
            and best_r < settings.xcorr_high_confidence_r
            and (old_r is None or old_r >= 0.0)
            and (best_r - second_r) < require_margin):
        logger.info(
            "xcorr reject: window [%d–%d]ms ambiguous — top1=%.2f top2=%.2f margin<%.2f (search=±%dms)",
            win_start, win_end, best_r, second_r, require_margin, search_ms,
        )
        return None

    # Beat-twin rejection. When tempo is known, explicitly score the same
    # template at best_shift ± n*beat_period for n ∈ {1, 2, 3, 4}. A periodic
    # passage's beat-tile twin matches strongly there; if any twin's r is
    # within `xcorr_beat_twin_margin` of best_r, the window is genuinely
    # ambiguous between two beat-aligned offsets and we should fall back to
    # OLD rather than commit to the wrong tile. Mirrors the anchor's
    # beat-twin penalty so both calibrators agree on what counts as
    # ambiguous in periodic music.
    if tempo_bpm and tempo_bpm > 0 and best_r < settings.xcorr_high_confidence_r:
        beat_period_ms = 60_000.0 / float(tempo_bpm)
        twin_margin = float(getattr(settings, "xcorr_beat_twin_margin", 0.10))
        for n in (1, 2, 3, 4):
            for sign in (-1, 1):
                twin_shift = best_shift + sign * int(round(n * beat_period_ms))
                if abs(twin_shift) > search_ms:
                    continue
                twin_r = score_at(twin_shift)
                if twin_r is None:
                    continue
                if best_r - twin_r < twin_margin:
                    logger.info(
                        "xcorr reject: window [%d–%d]ms beat-twin — best=%.2f at %+dms vs twin=%.2f at %+dms (%+d beats, margin<%.2f)",
                        win_start, win_end, best_r, best_shift,
                        twin_r, twin_shift, sign * n, twin_margin,
                    )
                    return None

    return (-best_shift, round(best_r, 3))


# DIAGNOSTIC CSV ──────────────────────────────────────────────────────────────
def _xcorr_window_detail(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float, float]],
    win_start: int,
    win_end: int,
    winning_shift: int,
    captured_duration_ms: int = 0,
) -> _XcorrDetail:
    """
    Compute per-band r at the winning shift and per-band independent peak shifts.
    Only called when xcorr_csv_logging is True.

    winning_shift: raw shift in ms (positive = live is late).
                   Pass -offset_ms to convert from offset sign convention.
    """
    bins   = np.arange(win_start, win_end, _XCORR_BIN_MS, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    per_band_r:    list[float] = []
    per_band_peak: list[int]   = []

    for band_idx in range(3):
        template = np.interp(bins, stored_ts, stored_bands[band_idx])
        if template.std() < 1e-6:
            per_band_r.append(0.0)
            per_band_peak.append(0)
            continue
        template_norm = (template - template.mean()) / template.std()

        live_rms = np.array([f[1 + band_idx] for f in frames], dtype=float)

        # r at the winning shift
        signal = np.interp(bins + winning_shift, live_ts, live_rms, left=0.0, right=0.0)
        if signal.std() < 1e-6:
            per_band_r.append(0.0)
        else:
            signal_norm = (signal - signal.mean()) / signal.std()
            per_band_r.append(round(float(np.dot(template_norm, signal_norm)) / n_bins, 4))

        # independent peak for this band alone
        best_r     = -np.inf
        best_shift = 0
        _detail_search = _xcorr_search_ms(captured_duration_ms)
        for shift in range(-_detail_search, _detail_search + 1, _XCORR_BIN_MS):
            sig = np.interp(bins + shift, live_ts, live_rms, left=0.0, right=0.0)
            if sig.std() < 1e-6:
                continue
            sn = (sig - sig.mean()) / sig.std()
            r  = float(np.dot(template_norm, sn)) / n_bins
            if r > best_r:
                best_r     = r
                best_shift = shift
        per_band_peak.append(-best_shift)  # shift → offset sign convention

    return _XcorrDetail(
        r_total=per_band_r[0], r_low=per_band_r[1], r_high=per_band_r[2],
        peak_total_ms=per_band_peak[0], peak_low_ms=per_band_peak[1], peak_high_ms=per_band_peak[2],
    )
# END DIAGNOSTIC CSV ──────────────────────────────────────────────────────────


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
            row[p + "r_high"]     = w["r_high"]
            row[p + "peak_total"] = w["peak_total"]
            row[p + "peak_low"]   = w["peak_low"]
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
        meta.setlist_offsets[sl_id] = {
            **prev,                                          # preserve perception_trim_ms, anti_corr_count, etc
            "timestamp_offset_ms": int(offset_ms),
            "offset_quality": round(quality, 3),
            "generated_at": now_iso,
            "observed_cut_ms": int(cut_ms),
            "history": history,
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
