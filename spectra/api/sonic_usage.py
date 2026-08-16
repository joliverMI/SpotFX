"""GET /api/sonic-usage — Sonic's token-usage summary for the review page:
last query, this fixed day period, this fixed week period (both anchored
Monday 22:00 America/New_York, never rolling — see services/sonic_usage.py's
module docstring for the reasoning). Read-only; nothing here writes — usage
is captured at its source in services/settings_agent.py (the "api" backend)
and services/settings_agent_cli.py (the "cli"/subscription backend).
"""
from __future__ import annotations

from fastapi import APIRouter

from spectra.services import sonic_usage

router = APIRouter(prefix="/api", tags=["spectra-sonic-usage"])


@router.get("/sonic-usage")
async def get_sonic_usage():
    return sonic_usage.summary()
