"""
SpotFX — GIF asset manifest API.

Serves storage/gif_assets.json (written by the gifsmith toolkit; see
.claude/skills/led-gif-assets/SKILL.md) merged with the live LedFX asset
list, so the UI's Dance GIF dropdown can flag assets whose upload is missing.
"""
import json
from pathlib import Path

from fastapi import APIRouter

from api import ledfx_client

router = APIRouter(prefix="/api/gif-assets", tags=["gif-assets"])

_MANIFEST = Path(__file__).parent.parent / "storage" / "gif_assets.json"


@router.get("")
async def get_gif_assets():
    manifest = {"version": 1, "assets": {}}
    if _MANIFEST.exists():
        manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    live_paths = {a.get("path") for a in await ledfx_client.list_assets()}
    assets = []
    for asset_id, entry in sorted(manifest.get("assets", {}).items()):
        assets.append({
            "id": asset_id,
            **entry,
            "uploaded": entry.get("path") in live_paths,
        })
    return {"assets": assets}
