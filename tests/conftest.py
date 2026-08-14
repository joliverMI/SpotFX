"""Shared test plumbing: a fake LedFX API server + per-test isolation of the
api.ledfx_client module globals.

No live access anywhere: every test talks to an in-process asyncio server on an
ephemeral loopback port. The topology payloads are recorded from the production
LedFX (2026-08-12) — the same shapes ambient-mode group discovery reads live.

The repo has no test infrastructure beyond this; tests are plain pytest
functions that drive their own event loop via asyncio.run(), so no
pytest-asyncio plugin is needed. Run with:  pip install -r requirements-dev.txt
&& python -m pytest
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Recorded from the live LedFX API (GET /api/virtuals, /api/devices/{id}) —
# trimmed to the fields ambient-mode discovery actually reads.
LIVE_VIRTUALS = {
    "hue-lights": {
        "active": False, "effect": {},
        "segments": [["hue-lights", 0, 9, False, 0]],
    },
    "dining-hues": {
        "active": False, "effect": {},
        "segments": [["dining-hues", 0, 6, False, 0]],
    },
    # The virtual that actually drives the bulbs during music: spans both Hue
    # devices per-pixel. Present so discovery must cope with segment refs.
    "hues": {
        "active": True, "effect": {"type": "power", "config": {}},
        "segments": [["hue-lights", 0, 0, False, 0], ["dining-hues", 0, 0, False, 0]],
    },
    "tv-mapper": {
        "active": True, "effect": {"type": "blackhole1d", "config": {}},
        "segments": [["tv-backlight", 0, 559, False, 0]],
    },
}

LIVE_DEVICES = {
    "hue-lights": {
        "type": "hue",
        "config": {
            "name": "Hue Lights", "ip_address": "192.168.40.201",
            "username": "test-app-key", "entertainment_id": "ent-1",
            "pixel_count": 10,
        },
    },
    "dining-hues": {
        "type": "hue",
        "config": {
            "name": "Dining Hues", "ip_address": "192.168.40.202",
            "username": "test-app-key", "entertainment_id": "ent-2",
            "pixel_count": 7,
        },
    },
    "tv-backlight": {
        "type": "wled",
        "config": {"name": "TV Backlight", "ip_address": "192.168.40.203"},
    },
}

# The live device-category record the ambient target points at.
LIVE_CATEGORY_ID = "2a86489e-1d99-43e6-b4cf-46756b027dc5"
LIVE_CATEGORIES = {
    LIVE_CATEGORY_ID: {
        "id": LIVE_CATEGORY_ID,
        "name": "Hue",
        "parent_id": None,
        "virtuals": ["hue-lights", "dining-hues"],
        "effects": ["power"],
        "sort_order": 3,
        "role": None,
    }
}


class FakeLedFX:
    """Minimal HTTP/1.1 LedFX stand-in. mode: 'ok' answers instantly;
    'stall' accepts + reads the request but never responds (the live outage's
    initiating LedFX behavior); 'lie' answers PUT /api/virtuals/{id} with
    {"status": "success"} WITHOUT actually flipping the virtual's active
    state — a command that claims success without it being true, the exact
    shape a read-back verification must catch."""

    def __init__(self, virtuals=None, devices=None):
        self.mode = "ok"
        self.virtuals = dict(LIVE_VIRTUALS if virtuals is None else virtuals)
        self.devices = dict(LIVE_DEVICES if devices is None else devices)
        self.requests: list[str] = []
        self.calls: list[tuple[str, str]] = []   # (method, path), method+state-aware
        self._server = None
        self.base_url = ""

    async def __aenter__(self):
        import asyncio
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        # close() only; wait_closed() would block on stalled handler tasks
        # (3.12 waits for handlers) — asyncio.run() reaps them at loop teardown.
        self._server.close()

    def _route(self, method: str, path: str, body: bytes = b""):
        if path == "/api/virtuals":
            return {"virtuals": self.virtuals}
        if path.startswith("/api/devices/") and path.endswith("/freeze"):
            did = path.split("/")[3]
            return {"id": did, "frozen": False}
        if path.startswith("/api/devices/"):
            did = path.split("/")[3]
            return self.devices.get(did)
        if path.startswith("/api/virtuals/"):
            vid = path.split("/")[3]
            v = self.virtuals.get(vid)
            if v is None:
                return None
            if method == "PUT" and body:
                # Mutates real state (not just echoes the request) so a
                # caller's own follow-up GET proves the write actually
                # landed — the release-verification proof needs this.
                try:
                    data = json.loads(body)
                except ValueError:
                    data = {}
                if "active" in data and self.mode != "lie":
                    v["active"] = bool(data["active"])
                return {"status": "success"}
            return {vid: v}
        return {"status": "ok"}

    async def _handle(self, reader, writer):
        import asyncio
        try:
            while True:
                header = await reader.readuntil(b"\r\n\r\n")
                request_line = header.split(b"\r\n", 1)[0].decode()
                method, path = request_line.split(" ")[0], request_line.split(" ")[1]
                clen = 0
                for line in header.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        clen = int(line.split(b":", 1)[1])
                body = b""
                if clen:
                    body = await reader.readexactly(clen)
                self.requests.append(path)
                self.calls.append((method, path))
                if self.mode == "stall":
                    await asyncio.sleep(3600)
                    return
                payload = self._route(method, path, body)
                if payload is None:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                else:
                    body = json.dumps(payload).encode()
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
                    )
                await writer.drain()
        except Exception:
            try:
                writer.close()
            except Exception:
                pass


@pytest.fixture()
def fresh_ledfx_client():
    """Reload api.ledfx_client so each test gets pristine module globals
    (semaphore, client, counters) unbound from any previous test's event loop.
    Returns a `make(base_url)` callable."""

    def make(base_url: str):
        import api.ledfx_client as lc
        importlib.reload(lc)
        object.__setattr__(lc.settings, "ledfx_base_url", base_url)
        return lc

    yield make


@pytest.fixture()
def ambient_env(tmp_path, monkeypatch, fresh_ledfx_client):
    """Ambient discovery against the recorded live topology: category file on
    tmp disk, target category configured, ambient_mode module state reset."""
    import services.device_category_service as dcs
    import services.ambient_mode as am

    cat_file = tmp_path / "device_categories.json"
    cat_file.write_text(json.dumps(LIVE_CATEGORIES), encoding="utf-8")
    monkeypatch.setattr(dcs, "CATEGORIES_FILE", cat_file)
    monkeypatch.setattr(am, "_groups_cache", None)
    monkeypatch.setattr(am, "_lock", None)
    am._light_cache.clear()
    object.__setattr__(am.settings, "ambient_target_category", LIVE_CATEGORY_ID)
    return am
