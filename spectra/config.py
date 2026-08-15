"""SPECTRA paths + the one external endpoint (LedFX HTTP, pre-S3 fires).

SPECTRA owns storage/spectra/; everything else it reads (colour sets,
librosa profiles) is spot-effects storage, READ-ONLY by the bridge contract.
Module-level paths so executable specs can repoint them at temp dirs.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# SPECTRA_STORAGE_DIR: executable specs and rehearsals repoint the standalone
# process (python -m spectra) at a temp dir. Production leaves it unset —
# both worlds must see the same storage/spectra (the ownership record in
# fx/light_ownership.py has its own path constant and is NOT moved by this).
SPECTRA_STORAGE = Path(os.getenv("SPECTRA_STORAGE_DIR")
                       or REPO_ROOT / "storage" / "spectra")
SCENES_FILE = SPECTRA_STORAGE / "scenes.json"
SEQUENCER_FILE = SPECTRA_STORAGE / "sequencer.json"
DRIFT_PROFILES_FILE = SPECTRA_STORAGE / "drift_profiles.json"
ROOM_COLOR_FILE = SPECTRA_STORAGE / "room_color.json"
ROOM_CONTROLS_FILE = SPECTRA_STORAGE / "room_controls.json"
TRIGGERS_FILE = SPECTRA_STORAGE / "triggers.json"
FIRE_HISTORY_FILE = SPECTRA_STORAGE / "fire_history.json"
SHOW_LOG_FILE = SPECTRA_STORAGE / "show_log.json"
FEEDBACK_FILE = SPECTRA_STORAGE / "feedback.json"
SETTINGS_LOG_FILE = SPECTRA_STORAGE / "settings_log.json"

# S3: SPECTRA's OWN fx config dir for the live device layer (seeded from the
# live LedFX config by scripts/seed_spectra_fx_live.py — never ~/.ledfx).
# The ownership record itself lives in fx/light_ownership.py (shared library:
# both worlds read one implementation).
FX_LIVE_CONFIG_DIR = SPECTRA_STORAGE / "fx-live"


def handover_armed() -> bool:
    """The safety latch on the handover API: run_handover is refused unless
    the operator exports SPECTRA_HANDOVER_ARMED=1 for the process (see
    docs/SPECTRA_HANDOVER.md). The machinery is complete; ARMING it is the
    owner's word, deliberately outside any config file an agent might edit."""
    return os.getenv("SPECTRA_HANDOVER_ARMED", "") == "1"


def settings_agent_api_key() -> str:
    """API key for the settings-console agent (spectra/services/
    settings_agent.py) — a small Sonnet-class model whose only tool is a
    validated setting write (spectra/services/settings_console.py). Not a
    settings.py field: same posture as handover_armed(), a credential
    belongs in the environment, not a file an agent's own writes could
    touch."""
    return os.getenv("ANTHROPIC_API_KEY", "")


def settings_agent_model() -> str:
    return os.getenv("SPECTRA_SETTINGS_AGENT_MODEL", "claude-sonnet-5")


def settings_agent_backend() -> str:
    """"api" (default) or "cli" -- which settings_agent* module
    spectra/api/settings_console.py's POST /message dispatches to. MUST
    default to "api": the captain's ruling (data/spectra-console-
    subscription-backend/) is that a subscription-authenticated CLI
    backend may be built ready-to-enable but never enables itself. Flipping
    this to "cli" is inert on its own -- see settings_agent_cli_oauth_token()."""
    return os.getenv("SPECTRA_SETTINGS_AGENT_BACKEND", "api")


def settings_agent_cli_oauth_token() -> str:
    """CLAUDE_CODE_OAUTH_TOKEN for the "cli" settings-agent backend
    (spectra/services/settings_agent_cli.py) -- Anthropic's own env var
    name for a long-lived token from `claude setup-token`
    (code.claude.com/docs/en/authentication#generate-a-long-lived-token),
    which bills to the subscription that minted it, not API credits. Same
    posture as settings_agent_api_key(): a credential belongs in the
    environment, never a file this repo's own agent could write. Nothing
    in this codebase ever runs `claude setup-token` or reads an existing
    interactive `/login` session on its own -- minting a token is a
    deliberate, human, browser-based act, and the captain has not
    authorised pointing this at his real account yet."""
    return os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")


def settings_agent_cli_binary() -> str:
    return os.getenv("SPECTRA_SETTINGS_AGENT_CLI_PATH", "claude")


def settings_agent_cli_workdir() -> Path:
    """A dedicated, empty, code-owned working directory for the settings-
    agent CLI subprocess (spectra/services/settings_agent_cli.py) --
    never the repo root or any directory that might carry a stray
    .claude/settings.json, .mcp.json, or CLAUDE.md. Bare mode (which
    would skip all of that) can't be used here because it also refuses to
    read CLAUDE_CODE_OAUTH_TOKEN, so this directory's cleanliness is the
    actual safety boundary against `claude -p` auto-running a hook or
    auto-connecting a stray MCP server it happens to find -- see
    settings_agent_cli.py's module docstring."""
    return SPECTRA_STORAGE / "settings-agent-cli-workdir"


def whisper_bridge_url() -> str:
    """Base URL (scheme://host:port) of the local-Whisper bridge
    spectra/services/transcription.py's transcribe() POSTs to. Verified
    address (2026-08-15): http://127.0.0.1:8090 — the bridge's own compose
    file defaults its STT_BRIDGE_PORT to 8090, so this default mirrors
    theirs rather than inventing a separate number. Still a configured
    value, not a literal buried in transcribe() — override with
    SPECTRA_WHISPER_BRIDGE_URL if the bridge ever moves.

    LOOPBACK ASSUMPTION, written down rather than left silent: 127.0.0.1
    only reaches the bridge because spectra.service runs as a plain
    systemd user unit directly on the same host the bridge publishes 8090
    on — no container boundary between them today. If SPECTRA is ever
    containerised, loopback stops resolving to the bridge and this needs
    the host's real address (or a shared network) — that failure would be
    silent (connection refused, indistinguishable from "bridge not
    started") unless whoever does the containerising reads this."""
    return os.getenv("SPECTRA_WHISPER_BRIDGE_URL") or "http://127.0.0.1:8090"

# Read-only spot-effects storage (S2 formalizes this as the bridge).
COLOR_SETS_FILE = REPO_ROOT / "storage" / "color_sets.json"
PROFILES_DIR = REPO_ROOT / "storage" / "profiles"
AUDIO_SHAPES_DIR = REPO_ROOT / "storage" / "audio_shapes"
TRAINING_PROFILES_FILE = REPO_ROOT / "storage" / "training_profiles.json"

WEB_DIST = Path(__file__).parent / "web" / "dist"


def ledfx_url() -> str:
    """Base URL of the external LedFX service (the owner's real-fire path
    until S3 hands SPECTRA the lights through the fx/ library)."""
    url = os.getenv("SPECTRA_LEDFX_URL") or os.getenv("LEDFX_BASE_URL") or ""
    if url:
        return url.rstrip("/")
    host = os.getenv("LEDFX_HOST", "127.0.0.1")
    port = os.getenv("LEDFX_PORT", "8888")
    return f"http://{host}:{port}"
