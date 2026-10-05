"""House lighting's two stores (spectra/models/house_mode.py says why two).

Both are atomic tmp+replace writes. The STATE lives in memory as the source
of truth for the running process and is written through on every change; it
is read from disk once (lazily per storage path) so a restart keeps the mode
he was in. The LIBRARY is read fresh on every call — small, and it only ever
changes on his edit.

NAMES AND ALIASES ARE UNIQUE ignoring case: he, Sonic and Home Assistant all
refer to a mode by a word, and one word must mean one mode.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Optional

from spectra import config
from spectra.models.house_mode import HouseLibrary, HouseMode, HouseState, now_ms

logger = logging.getLogger(__name__)

_state: Optional[HouseState] = None
_state_path: Optional[str] = None
_lock = threading.RLock()


class ModeConflict(ValueError):
    """A name or Home Assistant alias already belongs to another mode."""


def _write_json(path, data: dict) -> None:
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".house", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path) -> Optional[dict]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                    # noqa: BLE001
        logger.exception("house: unreadable store %s", path)
        return None


# ── library ────────────────────────────────────────────────────────────────

def load_library() -> HouseLibrary:
    raw = _read_json(config.HOUSE_MODES_FILE)
    if not raw:
        return HouseLibrary()
    try:
        return HouseLibrary(**raw)
    except Exception:                                    # noqa: BLE001
        logger.exception("house: mode library did not validate")
        return HouseLibrary()


def save_library(lib: HouseLibrary) -> None:
    _write_json(config.HOUSE_MODES_FILE, lib.model_dump())


def list_modes() -> list[HouseMode]:
    return list(load_library().modes)


def get_mode(mode_id: Optional[str]) -> Optional[HouseMode]:
    if not mode_id:
        return None
    return next((m for m in load_library().modes if m.id == mode_id), None)


def find_mode(name_or_id: str) -> Optional[HouseMode]:
    """By id, then by exact name ignoring case."""
    modes = load_library().modes
    hit = next((m for m in modes if m.id == name_or_id), None)
    if hit is not None:
        return hit
    low = (name_or_id or "").strip().lower()
    return next((m for m in modes if m.name.strip().lower() == low), None)


def mode_for_ha(ha_value: str) -> Optional[HouseMode]:
    """The mode answering to a Home Assistant lighting_mode value. An exact
    alias wins; failing that, a mode NAMED exactly that value (so a mode
    called "Evening" answers to "Evening" without repeating it)."""
    modes = load_library().modes
    hit = next((m for m in modes if m.answers_to(ha_value)), None)
    if hit is not None:
        return hit
    low = (ha_value or "").strip().lower()
    return next((m for m in modes if low and m.name.strip().lower() == low), None)


def put_mode(new: HouseMode) -> HouseMode:
    with _lock:
        lib = load_library()
        low = new.name.strip().lower()
        for m in lib.modes:
            if m.id == new.id:
                continue
            if m.name.strip().lower() == low:
                raise ModeConflict(f"a mode called {m.name!r} already exists")
            taken = {a.lower() for a in m.ha_aliases} | {m.name.strip().lower()}
            for alias in new.ha_aliases:
                if alias.lower() in taken:
                    raise ModeConflict(
                        f"Home Assistant's {alias!r} already belongs to {m.name!r}")
        existing = next((i for i, m in enumerate(lib.modes) if m.id == new.id), None)
        new = new.model_copy(update={"updated_ms": now_ms()})
        if existing is None:
            lib.modes.append(new)
        else:
            new = new.model_copy(update={"created_ms": lib.modes[existing].created_ms})
            lib.modes[existing] = new
        save_library(lib)
        return new


def delete_mode(mode_id: str) -> bool:
    with _lock:
        lib = load_library()
        kept = [m for m in lib.modes if m.id != mode_id]
        if len(kept) == len(lib.modes):
            return False
        lib.modes = kept
        save_library(lib)
        return True


# ── runtime state ──────────────────────────────────────────────────────────

def state() -> HouseState:
    global _state, _state_path
    with _lock:
        path = str(config.HOUSE_STATE_FILE)
        if _state is None or _state_path != path:
            raw = _read_json(path)
            try:
                _state = HouseState(**raw) if raw else HouseState()
            except Exception:                            # noqa: BLE001
                logger.exception("house: state did not validate; starting empty")
                _state = HouseState()
            _state_path = path
        return _state


def save_state() -> None:
    with _lock:
        st = state()
        try:
            _write_json(config.HOUSE_STATE_FILE, st.model_dump())
        except Exception:                                # noqa: BLE001
            logger.exception("house: could not persist runtime state")


def reset_memory() -> None:
    """Tests; a storage repoint."""
    global _state, _state_path
    with _lock:
        _state = None
        _state_path = None
