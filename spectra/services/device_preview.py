"""The device-preview strip's backend — a read-only relay from LedFX's own
visualisation WebSocket (report: data/spectra-device-preview-plan/report.md)
to SPECTRA's frontend, plus the small favourites/pause store behind it.
Approved verbatim by the owner alongside the pause requirement: "Great,
move forward, but add a pause button to pause the preview and conserve
resources."

Transport (report §2, read from the real LedFX fork at
/home/javi/ledfx-src): every virtual's render thread flushes to the
physical device FIRST, then fires VisualisationUpdateEvent off-thread —
LedFX's own event loop does the per-vis_id 30fps throttle, the ≤81-point
downsample, and the base64/list serialization, all before this relay ever
sees a frame. A client subscribes with one {"type": "subscribe_event",
"event_type": "visualisation_update", "event_filter": {"vis_id": ...,
"is_device": false}} message per virtual and gets back {"id", "type":
"event", "event_type": "visualisation_update", "is_device", "vis_id",
"pixels", "shape"} — relayed to the browser unchanged (pixels stay
base64-or-list exactly as LedFX encoded them; SPECTRA does not decode or
reshape server-side, the frontend does, same division of labour as LedFX's
own frontend). This module throttles FURTHER on top of that (RELAY_TARGET_FPS,
independent of LedFX's own visualisation_fps config, which this never
touches) — a glance preview doesn't need 30fps of motion fidelity.

THE PAUSE MUST GENUINELY STOP THE WORK (owner's own words, and the reason
this got a whole section instead of a one-line toggle): pausing must drop
the upstream LedFX connection itself, not just blank the display while the
feed keeps running underneath — that would be a control that reports
"paused" while still consuming exactly what he asked to save, the same
defect class this project spent two days removing elsewhere (CLAUDE.md).
DevicePreviewRelay._consume's inner receive loop polls a cleared
_active_event on a short timeout instead of blocking forever on ws.recv(),
so pause() (or a favourites change) breaks out of the `async with
websockets.connect(...)` block PROMPTLY — that block's exit is what
actually closes the socket. connected flips False and stays False until
resume() re-opens a fresh connection; frames_relayed/frames_received stop
incrementing the moment the socket closes, not merely when the frontend
stops rendering. tests/test_device_preview.py proves this against a real
fake-LedFX WebSocket server: the server's own live connection count drops
to zero on pause, not just the relay's local flag.

Favourites default (report §4): when the store is empty, auto-populate
from spectra.services.room_topology.genuinely_driven_virtual_ids() — the
same ground truth the S3 activation gate validates fx-live/config.json's
declared-active virtuals against (CLAUDE.md's "expected_active_ids"
section) — sorted, capped at DEFAULT_FAVORITES_CAP, rather than every raw
virtual LedFX's config happens to declare (mask/background layers,
gap-dummy placeholders). Never a legacy read-only decision; the owner can
always override it with an explicit favourites list.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from spectra import config
from spectra.services.ws import WSManager

logger = logging.getLogger(__name__)

DEFAULT_FAVORITES_CAP = 4
RELAY_TARGET_FPS = 8.0
RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 30.0
# How often the receive loop checks for pause/favourites-changed while
# connected — this bounds how quickly a pause actually closes the socket,
# so it must stay well under a human's sense of "immediate".
POLL_INTERVAL_S = 0.2

preview_ws_manager = WSManager()


class DevicePreviewState(BaseModel):
    favorite_virtual_ids: list[str] = Field(default_factory=list)
    paused: bool = False


def load_state() -> DevicePreviewState:
    path = config.DEVICE_PREVIEW_FILE
    if path.exists():
        try:
            return DevicePreviewState(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return DevicePreviewState()
    return DevicePreviewState()


def save_state(state: DevicePreviewState) -> None:
    path = config.DEVICE_PREVIEW_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(json.loads(state.model_dump_json()), fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def default_favorite_ids() -> list[str]:
    from spectra.services import room_topology
    return sorted(room_topology.genuinely_driven_virtual_ids())[:DEFAULT_FAVORITES_CAP]


def effective_favorite_ids(state: Optional[DevicePreviewState] = None) -> list[str]:
    """Stored favourites when he's chosen any; otherwise the sensible
    zero-configuration default (report §4's "works the first time he opens
    it" requirement)."""
    state = state or load_state()
    return (list(state.favorite_virtual_ids) if state.favorite_virtual_ids
            else default_favorite_ids())


class DevicePreviewRelay:
    """One upstream WebSocket connection to LedFX, subscribed to the
    current favourite virtuals, fanned out to every connected SPECTRA
    frontend client. connected/paused are read by both the status API and
    the tests that prove pause actually drops the socket."""

    def __init__(
        self, *,
        ws_url: Optional[str] = None,
        favorite_ids: Optional[list[str]] = None,
        paused: bool = False,
        target_fps: float = RELAY_TARGET_FPS,
        on_frame: Optional[Callable[[dict], Awaitable[None]]] = None,
        on_status_change: Optional[Callable[[], Awaitable[None]]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ws_url = ws_url or config.ledfx_ws_url()
        self._favorite_ids: list[str] = list(favorite_ids or [])
        self.paused = paused
        self.target_fps = target_fps
        self._min_interval = (1.0 / target_fps) if target_fps > 0 else 0.0
        self._on_frame = on_frame
        self._on_status_change = on_status_change
        self._clock = clock

        self.connected = False
        self.connect_count = 0
        self.frames_received = 0
        self.frames_relayed = 0
        self._last_relayed_at: dict[str, Optional[float]] = {}
        self._active_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._sync()

    def _wants_upstream(self) -> bool:
        return (not self.paused) and bool(self._favorite_ids)

    def _sync(self) -> None:
        if self._wants_upstream():
            self._active_event.set()
        else:
            self._active_event.clear()

    def set_favorites(self, ids: list[str]) -> None:
        self._favorite_ids = list(ids)
        self._last_relayed_at.clear()
        self._sync()

    def pause(self) -> None:
        self.paused = True
        self._sync()

    def resume(self) -> None:
        self.paused = False
        self._sync()

    async def _set_connected(self, value: bool) -> None:
        """The single place `connected` is ever assigned once the relay is
        running — every status push (the frontend badge's honesty) flows
        through here, not just the explicit pause()/resume() API calls.
        Without this, a reconnect that finishes AFTER the pause/resume
        handler's own one-shot broadcast (the connect attempt is
        asynchronous; resume() returning doesn't mean connected yet) would
        never tell an already-open frontend tab it's live again — the
        badge would sit on "reconnecting…" forever despite the server
        being fine (caught live in the smoke test, 2026-08-15)."""
        if self.connected != value:
            self.connected = value
            if self._on_status_change is not None:
                await self._on_status_change()

    def status(self) -> dict:
        return {
            "paused": self.paused,
            "connected": self.connected,
            "favorite_virtual_ids": list(self._favorite_ids),
            "target_fps": self.target_fps,
            "frames_relayed": self.frames_relayed,
        }

    async def _subscribe(self, ws, ids: list[str]) -> None:
        for vid in ids:
            await ws.send(json.dumps({
                "id": f"device-preview:{vid}",
                "type": "subscribe_event",
                "event_type": "visualisation_update",
                "event_filter": {"vis_id": vid, "is_device": False},
            }))

    async def _handle_frame(self, msg: dict) -> None:
        if msg.get("event_type") != "visualisation_update":
            return
        self.frames_received += 1
        vis_id = msg.get("vis_id")
        now = self._clock()
        last = self._last_relayed_at.get(vis_id)
        if last is not None and (now - last) < self._min_interval:
            return
        self._last_relayed_at[vis_id] = now
        self.frames_relayed += 1
        if self._on_frame is not None:
            await self._on_frame({
                "type": "device_preview_frame",
                "vis_id": vis_id,
                "pixels": msg.get("pixels"),
                "shape": msg.get("shape"),
                "is_device": bool(msg.get("is_device", False)),
            })

    async def _consume(self) -> None:
        import websockets
        backoff = RECONNECT_MIN_S
        while True:
            await self._active_event.wait()
            ids = list(self._favorite_ids)
            if not ids:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await self._subscribe(ws, ids)
                    await self._set_connected(True)
                    self.connect_count += 1
                    backoff = RECONNECT_MIN_S
                    logger.info("device_preview: connected to %s (%d favourite(s))",
                               self.ws_url, len(ids))
                    while self._active_event.is_set() and self._favorite_ids == ids:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=POLL_INTERVAL_S)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            await self._handle_frame(json.loads(raw))
                        except Exception:
                            logger.exception("device_preview: frame handling failed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.connected:
                    logger.warning("device_preview: connection lost (%s)", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_S)
            finally:
                # The async-with above has already closed the socket by the
                # time we get here (pause, favourites change, error, or
                # cancellation) — this just makes the state honest, AND
                # pushes it, for whoever's reading/watching status() next.
                await self._set_connected(False)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self.connected = False


async def _broadcast_frame(payload: dict) -> None:
    await preview_ws_manager.broadcast(payload)


async def _broadcast_status() -> None:
    await preview_ws_manager.broadcast({"type": "device_preview_status", **relay.status()})


relay = DevicePreviewRelay(on_frame=_broadcast_frame, on_status_change=_broadcast_status)


def init_from_storage() -> None:
    """Load persisted favourites/pause state into the live relay — called
    once at process start, and safe to call again any time the store might
    have drifted from the relay's in-memory copy."""
    state = load_state()
    relay.set_favorites(effective_favorite_ids(state))
    relay.paused = state.paused
    relay._sync()


async def start() -> None:
    init_from_storage()
    relay.start()


async def stop() -> None:
    await relay.stop()


# The API layer's own name for the same push _set_connected already fires
# on every connect/disconnect transition — kept as one function so a PUT/
# pause/resume handler's explicit call and an internal reconnect can never
# drift into two different broadcast shapes.
broadcast_status = _broadcast_status


def get_favorites() -> dict:
    state = load_state()
    return {
        "favorite_virtual_ids": state.favorite_virtual_ids,
        "effective_virtual_ids": effective_favorite_ids(state),
        "is_default": not state.favorite_virtual_ids,
    }


def set_favorite_ids(ids: list[str]) -> dict:
    state = load_state()
    # De-dup, preserve the order he picked them in.
    state.favorite_virtual_ids = list(dict.fromkeys(ids))
    save_state(state)
    relay.set_favorites(effective_favorite_ids(state))
    return get_favorites()


def pause() -> dict:
    state = load_state()
    state.paused = True
    save_state(state)
    relay.pause()
    return relay.status()


def resume() -> dict:
    state = load_state()
    state.paused = False
    save_state(state)
    relay.resume()
    return relay.status()
