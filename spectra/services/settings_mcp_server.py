"""The settings-console's MCP TOOL SURFACE for the "cli" (subscription)
settings-agent backend (spectra/services/settings_agent_cli.py) -- a
stdio MCP server exposing EXACTLY get_settings/set_setting, dispatching
to settings_agent._dispatch(), the SAME exhaustive two-branch mapping the
Anthropic-API backend's tool loop already uses (settings_agent.py's own
docstring: "There is no third branch"). This file adds no authority of
its own -- it is a wire adapter from MCP's stdio protocol onto that one,
already-proven dispatch function, so a CLI-driven agent and an
API-driven agent can never diverge in what either is allowed to do.

Spawned as a SUBPROCESS by `claude -p` itself (see settings_agent_cli.py's
_mcp_config_json(), which names this module by its `python -m` path in
the inline --mcp-config it builds) -- never imported into the main
FastAPI process. Its only job is to exist as a standalone entry point:

    python -m spectra.services.settings_mcp_server

`set_setting`'s `key` parameter is typed as a Literal built from
settings_console.SETTINGS_REGISTRY's own keys at import time, not
re-typed by hand -- the same enum constraint settings_agent.TOOLS
declares for the Anthropic-API path (also read from SETTINGS_REGISTRY),
kept in sync automatically because both read the one registry rather
than each other. The enum is defense-in-depth only: settings_agent.
_dispatch()/settings_console.apply_change() re-validate the key/value
server-side regardless of what any schema advertised, exactly as they do
for the API backend -- see data/spectra-console-subscription-backend/
report.md for the live re-proof (out-of-range, unknown-key, and
malformed-type all rejected through this exact path, with a JSON tool
schema that deliberately omitted the enum, to prove the mechanism -- not
client-side schema policing -- is what refuses)."""
from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer

from spectra.services import settings_agent, settings_console

_KeyEnum = Literal[tuple(sorted(settings_console.SETTINGS_REGISTRY))]

mcp = MCPServer("settings-console")


@mcp.tool()
async def get_settings() -> dict:
    """Read every settings-console setting's current value, type, unit, and legal range/choices."""
    return await settings_agent._dispatch("get_settings", {})


@mcp.tool()
async def set_setting(key: _KeyEnum, value: Any) -> dict:
    """Change ONE declared setting. The server validates the key and value
    against its declared range/choices server-side and rejects anything
    outside them -- this is the only way this agent can change anything."""
    return await settings_agent._dispatch("set_setting", {"key": key, "value": value})


if __name__ == "__main__":
    mcp.run(transport="stdio")
