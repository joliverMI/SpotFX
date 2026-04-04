"""
SpotFX — Palette CRUD.

Stores named key-to-event mappings in storage/palettes.json.
Each palette maps 5 keyboard keys (q, w, e, r, t) to music event IDs
for rapid trigger placement in the Profile Builder.
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/palettes", tags=["palettes"])

_STORE = Path(__file__).parent.parent / "storage" / "palettes.json"


def _load() -> list[dict]:
    if not _STORE.exists():
        return []
    return json.loads(_STORE.read_text(encoding="utf-8"))


def _save(data: list[dict]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class PaletteIn(BaseModel):
    name: str
    color: str  # hex e.g. "#ff5500"
    keys: dict[str, Optional[str]]  # {"q": event_id|null, ...}


@router.get("")
async def list_palettes():
    return _load()


@router.post("", status_code=201)
async def create_palette(body: PaletteIn):
    data = _load()
    palette = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "color": body.color,
        "keys": body.keys,
    }
    data.append(palette)
    _save(data)
    return palette


@router.patch("/{pid}")
async def update_palette(pid: str, body: PaletteIn):
    data = _load()
    for item in data:
        if item["id"] == pid:
            item["name"] = body.name
            item["color"] = body.color
            item["keys"] = body.keys
            _save(data)
            return item
    raise HTTPException(status_code=404, detail="Palette not found")


@router.delete("/{pid}", status_code=204)
async def delete_palette(pid: str):
    data = _load()
    filtered = [d for d in data if d["id"] != pid]
    if len(filtered) == len(data):
        raise HTTPException(status_code=404, detail="Palette not found")
    _save(filtered)
