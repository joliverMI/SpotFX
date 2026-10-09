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
                                       LightShowState, SequenceLibrary,
                                       ShowSequence, now_ms)

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


def put_set(new: ActionSet, *, after_id: Optional[str] = None) -> ActionSet:
    """`after_id` places a brand-new set right after that id in his list
    (the Admiral, 2026-10-08: "Duplicate" puts the copy right after the
    original, not at the end) — ignored for an update of an existing set,
    whose position is untouched. An unresolvable `after_id` falls back to
    appending, same as today's plain "+New"."""
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
            after = next((i for i, s in enumerate(lib.sets) if s.id == after_id), None) \
                if after_id else None
            if after is None:
                lib.sets.append(new)
            else:
                lib.sets.insert(after + 1, new)
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


# ── Show Sequences (spectra/services/show_sequence.py runs them) ──────────

class SequenceNameTaken(ValueError):
    pass


def load_sequences() -> SequenceLibrary:
    raw = _read_json(config.LIGHT_SHOW_SEQUENCES_FILE)
    if not raw:
        return SequenceLibrary()
    try:
        return SequenceLibrary(**raw)
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: sequence library did not validate")
        return SequenceLibrary()


def save_sequences(lib: SequenceLibrary) -> None:
    _write_json(config.LIGHT_SHOW_SEQUENCES_FILE, lib.model_dump())


def list_sequences() -> list[ShowSequence]:
    return list(load_sequences().sequences)


def get_sequence(seq_id: str) -> Optional[ShowSequence]:
    return next((s for s in load_sequences().sequences if s.id == seq_id), None)


def find_sequence(name_or_id: str) -> Optional[ShowSequence]:
    """By id, then by exact name ignoring case."""
    seqs = load_sequences().sequences
    hit = next((s for s in seqs if s.id == name_or_id), None)
    if hit is not None:
        return hit
    low = (name_or_id or "").strip().lower()
    return next((s for s in seqs if s.name.strip().lower() == low), None)


def put_sequence(new: ShowSequence, *, after_id: Optional[str] = None) -> ShowSequence:
    """Create or update; names are unique ignoring case (he and Sonic refer
    to a sequence by name). `after_id` places a NEW sequence right after
    that one (Duplicate), exactly like `put_set`."""
    with _lock:
        lib = load_sequences()
        low = new.name.strip().lower()
        if not low:
            raise SequenceNameTaken("a sequence needs a name")
        clash = next((s for s in lib.sequences if s.id != new.id
                      and s.name.strip().lower() == low), None)
        if clash is not None:
            raise SequenceNameTaken(f"a sequence called {clash.name!r} already exists")
        existing = next((i for i, s in enumerate(lib.sequences) if s.id == new.id), None)
        new = new.model_copy(update={"updated_ms": now_ms()})
        if existing is None:
            after = next((i for i, s in enumerate(lib.sequences) if s.id == after_id), None) \
                if after_id else None
            if after is None:
                lib.sequences.append(new)
            else:
                lib.sequences.insert(after + 1, new)
        else:
            new = new.model_copy(update={"created_ms": lib.sequences[existing].created_ms})
            lib.sequences[existing] = new
        save_sequences(lib)
        return new


def duplicate_sequence(seq_id: str) -> Optional[ShowSequence]:
    """An independent deep copy named "<name> copy" (uniqued: "copy 2", …),
    every item given a fresh id, placed right after the original."""
    from spectra.models.light_show import SequenceItem, _id
    with _lock:
        lib = load_sequences()
        src = next((s for s in lib.sequences if s.id == seq_id), None)
        if src is None:
            return None
        taken = {s.name.strip().lower() for s in lib.sequences}
        name = f"{src.name} copy"
        n = 2
        while name.strip().lower() in taken:
            name = f"{src.name} copy {n}"
            n += 1
        items = [SequenceItem(**{**it.model_dump(), "id": _id()}) for it in src.items]
        copy = ShowSequence(name=name, items=items, loop=src.loop, notes=src.notes)
        return put_sequence(copy, after_id=src.id)


def delete_sequence(seq_id: str) -> bool:
    with _lock:
        lib = load_sequences()
        kept = [s for s in lib.sequences if s.id != seq_id]
        if len(kept) == len(lib.sequences):
            return False
        lib.sequences = kept
        save_sequences(lib)
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
