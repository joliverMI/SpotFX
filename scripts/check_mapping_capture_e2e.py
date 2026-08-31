"""END-TO-END proof of the capture session over the REAL WebSocket path: a
real uvicorn server running the real spectra app, a real WebSocket client
speaking the real wire, a synthetic camera feeding real frames, and the real
`POST /api/rooms/{id}/map` route producing a stored footprint that matches
ground truth declared before the run.

WHAT MAKES THIS DIFFERENT from scripts/check_light_field.py, which drives
MappingSession.handle() directly: here every message is actually serialized,
sent over a socket to a listening server, routed by FastAPI, and answered —
so the wire shape, the router, the base64 envelope, the frame ring, the
run route's own refusals and its one-run-at-a-time lock are all exercised
rather than assumed. The task's proof bar names a Chromium fake-camera page
OR "an equivalent programmatic frame feed through the real WS path"; this is
that feed, and it is the stronger of the two for the SERVER half because a
fake camera device cannot lock exposure and would never get past the gate.
The page's own half — that it negotiates, refuses honestly on a camera that
will not lock, and renders — is smoke-tested separately against Chromium.

His fixtures are NOT granted, so the ONE thing faked is the two fx_seam
primitives (patched in the server process before the app is built). Every
other line of the path is production code.

Run from repo root: .venv/bin/python scripts/check_mapping_capture_e2e.py
Isolated: temp SPECTRA storage, a spare loopback port, no LedFX, no camera,
no network beyond 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from base64 import b64encode
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print = __import__("functools").partial(print, flush=True)     # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-map-e2e-"))
os.environ["SPECTRA_STORAGE_DIR"] = str(td / "spectra")

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")
scfg.COLOR_SETS_FILE = td / "color_sets.json"

import httpx                                                   # noqa: E402
import uvicorn                                                 # noqa: E402
import websockets                                              # noqa: E402

from spectra.services import fx_seam, light_field, mapping_session, room_mapping  # noqa: E402

FW, FH = light_field.FRAME_W, light_field.FRAME_H
DEVICE = "sconce-kitchen-left"
VIRTUAL = "sconce-left-v"
OTHER = "crystal-mapper"
REGION = (20, 80, 60, 200)          # y0, y1, x0, x1 — the ground truth
AMPLITUDE = 140.0

LOCKED = {"exposure_locked": True, "white_balance_locked": True,
          "exposure_mode": "manual", "white_balance_mode": "manual",
          "exposure_capabilities": ["manual", "continuous"],
          "white_balance_capabilities": ["manual", "continuous"]}
UNLOCKED = {**LOCKED, "exposure_locked": False, "exposure_mode": "continuous",
            "exposure_capabilities": ["continuous"]}


# ── the fake room, inside the server process ──────────────────────────────

LIT: dict[str, float] = {}
WRITES: list[dict] = []
VIRTUALS = {
    VIRTUAL: {"active": True, "effect": {"type": "singleColor",
                                         "config": {"color": "#2040ff",
                                                    "brightness": 0.5}}},
    OTHER: {"active": True, "effect": {"type": "blackhole",
                                       "config": {"brightness": 0.6}}},
}


async def fake_get_virtuals():
    return VIRTUALS


async def fake_apply_writes(writes, *, transition_ms=0):
    WRITES.append({"transition_ms": transition_ms,
                   "writes": [dict(w) for w in writes]})
    for w in writes:
        cfg = w["config"]
        level = 0.0 if cfg.get("color") == "#000000" else float(
            cfg.get("brightness", 1.0))
        LIT[w["virtual_id"]] = level
        VIRTUALS[w["virtual_id"]] = {
            "active": True,
            "effect": {"type": w["effect_type"], "config": dict(cfg)}}


fx_seam.apply_writes = fake_apply_writes        # type: ignore[assignment]
fx_seam.get_virtuals = fake_get_virtuals        # type: ignore[assignment]


async def fake_virtuals_for_device(device_id: str):
    return [VIRTUAL] if device_id == DEVICE else []


_real_production_deps = room_mapping.production_deps


def patched_production_deps(session):
    deps = _real_production_deps(session)
    deps.get_virtuals = fake_get_virtuals
    deps.virtuals_for_device = fake_virtuals_for_device
    return deps


room_mapping.production_deps = patched_production_deps   # type: ignore[assignment]
room_mapping.DARK_SETTLE_S = 0.05
room_mapping.DARK_CAPTURE_S = 0.10
room_mapping.LIT_SETTLE_S = 0.05
room_mapping.LIT_CAPTURE_S = 0.15


def render_frame() -> np.ndarray:
    f = np.full((FH, FW), 8.0)
    f[:, :30] += 12.0                       # a window, in both frames
    level = LIT.get(VIRTUAL, 0.0)
    if level > 0:
        y0, y1, x0, x1 = REGION
        f[y0:y1, x0:x1] += AMPLITUDE * level
    return np.clip(f, 0, 255).astype(np.uint8)


# ── the server ────────────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, port: int) -> None:
        from spectra.app import create_app
        # A bare app: create_app's own lifespan starts the live stack, the
        # frame watchdog and the resume path — none of which belong in a
        # check script. Routers are what this proof is about.
        app = create_app()
        app.router.lifespan_context = _no_lifespan
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port,
                                     log_level="warning", lifespan="on")
        self.server = uvicorn.Server(self.config)
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(200):
            if self.server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("server did not start")

    async def stop(self):
        self.server.should_exit = True
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=5.0)


import contextlib                                             # noqa: E402


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


# ── the phone, over a real socket ─────────────────────────────────────────

class WirePhone:
    def __init__(self, url: str) -> None:
        self.url = url
        self.ws = None
        self.received: list[dict] = []
        self.lock = dict(LOCKED)
        self.pump = None
        self.streamer = None

    async def connect(self, lock: dict | None = None):
        self.lock = dict(lock if lock is not None else LOCKED)
        self.ws = await websockets.connect(self.url)
        self.pump = asyncio.create_task(self._pump())
        await self._send({"type": "hello", "user_agent": "WirePhone/1.0",
                          "secure_context": True, "lock": self.lock})
        for _ in range(100):
            if any(m.get("type") == "hello_ack" for m in self.received):
                break
            await asyncio.sleep(0.02)

    async def _send(self, msg: dict):
        await self.ws.send(json.dumps(msg))

    async def _pump(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                self.received.append(msg)
                if msg.get("type") == "ping":
                    await self._send({"type": "pong", "seq": msg["seq"],
                                      "t_phone_ms": time.monotonic() * 1000.0})
        except Exception:
            pass

    def start_stream(self, fps: float = 120.0):
        self.streamer = asyncio.create_task(self._stream(1.0 / fps))

    async def _stream(self, period: float):
        while True:
            frame = render_frame()
            await self._send({
                "type": "frame", "mime": mapping_session.GREY_MIME,
                "width": FW, "height": FH,
                "captured_at_ms": time.monotonic() * 1000.0,
                "data": b64encode(frame.tobytes()).decode("ascii"),
                "lock": self.lock})
            await asyncio.sleep(period)

    async def set_lock(self, lock: dict):
        self.lock = dict(lock)
        await self._send({"type": "lock", **self.lock})

    async def close(self):
        for t in (self.streamer, self.pump):
            if t is not None:
                t.cancel()
        if self.ws is not None:
            await self.ws.close()


async def main():
    port = free_port()
    server = Server(port)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/api/rooms/map/ws"
    print(f"== the real server is up on 127.0.0.1:{port} ==\n")

    async with httpx.AsyncClient(base_url=base, timeout=30.0) as http:
        # ── 1. a run refuses with no phone connected ──────────────────────
        print("== 1. the route's own refusals ==")
        room = (await http.post("/api/rooms", json={
            "name": "Kitchen wall", "device_ids": [DEVICE],
            "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                     "ceiling": {"x": 0.5, "y": 0.0}}})).json()
        check(room["id"] and room["unmapped_ids"] == [DEVICE],
              "a fresh room reports its device as NOT mapped")
        r = await http.post(f"/api/rooms/{room['id']}/map")
        check(r.status_code == 409 and "no phone connected" in r.json()["detail"],
              "with no phone connected the run is refused by name, 409")
        check(not WRITES, "and nothing was written to the lights")

        # ── 2. an unlocked camera refuses, over the real wire ─────────────
        print("\n== 2. the exposure gate, over the real wire ==")
        phone = WirePhone(ws_url)
        await phone.connect(lock=UNLOCKED)
        ack = next(m for m in phone.received if m.get("type") == "hello_ack")
        check(ack.get("refusal") and "EXPOSURE" in ack["refusal"],
              "the server names the missing capability in its own hello_ack")
        phone.start_stream()
        await asyncio.sleep(0.2)
        body = (await http.post(f"/api/rooms/{room['id']}/map")).json()
        check(not body["ok"] and "EXPOSURE" in body["reason"],
              "the run refuses an unlocked camera by name")
        check(not WRITES, "and still nothing was written to the lights")
        await phone.close()
        await asyncio.sleep(0.2)

        # ── 3. the happy path, over the real wire ─────────────────────────
        print("\n== 3. a real capture over a real socket ==")
        phone = WirePhone(ws_url)
        await phone.connect()
        phone.start_stream()
        await asyncio.sleep(0.3)
        status = (await http.get("/api/rooms/map/status")).json()
        check(status["session"] and status["session"]["counts"]["frames"] > 3,
              f"frames are arriving over the socket "
              f"({status['session']['counts']['frames']})")
        check(status["session"]["lock"]["locked"] and not status["session"]["refusal"],
              "the session reports a locked camera and no refusal")
        check(status["session"]["frame_tap"]["enabled"],
              "the FrameRing tap is ON for this session type — it IS the "
              "instrument, not an optional extra")

        frame = await http.get("/api/rooms/map/frame/latest")
        check(frame.status_code == 200 and frame.content.startswith(b"P5\n"),
              "the latest tapped frame is served for checking aim "
              f"({len(frame.content)} bytes)")

        body = (await http.post(f"/api/rooms/{room['id']}/map")).json()
        check(body["ok"], f"the run succeeded: {body.get('reason', '')}")
        check(body["emitters"][0]["mapped"], "the emitter is mapped")
        check(body["pose_id"] == status["session"]["pose_id"],
              "the run records the pose it was captured in")

        fp = (await http.get(
            f"/api/rooms/{room['id']}/footprint/{DEVICE}")).json()
        grid = np.asarray(fp["grid"]).reshape(fp["height"], fp["width"])
        y0, y1, x0, x1 = REGION
        inside = grid[y0 // 5:y1 // 5, x0 // 5:x1 // 5]
        outside = grid.copy()
        outside[y0 // 5:y1 // 5, x0 // 5:x1 // 5] = 0.0
        check(np.allclose(inside, AMPLITUDE / 255.0, atol=1e-9),
              f"the stored footprint IS the region the fake emitter painted, "
              f"at its own amplitude ({AMPLITUDE / 255.0:.4f})")
        check(outside.max() == 0.0,
              "and exactly zero everywhere else — the window cancelled")
        check(fp["capture"]["exposure_locked"] and fp["capture"]["pose_id"],
              "the capture context travelled with it")

        listing = (await http.get("/api/rooms")).json()["rooms"][0]
        check(listing["mapped_ids"] == [DEVICE] and listing["footprints"][0]["thumbnail"],
              "the room listing shows it mapped, with a heat thumbnail")
        check(len(listing["footprints"][0]["thumbnail"]) == 9 and
              len(listing["footprints"][0]["thumbnail"][0]) == 16,
              "the thumbnail is a small 16x9 grid of numbers, never an image")

        # the room came back
        final = WRITES[-1]
        check(all(w["effect_type"] != room_mapping.MAP_EFFECT_TYPE or
                  w["virtual_id"] == VIRTUAL for w in final["writes"]),
              "the last write is the revert")
        check(VIRTUALS[OTHER]["effect"]["type"] == "blackhole",
              "the other virtual is back on the show's own effect")

        # ── 4. one run at a time ──────────────────────────────────────────
        print("\n== 4. one run at a time ==")
        first = asyncio.create_task(http.post(f"/api/rooms/{room['id']}/map"))
        await asyncio.sleep(0.05)
        second = await http.post(f"/api/rooms/{room['id']}/map")
        check(second.status_code == 409 and "already in progress" in second.json()["detail"],
              "a second concurrent run is refused, not queued")
        await first

        # ── 5. a disconnect aborts rather than stranding ──────────────────
        print("\n== 5. a dropped phone ==")
        await phone.close()
        await asyncio.sleep(0.3)
        status = (await http.get("/api/rooms/map/status")).json()
        check(status["session"] is None,
              "the session is gone once the socket closes")
        r = await http.post(f"/api/rooms/{room['id']}/map")
        check(r.status_code == 409, "and a run is refused again")

    await server.stop()
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL END-TO-END CAPTURE CHECKS PASSED")


if __name__ == "__main__":
    status = 0
    try:
        asyncio.run(main())
    except SystemExit as exc:
        print(exc)
        status = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        status = 1
    os._exit(status)
