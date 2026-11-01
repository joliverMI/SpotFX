"""GET /tv/probe — the TV probe page (spectra/services/tv_probe.py), plus
its three tiny JSON seams: a cheap ping target, the result POST, and the
stored-runs read the page itself renders at the bottom. Deliberately
outside `/api` for the page route (a human opens it in a browser tab, same
convention as `spectra/api/spec.py`); the three data seams are under `/api`
like every other JSON endpoint in this app."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse

from spectra.services import tv_probe

router = APIRouter(tags=["spectra-tv-probe"])


@router.get("/tv/probe", response_class=HTMLResponse)
async def get_probe_page() -> str:
    return tv_probe.render_probe_html()


@router.get("/api/tv/probe/ping")
async def get_probe_ping() -> dict:
    """The probe page's round-trip target — no work beyond the ASGI/HTTP
    hop itself, so what it measures is the hop, not a computation."""
    return {"ok": True}


@router.post("/api/tv/probe/result")
async def post_probe_result(body: dict[str, Any] = Body(...)) -> dict:
    probe_id = str(body.get("probe_id") or "").strip()
    if not probe_id:
        raise HTTPException(422, "probe_id is required")
    row = tv_probe.save_result(probe_id, body)
    return {"stored": True, "probe_id": probe_id, "updated_ms": row["updated_ms"]}


@router.get("/api/tv/probe/results")
async def get_probe_results() -> list[dict]:
    return tv_probe.list_results()
