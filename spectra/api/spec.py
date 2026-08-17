"""GET /spectra/spec — the rendered SPECTRA_SPEC.md page (spectra/services/
spec_viewer.py). Deliberately NOT under /api: this is a page a human opens
in a browser tab, not a JSON data endpoint agents call."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from spectra.services import spec_viewer

router = APIRouter(tags=["spectra-spec-viewer"])


@router.get("/spec", response_class=HTMLResponse)
async def get_spec() -> str:
    return spec_viewer.render_spec_html()
