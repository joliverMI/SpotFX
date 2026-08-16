"""GET/PUT/DELETE /api/intensity-scale/mark?uri= — the per-track manual
mark (2026-08-15 ruling): the one way past the 0.75 automatic ceiling.
See spectra/services/intensity_scale_marks.py for the mechanism and
spectra/services/intensity_scale.py for how song_scaling_factor() checks
it first. `uri` is explicit (not "whatever's currently playing") — same
convention as GET/POST /api/triggers?uri= — but in practice this is the
Now-Playing control's own surface, so the frontend always passes the
CURRENTLY playing track's uri and genres are read off the live bridge
(the mark only ever applies to a song he's listening to right now)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from spectra.services import intensity_scale, intensity_scale_marks

router = APIRouter(prefix="/api/intensity-scale", tags=["spectra-intensity-scale"])


class MarkBody(BaseModel):
    factor: float = Field(ge=intensity_scale_marks.MANUAL_MIN,
                          le=intensity_scale_marks.MANUAL_MAX)


def _genres_for(uri: str) -> list[str]:
    from spectra.services.engine import bridge
    return bridge.track_genres() if bridge.track_uri() == uri else []


@router.get("/mark")
async def get_mark(uri: str = Query(...)):
    genres = _genres_for(uri)
    return {
        "uri": uri,
        "mark": intensity_scale_marks.get_mark(uri),
        "auto_factor": intensity_scale.auto_scaling_factor(uri, genres),
        "effective_factor": intensity_scale.song_scaling_factor(uri, genres),
        "manual_min": intensity_scale_marks.MANUAL_MIN,
        "manual_max": intensity_scale_marks.MANUAL_MAX,
    }


@router.put("/mark")
async def put_mark(body: MarkBody, uri: str = Query(...)):
    saved = intensity_scale_marks.set_mark(uri, body.factor)
    return {"uri": uri, "mark": saved}


@router.delete("/mark")
async def delete_mark(uri: str = Query(...)):
    cleared = intensity_scale_marks.clear_mark(uri)
    return {"uri": uri, "cleared": cleared}
