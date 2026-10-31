"""
SpotFX's side of the capture lane (capture_lane/, its own process on
127.0.0.1:settings.capture_lane_port): three calls, each carrying the lane's
key. Every failure to reach it — not running, refused, timed out, an answer
that isn't the lane's — is ONE exception, LaneUnavailable, with a sentence:
the learning queue (services/jukebox/learning.py) treats a lane it can't
reach as no lane at all, and songs then play un-analysed.
"""
from __future__ import annotations

from typing import Optional

import httpx

TIMEOUT_S = 3.0


class LaneUnavailable(Exception):
    pass


class LaneBusy(Exception):
    pass


class LaneClient:
    def __init__(self, base_url: Optional[str] = None, key: Optional[str] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._base = base_url
        self._key = key
        self._transport = transport

    def _setup(self) -> tuple[str, str]:
        if self._base is None:
            from config import settings
            self._base = f"http://127.0.0.1:{settings.capture_lane_port}"
        if self._key is None:
            from capture_lane import key as lane_key
            self._key = lane_key.load_or_create()
        return self._base, self._key

    async def _call(self, method: str, path: str, body: Optional[dict] = None) -> httpx.Response:
        from capture_lane import key as lane_key
        base, key = self._setup()
        try:
            async with httpx.AsyncClient(base_url=base, timeout=TIMEOUT_S,
                                         transport=self._transport) as c:
                return await c.request(method, path, json=body,
                                       headers={lane_key.HEADER: key})
        except httpx.HTTPError as exc:
            raise LaneUnavailable(f"the capture lane isn't answering ({type(exc).__name__})") from None

    @staticmethod
    def _json(r: httpx.Response) -> dict:
        try:
            data = r.json()
        except ValueError:
            raise LaneUnavailable("the capture lane's answer wasn't readable") from None
        if not isinstance(data, dict):
            raise LaneUnavailable("the capture lane's answer wasn't readable")
        return data

    async def status(self) -> dict:
        r = await self._call("GET", "/status")
        if r.status_code != 200:
            raise LaneUnavailable(f"the capture lane refused ({r.status_code})")
        data = self._json(r)
        if "state" not in data or not isinstance(data.get("outcomes"), list):
            raise LaneUnavailable("the capture lane's answer wasn't readable")
        return data

    async def learn(self, job: dict) -> dict:
        r = await self._call("POST", "/learn", job)
        if r.status_code == 409:
            raise LaneBusy(str(self._json(r).get("uri") or ""))
        if r.status_code != 202:
            raise LaneUnavailable(f"the capture lane refused the song ({r.status_code})")
        return self._json(r)

    async def cancel(self, job_id: str) -> bool:
        r = await self._call("POST", "/cancel", {"job_id": job_id})
        if r.status_code != 200:
            raise LaneUnavailable(f"the capture lane refused ({r.status_code})")
        return bool(self._json(r).get("cancelled"))
