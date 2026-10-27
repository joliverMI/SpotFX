"""
The guest app's KEY: the one secret the guest app (this package, on :8020)
shows SpotFX (:8000) on every call it forwards, so SpotFX's guest routes
(routers/jukebox_guest_router.py) answer the guest app and nobody else —
:8000 is reachable on the LAN, and a guest route names a phone.

One file, `storage/jukebox_guest_key`, mode 0600, made by whichever side
needs it first (O_EXCL, so two starts at once agree on one key). Standard
library only: the guest app imports nothing of SpotFX's.
"""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from typing import Optional

HEADER = "X-Jukebox-Guest-Key"
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "storage" / "jukebox_guest_key"


def load_or_create(path: Path = DEFAULT_FILE) -> str:
    try:
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    return key


def matches(given: Optional[str], key: str) -> bool:
    return bool(key) and isinstance(given, str) and hmac.compare_digest(given, key)
