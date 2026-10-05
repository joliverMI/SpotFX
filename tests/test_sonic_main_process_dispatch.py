"""SONIC'S TOOLS RUN IN THE MAIN PROCESS (Light Show room proof D1).

THE INCIDENT (2026-10-04): with SPECTRA_SETTINGS_AGENT_BACKEND=cli, Sonic's
tools ran inside settings_mcp_server.py — a stdio subprocess of the
`claude` CLI with no live light stack. Every Light Show fire refused "live
stack is not up" while the room was live, and an arm replied "Armed" but
was overwritten by the main process's own arm board: a silent false
success.

Now the subprocess FORWARDS every call to POST
/api/settings-console/dispatch on the main process. Proven here through the
real `_call` wrapper, the real route (ASGI transport into the real app) and
the real `_dispatch`; an unreachable main process is a stated rejection.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from spectra.services import settings_agent, settings_agent_cli
from spectra.services import settings_mcp_server as srv


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def app():
    from spectra.app import create_app
    return create_app()


def _route_into(monkeypatch, app) -> list:
    """Every httpx.AsyncClient the wrapper opens talks to the real app;
    returns the list of requests that crossed the wire."""
    real = httpx.AsyncClient
    sent: list = []

    class Counting(httpx.ASGITransport):
        async def handle_async_request(self, request):
            sent.append((request.method, request.url.path))
            return await super().handle_async_request(request)

    def factory(*a, **kw):
        kw["transport"] = Counting(app=app)
        return real(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return sent


def test_a_tool_call_is_executed_by_the_main_process(monkeypatch, app):
    seen = []

    async def handler(**kw):
        seen.append(kw)
        return {"status": "applied", "summary": "ran in the main process"}
    import dataclasses
    op = settings_agent.ALL_OPERATIONS["show_status"]
    monkeypatch.setitem(settings_agent.ALL_OPERATIONS, "show_status",
                        dataclasses.replace(op, handler=handler))
    sent = _route_into(monkeypatch, app)
    monkeypatch.setenv(settings_agent.DISPATCH_URL_ENV,
                       "http://spectra/api/settings-console/dispatch")
    monkeypatch.setenv(settings_agent.DISPATCH_TOKEN_ENV,
                       settings_agent.DISPATCH_TOKEN)
    out = _run(srv._call("show_status"))
    assert out == {"status": "applied", "summary": "ran in the main process"}
    assert seen == [{}]
    assert sent == [("POST", "/api/settings-console/dispatch")], (
        "the tool ran inside the MCP subprocess, not the main process")


def test_an_unreachable_main_process_is_a_stated_rejection(monkeypatch):
    monkeypatch.setenv(settings_agent.DISPATCH_URL_ENV,
                       "http://127.0.0.1:9/api/settings-console/dispatch")
    monkeypatch.setenv(settings_agent.DISPATCH_TOKEN_ENV, "x")
    out = _run(srv._call("arm_show_set", set_name="anything", on="high"))
    assert out["status"] == "rejected"
    assert "could not be reached" in out["reason"]


def test_the_route_refuses_a_missing_or_wrong_token(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        r = client.post("/api/settings-console/dispatch",
                        json={"name": "show_status", "args": {}})
        assert r.status_code == 403
        r = client.post("/api/settings-console/dispatch",
                        json={"name": "show_status", "args": {}},
                        headers={"X-Sonic-Dispatch-Token": "wrong"})
        assert r.status_code == 403
        r = client.post("/api/settings-console/dispatch",
                        json={"name": "no_such_op", "args": {}},
                        headers={"X-Sonic-Dispatch-Token":
                                 settings_agent.DISPATCH_TOKEN})
        assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_the_cli_backend_tells_its_server_where_the_main_process_is(
        tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    env = settings_agent_cli._subprocess_env("tok", tmp_path)
    assert env[settings_agent.DISPATCH_URL_ENV] == settings_agent.dispatch_url()
    assert env[settings_agent.DISPATCH_TOKEN_ENV] == settings_agent.DISPATCH_TOKEN
    assert "NOTIFY_SOCKET" not in env
    server = json.loads(settings_agent_cli._mcp_config_json())[
        "mcpServers"][settings_agent_cli.MCP_SERVER_NAME]
    assert server["env"][settings_agent.DISPATCH_URL_ENV].endswith(
        "/spectra/api/settings-console/dispatch")
