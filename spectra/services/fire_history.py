"""Durable fire-history record — the smallest honest record of what
SPECTRA actually fired. Owner-scoped deliberately: no UI beyond the two
read endpoints (spectra/api/fire_history.py). Two surfaces, one module,
hooked at the same four existing choke points:

  COUNTS (record()/load_all(), GET /api/fire-history) — cheap durable
  per-key totals: count + first/last-fire ms. This is the whole of the
  original ask; kept exactly as scoped.

  SHOW LOG (append_show_log()/load_show_log(), GET /api/show-log) — the
  foundation for the owner's feedback sessions: a played show must be
  reconstructable as a timeline afterwards. One entry per fire (wall time,
  song uri + position_ms, and the event's own detail), bounded by a hard
  entry cap with oldest-first eviction on write — "size-based rotation"
  realized as an entry-count cap rather than a measured byte threshold,
  because it is exactly as bounded and needs no extra bookkeeping (see
  SHOW_LOG_MAX_ENTRIES). Never an unbounded log.

Each choke point's bucket is keyed by the dimension that identifies "what
fired" — the same key is used for both the count and the show-log entry:
  scenes       scene_sequencer.fire_scene_by_id, keyed by scene_id — every
               scene fire regardless of origin (sequencer roll, automatic
               transition, or a trigger's fire_scene action all land here,
               since they all route through this one choke point).
  responses    engine.fire_response_event, keyed by event_class.
  color_sets   drift_conductor.apply_set_directly, keyed by the applied
               set's id.
  triggers     trigger_engine's OWN fires, keyed by "{source}:{action_kind}"
               (source: authored/generated) — a narrower, second view of
               "what did THE KEYSTONE itself fire", distinct from the
               scene/response/color_set buckets above which count every
               caller, trigger-originated or not.
  deferred     scene_sequencer.fire_scene_by_id's dwell gate (spectra/
               services/dwell.py, 2026-08-20), keyed by the scene id that
               WOULD have fired — the interim behaviour for a scene change
               requested while the active scene's own minimum dwell hasn't
               elapsed: the room holds and fires the current scene's own
               "flare" response at double intensity instead (scene_response.
               ResponseEngine.on_update, a deliberate placeholder — see its
               own docstring), and this is the non-silent record of that
               — {requested_scene_id, remaining_dwell_s, update_result}.
               Without this, a scene with no "flare" response/bands
               declared at all (the same silent-no-op case a genuine flare
               already has) would look indistinguishable from "triggers
               stopped working."

Storage: storage/spectra/fire_history.json (counts) and storage/spectra/
show_log.json (timeline), same atomic tmp+replace discipline as
room_controls.py.

record_fire() is the one call site callers use: fire-and-forget (never
raises — a broken record must never break a live fire), synchronous writes
— call volume here is a handful of fires per song, not a hot loop, so no
write-behind batching is needed to keep this cheap. uri/position_ms are
read from the S2 bridge's live track state when a caller doesn't already
know them (trigger_engine tracks its own playback position and passes it
directly instead).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Optional

from spectra import config

logger = logging.getLogger(__name__)

BUCKETS = ("scenes", "responses", "color_sets", "triggers", "deferred")

# Entry-count cap for the show log — bounded, never unbounded growth. On
# each append, entries beyond this count are dropped oldest-first.
SHOW_LOG_MAX_ENTRIES = 5000


def _empty_counts() -> dict:
    return {b: {} for b in BUCKETS}


def _load_counts() -> dict:
    path = config.FIRE_HISTORY_FILE
    if not path.exists():
        return _empty_counts()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_counts()
    data = _empty_counts()
    for b in BUCKETS:
        if isinstance(raw.get(b), dict):
            data[b] = raw[b]
    return data


def _atomic_write_json(path, data) -> None:
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


def record(bucket: str, key: str, *, now_ms: Optional[int] = None) -> None:
    """Increment one key in one bucket, stamping first/last fire. Never
    raises — a fire-history write failure must never break the fire it's
    recording."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    try:
        data = _load_counts()
        entry = data[bucket].get(key)
        if entry is None:
            entry = {"count": 0, "first_fire_ms": now_ms, "last_fire_ms": now_ms}
        entry["count"] += 1
        entry["last_fire_ms"] = now_ms
        data[bucket][key] = entry
        _atomic_write_json(config.FIRE_HISTORY_FILE, data)
    except Exception:
        logger.exception("fire-history record failed: %s/%s", bucket, key)


def load_all() -> dict:
    return _load_counts()


def _current_track_state() -> tuple[Optional[str], Optional[int]]:
    """The S2 bridge's live uri/position — best-effort only. Callers that
    already track their own playback position (trigger_engine) pass it
    explicitly instead of going through this."""
    try:
        from spectra.services.engine import bridge
        return bridge.track_uri(), bridge.track_position_ms()
    except Exception:
        return None, None


def _load_log() -> list[dict]:
    path = config.SHOW_LOG_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def append_show_log(bucket: str, key: str, detail: Optional[dict] = None, *,
                    uri: Optional[str] = None,
                    position_ms: Optional[int] = None,
                    now_ms: Optional[int] = None) -> None:
    """Append one timeline entry, evicting the oldest past
    SHOW_LOG_MAX_ENTRIES. Never raises."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    try:
        if uri is None and position_ms is None:
            uri, position_ms = _current_track_state()
        log = _load_log()
        log.append({
            "wall_ms": now_ms,
            "uri": uri,
            "position_ms": position_ms,
            "bucket": bucket,
            "key": key,
            "detail": detail or {},
        })
        if len(log) > SHOW_LOG_MAX_ENTRIES:
            log = log[-SHOW_LOG_MAX_ENTRIES:]
        _atomic_write_json(config.SHOW_LOG_FILE, log)
    except Exception:
        logger.exception("show-log append failed: %s/%s", bucket, key)


def load_show_log(uri: Optional[str] = None,
                  since_ms: Optional[int] = None) -> list[dict]:
    log = _load_log()
    if uri is not None:
        log = [e for e in log if e.get("uri") == uri]
    if since_ms is not None:
        log = [e for e in log if e.get("wall_ms", 0) >= since_ms]
    return log


def record_fire(bucket: str, key: str, detail: Optional[dict] = None, *,
                uri: Optional[str] = None,
                position_ms: Optional[int] = None) -> None:
    """The one call site production choke points use: bumps the durable
    count and appends the bounded show-log entry for the same fire."""
    now_ms = int(time.time() * 1000)
    record(bucket, key, now_ms=now_ms)
    append_show_log(bucket, key, detail, uri=uri, position_ms=position_ms,
                    now_ms=now_ms)
