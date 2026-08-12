"""Talk to the live LedFX instance: asset upload/list, effect push/restore."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from . import DEFAULT_LEDFX_URL

PUSH_STATE = Path(__file__).resolve().parents[2] / "build" / "gifsmith_push_state.json"


def upload_asset(gif_path: str | Path, dest_path: str, base_url: str = DEFAULT_LEDFX_URL) -> dict:
    gif_path = Path(gif_path)
    with gif_path.open("rb") as fh:
        resp = requests.post(
            f"{base_url}/api/assets",
            files={"file": (gif_path.name, fh, "image/gif")},
            data={"path": dest_path},
            timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def list_assets(base_url: str = DEFAULT_LEDFX_URL) -> list[dict]:
    resp = requests.get(f"{base_url}/api/assets", timeout=10)
    resp.raise_for_status()
    return resp.json().get("assets", [])


def gif_frame_count(asset_path: str, base_url: str = DEFAULT_LEDFX_URL) -> int:
    resp = requests.post(
        f"{base_url}/api/get_gif_frames", json={"path_url": asset_path}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()["frame_count"]


def get_active_effect(virtual_id: str, base_url: str = DEFAULT_LEDFX_URL) -> dict | None:
    resp = requests.get(f"{base_url}/api/virtuals/{virtual_id}/effects", timeout=10)
    resp.raise_for_status()
    effect = resp.json().get("effect") or {}
    return effect if effect.get("type") else None


def set_effect(
    virtual_id: str, effect_type: str, config: dict, base_url: str = DEFAULT_LEDFX_URL
) -> dict:
    resp = requests.post(
        f"{base_url}/api/virtuals/{virtual_id}/effects",
        json={"type": effect_type, "config": config},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def clear_effect(virtual_id: str, base_url: str = DEFAULT_LEDFX_URL) -> None:
    requests.delete(f"{base_url}/api/virtuals/{virtual_id}/effects", timeout=10).raise_for_status()


def save_push_state(virtual_id: str, effect: dict | None) -> None:
    PUSH_STATE.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if PUSH_STATE.exists():
        state = json.loads(PUSH_STATE.read_text())
    state[virtual_id] = effect
    PUSH_STATE.write_text(json.dumps(state, indent=2))


def pop_push_state(virtual_id: str) -> dict | None:
    if not PUSH_STATE.exists():
        return None
    state = json.loads(PUSH_STATE.read_text())
    effect = state.pop(virtual_id, None)
    PUSH_STATE.write_text(json.dumps(state, indent=2))
    return effect
