"""SceneV2 CRUD store: storage/scenes_v2.json keyed by scene id.
Mirrors services/color_set_store.py.

Scene set-filters are per-set only (Scenes UI decision 1): accepted_set_ids
may reference kind="set" Color Sets exclusively — the API rejects group ids
on save, and loading migrates any legacy group reference to the group's
member sets so the UI never holds filter contents it cannot display."""
from __future__ import annotations

import json
import logging
from typing import Optional

from config import PROFILES_DIR
from models.scene_v2 import SceneV2

logger = logging.getLogger(__name__)

SCENES_V2_FILE = PROFILES_DIR.parent / "scenes_v2.json"


def _expand_group_refs(scene: SceneV2) -> SceneV2:
    """Replace any group-card id in accepted_set_ids with the group's member
    set ids (base members; recursive with a cycle guard), preserving order and
    deduplicating. Ids that match no card (deleted sets) are kept verbatim —
    dropping them silently is exactly the trap this migration closes."""
    from services import color_set_store
    if not scene.accepted_set_ids:
        return scene
    cards = {c.id: c for c in color_set_store.list_all()}
    if not any(cards[i].kind == "group" for i in scene.accepted_set_ids if i in cards):
        return scene
    expanded: list[str] = []
    seen: set[str] = set()

    def _add(set_id: str) -> None:
        if set_id in seen:
            return
        card = cards.get(set_id)
        if card is not None and card.kind == "group":
            seen.add(set_id)  # cycle guard only — the group id itself is dropped
            for m in card.members:
                _add(m.color_set_id)
            return
        seen.add(set_id)
        expanded.append(set_id)

    for set_id in scene.accepted_set_ids:
        _add(set_id)
    logger.info("SceneV2 '%s': expanded group refs in set filter %s -> %s",
                scene.name, scene.accepted_set_ids, expanded)
    scene.accepted_set_ids = expanded
    return scene


def group_ids_in_filter(scene: SceneV2) -> list[str]:
    """Group-card ids illegally present in accepted_set_ids (for validation)."""
    from services import color_set_store
    cards = {c.id: c for c in color_set_store.list_all()}
    return [i for i in scene.accepted_set_ids
            if i in cards and cards[i].kind == "group"]


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
    return [_expand_group_refs(SceneV2(**v)) for v in _load_raw().values()]


def get_by_id(scene_id: str) -> Optional[SceneV2]:
    raw = _load_raw()
    if scene_id in raw:
        return _expand_group_refs(SceneV2(**raw[scene_id]))
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
