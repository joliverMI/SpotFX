"""SPECTRA trigger CRUD store: storage/spectra/triggers.json, keyed by
spotify_uri → list of SpectraTrigger. Same atomic-write discipline as
scene_store.py. Per-trigger operations (not whole-song replace) so the
authoring surface's place/move/edit/delete gestures each land one write —
matching the legacy Builder's per-trigger feel without its whole-profile
save.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from spectra import config
from spectra.models.trigger import SpectraTrigger

logger = logging.getLogger(__name__)


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


def list_for_song(uri: str) -> list[SpectraTrigger]:
    raw = _load_raw().get(uri, [])
    out: list[SpectraTrigger] = []
    for v in raw:
        try:
            out.append(SpectraTrigger(**v))
        except Exception as exc:
            logger.warning("trigger %s (song %s) skipped: %s",
                           v.get("id"), uri, exc)
    return sorted(out, key=lambda t: t.timestamp_ms)


def upsert(uri: str, trigger: SpectraTrigger) -> None:
    """Add or replace by id."""
    data = _load_raw()
    song = data.setdefault(uri, [])
    song[:] = [t for t in song if t.get("id") != trigger.id]
    song.append(json.loads(trigger.model_dump_json()))
    _save_raw(data)
    logger.info("Saved SPECTRA trigger %s for %s @ %dms (%s)",
                trigger.id, uri, trigger.timestamp_ms, trigger.action.kind)


def delete(uri: str, trigger_id: str) -> bool:
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
