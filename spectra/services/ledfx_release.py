"""Direct external-LedFX REST client for spectra/services/release.py ONLY.

release_room()'s post-release cleanup and verification must reach the
external LedFX service AFTER the ownership record has already moved to
`released` (release() flips it before any cleanup runs — see release.py's
module docstring). Routing that through api.ledfx_client would hit its
ownership gate (_spot_effects_owns(), api/ledfx_client.py:601):
writes_allowed() is strict record equality, so with owner=released every
call there is shed — get_all_virtuals mapped that None to {}, and the
release path silently believed there was nothing to deactivate (merge-scout
two-writers report, 2026-08-13). Bypassing that gate here — rather than
adding an exemption flag inside it — also keeps the import discipline
AGENTS.md promises: nothing under spectra/ imports spot-effects runtime
internals. This mirrors the direct httpx call
spectra/services/handover.py's SpotEffectsSide.verify_active() already
makes to the same URL for the same reason (checking the external service
directly, not writing through the spot-effects app).
"""
from __future__ import annotations

import httpx

from spectra import config

_TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=1.0)


async def get_all_virtuals() -> dict:
    """Raises on failure — callers (release cleanup, post-release
    verification) decide how to treat an unreachable LedFX."""
    async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                 timeout=_TIMEOUT) as client:
        resp = await client.get("/api/virtuals")
        resp.raise_for_status()
        return resp.json() or {}


async def set_virtual_active(virtual_id: str, active: bool) -> bool:
    """PUT /api/virtuals/{id} {"active": bool}. Raises on failure; returns
    True only on a confirmed success body (same contract as
    api.ledfx_client.set_virtual_active)."""
    async with httpx.AsyncClient(base_url=config.ledfx_url(),
                                 timeout=_TIMEOUT) as client:
        resp = await client.put(f"/api/virtuals/{virtual_id}",
                                json={"active": bool(active)})
        resp.raise_for_status()
        return (resp.json() or {}).get("status") == "success"
