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

# Read-only spot-effects storage (S2 formalizes this as the bridge).
COLOR_SETS_FILE = REPO_ROOT / "storage" / "color_sets.json"
PROFILES_DIR = REPO_ROOT / "storage" / "profiles"

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
