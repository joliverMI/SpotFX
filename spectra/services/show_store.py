"""The Light Show's two stores (spectra/models/light_show.py says why two).

Both are atomic tmp+replace writes. The STATE is kept in memory as the
source of truth for the running process and written through on every
change; it is read from disk once (lazily) so a restart picks up the holds
and baselines it left behind. The LIBRARY is read fresh on every call — it
is small and only ever changes on his edit.

Names are his and unique ignoring case, because he (and later Sonic) refers
to a set by name.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Optional

from spectra import config
from spectra.models.light_show import (ActionSet, LightShowLibrary,
                                       LightShowState, now_ms)

logger = logging.getLogger(__name__)

_state: Optional[LightShowState] = None
_state_path = None
_lock = threading.RLock()


class SetNameTaken(ValueError):
    pass


def _write_json(path, data: dict) -> None:
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".light_show", suffix=".tmp")
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
        logger.exception("light show: unreadable store %s", path)
        return None


# ── library ────────────────────────────────────────────────────────────────

def load_library() -> LightShowLibrary:
    raw = _read_json(config.LIGHT_SHOW_SETS_FILE)
    if not raw:
        return LightShowLibrary()
    try:
        return LightShowLibrary(**raw)
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: library did not validate")
        return LightShowLibrary()


def save_library(lib: LightShowLibrary) -> None:
    _write_json(config.LIGHT_SHOW_SETS_FILE, lib.model_dump())


def list_sets() -> list[ActionSet]:
    return list(load_library().sets)


def get_set(set_id: str) -> Optional[ActionSet]:
    return next((s for s in load_library().sets if s.id == set_id), None)


def find_set(name_or_id: str) -> Optional[ActionSet]:
    """By id, then by exact name ignoring case."""
    sets = load_library().sets
    hit = next((s for s in sets if s.id == name_or_id), None)
    if hit is not None:
        return hit
    low = (name_or_id or "").strip().lower()
    return next((s for s in sets if s.name.strip().lower() == low), None)


def put_set(new: ActionSet) -> ActionSet:
    with _lock:
        lib = load_library()
        low = new.name.strip().lower()
        if not low:
            raise SetNameTaken("a set needs a name")
        clash = next((s for s in lib.sets if s.id != new.id
                      and s.name.strip().lower() == low), None)
        if clash is not None:
            raise SetNameTaken(f"a set called {clash.name!r} already exists")
        existing = next((i for i, s in enumerate(lib.sets) if s.id == new.id), None)
        new = new.model_copy(update={"updated_ms": now_ms()})
        if existing is None:
            lib.sets.append(new)
        else:
            new = new.model_copy(update={"created_ms": lib.sets[existing].created_ms})
            lib.sets[existing] = new
        save_library(lib)
        return new


def delete_set(set_id: str) -> bool:
    with _lock:
        lib = load_library()
        kept = [s for s in lib.sets if s.id != set_id]
        if len(kept) == len(lib.sets):
            return False
        lib.sets = kept
        save_library(lib)
        return True


# ── runtime state ──────────────────────────────────────────────────────────

def state() -> LightShowState:
    """The in-memory runtime state, loaded once per storage path."""
    global _state, _state_path
    with _lock:
        path = str(config.LIGHT_SHOW_STATE_FILE)
        if _state is None or _state_path != path:
            raw = _read_json(path)
            try:
                _state = LightShowState(**raw) if raw else LightShowState()
            except Exception:                            # noqa: BLE001
                logger.exception("light show: state did not validate; "
                                 "starting empty")
                _state = LightShowState()
            _state_path = path
        return _state


def save_state() -> None:
    with _lock:
        st = state()
        try:
            _write_json(config.LIGHT_SHOW_STATE_FILE, st.model_dump())
        except Exception:                                # noqa: BLE001
            logger.exception("light show: could not persist runtime state")


def reset_memory() -> None:
    """Forget the in-memory copy (tests; a storage repoint)."""
    global _state, _state_path
    with _lock:
        _state = None
        _state_path = None
