"""SPECTRA feedback-session store — Stage 2 of the owner's feedback
sessions (spectra-design-decisions.md "Feedback-session design
requirements", corr=ba48fb2d1b706f55 + 2ee17dea7df411d7). His two binding
requirements:

  MARK-THEN-NUDGE   a mark captures wall time + song uri + song position at
                     the moment he reacts; +/-1s (and +/-5s) nudges correct
                     the captured position before he types a note. The
                     queue itself — the marks, their nudges, and their
                     notes — lives entirely CLIENT-SIDE (localStorage) so
                     it survives a reload; see
                     spectra/web/src/feedback/FeedbackPage.tsx. This module
                     is only the MARK button's server-side half
                     (capture_moment) plus the durable record of whatever
                     the client eventually sends.
  BATCH SEND        marks/notes accumulate locally through a whole show and
                     leave in ONE batch on Send — never a mid-show
                     round-trip. save_batch() is that one write.

  capture_moment()   a fresh {wall_ms, uri, position_ms} triple read from
                     the S2 bridge's live track state — never raises;
                     degrades to uri/position_ms=None when the bridge is
                     down (same posture as fire_history's own
                     _current_track_state, duplicated rather than shared
                     so the two stores stay independent).
  save_batch()       persists one Send press as one batch record, keyed by
                     its own session_id + received_ms. Raises on write
                     failure — unlike fire_history's fire-and-forget choke
                     points, a feedback send is a direct user action and
                     the frontend needs to know it didn't land, so the
                     local queue stays intact for a plain retry.
  load_entries()     flattened, uri/since-filterable view across every
                     sent batch — the Stage 3 read surface
                     (GET /api/feedback?uri=&since=), same filter shape as
                     fire_history.load_show_log.

Storage: storage/spectra/feedback.json, one JSON list of batch records,
atomic tmp+replace (same discipline as fire_history.py/room_controls.py).
Bounded like the show log — FEEDBACK_MAX_ENTRIES, oldest whole batch
evicted first on write, the just-sent batch itself never evicted — never
unbounded growth.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field

from spectra import config

logger = logging.getLogger(__name__)

# Entry-count cap across all stored batches — bounded, never unbounded
# growth (mirrors fire_history.SHOW_LOG_MAX_ENTRIES). Feedback-session
# volume is far lower (a handful of marks per show) so this is a generous
# ceiling, not an expected steady state.
FEEDBACK_MAX_ENTRIES = 5000


class FeedbackEntry(BaseModel):
    id: str = Field(min_length=1)
    wall_ms: int = Field(ge=0)
    uri: Optional[str] = None
    position_ms: Optional[int] = Field(default=None, ge=0)
    note: str = Field(default="", max_length=4000)


class FeedbackBatch(BaseModel):
    session_id: str
    received_ms: int
    entries: list[FeedbackEntry]


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


def _load_batches() -> list[dict]:
    path = config.FEEDBACK_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def capture_moment() -> dict:
    """The MARK button's server-side half: a fresh wall_ms/uri/position_ms
    triple read from the S2 bridge's live track state. Never raises."""
    now_ms = int(time.time() * 1000)
    uri, position_ms = None, None
    try:
        from spectra.services.engine import bridge
        uri, position_ms = bridge.track_uri(), bridge.track_position_ms()
    except Exception:
        logger.exception("feedback capture: bridge read failed")
    return {"wall_ms": now_ms, "uri": uri, "position_ms": position_ms}


def save_batch(entries: list[FeedbackEntry]) -> FeedbackBatch:
    """Persist one Send press as one durable batch record."""
    batch = FeedbackBatch(
        session_id=str(uuid.uuid4()),
        received_ms=int(time.time() * 1000),
        entries=entries,
    )
    batches = _load_batches()
    batches.append(json.loads(batch.model_dump_json()))

    total = sum(len(b.get("entries", [])) for b in batches)
    while total > FEEDBACK_MAX_ENTRIES and len(batches) > 1:
        dropped = batches.pop(0)
        total -= len(dropped.get("entries", []))

    _atomic_write_json(config.FEEDBACK_FILE, batches)
    return batch


def load_all_batches() -> list[dict]:
    return _load_batches()


def load_entries(uri: Optional[str] = None,
                 since_ms: Optional[int] = None) -> list[dict]:
    """Flattened feedback entries across all sent batches, each carrying
    its batch's session_id — the Stage 3 read surface."""
    out: list[dict] = []
    for batch in _load_batches():
        session_id = batch.get("session_id")
        for entry in batch.get("entries", []):
            if uri is not None and entry.get("uri") != uri:
                continue
            if since_ms is not None and entry.get("wall_ms", 0) < since_ms:
                continue
            out.append({**entry, "session_id": session_id})
    return out
