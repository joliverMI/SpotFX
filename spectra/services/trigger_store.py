"""SPECTRA trigger CRUD store: storage/spectra/triggers.json, keyed by
spotify_uri → list of SpectraTrigger. Same atomic-write discipline as
scene_store.py. Per-trigger operations (not whole-song replace) so the
authoring surface's place/move/edit/delete gestures each land one write —
matching the legacy Builder's per-trigger feel without its whole-profile
save.

WRITERS ARE SERIALISED BY `write_lock`. Every mutation here is a full
load -> edit -> save of one file, and the writers no longer share one
thread: spectra/api/triggers.py's POST/DELETE run on the event loop,
midsong_generator.generate_for_song and testbed_promote.promote run under
asyncio.to_thread, and a file read releases the GIL. Two unserialised
read-modify-writes interleaving lose whichever landed first — a
hand-placed trigger silently vanishing from the corpus. upsert/delete/
apply_batch each hold the lock across their own load+save; a caller whose
correctness depends on a READ staying true until its WRITE (a
check-then-act, e.g. the promotion duplicate guard) holds `write_lock`
itself around both — it is re-entrant, so the nested upsert is fine. Plain
reads are deliberately not serialised.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Optional

from spectra import config
from spectra.models.trigger import SpectraTrigger

logger = logging.getLogger(__name__)

write_lock = threading.RLock()


class InvalidTriggerAction(ValueError):
    """A trigger's action references a scene/colour-set/scene-pool member
    that doesn't exist in SPECTRA's own stores. Raised by validate_action,
    the ONE validator spectra/api/triggers.py's human-authoring POST and
    spectra/services/testbed_promote.py's push-to-real gate both call —
    two write surfaces, one reference check, so a promoted mark can never
    reach storage under a laxer rule than a hand-typed one."""


def validate_action(action) -> None:
    # Imported here (not at module top) to avoid a service->service import
    # cycle at load time: scene_store/color_sets both live in
    # spectra/services/ alongside this module.
    from spectra.services import color_sets, scene_store

    if action.kind == "fire_scene":
        if action.scene_id is not None and scene_store.get_by_id(action.scene_id) is None:
            raise InvalidTriggerAction(f"scene '{action.scene_id}' not found")
        if action.color_set_id and color_sets.get_by_id(action.color_set_id) is None:
            raise InvalidTriggerAction(f"colour set '{action.color_set_id}' not found")
        for member in action.scene_pool or []:
            if scene_store.get_by_id(member.scene_id) is None:
                raise InvalidTriggerAction(
                    f"scene_pool scene '{member.scene_id}' not found")
    elif action.kind == "select_color_set":
        if color_sets.get_by_id(action.set_id) is None:
            raise InvalidTriggerAction(f"colour set '{action.set_id}' not found")


def _load_raw() -> dict:
    if config.TRIGGERS_FILE.exists():
        try:
            return json.loads(config.TRIGGERS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("spectra triggers.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    path = config.TRIGGERS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
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


def _parse_rows(uri: str, rows: list[dict]) -> list[SpectraTrigger]:
    out: list[SpectraTrigger] = []
    for v in rows:
        try:
            out.append(SpectraTrigger(**v))
        except Exception as exc:
            logger.warning("trigger %s (song %s) skipped: %s",
                           v.get("id"), uri, exc)
    return sorted(out, key=lambda t: t.timestamp_ms)


def list_for_song(uri: str) -> list[SpectraTrigger]:
    return _parse_rows(uri, _load_raw().get(uri, []))


def list_all() -> dict[str, list[SpectraTrigger]]:
    """Every song's triggers from ONE read of triggers.json — the read
    shape a whole-corpus listing needs (spectra/services/testbed_marks.py's
    song list). list_for_song() is deliberately per-song (one lookup, one
    read), but it re-reads and re-parses the entire ~9.5MB file every call;
    looping it over every stored URI costs a full parse per song, on the
    live process's event loop when called from a handler. Songs whose row
    list is empty are omitted, matching the store's own delete() rule that
    an emptied song is dropped from the file."""
    raw = _load_raw()
    return {uri: _parse_rows(uri, rows) for uri, rows in raw.items() if rows}


def upsert(uri: str, trigger: SpectraTrigger) -> None:
    """Add or replace by id."""
    with write_lock:
        data = _load_raw()
        song = data.setdefault(uri, [])
        song[:] = [t for t in song if t.get("id") != trigger.id]
        song.append(json.loads(trigger.model_dump_json()))
        _save_raw(data)
    logger.info("Saved SPECTRA trigger %s for %s @ %dms (%s)",
                trigger.id, uri, trigger.timestamp_ms, trigger.action.kind)


def delete(uri: str, trigger_id: str) -> bool:
    with write_lock:
        data = _load_raw()
        song = data.get(uri)
        if song is None:
            return False
        before = len(song)
        song[:] = [t for t in song if t.get("id") != trigger_id]
        if len(song) == before:
            return False
        if not song:
            del data[uri]
        _save_raw(data)
    return True


def get(uri: str, trigger_id: str) -> Optional[SpectraTrigger]:
    for t in list_for_song(uri):
        if t.id == trigger_id:
            return t
    return None


def apply_batch(uri: str, upserts: list[SpectraTrigger],
                delete_ids: list[str]) -> tuple[int, int]:
    """ONE read + ONE write for a whole song's worth of changes — the write
    shape the profile->fired sync needs (spectra/services/
    profile_trigger_sync.py).

    upsert() is deliberately per-trigger (one human gesture, one write), but
    it re-reads and re-writes the entire ~9.5MB triggers.json every call
    (~126ms against his real corpus). Looping it over a profile save's worth
    of triggers would cost seconds and, on the live process, block the event
    loop for the whole run — see AGENTS.md's own note on this. This function
    is that loop collapsed into a single load/save pair.

    Deletes are applied BEFORE upserts, so an id appearing in both lists ends
    up written, not removed. Returns (written, deleted) — the deleted count
    is ids actually present, not ids asked for."""
    with write_lock:
        data = _load_raw()
        song = data.get(uri, [])
        dead = set(delete_ids)
        before = len(song)
        song = [t for t in song if t.get("id") not in dead]
        deleted = before - len(song)

        replacing = {t.id for t in upserts}
        song = [t for t in song if t.get("id") not in replacing]
        song.extend(json.loads(t.model_dump_json()) for t in upserts)

        if song:
            data[uri] = song
        else:
            data.pop(uri, None)
        _save_raw(data)
    logger.info("Batch trigger write for %s: %d written, %d deleted",
                uri, len(upserts), deleted)
    return len(upserts), deleted
