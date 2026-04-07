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

    # How far into a song (ms) counts as "restarted from the beginning"
    _RESTART_THRESHOLD_MS = 5000
    _CAPTURE_GRACE_S = 5.0  # ignore transient URI changes for this long after capture starts

    async def on_track_change(self, track: Optional[SpotifyTrackInfo]) -> None:
        """
        Called from _on_state_update on every Spotify poll.
        Handles start/stop of capture based on current track.
        """
        from models.state import state as app_state
        new_uri = track.spotify_uri if track else None

        # Stop recording if URI changed or nothing is playing
        if self._recording_uri and self._recording_uri != new_uri:
            age = time.monotonic() - self._capture_started_at
            if age < self._CAPTURE_GRACE_S and new_uri is None:
                # Transient API blip during song skip — ignore
                logger.debug("Capture grace period: ignoring transient None URI (%.1fs old)", age)
                return
            await self._stop_and_save()

        # Clear block when a blocked URI is detected restarting from the beginning
        if new_uri and new_uri in self._blocked_uris and track:
            progress_ms = track.interpolated_progress_ms()
            if progress_ms < self._RESTART_THRESHOLD_MS:
                logger.info("Re-learn block lifted for %s (progress %.0f ms)", new_uri, progress_ms)
                self._blocked_uris.discard(new_uri)

        # Run auto-offset detection for complete but unverified shapes (independent of capture state)
        try:
            from services.auto_offset_service import auto_offset_service
            await auto_offset_service.on_track_change(track)
        except Exception as exc:
            logger.warning("Auto-offset service error (ignored): %s", exc)

        # Only capture when analysis is enabled
        if not app_state.audio_analysis_enabled:
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
                elif not _has_wav and _has_librosa and _has_mfcc and app_state.recapture_wavs and new_uri not in self._auto_recapture_attempted:
                    # Has librosa WITH MFCC but no WAV — only recapture if toggle is on
                    self._auto_recapture_attempted.add(new_uri)
                    progress_ms = track.interpolated_progress_ms()
                    npz_path = AUDIO_SHAPES_DIR / existing.npz_file
                    if progress_ms < 7000:
                        logger.info(
                            "WAV recapture: clearing shape for %s (progress %.0fms)",
                            existing.title, progress_ms,
                        )
                        for _p in (npz_path, npz_path.with_suffix(".json")):
                            _p.unlink(missing_ok=True)
                        existing = None  # fall through to _start below
                    else:
                        logger.info(
                            "WAV recapture: deleting shape for %s (progress %.0fms) — will recapture next play",
                            existing.title, progress_ms,
                        )
                        for _p in (npz_path, npz_path.with_suffix(".json")):
                            _p.unlink(missing_ok=True)
                        self._blocked_uris.add(new_uri)
                # no WAV but yes librosa and recapture off → do nothing
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

    async def _start(self, track: SpotifyTrackInfo) -> None:
        """Open capture stream and kick off the ingest loop."""
        # song_start_monotonic offset so frame timestamps are song-relative
        progress_s = track.interpolated_progress_ms() / 1000.0
        song_start = time.monotonic() - progress_s

        self._recording_uri = track.spotify_uri
        self._capture_started_at = time.monotonic()
        self._recorder = AudioShapeRecorder(
            track.spotify_uri, track.title, track.artist, track.duration_ms,
            genres=track.genres,
        )
        self._capture = AudioCaptureStream(song_start)
        self._capture.start()
        self._task = asyncio.create_task(self._ingest_loop(), name="audio-capture")
        logger.info("Audio capture started for: %s — %s", track.artist, track.title)

    async def _ingest_loop(self) -> None:
        """Consume frames from the capture stream into the recorder."""
        try:
            async for frame in self._capture:
                self._recorder.ingest(frame)
        except Exception as exc:
            logger.warning("Audio ingest loop error: %s", exc)

    async def _stop_and_save(self) -> None:
        """Stop capture, save .npz, run mark detection, update sidecar JSON."""
        if self._capture:
            self._capture.stop()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

        if self._recorder and self._recorder._timestamps:
            try:
                from config import settings as _s
                from models.state import state as app_state
                duration_ms = self._recorder.meta.duration_ms
                captured_ms = self._recorder._timestamps[-1] - self._recorder._timestamps[0]
                if duration_ms > 0 and captured_ms < duration_ms * _s.audio_shape_min_capture_pct:
                    logger.info(
                        "Capture too short (%.0f%% of song, need %.0f%%), discarding: %s",
                        captured_ms / duration_ms * 100,
                        _s.audio_shape_min_capture_pct * 100,
                        self._recorder.meta.npz_file,
                    )
                    self._recorder = None
                    self._capture = None
                    self._recording_uri = None
                    return
                # Gap detection — discard shape if any inter-sample gap exceeds threshold
                ts_list = self._recorder._timestamps
                if len(ts_list) > 1:
                    max_gap = max(ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1))
                    if max_gap > _s.audio_max_gap_ms:
                        logger.warning(
                            "Audio shape discarded — gap of %dms detected (limit %dms): %s",
                            max_gap, _s.audio_max_gap_ms, self._recorder.meta.npz_file,
                        )
                        # Write failure sidecar so on_track_change retries on next play
                        fail_meta = self._recorder.meta.model_copy(
                            update={"capture_complete": False, "capture_failed": True}
                        )
                        from config import AUDIO_SHAPES_DIR
                        sidecar = AUDIO_SHAPES_DIR / fail_meta.npz_file.replace(".npz", ".json")
                        AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
                        sidecar.write_text(fail_meta.model_dump_json(indent=2), encoding="utf-8")
                        self._recorder = None
                        self._capture = None
                        self._recording_uri = None
                        return

                # Drain raw PCM before saving (capture is already stopped)
                raw_pcm = self._capture.drain_pcm() if self._capture else None

                npz_path = self._recorder.save()
                # Mark detection disabled — not useful right now
                marks = []
                meta = self._recorder.meta
                meta.music_marks = marks
                meta.capture_complete = True
                sidecar = npz_path.with_suffix(".json")
                sidecar.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
                self._songs_captured += 1
                logger.info("Audio shape saved: %s", npz_path.name)

                # Write WAV and schedule librosa analysis
                if raw_pcm is not None and len(raw_pcm) > 0:
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

        self._recorder = None
        self._capture = None
        self._recording_uri = None

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


async def _save_wav_and_analyze(meta, raw_pcm, sample_rate: int) -> None:
    """Write a WAV file from captured PCM, enforce retention limit, then run librosa."""
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
        return

    await analyze_async(meta)


# Singleton — import this everywhere
audio_shape_service = AudioShapeService()
