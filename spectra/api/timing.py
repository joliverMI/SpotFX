"""THE TIMING READ — what SPECTRA currently believes about how far his
sound is running behind.

    GET /api/timing/effects-fire-later        the state block
    GET /api/timing/effects-fire-later/log    the raw series (drift picture)

BOTH ARE READS, AND THERE IS DELIBERATELY NO WRITE HERE. River pushes
nothing into SPECTRA: it PUBLISHES on its own loopback surface and SPECTRA
subscribes (one SSE subscriber for the steps, one 15 s poll for the ramp —
spectra/services/known_buffer.py). An inbound push route was in the first
plan for this and was DROPPED once River's surface was known; do not add
one back without a contract change on River's side, because a second way
in is a second thing that can disagree about the current reading.

Open, like every other read in this app. The two authenticated routes in
SPECTRA (`/api/night-run/{start,abort}`) carry a secret because they are
pushes that START something; a read cannot.
"""
from __future__ import annotations

from fastapi import APIRouter

from spectra.services import known_buffer

router = APIRouter(prefix="/api/timing", tags=["spectra-timing"])


@router.get("/effects-fire-later")
def get_effects_fire_later() -> dict:
    """The state block — the same shape `GET /api/engine/status` carries
    as `known_buffer`, built by the same function so the two can never
    describe his room differently."""
    return known_buffer.state()


@router.get("/effects-fire-later/log")
def get_effects_fire_later_log(limit: int = 500) -> dict:
    """The tail of the raw series SPECTRA has logged, oldest first. This is
    what makes a slowly-ramping buffer and its drains visible over days;
    the state block above is only ever the current instant."""
    return {"readings": known_buffer.read_log(max(1, min(int(limit), 5000)))}
