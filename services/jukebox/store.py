"""
SpotFX — the Jukebox's two stores (models/jukebox.py says what each holds).

Every write is tmp + os.replace, so a reader (or a crash) only ever sees a
whole file. Every read tolerates a missing or unreadable file by returning
the defaults — a corrupt night file must never stop his program settings
from loading. Paths are module attributes so a test repoints them
(tests/conftest.py's `_isolated_jukebox_stores`).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

from config import BASE_DIR
from models.jukebox import JukeboxNight, JukeboxNights, ProgramConfig, ShowConfig

logger = logging.getLogger(__name__)

CONFIG_FILE = BASE_DIR / "storage" / "jukebox.json"
NIGHT_FILE = BASE_DIR / "storage" / "jukebox_night.json"
SHOW_FILE = BASE_DIR / "storage" / "jukebox_show.json"

HISTORY_MAX = 20       # earlier nights kept (as briefs) beside the current one
LOG_MAX = 300          # the night's own log lines
PLAYED_MAX = 400       # the night's played list
LINE_MAX = 400         # the line, finished entries included

_lock = threading.Lock()


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Jukebox: unreadable %s (%s) — using defaults", path.name, exc)
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── his program settings ─────────────────────────────────────────────────────

def load_config() -> ProgramConfig:
    raw = _read(CONFIG_FILE)
    if not isinstance(raw, dict):
        return ProgramConfig()
    try:
        return ProgramConfig.model_validate(raw)
    except Exception as exc:
        logger.warning("Jukebox: program settings invalid (%s) — using defaults", exc)
        return ProgramConfig()


def save_config(cfg: ProgramConfig) -> None:
    with _lock:
        _write(CONFIG_FILE, cfg.model_dump(mode="json"))


# ── the show settings (presets, approval, the economy) ──────────────────────

def load_show() -> ShowConfig:
    raw = _read(SHOW_FILE)
    if not isinstance(raw, dict):
        return ShowConfig()
    try:
        return ShowConfig.model_validate(raw)
    except Exception as exc:
        logger.warning("Jukebox: show settings invalid (%s) — using defaults", exc)
        return ShowConfig()


def save_show(show: ShowConfig) -> None:
    with _lock:
        _write(SHOW_FILE, show.model_dump(mode="json"))


# ── nights ───────────────────────────────────────────────────────────────────

def bound(night: JukeboxNight) -> JukeboxNight:
    """Trim the night's growing lists to their bounds, oldest first. Line
    entries still in play (queued, committed, playing) are never dropped."""
    if len(night.log) > LOG_MAX:
        night.log = night.log[-LOG_MAX:]
    if len(night.played) > PLAYED_MAX:
        night.played = night.played[-PLAYED_MAX:]
    if len(night.line) > LINE_MAX:
        live = {"queued", "committed", "playing"}
        done = [e for e in night.line if e.state not in live]
        drop = len(night.line) - LINE_MAX
        gone = {id(e) for e in done[:drop]}
        night.line = [e for e in night.line if id(e) not in gone]
    return night


def load_nights() -> JukeboxNights:
    raw = _read(NIGHT_FILE)
    if not isinstance(raw, dict):
        return JukeboxNights()
    try:
        return JukeboxNights.model_validate(raw)
    except Exception as exc:
        logger.warning("Jukebox: night file invalid (%s) — starting empty", exc)
        return JukeboxNights()


def save_night_dict(night: Optional[dict], history: list[dict]) -> None:
    """Write the current night (a model_dump) and the history briefs."""
    with _lock:
        _write(NIGHT_FILE, {"night": night, "history": history[:HISTORY_MAX]})
