"""SPECTRA show-review API — Stage 3 read surface (spectra-design-
decisions.md "Feedback-session design requirements"): the desk-review view
over a played show, notes pinned against the reconstructed timeline.

  GET /api/review/sessions             every sent feedback batch, newest
                                        first, naming the songs it has
                                        notes for (the session/song picker).
  GET /api/review/timeline?session_id=&uri=
                                        one song's merged timeline within
                                        one session — show-log events +
                                        his notes, ordered by song position.

See services/show_reconstruction.py for the reconstruction rule.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from spectra.services import show_reconstruction

router = APIRouter(prefix="/api/review", tags=["spectra-show-review"])


@router.get("/sessions")
async def get_sessions():
    return show_reconstruction.list_sessions()


@router.get("/timeline")
async def get_timeline(session_id: str = Query(...), uri: str = Query(...)):
    return show_reconstruction.reconstruct(session_id, uri)
