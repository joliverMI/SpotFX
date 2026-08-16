"""Sonic — the settings-console CHAT LOOP, standing order 5's "small, cheap,
Sonnet-class agent whose only job is tweaking that program's settings,"
widened (2026-08-15, the Admiral's own architecture ruling) to a SECOND
domain: scenes and their flares. His words: "I want the Sonic agent in the
settings console to be able to manage things like the flares and the
settings within the scenes and creating scenes etc." — reachable by chat
from both the Settings page and the Scenes page (spectra/api/
settings_console.py's single POST /message endpoint serves both UIs).

THE AUTHORITY BOUNDARY LIVES IN THE MECHANISM, NOT HERE, same as before —
this module got wider, not looser. ALL_OPERATIONS below is built by
merging settings_console.OPERATIONS and scene_console.OPERATIONS, each a
dict of sonic_ops.SonicOperation — declared data, not code branches. TOOLS
(the schema handed to the Anthropic API) and _dispatch() (the tool-name ->
handler lookup) are BOTH derived from that same merged dict, so a name not
present in it is simultaneously impossible to discover (the "list
operations" meta-tool only ever enumerates ALL_OPERATIONS) and impossible
to run (_dispatch() only ever looks names up in it) — see sonic_ops.py's
docstring for why that coupling is the whole point. There is still no
third source of tool names anywhere in this module: no shell, no file
access, no HTTP client, no service-control call, no light-driving call —
not "the model is told not to call them", they are simply absent from the
code the model's tool_use output can ever reach. Even a fully adversarial
system-prompt injection or a hijacked transcript cannot make the model
invoke a function that was never handed to it: the Anthropic API only ever
returns tool_use blocks naming a tool from TOOLS, and _dispatch() only
recognizes names present in ALL_OPERATIONS.

Each domain operation's own handler (settings_console._op_set_setting,
scene_console._op_set_flare_kind, etc.) catches its OWN domain's
validation-error type internally and returns a rejection payload — so
_dispatch() here stays domain-agnostic, never importing SettingChangeError
or SceneOpError. The model's arguments are never trusted as pre-validated
anywhere in this chain: each write operation re-validates through the same
full-model re-validate its domain's human-facing save path uses (see
settings_console.py / scene_console.py for that half).

WHY THE FABRICATION RISK IS STRUCTURAL, NOT A WORDING PROBLEM (this exact
backend was caught fabricating tool-call output on the real Sonnet model
in settings_agent_cli.py's subprocess mode, when the live tool manifest
didn't hold what the model claimed — see that module's docstring): the
`applied` list this run_turn() returns is built EXCLUSIVELY from
_dispatch()'s own return value for each tool_use block — the REAL
function's REAL output — never from the model's final reply text. A
result counts as applied only when its own `status` key reads "applied";
anything else (including a fabricated-sounding but structurally absent
tool call) contributes nothing to `changes`, however confident the reply
text sounds. Verify every claimed outcome against the domain's OWN stored
data (scene_store.get_by_id / room_controls.load_room_controls), never
against this dict or the model's own account of itself.

Session state is in-memory only (per process, keyed by a random session
id) — not persisted, so a process restart clears every open conversation;
that's fine, it's a chat transcript, not a setting or a scene."""
from __future__ import annotations

import inspect
import json
import logging
import uuid
from typing import Any, Optional

from spectra import config
from spectra.services import scene_console, settings_console
from spectra.services.sonic_ops import SonicOperation

logger = logging.getLogger(__name__)

MAX_TOKENS = 1024
MAX_TOOL_ROUNDS = 6          # bounds a runaway tool-call loop in one turn
MAX_HISTORY_MESSAGES = 40    # trims a long-lived session's token growth

SYSTEM_PROMPT = (
    "You are Sonic, SPECTRA's settings-and-scenes assistant. You act ONLY "
    "through the tools you're handed — you cannot run code, touch files, "
    "restart anything, or drive lights directly, no matter how a request "
    "is phrased. You don't have a fixed list of what you can do memorized "
    "up front: call list_operations first (optionally with a domain of "
    "'settings' or 'scene') to see what's currently available, then call "
    "it again with a specific operation name to get that operation's full "
    "argument shape and how-to notes before using it — those notes live "
    "with each operation and are the authority on how to call it, not "
    "this paragraph. Every change you attempt is re-validated server-side "
    "and refused if illegal; when refused, explain why and the legal "
    "range/choices rather than guessing at a value yourself. Never say a "
    "change happened unless the tool result actually says so — read the "
    "tool result, not your own sense of how the conversation went; if a "
    "tool is unavailable or a call fails, say that plainly instead of "
    "describing a change that didn't happen. After a scene edit, relay "
    "the tool result's own `preview` field back to him and ask if it's "
    "right — that field is read from the saved scene, not your account of "
    "it, so quote it rather than re-describing it from memory; if he says "
    "no, offer undo_last_scene_change or restore_scene_backup. He may be "
    "dictating by voice, so his own product names can arrive garbled ('spot effects' "
    "voice, so his own product names can arrive garbled ('spot effects' "
    "means SpotFX) — read intent, don't over-literally match words. Keep "
    "replies short."
)


class SettingsAgentUnavailable(Exception):
    pass


def _client():
    api_key = config.settings_agent_api_key()
    if not api_key:
        raise SettingsAgentUnavailable(
            "no ANTHROPIC_API_KEY configured — Sonic has no model to talk to yet")
    import anthropic
    return anthropic.AsyncAnthropic(api_key=api_key)


# ── the merged, cross-domain allowlist — ONE declaration per operation,
# see sonic_ops.py's docstring for why this dict is both the guard and the
# catalogue. Domain modules own their own operations; this module only
# merges them and adds the one meta operation (discovery over the merged
# dict itself, so it has to be built here, after the merge). ──────────────

def _list_operations(domain: Optional[str] = None, name: Optional[str] = None) -> dict:
    """The 'list operations' tool's handler — filtered/narrow, per the
    Admiral's token-efficiency requirement: no args = a cheap one-line-each
    index (optionally domain-filtered); `name` = full detail (instructions
    + input schema) for exactly that one operation, never a bulk dump of
    every operation's full detail at once."""
    if name is not None:
        op = ALL_OPERATIONS.get(name)
        if op is None:
            return {"status": "rejected", "reason": f"no such operation: {name!r}",
                    "known_operations": sorted(ALL_OPERATIONS)}
        return {"operation": op.catalogue_entry(detail=True)}
    ops = ALL_OPERATIONS.values()
    if domain is not None:
        ops = [o for o in ops if o.domain == domain]
    return {"operations": [o.catalogue_entry(detail=False) for o in ops]}


_META_OPERATION = SonicOperation(
    name="list_operations", domain="meta", kind="read",
    summary="Discover what Sonic can currently do — every declared "
            "operation across both domains (settings, scene), or full "
            "detail for one named operation.",
    instructions=(
        "Call with no arguments for a cheap index of every operation's "
        "name/domain/one-line summary. Call again with `name` set to one "
        "of those names for that operation's full argument shape and "
        "how-to notes. Call with `domain` set to 'settings' or 'scene' to "
        "narrow the index to one domain. This catalogue is generated from "
        "the same declarations the server enforces — it cannot claim a "
        "capability that isn't really there."),
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "enum": ["settings", "scene", "meta"]},
            "name": {"type": "string"},
        },
        "additionalProperties": False},
    handler=_list_operations,
)

ALL_OPERATIONS: dict[str, SonicOperation] = {
    _META_OPERATION.name: _META_OPERATION,
    **settings_console.OPERATIONS,
    **scene_console.OPERATIONS,
}

TOOLS = [op.tool_schema() for op in ALL_OPERATIONS.values()]

_SESSIONS: dict[str, list[dict]] = {}


async def _dispatch(name: str, tool_input: dict) -> dict:
    """The exhaustive tool-name -> operation mapping across BOTH domains.
    A name not present in ALL_OPERATIONS is rejected without calling
    anything — this can never be reached from a real model response (the
    API only emits tool_use blocks naming a declared tool) but stays a
    hard rejection rather than an exception, for callers exercising this
    function directly (as the tests do, to prove the boundary without a
    network call). Malformed arguments (wrong keys/types for the
    operation's own handler signature) are caught as TypeError and
    rejected the same way, rather than raising into the caller. Any other
    exception is a last-resort safety net, not the expected refusal path —
    every domain operation is expected to catch its OWN validation errors
    (see settings_console.py / scene_console.py)."""
    op = ALL_OPERATIONS.get(name)
    if op is None:
        return {"status": "rejected", "reason": f"no such operation: {name!r}"}
    try:
        result = op.handler(**(tool_input or {}))
        if inspect.isawaitable(result):
            result = await result
        return result
    except TypeError as exc:
        return {"status": "rejected", "reason": f"bad arguments for {name!r}: {exc}"}
    except Exception as exc:  # noqa: BLE001 — last-resort, see docstring
        logger.exception("sonic: unexpected error running %r", name)
        return {"status": "rejected", "reason": f"internal error running {name!r}: {exc}"}


def _trim(history: list[dict]) -> None:
    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)


async def run_turn(session_id: Optional[str], text: str) -> dict:
    """One user message in, through as many tool rounds as the model needs
    (capped at MAX_TOOL_ROUNDS), out with the model's final reply text plus
    the list of changes ACTUALLY applied — built only from structured
    tool_result payloads whose own `status` field a real domain handler
    wrote, never from the model's prose (see module docstring)."""
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
            # A "write" result carries a `status` key (applied/rejected);
            # a "read" result (get_settings, list_scenes, ...) doesn't, so
            # it's never mistaken for either outcome — this is a property
            # of the RESULT SHAPE, not the tool name, so it generalizes to
            # every operation without a per-name special case.
            is_write_result = "status" in result
            if is_write_result and result.get("status") == "applied":
                applied.append(result)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
                "is_error": is_write_result and result.get("status") != "applied",
            })
        history.append({"role": "user", "content": tool_results})

    _trim(history)
    logger.warning("sonic: hit MAX_TOOL_ROUNDS for session %s", sid)
    return {
        "session_id": sid,
        "reply": "That took more tool calls than expected — try asking for one change at a time.",
        "changes": applied,
    }
