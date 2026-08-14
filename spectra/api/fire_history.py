"""SPECTRA fire-history read surface — two endpoints, no UI beyond them
(deliberately scoped out):

  GET /api/fire-history            — the four count buckets (scenes/
                                      responses/color_sets/triggers), each
                                      key -> {count, first_fire_ms,
                                      last_fire_ms}.
  GET /api/show-log?uri=&since=    — the bounded per-fire timeline (wall
                                      time, song uri + position_ms, event
                                      detail), optionally sliced to one
                                      song (uri) and/or a wall-time floor
                                      (since, epoch ms) — the foundation
                                      for reconstructing a played show
                                      afterwards.

See services/fire_history.py for what populates each bucket/entry.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from spectra.services import fire_history

router = APIRouter(prefix="/api", tags=["spectra-fire-history"])


@router.get("/fire-history")
async def get_fire_history():
    return fire_history.load_all()


@router.get("/show-log")
async def get_show_log(uri: Optional[str] = Query(None),
                       since: Optional[int] = Query(None)):
    return fire_history.load_show_log(uri=uri, since_ms=since)
