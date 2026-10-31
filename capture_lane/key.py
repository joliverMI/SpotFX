"""
The capture lane's KEY: the secret SpotFX shows the lane on every call, so
nothing else on this machine can make the hidden player play. Same shape as
the guest app's key (jukebox_guest/key.py, whose helpers it reuses): one
file, `storage/capture_lane_key`, mode 0600, made by whichever side needs it
first.
"""
from __future__ import annotations

from pathlib import Path

from jukebox_guest.key import load_or_create as _load_or_create
from jukebox_guest.key import matches  # noqa: F401  (re-exported)

HEADER = "X-Capture-Lane-Key"
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "storage" / "capture_lane_key"


def load_or_create(path: Path = DEFAULT_FILE) -> str:
    return _load_or_create(path)
