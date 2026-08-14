"""SPECTRA feedback-session API — Stage 2 (spectra-design-decisions.md
"Feedback-session design requirements"). Three endpoints:

  GET  /api/feedback/mark        MARK button's server half: a fresh
                                  {wall_ms, uri, position_ms} triple read
                                  from the live S2 bridge state. Read-only
                                  — nothing persisted here; the queue itself
                                  lives client-side (localStorage) until
                                  Send, so nudges/notes/reordering/deletes
                                  never round-trip.
  POST /api/feedback/batch       ONE send: the whole locally-queued batch
                                  lands in a single durable record. Body:
                                  {entries: [{id, wall_ms, uri,
                                  position_ms, note}, ...]}.
  GET  /api/feedback?uri=&since= Stage 3 read surface: flattened entries
                                  across every sent batch, optionally
                                  sliced to one song (uri) and/or a
                                  wall-time floor (since, epoch ms) — same
                                  filter shape as GET /api/show-log.

See services/feedback.py for storage, eviction, and capture semantics.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from spectra.services import feedback
from spectra.services.feedback import FeedbackEntry

router = APIRouter(prefix="/api", tags=["spectra-feedback"])


class FeedbackBatchIn(BaseModel):
    entries: list[FeedbackEntry]


@router.get("/feedback/mark")
async def mark():
    return feedback.capture_moment()


@router.post("/feedback/batch")
async def post_batch(body: FeedbackBatchIn):
    batch = feedback.save_batch(body.entries)
    return {"status": "saved", "session_id": batch.session_id,
            "received_ms": batch.received_ms, "count": len(batch.entries)}


@router.get("/feedback")
async def get_feedback(uri: Optional[str] = Query(None),
                       since: Optional[int] = Query(None)):
    return feedback.load_entries(uri=uri, since_ms=since)
