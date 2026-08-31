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
GRADIENT2D_FILE = SPECTRA_STORAGE / "gradients2d.json"
ROOM_COLOR_FILE = SPECTRA_STORAGE / "room_color.json"
ROOM_CONTROLS_FILE = SPECTRA_STORAGE / "room_controls.json"
TRIGGERS_FILE = SPECTRA_STORAGE / "triggers.json"
# Provenance for the two trigger worlds — which fired-copy triggers came out
# of a storage/profiles/*.json SongProfile, and from which legacy event id.
# See spectra/services/profile_sync_ledger.py for why this is a sidecar and
# not a field on SpectraTrigger.
PROFILE_SYNC_LEDGER_FILE = SPECTRA_STORAGE / "profile_sync_ledger.json"
FIRE_HISTORY_FILE = SPECTRA_STORAGE / "fire_history.json"
SHOW_LOG_FILE = SPECTRA_STORAGE / "show_log.json"
FEEDBACK_FILE = SPECTRA_STORAGE / "feedback.json"
SETTINGS_LOG_FILE = SPECTRA_STORAGE / "settings_log.json"
# Sonic's durable per-call token-usage record (spectra/services/
# sonic_usage.py) — the review page's "how much has Sonic used" figures.
# Real reported usage only, never estimated; see that module's docstring.
SONIC_USAGE_FILE = SPECTRA_STORAGE / "sonic_usage.json"
# Sonic's scene/flare change log (spectra/services/scene_console.py) — kept
# separate from SETTINGS_LOG_FILE so the two domains' audit trails never mix,
# matching scene_console.py never importing settings_console.py.
SCENE_AGENT_LOG_FILE = SPECTRA_STORAGE / "scene_agent_log.json"
# Sonic's backup-before-any-edit mechanism (2026-08-15 widening —
# overwrite_scene/restore_scene_backup/undo_last_scene_change):
# SCENE_BACKUPS_FILE is the bounded per-scene ring (last 10 edits);
# SCENE_GENESIS_FILE is the permanent, never-pruned snapshot of each scene
# as it stood before Sonic ever touched it. See scene_console.py's module
# docstring for why both exist and how they're verified, not just written.
SCENE_BACKUPS_FILE = SPECTRA_STORAGE / "scene_backups.json"
SCENE_GENESIS_FILE = SPECTRA_STORAGE / "scene_genesis.json"
# The device-preview strip's favourites + pause state (spectra/services/
# device_preview.py) — same small-store shape as ROOM_CONTROLS_FILE.
DEVICE_PREVIEW_FILE = SPECTRA_STORAGE / "device_preview.json"

# DEVICE_SETTINGS_FILE is SPECTRA's own per-device record store — settings a
# device carries that the vendored LedFX device config has no place for
# (today: timing_offset_ms, the per-device timing equalization). Same
# small-store shape as ROOM_CONTROLS_FILE; see
# spectra/services/device_settings.py.
DEVICE_SETTINGS_FILE = SPECTRA_STORAGE / "device_settings.json"
INTENSITY_SCALE_CACHE_FILE = SPECTRA_STORAGE / "intensity_scale_features.json"
INTENSITY_SCALE_MARKS_FILE = SPECTRA_STORAGE / "intensity_scale_marks.json"
# Per-virtual pre-dark effect snapshot (spectra/services/dark_light.py) — the
# "what was showing before Dark" record the Light transition replays, since
# clearing dark_lock alone restores nothing (see that module's docstring).
DARK_LIGHT_SNAPSHOT_FILE = SPECTRA_STORAGE / "dark_light_snapshot.json"
# The flare scrubbing-preview's LIVE hold (spectra/services/
# flare_preview_hold.py) — the pre-preview per-virtual snapshot a hold
# restores on close/heartbeat-timeout, persisted so a service restart mid-
# hold can land it back too (that module's own docstring has the mechanism).
FLARE_PREVIEW_HOLD_FILE = SPECTRA_STORAGE / "flare_preview_hold.json"
# The phone audio/visual-offset instrument (spectra/services/av_sync_*.py):
# AV_SYNC_MEASUREMENTS_FILE is the ONLY thing it ever persists — a bounded
# list of finished measurement RECORDS (numbers + the confidence statement),
# never audio, never video, never frames (privacy statement in the help
# topic "av-sync-page" and the av_sync_session.py module docstring).
# AV_SYNC_PATTERN_FILE is the flash-pattern driver's pre-pattern per-virtual
# snapshot, persisted for the same reason FLARE_PREVIEW_HOLD_FILE is: a
# restart mid-pattern must land the lights back, not strand them white.
AV_SYNC_MEASUREMENTS_FILE = SPECTRA_STORAGE / "av_sync_measurements.json"
AV_SYNC_PATTERN_FILE = SPECTRA_STORAGE / "av_sync_pattern.json"

# THE ROOM LIGHT-FIELD MAP (spectra/services/light_field.py) — per-emitter
# measured footprints: WHERE each emitter's light lands and how much, never
# where its LEDs are (spectra/models/room_map.py's docstring is the binding
# statement). Numbers only; no frames, no images, ever.
ROOM_MAPS_FILE = SPECTRA_STORAGE / "room_maps.json"
# The room-effects layer's authored effects (spectra/services/room_effects.py)
# — kind + knobs + which devices they drive. The running gains themselves are
# in-memory only; only the authored spec is durable.
ROOM_EFFECTS_FILE = SPECTRA_STORAGE / "room_effects.json"

# The TESTING IN PROGRESS record (spectra/services/test_session.py): the
# DECLARED half of the room-visibility bar — {actor, reason, since_ms,
# expires_ms}. Durable (not in-memory like preview_pause's own deadline)
# precisely so a SPECTRA restart mid-test cannot silently drop a live
# declaration and leave the bar down while his room is still being driven.
# Expiry is enforced at READ; nothing background prunes this file.
TEST_SESSION_FILE = SPECTRA_STORAGE / "test_session.json"

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


def ledfx_ws_url() -> str:
    """LedFX's own event WebSocket (ledfx/api/websocket.py) — the device
    preview's data source (data/spectra-device-preview-plan/report.md §2).
    Derived from ledfx_url() so both point at the same LedFX process by
    construction; http(s) swaps to ws(s), never a second hand-typed host."""
    base = ledfx_url()
    return ("wss://" + base[len("https://"):] if base.startswith("https://")
            else "ws://" + base[len("http://"):]) + "/api/websocket"
