"""SPECTRA's own WebSocket fan-out (/spectra/api/ws) — the engine's live
observability channel: drift_leg / drift_rebaseline / surge / sequencer_pick
payloads. Same per-client write deadline discipline as spot-effects' manager
(a stale tab must not pin every broadcast at the TCP timeout)."""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

SEND_DEADLINE_S = 0.25


class WSManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        try:
            self._connections.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, payload: dict) -> None:
        conns = list(self._connections)
        if not conns:
            return

        async def _send(ws: WebSocket) -> None:
            await asyncio.wait_for(ws.send_json(payload),
                                   timeout=SEND_DEADLINE_S)

        results = await asyncio.gather(*(_send(ws) for ws in conns),
                                       return_exceptions=True)
        for ws, result in zip(conns, results):
            if isinstance(result, Exception):
                self.disconnect(ws)


ws_manager = WSManager()
