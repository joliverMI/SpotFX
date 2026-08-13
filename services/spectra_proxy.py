"""Thin reverse proxy: /spectra/* on this app → the SPECTRA process.

The S3 process split moved SPECTRA (render host, engine, API, UI) into its
own interpreter (python -m spectra, spectra.service, port
settings.spectra_port). This proxy is what keeps every port-8000 address
working verbatim afterwards — the owner's /spectra/ bookmark, the docs'
curl lines, and THE LIVENESS CONTRACT (GET /spectra/api/liveness, binding:
never delete or repoint without the Admiral's word) — while the SPECTRA
process's own port stays the direct, spot-effects-independent address the
fleet checker should prefer (a proxied read shares this process's event
loop, so it inherits this loop's stalls; the render plane does not).

Transparent by design: same path + query on the backend (the standalone
process serves the identical /spectra URL space), status and bodies passed
through unchanged — a 503 from the liveness endpoint arrives as a 503, not
a proxy error. WebSockets are bridged the same way (/spectra/api/ws is a
published surface). When the SPECTRA process is down the proxy answers 502
with a hint naming spectra.service; it never fakes a healthy answer.

Raw ASGI app (mounted in main.py) — no spectra/ import, no fx/ import: the
whole point of the split is that this process knows SPECTRA only as a URL.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 3.0
READ_TIMEOUT_S = 60.0

# Hop-by-hop headers (RFC 9110 §7.6.1) — everything else passes through.
_HOP_BY_HOP = {
    b"connection", b"keep-alive", b"proxy-authenticate",
    b"proxy-authorization", b"te", b"trailer", b"transfer-encoding",
    b"upgrade", b"host",
}


def _pass_headers(pairs) -> list[tuple[bytes, bytes]]:
    return [(k, v) for k, v in pairs if k.lower() not in _HOP_BY_HOP]


class SpectraProxy:
    """ASGI app: app.mount("/spectra", SpectraProxy(port)). The backend URL
    keeps the /spectra prefix because the standalone process serves the same
    /spectra URL space."""

    @staticmethod
    def _sub_path(scope) -> str:
        # Starlette's Mount has shipped both semantics: full path with
        # root_path set (current), or pre-stripped path. Normalize to the
        # path below the mount, then re-prefix for the backend.
        path = scope["path"]
        root = scope.get("root_path", "")
        if root and path.startswith(root):
            path = path[len(root):]
        return path

    def __init__(self, port: int, host: str = "127.0.0.1"):
        self.base = f"http://{host}:{port}"
        self.ws_base = f"ws://{host}:{port}"
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        # Lazy: needs the running loop. Process-lifetime — mounted ASGI apps
        # get no lifespan from Starlette, so there is no close hook to wire.
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base,
                timeout=httpx.Timeout(READ_TIMEOUT_S,
                                      connect=CONNECT_TIMEOUT_S),
                limits=httpx.Limits(max_connections=20),
            )
        return self._client

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            await self._proxy_http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._proxy_ws(scope, receive, send)
        elif scope["type"] == "lifespan":
            # Consume politely so a bare-mounted proxy can't wedge startup.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

    # ── HTTP ─────────────────────────────────────────────────────────────────

    async def _proxy_http(self, scope, receive, send) -> None:
        url = "/spectra" + self._sub_path(scope)
        if scope.get("query_string"):
            url += "?" + scope["query_string"].decode("latin-1")

        async def request_body():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if body := message.get("body", b""):
                    yield body
                if not message.get("more_body"):
                    return

        request = self._http().build_request(
            scope["method"], url,
            headers=_pass_headers(scope.get("headers", [])),
            content=None if scope["method"] in ("GET", "HEAD")
            else request_body(),
        )
        try:
            response = await self._http().send(request, stream=True)
        except httpx.HTTPError as exc:
            await self._bad_gateway(send, exc)
            return
        try:
            await send({
                "type": "http.response.start",
                "status": response.status_code,
                "headers": _pass_headers(response.headers.raw),
            })
            async for chunk in response.aiter_raw():
                await send({"type": "http.response.body", "body": chunk,
                            "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        finally:
            await response.aclose()

    async def _bad_gateway(self, send, exc: Exception) -> None:
        body = (b'{"detail": "SPECTRA process unreachable at '
                + self.base.encode()
                + b' \xe2\x80\x94 is spectra.service running? '
                + b'(systemctl --user status spectra)"}')
        logger.warning("spectra proxy: backend unreachable (%r)", exc)
        await send({"type": "http.response.start", "status": 502,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    # ── WebSocket ────────────────────────────────────────────────────────────

    async def _proxy_ws(self, scope, receive, send) -> None:
        import asyncio

        import websockets

        message = await receive()
        if message["type"] != "websocket.connect":
            return
        url = self.ws_base + "/spectra" + self._sub_path(scope)
        try:
            backend = await websockets.connect(url,
                                               open_timeout=CONNECT_TIMEOUT_S)
        except Exception as exc:
            logger.warning("spectra proxy: WS backend unreachable (%r)", exc)
            await send({"type": "websocket.close", "code": 1013})
            return
        await send({"type": "websocket.accept"})

        async def client_to_backend():
            while True:
                msg = await receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("text") is not None:
                    await backend.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await backend.send(msg["bytes"])

        async def backend_to_client():
            async for data in backend:
                if isinstance(data, str):
                    await send({"type": "websocket.send", "text": data})
                else:
                    await send({"type": "websocket.send", "bytes": data})

        pumps = [asyncio.create_task(client_to_backend()),
                 asyncio.create_task(backend_to_client())]
        try:
            done, pending = await asyncio.wait(
                pumps, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(
                        exc, websockets.ConnectionClosed):
                    logger.debug("spectra proxy: WS pump ended: %r", exc)
        finally:
            await backend.close()
            try:
                await send({"type": "websocket.close", "code": 1000})
            except Exception:
                pass   # client already gone
