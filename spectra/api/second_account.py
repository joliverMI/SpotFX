"""THE SECOND SPOTIFY ACCOUNT'S SWITCH — the Settings page's toggle, and the
small surface a future Home Assistant switch would use.

  GET /api/second-account   {enabled, state ("on" | "off" | "unreadable"),
                             sentence, detail, changed_at_ms, changed_by,
                             history: [last 5 changes],
                             system_started: the play the system started on
                             the account and hasn't let go of yet, or null}
  PUT /api/second-account   {"enabled": true | false, "source"?} → the same

The Admiral, 2026-11-01: the switch "must be enabled in order for the system
to use the second account in any capacity other than reading info ... a
solid barrier so that the second user doesn't get their music taken from
them by the system". fx/second_account.py is the binding statement: this
route only writes the record SpotFX obeys at every write (its account-B
client asks it before each request leaves, fresh from disk), and the record
ships OFF.

TURNING IT OFF while the system is playing on the account needs nothing
from here: the capture lane reads the switch on every poll, so it ends its
song within a couple of seconds and lets go of it — pausing only the song
it started, on the device it started it on — and leaves the second user's
own playback alone.

SONIC — DELIBERATELY NOT AN OPERATION, read or write. This switch is a
barrier that protects another person's music; it moves only when the
Admiral presses it on the Settings page (or, later, a Home Assistant switch
he wires on purpose). A misheard voice command must never be able to
unlock it, and keeping Sonic out of it entirely — not just its "on" half —
keeps the one writer obvious. Revisit only on his word.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, StrictBool

from fx import second_account

router = APIRouter(prefix="/api/second-account", tags=["second-account"])


class SecondAccountBody(BaseModel):
    enabled: StrictBool
    source: Literal["settings-page", "home-assistant"] = "settings-page"


@router.get("")
async def get_second_account() -> dict:
    return second_account.status()


@router.put("")
async def put_second_account(body: SecondAccountBody) -> dict:
    second_account.set_enabled(body.enabled, by=body.source)
    out = second_account.status()
    if not body.enabled and out["system_started"]:
        out["letting_go"] = ("The hidden player is letting go of the song the system started "
                             "on the second account; it stops within a few seconds.")
    return out
