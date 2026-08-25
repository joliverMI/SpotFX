"""TESTING IN PROGRESS — the room-visibility surface's read/write API
(his ask 2026-08-24; spectra/services/test_session.py has the mechanism
and the three rules it exists to enforce).

  GET  /api/test-session          — {testing: "yes"|"no"|"unknown",
                                     sources[], declared|null, since_ms,
                                     readable}. The bar polls this. Never
                                     guesses: an unreadable store or a
                                     failing auto-source probe reports
                                     "unknown", which the bar SHOWS.
  POST /api/test-session/declare  — {actor, reason, ttl_s}. ttl_s is
                                     MANDATORY (422 without it) and capped
                                     at MAX_TTL_S; re-declaring renews.
                                     This is the surface an external agent
                                     calls before touching his fixtures.
  POST /api/test-session/clear    — drop the declaration early. Never
                                     REQUIRED (the ttl always expires on
                                     its own) — just polite.

Deliberately unauthenticated, like every other route in this app: the
whole point is that anything driving his room can say so in one line."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from spectra.services import test_session

router = APIRouter(prefix="/api/test-session", tags=["spectra-test-session"])


class DeclareRequest(BaseModel):
    actor: str = Field(..., description="Who is testing — a name he can read")
    reason: str = Field(..., description="What is being tested, in one phrase")
    # No default: a declaration without a deadline is exactly the defect
    # this feature exists to prevent (a banner that outlives its testing).
    ttl_s: float = Field(..., gt=0, description=(
        f"Seconds until this declaration expires on its own, capped at "
        f"{test_session.MAX_TTL_S:.0f}s. Re-declare to renew."))


@router.get("")
async def get_test_session():
    return test_session.status()


@router.post("/declare")
async def post_declare(body: DeclareRequest):
    record = test_session.declare(body.actor, body.reason, body.ttl_s)
    return {"declared": record, "status": test_session.status()}


@router.post("/clear")
async def post_clear():
    had = test_session.clear()
    return {"cleared": had, "status": test_session.status()}
