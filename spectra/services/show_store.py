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
                                       LightShowState, PlaylistLibrary,
                                       SequenceLibrary, ShowPlaylist,
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
        # A set may not call itself, directly or through other sets
        # (spectra/services/show_refs.py is the binding statement).
        from spectra.services import show_refs
        cycle = show_refs.find_cycle(new.id, new.actions, lib.sets)
        if cycle is not None:
            raise show_refs.SetReferenceCycle(
                show_refs.cycle_sentence(cycle, lib.sets, {new.id: new.name}))
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


# ── Show Playlists (spectra/services/show_playlists.py follows them) ─────

class PlaylistConflict(ValueError):
    """A name already taken, or a Spotify context already answered to by
    another program (one context, one program — the Set List rule)."""


def load_playlists() -> PlaylistLibrary:
    raw = _read_json(config.LIGHT_SHOW_PLAYLISTS_FILE)
    if not raw:
        return PlaylistLibrary()
    try:
        return PlaylistLibrary(**raw)
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: playlist library did not validate")
        return PlaylistLibrary()


def save_playlists(lib: PlaylistLibrary) -> None:
    _write_json(config.LIGHT_SHOW_PLAYLISTS_FILE, lib.model_dump())


def list_playlists() -> list[ShowPlaylist]:
    return list(load_playlists().playlists)


def get_playlist(pl_id: str) -> Optional[ShowPlaylist]:
    return next((p for p in load_playlists().playlists if p.id == pl_id), None)


def find_playlist(name_or_id: str) -> Optional[ShowPlaylist]:
    """By id, then by exact name ignoring case."""
    pls = load_playlists().playlists
    hit = next((p for p in pls if p.id == name_or_id), None)
    if hit is not None:
        return hit
    low = (name_or_id or "").strip().lower()
    return next((p for p in pls if p.name.strip().lower() == low), None)


def playlist_for_context(context_uri: Optional[str]) -> Optional[ShowPlaylist]:
    if not context_uri:
        return None
    return next((p for p in load_playlists().playlists if context_uri in p.contexts), None)


def put_playlist(new: ShowPlaylist, *, after_id: Optional[str] = None) -> ShowPlaylist:
    """Create or update. Names are unique ignoring case, and a Spotify
    context may belong to only one program; either clash is refused by
    name rather than silently taking it from the other program."""
    with _lock:
        lib = load_playlists()
        low = new.name.strip().lower()
        if not low:
            raise PlaylistConflict("a playlist program needs a name")
        clash = next((p for p in lib.playlists if p.id != new.id
                      and p.name.strip().lower() == low), None)
        if clash is not None:
            raise PlaylistConflict(f"a playlist program called {clash.name!r} already exists")
        contexts = []
        for c in new.contexts:
            c = (c or "").strip()
            if c and c not in contexts:
                contexts.append(c)
        for c in contexts:
            owner = next((p for p in lib.playlists if p.id != new.id and c in p.contexts), None)
            if owner is not None:
                name = new.context_names.get(c) or c
                raise PlaylistConflict(
                    f"{name} already belongs to the program {owner.name!r} — "
                    "one Spotify playlist can drive only one program")
        new = new.model_copy(update={"contexts": contexts, "updated_ms": now_ms()})
        existing = next((i for i, p in enumerate(lib.playlists) if p.id == new.id), None)
        if existing is None:
            after = next((i for i, p in enumerate(lib.playlists) if p.id == after_id), None) \
                if after_id else None
            if after is None:
                lib.playlists.append(new)
            else:
                lib.playlists.insert(after + 1, new)
        else:
            new = new.model_copy(update={"created_ms": lib.playlists[existing].created_ms})
            lib.playlists[existing] = new
        save_playlists(lib)
        return new


def duplicate_playlist(pl_id: str) -> Optional[ShowPlaylist]:
    """An independent deep copy named "<name> copy" (uniqued), every song
    and step given a fresh id, placed right after the original. The copy
    answers to NO Spotify context (a context belongs to one program), so
    it never starts following on its own until he gives it one."""
    from spectra.models.light_show import _id
    with _lock:
        lib = load_playlists()
        src = next((p for p in lib.playlists if p.id == pl_id), None)
        if src is None:
            return None
        taken = {p.name.strip().lower() for p in lib.playlists}
        name = f"{src.name} copy"
        n = 2
        while name.strip().lower() in taken:
            name = f"{src.name} copy {n}"
            n += 1
        data = src.model_dump()

        def fresh(obj):
            if isinstance(obj, dict):
                return {k: (_id() if k == "id" else fresh(v)) for k, v in obj.items()}
            if isinstance(obj, list):
                return [fresh(v) for v in obj]
            return obj
        data = fresh(data)
        data.update({"name": name, "contexts": [], "context_names": {}})
        data.pop("created_ms", None)
        data.pop("updated_ms", None)
        return put_playlist(ShowPlaylist(**data), after_id=src.id)


def delete_playlist(pl_id: str) -> bool:
    with _lock:
        lib = load_playlists()
        kept = [p for p in lib.playlists if p.id != pl_id]
        if len(kept) == len(lib.playlists):
            return False
        lib.playlists = kept
        save_playlists(lib)
        return True


def set_follow_enabled(on: bool) -> bool:
    with _lock:
        lib = load_playlists()
        lib.follow_enabled = bool(on)
        save_playlists(lib)
        return lib.follow_enabled


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
