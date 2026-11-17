"""The one way the lyric features ask Claude something and get JSON back
(spectra/services/lyric_reading.py, color_meanings.py). Text in, text out: no
audio ever goes through here, and no tools are offered.

THE SAME KEY AND THE SAME SWITCH AS SONIC. `config.settings_agent_backend()`
picks the transport -- the Anthropic SDK or the `claude` CLI -- and BOTH bill
his own API credits since the Admiral's order of 2026-11-17 (the subscription
login these features used to run on is gone; spectra/services/
settings_agent_cli.py's docstring has that history). The key itself comes from
spectra/services/anthropic_key.py on every call, which reads it fresh from the
environment or ~/.config/anthropic/api-key -- one helper, so a missing key says
the same sentence here that it says in Sonic's error path and on the lyric
pages. The CLI half reuses settings_agent_cli's clean working directory,
isolated config directory and env-building rather than a second copy of those
rules, so it inherits the same no-other-credential-in-the-child property and
the same apiKeySource check. A missing key is a stated ClaudeUnavailable before
anything is asked; a rejected one is the API's or the CLI's own error, redacted,
never retried against something else.

The model comes from `config.lyric_agent_model()`, which is Sonic's model unless
SPECTRA_LYRIC_AGENT_MODEL says otherwise.

WHAT COMES BACK IS NOT TRUSTED. The API backend constrains the reply to the
schema and the CLI backend only asks for it; either way the callers validate
every row against what is really on the list and in the lyrics, and a row that
names something that is not there is thrown away and counted.

Every call's real token usage goes on the same record Sonic's does
(spectra/services/sonic_usage.py), so the Review page's figures for how much of
his allowance is gone stay true. Nothing is recorded if a backend reports none.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from spectra import config
from spectra.services import anthropic_key, sonic_usage

logger = logging.getLogger(__name__)

MAX_TOKENS = 16_000
CLI_TIMEOUT_S = 240.0


class ClaudeUnavailable(Exception):
    """Claude could not be asked or did not answer. Worth trying again later."""


class ClaudeReplyInvalid(Exception):
    """Claude answered with something unusable (declined, cut off, not JSON)."""


@dataclass(frozen=True)
class ClaudeReply:
    data: dict[str, Any]
    model: str
    backend: str


def availability() -> dict[str, Any]:
    """Whether a press of a read button can work, without asking Claude.

    ONE CAUSE FOR BOTH TRANSPORTS now that both bill his API key: a key or
    no key, with anthropic_key.missing_reason()'s own sentence as the
    reason the page shows (it names ANTHROPIC_API_KEY and the key file, so
    the fix is in the message). `reason` is what the UI renders; it never
    carries the key, only the file's path."""
    backend = config.settings_agent_backend()
    model = config.lyric_agent_model()
    if anthropic_key.read():
        return {"available": True, "reason": None, "backend": backend, "model": model}
    return {"available": False, "reason": anthropic_key.missing_reason(),
            "backend": backend, "model": model}


def parse_json_text(text: str) -> dict[str, Any]:
    """The JSON object in a model's text reply, allowing for a code fence or a
    stray sentence around it."""
    stripped = (text or "").strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise ClaudeReplyInvalid("The reply had no JSON in it.")
    try:
        data = json.loads(stripped[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ClaudeReplyInvalid(f"The reply was not valid JSON ({exc}).") from exc
    if not isinstance(data, dict):
        raise ClaudeReplyInvalid("The reply was not a JSON object.")
    return data


def _record_usage(*, backend: str, model: str, usage: Any, purpose: str,
                  cost_usd: Any = None, rounds: Any = None) -> None:
    if usage is None:
        return
    get = (usage.get if isinstance(usage, dict) else lambda k, d=None: getattr(usage, k, d))
    try:
        sonic_usage.record(
            backend=backend, model=model,
            input_tokens=get("input_tokens", 0) or 0,
            output_tokens=get("output_tokens", 0) or 0,
            cache_creation_input_tokens=get("cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=get("cache_read_input_tokens", 0) or 0,
            cost_usd=cost_usd, session_id=purpose, rounds=rounds)
    except Exception:
        logger.exception("usage record failed (%s)", purpose)


async def _ask_api(*, system: str, user: str, schema: dict, purpose: str) -> ClaudeReply:
    api_key = anthropic_key.read()
    if not api_key:
        raise ClaudeUnavailable(anthropic_key.missing_reason())
    try:
        import anthropic
    except ImportError as exc:
        raise ClaudeUnavailable("The anthropic package is not installed.") from exc
    model = config.lyric_agent_model()
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            # The label list is the system prompt: identical for every song,
            # so all but the first song read it from the cache.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIError as exc:
        # A rejected key lands here (AuthenticationError/PermissionDenied):
        # the API's own words, redacted, never a retry against anything
        # else. redact() because an SDK error can quote the request it made.
        raise ClaudeUnavailable(anthropic_key.redact(
            f"Claude did not answer ({type(exc).__name__}: {exc}).")) from exc
    _record_usage(backend="api", model=model, usage=getattr(response, "usage", None),
                  purpose=purpose, rounds=1)
    if response.stop_reason == "refusal":
        raise ClaudeReplyInvalid("Claude declined to read this.")
    if response.stop_reason == "max_tokens":
        raise ClaudeReplyInvalid("Claude's reply was cut off before it finished.")
    text = "".join(block.text for block in response.content if block.type == "text")
    return ClaudeReply(parse_json_text(text), model, "api")


async def _ask_cli(*, system: str, user: str, schema: dict, purpose: str) -> ClaudeReply:
    from spectra.services import settings_agent_cli as cli
    try:
        api_key = cli._api_key_available()
        workdir = cli._workdir()
    except cli.SettingsAgentUnavailable as exc:
        raise ClaudeUnavailable(str(exc)) from exc
    model = config.lyric_agent_model()
    instruction = ("\n\nReply with one JSON object and nothing else, matching this "
                   f"schema:\n{json.dumps(schema)}")
    argv = [
        config.settings_agent_cli_binary(),
        "-p", user,
        "--model", model,
        "--system-prompt", system + instruction,
        "--strict-mcp-config",
        "--tools", "",
        "--output-format", "json",
        "--verbose",
    ]
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(workdir), env=cli._subprocess_env(api_key, workdir),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=CLI_TIMEOUT_S)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ClaudeUnavailable("Claude took too long to answer.") from exc
    if process.returncode not in (0, 1):
        raise ClaudeUnavailable(
            f"Claude's CLI exited {process.returncode}: "
            f"{anthropic_key.redact(stderr.decode('utf-8', 'replace'))[:300]}")
    try:
        events = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudeUnavailable(f"Claude's CLI output could not be read ({exc}).") from exc
    if not isinstance(events, list):
        events = [events]
    final = next((e for e in reversed(events)
                  if isinstance(e, dict) and e.get("type") == "result"), None)
    if final is None:
        raise ClaudeUnavailable("Claude's CLI gave no result.")
    # Same who-paid check Sonic's own CLI turns get -- raises if the CLI
    # reports it authenticated as anything other than his API key.
    try:
        cli._verify_api_key_source(events)
    except cli.SettingsAgentUnavailable as exc:
        raise ClaudeUnavailable(str(exc)) from exc
    model_usage = final.get("modelUsage") or {}
    _record_usage(backend="cli", model=next(iter(model_usage), None) or model,
                  usage=final.get("usage"), purpose=purpose,
                  cost_usd=final.get("total_cost_usd"), rounds=final.get("num_turns"))
    if final.get("is_error"):
        raise ClaudeUnavailable(anthropic_key.redact(
            str(final.get("result") or "Claude's CLI reported an error.")))
    return ClaudeReply(parse_json_text(str(final.get("result") or "")), model, "cli")


async def ask_json(*, system: str, user: str, schema: dict, purpose: str) -> ClaudeReply:
    """Ask once. Raises ClaudeUnavailable or ClaudeReplyInvalid; never retries,
    so a caller's own pacing decides how much of his allowance is spent."""
    if config.settings_agent_backend() == "cli":
        return await _ask_cli(system=system, user=user, schema=schema, purpose=purpose)
    return await _ask_api(system=system, user=user, schema=schema, purpose=purpose)
