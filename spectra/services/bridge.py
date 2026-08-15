"""The read-only spot-effects bridge — SPECTRA's music feed (report §2.1,
§2.4). ONE-DIRECTIONAL by contract: a WebSocket client on spot-effects'
existing /ws broadcasts plus read-only GETs and analysis-storage reads.
Spot-effects is not modified and never called with a mutation; this seam is
exactly what the S3 process split preserves (the URL doesn't care which
process it lives in).

Consumed broadcasts (services/websocket_manager.py shapes, unchanged):
  "state"          — track uri/title/progress/playing, paused, Dinner
                     Party, Ambient, last_scene_id (trigger-fired scene
                     observation), genres (→ training-profile bucket),
                     timing (spot-effects' own xcorr-derived audio/Spotify
                     -clock correction — see effective_position_ms below).
  "trigger_fired"  — the WHEN of the response engine until spot-effects'
                     trigger engine is replaced; already carries intensity.

xcorr sync (report: SPECTRA xcorr port). spot-effects still owns the audio
capture + xcorr correlation (services/xcorr_core.py, auto_offset_service.py,
systemic_offset.py) — duplicating that into a second OS process would mean a
second sounddevice.InputStream competing for the same PipeWire monitor
spot-effects already has open, the exact multi-consumer starvation
fx/audio_ingest.py's own docstring documents (report §2.2) as needing its
own not-yet-wired fan-out hub even WITHIN one process. So this bridge
doesn't re-derive the offset; it reads the one spot-effects already
computes every tick and already broadcasts as a sibling field next to
`track` on every "state" message (services/websocket_manager.py's
broadcast_state, payload["timing"] = state.timing) — that payload was
simply never parsed here before. `effective_position_ms()` applies it with
spot-effects' own formula (services/trigger_engine.py's
effective_now = now_ms + offset), and services/engine.py's trigger-engine
poll now feeds THAT instead of the raw bridge position, so a migrated
trigger fires at the same music-time spot-effects would have fired it at.
Only `timing.shape_offset_ms` (the audio-alignment term) is ported —
spot-effects' effective_offset_ms also adds ledfx_trigger_buffer_ms and
ledfx_rtt_ms, LedFX-HTTP-write-transport latency compensation for a
write path (api/ledfx_client's LedFX HTTP gate) SPECTRA's own executor
(fx_seam / live_host, in-process or direct-device REST, no LedFX HTTP hop)
doesn't share — a genuine mechanism-differs-in-kind case, not a value worth
guessing at. Degrades honestly like every other bridge feed: no "timing"
yet (older spot-effects, bridge just connected, or bridge down) means
shape_offset_ms() is None and effective_position_ms() falls back to the
raw position — today's pre-port behaviour, never a stall.

Event classification (the response engine's four classes):
  charge / lull / drop        → that class (the fixed phase events).
  scene_update / update_scene / reset_scene / scene_group
                              → a SCENE CHANGE, not a surge — observed for
                                the sequencer's trigger adoption, never fed
                                to the responses block.
  everything else             → FLARE. A trigger fire is a musical accent;
                                the legacy Shape/Color flare lanes and
                                ordinary authored triggers all land here,
                                band-gated by each scene's flare spec.

Degradation is STATED, never silent: bridge down → intensity None (callers
hold 0.5 neutral), no genre bucket, no deferral signals, no moments — the
sequencer ticks nothing and drift holds its arc at neutral.

force_scene_enabled is not broadcast, so it rides a read-only GET
/api/settings poll (sequencer deferral only — Force Scene deliberately
does NOT defer drift; the conductor's deferral reads pause / Dinner Party /
Ambient alone).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

from spectra.services import analysis_reader

logger = logging.getLogger(__name__)

PHASE_CLASSES = ("charge", "lull", "drop")
SCENE_CHANGE_TYPES = ("scene_update", "update_scene", "reset_scene",
                      "scene_group")
RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 30.0
SETTINGS_POLL_S = 15.0


def classify_event(event_type: str) -> Optional[str]:
    """Response class for a trigger_fired event_type; None = scene change."""
    if event_type in PHASE_CLASSES:
        return event_type
    if event_type in SCENE_CHANGE_TYPES:
        return None
    return "flare"


def default_ws_url() -> str:
    url = os.getenv("SPECTRA_BRIDGE_WS_URL")
    if url:
        return url
    return f"ws://127.0.0.1:{os.getenv('SPOTFX_PORT', '8000')}/ws"


def default_http_url() -> str:
    url = os.getenv("SPECTRA_BRIDGE_HTTP_URL")
    if url:
        return url.rstrip("/")
    return f"http://127.0.0.1:{os.getenv('SPOTFX_PORT', '8000')}"


class SpotEffectsBridge:
    """handle_message() is the whole protocol — the WS task is a thin shell
    around it, and the executable specs feed messages directly."""

    def __init__(
        self, *,
        ws_url: str | None = None,
        http_url: str | None = None,
        on_response_event: Callable[[str, float], Awaitable[Any]] | None = None,
        on_track_uri: Callable[[Optional[str]], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ws_url = ws_url or default_ws_url()
        self.http_url = http_url or default_http_url()
        self._on_response_event = on_response_event
        self._on_track_uri = on_track_uri
        self._clock = clock

        self.connected = False
        self._last_message_at: float | None = None
        self._track: dict | None = None
        self._track_received_at: float | None = None
        self._timing: dict | None = None
        self.paused = False
        self.dinner_party = False
        self.ambient = False
        self.force_scene = False
        self.last_scene_id: str | None = None
        self._last_event: dict | None = None
        self.counts = {"state": 0, "trigger_fired": 0, "responses": 0,
                       "scene_changes": 0}
        self._task: asyncio.Task | None = None
        self._settings_task: asyncio.Task | None = None

    # ── message handling (the protocol, socket-free) ─────────────────────────

    async def handle_message(self, payload: dict) -> None:
        self._last_message_at = self._clock()
        kind = payload.get("type")
        if kind == "state":
            self.counts["state"] += 1
            self.paused = bool(payload.get("paused"))
            self.dinner_party = bool(payload.get("dinner_party_mode"))
            self.ambient = bool(payload.get("ambient_mode_enabled"))
            self.last_scene_id = payload.get("last_scene_id") or None
            self._track = payload.get("track")
            self._track_received_at = self._clock()
            self._timing = payload.get("timing") or None
            if self._on_track_uri is not None:
                uri = (self._track or {}).get("spotify_uri")
                await self._on_track_uri(uri)
        elif kind == "trigger_fired":
            self.counts["trigger_fired"] += 1
            event_class = classify_event(payload.get("event_type") or "")
            intensity = payload.get("intensity")
            self._last_event = {
                "at": self._clock(),
                "event_type": payload.get("event_type") or "",
                "event_name": payload.get("event_name") or "",
                "class": event_class,
                "intensity": intensity,
            }
            if event_class is None:
                self.counts["scene_changes"] += 1
                return
            if self._on_response_event is not None:
                self.counts["responses"] += 1
                value = float(intensity) if isinstance(
                    intensity, (int, float)) else 0.5
                await self._on_response_event(event_class, value)

    # ── feeds (what the engine reads) ────────────────────────────────────────

    def track_uri(self) -> Optional[str]:
        return (self._track or {}).get("spotify_uri")

    def is_playing(self) -> bool:
        """True only when spot-effects is actively playing a track right
        now — not paused, a track is loaded, and its own broadcast
        is_playing flag agrees. spectra/services/dark_light.py gates its
        snapshot-restore repaint on this: forcing a stale pre-dark look over
        a room that should be tracking live music is the same shape of
        mistake as freezing the room under Ambient during a song — see that
        module's docstring."""
        return (not self.paused and self._track is not None
                and bool(self._track.get("is_playing")))

    def track_position_ms(self) -> Optional[int]:
        """Broadcast progress + elapsed-since-received while playing."""
        if not self._track:
            return None
        progress = self._track.get("progress_ms")
        if not isinstance(progress, (int, float)):
            return None
        if self._track.get("is_playing") and self._track_received_at is not None:
            progress += (self._clock() - self._track_received_at) * 1000.0
        return int(progress)

    def shape_offset_ms(self) -> Optional[int]:
        """spot-effects' audio-alignment xcorr correction for the current
        song (services/trigger_engine.py's _shape_offset_ms, mirrored onto
        state.timing every tick) — None when unknown (no broadcast yet,
        older spot-effects, or bridge down)."""
        if not self._timing:
            return None
        value = self._timing.get("shape_offset_ms")
        return int(value) if isinstance(value, (int, float)) else None

    def effective_position_ms(self) -> Optional[int]:
        """track_position_ms() corrected the same way spot-effects' own
        trigger engine corrects it (effective_now = now_ms + offset,
        services/trigger_engine.py:_effective_offset_ms) — the value the
        SPECTRA trigger clock should tick against so a migrated trigger
        fires at the same music-time spot-effects would fire it at. Falls
        back to the raw position when the offset isn't known yet, never
        blocking the clock."""
        position = self.track_position_ms()
        if position is None:
            return None
        offset = self.shape_offset_ms()
        return position if offset is None else position + offset

    def intensity(self) -> Optional[float]:
        """Section energy at the playback position (RAW ms — the standing
        rule); None when unknowable (callers hold 0.5 neutral, stated)."""
        uri = self.track_uri()
        position = self.track_position_ms()
        if uri is None or position is None:
            return None
        return analysis_reader.section_energy_at(uri, position)

    def is_playing(self) -> Optional[bool]:
        """Whether spot-effects currently reports a track actively
        playing — the single playback signal the Ambient music-precedence
        gate reads (services/ambient_music_gate.py). Matches every other
        feed on this class (track_uri/track_position_ms/intensity): trusts
        the LAST reported state regardless of the current `connected`
        flag, so a momentary reconnect gap doesn't erase a moment-old
        signal — a transient blip must not read as "unknown" and disturb
        an already-settled Ambient decision (ambient_music_gate's
        docstring). None only when there has been no signal at all yet
        (fresh bridge, no message ever received) — never guessed. False
        both when a track is loaded but paused AND when spot-effects
        reports no track at all (nothing to play is not playing, same as
        "the music ended")."""
        if self._last_message_at is None:
            return None
        if not self._track:
            return False
        return bool(self._track.get("is_playing"))

    def track_genres(self) -> list[str]:
        return list((self._track or {}).get("genres") or [])

    def genre_bucket(self) -> Optional[str]:
        genres = self.track_genres()
        if not genres:
            return None
        return analysis_reader.genre_bucket(genres)

    def song_scaling_factor(self) -> float:
        """The current song's per-song genre+bass render-intensity scale
        (spectra.services.intensity_scale, the SpotFX v2 port) — the
        `song_scaling_factor` term in intensity_scale.combine_measured_and_
        scale's headroom formula. Neutral 1.0 with no track (never blocks a
        fire); every other degradation (no bass data, no genre match) is
        handled inside intensity_scale.song_scaling_factor itself."""
        uri = self.track_uri()
        if uri is None:
            return 1.0
        from spectra.services import intensity_scale
        return intensity_scale.song_scaling_factor(uri, self.track_genres())

    def conductor_deferral(self) -> Optional[str]:
        """Pause / Dinner Party / Ambient hold drift; Force Scene does NOT
        (a pinned scene keeps its declared life)."""
        if self.paused:
            return "paused"
        if self.dinner_party:
            return "dinner_party"
        if self.ambient:
            return "ambient"
        return None

    def sequencer_deferral(self) -> Optional[str]:
        if self.force_scene:
            return "force_scene"
        return self.conductor_deferral()

    def trigger_scene_id(self) -> Optional[str]:
        return self.last_scene_id

    # ── the socket shell ─────────────────────────────────────────────────────

    async def _consume(self) -> None:
        import websockets
        backoff = RECONNECT_MIN_S
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.connected = True
                    backoff = RECONNECT_MIN_S
                    logger.info("bridge: connected to %s", self.ws_url)
                    async for raw in ws:
                        try:
                            await self.handle_message(json.loads(raw))
                        except Exception:
                            logger.exception("bridge: message handling failed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.connected:
                    logger.warning("bridge: connection lost (%s)", exc)
                self.connected = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_S)

    async def _poll_settings(self) -> None:
        import httpx
        while True:
            if self.connected:
                try:
                    async with httpx.AsyncClient(base_url=self.http_url,
                                                 timeout=5.0) as client:
                        resp = await client.get("/api/settings")
                        resp.raise_for_status()
                        self.force_scene = bool(
                            resp.json().get("force_scene_enabled"))
                except Exception:
                    pass   # transient; the WS loop owns connectivity truth
            await asyncio.sleep(SETTINGS_POLL_S)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._consume())
        if self._settings_task is None or self._settings_task.done():
            self._settings_task = asyncio.create_task(self._poll_settings())

    async def stop(self) -> None:
        for task in (self._task, self._settings_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._task = self._settings_task = None
        self.connected = False

    # ── observability ────────────────────────────────────────────────────────

    def status(self) -> dict:
        now = self._clock()
        return {
            "connected": self.connected,
            "ws_url": self.ws_url,
            "last_message_age_s": (round(now - self._last_message_at, 1)
                                   if self._last_message_at is not None
                                   else None),
            "track": ({
                "uri": self.track_uri(),
                "title": (self._track or {}).get("title"),
                "is_playing": (self._track or {}).get("is_playing"),
                "position_ms": self.track_position_ms(),
                "effective_position_ms": self.effective_position_ms(),
                "shape_offset_ms": self.shape_offset_ms(),
            } if self._track else None),
            "deferral": self.sequencer_deferral(),
            "intensity": self.intensity(),
            "genre_bucket": self.genre_bucket(),
            "last_event": self._last_event,
            "counts": dict(self.counts),
        }
