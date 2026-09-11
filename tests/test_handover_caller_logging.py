"""THE HANDOVER ROUTE NAMES ITS CALLER — and names the CALLER, not itself.

River built the same capture on her own endpoint and it resolved THE WRONG
SIDE: it printed the pid and cmdline of her own listening process, so every
entry named herself and identified nobody. The assertions that matter here
are therefore the DISCRIMINATING ones, and they are stated as pairs:

  * the resolved pid IS a known child process's, and IS NOT this process's
    own (sections 1 and 2) — the exact way River's version is wrong;
  * a caller that genuinely cannot be resolved is SAID to be unresolvable
    and still does not report a local pid (section 3) — the same failure
    arriving through the other door;
  * a lookup that raises, hangs or finds nothing leaves the handover
    committed and bounded (section 4);
  * no Authorization header and no token on a command line reaches the log
    (section 5).

Real sockets and a real second process throughout — a fake peer proves
nothing about which end of a socket the lookup walks. Nothing here touches
his storage or his room: the handover itself is stubbed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from fx import light_ownership
from spectra import config
from spectra.api import ownership as ownership_api
from spectra.services import caller_identity
from spectra.services import handover as handover_svc

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── helpers ─────────────────────────────────────────────────────────────────

def _child_connect_script(port: int, marker: str) -> str:
    """A child that CONNECTS and then holds the socket open, so the lookup
    runs against a live connection the way a real request does."""
    return textwrap.dedent(f"""
        import socket, sys, time
        marker = {marker!r}
        s = socket.create_connection(("127.0.0.1", {port}))
        sys.stdout.write(str(s.getsockname()[1]) + "\\n")
        sys.stdout.flush()
        time.sleep(30)
    """)


def _child_request_script(port: int, marker: str, headers: dict) -> str:
    return textwrap.dedent(f"""
        import json, sys, urllib.request
        marker = {marker!r}
        req = urllib.request.Request(
            "http://127.0.0.1:{port}/api/ownership/handover",
            data=json.dumps({{"to": "spectra"}}).encode(),
            headers={headers!r}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            sys.stdout.write(str(resp.status) + " " + resp.read().decode())
    """)


class _FakeRequest:
    """Exactly the three things `snapshot()` reads off a Starlette request."""

    class _Client:
        def __init__(self, host, port):
            self.host, self.port = host, port

    def __init__(self, peer, server, headers=None):
        self.client = self._Client(*peer) if peer else None
        self.scope = {"server": server}
        self.headers = headers or {}


async def _serve(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        lifespan="off"))
    task = asyncio.create_task(server.serve())
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:      # pragma: no cover
            raise AssertionError("uvicorn did not start")
        await asyncio.sleep(0.02)
    return server, task


async def _stop(server, task):
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=10)
    except asyncio.TimeoutError:             # pragma: no cover
        task.cancel()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ownership_app(monkeypatch, tmp_path, *, commit=True):
    """The REAL ownership router, with only the act stubbed out.

    The route's own `_record_json()` reads the ownership record, so the
    record file is repointed at a tmp copy: this test must never read or
    write his real `storage/spectra/ownership.json`."""
    from fastapi import FastAPI

    monkeypatch.setattr(light_ownership, "OWNERSHIP_FILE",
                        tmp_path / "ownership.json")
    monkeypatch.setattr(config, "handover_armed", lambda: True)
    monkeypatch.setattr(handover_svc, "production_sides",
                        lambda **kw: {}, raising=True)

    async def _fake_run_handover(to_world, sides, **kwargs):
        if not commit:                        # pragma: no cover
            raise handover_svc.HandoverFailed("stubbed failure")
        record = light_ownership.load()
        record.owner = to_world
        return record

    monkeypatch.setattr(handover_svc, "run_handover", _fake_run_handover)
    app = FastAPI()
    app.include_router(ownership_api.router)
    return app


# ── 1. THE ANTI-RIVER PROOF, at the socket ──────────────────────────────────

def test_the_lookup_resolves_the_caller_and_not_this_server(tmp_path):
    """A known child connects; the lookup must name THE CHILD.

    This is the defect River shipped, reproduced as a discriminating pair:
    the pid must equal the child's, and must NOT equal this process's own —
    the listening side, which is what her version printed every time."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    marker = "caller-identity-proof-child"
    child = subprocess.Popen(
        [sys.executable, "-c", _child_connect_script(port, marker)],
        cwd=str(tmp_path), stdout=subprocess.PIPE, text=True)
    try:
        conn, peer = listener.accept()
        server_addr = conn.getsockname()
        caller = caller_identity.describe({
            "peer": f"{peer[0]}:{peer[1]}", "peer_ip": peer[0],
            "peer_port": peer[1],
            "server": f"{server_addr[0]}:{server_addr[1]}",
            "server_ip": server_addr[0], "server_port": server_addr[1],
            "user_agent": None, "forwarded_for": None})

        assert caller.process is not None, caller.reason
        # THE CALLER…
        assert caller.process.pid == child.pid
        assert marker in caller.process.cmdline
        assert caller.process.cwd == os.path.realpath(str(tmp_path))
        # …AND EXPLICITLY NOT THIS SERVER. River's version printed exactly
        # this pid, for every caller, forever.
        assert caller.process.pid != os.getpid()
        assert str(os.getpid()) not in caller.line().split("pid=")[1]
        conn.close()
    finally:
        child.kill()
        child.wait(timeout=10)
        listener.close()


def test_the_mirror_match_cannot_select_the_servers_own_socket(tmp_path):
    """Fed the SERVER's end as if it were the peer, the lookup finds the
    server's socket — proving the two rows really are both present in
    /proc/net/tcp and that section 1's answer was a CHOICE between them,
    not the only row available. A lookup keyed on the wrong end is how
    River's named herself; this asserts which end ours is keyed on."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    child = subprocess.Popen(
        [sys.executable, "-c", _child_connect_script(port, "mirror-child")],
        cwd=str(tmp_path), stdout=subprocess.PIPE, text=True)
    try:
        conn, peer = listener.accept()
        server_addr = conn.getsockname()
        # Deliberately inverted: "peer" = the server's end.
        inverted = caller_identity.describe({
            "peer": None, "peer_ip": server_addr[0],
            "peer_port": server_addr[1],
            "server": None, "server_ip": peer[0], "server_port": peer[1],
            "user_agent": None, "forwarded_for": None})
        assert inverted.process is not None, inverted.reason
        assert inverted.process.pid == os.getpid()

        # …and the right way round, on the very same live connection, it is
        # the child. One socket pair, two answers, and the module takes the
        # caller's.
        correct = caller_identity.describe({
            "peer": None, "peer_ip": peer[0], "peer_port": peer[1],
            "server": None, "server_ip": server_addr[0],
            "server_port": server_addr[1],
            "user_agent": None, "forwarded_for": None})
        assert correct.process is not None, correct.reason
        assert correct.process.pid == child.pid
        conn.close()
    finally:
        child.kill()
        child.wait(timeout=10)
        listener.close()


# ── 2. THE SAME PROOF, through the REAL ROUTE ───────────────────────────────

def test_the_handover_route_names_its_local_caller(monkeypatch, tmp_path,
                                                   caplog):
    """The whole deliverable, end to end: a real uvicorn server, the real
    route, and a REAL separate process making the request."""
    app = _ownership_app(monkeypatch, tmp_path)
    port = _free_port()
    marker = "handover-route-caller-proof"
    ua = "spotfx-test-caller/1.0"

    async def run():
        server, task = await _serve(app, port)
        try:
            child = subprocess.Popen(
                [sys.executable, "-c",
                 _child_request_script(port, marker, {"User-Agent": ua,
                                                      "Content-Type":
                                                      "application/json"})],
                cwd=str(tmp_path), stdout=subprocess.PIPE, text=True)
            out = await asyncio.get_running_loop().run_in_executor(
                None, lambda: child.communicate(timeout=30)[0])
            assert child.returncode == 0, out
            assert out.startswith("200 "), out
            return child.pid
        finally:
            await _stop(server, task)

    with caplog.at_level(logging.WARNING, logger=ownership_api.__name__):
        child_pid = asyncio.run(run())

    lines = [r.getMessage() for r in caplog.records
             if "handover: REQUESTED" in r.getMessage()]
    assert len(lines) == 1, lines
    line = lines[0]
    assert "to=spectra" in line
    assert "peer=127.0.0.1:" in line
    assert f'ua="{ua}"' in line
    assert f"pid={child_pid}" in line
    assert f"cwd={os.path.realpath(str(tmp_path))}" in line
    assert marker in line
    # NOT the server. This is the assertion the task exists for.
    assert f"pid={os.getpid()}" not in line
    assert "NOT RESOLVABLE" not in line


# ── 3. A CALLER THAT CANNOT BE RESOLVED IS SAID SO, NEVER GUESSED ───────────

def test_a_remote_peer_is_reported_unresolvable_rather_than_guessed():
    """A peer that is not on this host has no pid here. Printing one anyway
    would be River's mistake inverted — an honest-looking local pid for a
    caller that was never local."""
    caller = caller_identity.describe(caller_identity.snapshot(
        _FakeRequest(("203.0.113.7", 51234), ("127.0.0.1", 8010),
                     {"user-agent": "curl/8.0"})))
    assert caller.process is None
    assert caller.reason and "not resolvable from here" in caller.reason
    line = caller.line()
    assert "NOT RESOLVABLE" in line
    assert "peer=203.0.113.7:51234" in line
    assert 'ua="curl/8.0"' in line
    assert "pid=" not in line
    assert str(os.getpid()) not in line


def test_a_closed_local_socket_is_reported_as_such():
    """A loopback peer whose socket has already gone gets its OWN sentence —
    'it closed' and 'the caller is not on this host' are different findings
    and a reader deserves to be told which."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    caller = caller_identity.describe(caller_identity.snapshot(
        _FakeRequest(("127.0.0.1", dead_port), ("127.0.0.1", 8010))))
    assert caller.process is None
    assert caller.reason and "closed before it could be read" in caller.reason


def test_no_peer_at_all_is_stated_not_invented():
    caller = caller_identity.describe(
        caller_identity.snapshot(_FakeRequest(None, ("127.0.0.1", 8010))))
    assert caller.process is None
    assert caller.reason and "no peer address" in caller.reason


# ── 4. NEVER FATAL, NEVER SLOW ──────────────────────────────────────────────

def test_a_raising_lookup_leaves_the_handover_committed(monkeypatch,
                                                        tmp_path, caplog):
    from fastapi.testclient import TestClient
    app = _ownership_app(monkeypatch, tmp_path)

    def _boom(_snap, budget_s=None):
        raise RuntimeError("/proc is on fire")

    monkeypatch.setattr(caller_identity, "describe", _boom)
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            resp = client.post("/api/ownership/handover", json={"to": "spectra"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "committed"
    line = [r.getMessage() for r in caplog.records
            if "handover: REQUESTED" in r.getMessage()]
    assert len(line) == 1
    assert "NOT RESOLVABLE" in line[0] and "RuntimeError" in line[0]


def test_a_hanging_lookup_neither_fails_nor_stalls_the_handover(
        monkeypatch, tmp_path, caplog):
    """A wedged /proc must cost the take a BOUNDED wait and nothing else.
    The handover still commits, and the line says the lookup was abandoned
    rather than inventing an answer."""
    from fastapi.testclient import TestClient
    app = _ownership_app(monkeypatch, tmp_path)
    monkeypatch.setattr(caller_identity, "AWAIT_BUDGET_S", 0.2)

    def _wedged(_snap, budget_s=None):
        time.sleep(30)                        # pragma: no cover

    monkeypatch.setattr(caller_identity, "describe", _wedged)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            resp = client.post("/api/ownership/handover", json={"to": "spectra"})
    elapsed = time.monotonic() - started
    assert resp.status_code == 200
    assert resp.json()["result"] == "committed"
    assert elapsed < 5.0, f"a wedged lookup delayed the take by {elapsed:.1f}s"
    line = [r.getMessage() for r in caplog.records
            if "handover: REQUESTED" in r.getMessage()][0]
    assert "abandoned so the take would not wait" in line


def test_a_refused_take_is_named_too(monkeypatch, tmp_path, caplog):
    """A take refused by the armed gate is still a take somebody asked for."""
    from fastapi.testclient import TestClient
    app = _ownership_app(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "handover_armed", lambda: False)
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            resp = client.post("/api/ownership/handover", json={"to": "spectra"})
    assert resp.status_code == 403
    assert any("handover: REQUESTED to=spectra" in r.getMessage()
               for r in caplog.records)


def test_the_budget_is_honoured_inside_the_scan(monkeypatch):
    """The in-thread deadline is checked BETWEEN processes, so a slow /proc
    gives up with a stated reason instead of running to completion."""
    monkeypatch.setattr(caller_identity, "_find_inode_for_test", None,
                        raising=False)
    pid, reason = caller_identity._pid_for_inode(
        "999999999", deadline=time.monotonic() - 1)
    assert pid is None
    assert reason and "budget and gave up" in reason


# ── 5. NO SECRETS ───────────────────────────────────────────────────────────

def test_the_authorization_header_never_reaches_the_log(monkeypatch,
                                                        tmp_path, caplog):
    from fastapi.testclient import TestClient
    app = _ownership_app(monkeypatch, tmp_path)
    secret = "s3cret-bearer-token-do-not-log"
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            resp = client.post("/api/ownership/handover",
                               json={"to": "spectra"},
                               headers={"Authorization": f"Bearer {secret}",
                                        "X-Api-Key": secret,
                                        "Cookie": f"session={secret}"})
    assert resp.status_code == 200
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in logged
    assert "authorization" not in logged.lower()


def test_a_secret_on_the_callers_command_line_is_redacted(tmp_path):
    """The command line is the deliverable and is logged in full — but a
    `curl -H 'Authorization: …'` press of this route would otherwise put a
    token in the log the long way round."""
    for raw, gone in (
            ("curl -H 'Authorization: Bearer abc123XYZ' http://x", "abc123XYZ"),
            ("python run.py --token=tok-987654 --port 1", "tok-987654"),
            ("prog --password hunter2 --keep", "hunter2"),
            ("prog --api-key=AKIAsecret", "AKIAsecret")):
        out = caller_identity.redact(raw)
        assert gone not in out, out
        assert "<redacted>" in out
    # …and an ordinary command line is left completely alone.
    plain = "/home/javi/SpotFX/.venv/bin/python -m spectra"
    assert caller_identity.redact(plain) == plain


def test_redaction_stops_at_the_argv_boundary():
    """A real curl press of this route, as its argv actually arrives.

    The header VALUE is two words inside one argument, so the mask has to be
    greedy within it — and `redact_argv` is what stops that greed at the
    argument's end. Redacting the JOINED string swallowed the `-d` payload
    too, which is forensic detail this whole module exists to keep."""
    argv = ["curl", "-s", "-X", "POST", "http://127.0.0.1:8010/api/x",
            "-H", "Content-Type: application/json",
            "-H", "Authorization: Bearer SUPER-SECRET-123",
            "-d", '{"to":"spectra"}']
    out = caller_identity.redact_argv(argv)
    assert "SUPER-SECRET-123" not in out
    assert "Authorization: <redacted>" in out
    # …everything after the masked argument survives.
    assert '-d {"to":"spectra"}' in out
    assert "Content-Type: application/json" in out
    assert out.startswith("curl -s -X POST http://127.0.0.1:8010/api/x")


def test_only_allowlisted_headers_are_ever_read():
    snap = caller_identity.snapshot(_FakeRequest(
        ("127.0.0.1", 1), ("127.0.0.1", 2),
        {"user-agent": "ua", "x-forwarded-for": "10.0.0.9",
         "authorization": "Bearer nope", "cookie": "session=nope"}))
    assert snap["user_agent"] == "ua"
    assert snap["forwarded_for"] == "10.0.0.9"
    assert "nope" not in repr(snap)
    assert set(caller_identity.SAFE_HEADERS) == {"user-agent",
                                                 "x-forwarded-for"}


# ── the address decoder, both families ──────────────────────────────────────

@pytest.mark.parametrize("hexaddr,expect", [
    ("0100007F", "127.0.0.1"),
    ("00000000", "0.0.0.0"),
    ("0000000000000000FFFF00000100007F", "127.0.0.1"),   # v4-mapped v6
    ("00000000000000000000000001000000", "::1"),
])
def test_proc_net_addresses_decode_and_normalise(hexaddr, expect):
    assert caller_identity._decode_addr(hexaddr) == expect
