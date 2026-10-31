"""
The capture lane's Spotify gateway: every call it makes, as ACCOUNT B, in
one place — blocking (spotipy sleeps synchronously on a 429), so the lane
only reaches it through asyncio.to_thread.

THREE RULES, each a line of code below, not a convention:
  * ACCOUNT B ONLY. The client is api.spotify_capture.capture_client(),
    which never opens the main token file.
  * ONE DEVICE. `play` and `pause` take an explicit device id and refuse
    without one: a play with no device goes to whatever account B last used,
    which could be a phone in somebody's pocket. The lane looks the id up by
    the hidden player's exact name.
  * SPACED. Control calls are at least MIN_CONTROL_SPACING_S apart (Absorb's
    gateway pattern), and so are reads, at READ_SPACING_S, so a bug that
    loops can never hammer the API.

`CaptureGateway` is the interface; tests hand the lane a fake with the same
methods.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

MIN_CONTROL_SPACING_S = 0.5
READ_SPACING_S = 0.5


class NoDevice(ValueError):
    """A control call without a device id — refused before it leaves."""


class CaptureGateway:
    def __init__(self, sp=None) -> None:
        self._sp = sp
        self._lock = threading.Lock()
        self._last = 0.0

    def _client(self):
        if self._sp is None:
            from api.spotify_capture import capture_client
            self._sp = capture_client()
        return self._sp

    def _spaced(self, gap: float) -> None:
        with self._lock:
            wait = gap - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    # ── reads ───────────────────────────────────────────────────────────────

    def me(self) -> dict:
        self._spaced(READ_SPACING_S)
        return self._client().me() or {}

    def devices(self) -> list[dict]:
        self._spaced(READ_SPACING_S)
        return list((self._client().devices() or {}).get("devices") or [])

    def playback(self) -> Optional[dict]:
        self._spaced(READ_SPACING_S)
        return self._client().current_playback()

    # ── control, one device only ────────────────────────────────────────────

    def play(self, device_id: str, uri: str) -> None:
        if not device_id:
            raise NoDevice("refusing to play with no device id")
        self._spaced(MIN_CONTROL_SPACING_S)
        self._client().start_playback(device_id=device_id, uris=[uri], position_ms=0)

    def pause(self, device_id: str) -> None:
        if not device_id:
            raise NoDevice("refusing to pause with no device id")
        self._spaced(MIN_CONTROL_SPACING_S)
        self._client().pause_playback(device_id=device_id)

    def full_volume(self, device_id: str) -> None:
        if not device_id:
            raise NoDevice("refusing to set a volume with no device id")
        self._spaced(MIN_CONTROL_SPACING_S)
        self._client().volume(100, device_id=device_id)
