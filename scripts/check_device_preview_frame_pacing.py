"""Before/after evidence for the device-preview DELIVERY fix
(data/preview-skips-under-fast-motion/, his SECOND "LedFX was better"
report: "the preview might look better but when there are fast motions it
skips still... LedFX was better").

WHY THIS IS A DIFFERENT BUG FROM THE ONE JUST FIXED: PR #143
(scripts/check_device_preview_remote_transport.py) made his crystal frames
3.4x smaller on the wire — real, measured, done. But payload size is
constant regardless of motion. "Skips under fast motion" specifically is a
DELIVERY-TIMING complaint, so it necessarily survived a bytes-only fix
untouched. This script measures the thing that fix didn't touch: how the
relay behaves when a single send takes longer than one frame interval —
ordinary on a real remote link, no motion required — not how many bytes
that send moves.

WHAT WAS FOUND reading LedFX's real client fan-out a second time
(ledfx/api/websocket.py WebsocketConnection.send()/_sender()): it never
queues a vis frame for delivery. It drops it into a per-vis_id
single-slot mailbox (a newer frame unconditionally overwrites whatever
hasn't been sent yet) and exactly ONE sender task per connection drains
it, one message at a time. SPECTRA's relay did neither: the facade
source fired a bare `asyncio.create_task` per accepted frame into
`WSManager.broadcast`, which wraps each client's send in
`asyncio.wait_for(..., timeout=SEND_DEADLINE_S=0.25s)`. This script
reproduces that OLD path byte-for-byte (it no longer exists in the
shipped code — spectra/services/device_preview.py now uses
PreviewFrameHub/_PreviewFrameSender) against a fake WebSocket with an
injected send delay, standing in for a slow/congested remote link, and
compares it with the NEW path (the real, currently-shipped classes)
under the identical delay.

Two distinct defects, two profiles below:
  A) "borderline remote link" (send takes longer than one 125ms frame
     interval but under the old 250ms eviction deadline) — demonstrates
     CONCURRENT OVERLAPPING SENDS on the same connection under the OLD
     path (undefined behaviour for a single ASGI WebSocket), absent on
     the NEW path by construction.
  B) "congested remote link" (send takes longer than the old 250ms
     deadline) — demonstrates the OLD path's FALSE EVICTION: the client
     is silently dropped from the fan-out list while its socket is never
     actually closed (proven here: .closed stays False), which is why a
     real browser tab never sees onclose fire and never reconnects. The
     NEW path never evicts a merely-slow-but-alive connection.

WHAT THIS DOES NOT PROVE: this is a delay-INJECTED simulation of a
congested link (an async sleep standing in for real network time), not a
test against his actual remote connection — his room and browser were
never touched, per this task's own hard limits. The delay magnitudes are
chosen to bracket the old 125ms/250ms thresholds, not measured from his
real link. Report this as a remote-EQUIVALENT proxy for the DELIVERY
mechanism, the same honesty bar
scripts/check_device_preview_remote_transport.py already set for BYTES —
this script does not re-measure bytes at all.

Run: .venv/bin/python scripts/check_device_preview_frame_pacing.py
No live storage, no LedFX, no audio, no real sockets — a fake WebSocket
object with an injected async delay is the only "network" involved.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectra.services.device_preview import PreviewFrameHub
from spectra.services.ws import WSManager

RELAY_TARGET_FPS = 8.0
FRAME_INTERVAL_S = 1.0 / RELAY_TARGET_FPS
N_FRAMES = 24  # 3 seconds at the relay's own target rate, matching the
               # #143 remote-transport script's own trial length


class _DelayedWebSocket:
    """Fake WebSocket: an injected async send delay stands in for a
    congested/slow remote link. Records overlap (two sends mid-flight at
    once — undefined behaviour for a real ASGI WebSocket), arrival order,
    and whether it was ever actually close()'d."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.sent: list[tuple[int, float]] = []  # (seq, arrival_monotonic)
        self.closed = False
        self.overlap_count = 0
        self._busy = False

    async def send_json(self, payload: dict) -> None:
        if self._busy:
            self.overlap_count += 1
        self._busy = True
        try:
            await asyncio.sleep(self.delay_s)
            self.sent.append((payload["seq"], time.monotonic()))
        finally:
            self._busy = False

    async def close(self) -> None:
        self.closed = True


async def _old_path_trial(delay_s: float) -> _DelayedWebSocket:
    """Byte-for-byte reproduction of the pre-fix pattern: _consume_facade's
    on_update fired asyncio.create_task(self._on_frame(payload)) per
    accepted frame, where _on_frame was WSManager.broadcast. WSManager
    itself is untouched by this task (still used for status pushes) —
    only the calling pattern that fed it frames has changed."""
    manager = WSManager()
    ws = _DelayedWebSocket(delay_s)
    manager._connections.append(ws)  # bypass .connect()'s ws.accept()

    for seq in range(N_FRAMES):
        payload = {"type": "device_preview_frame", "vis_id": "v", "seq": seq}
        asyncio.create_task(manager.broadcast(payload))
        await asyncio.sleep(FRAME_INTERVAL_S)
    await asyncio.sleep(max(2.0, delay_s * 3))  # let in-flight sends/timeouts resolve
    ws._still_registered = ws in manager._connections
    return ws


async def _new_path_trial(delay_s: float) -> _DelayedWebSocket:
    """The real, currently-shipped path: PreviewFrameHub.submit() (what
    _broadcast_frame now calls) feeding a real _PreviewFrameSender."""
    hub = PreviewFrameHub()
    ws = _DelayedWebSocket(delay_s)
    hub.connect(ws)

    for seq in range(N_FRAMES):
        payload = {"type": "device_preview_frame", "vis_id": "v", "seq": seq}
        hub.submit(payload)
        await asyncio.sleep(FRAME_INTERVAL_S)
    await asyncio.sleep(max(2.0, delay_s * 3))
    ws._still_registered = hub.client_count() > 0
    await hub.disconnect(ws)
    return ws


def _report(label: str, old: _DelayedWebSocket, new: _DelayedWebSocket) -> None:
    print(f"\n=== {label} ===")
    print(f"  OLD path: {len(old.sent)}/{N_FRAMES} frames delivered, "
          f"overlap_count={old.overlap_count}, still_registered={old._still_registered}, "
          f"socket.closed={old.closed}")
    if not old._still_registered and not old.closed:
        print("    -> FALSE EVICTION: silently dropped from the fan-out list, "
              "but the socket was never closed. A real browser's onclose never "
              "fires; the tab is stranded with no way to reconnect.")
    if old.overlap_count:
        print(f"    -> {old.overlap_count} send(s) started while a previous send to "
              "the SAME connection was still in flight (undefined behaviour for a "
              "single ASGI WebSocket).")
    print(f"  NEW path: {len(new.sent)}/{N_FRAMES} frames delivered, "
          f"overlap_count={new.overlap_count}, still_registered={new._still_registered}, "
          f"socket.closed={new.closed}")
    if new._still_registered and not new.closed:
        print("    -> merely-slow connection kept alive and still receiving frames.")


def main() -> None:
    print("Simulated delay values bracket the OLD path's own two thresholds "
          f"(frame interval {FRAME_INTERVAL_S*1000:.0f}ms, eviction deadline 250ms) — "
          "chosen to demonstrate the mechanism, not measured from his real link.\n")

    old_a = asyncio.run(_old_path_trial(delay_s=0.20))
    new_a = asyncio.run(_new_path_trial(delay_s=0.20))
    _report("Profile A: borderline remote link (send=200ms, over one frame "
            "interval, under the old 250ms eviction deadline)", old_a, new_a)

    old_b = asyncio.run(_old_path_trial(delay_s=0.40))
    new_b = asyncio.run(_new_path_trial(delay_s=0.40))
    _report("Profile B: congested remote link (send=400ms, over the old "
            "250ms eviction deadline)", old_b, new_b)

    print("\nDone. See docstring for what this does and does not prove.")


if __name__ == "__main__":
    main()
