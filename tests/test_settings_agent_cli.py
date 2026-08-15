"""The "cli" (subscription) settings-agent backend
(spectra/services/settings_agent_cli.py) -- offline proof that the hard
line holds structurally, no live `claude` call required for the bulk of
this file:

  1. The backend defaults to "api" (config.settings_agent_backend()) and
     the "cli" backend refuses to even build a subprocess argv without an
     explicit CLAUDE_CODE_OAUTH_TOKEN -- the same fail-before-any-state-
     changes posture settings_agent._client() uses for a missing
     ANTHROPIC_API_KEY.
  2. The dedicated working directory is created and verified clean on
     every call -- a stray .claude/, .mcp.json, or CLAUDE.md refuses the
     call rather than risking a non-bare `claude -p` session auto-running
     it.
  3. The subprocess argv never carries --bare (it can't read the OAuth
     token) and always carries --strict-mcp-config / --tools "" /
     --allowedTools naming exactly the two settings tools.
  4. The subprocess environment strips ANTHROPIC_API_KEY/AUTH_TOKEN and
     points CLAUDE_CONFIG_DIR at an isolated directory -- an ambient
     interactive `/login` session on the host can never be silently used
     instead of the explicitly-configured token.
  5. _parse_transcript() reads ONLY structured tool_use/tool_result
     blocks and the system/init event's own `tools` field -- never the
     model's prose -- against four REAL, live-captured transcripts
     (tests/fixtures/cli_transcript_*.json, captured while building this
     module and re-proving spectra-console-subscription-backend's report,
     signatures elided) covering: a valid change applying, an out-of-
     range value being rejected, a live tool-manifest mismatch (the MCP
     server failed to load) being refused before anything is trusted, and
     the model fabricating tool-call output in plain prose while the real
     manifest held only the two real tools -- proving `changes` is never
     built from anything but a genuine tool_result payload.
  6. test_settings_mcp_server_starts_from_a_clean_cwd spawns the EXACT
     command _mcp_config_json() builds, for real, with its cwd pointed at
     an empty tmp_path standing in for the dedicated clean workdir, and
     talks real MCP protocol to it (no `claude` binary, no token, no
     network) -- the regression proof for a real live production defect
     (2026-08-15, found by firstmate): `claude -p` runs the MCP server
     with ITS OWN cwd (the clean workdir), not a per-server `cwd` field
     this repo used to declare and which turned out not to be honoured,
     and `-m spectra.services.settings_mcp_server` needs `spectra`
     resolvable via the CURRENT WORKING DIRECTORY before any of that
     module's own code runs -- so the server silently failed to start
     from that specific cwd, and no unit test caught it because none of
     them launched a real subprocess from a real clean directory. The
     five points above are all still true after the fix -- the clean
     workdir itself is untouched; only the MCP server's own import
     resolution changed (settings_mcp_server.py's own docstring has the
     full mechanism).

One test (test_live_cli_can_apply_a_change) additionally proves the real
subprocess loop end to end -- SKIPPED here (no CLAUDE_CODE_OAUTH_TOKEN in
this sandbox, and none is ever minted by this suite); it would run this
exact assertion against a real `claude -p` call when a token is present.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _run(coro):
    return asyncio.run(coro)


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg

    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.delenv("SPECTRA_SETTINGS_AGENT_BACKEND", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


# ═══ 1. the backend switch itself defaults to "api" ═══════════════════

def test_backend_defaults_to_api():
    from spectra import config as scfg

    assert scfg.settings_agent_backend() == "api"


def test_backend_selects_cli_only_with_explicit_env(monkeypatch):
    from spectra import config as scfg

    monkeypatch.setenv("SPECTRA_SETTINGS_AGENT_BACKEND", "cli")
    assert scfg.settings_agent_backend() == "cli"


# ═══ 2. unavailable without an explicit token -- before anything else ═

def test_run_turn_refuses_without_token_before_any_subprocess(monkeypatch):
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    def _boom(*a, **k):
        raise AssertionError("must not spawn a subprocess without a token")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)

    with pytest.raises(SettingsAgentUnavailable, match="CLAUDE_CODE_OAUTH_TOKEN"):
        _run(sac.run_turn(None, "set brightness to half"))


# ═══ 3. the dedicated working directory is created and verified clean ═

def test_workdir_created_when_missing():
    from spectra.services import settings_agent_cli as sac
    from spectra import config as scfg

    workdir = sac._workdir()
    assert workdir.is_dir()
    assert workdir == scfg.settings_agent_cli_workdir()


def test_workdir_refuses_when_a_stray_mcp_config_is_present():
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    workdir = sac.config.settings_agent_cli_workdir()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / ".mcp.json").write_text("{}")

    with pytest.raises(SettingsAgentUnavailable, match=r"\.mcp\.json"):
        sac._workdir()


def test_workdir_refuses_when_a_stray_claude_dir_is_present():
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    workdir = sac.config.settings_agent_cli_workdir()
    (workdir / ".claude").mkdir(parents=True, exist_ok=True)

    with pytest.raises(SettingsAgentUnavailable, match=r"\.claude"):
        sac._workdir()


# ═══ 4. the subprocess is built to the hard line, not left to discipline ═

def test_mcp_config_names_exactly_one_server():
    from spectra import config as scfg
    from spectra.services import settings_agent_cli as sac

    parsed = json.loads(sac._mcp_config_json())
    assert set(parsed["mcpServers"]) == {sac.MCP_SERVER_NAME}
    server = parsed["mcpServers"][sac.MCP_SERVER_NAME]
    assert server["command"] == sys.executable
    # An ABSOLUTE SCRIPT PATH, not `-m spectra.services.settings_mcp_server`
    # -- see _mcp_config_json()'s docstring for the live production defect
    # this fixes: `-m` needs `spectra` resolvable via the CURRENT WORKING
    # DIRECTORY before the module's own code ever runs, and `claude -p`
    # spawns this server with the dedicated clean workdir as that cwd, not
    # the repo. test_settings_mcp_server_starts_from_a_clean_cwd below is
    # the real, live proof this config actually works from that directory.
    assert "cwd" not in server, "a per-server cwd override is NOT honoured by claude -p -- don't rely on it"
    assert server["args"] == [str(scfg.REPO_ROOT / "spectra" / "services" / "settings_mcp_server.py")]


def test_argv_never_carries_bare_and_locks_the_tool_surface():
    from spectra.services import settings_agent_cli as sac

    argv = sac._argv("set brightness to half", None)
    assert "--bare" not in argv, "bare mode can't read CLAUDE_CODE_OAUTH_TOKEN"
    assert argv[argv.index("--strict-mcp-config")] == "--strict-mcp-config"
    assert argv[argv.index("--tools") + 1] == "", "every built-in tool is stripped"
    assert argv[argv.index("--allowedTools") + 1] == ",".join(sac.TOOL_NAMES)
    assert "--resume" not in argv, "a fresh conversation never resumes"


def test_argv_resumes_an_existing_session():
    from spectra.services import settings_agent_cli as sac

    argv = sac._argv("continue", "some-session-id")
    assert argv[argv.index("--resume") + 1] == "some-session-id"


def test_subprocess_env_strips_api_key_and_isolates_config_dir(monkeypatch, tmp_path):
    from spectra.services import settings_agent_cli as sac

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-reach-the-child")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "also-should-never-reach-the-child")

    workdir = tmp_path / "workdir"
    env = sac._subprocess_env("a-real-token", workdir)

    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "a-real-token"
    assert env["CLAUDE_CONFIG_DIR"] == str(workdir / ".claude-config")


def test_settings_mcp_server_starts_from_a_clean_cwd(tmp_path):
    """THE regression test for the 2026-08-15 live production defect: this
    spawns the EXACT command _mcp_config_json() builds and speaks real MCP
    protocol to it (mcp.stdio_client/ClientSession, no `claude` binary
    involved) with cwd pointed at an EMPTY tmp_path -- standing in for
    settings_agent_cli._workdir()'s dedicated clean directory, which a
    real `claude -p` session always uses as the MCP server's own cwd (see
    _mcp_config_json()'s docstring). Before the fix, this failed exactly
    the way production did: ModuleNotFoundError inside the subprocess,
    the MCP handshake never completing. tmp_path is pytest's own fresh
    directory -- guaranteed to contain nothing related to spectra, so a
    regression to `-m` or to relying on an unhonoured `cwd` field fails
    this test the same way it failed live."""
    import mcp as mcp_pkg

    from spectra.services import settings_agent_cli as sac

    assert list(tmp_path.iterdir()) == [], "tmp_path must start genuinely empty to prove this"

    parsed = json.loads(sac._mcp_config_json())
    server = parsed["mcpServers"][sac.MCP_SERVER_NAME]

    async def _list_tools():
        params = mcp_pkg.StdioServerParameters(
            command=server["command"], args=server["args"], cwd=str(tmp_path))
        async with mcp_pkg.stdio_client(params) as (read, write):
            async with mcp_pkg.ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)
                return await session.list_tools()

    tools = _run(_list_tools())
    assert {t.name for t in tools.tools} == {"get_settings", "set_setting"}


# ═══ 5. transcript parsing: structured data only, never the model's prose ═

def test_parse_transcript_extracts_a_real_applied_change():
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_applied.json"))
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["status"] == "applied"
    assert change["key"] == "global_transition_ms"
    assert change["new_value"] == 1500
    assert result["reply"]


def test_parse_transcript_a_real_rejection_applies_nothing():
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_rejected.json"))
    assert result["changes"] == [], \
        "a rejected set_setting tool_result must never be counted as applied"


def test_parse_transcript_refuses_a_live_tool_manifest_mismatch():
    """The MCP server failed to load in this real capture (mcp_servers
    status "failed", tools: []); the model then fabricated a fake tool
    call and a fake JSON blob claiming bash/read/write/edit existed
    (data/spectra-console-subscription-backend/report.md Finding 7). The
    structural manifest check must refuse this turn outright, before
    _parse_transcript ever gets to trusting -- or having to specifically
    distrust -- that fabricated text."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    with pytest.raises(SettingsAgentUnavailable, match="tool manifest"):
        sac._parse_transcript(_load("cli_transcript_manifest_mismatch.json"))


def test_parse_transcript_ignores_hallucinated_capability_claims():
    """A different real capture: the tool manifest is genuinely correct
    (exactly the two settings tools, MCP server connected) and no tool
    was ever called, yet the model's own final reply text claims Read,
    Write, Edit, Glob, Grep, and unspecified "System Tools" exist. This
    must not be mistaken for anything having been applied -- `changes`
    is built only from real tool_result blocks, of which there are none
    in this transcript."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_hallucinated_capabilities_claim.json"))
    assert result["changes"] == []
    assert "Read" in result["reply"], \
        "the hallucination is real and present in the reply text -- " \
        "the point is that `changes` doesn't believe it"


# ═══ 6. live smoke test (skipped: no CLAUDE_CODE_OAUTH_TOKEN here, and ═══
# this suite never mints one -- see module docstring) ═══════════════════

@pytest.mark.skipif(not os.getenv("CLAUDE_CODE_OAUTH_TOKEN"),
                    reason="needs a real CLAUDE_CODE_OAUTH_TOKEN -- live CLI smoke test")
def test_live_cli_can_apply_a_change():
    from spectra.services import room_controls as rc
    from spectra.services import settings_agent_cli as sac

    result = _run(sac.run_turn(None, "Set the brightness to 50%."))
    assert result["changes"], "the model should have called set_setting"
    assert rc.load_room_controls().brightness_multiplier == pytest.approx(0.5, abs=0.05)
