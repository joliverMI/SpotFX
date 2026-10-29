"""GET /api/energy/timeline?uri= — the song's ENERGY timeline (spectra/
services/energy.py is the binding statement): every section in song time
with its loudness on the song's own 0..1 scale and its Energy with the Mark
math. The top bar, Home's audio shape, the Timeline page and the song strip
all draw THIS, so the screen shows the number the engine acts on. The top
bar reads it at the show clock every frame (spectra/web/src/lib/showClock.ts)
— no polling for a value that only changes at a section edge."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from spectra.services import energy

router = APIRouter(prefix="/api/energy", tags=["spectra-energy"])


@router.get("/timeline")
async def get_timeline(uri: str = Query(...)):
    tl = await asyncio.to_thread(energy.timeline, uri)
    if tl is None:
        return {"uri": uri, "status": "unavailable", "sections": [],
                "reason": "This song has not been analysed yet."}
    return {"status": "ok", **tl.as_dict()}
