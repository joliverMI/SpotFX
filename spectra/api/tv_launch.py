"""THE "ONE TAP" API (data/tv-display-plan/plan.html PR 1.6) —
`spectra/services/tv_launch.py`'s module docstring is the binding
statement. Three routes: the configured setting (read/partial-write) and
the one action every button/step/Sonic call funnels through."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from spectra.services import tv_launch

router = APIRouter(tags=["spectra-tv-launch"])


@router.get("/api/tv/launch-config")
async def get_launch_config() -> dict:
    return tv_launch.load_config().as_dict()


@router.put("/api/tv/launch-config")
async def put_launch_config(body: dict[str, Any] = Body(default={})) -> dict:
    try:
        cfg = tv_launch.apply_patch(body)
    except tv_launch.TvLaunchPatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return cfg.as_dict()


@router.post("/api/tv/put-on-tv")
async def post_put_on_tv(body: dict[str, Any] = Body(default={})) -> dict:
    """The one action — the Jukebox page's "Put on the TV" button calls
    this directly; a Light Show HA step and Sonic's `put_on_tv` op both
    call `tv_launch.put_on_tv()` in-process instead (no reason to hop
    through HTTP when they already run in this same process)."""
    script_entity = (body.get("script_entity") or None) if isinstance(body, dict) else None
    result = await tv_launch.put_on_tv(script_entity)
    return result.as_dict()
