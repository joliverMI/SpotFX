"""`/api/tv/ws` (data/tv-display-plan/plan.html PR 1.2) — the TV app's one
WebSocket. Protocol and every seam's rationale live in
spectra/services/tv_feed.py; this module is wiring only: accept, read the
client's `hello`, reply `config`, spawn the two background loops (clock,
jukebox relay), then dispatch whatever the client sends afterward (today,
only `ping`)."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from spectra.services import tv_feed

logger = logging.getLogger(__name__)

router = APIRouter(tags=["spectra-tv-feed"])


@router.websocket("/api/tv/ws")
async def tv_ws(ws: WebSocket) -> None:
    await ws.accept()
    deps = tv_feed.production_deps()
    send_lock = asyncio.Lock()

    async def send(msg: dict) -> None:
        async with send_lock:
            await ws.send_json(msg)

    try:
        hello = await ws.receive_json()
    except Exception:                                      # noqa: BLE001
        await ws.close()
        return
    if not isinstance(hello, dict):
        hello = {}

    # The FIRST config's layout reads a fresh board rather than waiting for
    # the relay loop's own first poll tick — a stale "attract" for up to a
    # whole poll interval right at connect would be the wrong screen.
    http_url = deps.http_url()
    initial_board = await deps.fetch_jukebox(http_url)
    running0 = initial_board.get("running") if isinstance(initial_board, dict) else None
    await send(tv_feed.config_message(hello, running0, deps.build_id()))

    clock_task = asyncio.create_task(tv_feed.run_clock_loop(send, deps, asyncio.sleep))
    jukebox_task = asyncio.create_task(tv_feed.run_jukebox_loop(send, deps, asyncio.sleep))
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ping":
                await send(await tv_feed.handle_ping(msg, deps))
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:                                      # noqa: BLE001
        logger.warning("tv feed: connection ended abnormally", exc_info=True)
    finally:
        clock_task.cancel()
        jukebox_task.cancel()
