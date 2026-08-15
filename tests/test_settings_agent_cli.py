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
     --allowedTools naming exactly settings_agent.TOOL_NAMES (originally
     the two settings tools; widened 2026-08-15 to Sonic's full cross-
     domain operation set, see settings_agent.py / scene_console.py).
  4. The subprocess environment strips ANTHROPIC_API_KEY/AUTH_TOKEN and
     points CLAUDE_CONFIG_DIR at an isolated directory -- an ambient
     interactive `/login` session on the host can never be silently used
     instead of the explicitly-configured token.
  5. _parse_transcript() reads ONLY structured tool_use/tool_result
     blocks and the system/init event's own `tools` field -- never the
     model's prose. Section 5 below proves this against four REAL,
     live-captured transcripts (tests/fixtures/cli_transcript_*.json,
     captured while building this module and re-proving spectra-console-
     subscription-backend's report, signatures elided) — pinned to the
     ORIGINAL two-tool surface, they now correctly REFUSE outright as a
     stale manifest once the tool surface widened (the regression proof
     for the widening itself). Section 5b re-proves the same four
     properties (applied / rejected / hallucinated-with-a-correct-
     manifest / unavailable-tool-fabrication) against the CURRENT, wider
     surface using hand-built `cli_transcript_synthetic_*.json` fixtures,
     explicitly labelled synthetic — no live CLAUDE_CODE_OAUTH_TOKEN
     exists in this sandbox to capture new real ones tonight.
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

    from spectra.services import settings_agent as sa

    tools = _run(_list_tools())
    assert {t.name for t in tools.tools} == set(sa.ALL_OPERATIONS), \
        ("this MCP server must expose exactly one hand-written wrapper per "
         "settings_agent.ALL_OPERATIONS entry -- see settings_mcp_server.py's "
         "module docstring for why that's hand-maintained instead of generated")


# ═══ 5. transcript parsing: structured data only, never the model's prose.
#
# The Admiral's scene/flare widening (2026-08-15) grew settings_agent.
# ALL_OPERATIONS (and therefore TOOL_NAMES) from {get_settings, set_setting}
# to eleven names. The four `cli_transcript_*.json` fixtures below (NOT the
# `_synthetic_` ones further down) are REAL, historical captures pinned to
# the tool surface as it existed when this module was FIRST built -- their
# `system/init.tools` field is exactly the old two-name set, unchanged
# because it's historical evidence, not something to edit to keep old
# fixtures passing. Re-running them against the CURRENT, wider TOOL_NAMES
# therefore now correctly REFUSES every one of them (a stale/narrower-than-
# expected manifest, the exact failure mode #5 in the module docstring
# exists to catch) -- this is the widening's own regression proof: the
# manifest check did not get loosened to keep old fixtures superficially
# green. Behavioral coverage for the CURRENT surface (a real applied
# change, a real rejection, a correct manifest with hallucinated prose, an
# unavailable-tool fabrication) is re-proven below in section 5b against
# hand-built `_synthetic_` fixtures, since no live CLAUDE_CODE_OAUTH_TOKEN
# exists tonight to capture new real ones (his room is asleep) -- those
# fixtures are explicitly labelled synthetic, never claimed as live
# captures. ════════════════════════════════════════════════════════════

def test_old_real_captures_are_now_correctly_refused_as_a_stale_manifest():
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    for fixture in ("cli_transcript_applied.json", "cli_transcript_rejected.json",
                    "cli_transcript_hallucinated_capabilities_claim.json"):
        with pytest.raises(SettingsAgentUnavailable, match="tool manifest"):
            sac._parse_transcript(_load(fixture))


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


# ═══ 5b. behavioral re-proof against the WIDENED scene/flare surface, with
# SYNTHETIC (hand-built, clearly labelled) fixtures -- see the section-5
# header comment for why these are synthetic rather than live captures. ══

def test_parse_transcript_extracts_a_real_applied_scene_change():
    """Proves _parse_transcript's structured-only extraction generalizes
    to a SCENE operation, not just set_setting -- `changes` comes from the
    tool_result's own `status` field regardless of which operation name
    produced it (see _parse_transcript's own docstring: a property of the
    result SHAPE, not a hardcoded tool-name suffix check anymore)."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_synthetic_scene_applied.json"))
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["status"] == "applied"
    assert change["op"] == "set_scene_setting"
    assert change["scene_id"] == "scene-fixture-0001"
    assert change["new_value"] == 1500
    assert result["reply"]


def test_parse_transcript_a_rejected_scene_change_applies_nothing():
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_synthetic_scene_rejected.json"))
    assert result["changes"] == [], \
        "a rejected set_scene_setting tool_result must never be counted as applied"
    assert "0-20000" in result["reply"] or "legal" in result["reply"].lower()


def test_parse_transcript_ignores_hallucinated_scene_capability_claims():
    """The tool manifest is genuinely correct (all eleven current tools,
    MCP server connected) and no tool was ever called, yet the model's
    own final reply text claims a scene and a flare kind were created.
    This must not be mistaken for anything having been applied --
    `changes` is built only from real tool_result blocks, of which there
    are none in this transcript."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_scene_correct_manifest_hallucinated_prose.json"))
    assert result["changes"] == []
    assert "Sunset Drift" in result["reply"], \
        "the hallucination is real and present in the reply text -- " \
        "the point is that `changes` doesn't believe it"


def test_parse_transcript_refuses_the_unavailable_tool_fabrication_case_for_scenes():
    """THE failure this task was told to hunt explicitly: a tool
    unavailable (mcp_servers status "failed", tools: []) and the model
    fabricating a confident, specific claim in plain prose -- "I created a
    new scene called 'Sunset Drift' and added a 'Boom' flare kind" -- with
    NO real tool_use/tool_result anywhere in the transcript, the same
    shape report.md Finding 7 caught on the original two-tool surface. The
    manifest check must refuse the WHOLE turn before _parse_transcript
    ever gets to trusting -- or having to specifically distrust -- that
    fabricated text; scene creation makes an undiscovered fabrication far
    more dangerous than a settings tweak (he wouldn't find out until a
    show), so this must fail exactly as loudly as the settings-only case
    did."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    with pytest.raises(SettingsAgentUnavailable, match="tool manifest"):
        sac._parse_transcript(_load("cli_transcript_synthetic_scene_unavailable_tool_fabrication.json"))


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
