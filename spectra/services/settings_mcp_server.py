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

CWD-INDEPENDENT ON PURPOSE (live production defect, 2026-08-15, found by
firstmate: `claude -p` runs with its cwd set to settings_agent_cli.py's
dedicated clean workdir -- see that module's docstring for why that
directory must stay empty -- and does NOT honour the per-server `cwd`
this module's --mcp-config entry used to declare; the subprocess it spawns
inherits the PARENT `claude` process's cwd instead. `python -m` resolves
imports off the CURRENT WORKING DIRECTORY, not this file's own location,
so `import spectra` silently failed with the server launched from that
clean workdir -- reproduced by hand: `python -m
spectra.services.settings_mcp_server` succeeds from the repo root and
raises `ModuleNotFoundError: No module named 'spectra'` from the clean
workdir. The fix is entirely LOCAL to this file -- the two lines below
insert this file's own resolved repo root into sys.path before importing
spectra, so the module works regardless of the spawning process's cwd,
regardless of whether any --mcp-config field the CLI does or doesn't
honour changes in a future version, and regardless of `-m` vs. a direct
script path. This does NOT touch, weaken, or route around the clean
workdir requirement itself: that directory governs the `claude` PROCESS's
OWN cwd, used only for ITS auto-discovery of a project's
`.claude/settings.json` hooks and `.mcp.json`/`CLAUDE.md` (the actual
hole `_workdir()` guards) -- a completely different mechanism from this
file's own sys.path, which affects nothing outside this one Python
process's own import resolution.

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

import sys
from pathlib import Path
from typing import Any, Literal

# Must run before the `spectra.services` import below -- see module
# docstring's "CWD-INDEPENDENT ON PURPOSE" section. This file lives at
# <repo_root>/spectra/services/settings_mcp_server.py, so its own resolved
# path (never the process's cwd) is what locates the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server import MCPServer  # noqa: E402

from spectra.services import settings_agent, settings_console  # noqa: E402

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
