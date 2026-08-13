"""SPECTRA paths + the one external endpoint (LedFX HTTP, pre-S3 fires).

SPECTRA owns storage/spectra/; everything else it reads (colour sets,
librosa profiles) is spot-effects storage, READ-ONLY by the bridge contract.
Module-level paths so executable specs can repoint them at temp dirs.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

SPECTRA_STORAGE = REPO_ROOT / "storage" / "spectra"
SCENES_FILE = SPECTRA_STORAGE / "scenes.json"
SEQUENCER_FILE = SPECTRA_STORAGE / "sequencer.json"
DRIFT_PROFILES_FILE = SPECTRA_STORAGE / "drift_profiles.json"
ROOM_COLOR_FILE = SPECTRA_STORAGE / "room_color.json"

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
