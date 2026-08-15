"""The settings-console CHAT LOOP — standing order 5's "small, cheap,
Sonnet-class agent whose only job is tweaking that program's settings."

THE AUTHORITY BOUNDARY LIVES IN THE MECHANISM, NOT HERE. This module is
allowed to be sloppy about wording because the boundary doesn't depend on
it: TOOLS below declares exactly two functions, and _dispatch() is the
complete, exhaustive mapping from tool name to code —

  get_settings -> settings_console.describe_current()   (read-only)
  set_setting  -> settings_console.apply_change()        (the ONE write path)

There is no third branch. No shell, no file access, no HTTP client, no
service-control call, no light-driving call exists anywhere in this
module or in settings_console.py — not "the model is told not to call
them", they are simply absent from the code the model's tool_use output
can ever reach. Even a fully adversarial system-prompt injection or a
hijacked transcript cannot make the model invoke a function that was
never handed to it: the Anthropic API only ever returns tool_use blocks
naming a tool from TOOLS, and _dispatch() only recognizes those two
names. apply_change() itself re-validates the key/value against
SETTINGS_REGISTRY and RoomControlState's own Field constraints — the
model's arguments are never trusted as pre-validated, exactly like any
other untrusted client input. See settings_console.py for that half.

Session state is in-memory only (per process, keyed by a random session
id) — not persisted, so a process restart clears every open conversation;
that's fine, it's a chat transcript, not a setting.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from spectra import config
from spectra.services import settings_console

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024
MAX_TOOL_ROUNDS = 6          # bounds a runaway tool-call loop in one turn
MAX_HISTORY_MESSAGES = 40    # trims a long-lived session's token growth

SYSTEM_PROMPT = (
    "You are SPECTRA's settings-console assistant. You have exactly two "
    "tools: get_settings (read every setting's current value and legal "
    "range) and set_setting (change one setting). You cannot do anything "
    "else — no code, no files, no restarting anything, no driving lights "
    "directly. If a request is out of scope, say so plainly instead of "
    "guessing at a tool call. He may be dictating by voice, so his own "
    "product names can arrive garbled ('spot effects' means SpotFX, 'led "
    "effects' means LedFX) — read intent, don't over-literally match "
    "words. If a value would be rejected as out of range, explain the "
    "legal range/choices and suggest the nearest legal value rather than "
    "silently picking one yourself. Keep replies short."
)

TOOLS = [
    {
        "name": "get_settings",
        "description": "Read every settings-console setting's current value, type, unit, and legal range/choices.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "set_setting",
        "description": (
            "Change ONE declared setting. The server validates the key and "
            "value against its declared range/choices server-side and "
            "rejects anything outside them — this is the only way this "
            "agent can change anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": sorted(settings_console.SETTINGS_REGISTRY)},
                "value": {"description": "The new value — type depends on the setting (see get_settings)."},
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        },
    },
]

_SESSIONS: dict[str, list[dict]] = {}


class SettingsAgentUnavailable(Exception):
    pass


def _client():
    api_key = config.settings_agent_api_key()
    if not api_key:
        raise SettingsAgentUnavailable(
            "no ANTHROPIC_API_KEY configured — the settings console has no "
            "model to talk to yet")
    import anthropic
    return anthropic.AsyncAnthropic(api_key=api_key)


async def _dispatch(name: str, tool_input: dict) -> dict:
    """The exhaustive tool-name -> code mapping. Anything not literally
    'get_settings' or 'set_setting' returns a rejection — it can never be
    reached from a real model response (the API only emits tool_use blocks
    naming a declared tool) but stays a hard rejection rather than an
    exception, for callers exercising this function directly (as the tests
    do, to prove the boundary without a network call)."""
    if name == "get_settings":
        return settings_console.describe_current()
    if name == "set_setting":
        try:
            return await settings_console.apply_change(
                tool_input.get("key"), tool_input.get("value"))
        except settings_console.SettingChangeError as exc:
            return exc.payload()
    return {"status": "rejected", "reason": f"no such tool: {name!r}"}


def _trim(history: list[dict]) -> None:
    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)


async def run_turn(session_id: Optional[str], text: str) -> dict:
    """One user message in, through as many get_settings/set_setting tool
    rounds as the model needs (capped at MAX_TOOL_ROUNDS), out with the
    model's final reply text plus the list of changes actually applied."""
    client = _client()  # raises SettingsAgentUnavailable before any state changes
    sid = session_id or str(uuid.uuid4())
    history = _SESSIONS.setdefault(sid, [])
    history.append({"role": "user", "content": text})

    applied: list[dict] = []
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.messages.create(
            model=config.settings_agent_model(),
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )
        history.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            reply = "".join(b.text for b in response.content if b.type == "text")
            _trim(history)
            return {"session_id": sid, "reply": reply, "changes": applied}

        tool_results = []
        for tu in tool_uses:
            result = await _dispatch(tu.name, tu.input)
            if tu.name == "set_setting" and result.get("status") == "applied":
                applied.append(result)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
                "is_error": result.get("status") != "applied" and tu.name == "set_setting",
            })
        history.append({"role": "user", "content": tool_results})

    _trim(history)
    logger.warning("settings agent: hit MAX_TOOL_ROUNDS for session %s", sid)
    return {
        "session_id": sid,
        "reply": "That took more tool calls than expected — try asking for one change at a time.",
        "changes": applied,
    }
