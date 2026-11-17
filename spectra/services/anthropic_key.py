"""THE ONE PLACE every Claude-calling feature in SPECTRA asks "do we have
his API key, and what do I say if we don't" — the Admiral's 2026-11-17
order, verbatim on the part that shapes this module: "read the key from
that file at runtime (or pass it via an env var loaded from that file by
the service unit) — never copy it into code, config in git, logs, status
lines or reports ... handle a missing/invalid key with a clear error, not
a silent fallback to claude -p."

Three features come through here, and they are the whole inventory of
Claude calls in this repo (grep `import anthropic` and
`create_subprocess_exec` for the proof):

  1. Sonic, "api" transport — spectra/services/settings_agent.py, the
     Anthropic SDK with tools dispatched in-process.
  2. Sonic, "cli" transport — spectra/services/settings_agent_cli.py, the
     real `claude` CLI in -p mode with the settings MCP server. THIS is
     what his live instance runs. The key goes into the subprocess
     environment as ANTHROPIC_API_KEY; Claude Code's own auth precedence
     puts an API key ahead of any subscription credential, and that module
     additionally strips every subscription credential out of the child's
     environment, so the subprocess has nothing else it could bill.
  3. The lyric readings, the sung labels and Claude's colour meanings —
     spectra/services/claude_text.py, which carries both transports for
     the same reason Sonic does and gets the same key from here.

The Jukebox calls Claude only THROUGH Sonic (spectra/services/
jukebox_console.py is a Sonic domain — declared operations, no model
client of its own), so it is covered by 1 and 2 and needs no credential
of its own. Nothing else in `services/jukebox/` imports anthropic or
spawns a `claude`.

WHERE THE KEY ACTUALLY COMES FROM is config.settings_agent_api_key() —
ANTHROPIC_API_KEY in the environment if set, else the contents of
config.anthropic_api_key_file() (~/.config/anthropic/api-key on his
machine, mode 600), read fresh on every call. This module owns the three
things that must not be re-written per feature:

  * `read()`     — the key, or "" (never raises, never logs it).
  * `missing_reason()` — the ONE plain-language sentence a user sees when
    there is no key, so Sonic's error path, claude_text.availability() and
    the lyric pages all say the same thing.
  * `redact()`   — scrubs the key out of any text before it can reach an
    exception message, a log line, a status line or the JSON the web app
    gets. The `claude` CLI's stderr is the one place a credential could
    plausibly be echoed back at us, and settings_agent_cli.py /
    claude_text.py both pass their stderr through here.

NO FALLBACK, BY CONSTRUCTION. There is no second credential left in this
codebase to fall back TO: config.settings_agent_cli_oauth_token() is
deleted, settings_agent_cli._subprocess_env() pops
CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_AUTH_TOKEN out of the child
environment, and CLAUDE_CONFIG_DIR still points at an isolated directory
so an interactive `/login` session on this host can never be picked up.
A missing key is a stated refusal before any model call is attempted; a
rejected key is the API's or the CLI's own error, surfaced verbatim
(redacted), never retried against something else.
"""
from __future__ import annotations

import os
import re

from spectra import config

# What a missing key looks like to a human, in ONE place. Names
# ANTHROPIC_API_KEY (the env route a service unit's EnvironmentFile would
# use) AND the file, because either one is a legitimate answer and a
# half-named cause is what sends someone looking in the wrong place. The
# PATH is not a secret; the key is, and never appears here.
_MISSING = ("no Claude API key configured — set ANTHROPIC_API_KEY for the "
            "service or put the key in {path} (mode 600). Nothing is billed "
            "to a Claude subscription any more, so there is nothing to fall "
            "back to.")

# A belt-and-braces net for a key that reached us from somewhere this
# process does not control (a CLI echo, a pasted log) and therefore is not
# necessarily byte-identical to the configured one.
_KEY_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}")


def read() -> str:
    """His API key, or "" when none is configured. Never raises, never
    logs. Callers turn "" into their own feature's stated refusal using
    missing_reason() — see Sonic's SettingsAgentUnavailable and
    claude_text's ClaudeUnavailable."""
    return config.settings_agent_api_key()


def missing_reason() -> str:
    """The one sentence shown when there is no key. Safe for a 503 body, a
    status line and a log — it carries the file PATH, never the key."""
    return _MISSING.format(path=config.anthropic_api_key_file())


def source() -> str | None:
    """"env", "file" or None — WHICH route supplied the key, for an
    availability/status surface that wants to say where to go and fix it.
    Never the key itself, and never its length or prefix."""
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "env"
    return "file" if read() else None


def status() -> dict:
    """{"available", "reason", "source", "key_file"} — everything a status
    surface needs and nothing it must not have. `reason` is None when a key
    is configured; it is missing_reason() otherwise."""
    key = read()
    return {
        "available": bool(key),
        "reason": None if key else missing_reason(),
        "source": source(),
        "key_file": str(config.anthropic_api_key_file()),
    }


def redact(text: str) -> str:
    """`text` with the configured key — and anything else shaped like an
    Anthropic key — replaced by a marker. Applied to subprocess stderr
    before it is put in an exception or a log line: a `claude` CLI that
    ever echoes its own credential (today's 2.1.x does not, but a future
    one deciding to is exactly the kind of thing nobody notices until the
    key is in a journal) must not be able to leak it through us."""
    if not text:
        return text
    key = read()
    if key and key in text:
        text = text.replace(key, "[redacted]")
    return _KEY_SHAPE.sub("[redacted]", text)
