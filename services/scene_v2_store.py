"""SceneV2 CRUD store: storage/scenes_v2.json keyed by scene id.
Mirrors services/color_set_store.py."""
from __future__ import annotations

import json
import logging
from typing import Optional

from config import PROFILES_DIR
from models.scene_v2 import SceneV2

logger = logging.getLogger(__name__)

SCENES_V2_FILE = PROFILES_DIR.parent / "scenes_v2.json"


def _load_raw() -> dict:
    if SCENES_V2_FILE.exists():
        try:
            return json.loads(SCENES_V2_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("scenes_v2.json parse failed: %s", exc)
    return {}


def _save_raw(data: dict) -> None:
    SCENES_V2_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCENES_V2_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_all() -> list[SceneV2]:
    return [SceneV2(**v) for v in _load_raw().values()]


def get_by_id(scene_id: str) -> Optional[SceneV2]:
    raw = _load_raw()
    if scene_id in raw:
        return SceneV2(**raw[scene_id])
    return None


def save(scene: SceneV2) -> None:
    raw = _load_raw()
    raw[scene.id] = json.loads(scene.model_dump_json())
    _save_raw(raw)
    logger.info("Saved SceneV2: %s (%d device entries)", scene.name, len(scene.devices))


def delete(scene_id: str) -> bool:
    raw = _load_raw()
    if scene_id not in raw:
        return False
    del raw[scene_id]
    _save_raw(raw)
    return True
