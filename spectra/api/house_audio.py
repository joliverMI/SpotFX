"""THE HOUSE AUDIO SEAM FOR ABSORB MUSIC — SpotFX's silence reaches Home
Assistant through here (data/absorb-music-plan/report.md §5 "Where each
piece lives", phase 2).

  GET  /api/house-audio          {"configured": bool,
                                  "snap_volume": {"ok", "value", "detail"},
                                  "sleeping":    {"ok", "value", "detail"}}
                                 two READS: input_number.snap_volume and
                                 input_boolean.sleeping
  PUT  /api/house-audio/volume   {"volume": 0..100} → script.music_volume_set,
                                 SNAPPED (ease 0)

WHY SPECTRA FRONTS IT. The plan put the client in SpotFX itself, on the
`HOME_ASSISTANT_TOKEN` already in SpotFX's .env, and said "verify that token
first, else front it with one SPECTRA route". It was verified (one read-only
`GET /api/`, 2026-10-20): it is the `.env.template` placeholder and Home
Assistant answers 401. SPECTRA already holds a working, River-provisioned
token (`SPECTRA_HA_URL` / `SPECTRA_HA_TOKEN`, spectra/services/ha_client.py),
so the volume goes through here — and through `ha_volume_ease.set_absolute`,
the ONE owner of snap_volume ramps, which STOPS any Light Show ramp in flight
before it writes: absorb's 0 can never be overwritten by a ramp's next step.

NARROW ON PURPOSE: two named entities to read, one script to call, a volume
clamped to 0-100. No other Home Assistant service is reachable through it —
the Light Show's own volume step can already set this same number, so this
adds no capability the network did not already have.

Unconfigured SPECTRA (no SPECTRA_HA_URL) answers `configured: false` and the
reads `ok: false`; SpotFX treats that exactly as Home Assistant being
unreachable — the window does not open, because there would be no silence
to prove.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/house-audio", tags=["house-audio"])

SNAP_VOLUME_ENTITY = "input_number.snap_volume"
SLEEPING_ENTITY = "input_boolean.sleeping"


def _reading(st, parse) -> dict:
    if not st.ok:
        return {"ok": False, "value": None, "detail": st.detail}
    try:
        return {"ok": True, "value": parse(st.state), "detail": ""}
    except (TypeError, ValueError):
        return {"ok": False, "value": None,
                "detail": f"unreadable state {st.state!r}"}


def _on_off(state: str) -> bool:
    s = str(state).strip().lower()
    if s == "on":
        return True
    if s == "off":
        return False
    raise ValueError(state)


@router.get("")
async def get_house_audio() -> dict:
    from spectra.services import ha_client
    volume = await ha_client.get_state(SNAP_VOLUME_ENTITY)
    sleeping = await ha_client.get_state(SLEEPING_ENTITY)
    return {"configured": ha_client.configured(),
            "snap_volume": _reading(volume, float),
            "sleeping": _reading(sleeping, _on_off)}


class VolumeBody(BaseModel):
    volume: int = Field(..., ge=0, le=100)


@router.put("/volume")
async def put_volume(body: VolumeBody) -> dict:
    from spectra.services import ha_volume_ease
    result = await ha_volume_ease.set_absolute(float(body.volume), ease_s=0.0)
    ha: Optional[object] = result.ha
    ok = bool(getattr(ha, "ok", False))
    return {"ok": ok, "status": getattr(ha, "status", "failed"),
            "http_status": getattr(ha, "http_status", None),
            "detail": result.detail if ok else (getattr(ha, "detail", "") or result.detail)}
