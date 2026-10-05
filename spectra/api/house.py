"""HOUSE LIGHTING — the wire (spectra/services/house.py is the binding
statement for what a mode does; spectra/models/house_mode.py for its shape).

  GET    /api/house/modes          his modes + every Home Assistant alias
  POST   /api/house/modes          create / update one mode
  DELETE /api/house/modes/{id}
  GET    /api/house/mode           which mode, set by whom, what it is doing
                                   (the same payload as engine status's
                                   `lighting` key)
  POST   /api/house/mode           select a mode — THE call Home Assistant
  PUT    /api/house/mode           makes, on Spectra's own port 8010:
                                     {"ha_mode": "Evening", "source": "ha"}
                                   or by name/id: {"mode": "Evening"}
                                   or clear: {"clear": true}
  GET    /api/house/targets        fixtures, categories, Hue areas

Selecting a mode is idempotent (the same value again is a no-op, so HA's
5-minute re-assert is a cheap heartbeat) and always 200 with a `status`
word: applied / unchanged / held_manual / unmapped / cleared. An unknown
mode NAME is 404 — that is a typo in a request, not a heartbeat. Nothing
here takes or releases the room: a mode set while the room is not
SPECTRA's is recorded and applies when SPECTRA holds it.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from spectra.models.house_mode import HouseMode
from spectra.services import house, house_store

router = APIRouter(prefix="/api/house", tags=["spectra-house"])


class ModeRequest(BaseModel):
    mode: Optional[str] = None
    ha_mode: Optional[str] = None
    source: str = "spectra"
    glide_s: Optional[float] = None
    clear: bool = False


def validate_mode(mode: HouseMode) -> tuple[list[str], list[str]]:
    """(problems, warnings). A problem refuses the save: a scene, colour
    set or category that does not exist would make the mode silently do
    nothing. A fixture or Hue area the LIVE room does not show is only a
    warning — it may be outside today's take, or the room may be released."""
    from spectra.services import color_sets, scene_store
    problems: list[str] = []
    warnings: list[str] = []
    for p in mode.scenes:
        if scene_store.get_by_id(p.scene_id) is None:
            problems.append(f"no scene {p.scene_id!r}")
    for p in mode.color_sets:
        if color_sets.get_by_id(p.card_id) is None:
            problems.append(f"no colour set or group {p.card_id!r}")
    try:
        from fx import device_model
        cats = {c.get("name") for c in device_model.list_categories()
                if isinstance(c, dict)}
    except Exception:                                    # noqa: BLE001
        cats = None
    from spectra.services import show_output
    host = show_output._host()
    for i, h in enumerate(mode.fixtures, 1):
        if h.target.kind == "category" and cats is not None and h.target.id not in cats:
            problems.append(f"fixture setting {i}: no category {h.target.id!r}")
        if h.target.kind == "fixture" and host is not None and h.target.id not in host.devices:
            warnings.append(f"fixture setting {i}: {h.target.id!r} is not in the live room")
        if (h.level is None and h.motion is None and h.fps is None and not h.off):
            warnings.append(f"fixture setting {i} sets nothing")
    areas = [lk.area for lk in mode.hue]
    if len(areas) != len(set(areas)):
        problems.append("a Hue area appears twice")
    if host is not None:
        hue_ids = {d for d in host.devices
                   if getattr(host.devices.get(d), "type", None) == "hue"}
        for a in areas:
            if a != "*" and a not in hue_ids:
                warnings.append(f"Hue area {a!r} is not in the live room")
    return problems, warnings


@router.get("/modes")
async def get_modes() -> dict:
    modes = house_store.list_modes()
    aliases = {a: m.name for m in modes for a in m.ha_aliases}
    return {"modes": [m.model_dump() for m in modes], "aliases": aliases,
            "current_mode_id": house_store.state().mode_id}


@router.post("/modes")
async def post_mode(body: dict):
    try:
        mode = HouseMode(**body)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                                for e in exc.errors())})
    problems, warnings = validate_mode(mode)
    if problems:
        return JSONResponse(status_code=422, content={"detail": "; ".join(problems),
                                                      "problems": problems})
    try:
        saved = house_store.put_mode(mode)
    except house_store.ModeConflict as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    if saved.id == house_store.state().mode_id:
        await house.tick()       # an edit to the live mode lands now
    return {"mode": saved.model_dump(), "warnings": warnings}


@router.delete("/modes/{mode_id}")
async def delete_mode(mode_id: str):
    was_current = house_store.state().mode_id == mode_id
    if not house_store.delete_mode(mode_id):
        return JSONResponse(status_code=404, content={"detail": "no such mode"})
    out: dict = {"deleted": mode_id}
    if was_current:
        res = await house.set_mode(clear=True, source="spectra")
        out["cleared"] = True
        out["lighting"] = res["lighting"]
    return out


@router.get("/mode")
async def get_mode() -> dict:
    return house.status()


async def _select(body: ModeRequest):
    res = await house.set_mode(mode=body.mode, ha_mode=body.ha_mode,
                               source=body.source, glide_s=body.glide_s,
                               clear=body.clear)
    if res.get("status") == "unknown_mode":
        return JSONResponse(status_code=404, content={"detail": res["reason"], **res})
    return res


@router.post("/mode")
async def post_select(body: ModeRequest):
    return await _select(body)


@router.put("/mode")
async def put_select(body: ModeRequest):
    return await _select(body)


@router.get("/targets")
async def get_targets() -> dict:
    from spectra.services import ambient, show_output
    out = show_output.list_targets()
    try:
        out["hue_areas"] = await ambient.list_groups()
    except Exception:                                    # noqa: BLE001
        out["hue_areas"] = []
    return out
