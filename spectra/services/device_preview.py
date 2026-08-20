"""The device-preview strip's backend — a read-only relay of live pixel
frames to SPECTRA's frontend, plus the small favourites/pause store behind
it. Approved verbatim by the owner alongside the pause requirement: "Great,
move forward, but add a pause button to pause the preview and conserve
resources."

SOURCE IS OWNERSHIP-ROUTED (2026-08-16 correction, matching
spectra/services/fx_seam.py's own dispatch — "read from whichever writer is
truly driving the lights right now", not always LedFX): the original build
always assumed the external LedFX process was the writer and relayed its
`visualisation_update` WebSocket unconditionally. That is wrong in his
normal operating state — LedFX is deliberately stopped whenever SPECTRA
owns the light path (S3), so the original relay sat permanently
"reconnecting…" against nothing. `_source_mode()` below picks the real
source per the SAME light-ownership record fx_seam reads:

  owner == spot-effects   the external LedFX process is the real writer —
                          relay its `visualisation_update` WebSocket, same
                          as the original build (`_consume_ledfx`).
  owner == spectra        her in-process fx/ pipeline is the real writer —
                          NO websocket, NO network hop: subscribe directly
                          to `fx.events.Event.VIRTUAL_UPDATE` on the live
                          `spectra.services.live_host.live.host` (the SAME
                          event the frame-freshness tap already listens
                          for, fired by the real render thread after
                          assemble+flush — this IS the literal pixel buffer
                          being written to the device, not a re-derivation
                          of it) via `_consume_facade`.
  handing-over / released / spectra-not-yet-active
                          nobody is driving — report `connected: False`,
                          `source: "none"`, and wait; there is nothing to
                          relay and nothing to fall back to.

Licence position, re-examined fresh for this source (not inherited from the
LedFX-websocket reasoning below, which was about a different codepath):
`fx/` is vendored under GPL-3.0 (`fx/LICENSE`, see `fx/VENDOR.md`) and
already imported throughout spectra/ (fx_seam, live_host, ambient.py,
dark_light.py, ...) — subscribing to its own `Event.VIRTUAL_UPDATE` here is
the same kind of use those modules already make, not a new incorporation.
What would NOT be safe is porting `ledfx/core.py`'s
`setup_visualisation_events`/`handle_visualisation_update` (the throttle +
≤81-point downsample + base64 serialize logic quoted below) — `core.py` was
explicitly `Dropped entirely` from the fx/ vendoring (VENDOR.md), so it is
not part of this repo's GPL-3.0 subtree at all; lifting it now would be a
fresh, deliberate act of incorporating that code that Stage 1 chose not to
do. `_facade_frame_payload` below is an independent, much simpler
implementation of the same generic idea (numpy pixels -> base64 bytes
+ a throttle-by-timestamp), reusing THIS module's own pre-existing,
SpotFX-authored throttle bookkeeping (`_throttle_ok`, MIT-licensed, already
here for the LedFX path) rather than core.py's; its base64 step is a
one-line stdlib call, not a port of core.py's own encode logic. The
frontend's `decodePixels()` (api/devicePreviewWs.ts) needed no change and
so carries no new exposure either: it already independently reimplements
(not copies) LedFX-Frontend-v2's AGPL-3.0 decode behaviour, and this repo
has no other relationship with that project — the wire shape emitted by
both source paths is identical (dict keys, and, since 2026-08-20, the
`pixels` encoding too — see `_facade_frame_payload`'s own docstring), so
that concern is untouched.

LedFX transport (report §2, read from the real LedFX fork at
/home/javi/ledfx-src, used only when owner == spot-effects): every
virtual's render thread flushes to the physical device FIRST, then fires
VisualisationUpdateEvent off-thread — LedFX's own event loop does the
per-vis_id 30fps throttle, the ≤81-point downsample, and the base64/list
serialization, all before this relay ever sees a frame. A client subscribes
with one {"type": "subscribe_event", "event_type": "visualisation_update",
"event_filter": {"vis_id": ..., "is_device": false}} message per virtual
and gets back {"id", "type": "event", "event_type": "visualisation_update",
"is_device", "vis_id", "pixels", "shape"} — relayed to the browser
unchanged (pixels stay base64-or-list exactly as LedFX encoded them;
SPECTRA does not decode or reshape server-side, the frontend does, same
division of labour as LedFX's own frontend). This module throttles FURTHER
on top of that (RELAY_TARGET_FPS, independent of LedFX's own
visualisation_fps config, which this never touches) — a glance preview
doesn't need 30fps of motion fidelity. The in-process facade path
(`_consume_facade`) applies the SAME RELAY_TARGET_FPS throttle itself,
since nothing upstream of it does that throttling for it.

PREVIEW FRAME DELIVERY — pacing, not payload (2026-08-20,
data/preview-skips-under-fast-motion/, his SECOND "LedFX was better"
report: "the preview might look better but when there are fast motions it
skips still... LedFX was better"). PR #143 fixed BYTES PER FRAME (the
base64 encoding above) — real, measured, 3.4x smaller. Bytes-per-frame is
constant regardless of motion, so it could not have been the cause of a
MOTION-dependent symptom, and it wasn't: "skips under fast motion" is a
DELIVERY-timing complaint, not a volume one, and it survived that fix
untouched.

Read LedFX's real client fan-out a second time (`ledfx/api/websocket.py`
`WebsocketConnection`), this time for what happens AFTER encoding, not
before: `send()` never queues a vis frame for delivery — it drops it into
a per-vis_id SINGLE-SLOT MAILBOX (`self._vis_slots[vis_id] = message`,
unconditionally overwriting whatever hasn't been sent yet), and exactly
ONE `_sender()` task per connection drains that mailbox (latest value
only — anything still sitting there when a newer frame lands is silently
dropped, never queued) plus a separate ordered control queue, writing to
the socket one message at a time. Two properties that gives LedFX and
SPECTRA's relay never had: (1) a client that can't keep up is never handed
a backlog — it only ever gets told the CURRENT state, so falling behind
reads as "skip to now," not "stutter through a growing queue"; (2) exactly
one coroutine ever writes to a given socket at a time.

SPECTRA's relay did neither. `_consume_facade`'s `on_update` fired a bare
`asyncio.create_task(self._on_frame(payload))` per accepted frame —
RELAY_TARGET_FPS=8 caps ACCEPTANCE, but nothing capped DELIVERY time — and
`_on_frame` was `preview_ws_manager.broadcast`, which wraps each client's
`ws.send_json()` in `asyncio.wait_for(..., timeout=SEND_DEADLINE_S=0.25s)`
(`spectra/services/ws.py`). Two real consequences, neither about bytes:
whenever one send takes longer than one frame interval (125ms) — ordinary
on a real remote/VPN link, no motion required, just link jitter — the next
frame's broadcast task starts before the previous one finishes, so two or
more coroutines can be mid-write on the SAME connection at once (Starlette
gives no guarantee concurrent `send()` calls on one WebSocket interleave
safely); and whenever a send exceeds 250ms, `asyncio.wait_for` raises,
`broadcast()` treats that as connection failure and calls
`self.disconnect(ws)` — which only does `self._connections.remove(ws)`. It
never calls `ws.close()`. The browser's own WebSocket is left fully OPEN
(`devicePreviewWs.ts`'s `onclose` — its only reconnect trigger — never
fires) while the server has silently stopped sending it anything, forever.
Not jitter: a permanent, invisible stall that looks exactly like his
report and never self-heals. Fast motion doesn't cause this directly —
it raises how often SOME send exceeds 250ms (more/larger state churn over
an already-jittery link) — but one occurrence is enough to strand a tab
for the rest of the session, which is consistent with a complaint that
gets worse the longer/more active a session runs.

Fix (`_PreviewFrameSender`/`PreviewFrameHub` below — ported to fit, not
copied verbatim): status pushes (pause/resume/connect — low frequency,
reliability matters more than latency there) stay on
`preview_ws_manager`'s existing ordered broadcast, unchanged — LedFX's own
control-queue half. Frame delivery gets its own per-connection
single-slot mailbox + one dedicated sender task, mirroring
`WebsocketConnection.send()`/`_sender()`: a new frame for a vis_id already
waiting to be sent overwrites it instead of queuing, and the sender loop
is the only writer for that socket, ever — no `asyncio.create_task` per
frame, so concurrent sends to one connection are impossible by
construction rather than merely unlikely. `FRAME_SEND_TIMEOUT_S` still
guards a genuinely wedged socket, but generously — it is not a per-frame
race against RELAY_TARGET_FPS — and when it actually trips, the sender
calls `ws.close()` for real before giving up, so a genuinely dead client
gets the close frame that lets `onclose` fire and reconnect, instead of
the silent strand above. Evidence:
`scripts/check_device_preview_frame_pacing.py` (the concurrent-send
violations and the false-eviction-without-close, both reproduced against
the OLD path for comparison and shown absent on the new one — a
throttled-loopback/injected-latency REMOTE-EQUIVALENT proxy, not a test
against his real link, which this task never touched) +
`tests/test_device_preview.py` section 6.

THE PAUSE MUST GENUINELY STOP THE WORK (owner's own words, and the reason
this got a whole section instead of a one-line toggle): pausing must drop
the live connection to the source itself, not just blank the display while
the feed keeps running underneath — that would be a control that reports
"paused" while still consuming exactly what he asked to save, the same
defect class this project spent two days removing elsewhere (CLAUDE.md).
This bar is re-proven per source, not inherited from one to the other:
  - LedFX path: DevicePreviewRelay._consume_ledfx's inner receive loop
    polls a cleared _active_event on a short timeout instead of blocking
    forever on ws.recv(), so pause() (or a favourites change) breaks out of
    the `async with websockets.connect(...)` block PROMPTLY — that block's
    exit is what actually closes the socket. Proven against a real
    fake-LedFX WebSocket server: the server's own live connection count
    drops to zero on pause, not just the relay's local flag.
  - Facade path: `_consume_facade` removes its `Event.VIRTUAL_UPDATE`
    listener from the live FxHost's event bus the same way — the listener
    is gone from `host.events`' own registry, not just ignored locally, so
    an event fired directly at the host while paused calls nothing.
Both paths: connected flips False and stays False until resume() re-opens;
frames_relayed/frames_received stop incrementing the moment the connection
drops, not merely when the frontend stops rendering.
tests/test_device_preview.py proves this against a real fake-LedFX
WebSocket server (LedFX path) and a real headless FxHost with a genuine
render thread (facade path).

Favourites default (report §4): when the store is empty, auto-populate
from spectra.services.room_topology.genuinely_driven_virtual_ids() — the
same ground truth the S3 activation gate validates fx-live/config.json's
declared-active virtuals against (CLAUDE.md's "expected_active_ids"
section) — sorted, capped at DEFAULT_FAVORITES_CAP, rather than every raw
virtual LedFX's config happens to declare (mask/background layers,
gap-dummy placeholders). Never a legacy read-only decision; the owner can
always override it with an explicit favourites list.

HIDDEN-TAB AUTO-PAUSE (OQ-7, decided 2026-08-15 — docs/SPECTRA_SPEC.md):
a SEPARATE, ephemeral mechanism from the sticky pause above, on purpose —
his own sticky pause() is a deliberate choice he'd have to remember to
undo, and an automatic one must never look or persist like that (the
"pause requirement" section of the plan report, restated in the module
docstring above). Rather than reusing pause()/resume() — which would
black out every OTHER open tab too, since paused/connected are relay-wide
state fanned out to every /device-preview/ws client — auto-pause is
DEMAND-DRIVEN: `_wants_upstream()` also requires at least one connected
downstream viewer (`has_viewers`, wired to `preview_ws_manager.
client_count() > 0`). A hidden tab's own frontend closes its own
downstream WebSocket (spectra/web/src/api/devicePreviewWs.ts); when the
last viewer disconnects, the relay itself drops the upstream connection
(whichever source is live) — the SAME genuine-stop mechanism pause() uses,
not a weaker imitation — and a second viewer reconnecting (tab visible again,
or another tab still open) reopens it. This composes correctly with
multiple tabs for free: the upstream feed only ever goes quiet when
NOBODY is watching, never because one tab looked away while another
didn't, and it never touches the persisted `paused` flag. The frontend's
own knowledge of "I closed this deliberately" (not a real outage) is what
drives the distinct "idle — tab hidden" badge; the server has nothing to
tell it apart from a plain zero-viewer moment because, by definition,
nobody is there to show a badge to.
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
# Guards a genuinely wedged frame-sender socket only — generous on purpose,
# not a per-frame race against RELAY_TARGET_FPS's 125ms cadence the way the
# old SEND_DEADLINE_S=0.25s broadcast timeout was (see the module docstring's
# "PREVIEW FRAME DELIVERY" section for why that raced real remote-link
# jitter and silently stranded clients).
FRAME_SEND_TIMEOUT_S = 10.0

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


def _source_mode() -> str:
    """Which world actually renders right now, read off the SAME light-
    ownership record spectra/services/fx_seam.py routes writes by —
    "facade" (in-process fx/, zero network hop), "ledfx" (the external
    LedFX process, over its visualisation websocket), or "none" (handing
    over, released, or spectra owns but her live stack isn't up yet — e.g.
    the brief window at process start before handover.resume_own_room()
    finishes). Never cached: ownership can change under a running relay
    (a handover, a panic release), and the consume loop re-checks this on
    its own POLL_INTERVAL_S cadence, same as it already does for
    pause/favourites."""
    from fx import light_ownership
    from spectra.services.live_host import live

    owner = light_ownership.load().owner
    if owner == light_ownership.SPECTRA:
        return "facade" if live.active else "none"
    if owner == light_ownership.SPOT_EFFECTS:
        return "ledfx"
    return "none"


def _facade_frame_payload(vis_id: str, pixels, host) -> dict:
    """The in-process equivalent of a relayed LedFX visualisation_update
    frame (module docstring's licence note explains why this is a fresh,
    independent implementation, not a port of ledfx/core.py's
    dropped-from-vendoring serialize logic). `pixels` is the real
    per-virtual buffer fx/virtuals.py just flushed to the device
    (fx.events.VirtualUpdateEvent.pixels), shape (pixel_count, 3).

    ENCODING MATCHES LEDFX'S OWN DEFAULT (fixed 2026-08-20, his report
    "the frame rate on the preview is still terrible... I'm always on a
    remote computer, but LEDFx previews were really good" —
    data/preview-frame-rate-is-still-bad-over-rem-dhvp/): base64 of the
    raw interleaved r,g,b bytes, exactly `transmission_mode="compressed"`
    (ledfx/config.py's own default, `ledfx/core.py::handle_visualisation_
    update`'s `pybase64.b64encode(bytes(pixels...))`). This used to emit a
    JSON list of three per-channel lists ("uncompressed" shape) instead —
    correct in structure (the frontend's `decodePixels()` in
    api/devicePreviewWs.ts already handles both, written to match LedFX's
    own two transmission modes) but far heavier on the wire: a JSON int
    array costs ~4 bytes per channel value (digits + comma) versus 4/3
    bytes per byte for base64, a ~2.7x difference that scales with pixel
    count — for crystal-mapper (2664 px) the prior list encoding measured
    ~29.4KB/frame at 8fps (docs/SPECTRA_SPEC.md §43); base64 cuts that to
    ~3.5KB/frame, same resolution, same shape, zero downsampling. §43's
    own prior investigation into this exact "choppy preview" complaint
    measured RENDER (DOM vs canvas) and ruled out payload size — but did
    so by timing local JSON.parse/decode cost only, never actual network
    transfer over his real remote link; that local measurement is still
    true and still irrelevant to why bytes-on-the-wire matter for him.
    Deliberately NOT reintroducing LedFX's `visualisation_maxlen≈81`
    downsample cap — that was evaluated and rejected in the same PR for a
    real, still-standing reason (his own "I don't see any Matrix for The
    Matrix previews" ask): downsampling drops points, this only changes
    how the same points are written on the wire. No frontend change is
    needed — `decodePixels()` already parses this exact shape; it just
    never received it from this path before."""
    import base64

    import numpy as np

    virtual = host.virtuals.get(vis_id) if host is not None else None
    rows = max(1, virtual.rows) if virtual is not None else 1
    pixel_count = int(pixels.shape[0])
    cols = pixel_count // rows if rows else pixel_count
    raw = np.ascontiguousarray(np.clip(pixels, 0, 255).astype(np.uint8)).tobytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return {
        "type": "device_preview_frame",
        "vis_id": vis_id,
        "pixels": encoded,
        "shape": [rows, cols],
        "is_device": False,
    }


class DevicePreviewRelay:
    """One live connection to whichever source is actually driving the
    lights (`_source_mode()` — LedFX's own websocket, or an in-process
    subscription to SPECTRA's own facade render events), subscribed to the
    current favourite virtuals, fanned out to every connected SPECTRA
    frontend client. connected/paused are read by both the status API and
    the tests that prove pause actually drops the connection."""

    def __init__(
        self, *,
        ws_url: Optional[str] = None,
        favorite_ids: Optional[list[str]] = None,
        paused: bool = False,
        target_fps: float = RELAY_TARGET_FPS,
        on_frame: Optional[Callable[[dict], Awaitable[None]]] = None,
        on_status_change: Optional[Callable[[], Awaitable[None]]] = None,
        clock: Callable[[], float] = time.monotonic,
        has_viewers: Callable[[], bool] = lambda: True,
    ) -> None:
        self.ws_url = ws_url or config.ledfx_ws_url()
        self._favorite_ids: list[str] = list(favorite_ids or [])
        self.paused = paused
        self.target_fps = target_fps
        self._min_interval = (1.0 / target_fps) if target_fps > 0 else 0.0
        self._on_frame = on_frame
        self._on_status_change = on_status_change
        self._clock = clock
        self._has_viewers = has_viewers

        self.connected = False
        self.connect_count = 0
        self.frames_received = 0
        self.frames_relayed = 0
        self._last_relayed_at: dict[str, Optional[float]] = {}
        self._active_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._sync()

    def _wants_upstream(self) -> bool:
        return (not self.paused) and bool(self._favorite_ids) and self._has_viewers()

    def _sync(self) -> None:
        if self._wants_upstream():
            self._active_event.set()
        else:
            self._active_event.clear()

    def set_favorites(self, ids: list[str]) -> None:
        self._favorite_ids = list(ids)
        self._last_relayed_at.clear()
        self._sync()

    def viewers_changed(self) -> None:
        """Call whenever a downstream /device-preview/ws client connects or
        disconnects — re-evaluates demand so the last viewer leaving (a
        hidden tab closing its own socket) genuinely drops the upstream
        LedFX connection, and the first viewer coming back reopens it."""
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
            "source": _source_mode(),
        }

    def _throttle_ok(self, vis_id: str) -> bool:
        """Shared per-vis_id throttle bookkeeping (RELAY_TARGET_FPS) — every
        arriving frame counts toward frames_received; only one per
        _min_interval is let through and counted toward frames_relayed.
        Used by both the LedFX path (which arrives already throttled by
        LedFX itself, but is throttled again here — see the module
        docstring) and the facade path (which arrives unthrottled, so this
        is the ONLY throttle it gets)."""
        self.frames_received += 1
        now = self._clock()
        last = self._last_relayed_at.get(vis_id)
        if last is not None and (now - last) < self._min_interval:
            return False
        self._last_relayed_at[vis_id] = now
        self.frames_relayed += 1
        return True

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
        vis_id = msg.get("vis_id")
        if not self._throttle_ok(vis_id):
            return
        if self._on_frame is not None:
            await self._on_frame({
                "type": "device_preview_frame",
                "vis_id": vis_id,
                "pixels": msg.get("pixels"),
                "shape": msg.get("shape"),
                "is_device": bool(msg.get("is_device", False)),
            })

    async def _consume(self) -> None:
        """Dispatches to whichever source _source_mode() names, re-checked
        every time we're between connections (favourites/pause/mode all
        change here) — never assumes the mode that was true a moment ago
        still is."""
        while True:
            await self._active_event.wait()
            ids = list(self._favorite_ids)
            if not ids:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue
            mode = _source_mode()
            if mode == "facade":
                await self._consume_facade()
            elif mode == "ledfx":
                await self._consume_ledfx(ids)
            else:
                await self._set_connected(False)
                await asyncio.sleep(POLL_INTERVAL_S)

    async def _consume_ledfx(self, ids: list[str]) -> None:
        import websockets
        backoff = RECONNECT_MIN_S
        while (self._active_event.is_set() and self._favorite_ids == ids
               and _source_mode() == "ledfx"):
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await self._subscribe(ws, ids)
                    await self._set_connected(True)
                    self.connect_count += 1
                    backoff = RECONNECT_MIN_S
                    logger.info("device_preview: connected to %s (%d favourite(s))",
                               self.ws_url, len(ids))
                    while (self._active_event.is_set() and self._favorite_ids == ids
                           and _source_mode() == "ledfx"):
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

    async def _consume_facade(self) -> None:
        """The in-process source: subscribe directly to the live FxHost's
        own Event.VIRTUAL_UPDATE, no socket at all. Filters by
        self._favorite_ids on every event (a live list, not a snapshot) so
        a favourites change while connected takes effect immediately
        without needing a resubscribe. Exits — removing the listener,
        which IS the "connection close" this feature's pause proof is
        built on — the moment pause/favourites-empty/mode/host-instance
        changes; the dispatcher above re-evaluates and reconnects."""
        from fx.events import Event
        from spectra.services.live_host import live

        host = live.host
        if host is None:
            await self._set_connected(False)
            await asyncio.sleep(POLL_INTERVAL_S)
            return

        def on_update(event) -> None:
            if event.virtual_id not in self._favorite_ids:
                return
            if not self._throttle_ok(event.virtual_id):
                return
            payload = _facade_frame_payload(event.virtual_id, event.pixels, host)
            if self._on_frame is not None:
                asyncio.create_task(self._on_frame(payload))

        remove_listener = host.events.add_listener(on_update, Event.VIRTUAL_UPDATE)
        await self._set_connected(True)
        self.connect_count += 1
        logger.info("device_preview: subscribed in-process to the live facade "
                   "(%d favourite(s))", len(self._favorite_ids))
        try:
            while (self._active_event.is_set() and bool(self._favorite_ids)
                   and _source_mode() == "facade" and live.host is host):
                await asyncio.sleep(POLL_INTERVAL_S)
        finally:
            remove_listener()
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


class _PreviewFrameSender:
    """One connected preview client's dedicated frame-write path — the
    per-connection half of LedFX's own `WebsocketConnection.send()`/
    `_sender()` (module docstring's "PREVIEW FRAME DELIVERY" section): a
    single-slot, latest-value-wins mailbox per vis_id, drained by exactly
    ONE loop that ever writes to this socket. A vis_id already waiting to
    be sent is overwritten by a newer frame, never queued behind it —
    there is never a backlog to fall behind on, and concurrent sends to
    this connection are impossible by construction, not merely unlikely."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self._slots: dict[str, dict] = {}
        self._wake = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.dropped_frames = 0

    def submit(self, payload: dict) -> None:
        vis_id = payload.get("vis_id")
        if vis_id in self._slots:
            self.dropped_frames += 1
        self._slots[vis_id] = payload
        self._wake.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                pending = self._slots
                self._slots = {}
                for payload in pending.values():
                    await asyncio.wait_for(
                        self.ws.send_json(payload), timeout=FRAME_SEND_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A genuinely broken/wedged connection: close it FOR REAL so the
            # browser's onclose fires and it reconnects, instead of the old
            # broadcast()-timeout path's silent strand (module docstring).
            logger.info("device_preview: frame sender closing a dead connection")
            try:
                await self.ws.close()
            except Exception:
                pass

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None


class PreviewFrameHub:
    """Fan-out for `device_preview_frame` messages only — one
    `_PreviewFrameSender` per connected client. Status messages
    (pause/resume/connect — low frequency, ordering matters more than
    latency there) stay on `preview_ws_manager`'s existing broadcast,
    unchanged; this is purely the high-frequency motion path LedFX's own
    vis-frame mailbox covers."""

    def __init__(self) -> None:
        self._senders: dict[object, _PreviewFrameSender] = {}

    def connect(self, ws) -> None:
        sender = _PreviewFrameSender(ws)
        self._senders[ws] = sender
        sender.start()

    async def disconnect(self, ws) -> None:
        sender = self._senders.pop(ws, None)
        if sender is not None:
            await sender.stop()

    def submit(self, payload: dict) -> None:
        for sender in list(self._senders.values()):
            sender.submit(payload)

    def client_count(self) -> int:
        return len(self._senders)


frame_hub = PreviewFrameHub()


async def _broadcast_frame(payload: dict) -> None:
    frame_hub.submit(payload)


async def _broadcast_status() -> None:
    await preview_ws_manager.broadcast({"type": "device_preview_status", **relay.status()})


relay = DevicePreviewRelay(
    on_frame=_broadcast_frame, on_status_change=_broadcast_status,
    has_viewers=lambda: preview_ws_manager.client_count() > 0)


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
