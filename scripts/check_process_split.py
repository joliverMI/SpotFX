"""Executable spec for the S3 PROCESS SPLIT — the cross-process seams,
proven on real processes and real sockets.

The split's claims, each pinned here:
  1. INTERPRETER ISOLATION: importing the whole spot-effects app loads
     nothing under spectra/ — her code cannot run in that interpreter; the
     /spectra mount is the reverse proxy, not her app.
  2. THE STANDALONE PROCESS: python -m spectra boots, serves the /spectra
     URL space, and runs the tight switch interval (0.001 — the Stage-1
     GIL mitigation, asserted on the real process via /api/status).
  3. THE READ-ONLY BRIDGE crosses the process boundary: a broadcast on the
     (fake) spot-effects /ws lands classified in the SPECTRA process, and
     the end-to-end latency is MEASURED and printed.
  4. THE LIVENESS CONTRACT keeps its address and semantics on BOTH ports:
     the same payload served direct and through the real SpectraProxy,
     status code passed through verbatim; the WS surface bridges too.
  5. THE OWNERSHIP RECORD + handover state machine work cross-process:
     transitions made by one process are visible and ENFORCED in another
     (begin refused while in flight, the quiesce gate blocks grants, flock
     excludes concurrent transitions ACROSS processes, commit lands).
  6. Graceful shutdown: SIGTERM lands exit 0 (the deploy-restart path).

Run from repo root:  .venv/bin/python scripts/check_process_split.py
Isolated: every port ephemeral loopback (NEVER 8000/8010 — the live app
may be on this box), storage in temp dirs, no device, no audio, no LedFX.

(No `from __future__ import annotations` here on purpose: the in-function
FastAPI endpoints' annotations must resolve at runtime.)
"""
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PY = sys.executable


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── record worker mode: each invocation is a FRESH PROCESS sharing the
#    record file — the cross-process actor for section 5 ────────────────────

def _record_worker() -> None:
    record_path, op, *args = sys.argv[2:]
    from fx import light_ownership as lo
    lo.OWNERSHIP_FILE = Path(record_path)
    out: dict = {}
    try:
        if op == "begin":
            out["token"] = lo.begin_handover(args[0]).token
        elif op == "quiesce":
            lo.mark_quiesced(args[0])
        elif op == "commit":
            lo.commit(args[0])
        elif op == "mint":
            lo.mint_activation_grant(args[0])
        elif op == "read":
            record = lo.load()
            out = {"owner": record.owner,
                   "step": record.handover.step if record.handover else None}
        elif op == "writes-allowed":
            out["allowed"] = lo.writes_allowed(args[0])
        elif op == "hold-lock":
            with lo._Locked():
                print(json.dumps({"holding": True}), flush=True)
                time.sleep(float(args[0]))
            print(json.dumps({"released": True}), flush=True)
            return
        print(json.dumps(out or {"ok": True}), flush=True)
    except lo.OwnershipError as exc:
        print(json.dumps({"refused": str(exc)}), flush=True)


if len(sys.argv) > 1 and sys.argv[1] == "--record-worker":
    _record_worker()
    sys.exit(0)


def worker(record_path: Path, op: str, *args: str) -> dict:
    out = subprocess.run(
        [PY, __file__, "--record-worker", str(record_path), op, *args],
        capture_output=True, text=True, cwd=REPO, timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"record worker crashed: {op} {args}\n{out.stderr}")
    return json.loads(out.stdout.splitlines()[-1])


# ═════════════════════════════════════════════════════════════════════════════
print("— 1. interpreter isolation —")

out = subprocess.run(
    [PY, "-c",
     "import main, sys, json; print(json.dumps(sorted("
     "m for m in sys.modules if m.split('.')[0] == 'spectra')))"],
    capture_output=True, text=True, cwd=REPO, timeout=180)
check(out.returncode == 0, "the spot-effects app imports clean")
check(json.loads(out.stdout.splitlines()[-1]) == [],
      "importing the spot-effects app loads ZERO spectra modules")

import main as spotfx_main                                    # noqa: E402
from services.spectra_proxy import SpectraProxy               # noqa: E402

mounts = {getattr(r, "path", None): r for r in spotfx_main.app.routes}
check(isinstance(mounts.get("/spectra").app, SpectraProxy),
      "/spectra on the spot-effects app is the reverse proxy, not her app")

from spectra.api.ownership import LIVENESS_ADDRESS            # noqa: E402

check(LIVENESS_ADDRESS == "/spectra/api/liveness",
      "the liveness contract address constant is unchanged")

print("— 1b. spectra import discipline (the reverse direction) —")

out = subprocess.run(
    [PY, "-c",
     "import spectra.app, sys, json; print(json.dumps(sorted("
     "m for m in sys.modules if m == 'api' or m.startswith('api.') "
     "or m == 'main' or m == 'services' or m.startswith('services.'))))"],
    capture_output=True, text=True, cwd=REPO, timeout=180)
check(out.returncode == 0, "importing the spectra app imports clean")
check(json.loads(out.stdout.splitlines()[-1]) == [],
      "importing the spectra app loads ZERO spot-effects runtime internals "
      "(top-level api.*/services.*/main — only fx/ and spectra/'s own code; "
      "the panic release's external-LedFX calls go through "
      "spectra/services/ledfx_release.py, a direct client, precisely so "
      "this stays clean)")


# ═════════════════════════════════════════════════════════════════════════════
print("— 2–4. the standalone process, the bridge, the proxied contract —")


async def live_process_sections() -> None:
    import httpx
    import uvicorn
    import websockets
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect

    fake_port, child_port, proxy_port = free_port(), free_port(), free_port()
    storage = Path(tempfile.mkdtemp(prefix="split-spec-storage-"))

    # The fake spot-effects world: /ws broadcasts + the settings poll.
    clients: list = []
    fake = FastAPI()

    @fake.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        clients.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            clients.remove(websocket)

    @fake.get("/api/settings")
    async def settings():
        return {"force_scene_enabled": False}

    async def serve(app, port):
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning",
            lifespan="off"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        return server, task

    fake_srv = await serve(fake, fake_port)

    # Self-test the fake /ws before blaming the child: a local client must
    # be able to complete the upgrade handshake.
    import websockets as _ws
    async with _ws.connect(f"ws://127.0.0.1:{fake_port}/ws",
                           open_timeout=5) as probe_ws:
        await probe_ws.send("probe")
    while clients:
        await asyncio.sleep(0.02)
    check(True, "fake spot-effects /ws accepts upgrades (self-test)")

    # The REAL proxy (the exact class main.py mounts) in front of the child.
    front = FastAPI()
    front.mount("/spectra", SpectraProxy(child_port))
    front_srv = await serve(front, proxy_port)

    # The REAL standalone process.
    child = subprocess.Popen(
        [PY, "-m", "spectra"], cwd=REPO,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        env={**os.environ,
             "SPECTRA_HOST": "127.0.0.1",
             "SPECTRA_PORT": str(child_port),
             "SPECTRA_STORAGE_DIR": str(storage),
             "SPECTRA_BRIDGE_WS_URL": f"ws://127.0.0.1:{fake_port}/ws",
             "SPECTRA_BRIDGE_HTTP_URL": f"http://127.0.0.1:{fake_port}"})
    try:
        base = f"http://127.0.0.1:{child_port}"
        async with httpx.AsyncClient(timeout=5.0) as http:
            status = None
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise SystemExit("FAIL: standalone process died: "
                                     + (child.stderr.read() or "")[-2000:])
                try:
                    resp = await http.get(base + "/spectra/api/status")
                    if resp.status_code == 200:
                        status = resp.json()
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            check(status is not None, "python -m spectra boots and serves "
                                      "the /spectra URL space")
            check(status["app"] == "SPECTRA", "it is SPECTRA")
            check(status["switch_interval_s"] == 0.001,
                  "the real process runs sys.setswitchinterval(0.001) — the "
                  "Stage-1 GIL mitigation, applied at last")

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not clients:
                await asyncio.sleep(0.05)
            if not clients:
                child.send_signal(signal.SIGTERM)
                try:
                    _, err = child.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    _, err = child.communicate()
                print("child stderr tail:\n" + "\n".join(
                    (err or "").splitlines()[-20:]), file=sys.stderr)
            check(bool(clients),
                  "the bridge connected to the fake spot-effects /ws — a "
                  "REAL socket into another process")

            # A state broadcast crosses and lands in the bridge's feeds.
            await clients[0].send_json({
                "type": "state", "paused": False,
                "track": {"spotify_uri": "spotify:track:split-spec",
                          "title": "Split Spec", "is_playing": True,
                          "progress_ms": 1000}})
            deadline = time.monotonic() + 10
            seen_track = None
            while time.monotonic() < deadline:
                engine_status = (await http.get(
                    base + "/spectra/api/engine/status")).json()
                seen_track = (engine_status["bridge"].get("track") or {}).get("uri")
                if seen_track == "spotify:track:split-spec":
                    break
                await asyncio.sleep(0.05)
            check(seen_track == "spotify:track:split-spec",
                  "a state broadcast crossed the boundary into the bridge")

            # A trigger fire crosses, is classified, and the latency is real.
            t0 = time.monotonic()
            await clients[0].send_json({
                "type": "trigger_fired", "event_type": "charge",
                "event_name": "split-spec-charge", "intensity": 0.8})
            latency_s = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                engine_status = (await http.get(
                    base + "/spectra/api/engine/status")).json()
                if engine_status["bridge"]["counts"]["responses"] >= 1:
                    latency_s = time.monotonic() - t0
                    break
                await asyncio.sleep(0.005)
            check(latency_s is not None and latency_s < 1.0,
                  "a trigger fire crossed and was classified as a response")
            last = engine_status["bridge"]["last_event"]
            check(last["class"] == "charge" and last["intensity"] == 0.8,
                  "classification and intensity survived the boundary")
            print(f"   measured bridge latency: {latency_s * 1000:.1f} ms "
                  "(broadcast → classified in the SPECTRA process, upper "
                  "bound incl. 5 ms poll granularity)")

            # The liveness contract, direct and through the REAL proxy.
            direct = await http.get(base + "/spectra/api/liveness")
            proxied = await http.get(
                f"http://127.0.0.1:{proxy_port}/spectra/api/liveness")
            check(direct.status_code == proxied.status_code == 200,
                  "liveness answers on the direct port AND the proxied "
                  "address (spot-effects owns by default, provably dark → "
                  "healthy)")
            d, p = direct.json(), proxied.json()
            for key in ("contract", "address", "owner", "state", "healthy"):
                check(d[key] == p[key],
                      f"liveness field {key!r} identical direct vs proxied")
            check(d["address"] == "/spectra/api/liveness",
                  "the contract names its own stable address")
            check(d["owner"] == "spot-effects" and d["state"] == "dark",
                  "start WITHOUT ownership: the real boot stays dark "
                  "(engine recording, no live stack)")
            engine_status = (await http.get(
                base + "/spectra/api/engine/status")).json()
            check(engine_status["dark"] is True,
                  "the engine came up dark (recording executor)")

            # The WS surface bridges through the proxy too.
            async with websockets.connect(
                    f"ws://127.0.0.1:{proxy_port}/spectra/api/ws",
                    open_timeout=5) as bridge_ws:
                await bridge_ws.send("ping")
            check(True, "/spectra/api/ws handshakes through the proxy")

        # Graceful shutdown: the deploy-restart path. uvicorn re-raises the
        # caught signal after finishing (so managers see the true cause):
        # exit-by-SIGTERM plus the lifespan's own completion line IS the
        # clean path — systemd counts stop-by-SIGTERM as success.
        child.send_signal(signal.SIGTERM)
        rc = child.wait(timeout=20)
        err = child.stderr.read() or ""
        check(rc in (0, -signal.SIGTERM),
              f"SIGTERM terminates promptly and gracefully (rc={rc})")
        check("SPECTRA shutdown complete." in err,
              "the lifespan shutdown ran to completion (engine stopped, "
              "room outputs released before exit)")
    finally:
        if child.poll() is None:
            child.kill()
        for server, task in (front_srv, fake_srv):
            server.should_exit = True
            await task


asyncio.run(live_process_sections())


# ═════════════════════════════════════════════════════════════════════════════
print("— 5. the ownership record + handover, cross-process —")

record = Path(tempfile.mkdtemp(prefix="split-spec-record-")) / "ownership.json"

check(worker(record, "read")["owner"] == "spot-effects",
      "fresh process reads the shipped default")

token = worker(record, "begin", "spectra")["token"]
state = worker(record, "read")
check(state["owner"] == "handing-over" and state["step"] == "quiescing",
      "a begin in process A is visible in process B")
check("refused" in worker(record, "begin", "spectra"),
      "process B cannot start a second handover (in-flight excluded "
      "cross-process)")
check("refused" in worker(record, "mint", "spectra"),
      "process B cannot mint a device grant before the quiesce gate")
check("refused" in worker(record, "quiesce", "not-the-token"),
      "a wrong token is refused from any process")

worker(record, "quiesce", token)
check(worker(record, "read")["step"] == "activating",
      "the quiesce gate passed in one process opens the next step in all")
check(worker(record, "mint", "spectra").get("ok"),
      "past the gate, a THIRD process mints the activation grant")

worker(record, "commit", token)
state = worker(record, "read")
check(state["owner"] == "spectra",
      "commit in one process lands the owner for every process")
check(worker(record, "writes-allowed", "spectra")["allowed"] is True
      and worker(record, "writes-allowed", "spot-effects")["allowed"] is False,
      "write gates across processes obey the committed record")

# flock excludes ACROSS processes: a held lock stalls another process's
# transition until release.
holder = subprocess.Popen(
    [PY, __file__, "--record-worker", str(record), "hold-lock", "1.2"],
    stdout=subprocess.PIPE, text=True, cwd=REPO)
check(json.loads(holder.stdout.readline())["holding"] is True,
      "process A holds the record lock")
t0 = time.monotonic()
token2 = worker(record, "begin", "spot-effects")["token"]
elapsed = time.monotonic() - t0
holder.wait(timeout=10)
check(elapsed > 0.6,
      f"process B's transition BLOCKED on A's flock ({elapsed:.2f}s) — "
      "exclusive across processes, not just threads")
state = worker(record, "read")
check(state["owner"] == "handing-over" and bool(token2),
      "the blocked transition then proceeded correctly")

print()
print("PROCESS SPLIT SPEC: ALL CHECKS PASSED")
