"""
SpotFX — what Snapcast says every room is doing, for Absorb Music's silence
proof (data/absorb-music-plan/report.md §3 and §6.2, phase 2).

`read_status()` is ONE `Server.GetStatus` on snapserver's JSON-RPC
(`settings.snapcast_rpc_url`, the same endpoint services/guest_source.py
and River's own scripts use). It is the proof's whole instrument: a 2xx from
Home Assistant says the volume script RAN, never that a room went quiet —
only Snapcast's own per-client {percent, muted} says that.

FAIL CLOSED. Any failure — unreachable, a timeout, an error object, a body
without the shape below — raises `SnapcastUnreadable`, and Absorb treats an
unreadable status as "could be audible" (report §6.2 item 4: on this path the
fail-safe direction is always less sound). Nothing here guesses.

A FRESH CONNECTION PER REQUEST, deliberately: snapserver mishandles
keep-alive on POST /jsonrpc (every second request on a reused connection
returns an empty body — services/guest_source.py's own docstring, and
River's Homelab AGENTS.md).

`set_client_volume()` is the ONE write, and only Absorb's fallback reaches
it: muting a room the house volume did not silence, and putting that mute
back afterwards. It never touches the capture client.

The shape read (snapserver 0.34, as River's snapcast-announce reads it):
  result.server.groups[] {id, muted, stream_id,
                          clients[] {id, connected, host{name},
                                     config{name, volume{percent, muted}}}}
  result.server.streams[] {id, status}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

TIMEOUT_S = 4.0


class SnapcastUnreadable(Exception):
    """Snapserver did not give a usable status."""


@dataclass
class SnapClient:
    id: str
    name: str
    connected: bool
    percent: int
    muted: bool
    group_id: str = ""
    group_muted: bool = False
    stream_id: str = ""

    @property
    def silent(self) -> bool:
        """Nothing of the stream reaches this room."""
        return self.muted or self.group_muted or self.percent <= 0

    def snapshot(self) -> dict:
        return {"id": self.id, "name": self.name, "percent": self.percent,
                "muted": self.muted}


@dataclass
class SnapStatus:
    clients: list[SnapClient] = field(default_factory=list)
    streams: dict[str, str] = field(default_factory=dict)   # id -> status

    def find(self, name_or_id: str) -> Optional[SnapClient]:
        want = (name_or_id or "").strip().lower()
        for c in self.clients:
            if c.id.lower() == want or c.name.strip().lower() == want:
                return c
        return None

    def connected(self) -> list[SnapClient]:
        return [c for c in self.clients if c.connected]


def parse_status(body: Any) -> SnapStatus:
    """A JSON-RPC answer → SnapStatus. Raises SnapcastUnreadable when the
    answer is not the shape above — a partial read is never a proof."""
    if not isinstance(body, dict):
        raise SnapcastUnreadable("answer was not an object")
    if body.get("error"):
        raise SnapcastUnreadable(f"snapserver error: {str(body['error'])[:120]}")
    try:
        server = body["result"]["server"]
        groups = server["groups"]
    except (KeyError, TypeError):
        raise SnapcastUnreadable("answer carried no server.groups")
    if not isinstance(groups, list):
        raise SnapcastUnreadable("server.groups was not a list")
    clients: list[SnapClient] = []
    try:
        for g in groups:
            for c in g.get("clients") or []:
                cfg = c.get("config") or {}
                vol = cfg["volume"]
                name = (cfg.get("name") or "").strip() or \
                    str(((c.get("host") or {}).get("name")) or "")
                clients.append(SnapClient(
                    id=str(c["id"]), name=name, connected=bool(c.get("connected")),
                    percent=int(vol["percent"]), muted=bool(vol["muted"]),
                    group_id=str(g.get("id") or ""), group_muted=bool(g.get("muted")),
                    stream_id=str(g.get("stream_id") or "")))
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapcastUnreadable(f"a client's volume was unreadable ({type(exc).__name__})")
    streams = {}
    for s in server.get("streams") or []:
        if isinstance(s, dict) and s.get("id"):
            streams[str(s["id"])] = str(s.get("status") or "")
    return SnapStatus(clients=clients, streams=streams)


async def _rpc(url: str, method: str, params: Optional[dict] = None,
               client: Any = None) -> Any:
    import httpx
    payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    if client is not None:
        resp = await client.post(url, json=payload)
    else:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as fresh:
            resp = await fresh.post(url, json=payload, headers={"Connection": "close"})
    if resp.status_code != 200:
        raise SnapcastUnreadable(f"snapserver answered {resp.status_code}")
    try:
        return resp.json()
    except Exception:                                             # noqa: BLE001
        raise SnapcastUnreadable("snapserver's answer was not JSON")


class SnapcastClient:
    """The interface absorb_silence talks to; tests hand it a fake."""

    def __init__(self, url: str, *, client: Any = None) -> None:
        self.url = url
        self._client = client

    async def read_status(self) -> SnapStatus:
        try:
            body = await _rpc(self.url, "Server.GetStatus", client=self._client)
        except SnapcastUnreadable:
            raise
        except Exception as exc:                                  # noqa: BLE001
            raise SnapcastUnreadable(f"snapserver unreachable ({type(exc).__name__})")
        return parse_status(body)

    async def set_client_volume(self, client_id: str, percent: int, muted: bool) -> None:
        """Raises SnapcastUnreadable when the write was not accepted."""
        try:
            body = await _rpc(self.url, "Client.SetVolume", {
                "id": client_id,
                "volume": {"percent": int(percent), "muted": bool(muted)}},
                client=self._client)
        except SnapcastUnreadable:
            raise
        except Exception as exc:                                  # noqa: BLE001
            raise SnapcastUnreadable(f"snapserver unreachable ({type(exc).__name__})")
        if isinstance(body, dict) and body.get("error"):
            raise SnapcastUnreadable(f"snapserver refused: {str(body['error'])[:120]}")


def from_settings() -> SnapcastClient:
    from config import settings
    return SnapcastClient(settings.snapcast_rpc_url)
