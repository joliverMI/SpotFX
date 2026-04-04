"""
SpotFX — Gradient profiles CRUD.

Stores named CSS gradient strings in storage/gradients.json.
These are used in the ledfx_effect_param action builder to send
gradient values to LedFX effect parameters.
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/gradients", tags=["gradients"])

_STORE = Path(__file__).parent.parent / "storage" / "gradients.json"


def _load() -> list[dict]:
    if not _STORE.exists():
        return []
    return json.loads(_STORE.read_text(encoding="utf-8"))


def _save(data: list[dict]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class GradientIn(BaseModel):
    name: str
    value: str  # CSS gradient string or hex color e.g. "linear-gradient(90deg, rgb(255,0,0) 0%, rgb(0,0,255) 100%)"


@router.get("")
async def list_gradients():
    return _load()


@router.post("", status_code=201)
async def create_gradient(body: GradientIn):
    data = _load()
    profile = {"id": str(uuid.uuid4()), "name": body.name, "value": body.value}
    data.append(profile)
    _save(data)
    return profile


@router.patch("/{gid}")
async def update_gradient(gid: str, body: GradientIn):
    data = _load()
    for item in data:
        if item["id"] == gid:
            item["name"] = body.name
            item["value"] = body.value
            _save(data)
            return item
    raise HTTPException(status_code=404, detail="Gradient not found")


@router.delete("/{gid}", status_code=204)
async def delete_gradient(gid: str):
    data = _load()
    filtered = [d for d in data if d["id"] != gid]
    if len(filtered) == len(data):
        raise HTTPException(status_code=404, detail="Gradient not found")
    _save(filtered)
