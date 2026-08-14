"""Durable fire-history counter — the smallest honest record of what
SPECTRA actually fired. Owner-scoped deliberately: a counter, not
analytics — no event log, no UI beyond the read endpoint (spectra/api/
fire_history.py).

Hooked at the four existing choke points, each its own bucket keyed by the
dimension that identifies "what fired":
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

Storage: storage/spectra/fire_history.json, same atomic tmp+replace
discipline as room_controls.py. Bounded by construction: one entry per key
ever seen (counts + first/last-fire ms), never one row per fire.

record() is fire-and-forget from a caller's point of view: it never raises
(a broken counter must never break a live fire) and writes synchronously —
call volume here is a handful of fires per song, not a hot loop, so no
write-behind batching is needed to keep this cheap.
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

BUCKETS = ("scenes", "responses", "color_sets", "triggers")


def _empty() -> dict:
    return {b: {} for b in BUCKETS}


def _load() -> dict:
    path = config.FIRE_HISTORY_FILE
    if not path.exists():
        return _empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty()
    data = _empty()
    for b in BUCKETS:
        if isinstance(raw.get(b), dict):
            data[b] = raw[b]
    return data


def _save(data: dict) -> None:
    path = config.FIRE_HISTORY_FILE
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
        data = _load()
        entry = data[bucket].get(key)
        if entry is None:
            entry = {"count": 0, "first_fire_ms": now_ms, "last_fire_ms": now_ms}
        entry["count"] += 1
        entry["last_fire_ms"] = now_ms
        data[bucket][key] = entry
        _save(data)
    except Exception:
        logger.exception("fire-history record failed: %s/%s", bucket, key)


def load_all() -> dict:
    return _load()
