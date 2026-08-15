"""The settings-console CHAT LOOP, "cli" (subscription) backend --
standing order 5 plus the captain's ruling on data/spectra-console-
subscription-backend/report.md: he wants his own Claude subscription
usage, not API credits, and refused provisioning an ANTHROPIC_API_KEY as
the answer. This module is the alternative run_turn() spectra/api/
settings_console.py dispatches to when config.settings_agent_backend()
is "cli" (default "api" -- see config.py). It drives the real, official
`claude` CLI as a subprocess in non-interactive mode (`-p`), authenticated
by a CLAUDE_CODE_OAUTH_TOKEN minted with `claude setup-token` -- Anthropic's
own documented mechanism for running Claude Code headlessly against a
Pro/Max/Team/Enterprise subscription instead of API billing
(code.claude.com/docs/en/authentication, code.claude.com/docs/en/
github-actions: "If you authenticate with an OAuth token, runs use your
Claude subscription instead of API billing").

THE HARD LINE, BY THE CAPTAIN'S EXPLICIT ORDER: this module must never
turn itself on against his real account. Two independent gates enforce
that, both required, neither a config file this repo's own agent-facing
writes could flip:
  1. config.settings_agent_backend() defaults to "api" -- selecting "cli"
     needs an env var change outside this codebase's own write surface.
  2. Even with "cli" selected, _client_available() below refuses (raises
     SettingsAgentUnavailable, same 503 the API backend gives for a
     missing key) unless CLAUDE_CODE_OAUTH_TOKEN is actually present.
Nothing in this file, or anywhere else in this repo, ever runs
`claude setup-token` or reads an existing interactive `/login` session on
its own -- minting a token is a deliberate, human, browser-based act (the
CLI opens a real browser tab for it), so this code structurally cannot
mint one for itself, and _subprocess_env() below goes one step further:
it does not inherit the parent process's ambient credentials at all. It
points CLAUDE_CONFIG_DIR at a directory under this module's OWN dedicated
workdir (see below) and sets CLAUDE_CODE_OAUTH_TOKEN explicitly, so even
if this machine also has a real interactive `~/.claude/.credentials.json`
sitting around (it does, on the machine this was built and re-proved on),
the subprocess cannot silently authenticate against it -- only the
explicitly-configured token, if any, is ever used. It also strips
ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN from the child's environment,
because Claude Code's own auth precedence puts an API key ahead of the
OAuth token -- if this process happens to also carry the "api" backend's
key, that must never silently hijack the "cli" backend away from
subscription billing.

THE WIDENED SURFACE IS STRUCTURAL, NOT A README FOOTNOTE. `--bare` mode
is documented as "the recommended mode for scripted and SDK calls" but
explicitly cannot be used here -- "bare mode never reads OAuth credentials
or the system keychain" (code.claude.com/docs/en/headless). Plain,
non-bare `-p` mode is therefore forced, and non-bare mode auto-runs a
project's .claude/settings.json hooks and auto-connects its .mcp.json
servers with NO trust-dialog to catch a mistake (there is no human in a
service to answer one). Five things below are what actually hold that
line, every one of them enforced by the code that launches the
subprocess on every call, not left as discipline for whoever deploys
this:
  1. _workdir() is a dedicated, code-owned, code-verified-EMPTY directory
     -- refuses to run at all if it ever contains a stray .claude/,
     .mcp.json, or CLAUDE.md, instead of trusting that nothing will show
     up there.
  2. --tools "" strips the ENTIRE built-in tool set (Bash/Read/Write/
     Edit/Glob/Grep/...) out of the manifest the model is even given --
     proven live: data/spectra-console-subscription-backend/report.md's
     Finding 6 shows the system/init event's own `tools` field held
     exactly the two MCP tool names below and nothing else, even under an
     explicit prompt-injection escape attempt.
  3. --strict-mcp-config + a single inline --mcp-config (built in code by
     _mcp_config_json(), never a file on disk a deploy step could edit
     out of sync with this module) names exactly ONE MCP server:
     settings_mcp_server.py, which itself only wraps settings_agent.
     _dispatch() -- the same exhaustive two-branch mapping the API
     backend uses.
  4. --allowedTools names exactly those two qualified tool names, so even
     an unapproved call to a tool that DID somehow exist would be denied,
     not silently allowed by a permissive default.
  5. _verify_tool_manifest() below re-checks, on every single call, that
     the live system/init event's `tools` field is byte-identical to
     what's expected -- if a hook, a stray MCP server, or a future CLI
     default ever widens that manifest without this file being updated
     to match, the WHOLE turn is refused (SettingsAgentUnavailable)
     before any tool_result is trusted, rather than quietly trusting a
     transcript that turned out wider than intended.

WHY THE MODEL'S OWN PROSE IS NEVER TRUSTED AS EVIDENCE: the live re-proof
(report.md Finding 7) caught claude-haiku-4-5 fabricating tool-call
output TWICE in a handful of calls -- once inventing a full JSON blob
claiming bash/read/write/edit/hooks existed when the real tool manifest
was empty, and once claiming Read/Write/Edit/"System Tools (implicit)"
existed alongside the two real settings tools, when neither was ever in
system/init's own `tools` field. _parse_transcript() below reads ONLY
structured `tool_use`/`tool_result` content blocks and the system/init
event's own `tools` list -- never the model's narrated text -- to decide
what actually happened. The `reply` text returned to the console UI is
purely conversational; `changes` is built exclusively from structured
tool_result payloads whose `status` field the real, unmodified
settings_console.apply_change() wrote.

Every `-p` invocation is a fresh subprocess (no persistent server); a
conversation is continued with `--resume <session_id>`, using the
session id `claude` itself returns -- there is no separate session
mapping to keep, unlike the API backend's in-memory message-history
list.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from spectra import config
from spectra.services.settings_agent import SYSTEM_PROMPT, TOOLS, SettingsAgentUnavailable

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "settings-console"
TOOL_NAMES = tuple(sorted(f"mcp__{MCP_SERVER_NAME}__{t['name']}" for t in TOOLS))
CLI_TIMEOUT_S = 90


def _client_available() -> str:
    """Returns the token, or raises SettingsAgentUnavailable -- the SAME
    fail-before-any-state-changes posture settings_agent._client() uses
    for a missing ANTHROPIC_API_KEY. Called before anything else in
    run_turn() so an unconfigured backend can never even reach the
    subprocess-launch code below."""
    token = config.settings_agent_cli_oauth_token()
    if not token:
        raise SettingsAgentUnavailable(
            "settings-agent backend is \"cli\" but no CLAUDE_CODE_OAUTH_TOKEN is "
            "configured -- the settings console has no model to talk to yet. "
            "This is intentional: nothing in this codebase mints or reads a "
            "token on its own (see settings_agent_cli.py's module docstring).")
    return token


def _workdir() -> Path:
    """The dedicated, empty, code-owned directory the `claude` subprocess
    itself runs from. Created if missing; REFUSES to proceed if it ever
    contains a stray .claude/, .mcp.json, or CLAUDE.md -- see module
    docstring point 1. This check runs on every call, not once at
    startup, so a file dropped in later (by hand, by a future script, by
    anything) is caught before the next turn rather than trusted forever
    from a stale one-time check."""
    path = config.settings_agent_cli_workdir()
    path.mkdir(parents=True, exist_ok=True)
    stray = sorted(p.name for p in path.iterdir()
                   if p.name in (".claude", ".mcp.json", "CLAUDE.md"))
    if stray:
        raise SettingsAgentUnavailable(
            f"settings-agent CLI workdir {path} is not clean (found {stray}) -- "
            "refusing to run a non-bare `claude -p` session against it, since "
            "non-bare mode auto-runs hooks/auto-connects MCP servers it finds "
            "in its working directory with no trust prompt")
    return path


def _mcp_config_json() -> str:
    """One inline JSON string naming exactly one MCP server -- built in
    code, every call, from this module's own constants, never read from a
    file a deploy step could let drift out of sync. --strict-mcp-config
    (passed alongside this in _argv()) refuses every OTHER MCP source, so
    this is the only one that can ever be live."""
    return json.dumps({
        "mcpServers": {
            MCP_SERVER_NAME: {
                # sys.executable, not a bare "python" -- must resolve to
                # THIS process's own venv regardless of PATH at spawn time
                # (systemd units don't inherit an interactive shell's PATH).
                "command": sys.executable,
                "args": ["-m", "spectra.services.settings_mcp_server"],
                "cwd": str(config.REPO_ROOT),
            },
        },
    })


def _argv(prompt: str, resume_session_id: Optional[str]) -> list[str]:
    argv = [
        config.settings_agent_cli_binary(),
        "-p", prompt,
        "--model", config.settings_agent_model(),
        "--system-prompt", SYSTEM_PROMPT,
        "--mcp-config", _mcp_config_json(),
        "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", ",".join(TOOL_NAMES),
        "--output-format", "json",
        "--verbose",
    ]
    if resume_session_id:
        argv += ["--resume", resume_session_id]
    return argv


def _subprocess_env(token: str, workdir: Path) -> dict:
    """See module docstring's "THE HARD LINE" section -- explicit token,
    isolated CLAUDE_CONFIG_DIR, and no API-key credential that could
    silently outrank the subscription token."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    env["CLAUDE_CONFIG_DIR"] = str(workdir / ".claude-config")
    return env


def _verify_tool_manifest(events: list[dict]) -> None:
    """Module docstring point 5 -- re-checked on every call, not assumed
    from the launch flags alone. Raises SettingsAgentUnavailable (never
    silently trusts a wider transcript) if the live tool manifest, MCP
    server set, or permission mode isn't exactly what was configured."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if init is None:
        raise SettingsAgentUnavailable("settings-agent CLI produced no system/init event -- refusing to trust this turn")
    if tuple(sorted(init.get("tools") or ())) != TOOL_NAMES:
        raise SettingsAgentUnavailable(
            f"settings-agent CLI tool manifest was {init.get('tools')!r}, "
            f"expected exactly {list(TOOL_NAMES)} -- refusing to trust this turn")
    servers = {s.get("name"): s.get("status") for s in (init.get("mcp_servers") or [])}
    if servers != {MCP_SERVER_NAME: "connected"}:
        raise SettingsAgentUnavailable(
            f"settings-agent CLI mcp_servers was {servers!r}, expected only "
            f"{MCP_SERVER_NAME!r} connected -- refusing to trust this turn")


def _parse_transcript(events: list[dict]) -> dict:
    """Structured-only parse -- see module docstring's "WHY THE MODEL'S
    OWN PROSE IS NEVER TRUSTED" section. `changes` comes exclusively from
    tool_result payloads for the set_setting tool_use blocks; `reply` is
    the terminal result event's own text, shown to the user as
    conversation, never consulted to decide what changed."""
    _verify_tool_manifest(events)

    tool_use_names: dict[str, str] = {}
    applied: list[dict] = []
    for event in events:
        message = event.get("message") if event.get("type") in ("assistant", "user") else None
        content = (message or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_use_names[block.get("id")] = block.get("name", "")
            elif block.get("type") == "tool_result":
                name = tool_use_names.get(block.get("tool_use_id"), "")
                if not name.endswith("__set_setting"):
                    continue
                raw = block.get("content")
                text = raw[0]["text"] if isinstance(raw, list) and raw and isinstance(raw[0], dict) else raw
                try:
                    result = json.loads(text) if isinstance(text, str) else text
                except (TypeError, ValueError):
                    continue
                if isinstance(result, dict) and result.get("status") == "applied":
                    applied.append(result)

    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    if final.get("is_error"):
        raise SettingsAgentUnavailable(str(final.get("result") or "settings-agent CLI call failed"))

    return {
        "session_id": final.get("session_id"),
        "reply": final.get("result", ""),
        "changes": applied,
    }


async def run_turn(session_id: Optional[str], text: str) -> dict:
    """One user message in, through the real `claude -p` subprocess, out
    with the same {session_id, reply, changes} shape run_turn() returns
    in settings_agent.py -- spectra/api/settings_console.py doesn't need
    to know which backend answered."""
    token = _client_available()
    workdir = _workdir()
    argv = _argv(text, session_id)
    env = _subprocess_env(token, workdir)

    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(workdir), env=env,
        # stdin=DEVNULL is not cosmetic: without it, `claude -p` waits ~3s
        # for stdin data before proceeding ("no stdin data received in
        # 3s..." on stderr) -- caught live while building this module's
        # test fixtures. Every call would otherwise pay that tax.
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=CLI_TIMEOUT_S)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise SettingsAgentUnavailable("settings-agent CLI call timed out")

    if process.returncode not in (0, 1):
        # 1 is claude -p's own "run failed" exit code, still followed by a
        # parseable JSON result on stdout (e.g. not-logged-in, quota
        # exhausted); anything else means it never got that far.
        raise SettingsAgentUnavailable(
            f"settings-agent CLI exited {process.returncode}: {stderr.decode('utf-8', 'replace')[:500]}")

    try:
        events = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SettingsAgentUnavailable(f"settings-agent CLI produced unparseable output: {exc}") from exc
    if not isinstance(events, list):
        events = [events]

    return _parse_transcript(events)
