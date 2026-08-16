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


def test_settings_mcp_server_actually_invokes_every_tool_without_a_python_level_argument_error(tmp_path):
    """THE regression test for a SECOND live production defect
    (2026-08-15, found running the adversarial set against the REAL model
    on the deployed CLI backend, his real subscription live): six tools
    whose own parameter is ALSO called `name` (create_scene,
    get_flare_kind, set_flare_kind, remove_flare_kind, overwrite_scene,
    list_operations) each called `_call("op", name=name, ...)` --
    `_call`'s own first parameter used to be a plain `name: str`, so that
    keyword collided with it: `_call() got multiple values for argument
    'name'`, a TypeError, on EVERY call to any of those six tools. The
    real Sonnet model, given the genuinely broken tool, reported the
    failure honestly instead of fabricating success -- but the defect
    itself had NO offline coverage: test_settings_mcp_server_starts_
    from_a_clean_cwd above only ever calls session.list_tools() (listing
    schemas), never session.call_tool() (actually invoking a wrapped
    function with real arguments), so a Python-level argument-binding
    crash inside any wrapper was invisible to every existing test. This
    one actually CALLS all six previously-broken tools (plus a seventh,
    unaffected one, as a control) through the real MCP subprocess and
    asserts none of them fail with a Python argument-binding error --
    `_call`'s fix (positional-only `op_name`, see its own docstring)
    makes this pass; reverting that fix reproduces the exact live
    failure here, offline."""
    import mcp as mcp_pkg

    from spectra.services import settings_agent_cli as sac

    storage_dir = tmp_path / "storage"
    workdir = tmp_path / "workdir"
    storage_dir.mkdir()
    workdir.mkdir()

    parsed = json.loads(sac._mcp_config_json())
    server = parsed["mcpServers"][sac.MCP_SERVER_NAME]
    env = dict(os.environ)
    env["SPECTRA_STORAGE_DIR"] = str(storage_dir)

    async def _exercise():
        params = mcp_pkg.StdioServerParameters(
            command=server["command"], args=server["args"], cwd=str(workdir), env=env)
        async with mcp_pkg.stdio_client(params) as (read, write):
            async with mcp_pkg.ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=15)

                async def call(tool_name, arguments):
                    result = await session.call_tool(tool_name, arguments)
                    text = result.content[0].text
                    assert "multiple values for argument" not in text, \
                        f"{tool_name}({arguments}) hit the name-collision defect: {text}"
                    return json.loads(text)

                # The previously-broken six, exercised for real, in the
                # order a real conversation would naturally use them.
                detail = await call("list_operations", {"name": "create_scene"})
                assert detail["operation"]["name"] == "create_scene"

                created = await call("create_scene", {"name": "MCP Regression Scene", "labels": []})
                assert created["status"] == "applied"
                scene_id = created["scene_id"]

                kind = await call("set_flare_kind", {
                    "scene_id": scene_id, "name": "TestKind", "type": "permanent",
                    "params": {"gain": 1.0}, "gain": 1.5})
                assert kind["status"] == "applied"

                fetched = await call("get_flare_kind", {"scene_id": scene_id, "name": "TestKind"})
                assert fetched["flare_kind"]["name"] == "TestKind"

                overwritten = await call("overwrite_scene", {
                    "scene_id": scene_id, "name": "MCP Regression Scene (renamed)"})
                assert overwritten["status"] == "applied"

                removed = await call("remove_flare_kind", {"scene_id": scene_id, "name": "TestKind"})
                assert removed["status"] == "applied"

                # Control: an unaffected tool (no "name" kwarg) must still work.
                settings = await call("get_scene_settings", {"scene_id": scene_id})
                assert settings["scene_id"] == scene_id

    _run(_exercise())


# ═══ 5. transcript parsing: structured data only, never the model's prose.
#
# TWO widenings have grown settings_agent.ALL_OPERATIONS (and therefore
# TOOL_NAMES) since this module was first built: 2026-08-15's scene/flare
# authority ({get_settings, set_setting} -> 11 names) and, the same night,
# his follow-up overwrite/backup/undo/preview/restore ask (11 -> 16 names).
# Every `cli_transcript_*.json` fixture NOT prefixed `_synthetic_` is a
# REAL, historical capture pinned to whichever tool surface existed at
# capture time — never edited to keep passing, because that would falsify
# the evidence. Re-run against the CURRENT, wider TOOL_NAMES, every one of
# them now correctly REFUSES as a stale/narrower-than-expected manifest
# (failure mode #5 in the module docstring) — the standing regression
# proof that neither widening loosened the check to keep old fixtures
# superficially green. Behavioral coverage for the CURRENT (16-tool)
# surface is re-proven in section 5b (scene/flare, from the first
# widening — still exercised, since those operations are still live) and
# 5c (overwrite/backup/undo/preview/restore, from tonight's widening)
# against hand-built `_synthetic_` fixtures, since no live
# CLAUDE_CODE_OAUTH_TOKEN exists tonight to capture new real ones (his
# room is asleep) — those fixtures are explicitly labelled synthetic,
# never claimed as live captures. ════════════════════════════════════════

def test_old_real_captures_are_now_correctly_refused_as_a_stale_manifest():
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    for fixture in ("cli_transcript_applied.json", "cli_transcript_rejected.json",
                    "cli_transcript_hallucinated_capabilities_claim.json"):
        with pytest.raises(SettingsAgentUnavailable, match="tool manifest"):
            sac._parse_transcript(_load(fixture))


def test_first_widenings_synthetic_scene_fixtures_are_now_ALSO_correctly_refused():
    """The three `cli_transcript_synthetic_scene_*` fixtures built for the
    FIRST widening (11-tool surface) are themselves now stale against the
    16-tool surface tonight's overwrite/backup ask added — proving the
    check keeps catching drift even against fixtures that were themselves
    synthetic-but-current a few hours ago, not just against the original
    real captures. (The unavailable-tool fixture from that same widening
    is unaffected — an empty manifest mismatches any non-empty expected
    set regardless of how large it grows — see test_parse_transcript_
    refuses_the_unavailable_tool_fabrication_case_for_scenes below.)"""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    for fixture in ("cli_transcript_synthetic_scene_applied.json",
                    "cli_transcript_synthetic_scene_rejected.json",
                    "cli_transcript_synthetic_scene_correct_manifest_hallucinated_prose.json"):
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


# ═══ 5b. the unavailable-tool fabrication case from the FIRST widening —
# still valid unchanged: an empty manifest ([]) mismatches any non-empty
# expected TOOL_NAMES regardless of how large it later grows. ═══════════

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


# ═══ 5c. behavioral re-proof against TONIGHT'S widening — overwrite_scene/
# restore_scene_backup/undo_last_scene_change/backup verification — the
# deploy hold's own explicit ask: "a fabricated 'I restored that for you'
# must be caught against stored data." SYNTHETIC (hand-built, clearly
# labelled) fixtures at the CURRENT 16-tool manifest. ════════════════════

def test_parse_transcript_extracts_a_real_applied_overwrite():
    """Proves the structured-only extraction generalizes to
    overwrite_scene specifically — his first genuinely destructive scene
    operation — same property as every other operation: `changes` comes
    from the tool_result's own `status` field, never the reply text."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_synthetic_overwrite_applied.json"))
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["status"] == "applied"
    assert change["op"] == "overwrite_scene"
    assert change["scene_id"] == "scene-fixture-0002"
    assert change["backup_id"] == "backup-0001", \
        "the applied result must carry the backup id the edit was verified against"
    assert result["reply"]


def test_parse_transcript_an_overwrite_refused_for_a_failed_backup_applies_nothing():
    """The exact adversarial case named by the deploy hold: 'an overwrite
    attempted while the backup mechanism FAILS must REFUSE' -- proven here
    at the transcript-parsing layer (the real tool_result the mechanism
    itself would produce), complementing test_scene_console.py's proof at
    the mechanism layer directly."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_overwrite_backup_failed_rejected.json"))
    assert result["changes"] == [], \
        "a backup-verification rejection must never be counted as applied"
    assert "back up" in result["reply"].lower() or "backup" in result["reply"].lower()


def test_parse_transcript_catches_a_fabricated_restore_claim():
    """THE deploy hold's other named case, quoted verbatim: 'a fabricated
    "I restored that for you" must be caught against stored data.' Here
    the tool manifest is genuinely correct (all 16 current tools, MCP
    server connected) and no tool was EVER called, yet the model's final
    reply claims a restore happened. `changes` must stay empty --
    verifying "the restore really happened" against stored scene data is
    exactly what test_scene_console.py's own restore/undo tests do at the
    mechanism layer; this proves the CLI transcript layer can't be talked
    into believing a restore that never ran."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_synthetic_restore_hallucinated_prose.json"))
    assert result["changes"] == []
    assert "restored" in result["reply"].lower(), \
        "the fabrication is real and present in the reply text -- " \
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
