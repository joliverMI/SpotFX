"""THE LIGHT SHOW — phase 1 wire (spectra/services/show_actions.py is the
binding statement for what each action does and how it is put back;
show_output.py for the per-fixture holds).

  GET    /api/light-show/catalogue          every action kind + its params
  GET    /api/light-show/targets            fixtures and categories
  GET    /api/light-show/status             holds, levels, settings changed,
                                            running sets, the gate
  GET    /api/light-show/sets               his library
  POST   /api/light-show/sets               create / update one set
  DELETE /api/light-show/sets/{id}
  POST   /api/light-show/sets/{id}/fire     run it NOW
  POST   /api/light-show/sets/{id}/preview  what it would change (writes nothing)
  POST   /api/light-show/fire               run ad-hoc steps NOW
  POST   /api/light-show/release/{device}   let one fixture go
  POST   /api/light-show/levels/{id}/end    end one Level early
  POST   /api/light-show/end                End show: put the room back

Nothing here takes or releases the room. A fire while SPECTRA does not own
it (or while a preview/camera/night run holds it) returns 409 with the
reason and runs nothing.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from spectra.models.light_show import ActionSet, ShowAction
from spectra.services import show_actions, show_output, show_store

router = APIRouter(prefix="/api/light-show", tags=["spectra-light-show"])


class SetBody(BaseModel):
    id: Optional[str] = None
    name: str
    actions: list[ShowAction] = Field(default_factory=list)
    notes: str = ""


class FireBody(BaseModel):
    actions: list[ShowAction]
    name: str = "Quick action"


async def _broadcast() -> None:
    try:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast({"type": "light_show", **brief()})
    except Exception:                                    # noqa: BLE001
        pass


def brief() -> dict:
    return show_actions.brief()


@router.get("/catalogue")
async def get_catalogue():
    return show_actions.catalogue()


@router.get("/targets")
async def get_targets():
    return show_output.list_targets()


@router.get("/status")
async def get_status():
    return {**show_actions.status(), **{"output": show_output.status()},
            "brief": brief()}


@router.get("/sets")
async def list_sets():
    out = []
    for s in show_store.list_sets():
        out.append({**s.model_dump(),
                    "problems": show_actions.validate_set(s.actions),
                    "conflicts": show_actions.conflicts(s.actions)})
    return {"sets": out}


@router.post("/sets")
async def upsert_set(body: SetBody):
    data = body.model_dump()
    if not data.get("id"):
        data.pop("id", None)
    try:
        s = show_store.put_set(ActionSet(**data))
    except show_store.SetNameTaken as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    # Saved even with problems — a half-built set is his to finish — but the
    # problems travel with it so the editor shows them.
    return {**s.model_dump(), "problems": show_actions.validate_set(s.actions),
            "conflicts": show_actions.conflicts(s.actions)}


@router.delete("/sets/{set_id}")
async def remove_set(set_id: str):
    if not show_store.delete_set(set_id):
        return JSONResponse(status_code=404, content={"detail": "no such set"})
    return {"deleted": set_id}


def _gate_or_none() -> Optional[JSONResponse]:
    reason = show_output.refusal()
    if reason:
        return JSONResponse(status_code=409, content={
            "detail": f"The Light Show is standing down: {reason}",
            "reason": reason})
    return None


@router.post("/sets/{set_id}/fire")
async def fire_set(set_id: str):
    s = show_store.find_set(set_id)
    if s is None:
        return JSONResponse(status_code=404, content={"detail": "no such set"})
    if (blocked := _gate_or_none()) is not None:
        return blocked
    try:
        run = await show_actions.fire_set(s.id)
    except show_actions.ActionError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    await _broadcast()
    return run


@router.post("/sets/{set_id}/preview")
async def preview_set(set_id: str):
    s = show_store.find_set(set_id)
    if s is None:
        return JSONResponse(status_code=404, content={"detail": "no such set"})
    return {"set": s.name, "steps": show_actions.preview(s.actions),
            "refusal": show_output.refusal()}


@router.post("/fire")
async def fire_actions(body: FireBody):
    if not body.actions:
        return JSONResponse(status_code=400, content={"detail": "no steps"})
    if (blocked := _gate_or_none()) is not None:
        return blocked
    run = await show_actions.fire(body.actions, name=body.name, source="button")
    await _broadcast()
    return run


@router.post("/release/{device_id}")
async def release_device(device_id: str, fade_ms: int = show_output.DEFAULT_RELEASE_FADE_MS):
    result = show_output.release_device(device_id, fade_ms)
    await _broadcast()
    return result


@router.post("/levels/{level_id}/end")
async def end_level(level_id: str):
    if not show_output.end_level(level_id):
        return JSONResponse(status_code=404, content={"detail": "no such level"})
    await _broadcast()
    return {"ended": level_id}


@router.post("/end")
async def end_show(fade_ms: int = show_output.DEFAULT_RELEASE_FADE_MS):
    result = await show_actions.end_show(fade_ms=fade_ms)
    await _broadcast()
    return result
