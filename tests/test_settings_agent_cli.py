"""The "cli" settings-agent backend (spectra/services/
settings_agent_cli.py) -- offline proof that the hard line holds
structurally, no live `claude` call required for the bulk of this file.

WHO PAYS, AND THE PROOF THAT NOTHING ELSE CAN (the Admiral's 2026-11-17
order): section 2 and section 4 below are the ones that moved. This
backend bills HIS OWN API KEY -- it reads no subscription credential at
all any more, strips CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_AUTH_TOKEN out of
the child environment, and refuses a turn whose own apiKeySource says
anything other than ANTHROPIC_API_KEY (section 8). A missing key is a
stated refusal before any subprocess exists; there is no second
credential left in the codebase to fall back to.

  1. The backend switch (config.settings_agent_backend()) still defaults
     to "api", and the "cli" backend refuses to even build a subprocess
     argv without a configured API key -- the same fail-before-any-state-
     changes posture settings_agent._client() uses.
  2. The dedicated working directory is created and verified clean on
     every call -- a stray .claude/, .mcp.json, or CLAUDE.md refuses the
     call rather than risking a non-bare `claude -p` session auto-running
     it.
  3. The subprocess argv never carries --bare (it can't read the OAuth
     token) and always carries --strict-mcp-config / --tools "" /
     --allowedTools naming exactly settings_agent.TOOL_NAMES (originally
     the two settings tools; widened 2026-08-15 to Sonic's full cross-
     domain operation set, see settings_agent.py / scene_console.py).
  4. The subprocess environment carries his API key and NOTHING else
     that could pay for the call (CLAUDE_CODE_OAUTH_TOKEN and
     ANTHROPIC_AUTH_TOKEN are popped), with CLAUDE_CONFIG_DIR pointed at
     an isolated directory -- an ambient interactive `/login` session on
     the host can never be silently used instead.
  4b. EVERY fixture here was captured or hand-built while this backend
     ran on the subscription, and the real captures record what that
     looked like: `apiKeySource: "none"`. The 13 explicitly-synthetic
     fixtures whose tests assert a SUCCESSFUL parse were updated to
     `"ANTHROPIC_API_KEY"` on 2026-11-17, the same way earlier widenings
     updated their recorded tool manifests — a synthetic fixture has to
     model what a real call looks like NOW, or it stops proving anything.
     The four REAL captures are untouched, as always: editing a capture
     would falsify the evidence, and they already refuse on the older
     stale-manifest diagnosis anyway (section 5).

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
subprocess loop end to end -- SKIPPED unless SPECTRA_LIVE_CLAUDE=1 is
exported, because it spends real money on his API key and (unlike every
other test here) drives the real stored room controls.
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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ═══ 1. the backend switch itself defaults to "api" ═══════════════════

def test_backend_defaults_to_api():
    from spectra import config as scfg

    assert scfg.settings_agent_backend() == "api"


def test_backend_selects_cli_only_with_explicit_env(monkeypatch):
    from spectra import config as scfg

    monkeypatch.setenv("SPECTRA_SETTINGS_AGENT_BACKEND", "cli")
    assert scfg.settings_agent_backend() == "cli"


# ═══ 2. unavailable without his API key -- before anything else ══════

def test_run_turn_refuses_without_an_api_key_before_any_subprocess(monkeypatch):
    """No key, no subprocess, and the refusal says what to do about it --
    naming ANTHROPIC_API_KEY and the key file, because either is a
    legitimate way to configure it. The autouse _no_real_anthropic_key
    fixture in conftest.py is what makes "no key" true here even though
    his real key file exists on this machine."""
    from spectra.services import anthropic_key
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    def _boom(*a, **k):
        raise AssertionError("must not spawn a subprocess without an API key")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)

    with pytest.raises(SettingsAgentUnavailable, match="ANTHROPIC_API_KEY") as exc:
        _run(sac.run_turn(None, "set brightness to half"))
    assert str(anthropic_key.config.anthropic_api_key_file()) in str(exc.value)


def test_a_missing_key_never_falls_back_to_a_subscription_credential(monkeypatch):
    """THE no-fallback property stated as a test: a CLAUDE_CODE_OAUTH_TOKEN
    exported in this process is not a credential any more. With one present
    and no API key, the backend must still refuse -- nothing in this module
    reads it (config.settings_agent_cli_oauth_token() no longer exists)."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-should-never-be-used")
    monkeypatch.setattr(asyncio, "create_subprocess_exec",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("must not spawn a subprocess")))

    with pytest.raises(SettingsAgentUnavailable, match="ANTHROPIC_API_KEY"):
        _run(sac.run_turn(None, "set brightness to half"))

    from spectra import config as scfg
    assert not hasattr(scfg, "settings_agent_cli_oauth_token"), \
        "the subscription credential reader must stay deleted, not merely unused"


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


def test_subprocess_env_carries_the_api_key_and_strips_every_subscription_credential(
        monkeypatch, tmp_path):
    """The 2026-11-17 inversion: the child gets his API key and loses every
    credential that could bill anything else. A host that still exports a
    subscription token (this one does, for other tools) must not be able to
    pay for a Sonic turn with it."""
    from spectra.services import settings_agent_cli as sac

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-should-never-reach-the-child")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "also-should-never-reach-the-child")

    workdir = tmp_path / "workdir"
    env = sac._subprocess_env("sk-ant-api03-a-real-key", workdir)

    assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-a-real-key"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["CLAUDE_CONFIG_DIR"] == str(workdir / ".claude-config")


def test_the_key_is_never_passed_on_the_command_line():
    """A credential in argv is visible in every `ps` line on the host for
    the length of the call. _argv() must carry none."""
    from spectra.services import settings_agent_cli as sac

    argv = sac._argv("set brightness to half", None)
    joined = " ".join(argv)
    assert "ANTHROPIC_API_KEY" not in joined
    assert "sk-ant-" not in joined
    assert not any(a.startswith("--api-key") for a in argv)


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

                # House lighting's create also carries a `name` kwarg.
                house = await call("create_house_mode", {"name": "MCP House Mode"})
                assert house["status"] == "applied"

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


def test_a_device_domain_write_parses_from_its_structured_tool_result():
    """The DEVICE widening (2026-08-28) gets its own explicitly-synthetic
    fixture on the CURRENT manifest, the same way each earlier widening
    did — so this file proves the new surface parses, not just that the
    old ones went stale. `changes` comes from the structured tool_result
    the real handler wrote, never the reply prose."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_synthetic_device_applied.json"))
    assert [c["device_id"] for c in result["changes"]] == ["hue-lounge"]
    assert result["changes"][0]["timing_offset_ms"] == -80
    assert "earlier" in result["changes"][0]["summary"]


def test_the_scene_entry_param_widening_parses_from_its_structured_tool_result():
    """The 2026-10-06 Sonic coverage audit build's own widening (Pulse and
    every other effect's per-entry params) gets its own synthetic fixture
    on the CURRENT manifest, same precedent as the device domain above."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_scene_entry_param_applied.json"))
    assert [c["param"] for c in result["changes"]] == ["rest_calm"]
    assert result["changes"][0]["effect_type"] == "pulse"
    assert result["changes"][0]["was_bound"] is False
    assert "Singles" in result["changes"][0]["summary"]


def test_the_music_device_allowlist_widening_parses_from_its_structured_tool_result():
    """The music-device-gate widening (the Admiral, 2026-10-09:
    "it should only happen when I am playing music on those specific
    devices") gets its own explicitly-synthetic fixture on the CURRENT
    manifest, same precedent as the device/scene-entry-param widenings
    above."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_music_device_allowlist_applied.json"))
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["status"] == "applied"
    assert change["devices"] == ["Serenity", "Serenity guest"]
    assert "Serenity" in change["summary"]


def test_the_ha_actions_widening_parses_from_its_structured_tool_result():
    """The outbound-HA-actions widening (the Admiral, 2026-10-11: Light
    Show volume/scene steps reaching Home Assistant) gets its own
    explicitly-synthetic fixture on the CURRENT manifest, same precedent
    as the device/scene-entry-param/music-device-allowlist widenings
    above. `changes` comes from the set_ha_volume_absolute tool_result's
    own `status`/`summary`, never the reply prose."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_ha_volume_absolute_applied.json"))
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["status"] == "applied"
    assert change["run"]["steps"][0]["kind"] == "ha_volume_absolute"
    assert "52" in change["summary"]


def test_every_declared_operation_including_the_device_domain_is_in_the_manifest():
    """--allowedTools and the live manifest check are both derived from
    ALL_OPERATIONS, so a new domain cannot be added without its tools
    becoming reachable AND checked. Adding an operation without an MCP
    wrapper fails test_settings_mcp_server_starts_from_a_clean_cwd; this
    catches the other half."""
    from spectra.services import device_console
    from spectra.services import settings_agent_cli as sac

    for name in device_console.OPERATIONS:
        assert f"mcp__{sac.MCP_SERVER_NAME}__{name}" in sac.TOOL_NAMES


# ═══ 6. live smoke test (skipped unless SPECTRA_LIVE_CLAUDE=1 -- it ═══
# spends real API credits and writes the real stored room controls) ════

@pytest.mark.skipif(os.getenv("SPECTRA_LIVE_CLAUDE") != "1",
                    reason="spends real API credits -- export SPECTRA_LIVE_CLAUDE=1 to run")
def test_live_cli_can_apply_a_change():
    from spectra.services import room_controls as rc
    from spectra.services import settings_agent_cli as sac

    result = _run(sac.run_turn(None, "Set the brightness to 50%."))
    assert result["changes"], "the model should have called set_setting"
    assert rc.load_room_controls().brightness_multiplier == pytest.approx(0.5, abs=0.05)


def test_the_lock_domain_widening_parses_from_its_structured_tool_result():
    """The whole-song check's Sonic reach (spectra/services/lock_console.py,
    data/lock-investigation/report.md rec. 1) gets its own explicitly-
    synthetic fixture on the CURRENT manifest, same precedent as the
    device/scene-entry-param widenings above."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_whole_song_applied.json"))
    assert [c["key"] for c in result["changes"]] == ["xcorr_whole_song_locked_every"]
    assert (result["changes"][0]["old"], result["changes"][0]["new"]) == (4, 2)


def test_the_absorb_domain_widening_parses_from_its_structured_tool_result():
    """Absorb Music's Sonic reach (spectra/services/absorb_console.py,
    data/absorb-music-plan/report.md §10, phase 5) on the CURRENT manifest.
    The point of this fixture is its SECOND call: an unconfirmed start
    answers needs_confirmation, and nothing that has not happened may ever
    be parsed as a change — the model's reply asking "shall I start it?"
    notwithstanding."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_absorb_asks_first.json"))
    assert [c["new"] for c in result["changes"]] == [{"max_attempts": 4}]
    assert [r["status"] for r in result["rejected"]] == ["needs_confirmation"]
    assert result["rejected"][0]["op"] == "start_absorb"


def test_the_jukebox_domain_widening_parses_from_its_structured_tool_result():
    """The Jukebox's Sonic reach (spectra/services/jukebox_console.py,
    data/jukebox-plan/report.md PR 3.4) on the CURRENT manifest. Every
    jukebox change asks first, and the fixture's SECOND call is an
    unconfirmed night start: it answers needs_confirmation and must never
    be parsed as a change, whatever the reply's prose says."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_jukebox_asks_first.json"))
    assert [c["new"] for c in result["changes"]] == [{"add_base": 5}]
    assert [r["status"] for r in result["rejected"]] == ["needs_confirmation"]
    assert result["rejected"][0]["op"] == "start_jukebox_night"


def test_put_on_tv_widening_parses_from_its_structured_tool_result():
    """"One tap" (data/tv-display-plan/plan.html PR 1.6,
    spectra/services/jukebox_console.py's `put_on_tv` op) on the CURRENT
    manifest. It always asks first — an unconfirmed call must be parsed
    as `needs_confirmation`, never as a change, whatever the model's own
    reply prose claims it is about to do."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_tv_asks_first.json"))
    assert result["changes"] == []
    assert [r["status"] for r in result["rejected"]] == ["needs_confirmation"]
    assert result["rejected"][0]["op"] == "put_on_tv"


def test_the_lyrics_domain_widening_parses_from_its_structured_tool_result():
    """The lyrics plan step 3's Sonic coverage follow-up (spectra/services/
    lyric_console.py, PR #499's own missing Sonic operation) on the CURRENT
    manifest. edit_sung_label applies at once; read_song_lyrics always asks
    first — every call spends his Claude allowance, so an unconfirmed call
    must be parsed as needs_confirmation, never as a change, whatever the
    model's own reply prose claims it is about to do."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_lyrics_asks_first.json"))
    assert [c["summary"] for c in result["changes"]] == [
        "'passion' added to Blood Red's labels."]
    assert [r["status"] for r in result["rejected"]] == ["needs_confirmation"]
    assert result["rejected"][0]["op"] == "read_song_lyrics"


# ═══ 7. the 2026-11-02 stale-restart hardening (data/sonic-jukebox-
# unresponsive/report.md): a manifest mismatch that is PURELY "the live
# manifest reports some tool this running process doesn't expect yet, and
# every tool this process DOES expect is still there" (the exact shape of
# a deploy fast-forwarding /home/javi/SpotFX without restarting
# spectra.service) now DEGRADES rather than refuses — every other
# mismatch shape, including every real/synthetic fixture refused above,
# is untouched and still refuses outright. Built with small, in-test
# event lists rather than a new fixture file, since these are
# hypothetical manifest shapes, not a real capture worth pinning as one. ═

def _init_event(tools, servers_connected=True, session_id="synthetic-manifest-0001"):
    return {
        "type": "system", "subtype": "init", "session_id": session_id,
        "tools": list(tools),
        "mcp_servers": [{"name": "settings-console",
                        "status": "connected" if servers_connected else "failed"}],
    }


def _result_event(text="All good.", is_error=False, usage=None,
                  session_id="synthetic-manifest-0001"):
    event = {
        "type": "result", "subtype": "success" if not is_error else "error_during_execution",
        "is_error": is_error, "session_id": session_id, "result": text,
    }
    if usage is not None:
        event["usage"] = usage
    return event


def test_classify_manifest_degrades_on_a_single_extra_tool():
    """The exact incident shape: every tool this process expects IS in
    the live manifest (missing is empty), plus one the running process
    doesn't recognise yet (extra, non-empty) -- safe, per module
    docstring. The notice names the extra tool in plain words and is
    short, never the two 128-element lists the pre-hardening message
    dumped."""
    from spectra.services import settings_agent_cli as sac

    actual = list(sac.TOOL_NAMES) + ["mcp__settings-console__put_on_tv_newer"]
    verdict = sac._classify_manifest([_init_event(actual)])
    assert verdict.outcome == "degraded"
    assert "reduced mode" in verdict.notice
    assert "put_on_tv_newer" in verdict.notice
    assert "restart" in verdict.notice.lower()
    assert len(verdict.notice) < 400, "must be a short plain-language sentence, not a dumped manifest"


def test_classify_manifest_refuses_when_a_known_tool_goes_missing():
    """The OTHER direction -- the live manifest is missing a tool this
    process actually expects -- stays a hard refusal: that is the shape
    every historical-capture/fabrication fixture above exercises, and
    nothing here loosens it, regardless of how many extra tools also
    happen to be present alongside the missing one."""
    from spectra.services import settings_agent_cli as sac

    actual = [t for t in sac.TOOL_NAMES if t != sac.TOOL_NAMES[0]]
    verdict = sac._classify_manifest([_init_event(actual)])
    assert verdict.outcome == "refused"
    assert "tool manifest" in verdict.notice
    assert "missing" in verdict.notice
    assert len(verdict.notice) < 400, "must be a short plain-language sentence, not a dumped manifest"


def test_classify_manifest_refuses_on_a_stray_mcp_server_even_with_an_exact_tool_list():
    """Tools match exactly but the one trusted server isn't reported
    connected -- still a hard refusal; the degrade path only ever applies
    to the extra-only tool-name shape, never to the server-identity
    check."""
    from spectra.services import settings_agent_cli as sac

    verdict = sac._classify_manifest([_init_event(sac.TOOL_NAMES, servers_connected=False)])
    assert verdict.outcome == "refused"
    assert "mcp_servers" in verdict.notice


def test_classify_manifest_refuses_extra_only_drift_if_the_server_is_not_connected():
    """Belt-and-braces: even an extra-only (missing=empty) tool-name
    mismatch must NOT degrade unless the one trusted server is actually
    reporting itself connected -- the foundational assumption the whole
    degrade path rests on."""
    from spectra.services import settings_agent_cli as sac

    actual = list(sac.TOOL_NAMES) + ["mcp__settings-console__put_on_tv_newer"]
    verdict = sac._classify_manifest([_init_event(actual, servers_connected=False)])
    assert verdict.outcome == "refused"


def test_verify_tool_manifest_degrades_without_raising_and_logs_a_warning(caplog):
    from spectra.services import settings_agent_cli as sac

    actual = list(sac.TOOL_NAMES) + ["mcp__settings-console__put_on_tv_newer"]
    with caplog.at_level("WARNING"):
        notice = sac._verify_tool_manifest([_init_event(actual)])
    assert notice is not None and "reduced mode" in notice
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a manifest drift must be logged at WARNING"
    assert "put_on_tv_newer" in warnings[0].getMessage()
    assert len(warnings[0].getMessage()) < 500, \
        "the journal line must carry the short set difference, not two full manifests"


def test_verify_tool_manifest_still_raises_and_logs_on_a_missing_tool(caplog):
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    actual = [t for t in sac.TOOL_NAMES if t != sac.TOOL_NAMES[0]]
    with caplog.at_level("WARNING"):
        with pytest.raises(SettingsAgentUnavailable, match="tool manifest"):
            sac._verify_tool_manifest([_init_event(actual)])
    assert any(r.levelname == "WARNING" for r in caplog.records), \
        "the old incident shipped a bare 503 with NO journal line explaining it -- a refusal must now log"


def test_parse_transcript_degrades_a_drifted_manifest_and_still_extracts_a_real_change():
    """The turn completes: the structured tool_result is still trusted
    (it went through the real dispatch table either way), `changes`
    parses exactly as it would without any drift, and the degraded-mode
    notice is PREPENDED to the reply -- "in the reply area," his own
    words -- never hidden behind a separate field nothing renders."""
    from spectra.services import settings_agent_cli as sac

    actual = list(sac.TOOL_NAMES) + ["mcp__settings-console__put_on_tv_newer"]
    events = [
        _init_event(actual),
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "mcp__settings-console__set_setting"},
            ]},
        },
        {
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                    {"type": "text", "text": json.dumps({
                        "status": "applied", "key": "brightness_multiplier",
                        "old": 1.0, "new": 0.5, "summary": "brightness_multiplier: 1.0 → 0.5",
                    })},
                ]},
            ]},
        },
        _result_event("Set it."),
    ]
    result = sac._parse_transcript(events)
    assert result["degraded"] is not None and "reduced mode" in result["degraded"]
    assert result["reply"].startswith(result["degraded"])
    assert "Set it." in result["reply"]
    assert len(result["changes"]) == 1
    assert result["changes"][0]["key"] == "brightness_multiplier"


def test_parse_transcript_has_no_degraded_field_on_an_exact_manifest_match():
    """Every existing, exact-manifest fixture keeps answering `degraded:
    None` -- additive, never a behaviour change for the common case."""
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(_load("cli_transcript_synthetic_overwrite_applied.json"))
    assert result["degraded"] is None


def test_record_usage_tags_the_manifest_outcome(tmp_path):
    """The 'optional' recommendation: usage is still recorded on EVERY
    outcome (tokens were genuinely spent regardless — _record_usage's own
    docstring), but is now tagged with the real manifest verdict so a
    refused/degraded turn is never silently counted the same as one that
    actually answered him."""
    import json as _json

    from spectra import config as scfg
    from spectra.services import settings_agent_cli as sac

    def _entries():
        return _json.loads(scfg.SONIC_USAGE_FILE.read_text())

    ok_events = [_init_event(sac.TOOL_NAMES, session_id="s-ok"),
                _result_event("ok.", usage={"input_tokens": 1, "output_tokens": 1}, session_id="s-ok")]
    sac._record_usage(ok_events)
    assert _entries()[-1]["outcome"] == "ok"

    degraded_actual = list(sac.TOOL_NAMES) + ["mcp__settings-console__put_on_tv_newer"]
    degraded_events = [_init_event(degraded_actual, session_id="s-degraded"),
                       _result_event("ok.", usage={"input_tokens": 1, "output_tokens": 1}, session_id="s-degraded")]
    sac._record_usage(degraded_events)
    assert _entries()[-1]["outcome"] == "degraded"

    refused_actual = [t for t in sac.TOOL_NAMES if t != sac.TOOL_NAMES[0]]
    refused_events = [_init_event(refused_actual, session_id="s-refused"),
                      _result_event("ok.", usage={"input_tokens": 1, "output_tokens": 1}, session_id="s-refused")]
    sac._record_usage(refused_events)
    assert _entries()[-1]["outcome"] == "refused"

    # Real spend is still counted the same regardless of outcome -- his
    # own ask was "how much usage," not "how much successful usage".
    from spectra.services import sonic_usage as su
    total = su.summary()
    assert total["day"]["query_count"] == 3
    assert total["day"]["total_tokens"] == 6


# ═══ 8. the Word Shapes W2.4 widening (the two band-attachment ops) ══════
# attach_flare_kind/detach_flare_kind are the first write in this backend
# that edits a scene's RESPONSE BANDS (responses[class].bands[*].kinds) —
# a meaningfully new write shape, so the sonic-ops checklist's step 7
# applies: one synthetic fixture on the CURRENT manifest, parsed from its
# structured tool_result rather than the model's own reply prose. It is
# also the op that switches a Word Shape on for a scene (the plan's "the
# band is the switch"), so "the model said it attached it" and "the
# attachment landed" must stay different claims here too. ════════════════

def test_the_band_attachment_widening_parses_from_its_structured_tool_result():
    from spectra.services import settings_agent_cli as sac

    result = sac._parse_transcript(
        _load("cli_transcript_synthetic_attach_flare_kind_applied.json"))
    assert result.get("degraded") is None
    assert [c["op"] for c in result["changes"]] == ["flare_kind_attached"]
    change = result["changes"][0]
    assert change["summary"] == (
        'Attached "Word Shape" to the Words section [0.0, 1.0) on "Fish".')
    assert change["response_class"] == "word"
    assert change["backup_id"] == "synthetic-backup-1"
    assert not result["rejected"]


# ═══ 9. WHO PAID (the Admiral's 2026-11-17 order) ════════════════════════
# The structural half is section 2 (no key -> no subprocess) and section 4
# (the child's environment carries his API key and nothing else that could
# pay). This section is the DETECTOR on top of it: `claude -p --output-
# format json`'s system/init event reports `apiKeySource`, and a turn that
# says it billed anything other than ANTHROPIC_API_KEY refuses rather than
# passing quietly. An ABSENT field warns instead of refusing, on purpose —
# the no-fallback guarantee rests on the environment, not on this field, and
# a CLI that stopped emitting it must not switch a working feature off.

def _init_with_key_source(source, tools=None):
    event = _init_event(tools if tools is not None else [])
    if source is not None:
        event["apiKeySource"] = source
    return event


def test_an_api_key_billed_turn_is_accepted():
    """The shape a real call produces — verified live against the real CLI
    (2.1.326) with the key file in place: apiKeySource "ANTHROPIC_API_KEY",
    total_cost_usd populated."""
    from spectra.services import settings_agent_cli as sac

    sac._verify_api_key_source([_init_with_key_source("ANTHROPIC_API_KEY")])


@pytest.mark.parametrize("source", ["subscription", "claude.ai", "bedrock", "none", "apiKeyHelper"])
def test_a_turn_billed_to_anything_else_refuses(source, caplog):
    """A subscription login, a keychain entry, a Bedrock/Vertex credential:
    the order says that is an error, not a fallback. The message names what
    it actually billed so the cause is in the text, not in a guess."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    with caplog.at_level("WARNING"):
        with pytest.raises(SettingsAgentUnavailable, match="ANTHROPIC_API_KEY"):
            sac._verify_api_key_source([_init_with_key_source(source)])
    assert any(source in r.getMessage() for r in caplog.records if r.levelname == "WARNING")


def test_an_absent_api_key_source_warns_but_does_not_break_the_turn(caplog):
    from spectra.services import settings_agent_cli as sac

    with caplog.at_level("WARNING"):
        sac._verify_api_key_source([_init_with_key_source(None)])
    assert any("apiKeySource" in r.getMessage()
               for r in caplog.records if r.levelname == "WARNING")


def test_parse_transcript_refuses_a_subscription_billed_turn_even_with_a_perfect_manifest():
    """End to end through the real parse path: the manifest is exactly
    right, the MCP server is connected, a real change was applied — and the
    turn is STILL refused, because it was not his API key that paid for it.
    `changes` is never returned from a refused turn."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    init = _init_event(sac.TOOL_NAMES)
    init["apiKeySource"] = "subscription"
    events = [
        init,
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1",
             "name": "mcp__settings-console__set_setting"}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                {"type": "text", "text": json.dumps({"status": "applied"})}]}]}},
        _result_event("Set it."),
    ]
    with pytest.raises(SettingsAgentUnavailable, match="not 'ANTHROPIC_API_KEY'"):
        sac._parse_transcript(events)


def test_a_stale_manifest_is_still_diagnosed_before_the_billing_check():
    """Ordering, stated as a test: a stale-restart manifest mismatch is the
    older and more specific diagnosis, so it must still be the message he
    gets even when the billing field is also wrong."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    init = _init_event([t for t in sac.TOOL_NAMES if t != sac.TOOL_NAMES[0]])
    init["apiKeySource"] = "subscription"
    with pytest.raises(SettingsAgentUnavailable, match="tool manifest"):
        sac._parse_transcript([init, _result_event("hi")])


def test_a_rejected_key_surfaces_the_clis_own_words_redacted(monkeypatch):
    """An invalid key is `claude -p`'s own is_error result (exit 1, parseable
    JSON on stdout). It must reach him verbatim — not flattened into a
    generic failure, not retried against anything else — and with any
    credential scrubbed out of it."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-the-real-one")
    events = [_init_with_key_source("ANTHROPIC_API_KEY", sac.TOOL_NAMES),
              {"type": "result", "subtype": "error_during_execution", "is_error": True,
               "result": "Invalid API key · Please run /login (key sk-ant-api03-the-real-one)"}]
    with pytest.raises(SettingsAgentUnavailable) as exc:
        sac._parse_transcript(events)
    assert "Invalid API key" in str(exc.value), "the CLI's own words, kept"
    assert "sk-ant-api03-the-real-one" not in str(exc.value), "the key, never"
    assert "[redacted]" in str(exc.value)


def test_subprocess_stderr_is_redacted_before_it_reaches_an_exception(monkeypatch, tmp_path):
    """The other leak path: a non-0/1 exit puts the child's stderr in the
    exception message. A CLI that ever echoes the credential it was handed
    must not be able to leak it through us."""
    import stat
    import textwrap

    from spectra.services import settings_agent_cli as sac
    from spectra.services.settings_agent import SettingsAgentUnavailable

    script = tmp_path / "claude"
    script.write_text("#!" + sys.executable + "\n" + textwrap.dedent("""
        import os, sys
        sys.stderr.write("boom, key was " + os.environ["ANTHROPIC_API_KEY"])
        sys.exit(2)
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-the-real-one")
    monkeypatch.setattr(sac.config, "settings_agent_cli_binary", lambda: str(script))
    monkeypatch.setattr(sac.config, "settings_agent_cli_workdir", lambda: tmp_path / "work")

    with pytest.raises(SettingsAgentUnavailable) as exc:
        _run(sac.run_turn(None, "hi"))
    assert "boom" in str(exc.value)
    assert "sk-ant-api03-the-real-one" not in str(exc.value)
