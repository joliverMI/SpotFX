"""
SpotFX — Audio shape capture lifecycle manager.

Starts an AudioCaptureStream when a new song plays (and no shape exists yet),
feeds frames into AudioShapeRecorder, then on song change saves the .npz,
runs MusicMarkDetector, and writes the marks into the sidecar JSON.
"""
from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

from config import AUDIO_SHAPES_DIR
from models.state import SpotifyTrackInfo
from api.audio_capture import AudioCaptureStream
from services.audio_analyzer import AudioShapeRecorder, MusicMarkDetector, load_audio_shape_meta

logger = logging.getLogger(__name__)


class AudioShapeService:
    def __init__(self) -> None:
        self._recorder: Optional[AudioShapeRecorder] = None
        self._capture: Optional[AudioCaptureStream] = None
        self._recording_uri: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._songs_captured: int = 0
        # URIs blocked from capture after Re-learn; cleared when song restarts or changes
        self._blocked_uris: set[str] = set()
        # Guard against firing auto-librosa/recapture more than once per URI per session
        self._auto_librosa_queued: set[str] = set()
        self._auto_recapture_attempted: set[str] = set()
        self._capture_started_at: float = 0.0  # monotonic time when capture began
        # Last-capture result (for the Now Playing UI indicator). Set in
        # _stop_and_save at all terminal points. status: "ok" | "failed" | None.
        # reason short-tag values: "too_short" | "gap" | "anchor_zero" |
        # "wav_failed" | "librosa_failed" — empty when status="ok".
        self._last_capture_status: Optional[str] = None
        self._last_capture_reason: str = ""
        self._last_capture_uri: Optional[str] = None
        # Acoustic-boundary monotonic instant computed once per track-change in
        # on_track_change: passed to _stop_and_save (trim prev tail) and
        # stashed here for _start (origin for new pre-roll). Tagged with the
        # URI that produced it so a transition that never starts a capture
        # can't leak a stale boundary into a later song's baseline.
        self._pending_boundary_monotonic: Optional[float] = None
        self._pending_boundary_uri: Optional[str] = None
        # Detached finalize pipelines (trim/save/WAV/librosa/realign) — strong
        # refs so the tasks aren't garbage-collected mid-run.
        self._finalize_tasks: set[asyncio.Task] = set()

    # How far into a song (ms) counts as "restarted from the beginning"
    _RESTART_THRESHOLD_MS = 10000
    _CAPTURE_GRACE_S = 5.0  # ignore transient URI changes for this long after capture starts

    async def on_track_change(self, track: Optional[SpotifyTrackInfo]) -> None:
        """
        Called from _on_state_update on every Spotify poll.
        Handles start/stop of capture based on current track.
        """
        from models.state import state as app_state
        new_uri = track.spotify_uri if track else None

        # Ring-buffer watchdog: the boundary search and force-recapture
        # pre-roll both depend on it, and its stream can die silently.
        if app_state.audio_analysis_enabled:
            try:
                from api.pcm_ring_buffer import pcm_ring_buffer
                pcm_ring_buffer.ensure_alive()
            except Exception as exc:
                logger.debug("Ring-buffer watchdog error (ignored): %s", exc)

        # Stop recording if URI changed or nothing is playing
        if self._recording_uri and self._recording_uri != new_uri:
            age = time.monotonic() - self._capture_started_at
            if age < self._CAPTURE_GRACE_S and new_uri is None:
                # Transient API blip during song skip — ignore
                logger.debug("Capture grace period: ignoring transient None URI (%.1fs old)", age)
                return
            # The boundary audio ARRIVES audio_latency_ms after the Spotify
            # track change. With fast end-of-song burst polling the URI flip
            # is often detected before the previous song's tail has reached
            # the capture device — wait for it so (a) the ring buffer
            # actually contains the boundary region for the acoustic search
            # and (b) the previous capture's recorder receives its full tail
            # (stopping immediately is what cut the end off captures).
            if track and track.is_playing:
                from config import settings as _cfg_w
                hint = track.fetched_at - track.progress_ms / 1000.0
                arrival_deadline = hint + _cfg_w.audio_latency_ms / 1000.0 + 0.5
                wait_s = arrival_deadline - time.monotonic()
                if 0 < wait_s <= 3.0:
                    logger.debug("Boundary-wait: %.2fs for prev tail to arrive", wait_s)
                    await asyncio.sleep(wait_s)
            # Compute one acoustic boundary that BOTH the prev capture's
            # _stop_and_save (tail trim) and the new song's _start (pre-roll
            # origin) will use. None when no new track is playing (pause /
            # device-off) so _stop_and_save skips the trim path.
            boundary = (
                self._compute_acoustic_boundary(track) if track and track.is_playing else None
            )
            self._pending_boundary_monotonic = boundary
            self._pending_boundary_uri = new_uri
            await self._stop_and_save(boundary)

        # Clear block when a blocked URI is detected restarting from the beginning
        if new_uri and new_uri in self._blocked_uris and track:
            progress_ms = track.interpolated_progress_ms()
            if progress_ms < self._RESTART_THRESHOLD_MS:
                logger.info("Re-learn block lifted for %s (progress %.0f ms)", new_uri, progress_ms)
                self._blocked_uris.discard(new_uri)
        # A different song playing also lifts pending blocks: the block only
        # exists to stop the cancelled song's CURRENT play from re-capturing.
        # (Restart detection alone is fragile — late URI-change detection plus
        # the boundary-wait can push the first progress check past the
        # threshold, leaving the block stuck forever.)
        elif new_uri and self._blocked_uris and new_uri not in self._blocked_uris:
            logger.info("Re-learn block lifted for %s (different song playing)",
                        ", ".join(sorted(self._blocked_uris)))
            self._blocked_uris.clear()

        # Run auto-offset detection for complete but unverified shapes (independent of capture state)
        try:
            from services.auto_offset_service import auto_offset_service
            await auto_offset_service.on_track_change(track)
        except Exception as exc:
            logger.warning("Auto-offset service error (ignored): %s", exc)

        # Only capture when analysis is enabled and on target device
        if not app_state.audio_analysis_enabled:
            return
        if not app_state.on_target_device:
            if self._recording_uri:
                logger.info("Device changed away from target — stopping capture")
                await self._stop_and_save()
            return

        # ── Force-recapture branch ────────────────────────────────────────
        # When app_state.recapture_active is True, every song that plays
        # gets a fresh capture regardless of whether a shape exists, whether
        # the URI is blocked, or whether auto-recapture has already fired
        # this session. The counter ticks down on every NEW song poll and
        # auto-disables the toggle at 0. Capture-time pre-roll is pulled
        # from the always-on PCM ring buffer, and the new shape is committed
        # atomically by _stop_and_save (originals preserved on failure).
        if (app_state.recapture_active and app_state.recapture_remaining > 0
                and track and track.is_playing
                and new_uri != self._recording_uri):
            # Count a song only when its capture actually starts — a deferred
            # _start (stale poll) retries on the next poll and must not burn
            # a second slot.
            if not await self._start(track, force_recapture=True):
                return
            app_state.recapture_remaining -= 1
            if app_state.recapture_remaining == 0:
                app_state.recapture_active = False
                logger.info("Recapture: counter exhausted, toggle disabled")
            else:
                logger.info(
                    "Recapture: force-recapture started for %s — %d songs remaining",
                    new_uri, app_state.recapture_remaining,
                )
            try:
                from services.websocket_manager import ws_manager
                await ws_manager.broadcast_state(app_state)
            except Exception:
                pass
            return

        # Start recording if:
        #   - there is a track playing on the target device
        #   - we're not already recording this URI
        #   - no complete shape exists yet
        #   - URI is not blocked pending a song restart after Re-learn
        if track and track.is_playing and new_uri != self._recording_uri:
            if new_uri in self._blocked_uris:
                return
            existing = load_audio_shape_meta(track.spotify_uri)

            # ── Auto-recapture / auto-librosa ──────────────────────────────
            # If a complete shape exists but is missing its WAV or librosa JSON,
            # either queue librosa analysis or clear the shape for a full recapture.
            if existing is not None and existing.capture_complete:
                from services.librosa_service import (
                    wav_path as _wav_path, get_analysis_by_uri as _get_analysis,
                    analyze_async as _analyze_async,
                )
                _has_wav     = _wav_path(existing).exists()
                _has_librosa = _get_analysis(new_uri) is not None
                _has_mfcc    = existing.librosa_version >= 2  # fast check from sidecar, no JSON parsing

                if _has_wav and not _has_librosa and new_uri not in self._auto_librosa_queued:
                    # WAV present but no librosa — just run analysis, no recapture needed
                    self._auto_librosa_queued.add(new_uri)
                    _existing_snap = existing  # capture for closure
                    async def _run_librosa(_m=_existing_snap, _u=new_uri) -> None:
                        await _analyze_async(_m)
                        self._auto_librosa_queued.discard(_u)
                    asyncio.create_task(_run_librosa())
                    logger.info(
                        "Auto-queued librosa analysis for %s (WAV present, no analysis)", existing.title
                    )

                elif not _has_wav and not _has_librosa and new_uri not in self._auto_recapture_attempted:
                    # No WAV and no librosa — need a full recapture
                    self._auto_recapture_attempted.add(new_uri)
                    progress_ms = track.interpolated_progress_ms()
                    npz_path = AUDIO_SHAPES_DIR / existing.npz_file
                    if progress_ms < 7000:
                        # Early enough — delete shape and start capture immediately
                        logger.info(
                            "Auto-recapture: clearing shape for %s (progress %.0fms)",
                            existing.title, progress_ms,
                        )
                        for _p in (npz_path, npz_path.with_suffix(".json")):
                            _p.unlink(missing_ok=True)
                        existing = None   # fall through to _start below
                    else:
                        # Too far in — delete shape and block until the song restarts
                        logger.info(
                            "Auto-recapture: deleting shape for %s (progress %.0fms) — will recapture next play",
                            existing.title, progress_ms,
                        )
                        for _p in (npz_path, npz_path.with_suffix(".json")):
                            _p.unlink(missing_ok=True)
                        self._blocked_uris.add(new_uri)
                elif not _has_wav and _has_librosa and not _has_mfcc and new_uri not in self._auto_recapture_attempted:
                    # Has librosa but no WAV and missing MFCC — auto-recapture to get MFCC data
                    self._auto_recapture_attempted.add(new_uri)
                    progress_ms = track.interpolated_progress_ms()
                    npz_path = AUDIO_SHAPES_DIR / existing.npz_file
                    if progress_ms < 7000:
                        logger.info(
                            "MFCC recapture: clearing shape for %s (progress %.0fms)",
                            existing.title, progress_ms,
                        )
                        for _p in (npz_path, npz_path.with_suffix(".json")):
                            _p.unlink(missing_ok=True)
                        existing = None  # fall through to _start below
                    else:
                        logger.info(
                            "MFCC recapture: deleting shape for %s (progress %.0fms) — will recapture next play",
                            existing.title, progress_ms,
                        )
                        for _p in (npz_path, npz_path.with_suffix(".json")):
                            _p.unlink(missing_ok=True)
                        self._blocked_uris.add(new_uri)
                # The legacy WAV-only auto-recapture branch was removed in
                # the recapture-overhaul. Force-recapture is now driven by
                # state.recapture_active and handled below as a top-level
                # branch BEFORE these missing-data heuristics.
            # ───────────────────────────────────────────────────────────────

            if existing is None or not existing.capture_complete:
                await self._start(track)

    async def stop_capture(self) -> None:
        """Stop any active capture without saving (used when analysis is disabled mid-capture)."""
        if self._capture:
            self._capture.stop()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._recorder = None
        self._capture = None
        self._recording_uri = None

    async def cancel_capture(self, uri: str) -> None:
        """Discard in-progress capture for *uri* without saving, and block re-capture until
        the song restarts from the beginning or a different song plays."""
        if self._recording_uri == uri:
            logger.info("Re-learn: cancelling active capture for %s", uri)
            await self.stop_capture()
        self._blocked_uris.add(uri)
        logger.info("Re-learn: capture blocked for %s until song restarts", uri)

    def _compute_acoustic_boundary(self, track: SpotifyTrackInfo) -> Optional[float]:
        """Locate the actual song boundary in the ring-buffer PCM around the
        Spotify-derived hint. Returns the refined monotonic instant on
        success, the hint instant on low-confidence (gapless transition),
        or None when there is no PCM available to search.
        """
        try:
            from api.pcm_ring_buffer import pcm_ring_buffer
            from api.boundary_detect import (
                find_track_boundary,
                DEFAULT_SEARCH_WINDOW_S,
                CONFIDENCE_THRESHOLD,
            )
            from config import settings as _cfg
            sample_rate = _cfg.audio_sample_rate
            # Spotify-time instant the track changed (progress_ms == 0).
            hint_monotonic = track.fetched_at - (track.progress_ms / 1000.0)
            # The audio pipeline delivers sound ~audio_latency_ms after
            # Spotify's reported position, so the acoustic boundary ARRIVES
            # at hint + latency. The ring buffer is stamped in arrival time —
            # search around the arrival instant (searching around the raw
            # hint centered the window a full latency early, which is what
            # put the previous track's tail at the head of captures). The
            # returned boundary stays in Spotify time, the same timebase as
            # song_start and the latency-adjusted frame timestamps.
            latency_s = _cfg.audio_latency_ms / 1000.0
            pcm_wide = pcm_ring_buffer.snapshot_since(
                hint_monotonic + latency_s - DEFAULT_SEARCH_WINDOW_S
            )
            if pcm_wide.size == 0:
                logger.info("Acoustic boundary: no PCM available, using Spotify estimate for %s", track.title)
                return hint_monotonic
            hint_offset_samples = int(DEFAULT_SEARCH_WINDOW_S * sample_rate)
            best_offset, confidence = find_track_boundary(
                pcm_wide, sample_rate, hint_offset_samples, DEFAULT_SEARCH_WINDOW_S,
            )
            delta_s = (best_offset - hint_offset_samples) / sample_rate
            if confidence >= CONFIDENCE_THRESHOLD:
                logger.info(
                    "Acoustic boundary: snapped %+d ms (confidence %.1f) for %s",
                    int(delta_s * 1000), confidence, track.title,
                )
                return hint_monotonic + delta_s
            logger.info(
                "Acoustic boundary: no peak above threshold (confidence %.1f), using Spotify estimate for %s",
                confidence, track.title,
            )
            return hint_monotonic
        except Exception as exc:
            logger.warning("Acoustic boundary: detection failed (%s), falling back to None", exc)
            return None

    async def _start(self, track: SpotifyTrackInfo, force_recapture: bool = False) -> bool:
        """Open capture stream and kick off the ingest loop. Returns True when
        the capture actually started, False when deferred (stale poll).

        force_recapture=True signals an atomic-save force-recapture. The
        always-on PCM ring buffer is consulted for any audio that played
        between the song's true start and now (the URI-detection lag);
        those samples are synthesized into AudioFrames and ingested into
        the recorder before live frames arrive, so the saved npz covers
        the full song. _stop_and_save honors `_force_recapture` to gate
        atomic commit on all four checks (coverage + WAV + librosa + anchor).
        """
        # Freshness guard: every time baseline below (acoustic boundary or
        # Spotify estimate) is derived from track.fetched_at. If that poll is
        # stale — machine sleep, stalled poller — the interpolated progress no
        # longer reflects the real song position and the whole capture is
        # placed at the wrong song-time (timestamps beyond the song → invisible
        # shape, triggers that never fire). Skip this cycle; on_track_change
        # fires again next poll and starts the capture once data is fresh.
        from config import settings as _s
        stale_ms = (time.monotonic() - track.fetched_at) * 1000
        max_stale_ms = _s.poll_interval_playing_ms * 3
        if stale_ms > max_stale_ms:
            logger.info(
                "Capture deferred for %s — track poll is %.0fms stale (limit %dms); "
                "awaiting fresh progress",
                track.title, stale_ms, max_stale_ms,
            )
            return False

        # song_start_monotonic offset so frame timestamps are song-relative.
        # Prefer the acoustic boundary computed in on_track_change when it was
        # produced by THIS track's transition (force-recapture symmetric
        # trim). Fall back to Spotify's reported progress for the first
        # capture of a session or when no PCM was available in the ring
        # buffer.
        if (self._pending_boundary_monotonic is not None
                and self._pending_boundary_uri == track.spotify_uri):
            song_start = self._pending_boundary_monotonic
        else:
            progress_s = track.interpolated_progress_ms() / 1000.0
            song_start = time.monotonic() - progress_s

        self._recording_uri = track.spotify_uri
        self._capture_started_at = time.monotonic()
        self._force_recapture = bool(force_recapture)
        self._recorder = AudioShapeRecorder(
            track.spotify_uri, track.title, track.artist, track.duration_ms,
            genres=track.genres,
        )

        # Pre-roll: pull whatever PCM the always-on ring buffer captured between
        # song-start and now (URI detection typically lags by 5-10s). Synthesize
        # AudioFrames and ingest into the recorder before live capture begins.
        # Also feed the raw PCM into the recorder's pre-roll PCM list so the
        # WAV file includes the leading audio. Skipped for non-force captures
        # to preserve legacy behavior.
        pre_roll_pcm: list = []
        if force_recapture:
            try:
                from api.pcm_ring_buffer import pcm_ring_buffer
                from api.audio_capture import synthesize_frames_from_pcm
                from config import settings as _cfg
                # Ring-buffer stamps are audio ARRIVAL time; song-time-0 audio
                # arrives audio_latency_ms after the Spotify-time song_start.
                # Snapshotting from song_start itself grabbed the previous
                # track's tail and labeled it as this song's first second.
                want_monotonic = song_start + _cfg.audio_latency_ms / 1000.0
                pcm, got_monotonic = pcm_ring_buffer.snapshot_since_with_start(
                    want_monotonic
                )
                if pcm.size > 0:
                    pre_roll_seconds = pcm.size / _cfg.audio_sample_rate
                    # Label from the buffer's EFFECTIVE start: 0 when the ring
                    # covered the whole head, later when it was too shallow
                    # (e.g. capture start delayed past the ring depth) — the
                    # coverage/gap checks then judge the real hole instead of
                    # mislabeled frames.
                    pre_roll_start_ms = max(0, int((got_monotonic - want_monotonic) * 1000))
                    frames = synthesize_frames_from_pcm(pcm, pre_roll_start_ms)
                    for f in frames:
                        self._recorder.ingest(f)
                    pre_roll_pcm = [pcm.copy()]  # for WAV concatenation later
                    logger.info(
                        "Recapture: pre-rolled %.1fs of PCM (%d frames synthesized) for %s",
                        pre_roll_seconds, len(frames), track.title,
                    )
                else:
                    logger.info(
                        "Recapture: no pre-roll PCM available for %s (ring buffer empty or stale)",
                        track.title,
                    )
            except Exception as exc:
                logger.warning("Recapture: pre-roll ingestion failed: %s", exc)

        self._capture = AudioCaptureStream(song_start)
        # Seed the capture's raw PCM buffer so WAV write includes pre-roll
        if pre_roll_pcm:
            self._capture._pcm_chunks.extend(pre_roll_pcm)
            self._capture.set_pcm_start_ms(pre_roll_start_ms)
        self._capture.start()
        self._task = asyncio.create_task(self._ingest_loop(), name="audio-capture")
        logger.info(
            "Audio capture started for: %s — %s%s",
            track.artist, track.title,
            " (force-recapture)" if force_recapture else "",
        )
        # Boundary has now been consumed by both _stop_and_save (prev) and _start (new)
        self._pending_boundary_monotonic = None
        self._pending_boundary_uri = None
        return True

    async def _ingest_loop(self) -> None:
        """Consume frames from the capture stream into the recorder."""
        try:
            async for frame in self._capture:
                self._recorder.ingest(frame)
        except Exception as exc:
            logger.warning("Audio ingest loop error: %s", exc)

    async def _stop_and_save(self, boundary: Optional[float] = None) -> None:
        """Stop the active capture and finalize it in the background.

        `boundary` is the acoustic track-boundary instant for a track-change
        stop (tail-wait + trim); None for pause/device-off stops.

        The finalize pipeline (trim, checks, npz save, WAV + librosa,
        realign, atomic commit/rollback) takes 30-60s in force-recapture
        mode. It runs as a detached task so on_track_change can start the
        NEXT song's capture within the same poll — when finalize was awaited
        inline, the next capture started so late that the 30s PCM ring no
        longer held the song's head, and consecutive force-recaptures were
        discarded with a pre-roll gap.
        """
        # Let the previous song's tail finish ARRIVING before stopping the
        # stream. The audio pipeline lags Spotify's reported position by
        # audio_latency_ms, so at URI-change time the last ~second of the
        # previous track hasn't reached the capture device yet — stopping
        # immediately is what cut the end off captures. Wait until the
        # boundary audio has arrived (plus a chunk margin); the acoustic
        # trim in finalize drops anything past the boundary.
        if boundary is not None and self._capture is not None:
            from config import settings as _cfg_t
            tail_deadline = boundary + _cfg_t.audio_latency_ms / 1000.0 + 0.3
            wait_s = tail_deadline - time.monotonic()
            if 0 < wait_s <= 3.0:
                logger.debug("Tail-wait: %.2fs for boundary audio to arrive", wait_s)
                await asyncio.sleep(wait_s)

        # Detach the capture state so the service is immediately free for the
        # next song.
        capture, recorder = self._capture, self._recorder
        recording_uri = self._recording_uri
        ingest_task = self._task
        force_recapture = bool(getattr(self, "_force_recapture", False))
        self._capture = None
        self._recorder = None
        self._task = None
        self._recording_uri = None
        self._force_recapture = False

        if capture:
            capture.stop()
        if ingest_task:
            await asyncio.gather(ingest_task, return_exceptions=True)
        if capture is None and recorder is None:
            return

        task = asyncio.create_task(
            self._finalize_capture(capture, recorder, recording_uri, force_recapture, boundary),
            name=f"finalize-capture-{recording_uri}",
        )
        self._finalize_tasks.add(task)
        task.add_done_callback(self._finalize_tasks.discard)

    async def _finalize_capture(
        self,
        capture: Optional[AudioCaptureStream],
        recorder: Optional[AudioShapeRecorder],
        recording_uri: Optional[str],
        force_recapture: bool,
        boundary: Optional[float],
    ) -> None:
        """Trim, validate, save .npz, run WAV + librosa, realign, update
        sidecar JSON — detached from the poll loop (see _stop_and_save).

        When force_recapture is True, the existing shape's four files
        (npz, json, wav, librosa.json) are renamed to *.bak before the new
        save runs. After the save + WAV + librosa + anchor pipeline completes,
        all four atomic-save checks are verified: coverage ≥90%, WAV write
        success, librosa success, ≥1 anchor candidate. If all pass, the
        .bak files are deleted (commit). If any fail, the new files are
        deleted and the .bak files are restored (rollback) — original shape
        is preserved intact.
        """
        # Acoustic-boundary trim: if a boundary was computed in
        # on_track_change, drop frames + WAV PCM whose timestamp is past
        # the actual track boundary so the previous song's saved shape
        # doesn't include the head of the next song.
        if (
            boundary is not None
            and capture is not None
            and recorder is not None
        ):
            try:
                from config import settings as _cfg_b
                prev_song_start = capture._song_start
                boundary_song_rel_ms = int((boundary - prev_song_start) * 1000)
                if boundary_song_rel_ms > 0:
                    dropped_frames = recorder.trim_after(boundary_song_rel_ms)
                    dropped_samples = capture.truncate_pcm_to(
                        boundary_song_rel_ms, _cfg_b.audio_sample_rate
                    )
                    if dropped_frames or dropped_samples:
                        logger.info(
                            "Acoustic trim: prev song tail trimmed at %d ms (-%d frames, -%d samples) for %s",
                            boundary_song_rel_ms, dropped_frames, dropped_samples,
                            recorder.meta.npz_file,
                        )
            except Exception as exc:
                logger.warning("Acoustic trim: prev tail trim failed (%s)", exc)

        if recorder and recorder._timestamps:
            try:
                from config import settings as _s
                from models.state import state as app_state
                duration_ms = recorder.meta.duration_ms
                captured_ms = recorder._timestamps[-1] - recorder._timestamps[0]
                if duration_ms > 0 and captured_ms < duration_ms * _s.audio_shape_min_capture_pct:
                    logger.info(
                        "Capture too short (%.0f%% of song, need %.0f%%), discarding: %s",
                        captured_ms / duration_ms * 100,
                        _s.audio_shape_min_capture_pct * 100,
                        recorder.meta.npz_file,
                    )
                    self._last_capture_status = "failed"
                    self._last_capture_reason = "too_short"
                    self._last_capture_uri = recording_uri
                    return
                # Timestamp-sanity — discard if the capture's song-time baseline
                # is implausible. A stale poll behind the song_start estimate
                # places every sample beyond the song's end (ts_first >=
                # duration), which renders no shape and fires no triggers. The
                # freshness guard in _start() should prevent this; this is the
                # final net so a poisoned baseline is never persisted as a
                # "complete" shape.
                ts_first = recorder._timestamps[0]
                if duration_ms > 0 and ts_first >= duration_ms:
                    logger.warning(
                        "Audio shape discarded — timestamp baseline beyond song end "
                        "(first sample at %dms, duration %dms): %s",
                        ts_first, duration_ms, recorder.meta.npz_file,
                    )
                    # Failure sidecar so on_track_change retries next play —
                    # but never clobber the intact original in force mode
                    # (the atomic-save backup hasn't been taken yet at this
                    # point, so writing here would destroy the good sidecar's
                    # learned offsets while its npz stays complete).
                    if not force_recapture:
                        fail_meta = recorder.meta.model_copy(
                            update={"capture_complete": False, "capture_failed": True}
                        )
                        from config import AUDIO_SHAPES_DIR
                        sidecar = AUDIO_SHAPES_DIR / fail_meta.npz_file.replace(".npz", ".json")
                        AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
                        sidecar.write_text(fail_meta.model_dump_json(indent=2), encoding="utf-8")
                    self._last_capture_status = "failed"
                    self._last_capture_reason = "bad_timestamps"
                    self._last_capture_uri = recording_uri
                    return
                # Gap detection — discard shape if any inter-sample gap exceeds threshold
                ts_list = recorder._timestamps
                if len(ts_list) > 1:
                    max_gap = max(ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1))
                    if max_gap > _s.audio_max_gap_ms:
                        logger.warning(
                            "Audio shape discarded — gap of %dms detected (limit %dms): %s",
                            max_gap, _s.audio_max_gap_ms, recorder.meta.npz_file,
                        )
                        # Write failure sidecar so on_track_change retries on
                        # next play — except in force mode, where the intact
                        # original (npz still complete on disk) must survive a
                        # discarded recapture attempt.
                        if not force_recapture:
                            fail_meta = recorder.meta.model_copy(
                                update={"capture_complete": False, "capture_failed": True}
                            )
                            from config import AUDIO_SHAPES_DIR
                            sidecar = AUDIO_SHAPES_DIR / fail_meta.npz_file.replace(".npz", ".json")
                            AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
                            sidecar.write_text(fail_meta.model_dump_json(indent=2), encoding="utf-8")
                        self._last_capture_status = "failed"
                        self._last_capture_reason = "gap"
                        self._last_capture_uri = recording_uri
                        return

                # Drain raw PCM before saving (capture is already stopped)
                raw_pcm = capture.drain_pcm() if capture else None

                # Atomic-save backup: rename existing files to *.bak so we
                # can restore them if any of the four checks fail. Only fires
                # in force-recapture mode; first-time captures have nothing
                # to back up.
                from config import AUDIO_SHAPES_DIR as _SHAPES_DIR
                _bak_paths: list[tuple[Path, Path]] = []   # (original, .bak)
                if force_recapture:
                    _stem = recorder.meta.npz_file[:-4]  # strip ".npz"
                    _candidates = [
                        _SHAPES_DIR / f"{_stem}.npz",
                        _SHAPES_DIR / f"{_stem}.json",
                        _SHAPES_DIR / f"{_stem}.wav",
                        _SHAPES_DIR / f"{_stem}.librosa.json",
                    ]
                    for orig in _candidates:
                        if orig.exists():
                            bak = orig.with_suffix(orig.suffix + ".bak")
                            try:
                                if bak.exists():
                                    bak.unlink()
                                orig.rename(bak)
                                _bak_paths.append((orig, bak))
                            except Exception as exc:
                                logger.warning(
                                    "Atomic-save: failed to back up %s: %s", orig.name, exc,
                                )
                    if _bak_paths:
                        logger.info(
                            "Atomic-save: backed up %d existing files for %s",
                            len(_bak_paths), recorder.meta.npz_file,
                        )

                # np.savez_compressed of a full song is seconds of CPU — keep
                # it off the event loop or the poll loop (and the next song's
                # capture start) stalls behind it.
                npz_path = await asyncio.get_event_loop().run_in_executor(
                    None, recorder.save
                )
                # Mark detection disabled — not useful right now
                marks = []
                meta = recorder.meta
                meta.music_marks = marks
                meta.capture_complete = True

                # Detect early-feature anchor candidates for snap-alignment on
                # subsequent plays. Round 6: gated behind settings.anchor_enabled
                # — the smart-window xcorr sweep handles song-start snapping by
                # itself with the round-5 4-band math, so rise detection at
                # capture time is unnecessary unless re-enabled for debugging.
                if _s.anchor_enabled:
                    try:
                        from services import anchor_detector, librosa_service

                        # Tempo may not be available at first-capture time (librosa
                        # runs after). When missing, the beat-twin penalty inside
                        # _score_uniqueness silently no-ops — the backfill script
                        # re-runs anchor detection once librosa.json exists.
                        def _detect_anchors():
                            npz = np.load(npz_path)
                            analysis = librosa_service.get_analysis(meta)
                            tempo_bpm = float(analysis.tempo_bpm) if analysis else None
                            return anchor_detector.detect_anchor_candidates(
                                npz["timestamps_ms"],
                                npz["rms_total"],
                                npz["rms_low"],
                                npz["rms_high"],
                                tempo_bpm=tempo_bpm,
                            )

                        # Anchor detection is ~seconds of pure-Python CPU —
                        # executor, same reason as recorder.save above.
                        anchors = await asyncio.get_event_loop().run_in_executor(
                            None, _detect_anchors
                        )
                        meta.anchor_candidates = [c.to_dict() for c in anchors]
                        if anchors:
                            top = anchors[0]
                            logger.info(
                                "Anchor: detected %d candidates for %s (top: %dms band=%s rise=%.2f uniqueness=%.2f)",
                                len(anchors), meta.spotify_uri,
                                top.timestamp_ms, top.band, top.rise_magnitude, top.uniqueness,
                            )
                        else:
                            logger.info("Anchor: no candidates passed thresholds for %s", meta.spotify_uri)
                    except Exception as exc:
                        logger.warning("Anchor: detector failed for %s: %s", meta.spotify_uri, exc)
                        meta.anchor_candidates = []
                else:
                    # Anchor disabled — leave the field at its default (empty list).
                    pass

                sidecar = npz_path.with_suffix(".json")
                sidecar.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
                self._songs_captured += 1
                logger.info("Audio shape saved: %s", npz_path.name)
                # Default-mark capture as ok now that the npz committed. The
                # force-recapture rollback path below will override this back
                # to "failed" if any of its four atomic-save checks tripped.
                self._last_capture_status = "ok"
                self._last_capture_reason = ""
                self._last_capture_uri = meta.spotify_uri

                # Write WAV and schedule librosa analysis. For force-recapture
                # mode, AWAIT the WAV+librosa task and use its boolean result
                # to validate the four atomic-save checks. For first-time
                # captures, fire-and-forget preserves legacy behavior.
                if raw_pcm is not None and len(raw_pcm) > 0:
                    if force_recapture:
                        wav_librosa_ok = await _save_wav_and_analyze(
                            meta, raw_pcm, _s.audio_sample_rate
                        )
                        # Four checks for atomic commit:
                        #   1. coverage ≥ 90%      — already passed (line 308)
                        #   2. WAV write success   — wav_librosa_ok subsumes
                        #   3. librosa success     — wav_librosa_ok subsumes
                        #   4. anchor count ≥ 1    — meta.anchor_candidates
                        anchor_ok = len(meta.anchor_candidates) >= 1
                        commit = bool(wav_librosa_ok) and anchor_ok
                        if commit:
                            # Self-correction BEFORE the .bak files are
                            # deleted: measure the timebase shift between the
                            # old capture (still on disk as *.bak) and the new
                            # one, then migrate triggers + learned xcorr
                            # offsets so they land on the same music.
                            try:
                                from services.capture_alignment import realign_after_recapture
                                _stem_r = meta.npz_file[:-4]
                                await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    lambda: realign_after_recapture(
                                        meta.spotify_uri, _stem_r, meta.duration_ms
                                    ),
                                )
                            except Exception as exc:
                                logger.warning("Realign failed (non-fatal): %s", exc)
                            for orig, bak in _bak_paths:
                                try:
                                    bak.unlink()
                                except Exception:
                                    pass
                            if _bak_paths:
                                logger.info(
                                    "Atomic-save: COMMITTED — discarded %d backup files for %s",
                                    len(_bak_paths), meta.npz_file,
                                )
                            # status already defaulted to "ok" above; nothing to override
                        else:
                            # Roll back: delete the just-written files, restore
                            # the .bak files to their original names.
                            reasons = []
                            if not wav_librosa_ok:
                                reasons.append("WAV/librosa pipeline failed")
                            if not anchor_ok:
                                reasons.append(
                                    f"anchor count {len(meta.anchor_candidates)} < 1"
                                )
                            logger.warning(
                                "Atomic-save: ROLLBACK for %s — %s",
                                meta.npz_file, "; ".join(reasons),
                            )
                            # Map to a single short tag for the UI indicator.
                            # WAV/librosa share a tag because the pipeline
                            # function returns a single bool covering both.
                            self._last_capture_status = "failed"
                            if not anchor_ok:
                                self._last_capture_reason = "anchor_zero"
                            else:
                                self._last_capture_reason = "wav_librosa_failed"
                            self._last_capture_uri = meta.spotify_uri
                            _stem = meta.npz_file[:-4]
                            for new in (
                                _SHAPES_DIR / f"{_stem}.npz",
                                _SHAPES_DIR / f"{_stem}.json",
                                _SHAPES_DIR / f"{_stem}.wav",
                                _SHAPES_DIR / f"{_stem}.librosa.json",
                            ):
                                try:
                                    new.unlink(missing_ok=True)
                                except Exception:
                                    pass
                            for orig, bak in _bak_paths:
                                try:
                                    bak.rename(orig)
                                except Exception as exc:
                                    logger.error(
                                        "Atomic-save: failed to restore %s from %s: %s",
                                        orig.name, bak.name, exc,
                                    )
                    else:
                        # Legacy first-time capture path: shape already on disk
                        # via recorder.save(). WAV+librosa is fire-and-forget;
                        # capture itself is already marked "ok" below.
                        asyncio.create_task(
                            _save_wav_and_analyze(meta, raw_pcm, _s.audio_sample_rate)
                        )
                # Auto-generate AI triggers if enabled and no suggestions exist yet
                if app_state.auto_generate_enabled:
                    asyncio.create_task(_auto_generate_for_uri(meta.spotify_uri))
                # Auto-disable analysis if max song count reached
                if _s.audio_analysis_max_songs > 0 and self._songs_captured >= _s.audio_analysis_max_songs:
                    app_state.audio_analysis_enabled = False
                    logger.info("Audio analysis disabled: reached max_songs=%d", _s.audio_analysis_max_songs)
            except Exception as exc:
                logger.error("Failed to save audio shape: %s", exc)

    def get_live_data(self, uri: str) -> dict | None:
        """Return in-progress frame data if currently recording this URI."""
        if self._recording_uri != uri or not self._recorder:
            return None
        r = self._recorder
        return {
            "timestamps_ms": list(r._timestamps),
            "rms_total":     list(r._rms_total),
            "rms_low":       list(r._rms_low),
            "rms_mid":       list(r._rms_mid),
            "rms_high":      list(r._rms_high),
            "capture_complete": False,
        }


def _find_profile_for_genres(genres: list[str]) -> dict | None:
    """Return best-matching training profile by genre, or the default profile."""
    from services.training_profile_manager import list_training_profiles
    profiles = list_training_profiles()
    song_genres_lower = [g.lower() for g in genres]
    for profile in profiles:
        for pg in profile.get("genres", []):
            pg_lower = pg.lower()
            if any(pg_lower in sg or sg in pg_lower for sg in song_genres_lower):
                return profile
    for profile in profiles:
        if profile.get("is_default", False):
            return profile
    return None


async def _auto_generate_for_uri(spotify_uri: str) -> None:
    """Background task: generate trigger suggestions for a freshly captured shape.

    Routes to the embedded KNN engine (auto-applies) or the Claude AI engine
    (saves suggestion set for review) based on settings.auto_generate_mode.
    """
    from services.websocket_manager import ws_manager
    from config import settings as _s

    meta = load_audio_shape_meta(spotify_uri)
    training_profile = _find_profile_for_genres(meta.genres if meta else [])
    if not training_profile:
        logger.info("Auto-generate skipped — no matching or default profile for %s", spotify_uri)
        return

    title  = meta.title  if meta else ""
    artist = meta.artist if meta else ""

    mode = _s.auto_generate_mode  # "embedded" | "claude"

    if mode == "embedded":
        await _auto_generate_embedded(
            spotify_uri, title, artist, meta, training_profile, ws_manager
        )
    else:
        await _auto_generate_claude(
            spotify_uri, title, artist, meta, training_profile, ws_manager
        )


async def _auto_generate_embedded(
    spotify_uri: str, title: str, artist: str, meta, training_profile: dict, ws_manager
) -> None:
    """Embedded KNN path: suggest triggers and auto-apply them directly to the profile."""
    from services.embedded_trigger_service import suggest_triggers
    from services.profile_manager import load_profile_by_uri, save_profile, get_event_map
    from models.song_profile import SongProfile, MusicTrigger

    all_train = training_profile.get("training_uris", []) + training_profile.get("embedded_only_uris", [])
    if not all_train:
        logger.info("Embedded auto-generate skipped — no training URIs in profile '%s'", training_profile.get("name", ""))
        return

    # Skip if the profile already has triggers
    existing = load_profile_by_uri(spotify_uri)
    if existing and existing.triggers:
        logger.debug("Embedded auto-generate skipped — triggers already exist for %s", spotify_uri)
        return

    track_id = spotify_uri.split(":")[-1]
    await ws_manager.broadcast({"type": "auto_generate_started", "title": title, "artist": artist, "method": "embedded"})

    try:
        from services.training_profile_manager import TrainingProfile
        tp_obj = TrainingProfile.model_validate(training_profile)
        event_map = get_event_map()
        available_event_ids = set(event_map.keys())
        raw = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: suggest_triggers(spotify_uri, all_train, available_event_ids,
                                     training_profile=tp_obj),
        )
    except Exception as exc:
        logger.warning("Embedded auto-generate failed for %s: %s", spotify_uri, exc)
        await ws_manager.broadcast({
            "type": "auto_generate_failed",
            "title": title, "artist": artist, "error": str(exc),
        })
        return

    if not raw:
        logger.info("Embedded auto-generate produced no suggestions for %s", spotify_uri)
        await ws_manager.broadcast({
            "type": "auto_generate_complete",
            "title": title, "artist": artist, "count": 0, "method": "embedded", "track_id": track_id,
        })
        return

    # Load or create a minimal profile to attach triggers to
    profile_obj = existing or SongProfile(
        spotify_uri=spotify_uri,
        title=title,
        artist=artist,
        duration_ms=meta.duration_ms if meta else 0,
    )
    profile_obj.triggers = [
        MusicTrigger(timestamp_ms=s["timestamp_ms"], event_id=s["event_id"])
        for s in raw
    ]
    profile_obj.embedded_generated = True
    save_profile(profile_obj)

    await ws_manager.broadcast({
        "type": "auto_generate_complete",
        "title": title, "artist": artist,
        "count": len(raw),
        "method": "embedded",
        "track_id": track_id,
    })
    logger.info("Embedded auto-generated %d triggers for %s — %s", len(raw), artist, title)


async def _auto_generate_claude(
    spotify_uri: str, title: str, artist: str, meta, training_profile: dict, ws_manager
) -> None:
    """Claude AI path: generate suggestions and save for review (existing behaviour)."""
    from services.ai_trigger_service import generate_suggestions
    from services.suggestion_store import save_suggestion_set, load_suggestion_set
    from models.ai_suggestion_set import AISuggestionSet, SavedSuggestion
    from datetime import datetime, timezone

    # Skip if suggestions already exist for this song
    track_id = spotify_uri.split(":")[-1]
    if load_suggestion_set(track_id) is not None:
        logger.debug("Auto-generate (claude) skipped — suggestions already exist for %s", track_id)
        return

    await ws_manager.broadcast({"type": "auto_generate_started", "title": title, "artist": artist, "method": "claude"})
    try:
        suggestions, usage = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: generate_suggestions(
                training_uris=training_profile["training_uris"],
                target_uri=spotify_uri,
                description=training_profile.get("description", ""),
            ),
        )
    except Exception as exc:
        logger.warning("Auto-generate (claude) failed for %s: %s", spotify_uri, exc)
        await ws_manager.broadcast({
            "type": "auto_generate_failed",
            "title": title, "artist": artist, "error": str(exc),
        })
        return

    saved_suggestions = [
        SavedSuggestion(
            timestamp_ms=s.timestamp_ms,
            event_id=s.event_id,
            event_name=s.event_name,
            confidence=s.confidence,
            reasoning=s.reasoning,
            original_timestamp_ms=s.timestamp_ms,
            original_event_id=s.event_id,
        )
        for s in suggestions
    ]
    suggestion_set = AISuggestionSet(
        spotify_uri=spotify_uri,
        title=title, artist=artist,
        duration_ms=meta.duration_ms if meta else 0,
        generated_at=datetime.now(timezone.utc).isoformat(),
        training_profile_id=training_profile["id"],
        training_profile_name=training_profile.get("name", ""),
        suggestions=saved_suggestions,
        cost_usd=usage["cost_usd"],
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
    )
    save_suggestion_set(suggestion_set)

    await ws_manager.broadcast({
        "type": "auto_generate_complete",
        "title": title, "artist": artist,
        "count": len(suggestions),
        "method": "claude",
        "track_id": track_id,
    })
    logger.info("Claude auto-generated %d suggestions for %s — %s", len(suggestions), artist, title)


async def _save_wav_and_analyze(meta, raw_pcm, sample_rate: int) -> bool:
    """Write a WAV file from captured PCM, enforce retention limit, then run
    librosa. Returns True on full success (WAV written + librosa produced an
    analysis), False on any failure. Force-recapture mode awaits the boolean
    to gate the atomic-save commit; legacy first-time captures fire-and-forget.
    """
    import soundfile as sf
    from services.librosa_service import wav_path, manage_wav_retention, analyze_async

    wpath = wav_path(meta)
    try:
        AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: sf.write(str(wpath), raw_pcm, sample_rate, subtype="FLOAT")
        )
        logger.info("WAV saved: %s (%.1f MB)", wpath.name, wpath.stat().st_size / 1e6)
        manage_wav_retention()
    except Exception as exc:
        logger.error("Failed to write WAV for %s: %s", meta.title, exc)
        return False

    librosa_result = await analyze_async(meta)
    librosa_ok = librosa_result is not None

    # Any cached analyzed triggers were generated from the previous capture's
    # librosa beats — stale for this fresh analysis. (Force-recapture also
    # invalidates via realign_after_recapture; this covers first-time captures
    # of songs whose old shape was deleted by the auto-recapture heuristics.)
    if librosa_ok:
        try:
            from services.capture_alignment import invalidate_analyzed_cache
            invalidate_analyzed_cache(meta.spotify_uri)
        except Exception:
            pass

    # All analysis complete (shape + WAV + librosa). Remove from recapture
    # playlist if present, and clear the needs_recapture flag on the sidecar.
    try:
        from services import recapture_playlist
        recapture_playlist.remove_track(meta.spotify_uri)
    except Exception:
        pass
    try:
        from services.audio_analyzer import clear_needs_recapture
        clear_needs_recapture(meta.spotify_uri)
    except Exception:
        pass

    return librosa_ok


# Singleton — import this everywhere
audio_shape_service = AudioShapeService()
