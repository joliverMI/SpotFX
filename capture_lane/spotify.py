"""
The capture lane's Spotify gateway: every call it makes, as ACCOUNT B, in
one place — blocking (spotipy sleeps synchronously on a 429), so the lane
only reaches it through asyncio.to_thread.

FIVE RULES, each a line of code below, not a convention:
  * ACCOUNT B ONLY. The client is api.spotify_capture.capture_client(),
    which never opens the main token file.
  * THE LOCK. That client is a SecondAccountSpotify: every write it sends
    asks the second account's lock (fx/second_account.py) first and is
    refused while it is off — the Settings page's switch, the barrier
    between the system and the second user's music. Nothing here can get
    round it, because the gate is in the client, not in these methods.
  * ONE DEVICE. `play` takes an explicit device id and refuses without one:
    a play with no device goes to whatever account B last used, which could
    be a phone in somebody's pocket. The lane looks the id up by the hidden
    player's exact name.
  * LETTING GO, NEVER A BARE PAUSE. There is no `pause`: the only way this
    lane stops anything is `release`, which pauses only what a fresh read
    shows is the song the system itself started, on the device it started
    it on — never the second user's own playback.
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

    # ── control, one device only, and only while the lock is on ─────────────

    def play(self, device_id: str, uri: str) -> None:
        if not device_id:
            raise NoDevice("refusing to play with no device id")
        self._spaced(MIN_CONTROL_SPACING_S)
        self._client().start_playback(device_id=device_id, uris=[uri], position_ms=0)

    def full_volume(self, device_id: str) -> None:
        if not device_id:
            raise NoDevice("refusing to set a volume with no device id")
        self._spaced(MIN_CONTROL_SPACING_S)
        self._client().volume(100, device_id=device_id)

    # ── letting go: the one write the lock allows, and only of the system's own

    def release(self, *, end_of_song: bool = False) -> dict:
        """Pause the song the system started — if it is still what's playing,
        on the device it started it on — and forget it. `{"paused", "why"}`
        (second_account.is_system_playback's words)."""
        self._spaced(MIN_CONTROL_SPACING_S)
        return self._client().release_system_playback(end_of_song=end_of_song)
