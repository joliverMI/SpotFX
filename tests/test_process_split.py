"""The S3 process split, proven offline.

The headline test is the 2026-08-13 diagnosis INVERTED: the render plane
holds full frame rate in its own interpreter while a foreign process runs
the exact synthetic GIL burst that freezes it in-process. Plus the
spot-effects-side proxy (HTTP + WS bridging, 502 honesty) and the SPECTRA
frame-watchdog predicate rows.

Same conventions as the rest of the suite: plain pytest, tests drive their
own loop, no live access — every socket is ephemeral loopback.
"""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROBE = REPO / "tests" / "gil_probe.py"

sys.path.insert(0, str(REPO))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── The frame-rate proof ──────────────────────────────────────────────────────

def _run_probe(burst: str, parent_burst_during_measure: bool) -> dict:
    """Run tests/gil_probe.py as a REAL child process. The probe prints
    MEASURING when its window opens; if parent_burst_during_measure, this
    process (standing in for the SpotFX app) then burns the same synthetic
    GIL burst beside it for the whole window."""
    from tests import gil_probe

    proc = subprocess.Popen(
        [sys.executable, str(PROBE), "--burst", burst,
         "--warmup", "2", "--measure", "5"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True)
    try:
        line = ""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line.strip() == "MEASURING" or line.startswith("{"):
                break
        if parent_burst_during_measure and line.strip() == "MEASURING":
            gil_probe.burn(gil_probe.make_blob(), 5.0)
        if not line.startswith("{"):
            line = proc.stdout.readline()
        out, _ = proc.communicate(timeout=60)
        payload = line if line.startswith("{") else out.splitlines()[-1]
        return json.loads(payload)
    finally:
        proc.kill()


def test_render_holds_frame_rate_beside_a_bursting_foreign_process():
    """The split's whole point: a 5 s C-level GIL burst in ANOTHER process
    (this one — standing in for the SpotFX app's analysis ingest) cannot
    touch the render process's pacing."""
    result = _run_probe("none", parent_burst_during_measure=True)
    assert result["fps"] > 55, result
    assert result["gap_max_ms"] < 200, result


def test_shared_interpreter_reproduces_the_freeze():
    """The control arm — the same burst INSIDE the render process starves
    the render thread (the live 5.3 s full freeze, reproduced). Proves the
    measurement detects the disease the other test claims is absent."""
    result = _run_probe("inline", parent_burst_during_measure=False)
    assert result["fps"] < 10, result


# ── Frame-watchdog predicate ─────────────────────────────────────────────────

def test_frame_watchdog_predicate_rows():
    from fx import light_ownership as lo
    from spectra.services.frame_watchdog import evaluate

    # Live and owned: freshness decides.
    assert evaluate(lo.SPECTRA, True, True) == (True, None)
    alive, reason = evaluate(lo.SPECTRA, True, False)
    assert not alive and "stale" in reason
    # Split-brain: live stack without ownership — restart is the fix.
    alive, reason = evaluate(lo.SPOT_EFFECTS, True, True)
    assert not alive and "split-brain" in reason
    # Mid-handover activation is legitimate; never race the orchestrator.
    assert evaluate(lo.HANDING_OVER, True, False) == (True, None)
    # Dark process = healthy process, in EVERY ownership state —
    # dark-but-owned must never restart-loop.
    for owner in (lo.SPECTRA, lo.SPOT_EFFECTS, lo.HANDING_OVER):
        assert evaluate(owner, False, False) == (True, None)


# ── The reverse proxy ────────────────────────────────────────────────────────

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402


def _backend_app():
    """Stands in for the standalone SPECTRA process: serves the same
    /spectra URL space (that is the proxy's forwarding contract)."""
    app = FastAPI()

    @app.get("/spectra/api/ping")
    async def ping(request: Request):
        return {"pong": True, "q": dict(request.query_params)}

    @app.get("/spectra/api/unhealthy")
    async def unhealthy():
        return JSONResponse({"healthy": False}, status_code=503)

    @app.post("/spectra/api/echo")
    async def echo(request: Request):
        return {"got": (await request.body()).decode()}

    @app.websocket("/spectra/api/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                text = await websocket.receive_text()
                await websocket.send_text("echo:" + text)
        except WebSocketDisconnect:
            pass

    return app


def _front_app(port: int):
    from services.spectra_proxy import SpectraProxy

    app = FastAPI()
    app.mount("/spectra", SpectraProxy(port))
    return app


async def _serve(app, port: int):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


async def _stop(server, task):
    server.should_exit = True
    await task


def test_proxy_http_passthrough_ws_bridge_and_502():
    async def scenario():
        import httpx
        import websockets

        backend_port, front_port, dead_port = (free_port(), free_port(),
                                               free_port())
        backend = await _serve(_backend_app(), backend_port)
        front = await _serve(_front_app(backend_port), front_port)
        try:
            async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{front_port}") as client:
                # Path + query + body pass through unchanged.
                resp = await client.get("/spectra/api/ping?a=1&b=x")
                assert resp.status_code == 200
                assert resp.json() == {"pong": True, "q": {"a": "1", "b": "x"}}
                resp = await client.post("/spectra/api/echo", content=b"hi")
                assert resp.json() == {"got": "hi"}
                # Non-200 statuses arrive verbatim — a liveness 503 must
                # reach the fleet checker as a 503, not a proxy error.
                resp = await client.get("/spectra/api/unhealthy")
                assert resp.status_code == 503
                assert resp.json() == {"healthy": False}

            # WebSocket bridged both directions.
            async with websockets.connect(
                    f"ws://127.0.0.1:{front_port}/spectra/api/ws") as ws:
                await ws.send("hello")
                assert await asyncio.wait_for(ws.recv(), 5) == "echo:hello"
                await ws.send("again")
                assert await asyncio.wait_for(ws.recv(), 5) == "echo:again"

            # Backend down → honest 502 naming spectra.service.
            dead_front = await _serve(_front_app(dead_port), free_port())
            try:
                port = dead_front[0].config.port
                async with httpx.AsyncClient(
                        base_url=f"http://127.0.0.1:{port}") as client:
                    resp = await client.get("/spectra/api/ping")
                    assert resp.status_code == 502
                    assert "spectra.service" in resp.text
            finally:
                await _stop(*dead_front)
        finally:
            await _stop(*front)
            await _stop(*backend)

    asyncio.run(scenario())


# ── Startup resume: restart-while-owner re-lights the room ──────────────────
# The operational gap proven twice on 2026-08-13: a spectra restart with
# ownership at spectra left the room dark until a manual handover cycle.
# These enter the REAL _standalone_lifespan / resume_own_room with the
# headless harness (dummy device, silenced audio, temp ownership record).

def _make_spectra_owner(lo) -> None:
    """Drive the record to owner=spectra through the real state machine."""
    handover = lo.begin_handover(lo.SPECTRA)
    lo.mark_quiesced(handover.token)
    lo.commit(handover.token)


def test_standalone_lifespan_resumes_when_spectra_owns(tmp_path, monkeypatch):
    import functools

    from fx import headless, light_ownership as lo
    import spectra.app as spectra_app
    from spectra.services import engine, handover
    from spectra.services.live_host import live

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    _make_spectra_owner(lo)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(
        str(config_dir),
        initial_effect={"type": "singleColor", "config": {"color": "#000080"}})
    # Keep the bridge off real ports (the live app may own 8000 on this box).
    dead = free_port()
    monkeypatch.setattr(engine.bridge, "ws_url", f"ws://127.0.0.1:{dead}/ws")
    monkeypatch.setattr(engine.bridge, "http_url", f"http://127.0.0.1:{dead}")
    # resume_own_room()'s default side, redirected at the harness.
    monkeypatch.setattr(handover, "SpectraSide", functools.partial(
        handover.SpectraSide, config_dir=str(config_dir), open_audio=False))

    async def scenario():
        async with spectra_app._standalone_lifespan(None):
            # Start-with-ownership: the boot sequence itself re-lit the room.
            assert live.active and live.fresh()
            assert engine.executor.mode == "facade"
            from spectra.api.ownership import get_liveness
            resp = await get_liveness()
            assert resp.status_code == 200
            body = json.loads(bytes(resp.body))
            assert body["owner"] == "spectra" and body["state"] == "live"
        # Lifespan exit released the room outputs; the record is untouched —
        # the NEXT start resumes again.
        assert not live.active
        assert engine.executor.mode == "recording"
        assert lo.load().owner == lo.SPECTRA

    asyncio.run(scenario())


def test_resume_stays_dark_without_ownership(tmp_path, monkeypatch):
    from fx import headless, light_ownership as lo
    from spectra.services.handover import SpectraSide, resume_own_room
    from spectra.services.live_host import live

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))

    async def scenario():
        # Missing record = spot-effects owns (the shipped default).
        resumed = await resume_own_room(
            SpectraSide(config_dir=str(config_dir), open_audio=False))
        assert resumed is False
        assert not live.active
        assert not lo.OWNERSHIP_FILE.exists()

    asyncio.run(scenario())


def test_resume_failure_lands_dark_but_owned(tmp_path, monkeypatch):
    from fx import headless, light_ownership as lo
    from spectra.services import engine
    from spectra.services.handover import SpectraSide, resume_own_room
    from spectra.services.live_host import live

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    _make_spectra_owner(lo)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(
        str(config_dir),
        initial_effect={"type": "singleColor", "config": {"color": "#000080"}})

    # A HARD failure — live.activate() itself raises (host.start() erroring,
    # a bad grant, no devices at all) — is the case that must land dark. A
    # virtual/device that merely never came up (the crystal lazy-activation
    # class) is a SOFT gap instead: activate() no longer raises on that, and
    # resume_own_room reports it loudly while keeping whatever DID come up
    # (owner amendment, 2026-08-13 — see spectra/services/handover.py's
    # resume_own_room docstring). That soft-gap path is covered by
    # tests/test_crystal_activation_verify.py, not here.
    async def boom(*args, **kwargs):
        raise RuntimeError("simulated hard activation failure")

    monkeypatch.setattr(live, "activate", boom)

    async def scenario():
        resumed = await resume_own_room(
            SpectraSide(config_dir=str(config_dir), open_audio=False))
        assert resumed is False
        assert not live.active
        assert engine.executor.mode == "recording"
        # Record untouched: dark-but-owned, liveness 503 carries the alarm.
        assert lo.load().owner == lo.SPECTRA

    asyncio.run(scenario())


def test_resume_refuses_on_unusable_fx_live_config(tmp_path, monkeypatch):
    """The order-8 readiness gate applies to the resume path too: with a
    missing/empty fx-live config, activation would 'succeed' with zero
    virtuals (freshness vacuously true) and liveness would claim live over a
    dark room. The resume must refuse the same way the handover does —
    dark-but-owned, record untouched."""
    from fx import headless, light_ownership as lo
    from spectra.services import engine
    from spectra.services.handover import SpectraSide, resume_own_room
    from spectra.services.live_host import live

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    _make_spectra_owner(lo)
    headless.silence_audio()
    # No write_headless_config: the go-day seeding step never ran.
    config_dir = tmp_path / "fx-live-unseeded"

    async def scenario():
        resumed = await resume_own_room(
            SpectraSide(config_dir=str(config_dir), open_audio=False))
        assert resumed is False
        assert not live.active
        assert engine.executor.mode == "recording"
        assert lo.load().owner == lo.SPECTRA

    asyncio.run(scenario())


# ── Interpreter isolation wiring ─────────────────────────────────────────────

def test_spotfx_process_imports_no_spectra_module():
    """The guarantee that makes the split real: importing the whole
    spot-effects app pulls in NOTHING under spectra/ — her code cannot run
    in this interpreter even by accident."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import main, sys, json; "
         "print(json.dumps(sorted(m for m in sys.modules "
         "if m.split('.')[0] == 'spectra')))"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.splitlines()[-1]) == []


def test_spotfx_mounts_the_proxy_at_spectra():
    import main
    from services.spectra_proxy import SpectraProxy

    mounts = {getattr(r, "path", None): r for r in main.app.routes}
    assert "/spectra" in mounts
    assert isinstance(mounts["/spectra"].app, SpectraProxy)
