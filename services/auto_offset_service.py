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
_XCORR_FIRST_START_MS = 5_000    # first window starts at 5s
_XCORR_END_BUFFER_MS  = 30_000   # stop 30s before song end
_XCORR_MARGIN_MS      = 1_000    # wait this far past window_end before computing
_XCORR_SEARCH_MS      = 2_000    # search range ±ms around each window
_XCORR_BIN_MS         = 25       # resample resolution (ms)
_XCORR_CANDIDATE_STEP = 500     # step size for candidate window positions (ms)

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

    def get_status(self, uri: str) -> dict:
        """Return whether xcorr calibration is currently active for a URI."""
        return {"active": self._watching_uri == uri}

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

        # Already watching this song
        if self._watching_uri == new_uri:
            return

        # Run for any song with a complete shape (including auto_verified).
        # user_verified: still run for logging; _detect_loop_xcorr won't save.
        meta = load_audio_shape_meta(new_uri)
        if meta is None or not meta.capture_complete:
            return

        current_pos_ms = track.interpolated_progress_ms()

        # Get smart windows (cached or freshly computed)
        all_windows = self._get_or_compute_windows(new_uri, meta)
        # Build difficulty lookup from cached window data
        diff_lookup = {(w["start_ms"], w["end_ms"]): w.get("difficulty", 0)
                       for w in (meta.xcorr_windows or [])}
        # Filter to only windows we can still reach
        windows = [(s, e) for s, e in all_windows if current_pos_ms < s]

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
        """Return smart xcorr windows, using cache if valid or computing fresh."""
        npz_path = AUDIO_SHAPES_DIR / meta.npz_file
        try:
            npz_mtime = os.path.getmtime(npz_path)
        except OSError:
            npz_mtime = 0

        params_hash = _compute_params_hash(npz_mtime)

        # Check cache
        if meta.xcorr_windows and meta.xcorr_params_hash == params_hash:
            windows = [(w["start_ms"], w["end_ms"]) for w in meta.xcorr_windows]
            logger.info("Auto-offset xcorr: using %d cached windows for %s", len(windows), uri)
            return windows

        # Compute fresh
        try:
            data = np.load(npz_path)
            stored_ts = data["timestamps_ms"].astype(float)
            stored_rms = data["rms_low"]
        except Exception as exc:
            logger.warning("Auto-offset xcorr: failed to load npz for window planning: %s", exc)
            return []

        planned = _plan_xcorr_windows(stored_ts, stored_rms, meta.duration_ms)
        windows = [(w["start_ms"], w["end_ms"]) for w in planned]

        # Save to sidecar
        meta.xcorr_windows = planned
        meta.xcorr_params_hash = params_hash
        meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
        try:
            meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
            logger.info(
                "Auto-offset xcorr: planned %d smart windows (saved to sidecar) for %s",
                len(planned), uri,
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
            stored_bands = [data["rms_total"], data["rms_low"], data["rms_high"]]
            stored_rms = data["rms_low"]  # kept for difficulty scoring
        except Exception as exc:
            logger.warning("Auto-offset xcorr: failed to load npz for %s: %s", uri, exc)
            capture.stop()
            return

        # Each frame: (timestamp_ms, rms_total, rms_low, rms_high) — 3 bands for multi-band xcorr
        frames: list[tuple[int, float, float, float]] = []
        _csv_window_rows: list[dict] = []   # DIAGNOSTIC CSV
        best_quality = -1.0
        best_offset  = 0
        best_difficulty = 0.0
        n_measurements = 0
        window_queue = list(windows)

        try:
            async for frame in capture:
                if not app_state.current_track:
                    break
                frames.append((frame.timestamp_ms, frame.rms_total, frame.rms_low, frame.rms_high))

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

                # ── NEW candidate: free-search xcorr (multi-band) ────────────
                new_result = _xcorr_window(stored_ts, stored_bands, frames, win_start, win_end)
                if new_result is not None:
                    new_offset_ms, new_r = new_result
                    new_quality = round(new_r * difficulty, 3)
                else:
                    new_offset_ms, new_r, new_quality = 0, 0.0, 0.0

                # ── OLD candidate: evaluate stored offset ─────────────────────
                # Re-read meta so we always compare against the CURRENT stored offset
                cur_meta = load_audio_shape_meta(uri)
                stored_offset_ms = cur_meta.timestamp_offset_ms if cur_meta else 0
                old_r = _eval_at_shift(
                    stored_ts, stored_bands, frames, win_start, win_end,
                    shift_ms=-stored_offset_ms,
                )
                if old_r is not None:
                    old_quality = round(old_r * difficulty, 3)
                else:
                    old_r, old_quality = 0.0, 0.0

                # ── Pick winner for this window ───────────────────────────────
                # Compare r-values directly. NEW must beat OLD's r by at least
                # (stored_quality / 10) — the better the stored offset's historical
                # quality, the larger the margin NEW needs to displace it.
                stored_quality = cur_meta.offset_quality if cur_meta else 0.0
                base_threshold = stored_quality / 10.0
                # Skips have unreliable song_start → require 3x margin to displace
                displacement_threshold = base_threshold * (3.0 if play_type == "skip" else 1.0)
                if new_result is not None and new_r > old_r + displacement_threshold:
                    win_offset, win_quality, win_r, is_new = new_offset_ms, new_quality, new_r, True
                else:
                    win_offset, win_quality, win_r, is_new = stored_offset_ms, old_quality, old_r, False

                is_global_best = win_quality > best_quality
                if is_global_best:
                    best_quality   = win_quality
                    best_offset    = win_offset
                    best_difficulty = difficulty

                n_measurements += 1

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

                if is_global_best and verification != "user_verified":
                    _save_offset(uri, best_offset, best_quality)

                # DIAGNOSTIC CSV ──────────────────────────────────────────
                if settings.xcorr_csv_logging:
                    _detail = _xcorr_window_detail(
                        stored_ts, stored_bands, frames,
                        win_start, win_end,
                        winning_shift=-win_offset,
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
            _save_offset(uri, best_offset, best_quality)

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
        f"{s.xcorr_max_windows}:{s.xcorr_min_early_windows}:{npz_mtime}"
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
    candidates: list[dict] = []
    pos = min_start
    while pos + win_size <= max_end:
        bins = np.arange(pos, pos + win_size, _XCORR_BIN_MS, dtype=float)
        window_rms = np.interp(bins, stored_ts, stored_rms)
        diff = _difficulty_score(window_rms, stored_rms)
        candidates.append({"start_ms": pos, "end_ms": pos + win_size, "difficulty": round(diff, 4)})
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
        "Auto-offset xcorr: planned %d windows (difficulties: %s)",
        len(selected),
        ", ".join(f"{w['difficulty']:.2f}" for w in selected),
    )
    return selected


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
    frames: list[tuple[int, float, float, float]],
    win_start: int,
    win_end: int,
    shift_ms: int,
) -> Optional[float]:
    """
    Evaluate multi-band Pearson r at a SPECIFIC shift (no search).
    shift_ms > 0 means the live signal is tested shifted right by shift_ms.
    Returns average correlation coefficient across bands, or None if all flat.

    stored_bands: [rms_total, rms_low, rms_high] arrays from npz.
    frames: [(ts, rms_total, rms_low, rms_high), ...] from live capture.
    """
    bins = np.arange(win_start, win_end, _XCORR_BIN_MS, dtype=float)
    live_ts = np.array([f[0] for f in frames], dtype=float)
    live_bins = bins + shift_ms

    r_values: list[float] = []
    for band_idx in range(len(stored_bands)):
        template = np.interp(bins, stored_ts, stored_bands[band_idx])
        if template.std() < 1e-6:
            continue
        template_norm = (template - template.mean()) / template.std()

        live_rms = np.array([f[1 + band_idx] for f in frames], dtype=float)
        signal = np.interp(live_bins, live_ts, live_rms, left=0.0, right=0.0)
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
    frames: list[tuple[int, float, float, float]],
    win_start: int,
    win_end: int,
) -> Optional[tuple[int, float]]:
    """
    Multi-band cross-correlation of stored shape window against live audio.
    Returns (offset_ms, avg_pearson_r) or None if below threshold.

    Computes Pearson r for each band (rms_total, rms_low, rms_high) at every
    candidate shift, averages across bands, then picks the shift with best avg r.
    This breaks beat-shift ambiguity because mid/high content (vocals, melody)
    doesn't repeat on the same cycle as bass.

    stored_bands: [rms_total, rms_low, rms_high] arrays from npz.
    frames: [(ts, rms_total, rms_low, rms_high), ...] from live capture.

    Sign convention: offset_ms = -best_shift
      shift > 0  →  live is LATE by |shift| ms  →  offset < 0  →  fires later  ✓
    """
    bins = np.arange(win_start, win_end, _XCORR_BIN_MS, dtype=float)
    n_bins = len(bins)
    live_ts = np.array([f[0] for f in frames], dtype=float)

    # Pre-compute normalised templates per band (skip flat bands)
    band_info: list[tuple[int, np.ndarray]] = []  # (band_idx, template_norm)
    for band_idx, stored_rms in enumerate(stored_bands):
        template = np.interp(bins, stored_ts, stored_rms)
        if template.std() < 1e-6:
            continue
        band_info.append((band_idx, (template - template.mean()) / template.std()))

    if not band_info:
        return None

    # Pre-extract live RMS arrays per band
    live_arrays: dict[int, np.ndarray] = {}
    for band_idx, _ in band_info:
        live_arrays[band_idx] = np.array([f[1 + band_idx] for f in frames], dtype=float)

    best_corr  = -np.inf
    best_shift = 0
    for shift in range(-_XCORR_SEARCH_MS, _XCORR_SEARCH_MS + 1, _XCORR_BIN_MS):
        live_bins = bins + shift
        r_sum = 0.0
        n_valid = 0
        for band_idx, template_norm in band_info:
            signal = np.interp(live_bins, live_ts, live_arrays[band_idx], left=0.0, right=0.0)
            if signal.std() < 1e-6:
                continue
            signal_norm = (signal - signal.mean()) / signal.std()
            r_sum += float(np.dot(template_norm, signal_norm)) / n_bins
            n_valid += 1
        if n_valid == 0:
            continue
        avg_r = r_sum / n_valid
        if avg_r > best_corr:
            best_corr  = avg_r
            best_shift = shift

    if best_corr < settings.xcorr_global_threshold:
        logger.debug(
            "Auto-offset xcorr: window [%d–%d]ms best r=%.2f below threshold %.2f",
            win_start, win_end, best_corr, settings.xcorr_global_threshold,
        )
        return None

    return (-best_shift, round(best_corr, 3))


# DIAGNOSTIC CSV ──────────────────────────────────────────────────────────────
def _xcorr_window_detail(
    stored_ts: np.ndarray,
    stored_bands: list[np.ndarray],
    frames: list[tuple[int, float, float, float]],
    win_start: int,
    win_end: int,
    winning_shift: int,
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
        for shift in range(-_XCORR_SEARCH_MS, _XCORR_SEARCH_MS + 1, _XCORR_BIN_MS):
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


def _save_offset(uri: str, offset_ms: int, quality: float = 0.0) -> None:
    """Persist offset + quality score, mark as auto_verified, hot-reload trigger engine."""
    meta = load_audio_shape_meta(uri)
    if meta is None:
        return
    meta.timestamp_offset_ms = offset_ms
    meta.offset_quality = round(quality, 3)
    meta.offset_verification = "auto_verified"
    meta_path = AUDIO_SHAPES_DIR / meta.npz_file.replace(".npz", ".json")
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    # Hot-reload in the trigger engine so offset takes effect without song change
    try:
        from main import engine
        engine.reload_shape_offset(uri)
    except Exception as exc:
        logger.warning("Auto-offset: could not hot-reload trigger engine offset: %s", exc)

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
